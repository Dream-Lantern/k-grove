---
id: kafka-log-storage
title: 第 6 章：日志段、稀疏索引与消息格式
description: "一条分区日志可以由多个日志段组成。记录通常追加到活动段，达到相应的大小、时间或其他滚动条件后，再创建新段。划分日志段后，保留、清理、索引和恢复都可以按较小的单位管理，不必把整个分区当成一个无限增长的文件。"
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
order: 6
---

# 第 6 章：日志段、稀疏索引与消息格式

> 版本基线：Kafka Broker / Java Client 3.9，固定源码为 3.9.0；librdkafka v2.8.0。文件结构和格式以现代 magic=2 Record Batch 为主；数字示例不代表实际文件采样。
>
> 学习目标：沿选择日志段、查询稀疏索引和解析记录的顺序，理解逻辑 Offset、相对 Offset 与字节位置。

## 1. 分区日志为什么划成 Segment

一条分区日志可以由多个日志段组成。记录通常追加到活动段，达到相应的大小、时间或其他滚动条件后，再创建新段。划分日志段后，保留、清理、索引和恢复都可以按较小的单位管理，不必把整个分区当成一个无限增长的文件。

Log Segment（日志段）是分区日志的一段文件集合；Active Segment（活动日志段）是当前接受追加的段。每个副本各自持有本机的文件，不是 A/B/C 三个 Broker 共用同一份目录。第 4 章的 LEO（Log End Offset，日志末端位点）与 HW（High Watermark，高水位）描述逻辑复制状态，这一章说明相关记录怎样存放在文件中。

“每段 500MB”这类示意不表示所有段必须恰好等大。按时间滚动、批次边界和实际负载都可能让大小不同。Roll 是切段，Flush 是适用的持久化刷新，Retention 是清理策略，不能说“每切一个段就删除并刷盘”。

Segment Roll（日志段滚动）关闭当前段的追加阶段，并建立新的活动段。Topic 的 `segment.bytes`（默认 1 GiB）和 `segment.ms`（默认 7 天）是大小和时间相关配置，不是“段必定精确写满 1 GiB，或到钟点无条件出现空文件”的承诺。

3.9.0 `LogSegment.shouldRoll()` 在追加路径上检查：新批次可能让段超过大小限制、非空段达到适用时间条件、Offset/Time Index 已满，或相对 Offset 无法继续表示等。大小判断会考虑**即将追加的批次**；时间判断还涉及时间戳和滚动抖动。因此，一个没有达到大小上限的段也可能滚动，空闲 Topic 也不应当被理解为每到 `segment.ms` 就必定独立触发一次定时切段。保留删除等其他路径还可按需要触发滚动，不能把这一方法当作所有滚动入口。

## 2. 用基准 Offset 与文件后缀识别日志段 {#_2-文件名表达基准-offset-不表达容量}

常见段文件用补零的十进制 base offset 命名，配合 `.log`、`.index`、`.timeindex` 等后缀；事务相关路径还可能有相应索引。不是所有文件都叫 `.kafka`，也不是每条业务消息都单独对应一个文件。

现代记录 Offset 是分区日志的逻辑位置，不等于从文件开头数出的字节数。消息长短、批次压缩和清理空洞都使“Offset 差值=字节距离”失效。官方历史 Log 页面仍保留部分很早期描述，本章以 3.9.0 固定源码与现代格式说明交叉核对，不照搬其旧字节 Offset 说法。

### Broker A 上 `orders-0` 的示意目录

下面是独立于第 4、5 章 Offset=100～104 的**另一个教学文件例子**；它的段基准为 0、1000、2000，不表示同一次实验结果。Base Offset（段基准位点）标识该段的逻辑起点，文件名用 20 位补零十进制数加后缀：

```text
<log.dirs>/orders-0/
├── 00000000000000000000.log         # 较早的非活动段
├── 00000000000000000000.index
├── 00000000000000000000.timeindex
├── 00000000000000001000.log         # 本章查询目标所在段
├── 00000000000000001000.index
├── 00000000000000001000.timeindex
├── 00000000000000001000.txnindex    # 适用事务场景中的中止事务索引
├── 00000000000000002000.log         # 本例活动段，后续追加在这里
├── 00000000000000002000.index
├── 00000000000000002000.timeindex
└── ...                            # 还有恢复、Epoch、生产者状态等相关文件
```

