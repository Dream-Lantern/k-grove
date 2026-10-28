---
id: redis-sorted-sets
title: 第七章 Sorted Set、排名与分数范围
description: "Sorted Set（有序集合，常写作 Zset）同时维护唯一成员与 score。成员不能重复，score 可以相同；同一个成员更新分数不会变成另一名成员。"
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
order: 7
---

# 第七章 Sorted Set、排名与分数范围

Sorted Set（有序集合，常写作 Zset）同时维护唯一成员与 score。成员不能重复，score 可以相同；同一个成员更新分数不会变成另一名成员。

![成员、分数与查询维度](/assets/notes/redis/redis-study-zset.svg)

## 1. 把排名和分数区间分开

新增例子，采用 Redis 6.2+ 的统一 ZRANGE 写法，未执行：

```redis
ZADD demo:rank 10 user-a 15 user-b 15 user-c
ZRANGE demo:rank 0 9 REV WITHSCORES
ZRANGE demo:rank 10 20 BYSCORE WITHSCORES
ZRANK demo:rank user-a
ZREVRANK demo:rank user-a
```

前一个范围按 rank 位置选择，后一个按 score 选择。rank 从 0 开始；score 是业务值，不一定等于名次。反向排名命令为 ZREVRANK，返回分数的选项为 WITHSCORES。[ZRANGE 的范围与版本](https://redis.io/docs/latest/commands/zrange/)

同分成员有相应的字节字典序规则，不能把插入时间当成通用同分裁决。若业务要求“先达到分数的排前面”，需要明确建模与精度约束，而不是默认平台替你保存这个规则。

## 2. 更新条件与计数返回

ZADD 的 NX、XX 用于限制成员新增或已存在时的写入，CH 会改变返回计数的含义，INCR 则改为增分语义。解释返回结果时，不能不区分这些选项，一律套用普通 ZADD 的规则。

ZINCRBY 可按增量修改分数。score 使用 64 位 double，可连续精确表示的整数范围为 `[-2^53, 2^53]`，含边界。超过该范围不保证相邻整数仍可区分，不表示范围外每个整数都必定失真。金额、时间戳和拼接排序字段应分别评估，不用一个巨大分数塞入所有条件。[ZADD 精度与排序](https://redis.io/docs/latest/commands/zadd/)

同分成员正向按二进制字典序比较，反向查询也反转该顺序，不按插入先后裁决。新增边界练习：9007199254740992 即 2^53 可精确表示，而再加 1 不能期待保持独立精度；这不是推荐用极大分数编码业务序号。

## 3. 分数范围与返回量

范围边界通常有闭区间与 `(` 前缀表示的开区间规则，不把数学表达式中的方括号直接当成任意命令参数。

ZRANGE 返回大量成员时，即使定位操作的复杂度合适，返回 M 个成员的成本仍然存在。极深分页、很大的 LIMIT 或全量 WITHSCORES 都可能增加 CPU、内存与带宽压力。

历史 ZRANGEBYSCORE、ZREVRANGE 等命令按各自参数解释；本章以注明版本的统一 ZRANGE 为教学入口，范围、顺序和分数选项分别查阅。

## 4. 排行榜之外的用途

按时间戳排序可表达延迟任务候选集；按权重可形成优先级索引。但读取到一个候选任务，不等于取得唯一执行资格；多个消费者还需要原子领取与重试设计。

用 score 表示到期时间，也不会让 Redis 自动在该时刻准确触发任务。轮询延迟、时钟与实例故障均需处理。

## 5. 聚合与 Cluster 条件

ZUNIONSTORE、ZINTERSTORE 等聚合可结合权重与 SUM/MIN/MAX 处理分数，结果写入目标键，属于变更操作。参与键和目的键需要满足适用的 Cluster 约束，不能靠“恰好在同一节点”替代同槽判断。

容量分析应同时看成员数、成员长度、读写模式与内部编码。旧版 ziplist、较新的 listpack/skiplist 路线，以及更后续紧凑结构属于版本实现，API 含义不随编码名称改变。

## 6. 将成员、精度与槽关系落实到接口 {#_6-读这个结构时的检查清单}

应明确唯一成员是什么、同分如何处理、score 是否会丢失精度、单次读取多少、是否需要原子领取，以及所有参与键的槽关系。把这些约束写进接口约定，比只记住“排行榜用 Zset”更能避免错误。

[返回本册目录](/collections/redis/)
