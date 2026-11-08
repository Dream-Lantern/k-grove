---
id: kafka-consumer-groups
title: 第 10 章：消费组、分区分配与并行
description: "共享 group.id 的传统消费成员参与组协调，分摊共同订阅的分区，并围绕组的恢复位点继续消费。不同 group.id 则分别维护进度，适合统计、搜索等独立处理链。"
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
order: 10
---

# 第 10 章：消费组、分区分配与并行

> 版本基线：Kafka Broker 3.9、Java Client 3.9 与 librdkafka v2.8.0。
>
> 学习目标：理解消费组如何分摊分区，再结合热点与业务成本选择消费者数量和应用并行方式。

## 1. Group 是共同承担同一消费任务

共享 `group.id` 的传统消费成员参与组协调，分摊共同订阅的分区，并围绕组的恢复位点继续消费。不同 group.id 则分别维护进度，适合统计、搜索等独立处理链。

稳定正常分配中，同组一个分区由一个成员负责；一个成员可以负责多个分区。故障交接和在途任务可能造成重复业务效果，因此“同组不重复分配”不能推出“下游永不出现重复操作”。

[![Kafka Consumer Groups：独立的消费位点](/assets/notes/kafka/kf-group.svg)](/assets/notes/kafka/kf-group.svg)

### Classic 如何协调分配

订单服务把订单 ID 作为 Key 写入 `review-orders`。同一个消费组（Consumer Group）中的成员共同处理这些事件。Kafka 3.9 Classic 中有三个容易混淆的角色：

| 角色                               | 职责                                                                            |
| ---------------------------------- | ------------------------------------------------------------------------------- |
| Group Coordinator（消费组协调器）  | Broker 上负责组成员管理（Group Membership）、组织分配同步和处理组位点请求的角色 |
| Group Leader（组内分配负责人）     | Classic 协议选出的消费者成员，运行协商选定的分配器                              |
| Partition Leader（分区副本主节点） | Broker 上负责分区副本的领导者角色，默认由它响应分区读取                         |

以下是首次形成稳定分配的教学流程，省略重试和增量交接等分支。客户端先通过 FindCoordinator 定位协调器，再用 JoinGroup 上报支持的分配策略及相应订阅元数据。协调器选定共同支持的策略，并将成员元数据交给 Group Leader。该成员计算消费分区分配（Partition Assignment），通过 SyncGroup 提交结果。协调器向各成员返回各自的分配，客户端初始化位置后开始拉取。成员离开、超时或加入时，原分配可能失效，组需要重新协调。KIP-848 的分配计算由服务端完成，见[第 12 章](/articles/kafka-rebalance.html)。

## 2. 分区数形成一层并行上限

一个只订阅 3 个分区的组，创建 5 个传统消费成员时，不能让每个成员都同时独占不同分区；部分成员可能空闲。若一个成员已负责多个分区，适当增加成员则可能分摊负载。

但最佳成员数未必等于分区数，还取决于业务处理成本、资源预算、Topic 订阅组合、热点分布和分配算法。如果一个 Key 占了大部分流量，即使其他分区有空闲成员，也无法接管这个热键对应的部分日志。

假设所有成员都订阅 `review-orders`，以下是一种可能的分配。具体成员和分区的对应关系取决于分配器和组状态。

| 成员数 | 示例分配                  | 空闲成员 | 瓶颈                         |
| ------ | ------------------------- | -------- | ---------------------------- |
| 1      | C1 → P0、P1、P2           | 0        | 一个实例承担全部业务         |
| 2      | C1 → P0、P1，C2 → P2      | 0        | C1 可能先耗尽处理能力        |
| 3      | C1 → P0，C2 → P1，C3 → P2 | 0        | 最忙分区仍可能积压           |
| 5      | C1 → P0，C2 → P1，C3 → P2 | 2        | 同组最多三个成员同时持有分区 |

普通负载不均可能来自多个繁忙分区集中在同一实例，扩成员或调整分配可以摊开它们。热点 Key 则把负载集中到一条分区日志，增加成员无法拆分该日志。增加分区适用于可分散的多个 Key，但按分区数取模的映射可能改变，同一 Key 的新旧事件可能落入不同分区，原来的顺序假设需要重新评估。业务内部并行适用于可独立执行的任务，若要求同一订单按序处理，可按订单 Key 串行调度。

## 3. Subscribe 和 Assign 是两种控制方式

Java 3.9 的 `subscribe()` 声明 Topic 订阅，由消费组管理分区分配。显式 `assign()` 直接指定分区集合，绕过自动组分配。对刚分配且尚无本地位置的分区，客户端优先使用有效的组提交位点，缺失或越界时按 `auto.offset.reset` 处理。对已分配分区调用 `seek()` 可覆盖本地读取位置，下一次读取仍受保留范围和记录可见性约束。Seek 本身不会提交位点。

以下是 Java 3.9 API 片段，假设 `consumer` 已用可连接的 Broker、`group.id` 和反序列化器创建，Topic 已存在。两种方式各用一个新实例，随后由各自的所有者线程持续调用 `poll(Duration)`。

```java
// 实例 A：首次 poll 驱动入组与分配
consumer.subscribe(List.of("review-orders"));
```