| 文件 / 概念    | 保存什么，解决什么问题                                                                                                                          |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------------- |
| `.log`         | Record Batch（记录批次）及批内记录的数据文件，不是应用文本日志                                                                                  |
| `.index`       | Offset Index（位点索引），稀疏地把逻辑位点映射为该 `.log` 内的物理字节位置                                                                      |
| `.timeindex`   | Time Index（时间索引），辅助按时间戳定位 Offset，再结合位点索引和数据查找；不保证每条记录有一个索引项                                           |
| `.txnindex`    | Transaction Index（事务索引），保存适用的中止事务范围等信息，辅助 `read_committed` 过滤；不是事务消息正文，也不是所有非事务段必有有效条目的文件 |
| Base Offset    | 识别段及相对位点的基准；压缩清理后第一条保留记录未必恰好等于这个值                                                                              |
| Active Segment | 只是当前追加目标，不代表其中所有字节已复制提交或完成刷盘                                                                                        |

一个查询既要满足逻辑保留范围，又要找到实际存在的批次。段文件存在并不代表所有编号仍有记录；日志起点、HW、事务可见性还会限制客户端能读到什么。

## 3. 稀疏索引如何缩小查找范围

![Segment、稀疏索引与 Record Batch 查找](/assets/notes/kafka/kf-index-review.svg)

[放大查看索引图](/assets/notes/kafka/kf-index-review.svg)。

例中 base=1000，目标=1006，相对位置为 6，不需要加 1。先选择合适日志段，再在稀疏索引中找不大于目标的可用入口，得到段文件中的物理位置，随后检查批次和记录，定位所需数据。

并非每条消息都有对应的索引项，也不能直接执行 `base + byte_position` 得到业务 Offset。稀疏索引减小了索引体积，代价是定位后仍需在有限范围内顺序检查。压缩批次还需要按格式解析，不能把示意表当成真实的二进制解析器。

### `OffsetIndex.lookup()` 与 `append()` 实际做什么

3.9.0 的 `OffsetIndex` 每个条目为 8 字节：4 字节相对 Offset 和 4 字节物理 Position（字节位置），通过内存映射的 `ByteBuffer` 读写。`append(offset, position)` 接收**绝对 Offset**，调用 `AbstractIndex.relativeOffset()` 检查与转换 `offset - baseOffset`，写入两个整数；不是让调用者传入相对 Offset。相对值必须在 0～`Integer.MAX_VALUE`，且后续追加的索引 Offset 要递增。

`lookup(targetOffset)` 同样接收**绝对目标 Offset**。它在已有条目中找 Offset 不大于目标的最大下界，解析时加回 baseOffset，返回 `OffsetPosition(绝对位点, 字节位置)`。如果索引为空或目标小于最小条目，返回 `(baseOffset, 0)` 作为扫描起点；这并不证明该位置就是目标记录。

本章假设 baseOffset=1000，稀疏条目为：

| relativeOffset | 对应绝对 Offset | position，单位字节 |
| -------------- | --------------- | ------------------ |
| 0              | 1000            | 0                  |
| 4              | 1004            | 320                |
| 8              | 1008            | 900                |

查找 1006 的完整推演：

1. 在段集合中选择基准不大于目标的合适段。本例后续段基准为 2000，因此选择 1000 段；同时要先确认目标没有早于日志起点或超出可读取范围。
2. 为理解条目，计算 `1006 - 1000 = 6`。实际调用仍是 `lookup(1006)`，不是 `lookup(6)`。
3. 相对条目 0、4、8 中，不大于 6 的最大值为 4；得到绝对索引 Offset 1004 和物理位置 320。
4. 从 `.log` 的第 320 字节开始解析批次。Position 指向可开始扫描的批次位置，不保证直接指向单条 1004，更不指向 1006。
5. 按批次长度和最后 Offset 继续搜索；找到覆盖目标的候选批次后，按需解压并解析 Record，计算 `baseOffset + offsetDelta` 定位记录。
6. 若 1006 已被 Compaction（按 Key 压缩清理）移除，应按读取范围和协议继续寻找实际可用的后续记录，而不是凭空恢复它；若没有符合可见边界的记录，则不会因为索引入口存在就返回目标。

