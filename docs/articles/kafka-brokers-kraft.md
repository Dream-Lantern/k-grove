---
id: kafka-brokers-kraft
title: 第 3 章：Broker、Controller 与 KRaft
description: "Broker 承载分区副本并处理客户端请求。某分区的 Leader 负责该分区的主要读写协调，Follower 复制其日志；同一个 Broker 可以是 P0 的 Leader、P1 的 Follower。"
date: '2026-10-25'
updated: '2026-10-29'
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
order: 3
---

# 第 3 章：Broker、Controller 与 KRaft

> 版本基线：Apache Kafka 3.9，固定源码使用 3.9.0；本章重点为 KRaft 模式。Kafka 4.0 的 ZooKeeper 差异单独说明。
>
> 学习目标：分清业务数据、集群元数据和消费组协调三条路径，并理解各自的领导关系与故障条件。

## 1. 先区分四个角色

Broker 承载分区副本并处理客户端请求。某分区的 Leader 负责该分区的主要读写协调，Follower 复制其日志；同一个 Broker 可以是 P0 的 Leader、P1 的 Follower。

Controller（控制器）管理集群元数据及相关状态变更，例如分区领导关系。Group Coordinator（组协调器）负责 Consumer Group（消费组）的协调及位点相关请求，两者职责不同。协调消费组不等于替该组处理每条业务消息。下表中的 ISR（In-Sync Replicas，同步副本集合）表示业务分区中满足同步条件的副本。

| 角色                              | 管理的数据与状态                                                           | 主要请求及作用范围                                                                                                                                |
| --------------------------------- | -------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| Broker（服务节点）                | 本机承载的分区日志、副本状态、已应用的集群元数据                           | 接收客户端连接及协议请求；承载多个业务分区及内部 Topic                                                                                            |
| Partition Leader（分区主副本）    | **某一个分区**的追加顺序、复制进度等                                       | 接收该分区 Produce（生产）写入；默认服务客户端 Fetch（拉取），并服务 Follower（从副本）复制。配置就近副本读取时，部分消费者读取可由 Follower 服务 |
| Active Controller（活动控制器）   | 集群级元数据，例如 Topic、分区副本分配、Leader / ISR 变更、Broker 注册状态 | 生成元数据变更并通过 KRaft 提交；需要控制器处理的部分请求由 Broker 转发，不转发所有业务 Value                                                     |
| Group Coordinator（消费组协调器） | 某些消费组的成员、代际、协调状态及提交位点                                 | 处理组协调、OffsetCommit / OffsetFetch（位点提交/查询）；将相关持久状态保存到它负责的 `__consumer_offsets` 分区                                   |

同一个 Broker 可以是订单 P0 的 Leader、P1 的 Follower，又是库存组的 Coordinator；如果 `process.roles=broker,controller`，该进程还承载 Controller 角色，但仍要区分这些逻辑职责。组协调器通常位于该组对应的 `__consumer_offsets` 分区 Leader 所在 Broker，客户端先用 FindCoordinator（查找协调器）请求定位它。它不负责给订单分区选 Leader，也不执行库存业务。

![Controller 元数据复制、业务日志复制与消费组协调](/assets/notes/kafka/kf-roles-review.svg)

[放大查看角色关系图](/assets/notes/kafka/kf-roles-review.svg)。

图中 Controller 与业务副本的 Fetch 都由跟随方主动发起，数据随响应返回；元数据订阅者也主动获取更新。Controller Quorum（控制器投票集合）复制的是 Metadata Log（元数据日志），业务分区副本集合复制的是订单记录，两者并非同一组节点或同一种提交机制。图中将不同路径分开画出，避免把 `__consumer_offsets`、`__cluster_metadata` 和 `orders` 混成一份日志。

## 2. ZooKeeper 时代与现代消费组 {#_2-zookeeper-时代的笔记如何理解}

早期 Kafka 使用 ZooKeeper 保存和协调部分集群元数据；非常早期消费客户端也把组成员或位点等状态放在 ZooKeeper。这两条历史路线要分别与对应版本的客户端和 Broker 对照。

