---
id: kafka-log-model
title: 第 1 章：Kafka 全景与事件日志模型
description: "假设订单服务产生 OrderCreated，库存、统计、搜索都需要这条事件。若逐个直接调用下游，订单请求就会受到下游延迟和故障的影响。"
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
order: 1
---

# 第 1 章：Kafka 全景与事件日志模型

> 版本基线：Apache Kafka Broker / Java Client 3.9；固定源码使用 3.9.0 标签。C 客户端使用 librdkafka v2.8.0。命令面向 Kafka 3.9 的 Bash 环境。
>
> 学习目标：用一条订单事件说明 Kafka 保存什么、消费者记录什么，以及它没有替业务完成什么。机制基线 Kafka 3.9，版本差异单独标注。

## 1. 从“发一条消息”转向“追加一条事实”

假设订单服务产生 `OrderCreated`，库存、统计、搜索都需要这条事件。若逐个直接调用下游，订单请求就会受到下游延迟和故障的影响。事件流提供了另一种协作方式：先把事实追加到有保留期限的日志，再由下游按自己的节奏读取。这能减轻部分时间与部署上的耦合，但不会自动解除业务依赖。

Kafka 以分区化、可复制的事件日志组织记录，读取进度与数据保留分别管理。先区分业务事实与保存它的载体：

| 术语               | 含义与职责                                                          | 在订单场景中解决的问题                                                            |
| ------------------ | ------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Event（事件）      | 已发生的业务事实                                                    | `OrderCreated` 表示订单已创建，而不是要求库存立即处理的函数调用                   |
| Record（记录）     | Kafka 读写的数据单元，通常含 Key、Value、时间戳及 Headers（头字段） | 将订单号作为 Key，事件内容作为 Value；Kafka 不会因为 Value 是 JSON 就理解订单状态 |
| Log（日志）        | 按位置有序追加的记录序列                                            | 保存可供下游重复读取的历史事实，不是这里所说的应用调试日志                        |
| Producer（生产者） | 序列化并发送记录的客户端                                            | 把订单事件交给 Kafka，观察发送结果并处理错误                                      |
| Broker（服务节点） | 保存分区副本、处理协议请求的 Kafka 服务进程                         | 承载日志并提供写入、读取等服务                                                    |
| Consumer（消费者） | 主动请求并读取记录的客户端                                          | 将事件转换为库存、统计等业务动作                                                  |

### 一条订单事件的完整生命周期

以下是教学推演。假设订单 `O-42` 创建成功，记录写入 `orders` 的 P0（Partition 0），得到 Offset 799；库存组此前已处理到 798。Topic、Partition、Offset 和 Consumer Group 在后两节继续展开。

![订单事件写入、独立读取与位点提交](/assets/notes/kafka/kf-overview-review.svg)

[放大查看订单事件图](/assets/notes/kafka/kf-overview-review.svg)。

1. **订单服务创建订单**：数据库提交订单 `O-42`，构造带有唯一 `event_id=evt-42` 的 `OrderCreated`。这里暂时假设事件可以被发送；数据库和 Kafka 的双写风险见第 4 节。
2. **Producer 发送记录**：把订单号编码为 Key 字节，把事件序列化为 Value，选择 P0，并向它的 Leader（主副本）发送。调用异步 `send()` 返回，通常只说明进入了客户端发送流程；应继续观察 Future（异步结果对象）或回调。
3. **Broker 追加日志**：P0 Leader 给该记录分配 Offset 799，Follower（从副本）按复制协议拉取日志。下一条记录可能在 800；Offset 是逻辑位置，不是文件字节地址。
4. **Producer 获得结果**：在 `acks=all` 等待条件满足后，客户端可以获得含 Topic、Partition、Offset 的成功结果。此时库存可能尚未读取 799。
5. **库存 Consumer Group 读取**：组内负责 P0 的成员主动发出 Fetch（拉取）请求，获取 799。读取后客户端的位置可以推进到 800，但业务尚未因此完成。
6. **处理库存业务**：消费者验证事件、按 `event_id` 去重，并在库存数据库中扣减库存。验证或数据库写入失败时，不能把 799 当作已经完成。
7. **提交恢复位点**：确认 799 及此前记录连续处理成功后，提交 800；Group Coordinator（组协调器，负责组协调和位点请求的 Broker 角色）保存它，供重启或重新分配分区后恢复。不同组可能由不同 Broker 协调，图中合并展示这类职责，不要求两组共享同一协调器。

这里有两条不同的成功边界：**Kafka 接受并复制记录**，以及**库存数据库的业务事务成功**。前者不会自动触发或证明后者。消费者甚至可能在 Producer 收到响应之前就读到已可见的记录，图中的编号表达教学主线，不是两个客户端之间的全局同步屏障。

`acks`（acknowledgements，写入确认级别）规定 Producer 等待什么：`0` 不等待 Broker 响应，`1` 等 Leader 追加，`all` 等当前 ISR（In-Sync Replicas，同步副本集合）满足确认条件。`min.insync.replicas`（最小同步副本数）与 `acks=all` 配合约束接受写入时的同步副本数量。它们不等于每条记录都立刻刷盘，也不覆盖库存数据库事务。超时可能意味着结果未知，重试需要结合幂等生产与业务去重，不能把每个报错都理解为“绝对没有写入”。详见[确认与最小 ISR](/articles/kafka-acks-min-isr.html)。

