---
id: kafka-producer-batching
title: 第 8 章：生产者路由、批次与压缩
description: "应用先把业务对象序列化成字节，客户端再确定目标分区、将记录排入队列，最后由后台 I/O 发送。API 是否阻塞、何时报告本地错误，以及如何获取最终结果，都取决于具体客户端。"
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
order: 8
---

# 第 8 章：生产者路由、批次与压缩

> 版本基线：Kafka Broker / Java Client 3.9，固定源码 3.9.0；librdkafka v2.8.0。默认值、队列实现与回调路径按客户端分别说明。
>
> 学习目标：串联序列化、分区路由、本地排队、批次发送与投递报告，再结合延迟和资源预算理解批次参数。

## 1. 从本地入队到投递报告 {#_1-send-成功可能只表示接受了任务}

应用先把业务对象序列化成字节，客户端再确定目标分区、将记录排入队列，最后由后台 I/O 发送。API 是否阻塞、何时报告本地错误，以及如何获取最终结果，都取决于具体客户端。

对于异步生产者，“函数返回没有错误”常常不等于远端已经可靠接受。Java Future 或回调、librdkafka Delivery Report 都需要按接口契约检查。不能丢弃全部回调，再用程序正常退出证明发送成功。

[![Kafka Producer：入队、发送和确认分层](/assets/notes/kafka/kf-batch-review.svg)](/assets/notes/kafka/kf-batch-review.svg)

### Java 3.9 的完整发送链

RecordAccumulator（记录累积器）维护待发送的分区批次，ProducerBatch（生产批次）聚合同一 TopicPartition（主题分区）的记录；后台 Sender（发送线程）把就绪批次组织成 Broker 请求。一个 Produce Request（生产请求）可以带多个分区的批次，Batch 不等于整份网络请求。

1. `KafkaProducer.send()` / `doSend()` 取得适用元数据、序列化 Key/Value，检查大小并计算分区。显式 Partition、自定义分区器和有 Key 路由规则见[第 2 章](/articles/kafka-topics-partitions.html)。`send()` 不是绝对不阻塞：元数据和缓冲分配等等待受 `max.block.ms` 等约束。
2. `RecordAccumulator.append()` 尝试追加到该分区已有批次，必要时分配缓冲区建立新 ProducerBatch，返回与该条记录对应的 Future（异步结果）。内置无 Key 路径还可能在这里完成分区选择，不能把分区器输出 UNKNOWN 直接解释为已经选好某个分区。
3. `RecordAccumulator.ready()` 判断哪些 Broker 的批次具备发送条件：包括批次填充、linger 到期、内存压力、flush/关闭等因素，还要考虑重试退避。就绪不代表连接已就绪，更不表示远端已接受。
4. `Sender.run()` 的循环推动网络与事务/幂等状态，使用 `drain()` 按 Broker 和分区取出适用批次，受请求大小、连接可用性、在途状态等限制，构造 ProduceRequest。
5. Broker 响应进入 Sender 的响应处理路径，例如 `handleProduceResponse()`；成功时完成批次内 Future/Callback（回调），可重试错误按条件重新排队，超时、致命或不可重试错误按相应路径完成失败。

Sticky Partitioning（粘性分区）让适用的无 Key 流量在一段批次聚合期间偏向同一分区，以提高聚合机会；Java 3.9 内置实现还有自适应分配逻辑。它不保证所有无 Key 消息轮询均匀，也不改变有 Key 的默认哈希规则。

### librdkafka v2.8.0 的另一套实现

`rd_kafka_producev()` 接收已编码的 Key/Value 指针等参数，检查并接受到本地队列；C 库不会自动理解业务对象并替应用完成 JSON 序列化。通常由后台 Broker 线程批量组装与发送请求，应用通过 `rd_kafka_poll()` 消费 Delivery Report（投递结果报告）等回调，不能把它称为 Java Sender 或 RecordAccumulator 的同一实现。

