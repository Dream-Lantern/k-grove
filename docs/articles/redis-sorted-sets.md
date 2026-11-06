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

排行榜既要按用户找分数，也要按分数找名次。Sorted Set（有序集合，常写作 Zset）同时维护唯一 member（成员）与 score（分数），解决这两种查询需求。成员不能重复，分数可以相同；同一个成员更新分数不会变成另一名成员。与普通集合的区别见 [第 6 章：Set](/articles/redis-sets.html)。

本章 `redis` 代码块是可在 `redis-cli` 交互环境输入的 Redis 命令。所有示例和预期结果均未实测；假定不同示例使用的新键起初不存在，无并发修改。同一节标明“接续”的命令沿用前面的数据。以 Redis Open Source 7.2.0 为教学基准，新增参数另标最低版本。

![成员、分数与查询维度](/assets/notes/redis/redis-study-zset.svg)

## 1. 把排名和分数区间分开

以下采用 Redis Open Source 6.2.0 起支持的统一 ZRANGE 写法，未执行：

```redis
ZADD demo:rank 10 user-a 15 user-b 15 user-c
ZRANGE demo:rank 0 9 REV WITHSCORES
ZRANGE demo:rank 10 20 BYSCORE WITHSCORES
ZRANK demo:rank user-a
ZREVRANK demo:rank user-a
```

ZADD 预期新增 `3` 个成员。两次范围查询按顺序分别得到 `[(user-c,15), (user-b,15), (user-a,10)]`、`[(user-a,10), (user-b,15), (user-c,15)]`；这里用二元组简写“成员、分数”，不是逐字的客户端输出。ZRANK 和 ZREVRANK 对 user-a 分别预期返回 `0`、`2`。

rank（排名索引）从 `0` 开始；score 是业务值，不一定等于名次。三种查询方式的区别如下，BY RANK 是说明用语，命令中不写这个参数：

| 查询方式               | 示例                              | 解决的问题                         |
| ---------------------- | --------------------------------- | ---------------------------------- |
| BY RANK（按索引）      | `ZRANGE demo:rank 0 9`            | 读取升序前 10 个；高分优先时加 REV |
| BY SCORE（按分数）     | `ZRANGE demo:rank 10 20 BYSCORE`  | 读取分数在 10～20 的成员           |
| BY LEX（按字节字典序） | `ZRANGE demo:rank:ties - + BYLEX` | 在下方同分集合中按成员字节顺序查询 |

WITHSCORES 表示同时返回分数。接续本节数据，可以直接比较正反向查询：

```redis
ZRANGE demo:rank 0 -1 WITHSCORES
ZRANGE demo:rank 0 -1 REV WITHSCORES
ZRANGE demo:rank 20 10 BYSCORE REV WITHSCORES
```

