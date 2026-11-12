---
id: kafka-replication-isr
title: 第 4 章：副本复制、ISR 与故障切换
description: "假设 Topic 的 P0 配置在 Broker A、B、C，复制因子 RF 为 3。这三份是同一个分区的副本，而不是各自保存该分区三分之一的消息。"
date: '2026-10-25'
updated: '2026-10-30'
category: distributed-systems
type: explanation
tags:
  - kafka
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kafka
series: kafka-learning
order: 4
---

# 第 4 章：副本复制、ISR 与故障切换

> 版本基线：Kafka Broker / Java Client 3.9，固定源码为 3.9.0；librdkafka v2.8.0。本文使用常规 ISR 选主模型，不把 Kafka 4.0 的 ELR 能力反推到此模型。
>
> 学习目标：把配置副本、同步副本和可被选为 Leader 的条件分开，理解“有三份副本”并非无条件的三份可靠数据。

## 1. Replica 保存同一分区的日志 {#_1-replica-是日志副本-不是分区的子分片}

假设 Topic 的 P0 配置在 Broker A、B、C，复制因子 RF 为 3。这三份是同一个分区的副本，而不是各自保存该分区三分之一的消息。副本消耗额外存储和网络，换取故障后的接管能力。

Replica（副本）保存同一 Partition（分区）的日志；RF（Replication Factor，复制因子）表示分配的副本数量。Leader（主副本）处理该分区的生产写入并协调复制，Follower（从副本）向 Leader 追赶。RF=3 只说明分配了 A/B/C，不能证明它们此刻都有最新记录。

Leader 接收相应的生产请求，Follower 主动发出 Fetch 拉取复制数据。由于复制存在延迟，三份副本的末端位置不一定始终相同。不能把异步复制描述成每写一条记录，就立即对所有副本进行同步远程调用。

![副本拉取、进度报告、ISR 与故障切换](/assets/notes/kafka/kf-replica-review.svg)

[放大查看复制图](/assets/notes/kafka/kf-replica-review.svg)。图为教学流程，数字见第 2 节的连续时间线。

### 一批记录如何复制到 Follower

1. Producer（生产者）通过元数据找到 P0 的 Leader A，发送 Produce（生产）请求。A 检查身份、角色和适用的写入条件，将记录追加到本地日志。
2. B/C 的副本抓取线程主动发送 Fetch（拉取）请求，请求中带有自己的下一读取位置。拉取便于跟随者按自己的网络、磁盘和批量进度追赶，不要求 Producer 逐台发送，也不是 Leader 对每条记录同步调用两个 Follower。
3. A 返回可复制的批次和相应的高水位信息；B/C 把记录追加到各自本地日志。副本 Fetch 可以取得用于追赶的未提交尾部，不等同于普通消费者的可见范围。
4. B 下一次携带更大 Fetch Offset 的请求，才让 A 得知 B 已经追加到哪里。A 发送上一轮响应成功，不足以证明 B 已写入该批次；这里也不是 B 返回一条额外的 Produce ACK。
5. A 在 `Partition.updateFollowerFetchState()` 中更新已知进度，评估 ISR 变化及 HW 推进；等待复制的 Produce 请求据此继续完成。ISR 更新还要与 Controller 协调，不能把本地决定直接当作已经生效的集群状态。

网络排队、批次等待、Follower 磁盘写入、线程调度和资源争用都能形成复制延迟。延迟影响追赶速度和写入确认等待，但“暂时少几条记录”不是自动退出 ISR 的消息条数阈值。

## 2. ISR 随复制进度动态变化 {#_2-isr-是动态资格-不是固定数量}

ISR 表示符合相应同步要求的副本集合，包含 Leader。副本长期跟不上或失去适用连接条件时，可以离开 ISR；恢复并追上后，可按协议重新加入。RF 是分配数量，ISR 是运行时状态，两者不能互换。

ISR 的全称是 In-Sync Replicas（同步副本集合）。它解决的是哪些副本具有同步资格、应参与相应复制条件与常规故障接管的问题，并不要求每个瞬间每个成员的日志末端完全相等。

按落后消息条数判断等旧参数需结合历史版本理解。观察现代副本恢复时，除了 Offset 进度，还要核对对应版本的同步判断、连接状态和配置机制。

### 时间阈值与重新加入条件