一般元数据已知路径先确定分区，再进入相应队列。**目标分区暂时未知时，librdkafka 等客户端存在内部待决/未分配队列**，之后根据元数据重新分配；它不能称作已知目标分区的 Batch 队列，也不能据此说所有客户端都必须先决定分区才能接收应用调用。

`rd_kafka_poll()` 不负责取代后台网络发送，但不及时服务回调会拖延报告处理及资源释放等行为。`rd_kafka_flush()` 等待尚未完成的消息，通常也服务相关回调，并可越过普通 linger 聚合等待；若超时，必须检查返回值及未完成数量。随后 `destroy` 不会把未完成消息神奇地变成成功；需要有限等待、保留失败/未知记录，必要时按明确的 purge（清除排队/在途消息）策略处理。清除在途消息也不表示 Broker 从未写入。

## 2. Batch 的大小与聚合等待条件 {#_2-batch-是聚合单位-不是必须装满才发}

`batch.size` 描述字节尺度的批次限制或目标机制，不是消息条数。librdkafka 另外有 `batch.num.messages`，它是生产者批次数量限制，不是消费者一次 Fetch 的条数。

低峰时批次可能装不满，客户端仍可根据聚合等待等条件发送。`linger.ms` 影响等待更多数据以凑批的时间，不是“从调用到 Broker 成功”的完整上界。背压、元数据获取、连接、重试、节流和确认都可能使总耗时更长。

| 配置                 | Java Client 3.9 默认 | librdkafka v2.8.0 默认             | 实现边界                                                                                                                                                                           |
| -------------------- | -------------------- | ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `batch.size`         | 16384B               | 1000000B                           | Java 是分区批次缓冲/目标尺度，首条较大记录可单独获得更大缓冲；不是绝对的单消息上限。C 计入相应协议开销，先加入首条，再应用批次上限，避免仅因首条超过 batch.size 就永远无法组成批次 |
| `linger.ms`          | 0ms                  | 5ms，别名 `queue.buffering.max.ms` | 都是聚合因素，但调度、回压及发送路径不同；Java 3.9 的 0 仍可能因已有积压自然形成批次                                                                                               |
| `batch.num.messages` | 没有同名直接配置     | 10000 条                           | C 的每批记录数上限，还同时受字节及消息/请求限制                                                                                                                                    |

Java 4.0 将 `linger.ms` 的默认值改为 5 ms，Java 3.9 的默认值仍为 0 ms。单条记录超过 batch.size 并不自动获得通行权，其他客户端、Broker 和 Topic 大小限制仍可能拒绝。

## 3. 先按分区理解批次收益

如果记录被分散到很多分区，每个分区的速率很低，即使总量很大，各自的批次也未必饱满。分区数、Key 分布、空 Key 策略和分区器会影响批次聚合；不能只看应用总 QPS。

教学推演：一个分区每秒 1000 条、平均每条 500 字节，约产生 0.5MB/s 的原始内容。等待 5ms 期间大约只有数条，不会因为 batch.size 写了几十 KB 就自动出现足量记录。这是量级估算，不包含突发、头部和压缩成本，也不是性能承诺。

把这个近似算例具体化：假设总输入均匀为 1000 条/s、平均 Payload（业务载荷）500B，等待窗口为 0.005s，则窗口内的平均到达量约 `1000 × 0.005 = 5` 条，原始 Payload 约 `5 × 500 = 2500B`。

若均匀分散到 10 个分区，每个约 100 条/s，同样窗口内平均只有 0.5 条、250B。0.5 是统计期望，不是存在“半条消息”，实际许多窗口没有记录，部分窗口有一条或更多。窗口起始记录、真实到达过程、Sticky 分配、调度与批次头部会改变实际批量；不能用这个计算直接断言平均 Batch 就是 2500B 或 250B。相同 Key 全落一个分区时，更不能按十等分计算。

