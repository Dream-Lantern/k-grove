---
id: redis-lists
title: 第五章 List、阻塞读取与可靠任务转移
description: List 是按顺序保存字节串的序列，支持两端插入与弹出。它既能表达栈，也能表达队列；选哪一端必须前后一致。
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
order: 5
---

# 第五章 List、阻塞读取与可靠任务转移

List 是按顺序保存字节串的序列，支持两端插入与弹出。它既能表达栈，也能表达队列；选哪一端必须前后一致。

## 1. 先画清左右方向

新增例子，未执行：

```redis
RPUSH demo:tasks task-a task-b
LPOP demo:tasks
LRANGE demo:tasks 0 9
LLEN demo:tasks
```

RPUSH 依次从右端追加，LPOP 从左端取出，形成 FIFO。若在 LPUSH 后使用 LPOP，则从同一侧存取，近似栈行为。RPOP 从右端弹出，而不是原文所写的“左侧”。

LRANGE 的结束下标包含在结果里，0 -1 表示全部。列表很长时，不要把全量范围读取当作无成本查看。

## 2. 阻塞的是等待中的客户端

BLPOP、BRPOP 可以在暂时没有元素时等待，时间单位是秒；0 表示不因该等待超时而结束，不代表永久无条件存活。连接、进程或权限异常仍会终止等待。

一个客户端等待空列表，不会让整个 Redis 停止处理其他命令。这与执行一个耗时脚本占用主要执行路径不同。

多键阻塞命令涉及键顺序、就绪顺序及等待客户端的规则，不能用一句“所有生产者消费者严格公平”概括。Cluster 还需要满足适用的同槽约束。

## 3. 简单弹出队列的丢失窗口

如果消费者 LPOP 成功后立即崩溃，任务已离开待处理列表，业务却没有完成。List 本身没有自动给这条任务补一个确认与重投协议。

新增的可靠队列思路，是把待处理项原子地移到处理中列表，再由应用在完成后确认和清理：

![待处理、处理中与业务确认的分工](/assets/notes/redis/redis-study-list-work.svg)

Redis 6.2+ 的 LMOVE / BLMOVE 可以表达适用的原子移动。以下新增正常路径流程使用统一命名，假定学习键是新建空列表、任务 ID 唯一，没有其他消费者，未执行：

```redis
RPUSH demo:{tasks}:ready task-a task-b
LMOVE demo:{tasks}:ready demo:{tasks}:processing LEFT RIGHT
LRANGE demo:{tasks}:processing 0 9
```

预期 task-a 从 ready 左侧进入 processing 右侧，而不是消失；task-b 仍待领取。业务成功提交后，按实际领取的唯一 ID 清理该项：

```redis
LREM demo:{tasks}:processing 1 task-a
```

在上述无竞争前提下，预期删除数为 1。若业务失败或消费者崩溃，不应提前执行这次确认。这段流程只覆盖正常处理时的移动—业务—确认过程，下面的接管协议仍需由应用实现。

两个键使用相同 hash tag 是为了示意 Cluster 同槽，不能因此获得跨系统事务。[LMOVE 的版本和可靠队列模式](https://redis.io/docs/latest/commands/lmove/)

## 4. 可靠性仍有应用部分

应用要记录处理时间、重试次数、任务标识和可接管条件。移到 processing 后崩溃，仍需要发现并重新处理；重新处理可能与旧进程恢复竞争，因此还需幂等。

新增恢复状态机示意：识别超时任务 → 验证当前处理资格/尝试标识 → 原子地登记重试并转回待处理状态 → 再次领取 → 幂等处理 → 按当前尝试确认。processing List 本身没有处理时间、owner 或租约字段，不能单靠 LRANGE 判断旧进程已死；租约等关联状态与转移若分开更新，也会产生新的崩溃窗口。完整实现需要受控原子逻辑和外部副作用幂等，不是后台定时 LREM 后 RPUSH 两步就自动可靠。

若列表中允许任务内容重复，仅用 LREM 删除某个字符串，可能误删另一份内容相同的任务。因此，应为任务设置明确身份，不能因内容相等就认定属于同一次处理。

需要日志位置、消费组与 pending 管理时，可以考虑后面的 Streams。选择它也不自动获得外部业务 exactly-once。

## 5. 修剪、随机访问与对象规模

LREM 根据 count 的正负与大小决定方向和数量；LTRIM 保留指定下标范围，会丢弃范围外内容，属于真实数据变更。

中间位置访问、删除匹配元素与两端操作的成本不同，不把所有 List 命令都写成 O(1)。历史 ziplist/linkedlist 规则与 quicklist/listpack 演进也不能混为一个当前实现。

持续积压时，关注任务数量、每条尺寸、消费者速率和失败比例。只是不断增大 List 容量，通常不能修复消费者错误或下游瓶颈。

[返回本册目录](/collections/redis/)
