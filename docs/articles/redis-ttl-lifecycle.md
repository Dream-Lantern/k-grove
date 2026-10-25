---
id: redis-ttl-lifecycle
title: 第十三章 TTL、主动过期与删除生命周期
description: TTL 决定数据何时不再有效；过期检查、对象删除和内存归还则是不同步骤。把它们当成同一时刻，容易误判内存和定时任务行为。
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
order: 13
---

# 第十三章 TTL、主动过期与删除生命周期

TTL 决定数据何时不再有效；过期检查、对象删除和内存归还则是不同步骤。把它们当成同一时刻，容易误判内存和定时任务行为。

![期限、过期处理与内存观察的不同阶段](/assets/notes/redis/redis-study-expiration.svg)

## 1. 单位与边界返回

新增示例，未执行：

```redis
SET demo:temporary value EX 60
TTL demo:temporary
PTTL demo:temporary
EXPIRE demo:temporary 120
PERSIST demo:temporary
```

TTL 是秒，PTTL 是毫秒。-1 表示存在但没有期限，-2 表示键不存在；剩余时间也可能是 0，不能只写成“必须大于 0 才存在”。

EXPIREAT/PEXPIREAT 使用相应的绝对时间，不能把参数当作持续时长。为不存在的键设置 TTL 不会生成新数据；不合适的非正期限可能导致立即删除，因此变更前需要核对参数。

## 2. 更新操作可能保留或清除期限

不要只记“写操作会不会重置过期”，而要分别看覆盖、原地修改与重命名：

| 操作                                    | 键级 TTL 的适用语义                                     |
| --------------------------------------- | ------------------------------------------------------- |
| 普通 SET 成功覆盖，未指定期限或 KEEPTTL | 清除旧 TTL；条件不满足而未写入，不等于已经清除          |
| SET … KEEPTTL                           | Redis 6.0+ 可保留已有 TTL；不存在键时不会凭空生成旧期限 |
| INCR、HSET 等适用的原地修改             | 保留键级 TTL，不等于保留所有成员级期限                  |
| RENAME                                  | 期限随源键转移；覆盖目标时不能继续沿用目标的旧 TTL      |

以上是键的期限。Redis 7.4+ 的 Hash 字段期限是另一层：普通 HSET 覆盖某个字段会清除该字段的 TTL，不能从“Hash 键的 TTL 没变”推出字段期限仍在。示例闭环见 [Hash 字段过期](/articles/redis-hashes.html)。[SET](https://redis.io/docs/latest/commands/set/) · [EXPIRE 的更新与重命名规则](https://redis.io/docs/latest/commands/expire/)

Redis 7.0+ 的 EXPIRE NX/XX/GT/LT 等条件可以表达适用的期限更新约束，命令版本与组合应以 [EXPIRE 文档](https://redis.io/docs/latest/commands/expire/)为准。

Hash field TTL 属于 7.4+ 的另一组能力；它不意味着 List、Set 或 GEO 的所有成员也同时获得统一成员过期命令。

## 3. 访问检查与主动处理

过期键可以在访问等路径中被识别，主动过期机制则在预算内检查并删除相应数据，而不是每个调度周期都遍历整个键空间。

调整 hz 或主动过期力度，可能改变 CPU 与清理节奏；不能由“值更大”推出所有请求都更快。后续版本还存在动态调度等条件，旧笔记里的固定公式和阈值应限定为当时实现。

大量具有相同 TTL 的键集中到期，还可能造成集中回源或清理压力。在业务允许时，可以按其容忍度加入过期抖动，但不应随意延长具有严格时效要求的数据。

## 4. 过期与淘汰有不同原因

expired_keys 与 evicted_keys 表示不同机制。前者与期限相关，后者与内存策略有关；volatile 策略的候选是有 TTL 的键，不是只剩已经过期的键。

逻辑上看不到键，也不保证 RSS 立即下降。分配器可能保留页面供后续复用，COW 或其他进程开销也会改变内存观察。

## 5. DEL 与 UNLINK

DEL 会按对象和实现执行删除，释放复杂大对象可能明显占用主要路径；UNLINK 将适用的内存回收移到异步路径，键的可见性先改变。

UNLINK 也有队列、后台 CPU 和最终回收成本，不能写成“永不阻塞且免费”。适用版本从 Redis 4.0 开始，真正维护前还要核对返回、权限与容量。[UNLINK](https://redis.io/docs/latest/commands/unlink/)

## 6. 过期不应充当唯一业务调度器

键空间通知可能有延迟、断线和投递边界。到期通知不是一个永久记录且必达的任务队列，也不保证精确时刻触发。

需要按时执行和失败追踪的业务，应采用可恢复的调度与任务状态设计。Redis TTL 可以参与清理和状态表达，但不能单独承担所有业务可靠性。

[返回本册目录](/collections/redis/)