聚合充分可能减少每条记录分摊的请求/协议开销、改善压缩；但一个请求可以包含多个分区，因此“分区批次翻倍就必然请求数翻倍”也不成立。更大批次或更长等待还会增加等待延迟、内存占用、失败重试时的工作量及 CPU 处理突发，需要结合吞吐和尾延迟一起评估。

## 4. 压缩是 CPU、网络与存储的交换

批次压缩可以减少网络传输量和存储字节数，对重复内容通常更有效。具体收益取决于算法、数据分布和压缩级别，客户端与 Broker 也需要支持对应格式。CPU 已满时，增加压缩开销可能使尾延迟恶化。

比较配置时，应固定消息大小分布、Key 热度、分区数、可靠性设置和测量时间窗，观测吞吐、p95/p99、CPU、队列及网络。吞吐能力需要在具体机器、配置与负载下测量，历史单次数字只代表其对应环境。

### none / lz4 / zstd 的对照实验

**可复现方案，未实测**：在隔离 Kafka 3.9 环境中使用全新 Topic，先分别准备 1 分区和 10 分区版本。固定 RF、acks、幂等、输入内容、消息大小分布、Key/分区策略、1000 条/s 目标速率、预热与采样窗口，轮换 `compression.type=none/lz4/zstd`，每组重复多次。重复字符串和随机字节的可压缩性不同，应分别注明，不能只靠一组重复数据宣称算法普遍更好。

Java 3.9 发行包提供性能测试工具，以下命令只展示一组输入；Topic 需预先在测试环境创建，认证参数按环境提供：

```bash
bin/kafka-producer-perf-test.sh --topic r3-batch-1p \
  --num-records 60000 --record-size 500 --throughput 1000 \
  --producer-props bootstrap.servers=localhost:9092 \
    acks=all enable.idempotence=true linger.ms=5 \
    batch.size=16384 compression.type=lz4 \
  --print-metrics
```

每次只改变一个因素，记录实际客户端版本、有效配置和实际发送吞吐。Java 工具的无 Key 默认路由可能是粘性的，10 分区 Topic 不自动满足上节“均匀分流”假设；要验证均匀算例，应额外使用显式分区的负载程序。C 客户端应使用同等输入/调度负载及其统计接口，不能把 Java 工具的指标当作 C 的实测。

| 指标                 | 采集口径                                                                      |
| -------------------- | ----------------------------------------------------------------------------- |
| 实际发送吞吐         | 成功确认的记录数/时间，另计应用产生数、本地接受数、最终错误；不能只报目标限速 |
| p50 / p95 / p99 延迟 | 百分位延迟；明确从入队前到结果回调，或从请求发出到响应，不能混用              |
| CPU 利用率           | 客户端与 Broker 分别采集，区分压缩、网络与后台负载；不是从压缩比推算          |
| 网络发送字节         | 同一时间窗的客户端网络量，注明是否含协议/重试，不只统计压缩后 Payload         |
| 平均 Batch 大小      | Java `batch-size-avg` 等；C 统计中的相应批次指标需按其定义解读                |
| 队列积压             | Java 缓冲等待/可用字节及 C 队列数量/字节、回调积压；报告最大值及变化          |
| 错误与重试           | 最终失败与中间协议重试分开计数；避免只保留成功样本造成延迟偏差                |

此表是待采集清单，没有填入性能结果。默认 batch.size 的跨客户端对比和统一大小的对比是两组不同问题，应分别安排。

## 5. 队列与消息大小有多个约束层

本地队列条数和字节数、批次限制、单请求限制、Broker/Topic 接收限制以及消费者 Fetch 限制分别约束不同层次。不能把 Java 的 max.request.size 直接复制成 C 配置名，也不能把压缩后和压缩前的大小简单混加。

出现 Queue Full 时，应先检查输入速率、回调是否得到处理，以及远端是否存在节流或故障。应对措施包括有界排队、上游背压和可观测的失败策略，而不是不断增加内存，直到进程崩溃。

### 从单条记录到队列的限制层次

