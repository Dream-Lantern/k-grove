---
id: redis-streams
title: 第十二章 Streams、消费组与重复处理
description: Stream 保存带有 ID 的条目，每条条目包含字段和值。应用可以按位置读取，消费组则在日志条目之外维护读取进度和待确认等状态。
date: '2026-10-25'
updated: '2026-10-25'
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

> 新增补充章节。Streams 自 Redis 5.0 提供；本章基础流程面向支持相应命令的版本，XAUTOCLAIM 标明 6.2+，8.x 新接口不混进旧流程。未创建流或消费者。

## 1. 条目日志与消费状态

Stream 保存带有 ID 的条目，每条条目包含字段和值。应用可以按位置读取，消费组则在日志条目之外维护读取进度和待确认等状态。

![写入、组内消费、PEL 与确认接管](/assets/notes/redis/redis-study-streams.svg)

同一组内的消费者通常分工领取新条目；不同消费组可以各自维护处理进度。这与 PubSub 对在线订阅者广播的语义不同。

## 2. 从写入到读取

新增示例，未执行：

```redis
XADD demo:events * event_id e-42 kind created
XGROUP CREATE demo:events workers 0
XREADGROUP GROUP workers consumer-a COUNT 10 STREAMS demo:events >
```

`*` 请求生成条目 ID；`XGROUP CREATE ... 0` 让新组从历史起点开始，使用 `$` 则有不同的起始位置。创建已有组会报错，需要由应用按部署流程处理，而不是无限重复创建。

`>` 读取该组尚未投递的新条目，不等于自动重新投递所有 pending。命令的键、ID 与参数位置参见 [XADD](https://redis.io/docs/latest/commands/xadd/)、[XGROUP CREATE](https://redis.io/docs/latest/commands/xgroup-create/)及 [XREADGROUP](https://redis.io/docs/latest/commands/xreadgroup/)。

## 3. PEL 记录尚未确认的处理

条目交给消费者后，在适用模式下会进入 Pending Entries List。消费者完成业务后，对实际收到的条目 ID 执行 XACK。

确认不是删除日志内容。XACK 的作用是相应组的确认管理；其他组、条目保留和修剪是不同维度。[XACK](https://redis.io/docs/latest/commands/xack/)

若消费者在业务成功后、确认前崩溃，重新接管会再次看到该事件。用稳定 event_id 去重、事务写入或业务状态机，才能处理副作用重复。

### 3.1 把领取和确认连起来

新增教学模板，接续上节：保留 XREADGROUP 返回的实际条目 ID，将下面的 STREAM_ID 替换为该 ID。它不是键名，也不是 event_id 字段。只有业务成功提交后才确认：

```redis
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

## 4. 发现与接管失败消费者

XPENDING 可查看待确认状态。Redis 6.2+ 的 XAUTOCLAIM 能按空闲时间等条件接管适用条目；它不是证明旧消费者已经停止。[XAUTOCLAIM](https://redis.io/docs/latest/commands/xautoclaim/)

接管阈值过小，可能接管仍在正常处理的大任务；过大又会延迟恢复。因此，需要结合处理耗时、心跳、重试次数和死信策略评估。

例如由 consumer-b 接管满足至少 60000 毫秒空闲条件的条目，起始游标为 0-0：

```redis
XAUTOCLAIM demo:events workers consumer-b 60000 0-0 COUNT 10
```

未达到空闲阈值时，即使存在 pending，也不一定能领取。处理成功后，应使用实际接管到的 ID 调用上节的 XACK。读取下一批时，继续传入返回的游标，直到返回 0-0；中途领取结果为空，并不代表后面没有可扫描条目。扫描完成后，其他条目可能随时间推移达到空闲阈值，恢复任务可以按应用策略再次扫描。

| 版本 | XAUTOCLAIM 回复结构                                 |
| ---- | --------------------------------------------------- |
| 6.2  | 下一游标、成功接管条目，共两项                      |
| 7.0+ | 再增加已从 PEL 清理的、流本体已不存在的条目 ID 列表 |

不要把新文档的三元素结构直接套给 6.2。PEL 中的引用与流本体不是同一份数据；删除或修剪本体后，恢复代码还应处理内容已经不存在的情况。[XAUTOCLAIM 游标及版本变化](https://redis.io/docs/latest/commands/xautoclaim/)

NOACK 省去适用的 pending 跟踪，也会改变失败恢复能力。只为了降低状态开销而开启，可能破坏业务期望。

## 5. 保留、修剪与持久化

Stream 不是无限增长的免费日志。MAXLEN、MINID 等修剪条件需要与最慢消费者和业务保留期协调；pending 引用与条目本体的删除关系必须理解。

重启能恢复什么还受 Redis 持久化、复制及故障切换条件影响，不因为“有日志 ID”就自动具有外部持久消息系统的全部保证。

Redis 8.2+ 的 XACKDEL 等能力进一步组合确认和条件删除，不能在 6.x/7.x 直接调用，也不能忽略多个组的引用语义。[XACKDEL](https://redis.io/docs/latest/commands/xackdel/)

| XACKDEL 策略，8.2+ | 确认与删除的关键区别                                |
| ------------------ | --------------------------------------------------- |
| KEEPREF，默认      | 确认指定组并尝试删除条目本体，保留其他相关 PEL 引用 |
| DELREF             | 删除条目本体，并清理所有组的相应 PEL 引用           |
| ACKED              | 确认指定组，只在所有消费组都已读取并确认时删除条目  |

省略策略不等于等待所有组处理完成。假设组 A 已完成、组 B 尚未读取，删除本体会影响 B 之后取得内容；保留 PEL 引用也不意味着本体仍在。不能把旧流程的 XACK 机械替换成无选项 XACKDEL。删除行为与逐 ID 返回还应按目标版本核对，本节不执行清理操作。

## 6. 验证要覆盖故障时刻

应分别测试领取前、领取后、业务提交后、确认前后、修剪期间和节点切换时的行为。同时观察积压数量、最老 pending、处理失败与去重结果，不能只确认消费者进程仍在运行。

本章只给出可审阅的机制和示意命令，不声称已验证你的任务系统。

[返回本册目录](/collections/redis/)