Kafka 3.9 的 `replica.lag.time.max.ms` 是 Broker 级复制滞后时间配置，默认 30000ms。`Replica.updateFetchStateOrThrow()` 根据本轮和上一轮 Fetch 对应的 Leader 末端，维护最近追赶时间 `lastCaughtUpTimeMs`。因此，持续写入时 Follower 不必在每次检查恰好等于 Leader 当前末端，仍可以保持同步资格。

`Partition.getOutOfSyncReplicas()` / `maybeShrinkIsr()` 结合 Leader **已知**的副本状态判定收缩；超过允许的未追赶时间且仍未追上，可能触发移除。检查调度、在途 ISR 更新、Broker 故障与控制器处理会影响生效时刻，不是从某条记录到达起精确倒计时，也不是“差 5 个 Offset 就移除”。

重新加入也不只是“进程恢复”：3.9.0 的 `isFollowerInSync()` 要求 A 已知的 Follower 末端至少达到当前 HW，并达到该 Leader Epoch 的起始 Offset；KRaft 模式还检查副本是否被 fenced（隔离）、是否正在受控关闭，以及 Broker Epoch（服务节点代际）的资格。满足后通过 AlterPartition（分区状态变更）提交 ISR 扩张，完成前还要处理在途状态。Follower 不必在持续写入下瞬时追到最新 LEO 才永远有资格加入。

### A/B/C 三副本时间线

LEO（Log End Offset，日志末端位点）是副本下一次追加的位置；HW（High Watermark，高水位）是分区已提交记录的**结束边界**，本章记录满足 `Offset < HW` 才位于该复制提交范围。下面是教学数据，不是集群采样；固定 RF=3、`min.insync.replicas=2`，初始 A 为 Leader，未启用事务，Leader Epoch 起始位置为 100。表中的 HW 指 A 的 HW，假设未列出的更新已完成。

| 时刻                               | 实际 LEO：A/B/C | A 已知的 B/C 进度 | 已生效 ISR | A 的 HW 与原因                            |
| ---------------------------------- | --------------- | ----------------- | ---------- | ----------------------------------------- |
| T0：全部追平                       | 100 / 100 / 100 | 100 / 100         | A,B,C      | 100；日志下一位置是 100，不是已有记录 100 |
| T1：A 追加 100～104                | 105 / 100 / 100 | 100 / 100         | A,B,C      | 100；尾部尚未复制                         |
| T2：B 先写到 102                   | 105 / 103 / 100 | 100 / 100         | A,B,C      | 100；实际写入和 A 获知有时间差            |
| T3：B 报告 103 并继续追平          | 105 / 105 / 100 | 103 / 100         | A,B,C      | 100；C 仍在 ISR                           |
| T4：A 收到 B 的下一次 Fetch        | 105 / 105 / 100 | 105 / 100         | A,B,C      | 100；C 只是落后，还未完成移除             |
| T5：C 超过滞后条件，收缩已确认     | 105 / 105 / 100 | 105 / 100         | A,B        | 可推进至 105；仍有 2 个 ISR 副本          |
| T6：C 恢复并报告到 103             | 105 / 105 / 103 | 105 / 103         | A,B        | 105；C 尚未达到 HW，不能立即加入          |
| T7：C 本地追加至 105，尚未再报告   | 105 / 105 / 105 | 105 / 103         | A,B        | 105；A 尚不知道 C 已追平                  |
| T8：C 报告 105，资格检查及扩张完成 | 105 / 105 / 105 | 105 / 105         | A,B,C      | 105；同步资格恢复                         |

T5 不是“因为 C 差 5 条”，而是额外满足了前述时间和状态条件；ISR 收缩也不是直接把 C 的磁盘日志删除。C 恢复后通过正常复制追赶。

## 3. LEO 与 HW 描述不同边界

LEO 可理解为某副本日志末端的下一位置，因此每份副本都可有自己的 LEO。HW 是复制提交相关的重要边界，不等于 Leader 最新刚接收的数据位置。读侧可见性还可能受事务稳定边界影响，第 14 章再展开。

教学例子：Leader 已追加到下一位置 105，Follower 尚未追上。不能仅看到 Leader 文件里有记录 104，就断言普通消费者一定能够读到，或故障接管后一定保留它。需要结合复制提交状态和选举条件。

### 为什么 HW 不能用一个即时最小值代替

