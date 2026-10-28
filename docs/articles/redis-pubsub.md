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

PubSub 将当前发布的消息分发给相应的在线订阅者，适用于部分通知或实时推送场景。频道本身不会保存一份历史队列，供将来的消费者读取。

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

这里频道匹配 demo:event:*。预期 A 因直接订阅收到 message，又因模式订阅收到 pmessage；这是两条匹配路径，不是业务事件唯一投递。若交互客户端在订阅后占用输入，应通过支持订阅状态命令的客户端 API 建立这两个订阅；也可分成两个订阅客户端观察分别接收，但那不再是“同一连接收到两类回复”的演示。RESP2 的发布命令放在独立连接，不能将整段当成单连接普通命令脚本。

PUBLISH 的返回与接收该发布的订阅关系有关，不证明这些消费者已经完成业务处理。消费者收到后立即崩溃，发布端也不会自动得到可靠的业务失败通知。

模式订阅和直接订阅可能使同一客户端通过不同匹配关系收到多份相关消息，应用不应默认每个业务事件只会出现一次。[PubSub 投递语义](https://redis.io/docs/latest/develop/pubsub/)

## 2. 断线后的状态对齐与消息恢复 {#_2-为什么断线会丢消息}

订阅者离线期间，没有一个自动历史游标让它重放所有遗漏消息。主副本切换、网络断开或缓冲区超限都可能中断订阅。

一种合适的设计是只把消息用作“状态可能已变”的提示，让消费者能够从权威数据源重新对齐状态。对于无法重建、也不允许丢失的业务事件，应采用具有持久日志、确认和恢复方案的机制。

即使发布消息与更新业务对象发生在相同应用流程，也不自动获得跨系统原子性。数据库更新成功但发布失败，或发布成功但数据库事务回滚，都要在设计时考虑。

## 3. 连接状态与协议版本

RESP2 订阅状态下，可执行命令需要按协议规则判断，包括适用的 PING、QUIT 等命令；RESP3 的订阅行为另行查阅。

为了减少状态混用，通常把订阅连接与普通命令连接分开管理。客户端是否支持 RESP3、PUSH 回复和自动重订阅，要看库版本，不能只看 Redis 服务端版本。

## 4. 慢订阅者与输出缓冲

如果发布速度持续高于读取和处理速度，服务端输出缓冲可能不断增长，进而触发配置中的连接关闭条件。调大缓冲只能延后问题出现，无法提高消费者的处理能力，还可能增加内存风险。

应观察发布速率、消息大小、消费者延迟、断线次数和补偿效果。MONITOR 会增加开销并暴露数据，不作为持续统计业务消息的默认方法。

## 5. Redis 7.0+ 的 Sharded PubSub

Sharded PubSub 提供 SPUBLISH、SSUBSCRIBE 等能力，把适用频道按槽组织，减少传统集群广播的某些扩散成本。它不是“把 PubSub 升级成持久队列”。[Sharded PubSub](https://redis.io/docs/latest/develop/pubsub/#sharded-pubsub)

迁移前需要核对频道路由、客户端 API、权限和重连行为，不能把普通 PUBLISH 与分片订阅接口任意交叉。

## 6. 实时通知与 Streams 条目日志 {#_6-与下一章的区别}

PubSub 以实时分发为中心，Streams 以条目和消费位置为中心。后者可以为重放、pending 和确认提供结构，但业务幂等和持久化仍需设计，不能只换一种 API 名字就宣称消息绝不丢失。

[返回本册目录](/collections/redis/)
