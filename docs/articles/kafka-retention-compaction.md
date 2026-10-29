---
id: kafka-retention-compaction
title: 第 7 章：保留策略、压缩清理与重放
description: "普通 delete 策略主要按时间、大小等条件清理合格日志段。消费者是否已读，不是必须先满足的删除条件。慢消费者可能在恢复时发现提交位点已经落到可保留范围之前。"
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
order: 7
---

# 第 7 章：保留策略、压缩清理与重放

> 版本基线：Kafka Broker / Java Client 3.9，固定实现按 3.9.0；librdkafka v2.8.0。清理状态、恢复案例和实验预期均为教学推演，不是实测输出。
>
> 学习目标：区分 delete、compact 和编码压缩，并根据保留范围与恢复目标设计重放。

## 1. delete 策略按日志段管理保留 {#_1-保留期限不等待消费者}

普通 `delete` 策略主要按时间、大小等条件清理合格日志段。消费者是否已读，不是必须先满足的删除条件。慢消费者可能在恢复时发现提交位点已经落到可保留范围之前。

时间保留也不是每条记录到了某秒就立即精确删除：日志段、检查周期和活动段等因素影响实际回收。容量估算不能只用“每天数据量×保留天数”，还要加入副本、索引、临时清理空间、负载变化和安全余量。

![Delete 与 Compact 分支及 Cleaner 核心流程](/assets/notes/kafka/kf-retention-review.svg)

[放大查看清理流程](/assets/notes/kafka/kf-retention-review.svg)。Delete 与 Compact 是可选或组合的策略，不是每条记录都必须先删除再压缩的串行步骤。

## 2. Compact 保留的是 Key 的状态线索

日志压缩清理会逐步清除同 Key 的旧值，适合变化日志或状态恢复等用途。它不会实时覆盖唯一键对应的记录，也不保证磁盘上每个 Key 始终只有一条记录。

例子：Key=A 先写版本 1，再写版本 2。普通事件审计可能关心两个版本；状态重建通常只需要最终状态。选择 compact 就必须接受某些中间事件不再完整可回放，不能同时把它当作永不丢历史的审计档案。

### Log Cleaner 内部工作机制

Log Cleaner（日志清理器）是 Broker 负责 Compaction（按 Key 压缩清理）的后台组件；清理线程选择合格日志、读取旧段并重写。它不是第 8 章的 gzip/lz4/zstd 编码器，也不是消费端提交位点时调用的同步删除接口。

Active Segment（活动日志段）仍接受追加，不参与这一轮普通 Cleaner 的可清理段范围。Cleaner 的 checkpoint（进度检查点）区分已处理过的 Clean（已清理）区域与尚待处理的 Dirty（待清理）区域；“Clean”不表示永远不会再被重写，因为新的 Key 版本可能淘汰其旧值。Dirty 也不表示内容损坏。

在 3.9.0 的 `LogCleanerManager` 中，候选范围还受 LSO（Last Stable Offset，最后稳定位点）、最小清理滞后等条件限制。Dirty Ratio（待清理字节比例）是可清理 Dirty 字节在相应总字节中的比例，不是“重复 Key 占比”，也不是逐条消息的年龄。`LogToClean.cleanableRatio` 依据可清理 Dirty 与 Clean 字节计算；活动段和当前不可清理尾部不能直接加进分母当作同一范围。

核心路径依次为：

1. **资格判断与调度**：`grabFilthiestCompactedLog()` 等逻辑挑选待清理分区，排除不可清理范围，并考虑比例和最大滞后条件。空日志或暂不合格日志继续等待。
2. **构建 Key → 最新 Offset 映射**：`Cleaner.buildOffsetMap()` 扫描本轮可覆盖范围，为 Key 记录遇到的最新位置。映射受内存和扫描上界限制，不是一次把整个无限日志装入内存。
3. **扫描与重写段**：`cleanSegments()` / `cleanInto()` 结合映射，保留相应最新值、仍需保留的 Tombstone（删除标记）及必要的事务/生产者状态。映射范围之外的记录不能直接当成旧版本扔掉。
4. **替换旧段**：将保留记录写入新的清理段并建立索引，通过受控的段替换流程切换，随后按实现的延迟删除流程回收旧文件。重写是因为直接在原文件中逐条挖洞会破坏批次、索引与读取关系。
5. **继续读取**：消费者看到清理后仍存在的逻辑记录；Offset 不重新编号，已有游标仍表示原来的逻辑位置。事务及幂等元数据还可能要求保留空批次等结构，不能把业务记录示意当成全部物理字节。

| Topic 配置                  | Kafka 3.9 默认       | 影响的条件                                                                              |
| --------------------------- | -------------------- | --------------------------------------------------------------------------------------- |
| `min.cleanable.dirty.ratio` | 0.5                  | 普通比例门槛；源码候选筛选使用大于该门槛，最大滞后路径还可促使合格范围参与清理          |
| `min.compaction.lag.ms`     | 0                    | Compaction Lag（压缩清理滞后）的最小时间约束，保护较新的记录暂不进入普通可清理范围      |
| `max.compaction.lag.ms`     | 9223372036854775807  | 最大清理滞后相关调度条件；不应解释为到了这一毫秒必然全部清理完毕                        |
| `delete.retention.ms`       | 86400000，即 24 小时 | Tombstone 的保留窗口；不是普通事件的 retention.ms，也不是生产者写入时刻加固定时间后必删 |

