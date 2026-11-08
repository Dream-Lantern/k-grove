---
id: kafka-connect-streams
title: 第 23 章：Connect、Streams 与演进路线
description: "直接使用 Producer/Consumer API，可以控制业务处理和依赖，但需要自己维护位点、错误、模式、并发和恢复。"
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
order: 23
---

# 第 23 章：Connect、Streams 与演进路线

> 版本导航：3.9生态入口 / 4.0演进旁注。
>
> 学习目标：按数据接入、流处理和跨集群恢复的职责理解生态组件，并区分 3.9、4.0 与 C 客户端的支持范围。

## 1. Producer/Consumer API 与 Connect 连接器 {#_1-自写-consumer-只是其中一条路线}

直接使用 Producer/Consumer API，可以控制业务处理和依赖，但需要自己维护位点、错误、模式、并发和恢复。若主要目标是把外部系统接入 Kafka，重复编写同样的连接与运行管理代码可能没有必要。

Kafka Connect 提供连接器运行框架，由 Source 将外部数据接入 Kafka，再由 Sink 从 Kafka 写向外部。但使用同一框架，不意味着每种 Connector 都有相同的 Exactly Once 保证；最终语义仍取决于版本、Connector、运行模式及外部系统的合作契约。

[![生态组件按职责选择，而非都叫消费者](/assets/notes/kafka/kf-ecosystem.png)](/assets/notes/kafka/kf-ecosystem.png)

| Connect 角色                                     | 负责什么                                                                                                                                                                                   |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Worker（运行进程）                               | 加载插件、运行 Connector 与 Task、协调位点及状态。Standalone Mode（独立模式）由单进程运行，Distributed Mode（分布式模式）由同组 Worker 协调分配，用内部 Kafka Topic 保存配置、源位点与状态 |
| Connector（连接器）                              | 生成任务配置，决定如何拆分外部系统工作。Source Connector 从外部读入 Kafka，Sink Connector 从 Kafka 写入外部                                                                                |
| Task（执行任务）                                 | 根据任务配置实际读写数据。 `tasks.max` 表示目标上限，插件能拆分的工作不足时可能创建更少任务                                                                                                |
| REST API（Representational State Transfer 接口） | 创建、查询和管理连接器，通过状态区分 Connector 和各 Task 的运行或失败                                                                                                                      |

分布式 Worker 加入或退出后，Connect 可将任务分给其他 Worker。Source Task 由插件定义源分区和源 Offset，例如文件位置或数据库日志位置。Connect 持久化源位点，新任务依靠插件从该位置恢复。发送结果已生效而源位点尚未保存时可能重复。Sink Task 用 Kafka 消费组位点恢复，外部写入成功而位点尚未提交时也可能重做。出现 FAILED 时先查 Task 状态和错误，修复后显式重启失败任务，再核对恢复点和下游结果。依赖故障或插件失败不一定自行恢复。

Kafka 3.9 的 Source Exactly Once（源端恰好一次）需 Distributed Mode，所有 Worker 启用 `exactly.once.source.support=enabled`，并使用具备相应能力的 Connector。已有集群按官方步骤先滚动进入 `preparing` 再进入 `enabled`。框架把 Kafka 输出和源 Offset 纳入同一 Kafka 事务，并隔离旧任务生产者。插件仍需提供可恢复的源位置，下游使用 `read_committed`。Sink 读取可用 `consumer.isolation.level=read_committed` 避开中止事务。外部写入仍需 Sink 插件与目标系统共同实现，例如用唯一键幂等写入或在目标事务中同时保存结果与恢复进度。

### 实践：独立 Worker 读取订单文本

使用 Kafka 3.9 发行包、Java 和已有的隔离 Broker。新建单分区 `review-connect-orders`，在发行包根目录运行。准备 `orders-worker.properties`：

```properties
bootstrap.servers=localhost:9092
key.converter=org.apache.kafka.connect.storage.StringConverter
value.converter=org.apache.kafka.connect.storage.StringConverter
offset.storage.file.filename=/tmp/review-orders-connect.offsets
offset.flush.interval.ms=1000
listeners=http://127.0.0.1:8083
plugin.path=libs/connect-file-3.9.2.jar
```

将 JAR 名改为发行包内实际的 3.9.x 版本，确认 `/tmp` 的位点文件名专用于该实验，且 Worker 用户可以读写。准备文件并启动：

```bash
bin/kafka-topics.sh --bootstrap-server localhost:9092 --create \
  --topic review-connect-orders --partitions 1 --replication-factor 1
printf 'order-001\n' > /tmp/review-orders-connect.txt
bin/connect-standalone.sh orders-worker.properties
```