现代 Kafka 消费组通常通过 Broker 协议协调，提交位点保存在内部 Topic `__consumer_offsets`，名称是复数。客户端使用 Bootstrap Broker 获取元数据，而不是要求业务程序直接连接 ZooKeeper 才能读写消息。

## 3. KRaft 改变了什么

KRaft 把元数据管理整合进 Kafka，通过 Controller quorum 的 Raft 日志维护元数据。部署角色可以区分 Broker 与 Controller。教学用合并角色不等于生产环境应无条件合并：资源争用、故障隔离和维护策略仍需评估。

KRaft 指 Kafka 的 Raft 元数据管理路线，Raft 是一种复制状态机共识协议。它解决多个控制器如何在故障后仍对集群状态形成一致认识的问题。元数据记录描述“P0 的 Leader 是谁”等状态，不保存每条 `OrderCreated` 的 Value。Broker 本地应用这些记录形成 Metadata Image（元数据状态视图），据此服务请求。

### 从选举到元数据应用的完整流程

以下用 3 个有投票权的 Controller C1、C2、C3 演示，属于教学推演。假设使用已正确配置的静态投票集合、网络正常、日志与磁盘无损；多数派为 2。Kafka 3.9 也包含动态 Quorum 相关能力，实际成员管理需核对 `kraft.version` 和部署方式，本例不执行成员增删。

1. **组成 Quorum**：投票节点保存 `__cluster_metadata` 的元数据日志副本。Broker 通常以 Observer（非投票观察者）身份获取日志，不计入控制器选举票数。
2. **选举 Active Controller**：没有可用 Leader 或选举超时后，候选者在新的 Epoch（领导代际）中请求投票。投票需遵循日志新旧等资格检查；获得多数票的候选者成为 Quorum Leader，也承担 Active Controller 职责。不是任意存活节点都能直接自称 Leader。
3. **生成变更**：例如创建 `orders`，请求通过 Broker 转到 Active Controller；控制器校验请求并产生 Topic / Partition 等元数据记录，追加到 Metadata Log。一次操作可以产生多条记录，不保证“一次命令等于一个 Offset”。
4. **Follower Controller 拉取**：C2、C3 发起 Fetch，C1 返回日志；后续 Fetch 中的进度让 C1 知道跟随者已复制到哪里。Raft 不是把业务写入同步广播给所有 Broker。
5. **多数派提交**：在满足当前 Epoch 的提交规则后，Leader 根据投票副本进度推进 High Watermark（高水位，已提交日志的结束边界），使其之前的元数据成为已提交历史。假设本轮有效提交边界从 41 推进到 42，则 Offset 41 被覆盖；42 不是“最后已提交记录的 Offset”。该例还假设已满足新 Leader 建立提交资格等条件，不把简单计数替代完整 Raft 规则。
6. **Broker 获取并应用**：Broker 的元数据获取路径拉取日志，获知已提交边界后按序应用增量，更新本地状态视图及相关组件。落后的节点可能先加载 Snapshot（快照）再追赶日志。提交和所有 Broker 都已应用之间存在传播时间。
7. **Controller 故障切换**：C1 故障后，C2、C3 若仍形成多数派，就可在新 Epoch 选举并恢复控制面。新旧日志按 Epoch / Offset 对齐，未提交尾部可能被截断；已提交历史的安全性依赖 Raft 前提及正确持久化。客户端可能经历超时或需要重试，不能把一次超时等同于操作必定没发生。
8. **保存 Metadata Snapshot**：快照保存某个已提交边界的元数据状态，配合边界之后的日志恢复，避免新节点永远从第一条元数据重放。它也支持旧元数据日志的清理；不是订单日志备份，不包含库存数据库，更不是手动格式化后自动恢复的保证。

### 同名术语在控制面与数据面的区别

控制面（Control Plane）管理集群状态；数据面（Data Plane）承载业务记录读写。两者都使用日志和 Epoch，但要先说明针对哪份日志：

