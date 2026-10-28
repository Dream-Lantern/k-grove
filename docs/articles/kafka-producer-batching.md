---
id: kafka-producer-batching
title: 第 8 章：生产者路由、批次与压缩
description: "应用先把业务对象序列化成字节，客户端再确定目标分区、将记录排入队列，最后由后台 I/O 发送。API 是否阻塞、何时报告本地错误，以及如何获取最终结果，都取决于具体客户端。"
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
order: 8
---

# 第 8 章：生产者路由、批次与压缩

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：串联序列化、分区路由、本地排队、批次发送与投递报告，再结合延迟和资源预算理解批次参数。

## 1. 从本地入队到投递报告 {#_1-send-成功可能只表示接受了任务}

应用先把业务对象序列化成字节，客户端再确定目标分区、将记录排入队列，最后由后台 I/O 发送。API 是否阻塞、何时报告本地错误，以及如何获取最终结果，都取决于具体客户端。

对于异步生产者，“函数返回没有错误”常常不等于远端已经可靠接受。Java Future 或回调、librdkafka Delivery Report 都需要按接口契约检查。不能丢弃全部回调，再用程序正常退出证明发送成功。

[![Kafka Producer：分区选择先于分区 Batch](/assets/notes/kafka/kf-batch.svg)](/assets/notes/kafka/kf-batch.svg)

## 2. Batch 的大小与聚合等待条件 {#_2-batch-是聚合单位-不是必须装满才发}

`batch.size` 描述字节尺度的批次限制或目标机制，不是消息条数。librdkafka 另外有 `batch.num.messages`，它是生产者批次数量限制，不是消费者一次 Fetch 的条数。

低峰时批次可能装不满，客户端仍可根据聚合等待等条件发送。`linger.ms` 影响等待更多数据以凑批的时间，不是“从调用到 Broker 成功”的完整上界。背压、元数据获取、连接、重试、节流和确认都可能使总耗时更长。

## 3. 先按分区理解批次收益

如果记录被分散到很多分区，每个分区的速率很低，即使总量很大，各自的批次也未必饱满。分区数、Key 分布、空 Key 策略和分区器会影响批次聚合；不能只看应用总 QPS。

教学推演：一个分区每秒 1000 条、平均每条 500 字节，约产生 0.5MB/s 的原始内容。等待 5ms 期间大约只有数条，不会因为 batch.size 写了几十 KB 就自动出现足量记录。这是量级估算，不包含突发、头部和压缩成本，也不是性能承诺。

## 4. 压缩是 CPU、网络与存储的交换

批次压缩可以减少网络传输量和存储字节数，对重复内容通常更有效。具体收益取决于算法、数据分布和压缩级别，客户端与 Broker 也需要支持对应格式。CPU 已满时，增加压缩开销可能使尾延迟恶化。

比较配置时，应固定消息大小分布、Key 热度、分区数、可靠性设置和测量时间窗，观测吞吐、p95/p99、CPU、队列及网络。吞吐能力需要在具体机器、配置与负载下测量，历史单次数字只代表其对应环境。

## 5. 队列与消息大小有多个约束层

本地队列条数和字节数、批次限制、单请求限制、Broker/Topic 接收限制以及消费者 Fetch 限制分别约束不同层次。不能把 Java 的 max.request.size 直接复制成 C 配置名，也不能把压缩后和压缩前的大小简单混加。

出现 Queue Full 时，应先检查输入速率、回调是否得到处理，以及远端是否存在节流或故障。应对措施包括有界排队、上游背压和可观测的失败策略，而不是不断增加内存，直到进程崩溃。

## 参考

- [Java Producer 配置](https://kafka.apache.org/39/configuration/producer-configs/)
- [librdkafka v2.8.0 配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)
