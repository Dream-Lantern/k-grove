---
id: redis-streams
title: 第十二章 Streams、消费组与重复处理
description: "Stream 保存带有 ID 的条目，每条条目包含字段和值。应用可以按位置读取，消费组则在日志条目之外维护读取进度和待确认等状态。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - redis
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: redis
series: redis-learning
order: 12
---

# 第十二章 Streams、消费组与重复处理

> 版本范围：Streams 自 Redis Open Source 5.0.0 提供；基本流程以 7.2.0 为参照，XAUTOCLAIM 自 6.2.0 提供，8.2.0 的新接口单独列出。以下代码块是 Redis 命令或明确标注的模板，不是 Shell 命令；所有预期结果均为教学推演。

## 1. 条目日志与消费状态

Stream 保存带有 ID（Identifier，标识符）的条目，每条条目包含字段和值。应用可以按位置读取，消费组则在日志条目之外维护读取进度和待确认等状态。

![写入、组内消费、PEL 与确认接管](/assets/notes/redis/redis-study-streams.svg)

同一组内的消费者通常分工领取新条目；不同消费组可以各自维护处理进度。这与 PubSub 对在线订阅者广播的语义不同。

可以把状态分成三层：

| 层次                                        | 保存什么                                                                                | 不代表什么                 |
| ------------------------------------------- | --------------------------------------------------------------------------------------- | -------------------------- |
| Stream 本体                                 | 条目 ID 和字段内容                                                                      | 不代表某个业务已完成       |
| Consumer Group（消费组）进度                | last-delivered-id，即该组最后投递的新条目位置                                           | 读到后面不代表前面都已确认 |
| Pending Entries List（PEL，待确认条目列表） | 该组已投递但未确认的 ID，以及所属消费者、空闲时间和投递次数；消费者也有对应的待确认索引 | 引用不是消息内容的副本     |

例如同一条 `1000-0` 可以同时出现在 workers 和 audit 两个组的 PEL 中，在各组内分别归属一个消费者。workers 的推进、确认或接管不会替 audit 完成同样操作。需要先比较广播与恢复边界时，可回看 [第 11 章 PubSub](/articles/redis-pubsub.html)；简单队列和处理中任务转移见 [第 5 章 List](/articles/redis-lists.html)。

## 2. 从写入到读取

新增示例：

```redis
XADD demo:events * event_id e-42 kind created
XGROUP CREATE demo:events workers 0
XREADGROUP GROUP workers consumer-a COUNT 10 STREAMS demo:events >
```

`*` 请求生成条目 ID；`XGROUP CREATE ... 0` 让新组从历史起点开始，使用 `$` 则有不同的起始位置。创建已有组会报错，需要由应用按部署流程处理，而不是无限重复创建。

Stream ID 通常形如 `1730000000000-0`：前半是毫秒时间部分，后半是同一毫秒内的序号。自动 ID 会维持流内递增顺序，不应当作可信业务发生时间；它与字段 `event_id` 的业务事件标识不同。手动指定完整 ID 时，必须大于该流已有的最大 ID，且不能使用 `0-0`。

下面是独立的组创建示例；使用不同组名，避免把两条命令误当成重复创建 workers：

```redis
XGROUP CREATE demo:events future-workers $
XGROUP CREATE demo:events:new workers 0 MKSTREAM
```

`0` 或 `0-0` 从历史起点开始；`$` 记录创建组当时的流尾位置，后续用 `>` 读取之后新增的条目，不读取创建前已有内容。它不是一个“未来消息 ID”。`MKSTREAM` 在键不存在时创建空流；它不允许重复创建同名组。在键和组满足上述前提时，两条命令的预期回复均为 `OK`。

