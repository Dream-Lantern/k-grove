---
id: kafka-retries-idempotency
title: 第 9 章：重试、幂等与超时的未知结果
description: "客户端发出请求后发生网络故障，可能有三种事实：Broker 尚未处理、已经处理但确认未返回、处理结果仍未确定。应用仅看到一个超时，不能据此可靠区分这些事实。"
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
order: 9
---

# 第 9 章：重试、幂等与超时的未知结果

> 版本基线：Kafka Broker / Java Client 3.9，固定源码为 3.9.0；librdkafka v2.8.0。协议序列、业务 ID 与日志 Offset 分别解释；故障时序是教学案例。
>
> 学习目标：从超时的不同执行阶段出发，区分客户端协议重试、业务重发与各自的去重范围。

## 1. 从请求到确认的未知结果窗口 {#_1-最容易被忽视的是-结果未知}

客户端发出请求后发生网络故障，可能有三种事实：Broker 尚未处理、已经处理但确认未返回、处理结果仍未确定。应用仅看到一个超时，不能据此可靠区分这些事实。

如果确认丢失，普通重新发送可能产生重复；若不重试，又可能遗漏业务事实。可靠协议要显式处理不确定窗口，而不是假设每个请求都会得到准确的“成功或完全没发生”二选一结果。

[![PID、Epoch、Sequence 去重与投递状态判断](/assets/notes/kafka/kf-idempotence-review.svg)](/assets/notes/kafka/kf-idempotence-review.svg)

## 2. 幂等生产者去掉哪一类重复

Kafka 幂等生产利用生产者身份、Epoch 和分区序列等机制识别适用的协议重试，避免同一批次因重发在日志中形成重复效果。它不是根据 JSON 的 order_id 自动比较全部历史。

如果应用在超时后重新构造并发送一条业务消息，或在重启后重新扫描待发业务，而又没有共享的业务去重协议，就不能保证这次 send 与上次属于“同一条”协议消息。因此，持久事件 ID、Outbox 状态和消费端幂等仍有价值。

### 幂等 Producer 协议原理

| 术语                                     | 含义及用途                                                                                      |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------- |
| Producer ID / PID（生产者标识）          | Broker 用来关联生产者协议状态的数字身份，不是应用的 order_id                                    |
| Producer Epoch（生产者代际）             | 区分该 PID 的不同协议代际，帮助隔离旧身份/处理重置；不是分区 Leader Epoch                       |
| Sequence Number（序列号）                | 相应 PID/Epoch 在每个 TopicPartition（主题分区）内的协议记录顺序，不是日志 Offset               |
| Base Sequence（批次起始序列号）          | 一个 Record Batch（记录批次）的起始序列，结合范围判断重试与顺序；Batch 与第 8 章含义一致        |
| ProducerStateManager（生产者状态管理器） | Broker 分区日志对应的生产者状态组件，维护身份、序列、最近批次及事务相关状态，配合快照和日志恢复 |
| In-Flight Request（在途请求）            | 已发送但结果尚未完成的协议请求；不同于仍在本地队列的消息，也不同于一个应用业务事务              |

以下假设 Producer 已获 PID=100、Epoch=0，在 `orders-0` 上发送 Batch1，三条记录的协议序列为 0～2；幂等及其配置约束均有效，Broker 的适用状态仍保留。为便于推演，假设该批正常追加的日志 Offset 为 500～502，这些都是教学数字：

1. Producer 发送 Batch1：`PID=100 / Epoch=0 / baseSequence=0 / lastSequence=2`。
2. Broker 取得该分区的 Producer 状态，检查代际、序列与适用事务条件。假设这是该身份的合法起始批次，校验通过。
3. Broker 追加记录，保存最近批次的序列范围和 Offset 等元数据，推进相应状态；生产请求按第 5 章的复制条件完成。
4. 成功 ACK（Acknowledgement，确认响应）在网络中丢失，Producer 尚未得知成功。
5. 客户端做**协议重试**，保留同一 PID/Epoch 与同一批次序列范围 0～2，而不是应用重新 `send()` 三条新消息。
6. 3.9.0 `UnifiedLog` 的客户端追加路径调用 `ProducerStateEntry.findDuplicateBatch()`，匹配相同 Epoch 及完整 first/last sequence 范围；命中已缓存的批次元数据后，返回原批次的相应结果，不再把同一批追加成 503～505。