表中 320、900 全部是**教学假设字节位置，不是 Kafka 文件测量结果**。`LogSegment.append()` 会将某次追加的最大 Offset 和该次数据的物理起点用于索引；入口可能指向含更早记录的批次，解释了为什么仍要解析扫描，而不能把索引当逐条消息地址表。

`index.interval.bytes` 默认 4096，控制大约累计多少追加字节后再考虑索引条目。`LogSegment.append()` 使用累计字节计数及追加边界，不是“每第 4096 条消息建一个索引”，也不是每隔精确 4096 字节一定有一个条目。批次大小和压缩改变物理长度，稀疏索引因此需要与 `.log` 一起理解。

源码阅读入口依次是：`OffsetIndex.lookup()` / `append()` → `AbstractIndex` 的下界搜索、相对值转换 → `LogSegment.translateOffset()` → `FileRecords.searchForOffsetWithSize()`。它们缩小的是物理扫描范围；消费者隔离与事务过滤属于更上层边界。

## 4. 新旧消息格式要分开

单条 Message 字段图需按旧消息格式理解。现代格式采用 Record Batch 及批内 Record，包含批次级字段、时间戳及 Offset 差值等机制。读旧图能帮助理解校验与长度，但不能拿它直接按固定字节偏移解析所有 3.9 文件。

如果保留或引用旧 Magic 0/1 单条 Message 图，应标注：**历史格式示意，不能直接用于 Kafka 3.9 现代 Record Batch 解析**。本页新增的是 Magic=2 格式，不复用旧图的字节偏移。

### Magic=2 的 Record Batch

Magic（格式版本标识）为 2，表示本节采用的现代批次格式；它不是 Kafka 产品版本“2.x”。下表的物理偏移以一个批次开始的第 0 字节计算，字段宽度来自 3.9.0 `DefaultRecordBatch` 常量：

| 字段                   | 起始字节 / 长度 | 含义                                                            |
| ---------------------- | --------------- | --------------------------------------------------------------- |
| `baseOffset`           | 0 / 8           | 批次逻辑基准 Offset，不是该批次在文件中的字节地址               |
| `batchLength`          | 8 / 4           | 后续批次数据的字节长度；批次总大小为 `12 + batchLength`         |
| `partitionLeaderEpoch` | 12 / 4          | 写入该批次时的分区 Leader Epoch（领导代际）                     |
| `magic`                | 16 / 1          | 本节为 2                                                        |
| `crc`                  | 17 / 4          | CRC-32C 校验值                                                  |
| `attributes`           | 21 / 2          | 压缩算法、时间戳类型、事务/控制批次等标志                       |
| `lastOffsetDelta`      | 23 / 4          | 批次最后逻辑 Offset 相对于 baseOffset 的差值                    |
| `baseTimestamp`        | 27 / 8          | 批内时间戳差值的基准；解释时需结合时间戳类型等标志              |
| `maxTimestamp`         | 35 / 8          | 批次最大时间戳；LogAppendTime 路线还影响实际记录时间戳解释      |
| `producerId`           | 43 / 8          | 生产者身份，供幂等/事务状态判断使用，普通非幂等路径可用无效标记 |
| `producerEpoch`        | 51 / 2          | 生产者代际，不是 partitionLeaderEpoch                           |
| `baseSequence`         | 53 / 4          | 该生产者在此分区的批次序列基准，供重试去重等判断                |
| `recordsCount`         | 57 / 4          | 实际编码的记录数量，属于 Records 数组编码的一部分               |
| `records`              | 61 / 可变       | 批内记录区域，启用压缩时为压缩后的数据                          |

![Magic 2 批次结构、CRC 覆盖与批内 Record](/assets/notes/kafka/kf-record-batch-review.svg)

[放大查看批次格式图](/assets/notes/kafka/kf-record-batch-review.svg)。图中的字节位置是格式定义；示例的 Offset 和时间戳是教学值。

CRC-32C（32-bit Cyclic Redundancy Check, Castagnoli，Castagnoli 多项式的 32 位循环冗余校验）与第 2 章分区路由使用的 CRC32 不是同一算法。`DefaultRecordBatch.computeChecksum()` 从 `attributes`（第 21 字节，包含）开始覆盖到整个批次末端，**不包含** baseOffset、batchLength、partitionLeaderEpoch、magic 和 crc 自身。它用于检测校验范围的数据损坏，不是防篡改签名，也不独立证明复制或业务正确性。