图中的两组读取同一份逻辑日志，但进度独立。库存组提交 800，不会让统计组被迫跳到 800，也不意味着位置 799 的数据立即删除。

## 2. Topic、Partition 与 Offset 的第一层认识

Topic（主题）是数据流的逻辑名称；Partition（分区）是有序追加和并行分配的重要单位；Offset（位点）是某个分区内的逻辑位置。只说“消息 offset=42”并不足以定位记录，至少还需要 Topic 和 Partition。

同一个 Topic 的不同分区没有自动形成全局总顺序。把全站事件写进一个分区虽然简化排序，却也限制并行度，并不能让外部数据库或多线程业务天然按顺序完成。第 2 章会继续拆开路由顺序、日志顺序和处理顺序。

## 3. 组内分摊，组间独立

Consumer Group（消费组）用 `group.id` 标识一套共同消费和恢复进度。Kafka 3.9 传统消费组模型下，一组成员共同分摊订阅的分区；稳定分配时，同一个分区在一个组内交给一个成员。另一组可以独立重读这些分区。这个机制可以同时支持“竞争消费”和多业务订阅，但不是给每个组复制全部文件。

消费组记录恢复位点，用于故障后确定从哪里继续。提交位点并不能证明某条记录对应的数据库更新已经完成，也不控制普通 Topic 的保留。若应用落后超过保留窗口，未读数据仍可能不可用。因此，设计恢复方案时，需要一起考虑保留策略、备份和外部系统契约。

### Position、处理进度与 Committed Offset

Consumer Position（消费者当前位置）是客户端下一次交付记录的位置；Committed Offset（已提交位点）是为该组保存的恢复位置。**最后成功处理的消息 Offset** 则是应用自己的业务状态，Kafka 客户端无法从数据库之外自动判断。下面假设非事务、未压缩的连续记录，单线程处理，不手动 `seek()`（调整读取位置）：

| 时刻                             | Consumer Position | 最后连续成功处理的 Offset | Committed Offset | 此时故障重启            |
| -------------------------------- | ----------------- | ------------------------- | ---------------- | ----------------------- |
| 已完成 798 并提交                | 799               | 798                       | 799              | 从 799 恢复             |
| `poll()` 返回 799、800，尚未处理 | 801               | 798                       | 799              | 重新读到 799、800       |
| 完成 799，800 仍在处理           | 801               | 799                       | 799              | 799 可能重复执行        |
| 明确提交 800                     | 801               | 799                       | 800              | 从 800 恢复，799 已越过 |
| 完成 800，尚未提交 801           | 801               | 800                       | 800              | 800 可能重复执行        |

因此，“提交 800”通常表示**下次从 800 开始**，而不是“已经处理了 800”。真实日志可能因为压缩、事务控制记录等存在不可见或不连续的 Offset，不应把表中的加一模式当作所有情况下都能逐整数读到记录的保证。

Java 3.9 自动提交按客户端读取进度工作，不了解异步线程池是否完成业务：若 `poll()` 得到 799、800，交给后台处理后继续轮询，自动提交可能先越过尚未成功的记录；此时崩溃并恢复，会跳过未完成的业务动作，形成**业务层遗漏**，记录本身可能仍在 Kafka。反过来，数据库已成功而提交尚未成功就崩溃，会导致重复业务尝试。手动提交应跟随**连续成功区间**；若 800 先完成而 799 未完成，也不能直接越过 799。幂等处理和失败重试仍然必要。librdkafka 还有自动位点存储与自动提交的区别，见[消费位点与水位](/articles/kafka-offset-watermarks.html)。

## 4. Kafka 适合与不适合承担什么

适合的例子包括事件分发、日志采集、异步流水线和流处理输入。选择时需要评估事件量、积压容忍、重放需求、顺序范围和运维能力，而不是只比较一张吞吐排名表。

它不是通用关系数据库，不提供任意字段的低延迟查询；也不是数据投递后就能永久保存的归档系统。重试、消息模式演进、敏感信息保护、消费者幂等和异常数据修复仍需要在应用层设计。账务场景尤其不能把“成功写入 Kafka”直接等同于“银行扣款成功”。

### 订单数据库与 Kafka 的双写问题

两次独立调用之间没有天然的共同事务，调整调用顺序只能改变故障窗口：

| 调用顺序与故障                                    | 产生的业务状态                                                                  |
| ------------------------------------------------- | ------------------------------------------------------------------------------- |
| 订单数据库提交成功，发送 Kafka 失败且没有可靠补发 | 有订单但库存、统计收不到事件                                                    |
| Kafka 发送成功，随后订单数据库事务回滚            | 下游看到并不存在的已提交订单                                                    |
| Kafka 已写入，但响应丢失，应用重新发送            | 同一业务事件可能出现多次；Producer 幂等不能替代所有跨会话、应用级重发的业务去重 |

