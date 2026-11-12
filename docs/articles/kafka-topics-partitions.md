---
id: kafka-topics-partitions
title: 第 2 章：Topic、Partition、Key 与顺序
description: "一个分区是一条独立日志。多个分区让数据和负载可以分布在不同 Broker 上，也给消费组提供可分配的并行单元。一个 Broker 可以承载很多分区，一个 Topic 也可以跨多个 Broker；两者不存在“一台机器对应一个 Topic”的固定关系。"
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
order: 2
---

# 第 2 章：Topic、Partition、Key 与顺序

> 版本基线：Apache Kafka Broker / Java Client 3.9，固定源码为 3.9.0；C 客户端为 librdkafka v2.8.0。路由计算与集群发送实验分别标注。
>
> 学习目标：理解分区的并行单位、Key 的路由规则，以及日志顺序与业务完成顺序之间的关系。

## 1. 一个 Topic 为什么要拆分

一个分区是一条独立日志。多个分区让数据和负载可以分布在不同 Broker 上，也给消费组提供可分配的并行单元。一个 Broker 可以承载很多分区，一个 Topic 也可以跨多个 Broker；两者不存在“一台机器对应一个 Topic”的固定关系。

沿用[第 1 章](/articles/kafka-log-model.html)的定义：Topic（主题）命名事件流，Partition（分区）保存局部有序的 Log（日志），Broker（服务节点）承载日志副本；Consumer Group（消费组）把分区分配给成员。下面增加 Key（键）：它是记录的可选字节字段，可以作为选择目标分区的输入。

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

### 从业务 Key 到分区编号

Partitioner（分区器）解决“这条记录应该追加到哪条日志”的问题。Kafka Java 3.9.0 的 `KafkaProducer.partition()` 按以下优先级选择：

1. 记录显式指定 Partition 时，采用该编号。
2. 配置自定义 `partitioner.class` 时，调用该分区器。
3. 否则，序列化后的 Key 非 `null`，且 `partitioner.ignore.keys=false` 时，调用 `BuiltInPartitioner.partitionForKey()`。
4. 其余交由内置的无 Key 分区路径；它包含批次粘性及可选自适应负载分配，不能解释成“每条轮询一次”。

在第 3 条路径中，`StringSerializer`（字符串序列化器）默认将字符串编码为 UTF-8 字节，例如 ASCII 字符组成的 `order-42` 为 `6f 72 64 65 72 2d 34 32`。随后使用以下公式：

```text
Java 3.9.0 内置有 Key 路径（实现说明，不是通用客户端协议）：
h = Utils.murmur2(serializedKey)            // 32 位 Murmur2
positive = h & 0x7fffffff                  // Utils.toPositive；不是 abs(h)
partition = positive % numPartitions

librdkafka v2.8.0 默认 consistent_random，keylen > 0：
partition = rd_crc32(key, keylen) % partition_cnt

librdkafka v2.8.0 murmur2_random，key != NULL：
partition = (rd_murmur2(key, keylen) & 0x7fffffff) % partition_cnt
```

Murmur2 是非加密哈希算法，Kafka Java 路线用于稳定散列 Key；CRC32（Cyclic Redundancy Check, 32-bit，32 位循环冗余校验）在这里被用作分区散列函数。两者都不是订单唯一性或安全校验机制，通常产生不同的整数。只要字节、算法、分区数和路径不变，相同 Key 就得到相同余数；哈希碰撞还会使不同 Key 共享分区。`murmur2_random` 对有 Key 映射兼容 Java，不代表无 Key 的批次选择也完全相同。

### Null、零长度 Key 与空字符串

| 输入                             | Java 3.9 内置路径                    | librdkafka 2.8 默认 `consistent_random`   | librdkafka `murmur2_random`    |
| -------------------------------- | ------------------------------------ | ----------------------------------------- | ------------------------------ |
| `null` / C 的 `NULL`，不存在 Key | 无 Key 路径                          | 随机相关路径，可受粘性分区影响            | 随机相关路径，可受粘性分区影响 |
| 非 `null` 的零长度字节数组       | 对空字节数组做 Murmur2               | `keylen == 0`，进入随机相关路径           | 对空字节数组做 Murmur2         |
| 业务空字符串 `""`                | 默认 StringSerializer 产生零长度数组 | 应用传入非 NULL 指针且长度 0 时等同上一行 | 同左，但路由使用本列规则       |

业务空字符串不是天然的 Null；如果应用序列化成 JSON 的两个引号，实际字节又会变成 `22 22`。应同时记录指针/Null 状态、字节长度和十六进制值。librdkafka 的 `sticky.partitioning.linger.ms` 还影响部分无 Key 分配，不能承诺逐条随机或固定均匀。