| 层次              | Java 3.9                                                     | librdkafka v2.8.0 / 服务端                                                                              | 需明确的字节口径                                                               |
| ----------------- | ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| 本地积压          | `buffer.memory` 与 `max.block.ms`，不是所有内存的硬总上限    | `queue.buffering.max.messages` 默认 100000；`queue.buffering.max.kbytes` 默认 1048576 KiB，字节限制优先 | 未完成消息/缓冲预算，不是网络单请求大小                                        |
| 分区批次          | `batch.size`                                                 | `batch.size`、`batch.num.messages`                                                                      | 记录和编码开销；不是只加 Key/Value 长度                                        |
| Produce 请求      | `max.request.size`                                           | C 的 `message.max.bytes` 限制相应协议请求，存在首条/协议开销边界                                        | Java 配置同时对未压缩记录批次形成约束，不应与 C 完全等同                       |
| Broker/Topic 接收 | Broker `message.max.bytes`；Topic `max.message.bytes` 可覆盖 | 同一服务端约束，两种客户端都需遵守                                                                      | 现代配置约束最大记录批次，适用时按压缩后的批次；还要考虑整个网络请求限制       |
| 消费读取          | `max.partition.fetch.bytes`、`fetch.max.bytes` 等            | C 对应配置需另外核对                                                                                    | 一些读取限制允许首个较大批次例外，以避免无法前进；不要误当发送端所有限制都失效 |

Backpressure（背压）把下游处理不及的信号传回上游，限制输入速度。C 的 `RD_KAFKA_RESP_ERR__QUEUE_FULL` 通常表示此次没有入队；先 poll 已有报告、有限退避，再按预算重试同一次入队。Java 缓冲不足可能阻塞，超过相应等待预算后失败；不能把 C 的错误码直接套给 Java。

队列不足时可降低产生速率、拒绝新请求、写入有界可靠缓冲或按已批准策略降载，分别记录失败和积压并告警。只加大队列会把错误变成更长延迟或内存风险；立即无限循环重试又会占用 CPU、放大故障。对最终交付失败应转入[第 9 章的状态判断](/articles/kafka-retries-idempotency.html)，不能当作本地入队失败统一重发。

### Java 与 C 最小发送示例

下载[第 8 章发送示例包](/examples/kafka-review/batching-examples.zip)，包含 `BatchJava.java` 与 `batch_librdkafka.c`。前者使用 Kafka Java Client 3.9.0，后者要求 librdkafka v2.8.0，均输出最终结果，不以入队返回代替成功。它们是教学发送程序，不是性能测试工具；运行依赖和集群步骤尚未实测。

```bash
javac -cp "$KAFKA_HOME/libs/*" BatchJava.java
java -cp ".:$KAFKA_HOME/libs/*" BatchJava localhost:9092 r3-batch-1p lz4

cc -Wall -Wextra batch_librdkafka.c -o batch_librdkafka \
  $(pkg-config --cflags --libs rdkafka)
./batch_librdkafka localhost:9092 r3-batch-1p lz4
```

测试 Topic 要提前创建。Java 使用 Future/Callback 观察结果，C 持续 poll 并检查 flush；C 回调中还打印第 9 章解释的消息持久化状态。运行返回失败时保留输出，不能因示例选择了有限 purge/关闭路径而认定在途记录从未写入。

## 参考

- [Java Producer 配置](https://kafka.apache.org/39/configuration/producer-configs/)
- [librdkafka v2.8.0 配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)
- [KafkaProducer.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java)：`send` / `doSend`。
- [RecordAccumulator.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/internals/RecordAccumulator.java)：`append` / `ready` / `drain`。
- [ProducerBatch.java](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/internals/ProducerBatch.java) / [Sender.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/internals/Sender.java)：批次完成、`run` 与 Produce 响应处理。
- [librdkafka v2.8.0 INTRODUCTION](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md) / [rdkafka_broker.c](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka_broker.c)：后台发送、队列及回调机制。
