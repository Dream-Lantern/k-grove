---
id: kafka-acks-min-isr
title: 第 5 章：acks、minISR 与可靠性边界
description: "acks=0 不等待 Broker 的生产确认，应用可能无法从该发送结果判断 Broker 是否接受数据。acks=1 等待 Leader 本地追加的相应确认，不等待同样的 Follower 复制条件。"
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
order: 5
---

# 第 5 章：acks、minISR 与可靠性边界

> 版本基线：Kafka Broker / Java Client 3.9，固定实现按 3.9.0；librdkafka v2.8.0。下面的时序和故障场景是教学推演，实验步骤未执行。
>
> 学习目标：解释 RF=3、minISR=2、acks=all 能做到什么，以及超时、断电和副本故障下仍有什么限制。

## 1. acks 的三种确认语义 {#_1-acks-不是任意的-收到-n-个回复}

`acks=0` 不等待 Broker 的生产确认，应用可能无法从该发送结果判断 Broker 是否接受数据。`acks=1` 等待 Leader 本地追加的相应确认，不等待同样的 Follower 复制条件。`acks=all`，也称 `-1`，要求满足当前 ISR 的相应复制确认条件。

这些值有各自的协议含义，不是可随意填写 2、3、4 的计数器。可靠性还取决于副本的运行状态：若允许 ISR 只有 Leader，`all` 也不代表写入了三份副本。

`acks` 是 acknowledgements（确认级别）的配置简称。Leader（主副本）追加数据、Follower（从副本）复制数据和向 Producer（生产者）返回结果是不同动作：

| 配置              | Broker 的生产响应                                                           | Producer 能从结果知道什么                                                 |
| ----------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `acks=0`          | 不发送 Produce 成功响应；部分错误可能表现为连接关闭或客户端本地错误         | 无 Broker 写入确认，也通常拿不到有效日志 Offset；本地发送完成不证明持久化 |
| `acks=1`          | Leader 本地追加后可返回；不等 Follower 达到该批次末端                       | 知道 Leader 接受了记录，不能据此证明已复制提交或立即可消费                |
| `acks=all` / `-1` | 先过最小 ISR 门槛；追加后等待所需提交边界，期间还要处理角色、ISR 变化及超时 | 成功对应本次复制确认条件，不是外部数据库成功或逐副本同步刷盘证明          |

这里的“本地追加”通常是写到文件系统及 Page Cache（操作系统页缓存），不是强制完成 `fsync`（文件同步调用）后才响应。其持久化边界见第 4 节。

### 一次 `acks=all` Produce 的请求时序

沿用第 4 章的 A/B/C：RF（Replication Factor，复制因子）=3，ISR（In-Sync Replicas，同步副本集合）初始为 A/B/C，A 为 Leader，minISR=2，LEO（Log End Offset，日志末端位点）初始为 100。请求含记录 100～104，所需结束边界为 105；以下是独立教学时序。

![Produce 追加、Follower 拉取、确认与未知结果](/assets/notes/kafka/kf-produce-acks-review.svg)

[放大查看确认时序](/assets/notes/kafka/kf-produce-acks-review.svg)。

1. A 接收 Produce，检查 `acks` 及同步副本数量。在可接受条件下追加，A 的 LEO 从 100 变为 105。
2. B/C 主动 Fetch，A 返回记录；B/C 各自追加。Leader 不是把原 Produce 转发给 Follower，再等它们直接给 Producer 回 ACK。
3. 下一轮 Fetch 报告新的进度，A 才能更新已知复制位置。在 ISR 稳定且其他条件满足时，HW（High Watermark，高水位，已提交结束边界）可推进到 105。
4. `DelayedProduce.tryComplete()` 调用 `Partition.checkEnoughReplicasReachOffset(105)`，检查 HW、当前等待集合与有效 minISR等条件。满足后返回成功；角色变化、复制不足或等待超时则走相应错误路径。
5. Producer 收到响应后完成 Future / 回调。若响应在网络中丢失，Broker 可能已经完成复制，而 Producer 仍会超时；图中保留这条“结果未知”分支。