![业务 Key、客户端路由、日志与业务处理顺序](/assets/notes/kafka/kf-key-review.svg)

[放大查看 Key 路由图](/assets/notes/kafka/kf-key-review.svg)。

## 3. 发起、日志追加与业务完成的三种顺序 {#_3-三种顺序不能混在一起}

第一种是应用发起顺序：两个线程同时提交时，业务是否已定义先后关系？第二种是分区日志顺序：记录追加后按该分区的 Offset 排列。第三种是业务效果完成顺序：消费者把任务交给线程池后，较晚读取的任务可能先写完数据库。

因此，“同分区由同一个消费者负责”不等于“业务效果必然串行”。若订单必须先创建再支付，消费侧可以按分区或业务 Key 串行，或在下游校验状态版本；不要仅依赖客户端读取顺序。

### A、B 两个事件的时间线

以下为教学时间线，A、B 属于同一订单，均进入 P1，假设本次正常追加且没有重试重排：

| 阶段                      | 先发生                | 后发生                | 保证的范围                                          |
| ------------------------- | --------------------- | --------------------- | --------------------------------------------------- |
| Producer 业务发起         | `send(A)`             | `send(B)`             | 应用线程先后调用；多个线程需额外定义同步关系        |
| Broker 日志追加           | A → Offset 10         | B → Offset 11         | 同一分区内的日志位置顺序                            |
| Consumer 读取后提交线程池 | 任务 A 开始，耗时较长 | 任务 B 开始，很快完成 | 读取顺序没有约束后台完成顺序                        |
| 业务完成                  | B 先写完数据库        | A 后写完数据库        | 与日志顺序相反；若直接提交 12，可能越过尚未成功的 A |

Producer 重试影响的是**最终追加顺序和重复风险**：关闭幂等且允许多个在途请求（`max.in.flight.requests.per.connection > 1`）时，较早批次失败、较晚批次先成功、早批次重试，可能重排。Java 3.9 开启幂等并满足配置约束（`acks=all`、允许重试、在途请求数不超过 5）时，客户端与 Broker 利用生产者 ID、Epoch（代际编号）及分区序列号保持该生产者单分区的相应顺序和去重保证。默认启用也可能因冲突配置而关闭或报错，应记录实际配置。它不负责修复消费线程池顺序，也不为多个独立 Producer 建立业务总顺序。

多个 Producer 同时发送同一 Key，Broker 仍会给到达同一分区的记录建立追加顺序，但无法仅从 Key 判断哪台服务的“创建”应该先于另一台服务的“支付”。需要由业务事件版本、单写者或外部串行约束表达这个先后关系。消费者应只提交连续成功的位置，并正确处理重平衡时仍在运行的任务，详见[重试与幂等](/articles/kafka-retries-idempotency.html)。

## 4. 扩分区为什么可能破坏原有路由假设

教学例子：原先按某种固定哈希对 4 个分区取模，扩为 6 个后，部分 Key 的结果会变化。旧记录仍留在旧分区，新记录可能进入新分区，于是同一订单的历史与后续事件可能跨分区。扩容不自动搬运已有日志来重新建立单 Key 总顺序。

假设某种算法的非负哈希值恰好为 17：`17 % 4 = 1`，扩容后 `17 % 6 = 5`。原来的 A 留在 P1，后来的 B 可能写入 P5，两条日志各有自己的 Offset，消费组可以同时处理它们。**17 只是简化教学输入，不是声称 `order-42` 的 Murmur2 或 CRC32 等于 17。** 客户端元数据刷新有时间差，切换期间旧分区数与新分区数还可能被不同客户端同时使用。

若必须维持单订单顺序，可以先停止或隔离旧路由的写入，等待旧流量处理到明确的完成边界，再协调所有生产者和消费者切换；也可以新建版本化 Topic，携带业务序列号，在确认旧版本处理完成后启用新版本。采用固定虚拟分桶或自定义分区器时，还要管理映射版本和切换屏障。迁移方案必须覆盖在途请求、重试、回滚及未完成消费；仅“把分区数改大”不能建立跨分区顺序。这里给出设计方向，不在现有集群执行扩容。

增加 Broker 则是另一件事：它增加了承载资源，但不一定会自动改变现有分区的分配或数量。若要迁移已有分区，需要明确的重分配计划。扩容前应先区分“增加机器”“调整副本位置”“增加分区”这三个动作。

## 5. 命名、模式与分区策略一起设计

