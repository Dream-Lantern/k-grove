---
id: kafka-transactions
title: 第 14 章：事务、read_committed 与可见边界
description: "Kafka 事务生产者在一个事务中发送到多个 Topic-Partition，并可把适用输入消费位点一起提交。成功提交后，按事务隔离读取的下游才能看到相应已提交记录；中止后这些事务记录不会作为正常已提交业务输出返回。"
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
order: 14
---

# 第 14 章：事务、read_committed 与可见边界

> 版本基线：Kafka Broker 3.9、Java Client 3.9 与 librdkafka v2.8.0。
>
> 学习目标：把事务写入、复制提交和消费者可见性分开。本章统一使用“下一位置／排他上界”口径，避免各种文档里最后一条与下一条差一的问题。

## 1. 事务可以跨多个分区

Kafka 事务生产者在一个事务中发送到多个 Topic-Partition，并可把适用输入消费位点一起提交。成功提交后，按事务隔离读取的下游才能看到相应已提交记录；中止后这些事务记录不会作为正常已提交业务输出返回。

“看不到”不等于所有物理字节立刻从磁盘删除。日志里仍有事务相关记录与控制信息，需要按协议解释。消费者若使用不同隔离级别，观察结果也不同。

### 谁协调一次事务

以订单支付为例，生产者在同一事务中把确认事件写入 P0，把对账事件写入 P1。以下是 Kafka 3.9 的教学流程，省略协议版本、重试和恢复分支。

1. Transactional ID（事务生产者逻辑身份）由应用配置，同一逻辑实例重启后复用，不同活跃实例使用不同 ID。Broker 根据该 ID 定位 Transaction Coordinator（事务协调器）。它负责跨分区推进同一个提交或中止决定。
2. 初始化时，协调器处理该 ID 遗留的事务，并建立当前 Producer ID（生产者标识，PID）和 Producer Epoch（生产者世代）。写入批次携带 PID 和世代。新实例接管时，协调器更新身份或世代，协议参与方拒绝过期生产者的请求。这个过程称为 Producer Fencing（旧生产者隔离）。
3. 生产者将涉及的分区纳入事务。协调器在内部 `__transaction_state` 日志持久化 Transaction State（事务状态），包括事务身份、参与分区和当前状态。事务性输入位点涉及保存组位点的 `__consumer_offsets` 分区。
4. 协调器持久化提交或中止决定，再向参与分区发送 Transaction Marker（事务控制标记）。各分区写入相应控制批次，协调器在标记写入流程完成后记录终态。发生故障时，接管协调器可依据持久化状态继续推进。消费者读取的是各自分区的稳定前缀，标记在各分区推进的时机可以不同。

### 跨分区提交与分批读取的区别 {#原子提交不是一次poll的跨分区快照}

一次事务写入 P0 和 P1 并提交，并不保证全部记录会在同一个 poll 中同时返回，也不保证某个消费者订阅了所有相关分区。组内由 A 处理 P0、B 处理 P1 时，A 可能已经更新业务，而 B 还没有取得或处理对应记录。

