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

本章 `redis` 代码块是可在 `redis-cli` 交互环境输入的 Redis 命令。以 Redis Open Source 7.2.0 为教学基准。

![成员、分数与查询维度](/assets/notes/redis/redis-study-zset.svg)

## 1. 把排名和分数区间分开

以下采用 Redis Open Source 6.2.0 起支持的统一 ZRANGE 写法：

```redis
# 向 Zset demo:rank 写入分数/成员：user-a→10、user-b→15、user-c→15
# 默认返回新增成员数；只更新已有成员的分数时可能返回 0
ZADD demo:rank 10 user-a 15 user-b 15 user-c
# 读取 Zset demo:rank 的索引范围 0～9，包含两端；索引从 0 开始，-1 表示最后一项
# REV 按逆序返回；WITHSCORES 同时返回每个成员的分数
ZRANGE demo:rank 0 9 REV WITHSCORES
# 读取 Zset demo:rank 分数在 10～20 范围内的成员；BYSCORE 按分数筛选，边界默认包含
# 默认按正序返回；WITHSCORES 同时返回每个成员的分数
ZRANGE demo:rank 10 20 BYSCORE WITHSCORES
# 查询成员 user-a 在 Zset demo:rank 中的升序排名；从 0 开始，成员不存在返回 nil
ZRANK demo:rank user-a
# 查询成员 user-a 在 Zset demo:rank 中的降序排名；从 0 开始，成员不存在返回 nil
ZREVRANK demo:rank user-a
```

ZADD 预期新增 `3` 个成员。两次范围查询按顺序分别得到 `[(user-c,15), (user-b,15), (user-a,10)]`、`[(user-a,10), (user-b,15), (user-c,15)]`；这里用二元组简写“成员、分数”。ZRANK 和 ZREVRANK 对 user-a 分别预期返回 `0`、`2`。

rank（排名索引）从 `0` 开始；score 是业务值，不一定等于名次。三种查询方式的区别如下，BY RANK 是说明用语，命令中不写这个参数：

| 查询方式               | 示例                              | 解决的问题                         |
| ---------------------- | --------------------------------- | ---------------------------------- |
| BY RANK（按索引）      | `ZRANGE demo:rank 0 9`            | 读取升序前 10 个；高分优先时加 REV |
| BY SCORE（按分数）     | `ZRANGE demo:rank 10 20 BYSCORE`  | 读取分数在 10～20 的成员           |
| BY LEX（按字节字典序） | `ZRANGE demo:rank:ties - + BYLEX` | 在下方同分集合中按成员字节顺序查询 |

WITHSCORES 表示同时返回分数。接续本节数据，可以直接比较正反向查询：

```redis
# 读取 Zset demo:rank 的索引范围 0～-1，包含两端；索引从 0 开始，-1 表示最后一项
# 默认按正序返回；WITHSCORES 同时返回每个成员的分数
ZRANGE demo:rank 0 -1 WITHSCORES
# 读取 Zset demo:rank 的索引范围 0～-1，包含两端；索引从 0 开始，-1 表示最后一项
# REV 按逆序返回；WITHSCORES 同时返回每个成员的分数
ZRANGE demo:rank 0 -1 REV WITHSCORES
# 读取 Zset demo:rank 分数在 20～10 范围内的成员；BYSCORE 按分数筛选，边界默认包含
# REV 按逆序返回，分数边界按上界、下界书写；WITHSCORES 同时返回每个成员的分数
ZRANGE demo:rank 20 10 BYSCORE REV WITHSCORES
```