如果 C 长时间落后、**已从 ISR 移除且状态生效**，A/B 仍满足 minISR=2，确认可以按新的适用集合继续。不是初始 RF=3 就永远等 3 个，也不是 ISR=A/B/C 时只取最快两个。等待集合在 ISR 更新过程中有额外状态，详见[副本进度与 HW](/articles/kafka-replication-isr.html)。

## 2. minISR 提供可靠写入门槛

`min.insync.replicas` 配合 `acks=all` 规定所需的最小同步副本条件。它不是指定“只需这些副本回复即可，不用管其他仍在 ISR 的副本”，也不会强制落后副本瞬间追上。

[![RF=3、minISR=2、acks=all 的含义](/assets/notes/kafka/kf-acks.png)](/assets/notes/kafka/kf-acks.png)

教学例子采用 RF=3、minISR=2。当 ISR 为 A、B、C 时，按当前同步集合确认；C 离开后，A、B 仍可能满足门槛。若只剩 A，则应拒绝不能满足门槛的可靠写入，而不是静默降级。操作发生前后 ISR 变化还可能影响返回错误，不能据某次快照推断完整执行历史。

minISR 是 `min.insync.replicas`（最小同步副本数）的简称。这个参数在 Topic 层可覆盖 Broker 默认值；RF 则由分区副本分配决定，不能通过提高 minISR 凭空生成副本。这里的 `acks=all` 也不是 Controller Quorum 那种固定多数派投票。

### RF=3、minISR=2 的状态矩阵

以下假设权限、磁盘空间、记录格式、路由等检查均正常，ISR 状态已经稳定；不包含在途集合变更及客户端自动重试造成的额外请求。表中的成功指该 `acks` 路线对应的结果，不是统一的“可靠投递成功”。

| 分区状态            | `acks=0`                                                                          | `acks=1`                                                        | `acks=all`                                                    |
| ------------------- | --------------------------------------------------------------------------------- | --------------------------------------------------------------- | ------------------------------------------------------------- |
| Leader A，ISR=A/B/C | 请求可被追加，但无 Broker 确认；失败无法完整反馈                                  | A 追加后可成功，不等 B/C；若随后 A 故障且尚未复制，尾部可能丢失 | 过门槛后等待对应复制提交；稳定集合下不能只等任意两个          |
| Leader A，ISR=A/B   | 仍无 Broker 确认，不能从本地发送成功推断复制完成                                  | A 追加即可确认，业务风险仍依复制进度                            | 仍达到 2，等待 A/B 对应的提交；C 不在当前 ISR，不要求先追平 C |
| Leader A，ISR=A     | 可能追加但无确认；3.9.0 中 HW 不会仅因这次追加自动推进                            | 可本地追加并返回成功，但新记录可能停留在 HW 之外                | 写入前即不满足门槛，通常返回 `NOT_ENOUGH_REPLICAS`            |
| 无可用 Leader       | 不能进行正常的分区写入；可能卡在元数据获取/本地超时，不能把 `acks=0` 当成仍可成功 | 无正常 Leader 追加；需刷新元数据、恢复或最终报错                | 同左；minISR 不能代替 Leader 恢复                             |

**3.9.0 源码边界**：`appendRecordsToLeader()` 对 `acks=-1` 做写入前门槛检查；`maybeIncrementLeaderHW()` 在低于有效 minISR 时不推进 HW。因而 `acks=0/1` 可以绕过前一个门槛，却不能保证新记录被提交和消费。原来已在 HW 以内的数据仍有自己的读取条件，不能把“HW 不前进”理解为抹掉既有提交。

## 3. 副本不足、未知结果与应用恢复 {#_3-拒绝写入与丢失数据不是同一个结论}

遇到副本不足相关错误时，应先判断应用需要重试、退避，还是停止接收上游请求，不能只修改 minISR 来消除报错。降低门槛可能恢复写入能力，但也会改变已接受数据的容错条件。

没有收到成功确认，也不一定表示记录没有追加。请求可能已经执行了一部分，只是确认尚未返回；此时重试可能导致重复。可靠性设计需要同时考虑丢失、重复、未知结果和业务恢复，不能用“失败就无限重发”代替状态管理。

