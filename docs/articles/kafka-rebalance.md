---
id: kafka-rebalance
title: 第 12 章：Rebalance、心跳与消费协议
description: "成员加入、离开或失效，订阅或分区变化，都可能需要重新计算所有权。Rebalance 的目标是让适用成员继续承担分区，不是把 Broker 的日志文件搬到消费机器，也不是回滚旧消费者已经发出的外部请求。"
date: '2026-10-25'
updated: '2026-10-28'
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
order: 12
---

# 第 12 章：Rebalance、心跳与消费协议

> 版本基线：Kafka Broker 3.9、Java Client 3.9 与 librdkafka v2.8.0。
>
> 学习目标：沿分区撤销、在途任务处理和新所有权建立的过程理解重平衡；分别阅读经典协议、新协议与客户端支持阶段。

## 1. 成员变化触发分区重新分配 {#_1-为什么需要重新分配}

成员加入、离开或失效，订阅或分区变化，都可能需要重新计算所有权。Rebalance 的目标是让适用成员继续承担分区，不是把 Broker 的日志文件搬到消费机器，也不是回滚旧消费者已经发出的外部请求。

因此，交接发生时，旧消费者在线程池中尚未完成的任务，可能与新持有者的任务重叠。组协议能管理分区所有权，但外部系统若没有去重或 fencing，就无法仅凭 group.id 拒绝旧任务延迟到达的写入。

![分区交接与在途工作](/assets/notes/kafka/kf-rebalance.svg)

重平衡（Rebalance）可用一次订单分区交接来理解。假设 C1 原来处理 `review-orders` 的三个分区，C2 加入后将接手其中一个分区：

1. 协调器识别 C2 加入并触发重新分配。原成员正常离开或超时也能触发重分配。
2. 在能通知 C1 的交接中，客户端执行适用的撤销回调。C1 停止向待交接分区派发任务，给在途工作有限的收尾时间。未开始的任务可移除，无法取消的任务用旧所有权标记隔离结果。
3. C1 计算已完成的连续前沿，若仍有权提交则尝试提交。遇到崩溃或长时间失联时，C1 可能没有机会收到撤销通知或完成最后一次提交。
4. C2 获得分区后初始化本地状态，从有效的已提交位点继续。旧任务已经完成但提交未生效时，C2 可能重做同一业务。

这是跨协议的教学框架。Classic Eager 会先撤销整组成员的原分配，Classic Cooperative 只交接需要移动的分区。KIP-848 由协调器逐成员推进增量交接，见本章第 4 节。

## 2. 分别观察组成员存活与业务进度 {#_2-心跳存活与业务推进是两件事}

在 Kafka 3.9 Java Classic 中，心跳（Heartbeat）由客户端后台发送，`heartbeat.interval.ms` 控制预期发送间隔，应小于 `session.timeout.ms`。协调器在会话超时内收不到心跳时移除该成员。`max.poll.interval.ms` 则限制应用两次 `poll()` 之间的间隔。Worker 成功处理记录和连续完成前沿推进也是两件事，后续任务完成时，前沿仍可能被更早的未完成任务挡住。

| 纸面历史                           | 组协议看到什么                          | 业务仍需监测什么                                 |
| ---------------------------------- | --------------------------------------- | ------------------------------------------------ |
| 同步处理阻塞，主线程长时间不再poll | 可能超过max.poll.interval并失去成员资格 | 单条处理时间、恢复与重复窗口                     |
| 主线程持续poll，工作线程卡在数据库 | 消费API仍活跃，可能继续保持成员资格     | 连续完成前沿停滞时间、最老在途任务年龄、有界队列 |