Topic 可按业务事实域命名，避免把每个用户或每个订单都变成独立 Topic。Value 模式要考虑兼容性，Key 编码变化也应按协议变更管理。消费者遇到未知字段、缺字段或新事件类型时，应有明确的兼容或隔离处理。

热点 Key 也需要按业务处理。假设 90% 的记录都使用 Key `global`，在稳定的有 Key 哈希路径下，这 90% 会集中到一个分区；把 4 分区增到 40 分区不会自动把这个 Key 拆散。若 `global` 只是误用，应改为真正需要共同排序的实体；若业务确实要求它全局有序，就要接受单通道约束，或经业务允许拆成子 Key 并设计合并规则。随机加盐虽然可能分摊流量，也会改变顺序与聚合语义。

自检问题：相同订单由 Java 和 C 服务同时发布，为什么可能落到不同分区？正确答案应同时考虑算法、字符编码、分区数、显式分区和 Key 是否真的相同，而不是只检查字符串显示是否一致。

### 实验：同一 Key 的 Java 与 C 路由对照

准备隔离的 Kafka 3.9 集群，创建全新 4 分区 Topic `orders-routing-r1`，复制因子按实验集群配置。使用发行包自带的 Java Client 3.9.0 JAR、JDK，以及已安装的 librdkafka v2.8.0 开发库。示例没有自定义分区器、拦截器或显式 Partition，均发送 UTF-8 / ASCII 字节 `order-42`。

下载并解压[路由教学示例包](/examples/kafka-review/kafka-routing-examples.zip)，其中包含 `RouteJava.java`、`route_librdkafka.c` 和 `route_calculation.py`。它们是本章的独立教学程序，不是摘录的官方源码。Java 打印 `RecordMetadata`（写入结果元数据），C 通过 delivery report（投递结果回调）打印最终分区；两者都检查客户端版本。以下为 Linux/Bash 步骤：

```bash
# KAFKA_HOME 指向解压的 Kafka 3.9.0 发行包。
"$KAFKA_HOME/bin/kafka-topics.sh" --bootstrap-server localhost:9092 \
  --create --topic orders-routing-r1 --partitions 4 --replication-factor 1
javac -cp "$KAFKA_HOME/libs/*" RouteJava.java
java -cp ".:$KAFKA_HOME/libs/*" RouteJava localhost:9092 orders-routing-r1

cc -Wall -Wextra route_librdkafka.c -o route_librdkafka \
  $(pkg-config --cflags --libs rdkafka)
./route_librdkafka localhost:9092 orders-routing-r1 consistent_random
./route_librdkafka localhost:9092 orders-routing-r1 murmur2_random
```

每次保存客户端版本、分区器配置、Key 长度与十六进制字节、Topic 分区数、成功回调的 Partition / Offset 或错误。先确认 Topic 确实为 4 分区，再对照以下**本地算法计算**；不能把计算结果当作投递回调：

| 同一组字节 `6f726465722d3432` | 路由输入整数 | 4 分区的计算结果 |
| ----------------------------- | ------------ | ---------------- |
| Java Murmur2，清除符号位      | 501153024    | 0                |
| C 默认 CRC32                  | 1475806942   | 2                |
| C `murmur2_random`            | 501153024    | 0                |

离线计算可使用示例包中的 `route_calculation.py`（Python 标准库；按固定版本算法编写的教学实现）。它还以 librdkafka 源码自带向量校验 Murmur2，并展示空字节 Key 的边界。真实路由仍以成功发送结果为准；若不一致，先检查版本、序列化字节、分区数量和实际生效分区器，不从预期反推实测结果。

## 参考

- [Java 3.9 Producer 配置](https://kafka.apache.org/39/configuration/producer-configs/)
- [librdkafka v2.8.0 分区器与配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)
- [Kafka 3.9.0 KafkaProducer.partition：显式分区、分区器、Key 的优先级](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/KafkaProducer.java)
- [Kafka 3.9.0 BuiltInPartitioner.partitionForKey](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/internals/BuiltInPartitioner.java)
- [Kafka 3.9.0 Utils：murmur2 与 toPositive](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/common/utils/Utils.java)
- [librdkafka v2.8.0 rdkafka_msg.c：consistent_random 与 murmur2_random](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka_msg.c)
- [librdkafka v2.8.0 rdmurmur2.c：算法与测试向量](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdmurmur2.c)
- [KIP-794：Java 内置无 Key 粘性分区的设计背景](https://cwiki.apache.org/confluence/display/KAFKA/KIP-794%3A+Strictly+Uniform+Sticky+Partitioner)
