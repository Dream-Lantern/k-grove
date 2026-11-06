---
id: redis-pubsub
title: 第十一章 PubSub、消息通知与丢失边界
description: "PubSub 将当前发布的消息分发给相应的在线订阅者，适用于部分通知或实时推送场景。频道本身不会保存一份历史队列，供将来的消费者读取。"
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
order: 11
---

# 第十一章 PubSub、消息通知与丢失边界

PubSub（Publish/Subscribe，发布/订阅）将当前消息分发给相应的在线订阅者，适合通知和实时推送。它采用 At-most-once Delivery（最多一次投递）：对一次匹配的分发，消息至多发送一次，失败后不自动重发。断线期间不会自动重放，也没有供消费者恢复的历史队列或类似 Streams XACK 的业务确认。[官方投递语义](https://redis.io/docs/latest/develop/pubsub/#delivery-semantics)

以下是 Redis 命令与教学推演，未实际建立连接或发布消息。示例以 Redis Open Source 7.2.0 为参照，明确区分订阅连接和发布连接；交互客户端是否允许订阅后继续输入命令，需要另查其支持情况。

![发布者、频道与多个在线订阅者](/assets/notes/redis/redis-study-pubsub.svg)

## 1. 一对多通知

新增教学流程，未执行。订阅连接 A 依次建立频道订阅和模式订阅：

```redis
SUBSCRIBE demo:event:created
PSUBSCRIBE demo:event:*
```

另一个发布连接 B 发送：

```redis
PUBLISH demo:event:created "{\"event_id\":\"e-42\"}"
```

这里频道匹配 demo:event:*。预期 A 因直接订阅收到 message，又因模式订阅收到 pmessage；这是两条匹配路径，不是业务事件唯一投递。若交互客户端在订阅后占用输入，应通过支持订阅状态命令的客户端 API（Application Programming Interface，应用程序编程接口）建立这两个订阅；也可分成两个订阅客户端观察分别接收，但那不再是“同一连接收到两类回复”的演示。订阅状态的协议限制见第 3 节；发布命令使用独立连接，不能将整段当成单连接普通命令脚本。

在单实例且只有连接 A 及这两种订阅关系的前提下，PUBLISH 预期返回 `2`，A 分别收到 message（直接频道消息）和 pmessage（模式匹配消息）。这是同一个客户端的两条匹配关系各计一次，不是两名消费者完成了业务。[7.2.0 匹配与计数实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/pubsub.c)

| 返回值 | 可以说明什么                                   | 不能说明什么                                         |
| ------ | ---------------------------------------------- | ---------------------------------------------------- |
| 0      | 在返回值统计范围内，没有计入本次分发的订阅匹配 | 不代表业务事件未产生，也不保证集群其他节点没有订阅者 |
| 大于 0 | 有直接或模式匹配的分发被计入                   | 不等于独立人数、业务 ACK 或成功处理次数              |

ACK（Acknowledgment，确认）在这里指业务完成确认，PubSub 不提供这项协议。Redis Cluster 中，PUBLISH 的返回只统计与发布客户端连接到同一节点的接收者，不汇总远端节点；第 5 节的 SPUBLISH 也有这一返回范围限制。普通 PUBLISH 会分别计入同一客户端的频道匹配和每个匹配模式，不能把计数当成全局唯一消费者数。[PUBLISH 返回说明](https://redis.io/docs/latest/commands/publish/) · [SPUBLISH 返回说明](https://redis.io/docs/latest/commands/spublish/)

模式订阅和直接订阅分别匹配，与最多一次投递并不矛盾，也不是 Redis 随机重发。应用不应默认每个业务事件只出现一次；如需防止重复业务效果，应使用稳定 event_id（业务事件标识）及受控去重机制。[直接与模式重复匹配](https://redis.io/docs/latest/develop/pubsub/#messages-matching-both-a-pattern-and-a-channel-subscription)

Channel（频道）不属于某个逻辑 DB（Database，数据库）。另做一个独立实验：在包含 DB 1、DB 10 的非 Cluster 学习实例上，仅以下订阅者在线，先用订阅连接执行：

```redis
SELECT 1
SUBSCRIBE demo:event:created
```

确认订阅建立后，另一条发布连接执行：

```redis
SELECT 10
PUBLISH demo:event:created hello
```

预期发布返回 `1`，订阅者仍收到 hello，两个 SELECT 并不隔离频道。可以将环境放入名称，例如 `demo:dev:order:created`、`demo:test:order:created`、`demo:prod:order:created`；命名用于避免冲突，本身不是权限控制。[PubSub 与数据库](https://redis.io/docs/latest/develop/pubsub/#database--scoping)

## 2. 断线后的状态对齐与消息恢复 {#_2-为什么断线会丢消息}

订阅者离线期间，没有一个自动历史游标让它重放所有遗漏消息。主副本切换、网络断开或缓冲区超限都可能中断订阅。

故障推演：Publisher（发布者）执行 PUBLISH → Redis 分发 → Subscriber（订阅者）A 收到 → A 处理业务时崩溃。消息分发成功不等于业务成功，Redis 不会据此重新发送，发布者也收不到可靠的业务失败确认。若要补偿，只能依赖应用设计的权威状态、事件记录或其他恢复来源。

一种合适的设计是只把消息用作“状态可能已变”的提示，让消费者能够从权威数据源重新对齐状态。对于无法重建、也不允许丢失的业务事件，应采用具有持久日志、确认和恢复方案的机制。

即使发布消息与更新业务对象发生在相同应用流程，也不自动获得跨系统原子性。数据库更新成功但发布失败，或发布成功但数据库事务回滚，都要在设计时考虑。

## 3. 连接状态与协议版本

RESP2（Redis Serialization Protocol version 2，Redis 序列化协议第 2 版）把订阅连接置于受限状态。以 Redis Open Source 7.2.0 的命令检查为准，允许：

| 类别     | 命令                                    |
| -------- | --------------------------------------- |
| 建立订阅 | SUBSCRIBE、PSUBSCRIBE、SSUBSCRIBE       |
| 取消订阅 | UNSUBSCRIBE、PUNSUBSCRIBE、SUNSUBSCRIBE |
| 连接管理 | PING、RESET、QUIT                       |

RESET 自 Redis Open Source 6.2.0 起支持，可退出订阅并重置连接状态，不只是取消一个频道；SSUBSCRIBE、SUNSUBSCRIBE 则自 7.0.0 起支持。不能把这份 7.2.0 列表直接套给早期版本。[7.2.0 订阅状态检查](https://raw.githubusercontent.com/redis/redis/7.2.0/src/server.c) · [RESET](https://redis.io/docs/latest/commands/reset/)

RESP3（Redis Serialization Protocol version 3，Redis 序列化协议第 3 版）允许在订阅状态下发送其他命令，客户端需能区分普通回复与 PUSH（服务端主动推送）消息。服务端支持 RESP3 不意味着连接已经使用它，还需要客户端支持并完成相应协议协商；命令的权限等约束仍然存在。[RESP2/RESP3 订阅规则](https://redis.io/docs/latest/develop/pubsub/)

为了减少状态混用，通常把订阅连接与普通命令连接分开管理。客户端是否支持 RESP3、PUSH 回复和自动重订阅，要看库版本，不能只看 Redis 服务端版本。

## 4. 慢订阅者与输出缓冲

如果发布速度持续高于读取和处理速度，服务端输出缓冲可能不断增长，进而触发配置中的连接关闭条件。调大缓冲只能延后问题出现，无法提高消费者的处理能力，还可能增加内存风险。

Redis Open Source 7.2.0 可通过配置文件的 `client-output-buffer-limit pubsub` 规则设置订阅客户端输出缓冲限制；硬限制超限或软限制持续超限时会关闭连接。它是配置项，不是可以单独输入的 Redis 命令，也不要将该短语直接当作 CONFIG GET 的完整参数。本章不写死不同部署的默认大小，应检查实际配置和运行状态。[7.2.0 输出缓冲配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

应观察发布速率、消息大小、消费者延迟、断线次数和补偿效果。MONITOR 会增加开销并暴露数据，不作为持续统计业务消息的默认方法。

## 5. Redis 7.0+ 的 Sharded PubSub

Redis Open Source 7.0.0 起的 Sharded PubSub（分片发布订阅）提供 SPUBLISH、SSUBSCRIBE 等命令。Shard Channel（分片频道）按 Redis Cluster 的 Hash Slot（哈希槽）规则映射；发布需路由到负责该槽的主节点，订阅可连接该分片的主节点或副本。相同频道名对应相同槽，消息限制在相应分片传播，减少传统全局 PubSub 的集群扩散范围。[Sharded PubSub 路由](https://redis.io/docs/latest/develop/pubsub/#sharded-pubsub) · [SSUBSCRIBE](https://redis.io/docs/latest/commands/ssubscribe/)

以下在 Redis Open Source 7.0.0 或更高版本的 Cluster 学习环境中使用能正确路由的客户端。先在一条连接上订阅：

```redis
SSUBSCRIBE demo:order:created
```

确认成功后，另一条连接将发布命令路由到该槽主节点：

```redis
SPUBLISH demo:order:created order-42
```

预期匹配的分片订阅者收到 smessage（分片频道消息）；返回整数仅包含发布节点本地接收者，不能据此写死集群总人数。分片发布不匹配普通 SUBSCRIBE/PSUBSCRIBE，普通 PUBLISH 也不替代 SPUBLISH；分片频道没有对应的模式订阅接口。传播范围缩小并未增加历史保存、业务确认或故障重放，仍需考虑丢失和业务幂等（Idempotency，使重复处理不重复产生业务效果）。[SPUBLISH](https://redis.io/docs/latest/commands/spublish/) · [7.2.0 分片与模式处理](https://raw.githubusercontent.com/redis/redis/7.2.0/src/pubsub.c)

迁移前需要核对频道路由、客户端 API、权限和重连行为，不能把普通 PUBLISH 与分片订阅接口任意交叉。

## 6. 实时通知与 Streams 条目日志 {#_6-与下一章的区别}

PubSub 以实时分发为中心，Streams 以条目和消费位置为中心。后者可以为重放、pending 和确认提供结构，但业务幂等和持久化仍需设计，不能只换一种 API 名字就宣称消息绝不丢失。

需要保存条目并追踪未确认处理时，继续读 [第 12 章：Streams、消费组与重复处理](/articles/redis-streams.html)，同时区分“保存了消息”和“外部业务恰好执行一次”。

[返回本册目录](/collections/redis/)