动态成员在客户端检测到 Poll 超时后会尝试离组，即使此前后台仍在发心跳。静态成员（设置 `group.instance.id`）达到 Poll 超时后停止发送心跳，协调器通常等会话超时才重新分配。若主线程持续 Poll 而 Worker 卡住，成员可能保持资格，订单前沿却停在原处。暂停分区期间仍需处理客户端事件。[Java 3.9 max.poll.interval.ms](https://kafka.apache.org/39/configuration/consumer-configs/#max.poll.interval.ms)

配置大超时可以容忍慢任务，却也拉长某些故障恢复窗口。正确方案还包括拆分有界任务、限制在途量、暂停适用分区而持续服务客户端事件，以及确保队列不会无限增长。不要仅以“后台线程还在发心跳”证明业务健康。

## 3. Eager 与 Cooperative 的交接方式和回调 {#_3-eager-与-cooperative-不可混用回调}

Eager 交接可能先撤销完整分配；Cooperative 则采用增量交接，减少不必要的全量停止。两者对回调内分配操作的要求不同，不能直接拼接分别采用这两种方式的示例代码。

| Classic 交接方式                      | 分配器示例                                                          | 教学流程                                                                     |
| ------------------------------------- | ------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| Eager Rebalance（全量撤销式重平衡）   | Java `RangeAssignor` 或 librdkafka `range`                          | 原成员先撤销全部分区，再入组同步完整分配，连最终仍归原成员的分区也会暂停处理 |
| Cooperative Rebalance（协作式重平衡） | Java `CooperativeStickyAssignor` 或 librdkafka `cooperative-sticky` | 可保留无需移动的分区。待转移分区先从原成员撤销，再经后续一轮协调分给目标成员 |

同组要能协商出共同支持的策略。Cooperative 缩小了停顿范围，移动的分区仍有交接和重放窗口。

Java 3.9 的 `ConsumerRebalanceListener` 在消费线程上通知应用，分配由客户端执行。用 `onPartitionsRevoked` 停止派发并尝试提交安全前沿，用 `onPartitionsAssigned` 初始化新增分区，用 `onPartitionsLost` 清理已失去的所有权。应显式实现 Lost 回调，避免默认转调 Revoked 时误走提交路径。

librdkafka v2.8.0 注册 `rd_kafka_conf_set_rebalance_cb()` 后，应用承担相应的分配操作。可用 `rd_kafka_rebalance_protocol()` 判断 Classic 回调的交接方式：

| 回调事件                               | Eager                                | Cooperative                                                    |
| -------------------------------------- | ------------------------------------ | -------------------------------------------------------------- |
| `RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS` | `rd_kafka_assign(rk, partitions)`    | `rd_kafka_incremental_assign(rk, partitions)`                  |
| `RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS` | `rd_kafka_assign(rk, NULL)` 清除分配 | `rd_kafka_incremental_unassign(rk, partitions)` 仅移除回调列表 |

检查分配操作的返回错误。若 `rd_kafka_assignment_lost()` 表明分配已丢失，仍要执行相应的本地撤销操作，但应跳过最后提交。没有自定义回调时库会处理适用的分配操作，业务资源仍由应用管理。

## 4. Kafka 4.0 的新消费协议

Kafka 4.0 的 KIP-848 Consumer 协议进入 GA，分配计算与部分超时配置职责发生变化；Classic 仍存在。不能据服务端 4.0 支持，就断言任意旧客户端已完整支持。

固定到 librdkafka v2.8.0 时，其该协议仍标为 Early Access，缺少部分能力。因此本册 C 路线保持 Classic，不推荐直接把 `group.protocol=consumer` 加进旧示例当作升级完成。未来升级需重新核对客户端发布说明、回调契约和兼容矩阵。

Classic 依赖组内 Leader 计算分配，并通过 JoinGroup 和 SyncGroup 同步。新协议把目标分配放到协调器，移除组内 Leader。成员通过 ConsumerGroupHeartbeat 上报订阅和持有状态，协调器用成员 epoch 跟踪状态，逐步下发分配变更。需要移交的分区先由旧持有者释放，其他成员无需等一次全组同步才能继续工作。

Kafka 4.0 的新协议需要支持它的客户端显式启用 `group.protocol=consumer`。服务端使用 `group.consumer.heartbeat.interval.ms` 和 `group.consumer.session.timeout.ms` 控制心跳与会话超时，应用仍受客户端 `max.poll.interval.ms` 约束。分配器从服务端支持的列表中选择，可通过 `group.remote.assignor` 请求相应策略。4.0 文档支持空组离线迁移，在线转换受 Classic 分配器是否嵌入自定义元数据等条件约束。

v2.8.0 的 Early Access 文档仅列出空组离线升级。该版本启用新协议且设置 `group.remote.assignor` 时，自定义回调必须用增量分配 API。该版本文档还描述了按原有 `partition.assignment.strategy` 决定回调 API 的过渡兼容路径。

## 5. 交接中的派发停止、完成前沿与提交 {#_5-交接时怎样处理位点}

停止向被撤销分区派发新工作，识别已完成的连续区间，有界等待或取消剩余任务，并按仍然有效的所有权条件提交。所有权已经丢失时，不能把旧实例的提交成功视为必然。

写数据库的任务无法取消时，需要通过业务 ID 幂等或下游 fencing 控制交接期间的重叠效果。仅调用 pause 不会撤回已经发到外部系统的请求，也不会替你完成线程池排空。

订单写库的教学时序如下。假定 P0 的已提交位置仍是 100：

| 时刻 | C1                                     | C2 / 数据库               |
| ---- | -------------------------------------- | ------------------------- |
| T0   | 取到 Offset 100，向数据库发出写入请求  | 请求仍在执行              |
| T1   | 失去 P0 所有权，隔离迟到的 Worker 结果 | C2 接管 P0，从 100 恢复   |
| T2   | 旧请求尚未返回                         | C2 重做同一订单事件并写库 |
| T3   | 旧请求延迟完成                         | 两次写入均可能生效        |

如果两次写入都触发扣减或追加，外部系统可能产生两份效果，Kafka 位点只控制恢复位置。幂等性（Idempotency）可用稳定的订单事件 ID 实现，例如在同一个数据库事务内写入带唯一约束的处理记录和业务变更。一个订单允许多个事件时，去重键应区分这些事件。若业务需要拒绝已经失去所有权的写入，可在下游维护单调的 Fencing Token，并在同一事务中校验它再写入。进程内的所有权标记只拦截迟到结果，数据库必须执行自己的检查。

工程上的交接可以按这个顺序做：停止派发受影响分区，取消还在队列里的任务，给在途工作预留有限收尾时间，仍有权时提交前沿，最后使该次所有权标记失效。Lost 路径立即隔离旧工作并跳过提交。停止派发后线程池仍可能在执行，`pause()` 只控制后续消费交付。外部副作用的去重或隔离由业务系统提供。

### 实践：观察成员变化和业务停滞

以下是 Java 3.9 Classic 实验方案，尚未在 Kafka 上实测。使用第 10 章的三分区订单 Topic，使用独立实验组。两个实例都设 `group.protocol=classic`、`enable.auto.commit=false`，显式选 `org.apache.kafka.clients.consumer.RangeAssignor`。配置 `heartbeat.interval.ms=1000`、`session.timeout.ms=10000`、`max.poll.interval.ms=5000`，确认 Broker 允许 10 秒的会话超时。

在 `subscribe(..., listener)` 中记录 assigned、revoked、lost 的时间、成员标识和分区列表，显式实现三个回调。所有者平时每轮用 `poll(Duration.ofMillis(200))`，并记录每分区前沿和最老在途任务年龄。每个场景先让组稳定，用组管理命令对照成员和分区。

| 操作                                                        | 预期观察                                                                     |
| ----------------------------------------------------------- | ---------------------------------------------------------------------------- |
| 启动 C1，再启动 C2                                          | C1 出现 Eager 撤销，随后两个成员得到新分配                                   |
| 通知 C2 的 Poll 线程调用 `close()`                          | 动态成员正常离组，C1 重新获得分区                                            |
| 重新启动 C2 后强制终止进程                                  | C2 没有机会记录回调，协调器按会话超时发现失联                                |
| 重新启动 C2 并保持进程存活，停止 Poll 20 秒再恢复           | 动态成员触发 Poll 超时，C1 可接手。C2 恢复 Poll 后记录实际回调和重新入组情况 |
| 写入订单，让所有 Worker 阻塞在闩锁上，所有者持续短周期 Poll | 前沿停滞，队列到限后暂停分区。组仍可保持稳定，释放闩锁后才恢复业务推进       |

可以给 C2 一个独立的 `group.instance.id` 重做停止 Poll 的场景，记录从 Poll 超时到会话过期的交接时差。以上预期仅适用于指定的 Classic 实验配置。

## 参考

- [Kafka 3.9 Java Rebalance Listener](https://kafka.apache.org/39/javadoc/org/apache/kafka/clients/consumer/ConsumerRebalanceListener.html)
- [Kafka 3.9 Consumer 配置](https://kafka.apache.org/39/configuration/consumer-configs/)
- [librdkafka v2.8.0 分配回调与 API](https://raw.githubusercontent.com/confluentinc/librdkafka/v2.8.0/src/rdkafka.h)

- [Kafka 4.0 Consumer Rebalance Protocol](https://kafka.apache.org/40/operations/consumer-rebalance-protocol/)
- [librdkafka v2.8.0 KIP-848 支持阶段](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md#next-generation-of-the-consumer-group-protocol-kip-848)