清理线程负载、可清理段边界、事务稳定范围和实际调度都会影响完成时间。现代 Magic=2 记录的 Tombstone 回收还使用批次的 delete horizon（删除期限）信息；3.9.0 `shouldRetainRecord()` 区分现代格式与旧格式。不能用旧段修改时间算法概括所有版本，更不能给出精确完成时刻。

## 3. Tombstone 与“空值”要准确区分

压缩Topic中，带Key的null Value可以表达删除标记。它不同于空字符串或零长度普通字节值，序列化协议必须区分。`delete.retention.ms`控制此类删除标记的保留，Kafka 3.9文档默认86400000ms，即一天；它不是精确到某毫秒必删除的定时器。

以一段假设的历史为例：A=v1，随后 A=null。持有旧快照的消费者本地仍有 A=v1，若离线期间错过 tombstone，增量恢复时可能再也收不到删除通知，从而错误保留 A。从空状态开始扫描时，本地没有 A，与删除后的最终状态可以一致；但如果扫描很慢，先读到了 v1，而 tombstone 在被读到前已被清理，仍可能留下旧状态。因此，完整扫描也需要满足删除标记窗口等恢复前提，不能认为 earliest 天然保证最终状态正确。[3.9 delete.retention.ms](https://kafka.apache.org/39/configuration/topic-level-configs/#delete.retention.ms)

`delete,compact` 可组合使用，但组合并不意味着保留所有 Key 的最终值直到永久：普通保留仍可能淘汰旧段。恢复时间要求应和整个策略一起验收，而不只检查 cleanup.policy 的名称。

### Offset 10～13 的状态演变

假设四条非事务记录均已提交，Key 编码一致，A 的 null 是真正的 Null Value；它们所在的非活动段已经可清理，没有后续 A/B 更新，也没有普通 Delete 淘汰。以下状态只展示业务记录，不展示可能保留的批次元数据：

| 阶段                                | 可保留的业务记录                     | 重建状态与前提                                                  |
| ----------------------------------- | ------------------------------------ | --------------------------------------------------------------- |
| 刚写入                              | 10:A=v1，11:B=x1，12:A=v2，13:A=null | 顺序应用后 A 已删除、B=x1；此时旧版本仍在文件中                 |
| 一轮覆盖这些 Key 的 Compaction 完成 | 11:B=x1，13:A=null                   | 映射识别 A 的最新位置 13，清掉 10/12；假设 Tombstone 尚需保留   |
| Tombstone 窗口仍有效                | 11:B=x1，13:A=null                   | 带有旧 A 状态的消费者仍有机会收到删除标记                       |
| 后续清理满足 Tombstone 回收条件     | 11:B=x1                              | 13 也可消失，A 不再有记录；不是第 13 条记录被改成 B，也不重编号 |

从空状态完整处理这个最终集合，可得到 B=x1、A 不存在；但只拿旧快照里的 A=v1 做增量恢复，若删除标记已消失，就可能错误保留 A。消费者从仍在保留范围内的已清理 Offset 12 开始读取时，可跳到实际存在的后续记录，例如尚存的 13；如果后面没有合格可见记录，就等待或返回空结果。若位置低于 Log Start Offset（日志起点，当前允许读取的最早逻辑边界），则是另一类越界/重置问题。Compaction 造成的内部空洞不等于起点一定前移。

纯 `compact` 不按普通时间保留规则删除每个 Key 的最终非 Null 状态，但中间历史仍不完整；`delete,compact` 会同时受到整段普通保留淘汰影响，最终非 Null 状态也不能当作永久快照。

## 4. 编码压缩与按 Key 清理的不同作用 {#_4-数据压缩不是日志压缩清理}

gzip、lz4、zstd 等编码压缩减少字节体积，通常不改变业务记录的逻辑含义。Compact 则依据 Key 清理旧版本，改变可保留的历史记录集合。中文里都叫“压缩”，但作用层次完全不同。

同样，副本不是独立备份：误删 Topic、错误保留设置或有权限的坏写入可能影响整套副本。灾备或归档需要独立评估版本、保留、权限与恢复能力。

## 5. 重放前先定义目标

重建查询视图前，应先明确目标：恢复最终状态，还是逐条重演完整事件。再检查数据保留范围、模式兼容、外部副作用和消费组位点，据此决定是使用独立新组、显式指定读取范围，还是受控调整位点。

不要在生产环境直接重置一个仍在线的组，然后观察“会不会好”。重放可能重复发邮件、重复调用支付接口或覆盖新的业务状态。可靠方法是隔离输出、确保幂等、记录范围，并设置人工停止与回退条件。本次没有重置任何位点。

### 停机 36 小时、Tombstone 窗口 24 小时

这是教学风险场景，不是“离线超过 24 小时必定丢失 Tombstone”的精确定理。库存服务恢复时持有旧状态，离线 36 小时，而 Topic 的 `delete.retention.ms=86400000`；期间可能有删除标记已经满足条件并被回收。即便组提交 Offset 仍在有效范围内，也不能据此证明所有增量删除都还在。

![重放与状态恢复的决策流程](/assets/notes/kafka/kf-replay-review.svg)

[放大查看恢复决策图](/assets/notes/kafka/kf-replay-review.svg)。

1. **确认目标**：完整事件审计需要完整事件历史；状态重建只要求正确的当前状态。压缩日志无法无条件满足前者。
2. **读取边界与来源**：按分区记录 Log Start Offset、日志末端、组 Committed Offset（已提交恢复位点）、Topic 策略、原快照版本和对应源位点。已提交位置不证明本地数据库与它一致。
3. **区分自动重置策略**：Java 3.9 `auto.offset.reset=earliest` 从仍可读取的起点恢复，`latest` 跳到当前末端，`none` 在缺少有效位置时抛出错误。它们主要处理没有有效提交或位置越界，不会检测所有 Compaction 内部空洞，也不会主动覆盖一个仍有效的提交。这些取值不能直接照搬到所有客户端；librdkafka 的报错策略名称为 `error`。
4. **选择可靠起点**：若不能证明旧快照后的增量仍完整，应取得权威业务快照及与之匹配的每分区增量起点；或在满足完整扫描与 Tombstone 窗口条件时从空状态重建。快照与日志衔接要有一致性协议，不能随意把“今天导出的数据库”和“任意 Kafka Offset”拼起来。
5. **隔离重放与核对**：使用新的实验/恢复组与隔离输出，禁用支付、发邮件等真实副作用，以稳定事件 ID 或业务版本幂等应用，比较记录数、关键实体状态和业务不变量。不要直接改在线组。
6. **切换或停止**：只有边界、模式版本、权限、删除覆盖及核对结果都满足要求才切换。来源缺失、无法证明快照衔接、重复副作用或核对不一致时停止，保留旧结果与运行记录，按预定方案回退。

把在线组直接重置为 earliest，最多改变读取位置，不能找回已删除历史、已回收 Tombstone，也不能替外部数据库撤销已经执行的业务效果。

### 独立测试 Topic：三种策略对照

**未执行的实验步骤**：需要已运行且允许实验的 Kafka 3.9 集群，Cleaner 已启用；只创建全新的实验 Topic，不清理既有业务数据。以下为发行包目录下的 Bash，不更改 Broker 级配置：

```bash
for policy in delete compact delete,compact; do
  suffix=${policy//,/-}
  bin/kafka-topics.sh --bootstrap-server localhost:9092 --create \
    --topic "r3-clean-$suffix" --partitions 1 --replication-factor 1 \
    --config "cleanup.policy=$policy" --config segment.ms=1000 \
    --config segment.bytes=1048576 --config retention.ms=120000 \
    --config min.cleanable.dirty.ratio=0.01 \
    --config min.compaction.lag.ms=0 --config max.compaction.lag.ms=60000 \
    --config delete.retention.ms=60000

  printf '%s\n' 'A:v1' 'B:x1' 'A:v2' 'A:__NULL__' | \
    bin/kafka-console-producer.sh --bootstrap-server localhost:9092 \
      --topic "r3-clean-$suffix" --property parse.key=true \
      --property key.separator=: --property null.marker=__NULL__
done
```

这些配置仅缩短实验观察窗口，不推荐用于生产。全新 Topic 的实际 Offset 通常从 0 开始，不能把命令输出伪装成正文的 10～13。`__NULL__` 由控制台的 null.marker 转为 Null Value；发送字符串 `null` 并不等价。等待超过段时间后再向各 Topic 写入不同 Key 的少量标记，帮助触发滚动；持续观察而非断言 60 秒整必清。

以新的独立组用 `kafka-console-consumer.sh --from-beginning --property print.key=true --property print.offset=true` 分别扫描，记录真实时间、配置、Log Start Offset 与仍存在的记录。预期 Delete 淘汰满足条件的旧段，Compact 逐步去旧值并保留/回收删除标记，联合策略还会整段淘汰。若长期不清理，先检查活动段、稳定范围、Cleaner 状态和调度条件，不手工删除段文件来制造“成功”。

## 参考

- [Topic 保留、cleanup.policy 与 tombstone 配置](https://kafka.apache.org/39/configuration/topic-level-configs/)
- [Kafka Log Compaction 设计](https://kafka.apache.org/39/design/design/#log-compaction)
- [LogCleaner.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/log/LogCleaner.scala)：`clean`、`buildOffsetMap`、`cleanSegments`、`shouldRetainRecord`。
- [LogCleanerManager.scala 3.9.0](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/log/LogCleanerManager.scala)：候选资格、范围、比例和最大滞后调度。
- [Java Consumer 配置 3.9](https://kafka.apache.org/39/configuration/consumer-configs/) / [librdkafka v2.8.0 配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)：重置策略名称及适用范围。
