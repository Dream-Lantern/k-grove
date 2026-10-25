---
id: kafka-transactions
title: 第 14 章：事务、read_committed 与可见边界
description: Kafka 事务生产者在一个事务中发送到多个 Topic-Partition，并可把适用输入消费位点一起提交。成功提交后，按事务隔离读取的下游才能看到相应已提交记录；中止后这些事务记录不会作为正常已提交业务输出返回。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 14
---

# 第 14 章：事务、read_committed 与可见边界

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：把事务写入、复制提交和消费者可见性分开。本章统一使用“下一位置／排他上界”口径，避免各种文档里最后一条与下一条差一的问题。

## 1. 事务可以跨多个分区

Kafka 事务生产者在一个事务中发送到多个 Topic-Partition，并可把适用输入消费位点一起提交。成功提交后，按事务隔离读取的下游才能看到相应已提交记录；中止后这些事务记录不会作为正常已提交业务输出返回。

“看不到”不等于所有物理字节立刻从磁盘删除。日志里仍有事务相关记录与控制信息，需要按协议解释。消费者若使用不同隔离级别，观察结果也不同。

### 原子提交不是一次poll的跨分区快照

一次事务写入 P0 和 P1 并提交，并不保证全部记录会在同一个 poll 中同时返回，也不保证某个消费者订阅了所有相关分区。组内由 A 处理 P0、B 处理 P1 时，A 可能已经更新业务，而 B 还没有取得或处理对应记录。

read_committed 约束记录的提交可见性，不会替多个实例建立跨分区一致快照，更不会建立外部数据库事务。seek、保留与 compact 也可能使历史读取只覆盖事务的一部分。若需要成组展示或执行，应设计事务/业务聚合 ID、完成标记、版本或其他明确协议。[Kafka 3.9 Consumer事务读取](https://kafka.apache.org/39/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html)

## 2. 三个上界按统一口径解释

LEO 是某副本日志末端的下一位置。HW 是复制提交相关上界。LSO 在这里指 Last Stable Offset，即适用的稳定前缀上界，不是 Log Start Offset，也不是“日志里最后一个字节”。

![复制与事务的可见边界](/assets/notes/kafka/kf-visibility.svg)

在有开放事务时，稳定前缀受最早未完成事务等条件约束；通常 LSO≤HW≤Leader LEO。没有开放事务阻挡时，LSO 可以等于 HW。即使日志后面还有非事务数据，也不能认为 read_committed 总能越过开放事务直接返回它。

## 3. read_committed 不只是过滤 aborted

假设位置 10 开始的事务迟迟未完成，后面又追加了其他记录。为了保持适用的日志顺序，read_committed 可能等待事务状态确定，而不是只删除已知 aborted 记录后返回全部尾部。

因此消费者“没有新消息”可能由事务可见边界造成，不一定是生产者没有写入。诊断时应比较输入写入、HW、稳定边界和事务状态，不要仅通过增大 Fetch 字节数试图解决。

## 4. 事务生产者的生命周期

事务身份用于识别跨会话的逻辑生产者并隔离僵尸实例。需要初始化事务能力、开始事务、产生输出、加入安全消费位点并提交，或者按错误分类中止。事务 ID 的稳定性与不同活动实例的唯一性必须一起设计。

错误分为可重试、要求中止和致命等类别，不能遇到任何错误都再次 commit。事务超时也不能保障任意长的业务任务：开放事务持续过久，会影响下游可见性和资源占用。

## 5. 两个默认值差异

Java 3.9 消费者默认 `read_uncommitted`，librdkafka v2.8.0 配置表中则默认 `read_committed`。不能把其中一个写成“Kafka 所有消费者默认”。实际部署仍应显式核对有效配置，封装库也可能覆盖默认值。

本章没有可执行的事务应用，避免用几行省略错误处理的代码冒充端到端 Exactly Once。完整实现还必须协调分区交接、输入恢复和事务失败后的位置处理。

## 参考

- [Java 3.9 isolation.level](https://kafka.apache.org/39/configuration/consumer-configs/#isolation.level)
- [librdkafka v2.8.0 事务 API 与配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