在另一终端创建 Connector 并观察：

```bash
curl -fsS -H 'Content-Type: application/json' -X POST \
  -d '{"name":"review-file-orders","config":{"connector.class":"org.apache.kafka.connect.file.FileStreamSourceConnector","tasks.max":"1","file":"/tmp/review-orders-connect.txt","topic":"review-connect-orders"}}' \
  http://127.0.0.1:8083/connectors
curl -fsS http://127.0.0.1:8083/connectors/review-file-orders/status
curl -fsS http://127.0.0.1:8083/connectors/review-file-orders/tasks/0/status
bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic review-connect-orders --from-beginning --max-messages 1 --timeout-ms 10000
```

创建请求返回后，重复查询状态，等 Task 0 进入 `RUNNING` 再观察消费输出。若它进入 `FAILED`，先查看任务状态和 Worker 日志。预期消费者读到 `order-001`。单 Broker 环境还需满足[内部位点 Topic 的创建条件](/articles/kafka-log-model.html)。再追加一行，确认该行已进入 Kafka，并在对应源位点落盘前强制终止 Worker。重启后用原位点文件、原文件路径和相同名称重新提交 Connector 配置，观察该行是否重放。若无法确认终止发生在这个窗口，应将结果记为触发条件未确认。停止前可用 REST DELETE 删除本实验 Connector，再正常结束 Worker，清理本实验文件和位点文件。此例用于本地文本接入，实验未联机实测。

## 2. Streams 的流表、窗口与状态恢复 {#_2-kafka-streams-处理的是什么}

Streams 是构建 Kafka 流处理应用的 Java 库，涉及流表模型、窗口、聚合、状态存储及恢复。它不是需要另行安装在每台 Broker 上的通用 SQL 数据库，也不是 C Consumer 的同义名称。

窗口与事件时间还会引入乱序、迟到和状态保留问题。选择 Streams 时，应先理解输入输出、Key、分区和状态恢复，不要因为启用某个处理保证就忽略外部副作用。

KStream（记录流）把订单事件看作独立事实。同一个 Key 的两条记录都可参与 Aggregation（聚合）。KTable（更新表）将记录解释成每个 Key 的更新，表中的当前值可由后来的更新替换。按 SKU 聚合时，相关记录必须由同一任务处理。若输入按订单 Key 分区，改用 SKU Key 后需 Repartition（重分区），通常由内部 Kafka Topic 完成。

Event Time（事件时间）来自事件或记录时间戳，Processing Time（处理时间）是应用执行时的机器时间。Window（窗口）按时间将数据分组。Grace Period（宽限期）允许部分乱序记录在窗口结束后继续更新结果，是否迟到取决于相关处理任务的流时间推进。窗口结果可能有多次更新，宽限期结束后不再纳入该窗口的更晚记录。

State Store（状态存储）在本地保存聚合值。启用日志记录的存储用 Changelog Topic（变更日志主题）备份状态更新。Rebalance 后新任务所有者可恢复本地状态并重放所需变更，恢复耗时与状态规模、日志保留及备用副本等有关。

`processing.guarantee=at_least_once` 允许故障后的重复处理。`exactly_once_v2` 将输入 Kafka 位点、状态 changelog 与 Kafka 输出纳入事务提交范围。恢复以提交的位点和状态为准。普通数据库或 HTTP 调用在此事务之外，仍需外部幂等协议。

### 实践：观察乱序和窗口宽限

在 Kafka 3.9 测试 Broker 创建各一个分区的 `review-window-input` 和 `review-window-output`。用 Java 17、Maven 项目依赖 `org.apache.kafka:kafka-streams:3.9.2`，将代码存为 `src/main/java/OrderWindows.java`，执行 `mvn compile exec:java -Dexec.mainClass=OrderWindows`，项目编译级别设为 17。使用独立应用 ID、空 Topic 和本地状态目录。此例选默认至少一次，避免单 Broker 实验依赖事务配置。