在稳定 ISR、进度已上报且没有其他限制的教学模型中，可以用各同步副本进度的最小值帮助理解复制边界；源码不是无条件计算“所有机器此刻实际 LEO 的 min”。`Partition.maybeIncrementLeaderHW()` 使用 Leader 保存的进度快照、`maximalIsr`（含在途 ISR 扩张等状态的等待集合）及特定追赶副本条件，并且只推进、不随落后的临时观察值任意回退。

**3.9.0 的重要限制**：该方法在 `isUnderMinIsr` 时直接不推进 HW。对于本章 RF=3、minISR=2，如果只剩 A 在 ISR，`acks=1` 仍可能在本地追加后返回成功，但这些新记录不会因此自动越过 HW 变成已提交。这与 `acks=all` 的写入前门槛是两层不同检查，第 5 章继续推演。源码还以 `min(配置 minISR, 分配副本数)` 计算有效 minISR；本章 minISR=2 小于 RF=3，不涉及超配特例，也不建议依赖该特例设计可靠性。

HW 还要在 Fetch 响应中传播，Follower 本地的 HW 可能暂时落后于 A。不能用一次 A 的 HW 采样替代所有副本的当前状态。LSO（Last Stable Offset，最后稳定位点）是事务读取的另一层边界：`read_committed` 消费者受未完成事务限制，LSO 不超过 HW，且需要过滤已中止事务；`read_uncommitted` 也不是越过 HW 读取未复制尾部。详见[事务与可见性](/articles/kafka-transactions.html)。

### Leader Epoch、追赶与截断

Leader Epoch（分区领导代际）区分 P0 的不同领导任期，帮助副本判断哪段日志属于哪次领导历史。它不是第 3 章 Controller Quorum 的 Epoch，也不是 Producer 幂等使用的 Producer Epoch。

独立教学例子：A 曾本地追加到 LEO=105，但只有 `[0,100)` 已提交；A 故障后，合格副本 B 的 LEO=103 并成为新 Leader。原 A 恢复时，其 103、104 不能仅因曾在磁盘存在就继续作为权威历史；副本根据 Leader Epoch 和日志末端协商对齐，可能截断分歧尾部，再从新 Leader 拉取。未提交尾部可能保留、后来提交，也可能丢弃，取决于实际选主和对齐结果，不能承诺一律保留或一律删除。

## 4. 干净选主与数据风险

常规的干净故障切换会从合格的同步副本中选择新 Leader，以保留已提交的历史。若所有合格副本都不可用，就需要在等待其恢复和使用落后副本接管之间取舍。Unclean leader election 可能提高某些故障下的可用性，却也会引入丢失已确认数据的风险。

这不是“任何一台机器活着，三副本集群就能继续可靠写入”。还要满足控制面、网络、ISR 与 `min.insync.replicas` 等条件。故障模型若包含同机架断电、全部磁盘损坏或操作误删，单纯增加同一故障域的副本无法解决。

### Clean 与 Unclean 的三个故障案例

以下案例共用另一份明确的初始状态：A 为 Leader，LEO A/B/C=105/105/100，HW=105，ISR=A,B；`acks=all`、minISR=2，Controller Quorum 健康，副本存储未损坏，C 未追平。Clean Leader Election（干净选主）从合格 ISR 副本接管；Unclean Leader Election（不干净选主，常称脏选举）允许不在 ISR 的副本参与，改变数据安全前提。

| 案例                                  | 可选 Leader 与 ISR                                      | 数据及消费结果                                                                                                       | 能否满足 minISR=2 写入                                              |
| ------------------------------------- | ------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------- |
| A：只有 A 宕机                        | B 在 ISR，具备接管资格；切换完成后可能暂时只有 B 在 ISR | `[0,105)` 已复制给 B，可在其 HW 恢复/传播及客户端刷新后读取；不包含已损坏磁盘等额外故障                              | 暂时不能完成 `acks=all` 写入，需 C 等副本恢复同步并加入，达到至少 2 |
| B：A/B 都宕机，只剩落后 C，禁止脏选举 | C 不在 ISR，不能仅因存活就安全接管；P0 无可用 Leader    | 读写不可正常服务；等待合格副本恢复，不主动用缺失历史替代已提交日志                                                   | 不能；无 Leader，且没有满足门槛的同步副本                           |
| C：与 B 相同，但显式允许脏选举        | 控制面可能选 C；接管后可能只剩 C 在 ISR                 | C 缺少 100～104，可能丢失此前已确认记录；历史分叉需对齐。已有记录的读取要等新 Leader/HW 初始化，不等于丢失记录能恢复 | 仍不能满足 `acks=all` 的 minISR=2；允许脏选举不会补齐副本或绕过门槛 |