第一条预期按 user-a、user-b、user-c 返回；后两条均按 user-c、user-b、user-a 返回。REV（Reverse，反向）会同时反转分数顺序和同分成员顺序。按排名时仍用 `0 -1` 选择反向序列；按分数且带 REV 时则把范围写成“最大值、最小值”，这里是 `20 10`。[ZRANGE 范围与版本](https://redis.io/docs/latest/commands/zrange/)

同分不代表是同一个成员。同分的成员之间按成员名的字节顺序排，不按插入时间排——下面先写 carol 再写 alice，正序读出来却是 alice 在前。以下每个成员都必须带自己的 score，不能把多个名字直接接在单个 `100` 后面：

```redis
# 向 Zset demo:rank:ties 写入分数/成员：carol→100、bob→100、alice→100
# 默认返回新增成员数；只更新已有成员的分数时可能返回 0
ZADD demo:rank:ties 100 carol 100 bob 100 alice
# 读取 Zset demo:rank:ties 的索引范围 0～-1，包含两端；索引从 0 开始，-1 表示最后一项
# 默认按正序返回；WITHSCORES 同时返回每个成员的分数
ZRANGE demo:rank:ties 0 -1 WITHSCORES
# 读取 Zset demo:rank:ties 的索引范围 0～-1，包含两端；索引从 0 开始，-1 表示最后一项
# REV 按逆序返回；WITHSCORES 同时返回每个成员的分数
ZRANGE demo:rank:ties 0 -1 REV WITHSCORES
# 读取 Zset demo:rank:ties 的字典序范围；BYLEX 按成员字节序筛选，- 和 + 分别表示无下界和无上界，使用 BYLEX 的前提是成员必须同分。
# 默认按正序返回
ZRANGE demo:rank:ties - + BYLEX
```

预期新增 `3` 个成员，正向为 alice、bob、carol，反向为 carol、bob、alice，分数均为 `100`；BYLEX 返回 alice、bob、carol。字节字典序比较的是成员的二进制字节，不是语言学排序。 **BYLEX 需要成员具有相同 score 才能得到预期字典序；不同 score 下回复未规定，不能当作全局字典序查询。**

## 2. 更新条件与计数返回

ZADD 的条件选项把“先判断、再决定写不写”收进同一条命令：客户端不必先读一次、再拼一条写命令，也就没有中间被别的客户端改掉的空隙。例如初始化成员时不覆盖旧值用 NX，只接受更好的成绩用 GT：

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
# 向 Zset demo:rank:update 写入分数/成员：user-a→100
# 默认返回新增成员数；只更新已有成员的分数时可能返回 0
ZADD demo:rank:update 100 user-a
# 向 Zset demo:rank:update 写入分数/成员：user-a→90；GT 表示已有成员仅在新分数更大时更新
# 默认返回新增成员数；只更新已有成员的分数时可能返回 0
ZADD demo:rank:update GT 90 user-a
# 向 Zset demo:rank:update 写入分数/成员：user-a→120；GT 表示已有成员仅在新分数更大时更新
# 默认返回新增成员数；只更新已有成员的分数时可能返回 0
ZADD demo:rank:update GT 120 user-a
# 查询 Zset demo:rank:update 中成员 user-a 的分数；成员不存在返回 nil
ZSCORE demo:rank:update user-a
```

预期依次返回 `1`、`0`、`0`、`"120"`。90 小于原分数，不更新；120 更大，更新成功，但没有新增成员，所以普通计数仍是 `0`。带 CH 时，分数确实改变也计入变化数；相同分数重复写入不计变化。INCR 则返回更新后的分数，条件阻止操作时返回 nil（空值），不能解释成成员计数。

ZINCRBY 可按增量修改分数。score 使用 IEEE 754（IEEE Standard for Floating-Point Arithmetic，浮点算术标准）的 64 位双精度浮点数 double，**不是任意精度整数**。可连续精确表示的整数范围为 `[-2^53, 2^53]`，包含边界；超出后不保证相邻整数仍可区分，不表示范围外每个整数都必定失真。[ZADD 精度说明](https://redis.io/docs/latest/commands/zadd/)

当前常见的 Unix 时间戳（自 1970 年起的时间计数）按秒或毫秒保存通常处于该整数范围内。金额可考虑换算成整数最小货币单位，同时检查范围；不应无限拼接毫秒、用户标识、优先级和业务序号成为巨大 score。边界推演：9007199254740992 即 2^53 可精确表示，但再加 1 不能期待独立精度。

## 3. 分数范围与返回量

范围边界默认把端点算在内（闭区间）；在边界值前面加 `(`，表示不包含这个端点。

下表是官方命令复杂度，N 为集合成员数，M 为本次返回或处理的成员数：

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

## 4. 排行榜之外的用途

把任务的计划执行时刻当分数存进去，就能用 `BYSCORE` 查出“现在该跑的任务”，得到延迟任务的候选集；把优先级当分数，就能按优先级取任务。但查到一个候选任务，不等于拿到了唯一的执行资格——多个消费者会同时查到同一条，还需要原子领取和重试设计。

例如以下是简化时间轴，不是真实 Unix 时间戳或已运行结果：任务 A、B、C 的计划时间分别是 `100`、`120`、`150`，当前时间是 `110`。可在新键上演示：

```redis
# 向 Zset demo:delayed 写入分数/成员：task-a→100、task-b→120、task-c→150
# 默认返回新增成员数；只更新已有成员的分数时可能返回 0
ZADD demo:delayed 100 task-a 120 task-b 150 task-c
# 读取 Zset demo:delayed 分数在 -inf～110 范围内的成员；-inf 表示负无穷，110 为包含在内的上界
# 默认按正序返回
ZRANGE demo:delayed -inf 110 BYSCORE
```

预期新增 `3` 个任务，查询只返回 task-a；`-inf` 表示负无穷。多个 Worker（工作进程，负责执行任务）可能同时查到 task-a。应用还需原子领取、状态更新、超时重试和业务幂等（Idempotency，使重复请求不重复产生业务效果），见 [第 28 章：锁、限流与业务幂等](/articles/redis-locks-rate-limits.html)。

## 5. 聚合与 Cluster 条件

ZUNIONSTORE、ZINTERSTORE 等聚合把几个 Zset 合并或求交集，可以给每个来源乘上权重，再用 SUM/MIN/MAX 决定同一成员的新分数，最后把结果写进目标键——它会写入数据，不是只读查询。参与键和目的键需要满足适用的 Cluster 约束，不能靠“恰好在同一节点”替代同槽判断。

Redis Cluster（Redis 集群）按 Hash Slot（哈希槽）分配键，同一节点可承载多个槽，所以同节点不等于同槽。以下只在启用了 Cluster 的学习节点执行：

```redis
# 计算键 demo:{rank}:day1 所属的槽号；花括号内的 hash tag 用于确定槽，相同 tag 的键会落在同一槽
CLUSTER KEYSLOT demo:{rank}:day1
# 计算键 demo:{rank}:day2 所属的槽号；花括号内的 hash tag 用于确定槽，相同 tag 的键会落在同一槽
CLUSTER KEYSLOT demo:{rank}:day2
# 计算键 demo:{rank}:result 所属的槽号；花括号内的 hash tag 用于确定槽，相同 tag 的键会落在同一槽
CLUSTER KEYSLOT demo:{rank}:result
```

`{rank}` 是 Hash Tag（哈希标签），让目标键和源键按同一内容计算槽。相同标签满足多键同槽要求，但大量键共用标签也可能集中负载，不能解决所有热点。[ZUNIONSTORE](https://redis.io/docs/latest/commands/zunionstore/) · [ZINTERSTORE](https://redis.io/docs/latest/commands/zinterstore/) · [Cluster Hash Tag 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

内部编码（Internal Encoding）决定内存中的表示方式，不改变成员唯一、按分数排序等对外语义。Redis Open Source 7.2.0 的两条主要路径如下：

| 编码                                 | 条件与分工                                          |
| ------------------------------------ | --------------------------------------------------- |
| listpack（紧凑列表）                 | 小集合紧凑排列成员和分数，减少指针及分配开销        |
| skiplist + dictionary（跳表 + 字典） | 较大集合的组合表示；OBJECT ENCODING 显示为 skiplist |

Dictionary 按成员快速查找 score；Skip List 通过多层有序链接跳过部分成员，支持分数范围和排名查询。两者共同维护同一份成员与分数关系，分别服务按成员查找与有序访问。

7.2.0 中，`zset-max-listpack-entries` 默认 `128`，限制紧凑集合成员数；`zset-max-listpack-value` 默认 `64` 字节，限制成员长度。增长超过适用阈值，或不能满足容量安全检查时，会转为 skiplist 与 dictionary；创建时也可能根据预计规模直接选择skiplist+dictionary，所以不能只按当前成员数推断编码。[7.2.0 t_zset.c](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_zset.c) · [7.2.0 redis.conf](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

历史对照：Redis Open Source 6.2.0 的小集合使用 ziplist（压缩列表），7.0.0 改为 listpack；较大集合仍有跳表与字典组合。[6.2.0 源码](https://raw.githubusercontent.com/redis/redis/6.2.0/src/t_zset.c) · [7.0.0 源码](https://raw.githubusercontent.com/redis/redis/7.0.0/src/t_zset.c)

## 6. 将成员、精度与槽关系落实到接口 {#_6-读这个结构时的检查清单}

应明确唯一成员是什么、同分如何处理、score 是否会丢失精度、单次读取多少、是否需要原子领取，以及所有参与键的槽关系。把这些约束写进接口约定，比只记住“排行榜用 Zset”更能避免错误。

[返回本册目录](/collections/redis/)
