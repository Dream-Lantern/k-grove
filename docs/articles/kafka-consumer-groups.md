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

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：理解消费组如何分摊分区，再结合热点与业务成本选择消费者数量和应用并行方式。

## 1. Group 是共同承担同一消费任务

共享 `group.id` 的传统消费成员参与组协调，分摊共同订阅的分区，并围绕组的恢复位点继续消费。不同 group.id 则分别维护进度，适合统计、搜索等独立处理链。

稳定正常分配中，同组一个分区由一个成员负责；一个成员可以负责多个分区。故障交接和在途任务可能造成重复业务效果，因此“同组不重复分配”不能推出“下游永不出现重复操作”。

[![Kafka Consumer Groups：独立的消费位点](/assets/notes/kafka/kf-group.svg)](/assets/notes/kafka/kf-group.svg)

## 2. 分区数形成一层并行上限

一个只订阅 3 个分区的组，创建 5 个传统消费成员时，不能让每个成员都同时独占不同分区；部分成员可能空闲。若一个成员已负责多个分区，适当增加成员则可能分摊负载。

但最佳成员数未必等于分区数，还取决于业务处理成本、资源预算、Topic 订阅组合、热点分布和分配算法。如果一个 Key 占了大部分流量，即使其他分区有空闲成员，也无法接管这个热键对应的部分日志。

## 3. Subscribe 和 Assign 是两种控制方式

Subscribe 表达希望订阅哪些 Topic，由组管理参与分配。显式 Assign 则直接指定分区集合及相应起点控制，不自动替应用完成同样的组内负载均衡。

手动分配不必然禁止使用 group.id 提交位点，但共享位点的多个实例若无协调，可能互相覆盖恢复位置。不能仅把 subscribe 改成 assign 就宣称解决了 Rebalance，也不能把手动分配当作 Exactly Once 的实现。

## 4. client.id 与静态成员身份的用途 {#_4-client-id-不是组内强制唯一身份}

`client.id` 用于请求标识、日志、指标及适用配额等，不是消费者成员的排他身份。因此，不能把“同组 client.id 绝对不能重复”作为身份约束。

静态成员使用 `group.instance.id` 表达另一层身份约束，同组实例值需要正确管理；重复可能被 fencing。它能减少某些短暂重启造成的扰动，但不保证永不重平衡，更不能拿相同静态 ID 同时运行两份程序来扩容。

## 5. 应用内部并行需要额外协议

将 poll 得到的消息放进线程池可以提高业务并行，但会引入乱序完成、队列积压、所有权交接和位点提交问题。工作线程不能随意提交它看到的最大 Offset，而应由每个分区的连续完成前沿控制。

选择并行策略前，先明确幂等能力、Key 顺序要求、任务时限，以及分区撤销后的旧任务处置。下一章的连续完成水位将这些条件联系到安全恢复位点。

所有工作线程都卡住，而主线程仍在 poll，就是“组成员存活、业务停滞”的反例。应监测每个分区连续完成前沿的停滞时间，以及最老在途任务的年龄；仅看心跳、poll 频率或进程存活指标还不够。[两种活性历史](/articles/kafka-rebalance.html)

## 参考

- [Kafka 3.9 Consumer 配置](https://kafka.apache.org/39/configuration/consumer-configs/)
- [librdkafka Consumer group 说明](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
