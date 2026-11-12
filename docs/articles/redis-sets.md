---
id: redis-sets
title: 第六章 Set、成员关系与集合运算
description: "Set 保存不重复的成员，不提供插入顺序或按下标读取。它适合表达“某人是否属于这一组”，而不是需要稳定排名的列表。"
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
order: 6
---

# 第六章 Set、成员关系与集合运算

Set（集合）保存不重复的成员，不提供插入顺序或按下标读取。它适合表达“某人是否属于这一组”，而不是需要稳定排名的列表。需要按分数排序时，见 [第 7 章：Sorted Set（有序集合）](/articles/redis-sorted-sets.html)。

本章 `redis` 代码块是 Redis 命令，可在 `redis-cli` 交互环境输入。除特别说明外，以 Redis Open Source 7.2.0 为参照，假定各示例键起初不存在、没有并发修改。Cluster 和 Bloom 示例有额外环境要求。

## 1. 分别查询键、成员与集合数量 {#_1-键存在与成员存在}

新增例子：

```redis
SADD demo:tags:user-42 sports music
SISMEMBER demo:tags:user-42 sports
SCARD demo:tags:user-42
SREM demo:tags:user-42 music
```

预期依次返回 `2`、`1`、`2`、`1`。EXISTS 检查键是否存在，SISMEMBER 检查成员，不能互相替代。SADD 返回新加入的成员数；重复添加同一成员不增加集合基数（Cardinality，即不重复成员的数量）。

`SCARD` 可以读取已有的数量信息，不需要为了数成员而先 SMEMBERS。读取全部成员的回复量则随集合大小增长。

## 2. 并集、交集与差集

把用户兴趣、已完成任务或参与人群表示为集合后，可以计算共同成员与覆盖范围：

```redis
SADD demo:{audience}:a user-1 user-2
SADD demo:{audience}:b user-2 user-3
SINTER demo:{audience}:a demo:{audience}:b
SUNION demo:{audience}:a demo:{audience}:b
SDIFF demo:{audience}:a demo:{audience}:b
```

两个 SADD 预期各返回 `2`；交集成员为 `{user-2}`，并集为 `{user-1, user-2, user-3}`，差集为 `{user-1}`。这里花括号表示结果集合，实际返回的成员顺序不保证。差集有方向，A 减 B 与 B 减 A 不同。STORE 版本把结果写入目标键，可能覆盖已有数据，还会消耗内存；不能把它当成纯查询。

在 Redis Cluster（Redis 集群）中，上述多键运算要求键位于同一个 Hash Slot（哈希槽，即键所在的分片单元）。Hash Tag（哈希标签）让这些键按花括号中的 `audience` 计算槽；下面需连接启用了 Cluster 的学习节点，单实例不能直接运行，且无需先创建键：

```redis
CLUSTER KEYSLOT demo:{audience}:a
CLUSTER KEYSLOT demo:{audience}:b
```