Kafka 3.9 的 `unclean.leader.election.enable` 默认 false，Topic 可覆盖 Broker 默认值。表中的“可选”仍依赖节点状态和控制面完成选举；它不是 Controller Quorum 自己的多数派投票。不要通过开启脏选举掩盖复制故障，也不要把后续版本 ELR（Eligible Leader Replicas，合格领导副本）的条件混入本章案例。

## 5. 从分区可用性到副本恢复的监控 {#_5-副本监控应该如何看}

先区分离线分区、欠复制分区和低于最小同步副本数的分区：它们反映的问题严重程度和受影响操作不同。再关联副本 Fetch 延迟、磁盘与网络压力、Leader 变更以及 ISR 变化。

恢复后不能只确认 Broker 进程重新出现，还应检查副本是否重新同步、分区领导关系是否正常，以及业务能否读写。补副本期间的网络与磁盘流量可能影响正常请求，因此需要一起规划恢复速度和业务容量。

### 只读观察：分区状态与复制指标

下面为 Kafka 3.9 Bash 命令和指标入口，**未执行集群实测**。`orders` 必须已经存在；读取需要相应授权，不创建 Topic、不更改副本或生产集群配置。

```bash
bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --describe --topic orders

# 仅当本机 Broker 已经安全配置 JMX/RMI 端口 9999 时使用；不为此开启公网 JMX。
bin/kafka-run-class.sh org.apache.kafka.tools.JmxTool \
  --jmx-url service:jmx:rmi:///jndi/rmi://localhost:9999/jmxrmi \
  --object-name 'kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions' \
  --one-time true
```

JMX（Java Management Extensions，Java 管理扩展）提供运行时指标。若部署使用认证或不同地址，需按既有安全设置接入；命令不包含虚构的输出。

| 观察项                                                            | 含义与判断                                                                     |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Topic 输出 `Leader / Replicas / Isr`                              | P0 当前 Leader、分配副本和同步集合；不是元数据 Quorum 成员                     |
| `kafka.server:type=ReplicaManager,name=UnderReplicatedPartitions` | 当前 Broker 负责的 Leader 分区中，ISR 数少于分配副本数的数量；不是缺少几条消息 |
| `kafka.server:type=ReplicaManager,name=UnderMinIsrPartitionCount` | 低于有效最小 ISR 的 Leader 分区数；与“欠复制”不是同一个阈值                    |
| `kafka.server:type=ReplicaManager,name=IsrShrinksPerSec`          | ISR 收缩事件速率/计数指标；结合具体分区和滞后原因解读                          |
| `kafka.server:type=ReplicaManager,name=IsrExpandsPerSec`          | ISR 扩张事件速率/计数指标                                                      |

可替换 `--object-name` 分别查询以上指标；跨 Broker 汇总时注意采样时间和 Leader 迁移，避免重复解释同一分区。复制正常时 URP 通常为 0，但单个快照不能证明后续无故障，也不能从 ISR 数量反算所有副本实际字节进度。

## 参考

- [Kafka 3.9 复制设计](https://kafka.apache.org/39/design/design/#replication)
- [Kafka 3.9 监控](https://kafka.apache.org/39/operations/monitoring/)
- [Partition.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/cluster/Partition.scala)：`updateFollowerFetchState`、`maybeShrinkIsr`、`isFollowerInSync`、`maybeIncrementLeaderHW`、`effectiveMinIsr`。
- [Replica.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/cluster/Replica.scala)：`updateFetchStateOrThrow`、`ReplicaState.isCaughtUp`。
- [ReplicaFetcherThread.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/server/ReplicaFetcherThread.scala)：副本抓取和本地追加路径。
- [Kafka 3.9 Broker 配置](https://kafka.apache.org/39/configuration/broker-configs/)：`replica.lag.time.max.ms` 等。
- [JmxTool.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/tools/src/main/java/org/apache/kafka/tools/JmxTool.java)：只读指标工具。

## 联读

共同课程“复制与可靠写入”上半课：[acks/minISR与确认下半课](/articles/kafka-acks-min-isr.html)。两课共用A/B/C三副本例子；[4.0 ELR旁注](/articles/kafka-connect-streams.html)不反推3.9。