压缩作用于批内 records 数据区域，不把整个批次头一起压缩；算法由 attributes 的相关位表示，CRC 对实际存储的字节进行计算。因此不能先把“压缩后的任意一段字节”当作独立 Record 直接按固定字段读取。Broker 可能按配置进行必要转换，源码路径和测量环境要另行区分。

### 批内 Record 与 Offset 空洞

`DefaultRecord` 使用可变长编码：`length`、`attributes`、`timestampDelta`、`offsetDelta`，以及带长度的 Key、Value 和 Headers（头字段）。Headers 包含头字段数量、各 Header Key / Value；Key、Value 的长度可以表达 Null，不能把零长度与 Null 混同。Varint/Varlong（变长整数）使这些字段的起始位置随实际值变化，不能照搬批头那张固定偏移表解析每条 Record。

教学例子：某批次 baseOffset=1000，某条记录 offsetDelta=6，它的逻辑 Offset 为 `1000 + 6 = 1006`。在 CreateTime（创建时间）路线下，若 baseTimestamp=1700000000000、timestampDelta=25，则记录时间戳为 1700000000025ms；这些数值不是真实采样。LogAppendTime（日志追加时间）路线由批次时间戳类型控制，不能无条件套用同一个时间戳加法。

假设原批次范围为 1000～1008，经 Compaction 后只剩 1001、1006、1008：记录数为 3，批次边界及相关序列语义仍需保留，不能把幸存记录重编号为 1000、1001、1002。`lastOffsetDelta=8` 不因此等于 `recordsCount-1=2`。这既解释了 Offset 空洞，也解释了幂等和事务需要保留批次级身份、代际和序列信息。有关控制记录与事务状态的细节见[第 14 章](/articles/kafka-transactions.html)。

CRC 用于发现其校验范围内的数据损坏，但发现错误后，不能让业务静默忽略。恢复、截断与副本修复需要使用明确的工具，并遵循运行手册。手工修改 `.log` 或删除索引可能造成额外损坏，本册不执行这些动作。

## 5. 文件结构为什么影响性能

批量追加、页缓存和连续读取有利于吞吐，但不能得出“所有操作永远 O(1)、数据量无限增长也无影响”。索引查找、冷热数据、磁盘压力、恢复及清理都有成本。某些传输路径可以减少用户态拷贝；TLS、格式转换等条件又会改变路径，不能统一宣称完全零拷贝。

### 一个日志段的生命周期

| 动作                   | 改变什么                                                           | 与其他动作的区别                                             |
| ---------------------- | ------------------------------------------------------------------ | ------------------------------------------------------------ |
| Append（追加）         | 向活动段写入批次，按需更新稀疏索引                                 | 不等于该记录已提交或已 fsync                                 |
| Roll（滚动）           | 建立下一活动段，原段结束追加阶段                                   | 不等于立刻删除旧段；实现可以伴随安排刷新，但两者不是同一操作 |
| Flush（刷新）          | 同步适用文件数据/索引等，推进本地恢复相关状态                      | 不改变业务 Offset 编号，也不代替其他 Broker 的复制           |
| Retention（保留清理）  | 根据时间/容量等策略清理符合条件的旧段，推进可保留范围              | 通常按段清理，不是在某消费组提交后立刻逐条删除               |
| Compaction（压缩清理） | 对适用 Topic 按 Key 保留相应的新状态，重写清理范围中的段并形成空洞 | 不是 gzip/zstd 等批次压缩，也不保证每条旧 Key 立即消失       |

Active → Roll 后的非活动段 → 符合条件的保留删除或压缩清理，是理解生命周期的主线；具体清理受配置、日志边界与异步调度限制。`cleanup.policy=compact,delete` 还可以组合两类策略，不能把“设置 compact”理解为无限期保留所有记录。

### Page Cache、顺序 I/O 与 sendfile

Page Cache（页缓存）缓存文件页，近期追加和热读取可能由内存服务；顺序 I/O（Input/Output，输入输出）与批量处理减少细碎请求、寻址和系统调用开销。冷数据仍需实际设备读入，内存压力也会驱逐缓存；这些机制提供设计上的效率机会，不构成固定吞吐或延迟收益数据。