第一条预期按 user-a、user-b、user-c 返回；后两条均按 user-c、user-b、user-a 返回。REV（Reverse，反向）会同时反转分数顺序和同分成员顺序。按排名时仍用 `0 -1` 选择反向序列；按分数且带 REV 时则把范围写成“最大值、最小值”，这里是 `20 10`。[ZRANGE 范围与版本](https://redis.io/docs/latest/commands/zrange/)

同分不等于成员相同，也不按插入时间排序。以下每个成员都必须带一个 score，不能把多个名字直接接在单个 `100` 后面：

```redis
ZADD demo:rank:ties 100 carol 100 bob 100 alice
ZRANGE demo:rank:ties 0 -1 WITHSCORES
ZRANGE demo:rank:ties 0 -1 REV WITHSCORES
ZRANGE demo:rank:ties - + BYLEX
```

预期新增 `3` 个成员，正向为 alice、bob、carol，反向为 carol、bob、alice，分数均为 `100`；BYLEX 返回 alice、bob、carol。字节字典序比较的是成员的二进制字节，不是语言学排序。**BYLEX 需要成员具有相同 score 才能得到预期字典序；不同 score 下回复未规定，不能当作全局字典序查询。**Redis 不记录谁先达到该分数；业务若要求先到先排，需额外设计模型。

## 2. 更新条件与计数返回

ZADD 的条件选项可以在单条命令内判断是否更新，减少“客户端先读再写”的竞争窗口。例如初始化成员时不覆盖旧值、只接受更好成绩，分别适合 NX、GT：

| 参数 | 含义及用途                                         |
| ---- | -------------------------------------------------- |
| NX   | 仅添加不存在的成员，保护已有成绩                   |
| XX   | 仅更新已有成员，避免误创建成员                     |
| GT   | 对已有成员，仅当新分数更大才更新，适合保留最高成绩 |
| LT   | 对已有成员，仅当新分数更小才更新，适合保留最短耗时 |
| CH   | 非 INCR 模式下，返回新增及分数改变的成员数量       |
| INCR | 把 score 当作增量，只能指定一个 score-member 对    |

GT、LT 不阻止新增成员；只允许更新已有成员时可与 XX 组合。NX 与 XX 互斥，GT 与 LT 互斥，NX 也不能与 GT/LT 组合。Redis Open Source 3.0.2 增加 NX、XX、CH、INCR，6.2.0 增加 GT、LT，不能向更旧实例直接发送新参数。[ZADD 参数与版本历史](https://redis.io/docs/latest/commands/zadd/)

下面使用新学习键，演示“只更新更高分”：

```redis
ZADD demo:rank:update 100 user-a
ZADD demo:rank:update GT 90 user-a
ZADD demo:rank:update GT 120 user-a
ZSCORE demo:rank:update user-a
```

预期依次返回 `1`、`0`、`0`、`"120"`。90 小于原分数，不更新；120 更大，更新成功，但没有新增成员，所以普通计数仍是 `0`。带 CH 时，分数确实改变也计入变化数；相同分数重复写入不计变化。INCR 则返回更新后的分数，条件阻止操作时返回 nil（空值），不能解释成成员计数。

ZINCRBY 可按增量修改分数。score 使用 IEEE 754（IEEE Standard for Floating-Point Arithmetic，浮点算术标准）的 64 位双精度浮点数 double，**不是任意精度整数**。可连续精确表示的整数范围为 `[-2^53, 2^53]`，包含边界；超出后不保证相邻整数仍可区分，不表示范围外每个整数都必定失真。[ZADD 精度说明](https://redis.io/docs/latest/commands/zadd/)

当前常见的 Unix 时间戳（自 1970 年起的时间计数）按秒或毫秒保存通常处于该整数范围内。金额可考虑换算成整数最小货币单位，同时检查范围；不应无限拼接毫秒、用户标识、优先级和业务序号成为巨大 score。边界推演：9007199254740992 即 2^53 可精确表示，但再加 1 不能期待独立精度。

## 3. 分数范围与返回量

范围边界通常有闭区间与 `(` 前缀表示的开区间规则，不把数学表达式中的方括号直接当成任意命令参数。

下表是官方命令复杂度，表示工作量随规模增长的趋势，不是固定耗时。N 为集合成员数，M 为本次返回或处理的成员数：

| 命令          | 复杂度                                    |
| ------------- | ----------------------------------------- |
| ZADD          | 每个成员 O(log N)                         |
| ZSCORE        | O(1)                                      |
| ZRANK         | O(log N)                                  |
| ZRANGE        | O(log N + M)                              |
| ZRANGEBYSCORE | O(log N + M)                              |
| ZREM          | 每个成员 O(log N)，处理 M 个为 O(M log N) |

[ZADD](https://redis.io/docs/latest/commands/zadd/) · [ZSCORE](https://redis.io/docs/latest/commands/zscore/) · [ZRANK](https://redis.io/docs/latest/commands/zrank/) · [ZRANGE](https://redis.io/docs/latest/commands/zrange/) · [ZRANGEBYSCORE](https://redis.io/docs/latest/commands/zrangebyscore/) · [ZREM](https://redis.io/docs/latest/commands/zrem/)

ZRANGE 的 LIMIT 用于 BYSCORE/BYLEX 范围，不能用于默认的索引查询。很大的 offset（跳过的成员数）仍需遍历前面的成员，可能产生 O(N) 级成本；LIMIT 不会把任意深度分页变成常数时间。大返回量及全量 WITHSCORES 还会消耗处理器、内存与网络资源。

历史 ZRANGEBYSCORE、ZREVRANGE 等命令按各自参数解释；本章以注明版本的统一 ZRANGE 为教学入口，范围、顺序和分数选项分别查阅。

## 4. 排行榜之外的用途

按时间戳排序可表达延迟任务候选集；按权重可形成优先级索引。但读取到一个候选任务，不等于取得唯一执行资格；多个消费者还需要原子领取与重试设计。

例如以下是简化时间轴，不是真实 Unix 时间戳或已运行结果：任务 A、B、C 的计划时间分别是 `100`、`120`、`150`，当前时间是 `110`。可在新键上演示：

```redis
ZADD demo:delayed 100 task-a 120 task-b 150 task-c
ZRANGE demo:delayed -inf 110 BYSCORE
```

预期新增 `3` 个任务，查询只返回 task-a；`-inf` 表示负无穷。多个 Worker（工作进程，负责执行任务）仍可能同时查到 task-a，查询没有领取或删除它。应用还需原子领取、状态更新、超时重试和业务幂等（Idempotency，使重复请求不重复产生业务效果），见 [第 28 章：锁、限流与业务幂等](/articles/redis-locks-rate-limits.html)。

用 score 表示到期时间，也不会让 Redis 自动在该时刻准确触发任务。轮询延迟、时钟与实例故障均需处理。

## 5. 聚合与 Cluster 条件

ZUNIONSTORE、ZINTERSTORE 等聚合可结合权重与 SUM/MIN/MAX 处理分数，结果写入目标键，属于变更操作。参与键和目的键需要满足适用的 Cluster 约束，不能靠“恰好在同一节点”替代同槽判断。

Redis Cluster（Redis 集群）按 Hash Slot（哈希槽）分配键，同一节点可承载多个槽，所以同节点不等于同槽。以下只在启用了 Cluster 的学习节点执行，无需先创建这些键；预期三个槽编号相同，本次未实测：

```redis
CLUSTER KEYSLOT demo:{rank}:day1
CLUSTER KEYSLOT demo:{rank}:day2
CLUSTER KEYSLOT demo:{rank}:result
```

`{rank}` 是 Hash Tag（哈希标签），让目标键和源键按同一内容计算槽。相同标签满足多键同槽要求，但大量键共用标签也可能集中负载，不能解决所有热点。[ZUNIONSTORE](https://redis.io/docs/latest/commands/zunionstore/) · [ZINTERSTORE](https://redis.io/docs/latest/commands/zinterstore/) · [Cluster Hash Tag 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

内部编码（Internal Encoding）决定内存中的表示方式，不改变成员唯一、按分数排序等对外语义。Redis Open Source 7.2.0 的两条主要路径如下：

| 编码                                 | 条件与分工                                          |
| ------------------------------------ | --------------------------------------------------- |
| listpack（紧凑列表）                 | 小集合紧凑排列成员和分数，减少指针及分配开销        |
| skiplist + dictionary（跳表 + 字典） | 较大集合的组合表示；OBJECT ENCODING 显示为 skiplist |

Dictionary 按成员快速查找 score；Skip List 通过多层有序链接跳过部分成员，支持分数范围和排名查询。两者共同维护同一份成员与分数关系，分别服务按成员查找与有序访问。

7.2.0 中，`zset-max-listpack-entries` 默认 `128`，限制紧凑集合成员数；`zset-max-listpack-value` 默认 `64` 字节，限制成员长度。增长超过适用阈值，或不能满足容量安全检查时，会转为 skiplist 与 dictionary；创建时也可能根据预计规模直接选择后者，不能只按当前成员数推断编码。[7.2.0 t_zset.c](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_zset.c) · [7.2.0 redis.conf](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

历史对照：Redis Open Source 6.2.0 的小集合使用 ziplist（压缩列表），7.0.0 改为 listpack；较大集合仍有跳表与字典组合。这里只比较固定版本，不外推所有早期实现，更不把编码名称当作 Redis 对外命令接口的行为差异。[6.2.0 源码](https://raw.githubusercontent.com/redis/redis/6.2.0/src/t_zset.c) · [7.0.0 源码](https://raw.githubusercontent.com/redis/redis/7.0.0/src/t_zset.c)

## 6. 将成员、精度与槽关系落实到接口 {#_6-读这个结构时的检查清单}

应明确唯一成员是什么、同分如何处理、score 是否会丢失精度、单次读取多少、是否需要原子领取，以及所有参与键的槽关系。把这些约束写进接口约定，比只记住“排行榜用 Zset”更能避免错误。

[返回本册目录](/collections/redis/)