`>` 读取该组尚未投递的新条目，不等于自动重新投递所有 pending。命令的键、ID 与参数位置参见 [XADD](https://redis.io/docs/latest/commands/xadd/)、[XGROUP CREATE](https://redis.io/docs/latest/commands/xgroup-create/)及 [XREADGROUP](https://redis.io/docs/latest/commands/xreadgroup/)。

## 3. PEL 记录尚未确认的处理

默认用 `XREADGROUP ... >` 领取新条目后，该组会将其加入 PEL 并记录消费者归属。消费者完成业务后，对实际收到的条目 ID 执行 XACK。

确认不是删除日志内容。XACK 的作用是相应组的确认管理；其他组、条目保留和修剪是不同维度。[XACK](https://redis.io/docs/latest/commands/xack/)

若消费者在业务成功后、确认前崩溃，重新接管会再次看到该事件。用稳定 event_id 去重、事务写入或业务状态机，才能处理副作用重复。

以下是可逐行输入的独立教学示例，要求学习实例中 `demo:events:ack` 原先不存在，没有并发写入；固定 ID 用于明确后续确认对象，不表示实际事件时间。

```redis
XADD demo:events:ack 1000-0 event_id e-01 kind created
XGROUP CREATE demo:events:ack workers 0
XGROUP CREATE demo:events:ack audit 0
XREADGROUP GROUP workers consumer-a COUNT 1 STREAMS demo:events:ack >
XREADGROUP GROUP audit auditor COUNT 1 STREAMS demo:events:ack >
XACK demo:events:ack workers 1000-0
XPENDING demo:events:ack workers
XPENDING demo:events:ack audit
XRANGE demo:events:ack - +
```

预期两次读取都得到 `1000-0`；XACK 返回整数 `1`，workers 的 pending 总数变为 `0`，audit 仍为 `1`，XRANGE 仍返回该条目的字段内容。XACK 只移除指定组及其消费者的相应 PEL 记录，不删除 Stream 本体，也不确认其他组。

### 3.1 把领取和确认连起来

新增教学模板，接续上节：保留 XREADGROUP 返回的实际条目 ID，将下面的 STREAM_ID 替换为该 ID。它不是键名，也不是 event_id 字段。只有业务成功提交后才确认：

```text
XACK demo:events workers STREAM_ID
XPENDING demo:events workers
```

若这条 ID 原先确在 workers 的 PEL 中，XACK 的预期返回为 1；同一 ID 再确认通常返回 0。它不会删除流本体，不会替其他组确认，也不证明外部数据库事务已提交。

再写入另一个教学事件并由 consumer-a 领取，但暂不确认，形成恢复情景：

```redis
XADD demo:events * event_id e-43 kind updated
XREADGROUP GROUP workers consumer-a COUNT 10 STREAMS demo:events >
XPENDING demo:events workers
XREADGROUP GROUP workers consumer-a COUNT 10 STREAMS demo:events 0
```

这里非 `>` 的 ID 路径用于读取 consumer-a 自己的 pending 历史，不是任意领取其他消费者的 pending。实际返回可能受已有数据和并发影响，不能预先写死为“恰好一条”。此流程没有在任何实例执行。

## 4. 从 Pending 检查到空闲条目接管 {#_4-发现与接管失败消费者}

XPENDING 可查看待确认状态。Redis Open Source 6.2.0 起的 XAUTOCLAIM 能按空闲时间等条件接管适用条目；它不是证明旧消费者已经停止。[XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/)

接管阈值过小，可能接管仍在正常处理的大任务；过大又会延迟恢复。因此，需要结合处理耗时、心跳、重试次数和死信策略评估。

例如由 consumer-b 接管满足至少 60000 毫秒空闲条件的条目，起始游标为 0-0：

```redis
XAUTOCLAIM demo:events workers consumer-b 60000 0-0 COUNT 10
```

故障推演：consumer-a 先领取条目，随后崩溃或暂停；该 pending 的空闲时间达到阈值后，consumer-b 执行上述命令，将符合条件的条目归属改为自己并重置空闲计时。这里的空闲时间是距上次投递或接管的时间，不是业务处理进度，也不是消费者心跳。若 A 只是暂停，之后仍可能继续原业务，Redis 不会替应用中止它。

因此接管不提供 Exactly-once（恰好一次）业务效果。需要幂等（Idempotency，重复处理不重复产生副作用），必要时让外部资源检查 Fencing Token（栅栏令牌，拒绝过期执行者写入）。相关边界见 [第 18 章事务与 Lua](/articles/redis-transactions-lua-functions.html)和 [第 28 章分布式锁与限流](/articles/redis-locks-rate-limits.html)。

`COUNT 10` 至多尝试领取 10 条，不保证返回 10 条；在 Redis Open Source 7.2.0 中，一次最多检查 `COUNT × 10` 个 PEL 记录，所以扫描量不等于返回量。普通接管会增加投递尝试次数；加 `JUSTID` 时，成功领取部分只返回 ID、不返回字段，也不增加该次数，但仍改变归属并重置空闲时间。[7.2.0 接管实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_stream.c)

未达到空闲阈值时，即使存在 pending，也不一定能领取。处理成功后，应使用实际接管到的 ID 调用上节的 XACK。读取下一批时，继续传入返回的游标，直到返回 0-0；中途领取结果为空，并不代表后面没有可扫描条目。扫描完成后，其他条目可能随时间推移达到空闲阈值，恢复任务可以按应用策略再次扫描。

| 版本                       | XAUTOCLAIM 回复结构                                     |
| -------------------------- | ------------------------------------------------------- |
| Redis Open Source 6.2.0    | 下一游标、成功接管条目，共两项                          |
| Redis Open Source 7.0.0 起 | 再增加已从该组 PEL 清理的、流本体已不存在的条目 ID 列表 |

不要把新文档的三元素结构直接套给 6.2。PEL 中的引用与流本体不是同一份数据；删除或修剪本体后，恢复代码还应处理内容已经不存在的情况。[XAUTOCLAIM 游标及版本变化](https://redis.io/docs/latest/commands/xautoclaim/) · [6.2.0 实现](https://raw.githubusercontent.com/redis/redis/6.2.0/src/t_stream.c) · [7.0.0 实现](https://raw.githubusercontent.com/redis/redis/7.0.0/src/t_stream.c)

对 `XREADGROUP ... >` 的新条目投递，两种模式的差别是：

| 模式  | 是否加入该组 PEL | 崩溃后能否通过该 PEL 接管          |
| ----- | ---------------- | ---------------------------------- |
| 默认  | 是               | 内容仍在且满足接管条件时可以       |
| NOACK | 否               | 不可以，未留下这次投递的待确认记录 |

NOACK 省去 pending 跟踪，不提高可靠性，适合能接受丢失或有其他恢复来源的场景。指定历史 ID 读取自己的 pending 时，NOACK 不发挥跳过记录的作用。它也不是删除流内容的选项。

## 5. 保留、修剪与持久化

Stream 不是无限增长的免费日志。MAXLEN、MINID 等修剪条件需要与最慢消费者和业务保留期协调；pending 引用与条目本体的删除关系必须理解。

以下是三种修剪策略示例，不是要求连续执行的生产清理脚本。返回整数表示实际删除的条目数，取决于已有内容：

```redis
XTRIM demo:events MAXLEN 1000
XTRIM demo:events MAXLEN ~ 1000
XTRIM demo:events MINID 1730000000000-0
```

MAXLEN 按条目数量修剪；省略符号等同于 `=`，要求精确限制。`~` 允许按内部存储块近似修剪，通常工作更少，但剩余长度可能高于目标。MINID 自 Redis Open Source 6.2.0 提供，删除小于阈值 ID 的条目，并非按业务时间字段过滤。7.2.0 的修剪不自动清理各组 PEL；过早修剪会让 pending 只剩 ID，无法恢复原内容。[XTRIM](https://redis.io/docs/latest/commands/xtrim/)

Redis Open Source 8.2.0 增加以下引用管理能力，不能在 6.x/7.x 直接调用：

| 命令    | 语法示意与返回                                                                                                 |
| ------- | -------------------------------------------------------------------------------------------------------------- |
| XACKDEL | `XACKDEL key group [KEEPREF或DELREF或ACKED] IDS numids id ...`；先确认指定组，再按策略删除；逐 ID 返回状态数组 |
| XDELEX  | `XDELEX key [KEEPREF或DELREF或ACKED] IDS numids id ...`；按策略删除，不执行指定组确认；逐 ID 返回状态数组      |
| XADD    | 如 `XADD demo:events KEEPREF MAXLEN ~ 1000 * event_id e-44`；追加时修剪可指定引用策略，返回新条目 ID           |
| XTRIM   | 如 `XTRIM demo:events MAXLEN = 1000 DELREF`；修剪时指定引用策略，返回删除的条目数                              |

前两行是语法模板，方括号、中文“或”和省略号不是可输入参数；`IDS` 后必须给出数量和相应 ID。后两行是完整 Redis 命令示例。四项能力省略引用策略时都采用 KEEPREF，默认行为不是等待所有组完成。[XACKDEL](https://redis.io/docs/latest/commands/xackdel/) · [XDELEX](https://redis.io/docs/latest/commands/xdelex/) · [XADD](https://redis.io/docs/latest/commands/xadd/) · [8.2.0 参数解析及删除实现](https://raw.githubusercontent.com/redis/redis/8.2.0/src/t_stream.c)

| 引用策略，Redis Open Source 8.2.0 起 | 确认、消息本体与引用的区别                                                                  |
| ------------------------------------ | ------------------------------------------------------------------------------------------- |
| KEEPREF，默认                        | 删除符合操作条件的消息本体，保留 PEL 引用；XACKDEL 已确认的指定组记录会移除，其他组引用保留 |
| DELREF                               | 删除本体并清理所有组相关的 PEL 引用；不能把清理引用当成业务已经完成                         |
| ACKED                                | 仅当所有消费组都已读取并确认时才允许删除；XACKDEL 会先确认指定组                            |

KEEPREF 不代表保留消息本体，PEL 中存在 ID 也不代表还能读到字段。假设组 A 已完成、组 B 尚未读取，默认删除本体会影响 B 之后取得内容；不能把旧流程的 XACK 机械替换成无选项 XACKDEL。ACKED 用于协调现有各组的生命周期，不能恢复已经被删掉的内容；它还可能使修剪无法达到目标长度。

下面是仅适用于 Redis Open Source 8.2.0 或更高版本的独立教学流程，要求 `demo:events:refs` 原先不存在，无其他消费者或组。

```redis
XADD demo:events:refs 1000-0 event_id e-01
XGROUP CREATE demo:events:refs group-a 0
XGROUP CREATE demo:events:refs group-b 0
XREADGROUP GROUP group-a a COUNT 1 STREAMS demo:events:refs >
XREADGROUP GROUP group-b b COUNT 1 STREAMS demo:events:refs >
XACKDEL demo:events:refs group-a ACKED IDS 1 1000-0
XRANGE demo:events:refs - +
XACKDEL demo:events:refs group-b ACKED IDS 1 1000-0
XDELEX demo:events:refs KEEPREF IDS 1 1000-0
```

预期第一次 XACKDEL 返回单元素数组 `[2]`：A 已确认，B 未确认，内容仍在，XRANGE 可读。第二次返回 `[1]`：B 确认后允许删除。最后 XDELEX 返回 `[-1]`，因为本体已不存在。

两条删除命令都逐 ID 返回 `1`（删除成功）、`2`（ACKED 条件未满足，未删除）或 `-1`，但 `-1` 的边界不同：XACKDEL 表示指定组 PEL 中没有该 ID，XDELEX 表示没有可删除的本体。XACKDEL 的 `1` 也可表示已确认并完成删除语义，即使本体早已不存在；不要把状态码等同于业务成功。DELREF 清理悬空引用也不代表找回内容。

Stream 本身仍是内存结构，重启能恢复什么取决于 RDB（Redis Database，数据库快照）和 AOF（Append Only File，只追加文件）等持久化配置；需要恢复的既有条目，也有消费组进度和 PEL 状态。快照间隔、日志落盘策略会留下不同丢失窗口。主从复制通常是异步的，故障切换时未复制完成的写入或确认状态仍可能丢失，不能因为有日志 ID 就视为具备 Kafka 等系统的全部可靠性保证。继续参见 [第 19 章 RDB 与 AOF](/articles/redis-rdb-aof.html)和 [第 21 章复制与 PSYNC](/articles/redis-replication-psync.html)。

## 6. 按领取、提交与确认阶段验证恢复 {#_6-验证要覆盖故障时刻}

应分别测试领取前、领取后、业务提交后、确认前后、修剪期间和节点切换时的行为。同时观察积压数量、最老 pending、处理失败与去重结果，不能只确认消费者进程仍在运行。

本章给出机制与教学命令，实际任务系统仍需按上述阶段验证处理、恢复和业务结果。

[返回本册目录](/collections/redis/)