正常的下一批通常从序列 3 开始；未命中可识别的重复批次却出现不符合预期的序列时，`ProducerAppendInfo.checkSequence()` 可返回 `OutOfOrderSequenceException`。旧 Epoch 的客户端追加也会受到代际校验。序号存在回绕及无已知状态等专门路径，不能概括为“所有小于最大序列的记录都丢弃，大于就接收”。Broker 不会逐条解析 JSON 再比较订单号。

`ProducerStateEntry` 在该版本缓存最近 5 个批次的元数据，`findDuplicateBatch()` 匹配完整范围，而非永久保存所有历史请求；ProducerStateManager 通过快照及保留日志等重建状态，也存在过期、日志截断/保留以及恢复边界。客户端的在途数约束与恢复协议要配套。不能把“支持幂等”解释成任意多年后、任意新客户端会话重新发送，都能凭原业务内容去重。

### 三种幂等与事务边界

| 支付/订单场景                   | 对应机制                                                    | 保证边界                                                             |
| ------------------------------- | ----------------------------------------------------------- | -------------------------------------------------------------------- |
| ACK 丢失后重试同一协议批次      | Kafka 协议层幂等                                            | 在相应身份、序列和恢复条件下避免重复追加，不保证外部扣款幂等         |
| 应用再次 `send()` 相同 order_id | 稳定 event_id、业务版本及消费端去重                         | 新 send 通常拥有新序列；相同 Key 本身不会阻止新记录                  |
| Outbox 中继恢复后重发同一事件   | Outbox 可靠恢复 + 相同 event_id + 下游幂等                  | 数据库发送意图不会丢失，但重复发布仍可能发生                         |
| Consumer 重复执行扣款           | 支付方幂等键、业务唯一约束或与本地处理一致的去重事务        | Producer 幂等不覆盖 Consumer 对外部系统的副作用                      |
| 消费 Kafka 后写入 Kafka         | 正确使用 Kafka 事务并将消费位点纳入事务，读取端使用适用隔离 | 原子管理相应 Kafka 输出与消费进度；不自动涵盖任意外部数据库/支付接口 |

Kafka Transaction（Kafka 事务）解决适用 Kafka 操作的原子提交/中止；Exactly-Once Semantics / EOS（恰好一次语义）必须说明覆盖范围。它与业务事件去重和协议幂等不是三种叫法指向同一个功能。事务协议见[第 14 章](/articles/kafka-transactions.html)，本章不重复其实现。

## 3. 顺序与最大在途请求相关

未使用幂等时，多个在途批次可能出现前一批失败重试、后一批先成功的情况，从而改变原来的发送顺序。启用幂等也必须满足客户端对确认、重试和在途请求数量的约束。

重试与幂等应结合客户端的默认值、显式配置和冲突检查一起设计。Java 3.9 在无冲突配置时默认启用幂等；librdkafka v2.8.0 默认关闭。具体设置不兼容时可能被拒绝或改变行为，启动时的配置检查不能省略。

具体约束是acks=all、retries>0、max.in.flight.requests.per.connection≤5。Java3.9未显式启用幂等时，显式冲突值可能使默认幂等失效；显式true且冲突则配置异常。C2.8显式启用后会调整用户未设置的相关参数，用户自己设置不兼容值则实例创建失败。默认值、自动调整与显式冲突不能混为一列；[第19章配置组合表](/articles/kafka-client-configuration.html)给出合法与冲突例子。

## 4. 超时有不同层次

聚合等待、单次请求、整体消息投递以及事务超时，各自约束的过程不同。把所有 timeout 都设得很大，可能导致故障后长期堆积；都设得很小，又可能带来无效重试和误判。

以 librdkafka 为例，消息投递超时约束本地等待与重试过程，不能用 poll 的等待毫秒数替代。poll 的等待时长主要影响调用线程处理事件和等待的方式，不会自动把消息的可靠投递时限设为相同的毫秒数。

### 消息 1、2、3、4、5 不保证全部成功

这是按 librdkafka v2.8.0 官方说明构造的应用消息序列，不是实际故障注入。假设幂等开启，应用提交业务消息 1～5：1 已成功，2/3 在等待或重试过程中达到整体交付期限，恢复连接后 4/5 继续发送并成功。在某个允许的故障历史里，日志最终可能只有业务消息 1、4、5。