| 术语                                  | Controller 元数据路径                                        | 业务 Partition 路径                                                          |
| ------------------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------------------------- |
| Leader Epoch（领导代际）              | Quorum Leader 的代际，参与投票、复制和日志一致性检查         | 某个业务分区 Leader 的代际，用于识别陈旧领导关系和日志对齐；不是同一个计数器 |
| High Watermark / HW（高水位）         | 由 Raft 投票集合的多数派复制及协议条件推进的已提交边界       | 分区复制的提交边界，基于 ISR 等复制条件推进；不是固定 RF 多数投票            |
| ISR（In-Sync Replicas，同步副本集合） | 不用于描述 Raft 的投票成员；Quorum 有自己的 voters（投票者） | 业务分区中满足同步条件的副本集合，关联 `acks=all` 与 `min.insync.replicas`   |

事务消费者还要区分 LSO（Last Stable Offset，最后稳定位点）：`read_committed` 的可见边界会受未完成事务限制，不能仅凭业务分区 HW 推断所有记录对该消费者都已可见。本章不展开事务协议，见[位点与水位](/articles/kafka-offset-watermarks.html)。

Kafka 3.9 文档同时包含 ZooKeeper 与 KRaft 路线；Kafka 4.0 已移除 ZooKeeper 模式。因此保留 3.9 机制作为本册复盘基线，并把 4.0 的差异单列，不把两种配置拼成一个“通用 server.properties”。

## 4. 两个故障域，两类多数与同步条件

Controller quorum 的可用性与其多数派有关。业务分区的数据可靠性则要看副本分配、ISR、确认策略和选主条件。不能说“Kafka用了 Raft，所以每个业务分区写入都等 RF 的多数票”。

控制面健康，并不代表每个分区都有可用 Leader；反过来，控制面故障时，部分已有读写可能短暂继续，但这也不代表集群能完成后续的所有故障切换。诊断时必须分别检查控制状态和分区状态，不能只看进程是否存活。

### 三类故障的条件推演

以下是故障分析，不执行停机或故障注入。假设 Controller 与 Broker 分离部署，3 个 Controller；订单 P0 副本在 B1、B2、B3，B1 为 Leader，初始 ISR 完整，`acks=all`、`min.insync.replicas=2`，禁止不干净选举，客户端可连接剩余节点。

| 故障                                      | 已有 P0 读写                                                                                                                           | Leader 变更                                                                         | 新元数据操作                                                                                     |
| ----------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ |
| 普通 Broker B1 故障，控制器多数派健康     | 检测与切换期间受影响；选出存活的合格副本并恢复足够 ISR 后可恢复写入。若只是其他分区的 Follower 故障，P0 的影响取决于其 ISR 是否仍足够  | Active Controller 记录新的分区 Leader，客户端刷新元数据；不是等 B1 自己恢复才能换主 | 可继续提交；其他健康分区通常不必一起停止                                                         |
| Active Controller C1 故障，C2/C3 健康     | 若 B1 和业务副本仍健康，已有分区读写可能继续；需要新元数据的请求可能暂时受阻                                                           | C2/C3 选新的 **Quorum Leader**；不因此要求所有订单分区换 Leader                     | 选举与恢复期间可能超时，控制面恢复后继续；已有提交但响应丢失的操作要查询状态                     |
| 3 个 Controller 中 2 个不可用，失去多数派 | 已有健康 Leader 与副本可能继续服务一段时间，但不能承诺长期可用；ISR 变化、额外 Broker 故障、需更新元数据或客户端重新发现都可能暴露阻塞 | 无法提交新的有效领导关系；若 B1 此时再故障，不能依赖控制面完成安全分区切换          | 无法可靠提交新的创建 Topic、分区变更等操作；剩余 Leader 也会按协议超时退出领导状态，需恢复多数派 |

若故障 Broker 同时是库存组 Coordinator，消费组协调和位点提交还会受到其 `__consumer_offsets` 分区恢复影响，即使订单 P0 仍能读取。合并部署下一个进程故障可能同时击中控制面与数据面，不能直接套用上表的单角色故障前提。

## 5. 迁移中的状态、回退与集群验收 {#_5-迁移不是删除一个配置项}

从 ZooKeeper 迁移到 KRaft 涉及版本、元数据迁移状态、回退边界和集群验收。不能在已有数据目录上随意格式化，然后认为会自动恢复原元数据。