Transactional Outbox（事务发件箱）把“创建订单”和“写入待发送事件”放进**同一个数据库本地事务**。中继程序再通过轮询或 CDC（Change Data Capture，变更数据捕获）把已提交的 outbox 记录送到 Kafka。这样，事务回滚时两者一起回滚，发送失败时待发送事件仍可重试。

Outbox 解决的是本地业务状态与发送意图的一致保存，通常仍要面对重复投递、发送积压、事件顺序和清理策略。中继在发送后、标记完成前崩溃仍可能重复发送；消费者应以稳定 `event_id` 做幂等。Kafka 事务也不会自动把任意外部数据库事务纳入同一原子提交。本章先理解这个边界，不展开中继的生产实现。

## 5. 本册如何阅读

先掌握分区与复制，再阅读存储和批次，随后讨论位点、重平衡和事务，最后进入 librdkafka 与运维。ZooKeeper、早期 High-Level Consumer 和旧参数按历史背景阅读，Kafka 4.0 的部署差异单独查阅对应文档。

贯穿本册的订单场景都是教学构造，没有真实部署、压测或故障注入记录。阅读保证条件时，依次记录它覆盖的输入输出范围、必要设置、故障假设和剩余风险。

### 验证：两个消费组独立读取

若使用全新的单 Broker 实验环境，启动 Broker 前确认 `offsets.topic.replication.factor=1`，使组协调器能创建内部 Topic `__consumer_offsets`。Kafka 3.9 的默认内部位点 Topic 副本因子为 3。下面创建业务 Topic 时指定的副本因子只影响该业务 Topic。该前置条件也适用于后续用到组订阅或组位点提交的单 Broker 实验。[Kafka 3.9 Broker 配置](https://kafka.apache.org/39/configuration/broker-configs/#offsets.topic.replication.factor)

**可复现实验**：需要已启动的隔离 Kafka 3.9 集群、发行包和 Java。以下为发行包根目录下的 Bash 命令；不启动、格式化或重置任何现有集群。使用全新实验 Topic 和组名，若已存在请整体换名。单副本只用于观察流程，不验证副本可靠性；认证集群还需按环境提供客户端配置。

```bash
bin/kafka-topics.sh --bootstrap-server localhost:9092 \
  --create --topic orders-review-r1 --partitions 1 --replication-factor 1

# 终端 A：保持运行，控制台输出不是库存数据库处理证明。
bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic orders-review-r1 --group inventory-review-r1 --from-beginning \
  --consumer-property enable.auto.commit=true \
  --consumer-property auto.commit.interval.ms=1000 \
  --property print.partition=true --property print.offset=true

# 终端 B：不同 group.id，各自维护进度。
bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic orders-review-r1 --group analytics-review-r1 --from-beginning \
  --consumer-property enable.auto.commit=true \
  --consumer-property auto.commit.interval.ms=1000 \
  --property print.partition=true --property print.offset=true

# 终端 C：输入一条 Key:Value 记录。
printf '%s\n' 'O-42:{"event_id":"evt-42","type":"OrderCreated"}' | \
  bin/kafka-console-producer.sh --bootstrap-server localhost:9092 \
    --topic orders-review-r1 --producer-property acks=all \
    --property parse.key=true --property key.separator=:

# 等两个消费者继续轮询并完成自动提交后，分别查看已提交进度。
bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group inventory-review-r1
bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group analytics-review-r1
```

观察两组是否各自输出同一条记录、`CURRENT-OFFSET`（组已提交位点）、`LOG-END-OFFSET`（日志末端位置）和 `LAG`（两者差值）。在全新单分区、只有这一条非事务记录的理想条件下，预期记录 Offset 为 0，提交位置最终为 1；这是推演，不是本机输出。两组都追平时位置相等不代表共享进度：先停止 B，向同一 Topic 再发送不同 `event_id` 的记录，观察 A 推进而 B 的提交不动；恢复同一 B 组后继续读取。`--from-beginning` 不会覆盖已有有效提交。该实验不验证数据库处理、Outbox 或自动提交的安全性。

## 参考

- [Kafka 3.9 Introduction](https://kafka.apache.org/39/getting-started/introduction/)
- [Kafka 3.9 Design](https://kafka.apache.org/39/design/design/)
- [Kafka 3.9.0 KafkaConsumer：位置、提交与多线程说明](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/consumer/KafkaConsumer.java)
- [Kafka 3.9 Producer 配置：acks、幂等与重试](https://kafka.apache.org/39/configuration/producer-configs/)
- [Kafka 3.9 Quick Start：Topic 与控制台客户端](https://kafka.apache.org/39/getting-started/quickstart/)
- [Kafka 3.9.0 ConsoleConsumerOptions：本章控制台参数](https://github.com/apache/kafka/blob/3.9.0/tools/src/main/java/org/apache/kafka/tools/consumer/ConsoleConsumerOptions.java)
- [Debezium Outbox Event Router：事务发件箱设计及事件 ID](https://debezium.io/documentation/reference/stable/transformations/outbox-event-router.html)（仅引用模式说明，不作为 Kafka 3.9 的内置功能或已部署实现）。