```java
import java.time.Duration;
import java.util.Properties;
import java.util.concurrent.CountDownLatch;
import org.apache.kafka.common.serialization.Serdes;
import org.apache.kafka.streams.KafkaStreams;
import org.apache.kafka.streams.StreamsBuilder;
import org.apache.kafka.streams.kstream.Consumed;
import org.apache.kafka.streams.kstream.Grouped;
import org.apache.kafka.streams.kstream.Produced;
import org.apache.kafka.streams.kstream.TimeWindows;

class OrderWindows {
    public static void main(String[] args) throws InterruptedException {
        var props = new Properties();
        props.put("bootstrap.servers", "localhost:9092");
        props.put("application.id", "review-order-windows");
        props.put("state.dir", "/tmp/review-order-windows");
        props.put("auto.offset.reset", "earliest");
        props.put("statestore.cache.max.bytes", "0");
        props.put("replication.factor", 1);
        var builder = new StreamsBuilder();
        var strings = Serdes.String();
        builder.stream("review-window-input", Consumed.with(strings, strings)
                .withTimestampExtractor((record, previous) ->
                    Long.parseLong(((String) record.value()).split(",", 2)[0])))
            .selectKey((order, value) -> value.split(",", 2)[1])
            .groupByKey(Grouped.with(strings, strings))
            .windowedBy(TimeWindows.ofSizeAndGrace(
                Duration.ofSeconds(10), Duration.ofSeconds(5)))
            .count()
            .toStream()
            .map((window, count) -> org.apache.kafka.streams.KeyValue.pair(
                window.key() + "@" + window.window().start(), count.toString()))
            .to("review-window-output", Produced.with(strings, strings));
        var streams = new KafkaStreams(builder.build(), props);
        var stopped = new CountDownLatch(1);
        Runtime.getRuntime().addShutdownHook(new Thread(() -> {
            streams.close();
            stopped.countDown();
        }));
        streams.start();
        stopped.await();
    }
}
```

```bash
printf '%s\n' 'o1:1000,sku-100' 'o2:12000,sku-100' 'o3:7000,sku-100' \
  'o4:16000,sku-100' 'o5:8000,sku-100' | \
  bin/kafka-console-producer.sh --bootstrap-server localhost:9092 \
    --topic review-window-input --property parse.key=true --property key.separator=:
bin/kafka-console-consumer.sh --bootstrap-server localhost:9092 \
  --topic review-window-output --from-beginning --property print.key=true
```

输入值格式为 `事件时间毫秒,SKU`。按给定顺序、单分区执行时，`sku-100@0` 预期先输出 1，再因 7000 ms 的记录输出 2。16000 ms 推进流时间越过 15000 ms 后，8000 ms 的记录不应再增加窗口计数。输出是更新流。若用单 Broker，其组位点内部 Topic 也须可创建，例如在新实验环境首次创建前设置 `offsets.topic.replication.factor=1`。停止应用后，只有明确放弃该实验的恢复状态时才清理专用状态目录和 Topic。以上 Java 示例及窗口行为未实测。

## 3. 跨集群复制与业务灾备切换 {#_3-跨集群复制不等于同步多主事务}

MirrorMaker 等复制路线用于跨集群数据流动，但复制延迟、位点映射、故障切换、循环复制和目标命名都需要单独管理。异步复制通常存在可量化的恢复点风险，不能直接宣传为两地任意切换零丢失。

设计灾备时，应先定义 RPO、RTO 和业务切换条件，再安排复制与验证。目标 Topic 已经出现，并不能证明消费恢复、权限、事务语义和外部状态都已满足立即接管的条件。

MirrorMaker 2（MM2）基于 Connect。MirrorSourceConnector 从 Source Cluster（源集群）拉取并写入 Target Cluster（目标集群），默认远端 Topic 名带源别名前缀，如 `A.review-orders`。Offset Sync 记录源与目标位置对应关系，MirrorCheckpointConnector 为消费组生成翻译后的 Checkpoint（恢复位点检查点）。可显式启用 `sync.group.offsets.enabled` 向目标写入翻译位点，但仅对目标端没有活动消费者的组同步。MirrorHeartbeatConnector 写 Heartbeat（心跳记录）以观察复制路径。心跳到达只说明路径有进展，业务 Topic 仍可能积压。

假设 A 的订单分区已写到 Offset 1199，故障时 B 只覆盖源 Offset 0–1179。A 组的恢复位置 1160 经已核对的映射在 B 是 350，B 可见末端是 370。若目标 checkpoint 只到 345，选择从 345 启动会重放部分业务。A 最后 20 条尚不在 B，若 A 无法恢复，需按业务记录核对缺口。这里假设区间内每条 Offset 都对应一个可见事件，数字只是教学推演。RPO（Recovery Point Objective，恢复点目标）规定允许丢失多少数据或时间。RTO（Recovery Time Objective，恢复时间目标）包含发现、隔离旧写入、检查目标数据与位点、切换和验证所需时间。