读图练习：指出消费者请求位点提交、生产者写 P0、P0 Follower 复制、Controller 元数据同步分别属于哪条路径。能说明这四条路径，就比“所有请求交给 Leader”更接近真实架构。

### 只读观察：Quorum Leader 与业务 Leader

以下 Kafka 3.9 Bash 命令只查询状态。前提是存在可访问的 KRaft 集群以及 `orders` Topic，认证环境应使用相应客户端配置。Topic 不存在或授权不足时会报错，不应为取得输出去格式化数据目录。

```bash
bin/kafka-metadata-quorum.sh \
  --bootstrap-server localhost:9092 \
  describe --status

bin/kafka-topics.sh \
  --bootstrap-server localhost:9092 \
  --describe --topic orders
```

第一个命令的字段按 3.9.0 `MetadataQuorumCommand.handleDescribeStatus()` 核对：

| 字段                   | 应如何阅读                                                                                |
| ---------------------- | ----------------------------------------------------------------------------------------- |
| `ClusterId`            | 集群标识，不是 Topic ID                                                                   |
| `LeaderId`             | 元数据 Quorum Leader 的节点 ID，即 Active Controller；不是 `orders` 的 Leader             |
| `LeaderEpoch`          | Quorum 当前领导代际，不是订单分区的代际                                                   |
| `HighWatermark`        | 元数据日志已提交结束边界，不是订单消费位点                                                |
| `MaxFollowerLag`       | Leader 与最落后的投票副本的日志末端位置之差，不是消费组 Lag，也不包含所有 Observer        |
| `MaxFollowerLagTimeMs` | 按投票副本的追平时间戳计算的差值；缺少必要时间戳时可能为 -1，不能解释成测得的业务处理延迟 |
| `CurrentVoters`        | 当前投票成员的 ID 等信息；具体展示取决于 Quorum 配置和协商能力                            |
| `CurrentObservers`     | 已知的非投票观察者；不参与多数派票数统计                                                  |

第二个命令按 Topic / Partition 展示 `Partition`（分区号）、`Leader`（该业务分区 Leader 的 Broker ID）、`Replicas`（副本分配）、`Isr`（当前同步副本）；还有 Topic ID、分区数、复制因子和配置等摘要。若出现迁移相关的额外字段，应按其版本语义阅读。逐分区检查副本与 ISR，不能只看摘要复制因子。

比较这两条命令的 Leader 时，先问它管理哪份日志。分离部署下 Controller ID 与 Broker ID 可以明显不同；合并部署即使数值恰好相同，也只表示同一节点承担两个职责。保留原始输出与采集时间，连续观察故障后的变化比孤立的一次“进程存活”检查更有意义，但本轮不执行破坏性实验。

## 参考

- [Kafka 3.9 KRaft 运维](https://kafka.apache.org/39/operations/kraft/)
- [Kafka 4.0 KRaft 与 ZooKeeper 差异](https://kafka.apache.org/40/getting-started/zk2kraft/)
- [Kafka 3.9 Distribution：组协调器与消费位点](https://kafka.apache.org/39/implementation/distribution/)
- [Kafka 3.9 Design：业务分区复制、ISR 与提交](https://kafka.apache.org/39/design/design/)
- [KIP-595：元数据 Quorum 的 Raft 协议](https://cwiki.apache.org/confluence/display/KAFKA/KIP-595%3A+A+Raft+Protocol+for+the+Metadata+Quorum)
- [KIP-630：Kafka Raft Snapshot](https://cwiki.apache.org/confluence/display/KAFKA/KIP-630%3A+Kafka+Raft+Snapshot)
- [Kafka 3.9.0 KafkaRaftClient：选举、Fetch、提交与退出领导状态](https://github.com/apache/kafka/blob/3.9.0/raft/src/main/java/org/apache/kafka/raft/KafkaRaftClient.java)
- [Kafka 3.9.0 MetadataQuorumCommand：只读命令及字段计算](https://github.com/apache/kafka/blob/3.9.0/tools/src/main/java/org/apache/kafka/tools/MetadataQuorumCommand.java)