read_committed 约束记录的提交可见性，不会替多个实例建立跨分区一致快照，更不会建立外部数据库事务。seek、保留与 compact 也可能使历史读取只覆盖事务的一部分。若需要成组展示或执行，应设计事务/业务聚合 ID、完成标记、版本或其他明确协议。[Kafka 3.9 Consumer事务读取](https://kafka.apache.org/39/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html)

## 2. 三个上界按统一口径解释

LEO 是某副本日志末端的下一位置。HW 是复制提交相关上界。LSO 在这里指 Last Stable Offset，即适用的稳定前缀上界，不是 Log Start Offset，也不是“日志里最后一个字节”。

![复制与事务的可见边界](/assets/notes/kafka/kf-visibility.svg)

在有开放事务时，稳定前缀受最早未完成事务等条件约束；通常 LSO≤HW≤Leader LEO。没有开放事务阻挡时，LSO 可以等于 HW。即使日志后面还有非事务数据，也不能认为 read_committed 总能越过开放事务直接返回它。

| 边界                                      | 图中值 | 含义                                                   |
| ----------------------------------------- | ------ | ------------------------------------------------------ |
| Log Start Offset（日志起始偏移量）        | 0      | 当前保留范围的起点，包含该位置                         |
| Log End Offset（日志末端偏移量，LEO）     | 12     | Leader 已追加范围的排他上界                            |
| High Watermark（高水位，HW）              | 10     | 复制提交的排他上界，消费者不会读取 `[10, 12)`          |
| Last Stable Offset（最后稳定偏移量，LSO） | 6      | 事务稳定前缀的排他上界，此处受 Offset 6 开始的事务限制 |

`[0, 6)` 的事务结果已稳定，但仍可能包含中止记录或控制批次。`[6, 10)` 已达到复制提交边界，仍被开放事务挡在稳定前缀之外。`read_committed` 按分区顺序读取，如果跳到后面的普通记录，恢复位置可能越过最终会提交的事务记录。

假设期间没有其他写入或开放事务，事务标记追加在 12，则 Leader LEO 先变为 13。标记达到复制提交边界后，HW 与 LSO 才都能到达 13。提交时事务记录变为可见，中止时则继续过滤该事务记录。两种结果都会放行稳定范围里的后续普通记录。

## 3. 开放事务对 read_committed 可见性的影响 {#_3-read-committed-不只是过滤-aborted}

假设位置 10 开始的事务迟迟未完成，后面又追加了其他记录。为了保持适用的日志顺序，read_committed 可能等待事务状态确定，而不是只删除已知 aborted 记录后返回全部尾部。

因此消费者“没有新消息”可能由事务可见边界造成，不一定是生产者没有写入。诊断时应比较输入写入、HW、稳定边界和事务状态，不要仅通过增大 Fetch 字节数试图解决。

以下沿用图中的边界。表中“返回”假设读取位置已到达对应范围，且记录仍保留。

| P0 Offset | 日志内容             | `read_uncommitted` | `read_committed`                 |
| --------- | -------------------- | ------------------ | -------------------------------- |
| 0         | 普通订单事件         | 返回               | 返回                             |
| 1         | 已提交事务记录       | 返回               | 返回                             |
| 3         | 已中止事务记录       | 返回               | 过滤                             |
| 5         | 事务控制标记         | 跳过               | 跳过                             |
| 6         | 未结束的事务记录     | 返回               | 等待，稳定后按提交或中止结果处理 |
| 8         | 开放事务后的普通记录 | 返回               | 等待，稳定边界越过后返回         |
| 10        | 尚未达到 HW 的记录   | 等待复制提交       | 等待复制提交及事务稳定           |

已中止记录仍可留在日志中，控制标记由客户端处理而不交付业务。应用可见 Offset 因此可能不连续。P1 的对账记录也按 P1 的稳定边界读取，两个 Worker 如需共同更新业务，应按事务或订单聚合 ID 等待完整输入，再原子应用聚合结果。

排查停滞时，可对同一分区用两种隔离级别查询 Java `endOffsets()`。前者看到 HW，后者看到 LSO。若差距持续存在，查看 Broker 上事务的状态、参与分区及生产者超时或错误日志。还需区分没有新输入、复制滞后和消费者自身没有继续 Poll。

## 4. 事务生产者的生命周期

事务身份用于识别跨会话的逻辑生产者并隔离僵尸实例。需要初始化事务能力、开始事务、产生输出、加入安全消费位点并提交，或者按错误分类中止。事务 ID 的稳定性与不同活动实例的唯一性必须一起设计。

错误分为可重试、要求中止和致命等类别，不能遇到任何错误都再次 commit。事务超时也不能保障任意长的业务任务：开放事务持续过久，会影响下游可见性和资源占用。

Java 3.9 先配置 `transactional.id` 和序列化器，再创建 `KafkaProducer`。每个实例先成功调用一次 `initTransactions()`，随后按批次 `beginTransaction()`、`send()`。Kafka 到 Kafka 的处理关闭输入 Consumer 的 `enable.auto.commit`，不单独提交同一批输入。输出全部准备好后，把仍持有的各分区安全下一位置作为 `Map<TopicPartition, OffsetAndMetadata>` 纳入事务：

```java
producer.sendOffsetsToTransaction(offsets, consumer.groupMetadata());
producer.commitTransaction();
```

组元数据包含比只传 `group.id` 更完整的成员身份，协调器可据此隔离过期成员。完整元数据要求 Broker 至少为 2.5，Kafka 3.9 符合要求。Java 3.9 仍有只传组 ID 的旧重载，新的实现优先使用组元数据重载。位点随事务提交生效。中止后，Consumer 本地读取位置不会自动回退，应清理本批缓存并按当前有效分配从已提交位置恢复。下游使用 `read_committed` 读取输出。

| 失败类型                                       | Java 3.9 的处理                                                                                                |
| ---------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| 临时发送错误                                   | Producer 在适用条件和时限内内部重试。发送最终失败后按 API 错误分类处理，避免重新盲发同一业务记录               |
| 当前事务已不可提交，但实例仍可用               | 执行 `abortTransaction()`，恢复输入位置，再开始下一事务                                                        |
| 组所有权变化                                   | 若纳入位点时因成员失效收到 `CommitFailedException`，中止该事务并等待重新分配。旧任务不得用于推进新所有权的位点 |
| Fencing、无效生产者世代等致命状态              | 停止使用实例并关闭。确认逻辑身份应由谁持有，再决定是否新建实例                                                 |
| 事务超时                                       | 协调器可中止过久的开放事务。按具体 API 错误判断实例能否继续使用，恢复时从已提交输入位点重做                    |
| `commitTransaction()` 超时或被中断，结果不确定 | 按 Javadoc 可重试同一操作。若放弃重试则关闭实例，不能改做 Abort，因为提交可能已在进行                          |
| 进程崩溃                                       | 由该逻辑身份的继任者用相同 `transactional.id` 重新初始化，协调器完成遗留事务的处理，然后按实际已提交位点恢复   |

同理，`abortTransaction()` 结果不确定时按它自身的契约重试原操作或关闭。librdkafka v2.8.0 的事务 API 则返回错误对象，使用 `rd_kafka_error_is_retriable()`、`rd_kafka_error_txn_requires_abort()` 和 `rd_kafka_error_is_fatal()` 分类，用完销毁错误对象。

## 5. 两个默认值差异

Java 3.9 消费者默认 `read_uncommitted`，librdkafka v2.8.0 配置表中则默认 `read_committed`。不能把其中一个写成“Kafka 所有消费者默认”。实际部署仍应显式核对有效配置，封装库也可能覆盖默认值。

### 实践：观察事务提交和中止

使用 Kafka Broker 3.9、Java 17 和 Maven，确保 Broker 的事务状态日志可以建立并达到最小 ISR（In-Sync Replicas，同步副本集合）。默认配置需要足够的 Broker。单 Broker 教学环境可在内部 Topic 首次创建前将 `transaction.state.log.replication.factor` 和 `transaction.state.log.min.isr` 设为 1。每次使用一个新的空 Topic 和未被其他进程使用的事务 ID。

```bash
bin/kafka-topics.sh --bootstrap-server localhost:9092 --create \
  --topic review-txn-orders --partitions 1 --replication-factor 1

mvn dependency:copy -Dartifact=org.apache.kafka:kafka-clients:3.9.2 \
  -DoutputDirectory=lib
mvn dependency:copy -Dartifact=org.slf4j:slf4j-api:1.7.36 \
  -DoutputDirectory=lib
java -cp 'lib/*' TxnVisibility.java
```

把下面的代码保存为 `TxnVisibility.java`。实验只发送未压缩的字符串。两个消费者手动分配同一分区，从 0 读取且关闭自动提交，分别观察事务输出。实验关注可见性，因此没有输入组位点需要加入事务。

```java
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.clients.producer.KafkaProducer;
import org.apache.kafka.clients.producer.ProducerRecord;
import org.apache.kafka.common.TopicPartition;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.apache.kafka.common.serialization.StringSerializer;

class TxnVisibility {
    static final String BROKER = "localhost:9092";
    static final String TOPIC = "review-txn-orders";
    static final TopicPartition P0 = new TopicPartition(TOPIC, 0);

    static KafkaConsumer<String, String> reader(String isolation) {
        return new KafkaConsumer<>(Map.of(
            "bootstrap.servers", BROKER,
            "enable.auto.commit", false,
            "isolation.level", isolation
        ), new StringDeserializer(), new StringDeserializer());
    }

    static void expect(KafkaConsumer<String, String> reader,
                       long millis, String... expected) {
        var seen = new ArrayList<String>();
        long deadline = System.nanoTime() + Duration.ofMillis(millis).toNanos();
        do {
            reader.poll(Duration.ofMillis(100)).forEach(r -> seen.add(r.value()));
        } while (System.nanoTime() < deadline
                 && (expected.length == 0 || seen.size() < expected.length));
        if (!seen.equals(List.of(expected))) {
            throw new AssertionError("expected " + List.of(expected) + ", got " + seen);
        }
        System.out.println(seen);
    }

    public static void main(String[] args) throws Exception {
        var config = Map.<String, Object>of(
            "bootstrap.servers", BROKER,
            "transactional.id", "review-txn-orders-writer",
            "transaction.timeout.ms", 60_000,
            "compression.type", "none"
        );
        try (var producer = new KafkaProducer<>(config,
                 new StringSerializer(), new StringSerializer());
             var uncommitted = reader("read_uncommitted");
             var committed = reader("read_committed")) {
            for (var reader : List.of(uncommitted, committed)) {
                reader.assign(List.of(P0));
                reader.seek(P0, 0L);
                reader.endOffsets(List.of(P0));
            }
            producer.initTransactions();

            producer.beginTransaction();
            producer.send(new ProducerRecord<>(TOPIC, 0, "order-001", "payment")).get();
            expect(uncommitted, 5_000, "payment");
            expect(committed, 1_000);
            producer.commitTransaction();
            expect(committed, 5_000, "payment");

            producer.beginTransaction();
            producer.send(new ProducerRecord<>(TOPIC, 0, "order-001", "cancelled-test")).get();
            producer.abortTransaction();
            // 普通记录由另一个非事务生产者写入，证明读取已越过中止记录。
            try (var marker = new KafkaProducer<>(Map.of("bootstrap.servers", BROKER),
                     new StringSerializer(), new StringSerializer())) {
                marker.send(new ProducerRecord<>(TOPIC, 0, "order-001", "after-abort")).get();
            }
            expect(uncommitted, 5_000, "cancelled-test", "after-abort");
            expect(committed, 5_000, "after-abort");
        }
    }
}
```

预期五次观察依次得到 `[payment]`、空列表、`[payment]`、`[cancelled-test, after-abort]`、`[after-abort]`。空列表是事务开放期间的有界观察，提交后的读取和中止后的普通记录共同验证读取能继续。实验遇错直接退出，实际业务应按第 4 节分类恢复。

## 参考

- [KIP-98 事务协议设计](https://cwiki.apache.org/confluence/spaces/KAFKA/pages/66854913/KIP-98+-+Exactly+Once+Delivery+and+Transactional+Messaging)
- [Kafka 3.9 Java Producer API](https://kafka.apache.org/39/javadoc/org/apache/kafka/clients/producer/KafkaProducer.html)
- [Kafka 3.9 Broker 配置](https://kafka.apache.org/39/configuration/broker-configs/)
- [librdkafka v2.8.0 默认配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)

- [Java 3.9 isolation.level](https://kafka.apache.org/39/configuration/consumer-configs/#isolation.level)
- [librdkafka v2.8.0 事务 API 与配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