预期返回两个相同的槽编号。相同标签解决同槽约束，不解决所有热点问题；大量集合共用同一标签会使负载集中到一个槽及其节点。[CLUSTER KEYSLOT](https://redis.io/docs/latest/commands/cluster-keyslot/) · [Cluster Hash Tag 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

## 3. 随机返回与随机删除

SRANDMEMBER 用于随机返回，SPOP 用于随机移除。前者不会因为读取而删除成员，后者会改变集合。

| 命令                 | 是否删除 | 是否允许重复 | 结果数量                              |
| -------------------- | -------- | ------------ | ------------------------------------- |
| `SRANDMEMBER key`    | 否       | 不适用       | 单个成员；空集合为 nil                |
| `SRANDMEMBER key 3`  | 否       | 否           | 数组中最多 3 个成员                   |
| `SRANDMEMBER key -3` | 否       | 是           | 非空集合返回 3 个位置，空集合为空数组 |
| `SPOP key`           | 是       | 否           | 单个成员；空集合为 nil                |
| `SPOP key 3`         | 是       | 否           | 数组中最多 3 个成员                   |

表中的 key 是语法占位，不是要操作的真实键。SRANDMEMBER 正数 count 不重复，但不保证返回数组是随机排序；负数 count 允许重复，非空集合返回其绝对值指定的数量。SPOP 会实际删除成员，返回数量不超过现有成员数。[SRANDMEMBER 随机规则](https://redis.io/docs/latest/commands/srandmember/) · [SPOP](https://redis.io/docs/latest/commands/spop/)

教学推演：集合只有 a、b，count=3 最多返回这两个不同成员；count=-3 可以返回三个位置，其中必有重复，具体顺序不能预先确定。随机返回机制本身并不能证明商业抽奖公平，重复参与、随机来源和审计仍需在业务层考虑。

## 4. 精确集合的成本

Set 能回答精确成员关系，也能列出成员；这些能力需要相应存储。若只需要近似统计不重复元素数量且不需要名单，见 [第 9 章：HyperLogLog](/articles/redis-hyperloglog.html)，它不能替代精确成员查询。

Bloom Filter（布隆过滤器）是一种概率型数据结构，用较少空间快速判断元素是否可能出现过。它通过若干哈希函数把元素映射到位数组，不保存完整成员列表；查询发现某个必要位未设置就可排除，但不同元素可能共享这些位，所以“全部位已设置”不证明元素真的加入过。

| 查询结果    | 正常使用时的含义                                                      |
| ----------- | --------------------------------------------------------------------- |
| 不存在（0） | 确定未加入当前过滤器，不会漏掉已成功加入且仍被保留的元素              |
| 存在（1）   | 可能存在，也可能是 False Positive（假阳性，即未加入却被判为可能存在） |

正常使用条件下没有 False Negative（假阴性，即已加入却被判不存在）；这里假定加入成功、过滤器完整，且没有因重建、数据丢失等遗漏已加入元素。它适合在查数据库前排除明显不存在的对象，不适合代替 Set 的精确成员判断；“可能存在”仍应回查权威数据。[官方 Bloom Filter 说明](https://redis.io/docs/latest/develop/data-types/probabilistic/bloom-filter/)

`BF.*` 属于 RedisBloom 提供的概率结构能力，不是核心 Set 命令。在 Redis Open Source 7.2.0 / 7.4.0 普通实例上，需要另行安装兼容的 RedisBloom 模块，并通过服务端启动配置 `loadmodule` 加载实际模块文件，或使用包含该模块的 Redis Stack；安装客户端库不会补上命令。Redis Open Source 8.0.0 已将 RedisBloom 纳入发行包，二进制分发与自行构建、加载配置仍需分别确认，不能说所有实例都要另装模块或一定已启用。[RedisBloom 项目与版本边界](https://github.com/RedisBloom/RedisBloom#readme) · [8.0.0 Release Notes](https://raw.githubusercontent.com/redis/redis/8.0.0/00-RELEASENOTES)

以下以使用 `redis-full.conf` 加载完整概率结构能力的 Redis Open Source 8.0.0 学习实例为目标，假定 `demo:bloom` 不存在；这是教学语法与推演。`0.001` 表示期望假阳性率 0.1%，`100000` 是初始容量规划，不保证每批查询恰好有 0.1% 误判：

```redis
BF.RESERVE demo:bloom 0.001 100000
BF.ADD demo:bloom user-42
BF.EXISTS demo:bloom user-42
BF.EXISTS demo:bloom user-99
```

预期前两条返回 `OK`、`1`，已成功加入的 user-42 查询返回 `1`；未加入的 user-99 通常返回 `0`，也可能因假阳性返回 `1`。不能把最后一条写成必然为 `0` 的测试结论。具体部署版本与扩展边界见 [第 33 章](/articles/redis-extensions.html)。[BF.RESERVE](https://redis.io/docs/latest/commands/bf.reserve/) · [BF.ADD](https://redis.io/docs/latest/commands/bf.add/) · [BF.EXISTS](https://redis.io/docs/latest/commands/bf.exists/)

SSCAN 使用 cursor（游标，服务器返回的继续遍历标记）分批扫描。以下先在全新命名空间初始化集合，预期 SADD 返回 `3`；第一次 SSCAN 从游标 `0` 开始：

```redis
SADD demo:users user-1 user-2 user-3
SSCAN demo:users 0 COUNT 100
```

每次扫描返回“下次游标 + 本批成员”。之后必须传入上次返回的游标，只有返回游标为 `0` 才结束。下面用 `123`、`456` 表示中间游标，执行时替换为上次返回的实际值；小集合第一次就可能结束，无需继续：

```text
SSCAN demo:users 123 COUNT 100
SSCAN demo:users 456 COUNT 100
```

COUNT 是工作量提示，不是严格分页大小；一次可能返回空集合而游标仍不为 `0`。完整遍历可能出现重复成员，数据变化时不保证快照一致性，应用需去重并定义如何处理变化。SSCAN 不是 OFFSET/LIMIT（按偏移与条数取页）式稳定快照分页。[SSCAN](https://redis.io/docs/latest/commands/sscan/) · [官方 SCAN 遍历保证](https://raw.githubusercontent.com/redis/redis-doc/master/commands/scan.md)

时间复杂度描述工作量怎样随规模增长，不是固定耗时。下表中 N 一般表示集合成员数，M 表示参与交集的集合数量，T 表示所有输入集合的元素总数（含输入间重复）：

| 命令      | 作用         | 官方复杂度特点                             |
| --------- | ------------ | ------------------------------------------ |
| SISMEMBER | 精确成员判断 | O(1)                                       |
| SADD      | 添加成员     | 每个成员平均 O(1)，添加 K 个为 O(K)        |
| SCARD     | 获取基数     | O(1)                                       |
| SMEMBERS  | 返回所有成员 | O(N)                                       |
| SINTER    | 交集         | 最坏 O(N×M)，此行 N 特指最小输入集合的基数 |
| SUNION    | 并集         | O(T)                                       |
| SSCAN     | 游标遍历     | 固定 COUNT 下单次 O(1)，完整遍历 O(N)      |

K 是本次添加的成员数。SSCAN 的单次复杂度并不意味着任意调大 COUNT 也成本固定，紧凑编码还可能一次返回全部成员。SINTER 即使结果很小，也可能要比较大量成员；并交差运算和大回复都要按输入规模评估。[SISMEMBER](https://redis.io/docs/latest/commands/sismember/) · [SADD](https://redis.io/docs/latest/commands/sadd/) · [SCARD](https://redis.io/docs/latest/commands/scard/) · [SMEMBERS](https://redis.io/docs/latest/commands/smembers/) · [SINTER](https://redis.io/docs/latest/commands/sinter/) · [SUNION](https://redis.io/docs/latest/commands/sunion/)

## 5. 类型与编码分开

内部编码（Internal Encoding）是 Redis 在内存中保存 Set 的方式。以 Redis Open Source 7.2.0 为准：

| 编码                            | 使用场景                                               |
| ------------------------------- | ------------------------------------------------------ |
| intset（Integer Set，整数集合） | 成员可表示为有符号 64 位整数、数量满足条件的小集合     |
| listpack（紧凑列表）            | 满足数量、成员大小及容量安全条件的小集合，可包含非整数 |
| hashtable（哈希表）             | 超出紧凑表示条件或按预估规模创建的常规表示             |

| 配置                       | 7.2.0 默认值 | 作用                                  |
| -------------------------- | -----------: | ------------------------------------- |
| `set-max-intset-entries`   |          512 | intset 成员数阈值                     |
| `set-max-listpack-entries` |          128 | listpack 成员数阈值                   |
| `set-max-listpack-value`   |           64 | listpack 单个成员长度阈值，单位为字节 |

7.2.0 的创建路径会结合首个成员和预计添加数量选择编码；不能仅凭“这是整数”判断最终必为 intset。向 intset 增加整数并超过数量阈值时会转成 hashtable；增加非整数时，若当前数量、已有成员表示长度、新成员长度和容量安全检查都允许，可转成 listpack，否则转成 hashtable。listpack 增长超出数量或长度等条件也会转成 hashtable。阈值只是条件的一部分，不应把它当成任意命令后都强制满足的编码承诺。[7.2.0 t_set.c](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_set.c) · [redis.conf](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf) · [config.c 默认值](https://raw.githubusercontent.com/redis/redis/7.2.0/src/config.c)

intset 内部还可用 int16、int32、int64（分别为 16、32、64 位有符号整数）保存成员。加入超出当前宽度范围的整数，会扩大整个 intset 的整数宽度；这与对象编码转换不同：

| 变化                | 示例与含义                                                           |
| ------------------- | -------------------------------------------------------------------- |
| intset 内部宽度升级 | 原先只存 `1`，再加入 `32768`，可由 int16 升为 int32，对象仍是 intset |
| 对象编码转换        | 加入非整数或增长超出条件，intset 可转为 listpack 或 hashtable        |

这是按 7.2.0 源码推演的例子。intset 内部有序，也不意味着应用可以按下标或排序读取 Set。转换和回退需按具体命令、版本判断，不能概括为“所有类型永不回退”。[7.2.0 intset.c](https://raw.githubusercontent.com/redis/redis/7.2.0/src/intset.c)

优化前先看实际版本与 OBJECT ENCODING，再比较典型负载，而不是只根据教科书里的一个阈值重组全部数据。基础成员语义见 [Set 数据类型](https://redis.io/docs/latest/develop/data-types/sets/)。

[返回本册目录](/collections/redis/)