这里的 1～5 是**应用消息标签**，不是断言同一 PID/Epoch 的底层序列号可以直接越过协议校验。C 客户端会结合队列、在途请求、排空及必要的 Epoch 更新等恢复流程保持协议状态一致；官方说明区分排队超时和在途超时。若 2/3 已发出而只是确认未知，也可能其实已写入，不能仅凭失败报告就宣称最终日志必然没有它们。

| 配置                                         | librdkafka v2.8.0 默认 / 作用                                                            | 与 Java 3.9 的区别                                                                   |
| -------------------------------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------ |
| `message.timeout.ms` / `delivery.timeout.ms` | 前者默认 300000ms，后者为别名；本地等待及重试的整体交付期限，事务设置还会约束有效值      | Java 使用 `delivery.timeout.ms`，默认 120000ms，没有同名 message.timeout.ms 直接配置 |
| `request.timeout.ms`                         | 默认 30000ms，C 的 Broker 生产确认等待，依赖 acks 非 0                                   | Java 同名默认也为 30000ms，但作用是相应请求响应等待；不能因同名假设完全相同          |
| `retries`                                    | 默认 2147483647，别名 message.send.max.retries，受整体期限限制                           | Java 同默认值，也受交付期限约束；不是无限期重发                                      |
| `retry.backoff.ms`                           | 默认 100ms，重试退避起点，结合最大退避配置                                               | Java 同名默认也是 100ms，需按其退避实现和上限理解                                    |
| `enable.gapless.guarantee`                   | 默认 false，实验性；依赖幂等，在某些造成消息序列缺口的批次失败时使 Producer 进入致命错误 | 没有可直接照抄的 Java 同名配置；**不覆盖 message.timeout.ms 超时**                   |

Epoch 更新用于客户端协议恢复，不恢复已最终超时消息的业务事实。幂等保证适用发送顺序和重试去重，不能把“应用接受了 5 条任务”自动变成“5 条都将连续成功”。本章的这种缺失也不同于第 7 章 Compaction 清掉**已经追加过**的历史记录：一个是发送结果/业务序列问题，一个是存储保留问题。

## 5. 重试策略还需要边界

区分可恢复错误、配置错误、权限错误和致命状态。过大的消息、错误认证或不支持的参数不会因为立即重复一百万次而恢复。重试需要退避、预算、告警和可恢复的失败记录，避免形成放大故障的重试风暴。

对业务暴露结果时，也应区分已确认、已拒绝和待查证。若业务要求严格追踪，可以用稳定 event_id 关联发送记录、投递报告和消费效果，而不是仅依赖进程退出码。

### librdkafka Delivery Report 的持久化状态

Delivery Report（投递结果报告）由 C 客户端在应用 poll 等处理路径中交付；`rd_kafka_message_status()` 可在报告中查询该次消息的协议持久化状态，用于辅助失败决策：

| 状态                                     | v2.8.0 的含义                                   | 应用处理方向                                                                   |
| ---------------------------------------- | ----------------------------------------------- | ------------------------------------------------------------------------------ |
| `RD_KAFKA_MSG_STATUS_NOT_PERSISTED`      | 从未传到 Broker，或错误表明这次记录没有写入日志 | 可按预算安排重发，但注意业务事件的其他尝试、顺序和期限；不替整个历史作保证     |
| `RD_KAFKA_MSG_STATUS_POSSIBLY_PERSISTED` | 已发送，未得到足够确定的确认信息，可能已写入    | 标记未知结果，保留事件 ID 及证据；直接新 send 有重复及重排风险                 |
| `RD_KAFKA_MSG_STATUS_PERSISTED`          | Broker 已写入并按适用确认语义确认               | 通常不应应用级重发；不是所有物理设备均已 fsync、事务已提交或消费扣款成功的证明 |

先区分本地入队失败：例如 producev 返回 Queue Full，此次没有成功入队，也还没有这条消息的最终报告可查询。已入队后，先让客户端完成协议重试和报告；报告失败时结合 `err`、上述状态、是否存在致命错误及业务预算决定。应用重发是一个新的协议发送，不是继续等待原请求。

`NOT_PERSISTED` 与“服务端明确拒绝”并不完全等同，它还包含没有发送的情况；`POSSIBLY_PERSISTED` 也不能升级成“肯定已写入”。v2.8.0 头文件还明确要求 **PERSISTED 只应在 `acks=all` 下信任**，不能把此枚举当作弱确认配置的可靠性升级。把状态、错误码、event_id、时间和重试决定一起保存，避免只保留“成功/失败”布尔值。