### 两种副本不足错误与超时

| 结果                                 | 3.9.0 对应路径                                                                          | 不能据此推断的结论                                                 |
| ------------------------------------ | --------------------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| `NOT_ENOUGH_REPLICAS`                | 本次 `acks=all` 追加前，同步集合低于有效 minISR，被拒绝                                 | 只能说明这次尝试的检查；同一业务事件此前或之后的其他重试可能已写入 |
| `NOT_ENOUGH_REPLICAS_AFTER_APPEND`   | 本地已经追加；延迟确认检查中，所需 HW 已达到，但适用同步集合低于有效 minISR，返回此错误 | 不能说“记录绝对没写入”，更不能把错误当作自动回滚本地日志           |
| `REQUEST_TIMED_OUT` 或客户端交付超时 | 等待、网络或客户端总交付期限耗尽；可能涉及多个尝试                                      | 不能仅凭超时确定记录未追加、未提交或绝对不可见                     |

`AFTER_APPEND` 不是任何一次 ISR 收缩都必定立即返回的错误：需要结合 `checkEnoughReplicasReachOffset()` 的实际条件。若 HW 尚未到所需位置，等待也可能最终超时；若不再是 Leader，又有角色错误路径。客户端还可能把可重试错误隐藏在重试过程中，应用最后看到的结果未必就是第一次尝试的错误。

Producer 幂等机制使用 Producer ID、Producer Epoch（生产者代际）及每分区序列号识别协议重试，降低重复追加与重排风险。它不让超时自动变成成功、不把应用重新构造的所有业务发送去重，也不和外部数据库共享事务。按稳定 `event_id` 管理业务恢复，详细配置见[重试与幂等](/articles/kafka-retries-idempotency.html)。

## 4. 复制确认与介质持久化的区别 {#_4-复制确认不是同步落盘到所有物理介质}

Kafka 利用操作系统页缓存，复制到其他 Broker 和在每份磁盘上完成同步 `fsync` 是不同保证。`acks=all` 不等于每份副本已在响应前同步刷新到持久介质。

### 六条不同的完成边界

| 边界           | 表示完成的动作                                 | 仍未证明什么                                                                 |
| -------------- | ---------------------------------------------- | ---------------------------------------------------------------------------- |
| 本地写入       | Leader 已追加文件数据，相关页可能仍是脏页      | 不证明其他副本已有相同尾部                                                   |
| 复制提交       | HW 推进，记录进入分区复制提交范围              | 不证明每份副本已同步到永久介质                                               |
| Producer 确认  | 客户端收到其 `acks` 路线对应的响应             | 不证明消费已开始；`acks=1` 也不证明提交                                      |
| `fsync` 持久化 | 操作系统要求将文件数据及相关必要状态同步到存储 | 保证仍取决于文件系统、设备及存储是否正确履行持久化契约，不是任意损坏下的备份 |
| Consumer 读取  | 记录满足读取隔离和可见性条件后交给应用         | 不证明库存数据库已经更新                                                     |
| 外部业务成功   | 下游数据库等业务事务完成                       | 不证明消费恢复位点已成功提交                                                 |

Page Cache 缓存文件数据，将应用追加与设备写入解耦；操作系统随后按回写策略刷新脏页。副本复制把风险分散到其他 Broker 的内存、操作系统和存储故障域；`fsync` 强调本机存储同步，它们分别解决不同问题。Topic 的 `flush.messages` / `flush.ms` 影响刷新策略，不能直接改写为“acks=all 每次同步刷三块盘”。

### 四个故障场景