```java
// 实例 B：手动分配。第二行之后仍可按组提交位点恢复
var partition = new TopicPartition("review-orders", 0);
consumer.assign(List.of(partition));
// 可选：已知 100 仍处于有效范围时，显式改从 100 读取
consumer.seek(partition, 100L);
```

手动分配不必然禁止使用 group.id 提交位点，但共享位点的多个实例若无协调，可能互相覆盖恢复位置。不能仅把 subscribe 改成 assign 就宣称解决了 Rebalance，也不能把手动分配当作 Exactly Once 的实现。

## 4. client.id 与静态成员身份的用途 {#_4-client-id-不是组内强制唯一身份}

`client.id` 用于请求标识、日志、指标及适用配额等，不是消费者成员的排他身份。因此，不能把“同组 client.id 绝对不能重复”作为身份约束。

静态成员使用 `group.instance.id` 表达另一层身份约束，同组实例值需要正确管理；重复可能被 fencing。它能减少某些短暂重启造成的扰动，但不保证永不重平衡，更不能拿相同静态 ID 同时运行两份程序来扩容。

## 5. 应用内部并行需要额外协议

将 poll 得到的消息放进线程池可以提高业务并行，但会引入乱序完成、队列积压、所有权交接和位点提交问题。工作线程不能随意提交它看到的最大 Offset，而应由每个分区的连续完成前沿控制。

选择并行策略前，先明确幂等能力、Key 顺序要求、任务时限，以及分区撤销后的旧任务处置。下一章的连续完成水位将这些条件联系到安全恢复位点。

所有工作线程都卡住，而主线程仍在 poll，就是“组成员存活、业务停滞”的反例。应监测每个分区连续完成前沿的停滞时间，以及最老在途任务的年龄；仅看心跳、poll 频率或进程存活指标还不够。[两种活性历史](/articles/kafka-rebalance.html)

### Poll 线程和业务线程池

Java `KafkaConsumer` 实例由一个线程独占。该线程负责 `poll()`、`pause()/resume()`、`commitSync()`、`seek()` 和回调内的分区状态维护。Worker 并发执行业务，只把完成结果交还所有者线程。跨线程发起关闭时，可以用 Java API 明确允许跨线程调用的 `wakeup()` 唤醒所有者，由所有者关闭实例。

一个有界流程可按以下步骤实现：

1. 所有者关闭自动提交，为每个持有分区建立按交付顺序排列的任务表，为每次取得分区生成新的本地所有权标记。每轮先收集结果，按分区和标记匹配任务，推进连续完成前沿，再提交安全位置。
2. 把已排队、正在执行和已完成但仍被前序任务阻塞的记录都计入容量。令 `max.poll.records=N`，仅在应用缓冲至少还能容纳 N 条时开放读取。容量不足时暂停已分配分区，仍短周期 poll 服务组事件。新分配的分区也由同一容量规则控制，可在分配回调里先暂停。
3. Poll 返回后先登记整批，再由所有者把任务放进有界线程池队列。队列满时把已登记任务留在有界缓冲中，后续再派发。这种背压（Backpressure）会降低取数速度，避免 Worker 卡住时无限积压。
4. Worker 返回分区、Offset、所有权标记及结果。失败项保留在前沿之前的处理链上并按应用策略重试，后完成的记录无法越过它。撤销时停止派发，有界收尾并在仍有权时提交，丢弃旧标记的迟到结果。已发出的外部请求仍需由下游控制重复效果。

[第 11 章](/articles/kafka-offset-watermarks.html)展开任务表的推进算法。静态成员的隔离（Fencing）作用于组身份，业务任务的本地标记则用于隔离旧结果。

### 实践：观察同组分区分配

使用 Kafka 3.9 发行包的 Bash 脚本，假设本地 Broker 可访问、允许建 Topic 和加入组，且实验 Topic 与 `group.id` 未被占用。单 Broker 实验还需满足[内部位点 Topic 的创建条件](/articles/kafka-log-model.html)。

```bash
bin/kafka-topics.sh --bootstrap-server localhost:9092 --create \
  --topic review-orders --partitions 3 --replication-factor 1

# 在不同终端运行同一命令，可分别设置 client.id 为 review-c1 到 review-c5
bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic review-orders --group review-g1 \
  --consumer-property group.protocol=classic --consumer-property client.id=review-c1

bin/kafka-consumer-groups.sh --bootstrap-server localhost:9092 \
  --describe --group review-g1 --members --verbose
```

从 1 个成员依次增加到 2、3、5 个，每次等组稳定后查看 `CONSUMER-ID`、`CLIENT-ID`、`#PARTITIONS` 和 `ASSIGNMENT`。预期稳定时三个分区各出现一次，5 个成员中两个分区数为零。仅观察分配时，Topic 可以为空。此处为实验步骤与预期。

## 参考

- [Kafka 3.9 Java Consumer API](https://kafka.apache.org/39/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html)
- [Kafka 3.9 消费组运维命令](https://kafka.apache.org/39/operations/basic-kafka-operations/)
- [KIP-848 的 Classic 协议背景与新协议设计](https://cwiki.apache.org/confluence/display/KAFKA/KIP-848%3A+The+Next+Generation+of+the+Consumer+Rebalance+Protocol)

- [Kafka 3.9 Consumer 配置](https://kafka.apache.org/39/configuration/consumer-configs/)
- [librdkafka Consumer group 说明](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