### Java Future / Callback 单独处理

Java Producer 不提供完全同名的 `rd_kafka_message_status()`。应用同时处理 `send()` 阶段的本地异常、Future 完成异常及 Callback 中的异常；成功时保留 RecordMetadata（记录元数据）的 Topic/Partition/Offset。授权、序列化、超大记录、超时和客户端致命状态不应统一进入无限重发。

特别区分 `future.get(timeout)` 的调用方等待超时与 Kafka `delivery.timeout.ms` 最终到期：前者只是应用暂时不等了，底层发送未必结束或被取消；后来仍可能收到成功回调。Future 已以 Kafka 超时异常完成，也不能对所有历史尝试断言没有写入。记录并遵循 SDK 的重试、恢复和致命状态语义，必要时向上游暴露待查证状态，不手工修改协议序号继续发送。

### 隔离故障实验与配置对照

使用已准备的独立测试 Topic 和可丢弃的客户端实例，禁止在生产网络断连或重置在线消费组。以下均为**实验方案**：

1. 记录 Broker 3.9、Java Client 3.9.0 / librdkafka 2.8.0、acks、幂等、在途数、整体交付与请求超时、退避、分区数、业务 event_id。配置有效性按第 3 节及[第 5 章配置表](/articles/kafka-acks-min-isr.html)核对。
2. 基线发送一小批带不同 event_id 的记录，分别保存 Java 最终元数据与 C Delivery Report 的错误/状态。
3. 使用隔离环境的网络代理控制“请求已到达但响应被丢弃”的窗口。普通停掉客户端网络只能制造连接问题，不能证明精确丢了 ACK；没有代理、服务端证据及时间线时，标为不能确认的故障条件。
4. 分别观察协议自动重试与**另一次应用 send**，以消费者读取/服务端日志中的 event_id、Partition、Offset 核对实际重复，不能从回调次数直接推断日志份数。C 状态来自真实报告，不预填值。
5. 另设较短交付期限，观察排队/在途超时差异；由于消息入队时刻和连接状态影响结果，不能保证随便暂停一下就精确得到 1、4、5。不要把 `enable.gapless.guarantee=true` 当作解决超时缺口的方法。
6. 按预算恢复或停止客户端，保留失败和未知记录；核对结果后再决定是否用相同 event_id 做业务恢复，不在生产执行支付副作用。

可以复用[第 8 章 Java/C 发送示例](/articles/kafka-producer-batching.html#java-与-c-最小发送示例)观察基本报告，但它不是网络故障代理或完整去重验证框架。本轮没有虚构“协议重试恰好发生一次”等运行结果。

## 参考

- [Java 3.9 幂等与在途请求约束](https://kafka.apache.org/39/configuration/producer-configs/#enable.idempotence)
- [librdkafka v2.8.0 可靠性说明](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
- [ProducerStateManager.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/storage/src/main/java/org/apache/kafka/storage/internals/log/ProducerStateManager.java)：生产者状态、过期及快照恢复。
- [ProducerStateEntry.java](https://github.com/apache/kafka/blob/3.9.0/storage/src/main/java/org/apache/kafka/storage/internals/log/ProducerStateEntry.java) / [ProducerAppendInfo.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/storage/src/main/java/org/apache/kafka/storage/internals/log/ProducerAppendInfo.java)：最近批次范围、重复识别、Epoch/Sequence 检查。
- [UnifiedLog.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/log/UnifiedLog.scala)：客户端追加路径中的重复批次识别。
- [librdkafka v2.8.0 rdkafka.h](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)：消息状态 API 与枚举；[配置表](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)及 INTRODUCTION 的 Message timeout considerations 提供边界。
- [KIP-98：幂等与事务设计](https://cwiki.apache.org/confluence/display/KAFKA/KIP-98+-+Exactly+Once+Delivery+and+Transactional+Messaging) / [KIP-360：幂等/事务 Producer 可靠性与未知身份恢复](https://cwiki.apache.org/confluence/spaces/KAFKA/pages/89068820/KIP-360%2BImprove%2Breliability%2Bof%2Bidempotent%2Btransactional%2Bproducer)：设计背景；实际判断仍以固定版本实现为准。

## 联读

通用未知结果与重试预算见[分布式RPC主文](/articles/distributed-rpc-retries-idempotency.html)；本章聚焦Kafka协议重试。