在支持的明文网络路径中，Java 文件通道的 `transferTo` 可以利用操作系统 sendfile 一类能力，将文件数据送往 socket，减少用户态复制与切换。3.9.0 `FileRecords.writeTo()` 委托 `TransferableChannel`，具体还要看 `PlaintextTransportLayer.transferFrom()` 等实现。TLS（Transport Layer Security，传输层安全）通常需要在用户态加密，格式转换或解压也可能要求构造新缓冲区，不能统一宣称任意 Kafka Fetch 都走完全零拷贝。该机制不改变第 5 章的复制与持久化语义。

### 只读查看日志文件与索引

以下为**未执行**的 Kafka 3.9 Bash 示例。优先使用隔离实验环境中已经停止变化的副本文件，或一致性复制出的诊断目录；不要对生产活动文件做手工修改。`kafka-dump-log.sh` 选项根据 3.9.0 `DumpLogSegments` 中的定义列出，最终仍应以使用的发行包 `--help` 核对：

```bash
bin/kafka-dump-log.sh --help

# SAMPLE_LOG_DIR 指向既有的、获准读取的诊断文件目录；不指向待初始化目录。
# 文件名只是上面的教学示意，需替换为该目录真实存在的一组同基准文件。
bin/kafka-dump-log.sh \
  --files "$SAMPLE_LOG_DIR/00000000000000001000.log" \
  --deep-iteration --max-bytes 1048576

bin/kafka-dump-log.sh \
  --files "$SAMPLE_LOG_DIR/00000000000000001000.index"

bin/kafka-dump-log.sh \
  --files "$SAMPLE_LOG_DIR/00000000000000001000.timeindex"
```

3.9.0 的工具通过只读方式打开相应数据及索引；检查索引还需要同目录、同基准的配套 `.log` 等文件。`--max-bytes` 用于限制扫描数据范围，不保证恰好输出固定数量记录；`--deep-iteration` 会深入批内记录。默认不加 `--print-data-log`，避免无必要地打印 Key/Value；需要内容解码时先确认数据公开范围及解码器，而不是把任意二进制内容当 UTF-8 文本。

应记录实际文件基准、索引入口、批次范围、物理 Position、记录 Offset 及校验状态，再和本节算法对应。此处没有真实文件测量、没有输出截图，也不执行删除索引、修复、truncate（截断）或格式化命令。

练习：若目标 Offset 因 compact 已不存在，读取不应该凭空造出该消息；要理解接口如何从可用范围继续，而不是用差值计算出一个必有记录的位置。

## 参考

- [Kafka 3.9.0 OffsetIndex 源码](https://github.com/apache/kafka/blob/3.9.0/storage/src/main/java/org/apache/kafka/storage/internals/log/OffsetIndex.java)
- [Kafka 3.9 Message Format](https://kafka.apache.org/39/implementation/message-format/)
- [AbstractIndex.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/storage/src/main/java/org/apache/kafka/storage/internals/log/AbstractIndex.java)：相对 Offset、下界搜索与映射。
- [LogSegment.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/storage/src/main/java/org/apache/kafka/storage/internals/log/LogSegment.java)：`append`、`shouldRoll`、`translateOffset`。
- [DefaultRecordBatch.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/common/record/DefaultRecordBatch.java)：固定头字段、CRC-32C 范围、批次压缩及清理语义。
- [DefaultRecord.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/common/record/DefaultRecord.java)：批内记录编码。
- [FileRecords.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/common/record/FileRecords.java)：按 Offset 搜索与通道传输。
- [PlaintextTransportLayer.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/common/network/PlaintextTransportLayer.java) / [SslTransportLayer.java 3.9.0](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/common/network/SslTransportLayer.java)：明文文件通道传输和 TLS 缓冲路径的区别。
- [DumpLogSegments.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/tools/DumpLogSegments.scala)：日志/索引只读工具的参数和读取路径。
- [Kafka 3.9 Topic 配置](https://kafka.apache.org/39/configuration/topic-level-configs/)：`segment.bytes`、`segment.ms`、`index.interval.bytes`、`cleanup.policy`。