切换前确认旧端已停止业务写入或已隔离，B 的数据、翻译位点、权限和外部库存状态都满足验收条件。核对事件 ID 和下游效果以识别重复或缺口。回切要重新验证反向复制、目标端组位点和数据库状态。双向复制应验证默认前缀和循环检测策略，若更换命名策略则单独证明不会把远端记录再复制回源。异步复制的两侧没有共享提交事务。

例如事先约定 RPO 为每分区最多缺 30 条订单事件、RTO 为 120 秒。上述 20 条缺口在数量预算内，仍要核对它们是否包含不能丢失的订单。假定发现、隔离与检查耗时 25、30、40 秒，切换并验证再用 20 秒，合计 115 秒。两个结果都是计划演算，实测应以故障时数据核对和业务恢复时间为准。

## 4. 版本演进的三条清晰边界

第一，3.9 与 4.0 的元数据模式不同：4.0 已不再支持 ZooKeeper 模式。第二，4.0 新 Consumer Rebalance 协议 GA，但客户端支持阶段独立；librdkafka 2.8.0 的对应能力仍是 Early Access。第三，默认参数会变化，应固定客户端文档而非只写“Kafka 默认”。

另一个 4.0 的补充是 Eligible Leader Replicas（ELR）：在相应协议和功能条件下，控制器可记录不在当前 ISR 内、但仍可安全接管的副本资格。因此第 4—5 章的 3.9 常规 ISR 模型不能直接外推为以后所有版本的完整选主算法。ELR 也不是允许任意落后副本无损接管。

分层存储也值得后续学习，但插件实现、版本支持、Topic 策略和运维边界需要另设专题讨论。本册只给出入口，不将其描述为已经可以替代所有本地磁盘规划。

| 能力                       | Kafka 3.9                              | Kafka 4.0 对照                                                                      |
| -------------------------- | -------------------------------------- | ----------------------------------------------------------------------------------- |
| 元数据                     | KRaft 与 ZooKeeper 模式并存            | 仅 KRaft                                                                            |
| 消费组协议                 | 本册使用 Classic，KIP-848 尚处演进阶段 | Consumer 协议 GA，客户端需支持并按条件启用。固定 librdkafka 2.8.0 仍是 Early Access |
| ELR                        | 本册按常规 ISR 选主模型学习            | 资格取决于启用条件和复制安全约束                                                    |
| Tiered Storage（分层存储） | 需适配的远端存储插件与 Topic 配置      | 继续按插件和版本核对，仍要保留本地与恢复容量                                        |

## 5. 选择补充知识的顺序

先把单集群分区、可靠性、消费位点和幂等理解扎实，再学习状态流处理、跨集群恢复和存储演进。它们都不能绕过基础语义。

本册补充的是可持续学习路径，不是某个新版本的完整发布说明。没有核实的后续特性不作肯定结论，更不据网站“latest”导航推断本机已升级或某项配置已经可用。

| 目标                           | 选择与代价                                                                                  |
| ------------------------------ | ------------------------------------------------------------------------------------------- |
| 控制业务事务、重试和外部副作用 | 原生 Producer/Consumer，自行负责位点和恢复，见[订单案例](/articles/kafka-order-events.html) |
| 接入外部系统                   | Connect，运维 Worker、插件和内部 Topic，交付语义取决于 Connector                            |
| 用 Kafka 流做聚合或维护状态    | Streams，运维应用实例、重分区和状态恢复                                                     |
| 跨集群复制及灾备准备           | MM2，额外管理链路、目标位点、切换和外部状态                                                 |

## 参考

- [Kafka 3.9 Connect 用户指南](https://kafka.apache.org/39/kafka-connect/user-guide/)
- [Kafka 3.9 Streams 核心概念](https://kafka.apache.org/39/streams/core-concepts/)
- [Kafka 3.9 Streams 应用配置](https://kafka.apache.org/39/streams/developer-guide/config-streams/)
- [Kafka 3.9 MirrorMaker 2](https://kafka.apache.org/39/operations/geo-replication-cross-cluster-data-mirroring/)

- [Kafka Connect Overview](https://kafka.apache.org/39/kafka-connect/overview/)
- [Kafka Streams Introduction](https://kafka.apache.org/39/streams/introduction/)
- [Kafka 3.9 Tiered Storage](https://kafka.apache.org/39/operations/tiered-storage/)
- [Kafka 4.0 Consumer Protocol](https://kafka.apache.org/40/operations/consumer-rebalance-protocol/)
- [Kafka 4.0 升级与 ELR 变化](https://kafka.apache.org/40/getting-started/upgrade/)