1. **Producer 收到成功**：先确认本次是 `acks=1` 还是 `all`。前者只确认 Leader 追加；后者在本章条件下经过相应复制提交。两者都没有证明库存业务成功，Consumer 也可能在 Producer 获得响应前读取到已提交数据。
2. **副本不足收到错误**：区分追加前拒绝、追加后失败及历次重试；保留事件标识和结果状态，不能盲目判断“删除本地重试记录就安全”。
3. **Broker 写入完成，响应丢失**：记录可能已经复制提交，客户端却返回未知结果；重试要利用协议幂等并保持业务幂等，不编造一次性确定结果。
4. **多个副本确认后共同电源/存储故障**：若它们共享故障域，且相关数据尚未可靠写到持久介质，就存在同时丢失风险；即使已刷新，全部设备损坏也超出单纯 RF 的保证。风险取决于实际设备、缓存和故障隔离条件，不能给出没有实测依据的丢失概率。

因此，需要说明故障假设：独立 Broker 故障、同时断电、存储控制器行为、机架或机房故障，各自带来的风险不同。更频繁地刷盘会改变性能与持久化行为，但无法排除任意硬件故障。不能从教学公式推导出“永不丢失”。

## 5. 一套设置之外还需要什么

检查生产回调、幂等配置、副本跨故障域分布、禁止无意脏选举、监控与演练，以及消费侧提交和外部幂等。Topic 的重要覆盖项应与 Broker 默认值一起核对，不能只看一个服务端配置文件。

三副本中已有两个掉线时，单个剩余副本无法满足 minISR=2 的写入约束。坚持该门槛就需要等待同步副本恢复；改为单副本成功写入，则改变了可用性与容错选择。

### Java 3.9 与 librdkafka v2.8.0 配置对照

以下是指定版本的默认值及作用域，不是生产环境推荐清单；相同参数名也不保证两种客户端实现方式相同。事务配置及显式冲突设置还可能改变有效值。

| 配置                                    | Java Client 3.9 默认                   | librdkafka v2.8.0 默认                                        | 作用域 / 边界                                                                                   |
| --------------------------------------- | -------------------------------------- | ------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `acks`                                  | `all`                                  | `-1`，是 `request.required.acks` 的别名                       | Producer；0/1/all 的协议路线；不是 Broker 全局可靠性开关                                        |
| `enable.idempotence`                    | `true`，存在冲突且未显式启用时可能关闭 | `false`；显式启用后自动调整未覆盖的相关配置，显式不兼容会失败 | Producer；跨语言不可仅复制一个默认假设                                                          |
| `max.in.flight.requests.per.connection` | 5                                      | 1000000；启用幂等时限制为不超过 5，未覆盖时调为 5             | Java 表示相应连接的在途请求；C 是通用连接配置，具体协议还有其他限制                             |
| `retries`                               | 2147483647                             | 2147483647；别名 `message.send.max.retries`                   | Producer；仍受交付期限限制，不代表真的无限等待                                                  |
| `delivery.timeout.ms`                   | 120000ms                               | 300000ms；是 `message.timeout.ms` 的别名                      | 本地交付期限；不能直接当作 Broker 的复制等待超时                                                |
| `request.timeout.ms`                    | 30000ms                                | 30000ms                                                       | Java 的请求响应等待配置；C 这里是 Broker 侧生产确认等待，且依赖 acks 非 0，作用不能仅凭同名等同 |
| `min.insync.replicas`                   | 不属于 Java 客户端参数                 | 不属于 C 客户端参数                                           | Topic 覆盖 / Broker 默认，默认 1；本章显式设置 2                                                |
| RF                                      | 不是客户端 acks 配置                   | 同左                                                          | Topic 分区副本分配；本章显式 3，不代表集群默认创建值                                            |

### 隔离实验：RF=3、minISR=2

**以下配置和命令未运行。** 提供[独立实验 Compose 文件](/examples/kafka-review/rf3-minisr2.compose.yaml)，使用官方 `apache/kafka:3.9.0` 镜像：一个独立实验 Controller，三个 Broker A/B/C（ID 1/2/3），没有对宿主机发布端口。单 Controller 仅用于这次数据副本实验，不验证控制器容错；数据写入专用命名卷，不能指向已有 Kafka 数据目录。

在独立目录保存该文件，以固定实验项目名运行；需要已可用的 Docker Compose、镜像和足够内存。本轮不安装、不启动它，不执行停止真实 Broker 的命令：

