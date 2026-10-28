---
id: kafka-topics-partitions
title: 第 2 章：Topic、Partition、Key 与顺序
description: "一个分区是一条独立日志。多个分区让数据和负载可以分布在不同 Broker 上，也给消费组提供可分配的并行单元。一个 Broker 可以承载很多分区，一个 Topic 也可以跨多个 Broker；两者不存在“一台机器对应一个 Topic”的固定关系。"
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
order: 2
---

# 第 2 章：Topic、Partition、Key 与顺序

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：理解分区的并行单位、Key 的路由规则，以及日志顺序与业务完成顺序之间的关系。

## 1. 一个 Topic 为什么要拆分

一个分区是一条独立日志。多个分区让数据和负载可以分布在不同 Broker 上，也给消费组提供可分配的并行单元。一个 Broker 可以承载很多分区，一个 Topic 也可以跨多个 Broker；两者不存在“一台机器对应一个 Topic”的固定关系。

增加分区数能提供更多并行机会，也会增加文件、元数据、复制、恢复和调度成本。因此，不能因为希望增加消费者，就无限增加分区。单个业务 Key 过热时，增加分区也未必能缓解这个 Key 的瓶颈。

## 2. Key 的路由作用与客户端规则 {#_2-key-是路由输入-不是数据库唯一约束}

以 `order_id` 为 Key，可以让同一订单的事件在稳定的路由规则下进入同一分区；这便于按订单串行处理。Key 本身不阻止重复 Value，不验证事件版本，也不自动拒绝两条相同 `event_id`。

常见分区器根据 Key 哈希和分区数计算目标。算法随客户端而异，计算中的分区数量也与 Broker 数量分别管理。跨语言生产者需要统一算法、编码和空 Key 行为，或显式选择分区，才能让相同业务 Key 遵循预期路由。

| 固定客户端路线                          | 非空Key                       | NULL／空Key要另外确认                                 |
| --------------------------------------- | ----------------------------- | ----------------------------------------------------- |
| Java 3.9内置路线，未显式分区、未忽略Key | Murmur2，正数化后对分区数取模 | NULL进入无Key批次分配；零长度字节数组仍是有Key        |
| librdkafka v2.8.0默认consistent_random  | CRC32                         | NULL与零长度Key走随机分配相关路线                     |
| C v2.8.0 murmur2_random                 | Java兼容的Murmur2有Key映射    | NULL随机路线；不能据此保证无Key批次分布与Java完全相同 |

以上还要排除自定义分区器、显式Partition与Java的`partitioner.ignore.keys=true`。UTF-8文本看起来一样但字节不同，也可能路由不同。固定字节算例与分区期望见[配置对照](/articles/kafka-client-configuration.html)。

![Key 与分区顺序的边界](/assets/notes/kafka/kf-key.svg)

## 3. 发起、日志追加与业务完成的三种顺序 {#_3-三种顺序不能混在一起}

第一种是应用发起顺序：两个线程同时提交时，业务是否已定义先后关系？第二种是分区日志顺序：记录追加后按该分区的 Offset 排列。第三种是业务效果完成顺序：消费者把任务交给线程池后，较晚读取的任务可能先写完数据库。

因此，“同分区由同一个消费者负责”不等于“业务效果必然串行”。若订单必须先创建再支付，消费侧可以按分区或业务 Key 串行，或在下游校验状态版本；不要仅依赖客户端读取顺序。

## 4. 扩分区为什么可能破坏原有路由假设

教学例子：原先按某种固定哈希对 4 个分区取模，扩为 6 个后，部分 Key 的结果会变化。旧记录仍留在旧分区，新记录可能进入新分区，于是同一订单的历史与后续事件可能跨分区。扩容不自动搬运已有日志来重新建立单 Key 总顺序。

增加 Broker 则是另一件事：它增加了承载资源，但不一定会自动改变现有分区的分配或数量。若要迁移已有分区，需要明确的重分配计划。扩容前应先区分“增加机器”“调整副本位置”“增加分区”这三个动作。

## 5. 命名、模式与分区策略一起设计

Topic 可按业务事实域命名，避免把每个用户或每个订单都变成独立 Topic。Value 模式要考虑兼容性，Key 编码变化也应按协议变更管理。消费者遇到未知字段、缺字段或新事件类型时，应有明确的兼容或隔离处理。

自检问题：相同订单由 Java 和 C 服务同时发布，为什么可能落到不同分区？正确答案应同时考虑算法、字符编码、分区数、显式分区和 Key 是否真的相同，而不是只检查字符串显示是否一致。

## 参考

- [Java 3.9 Producer 配置](https://kafka.apache.org/39/configuration/producer-configs/)
- [librdkafka v2.8.0 分区器与配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)