```bash
docker compose -p kafka-r2-lab -f rf3-minisr2.compose.yaml up -d

# 等服务就绪后，只在该实验项目创建全新 Topic；固定副本顺序 1:2:3。
docker compose -p kafka-r2-lab -f rf3-minisr2.compose.yaml exec -T broker-a \
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server broker-a:9092 \
  --create --topic orders-r2-lab --replica-assignment 1:2:3 \
  --config min.insync.replicas=2 --config unclean.leader.election.enable=false

docker compose -p kafka-r2-lab -f rf3-minisr2.compose.yaml exec -T broker-a \
  /opt/kafka/bin/kafka-topics.sh --bootstrap-server broker-a:9092 \
  --describe --topic orders-r2-lab

printf '%s\n' 'evt-r2-1' | \
  docker compose -p kafka-r2-lab -f rf3-minisr2.compose.yaml exec -T broker-a \
  /opt/kafka/bin/kafka-console-producer.sh --bootstrap-server broker-a:9092 \
  --topic orders-r2-lab --producer-property acks=all \
  --producer-property enable.idempotence=true \
  --producer-property delivery.timeout.ms=15000 \
  --producer-property request.timeout.ms=5000
```

记录实际版本、Leader/ISR、Producer 标准错误和每轮事件标识。控制台没有打印错误不足以代替应用级 delivery 回调；可另写客户端逐条记录返回结果。后续仅在上面这个新实验项目中按次序操作：

1. 确认 Leader=1、ISR=1/2/3；若实际不符先记录原因，不照抄停机顺序。
2. `docker compose -p kafka-r2-lab -f rf3-minisr2.compose.yaml stop broker-c`，等待描述显示 ISR=1/2，再发送不同事件。预期在 A/B 健康时仍可满足 `acks=all`；可能先有等待或重试，不规定虚构的耗时。
3. 再用同样的限定命令 `stop broker-b`，确认仅 ISR=1，向 A 发新的 `acks=all` 记录。预期客户端重试并最终报告副本不足/交付失败，最后具体错误取决于路径；不能以此推断该业务 ID 的所有历史尝试均未写入。
4. 独立对照 `acks=1` 时必须显式设置 `enable.idempotence=false`；观察本地确认与消费可见性分离，不能把无输出当成验证 HW 的证据。`acks=0` 只用于观察没有生产响应，不作为成功投递测试。
5. `docker compose -p kafka-r2-lab -f rf3-minisr2.compose.yaml start broker-b broker-c`，等待副本追赶与 ISR 恢复，再检查事件与后续写入。已追加但未提交的尾部如何处理，要按实际历史记录，不能预填结论。
6. 实验结束可限定项目 `stop`，保留命名卷用于复查；不要执行 `down -v`、删除卷或格式化数据目录。Leader 失效、脏选举和断电风险在正文做条件推演，不在此实验中追加危险动作。

这个实验验证副本数量与确认门槛，不验证真实库存事务、任意断电安全性或生产环境可用性。Compose 与命令尚待最后统一验证及隔离环境实测。

## 参考

- [Java Producer：acks](https://kafka.apache.org/39/configuration/producer-configs/#acks)
- [Topic：min.insync.replicas 与 flush 配置](https://kafka.apache.org/39/configuration/topic-level-configs/)
- [Partition.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/cluster/Partition.scala)：`appendRecordsToLeader`、`maybeIncrementLeaderHW`、`checkEnoughReplicasReachOffset`。
- [DelayedProduce.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/server/DelayedProduce.scala)：等待完成、超时和结果返回。
- [librdkafka v2.8.0 CONFIGURATION.md](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)：默认值、幂等依赖与超时作用域。
- [ProducerConfig.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/ProducerConfig.java)：Java 默认值及幂等配置冲突处理。
- [Kafka 3.9 官方 Docker 说明](https://kafka.apache.org/39/getting-started/docker/)：镜像及环境配置入口，实验文件是本章教学配置，不是已运行结果。

## 联读

共同课程下半课：[先读RF/ISR与故障切换](/articles/kafka-replication-isr.html)；文件持久化背景见[OS文件与fsync](/articles/os-file-descriptors-persistence.html)。
