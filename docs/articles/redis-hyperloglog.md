---
id: redis-hyperloglog
title: 第九章 HyperLogLog 与基数估算
description: "HyperLogLog（HLL）估计去重后的基数，例如一天约有多少独立访客。它适合只要数量、不需要成员列表且能接受统计误差的场景。"
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
order: 9
---

# 第九章 HyperLogLog 与基数估算

网站每天约有多少独立访客？如果只要数量趋势，不需要用户名单，可以考虑 HyperLogLog（HLL，基数估算概率数据结构）。它用固定规模的统计信息近似估算 Cardinality（基数，即不重复元素数量），以统计误差换取较少内存，不保存可精确查询的成员集合。

本章 `redis` 代码块是可在 `redis-cli` 交互环境输入的 Redis 命令，假定示例新键起初不存在且无并发修改。以下按 Redis Open Source 7.2.0 解释实现，HLL 命令自 Redis Open Source 2.8.9 起提供。

## 1. 先区分数量与成员查询

用同一个“每日独立访客”问题比较三种工具，更容易看清使用前提：

| 维度           | Set（集合）          | Bitmap（位图）                       | HyperLogLog                                    |
| -------------- | -------------------- | ------------------------------------ | ---------------------------------------------- |
| 成员判断       | 精确                 | 有稳定映射时可精确读取对应位         | 不支持                                         |
| 成员列表       | 支持                 | 需扫描置位位置并反查映射             | 不支持                                         |
| 不重复元素数量 | 精确                 | 一人一位、映射无冲突且范围完整时精确 | 近似                                           |
| 内存           | 随成员数量与长度增长 | 取决于最大 offset（位偏移）          | 固定规模统计状态为主，实际占用依表示与开销而变 |
| 删除单个成员   | 支持                 | 清零对应位                           | 不支持                                         |
| 典型用途       | 精确成员集合         | 紧凑布尔状态                         | 大规模 UV 估算                                 |

UV（Unique Visitors，独立访客数）必须先定义“同一个访客”的身份。Set 保存用户标识，支持精确统计和名单，但内存随成员增长；Bitmap 要求标识能稳定、无冲突地映射到紧凑有界的位置；HLL 适合不需要名单、允许数量近似的统计。不能脱离这些前提只比较谁更省内存，见 [第 6 章：Set](/articles/redis-sets.html) 和 [第 8 章：Bitmap](/articles/redis-bitmaps.html)。

HLL 不保存一份可重新取出的完整用户名单。因此不能用它判断“订单 42 是否处理过”，也不能从统计结果恢复所有原始事件。

其核心思路是把每个输入变成稳定、近似均匀分布的哈希值，再保留少量统计信息：

```text
原始标识 → Hash（哈希）计算 → 二进制序列
         → 用部分比特选择 Register（寄存器，保存局部统计量）
         → 用剩余比特的连续零特征更新寄存器
         → 综合多个寄存器 → 估算不重复元素数量
```

相同字节输入通过相同哈希算法得到相同结果，所以会命中同一寄存器并提出同一统计值；重复输入不会不断增加寄存器。随机序列中连续出现很多个零较少见：例如从约定方向看，开头连续三个零的概率约为八分之一。观察的不同输入越多，看到较长零串的机会越大，零串长度因此提供数量线索。

只依赖一条最长零串容易受偶然极端值影响。多个寄存器把输入分组，各自保留观察到的最大零串统计值，再综合估计，降低波动；哈希映射和样本本身仍有随机性，所以结果存在统计误差，不能当成精确计数。[HLL 原始论文](https://algo.inria.fr/flajolet/Publications/FlFuGaMe07.pdf)

“前导零”常用于解释原理；Redis Open Source 7.2.0 的具体实现是用哈希低 14 位选择寄存器，再从剩余部分的低位端数连续零，记录“零的数量加 1”。这里的方向是实现约定，不应把概念图当作逐位源码布局。[7.2.0 hllPatLen 与寄存器更新](https://raw.githubusercontent.com/redis/redis/7.2.0/src/hyperloglog.c)

## 2. 基本用法与返回

新增示例：

```redis
PFADD demo:uv:day-1 user-a user-b user-a
PFCOUNT demo:uv:day-1
PFADD demo:uv:day-2 user-b user-c
PFMERGE demo:uv:combined demo:uv:day-1 demo:uv:day-2
PFCOUNT demo:uv:combined
```

两个 PFADD 对新键预期都返回 `1`，PFMERGE 返回 `OK`。day-1 的业务精确基数是 2，两天并集是 3；PFCOUNT 返回相应估计值，而不是承诺每次都精确返回 2、3。

| PFADD 返回 | 含义                                                                 |
| ---------- | -------------------------------------------------------------------- |
| 1          | 对已有 HLL 输入元素时，至少一个内部寄存器变化；创建新 HLL 时也返回 1 |
| 0          | 没有寄存器变化，也没有新建结构                                       |

7.2.0 允许不带元素执行 PFADD：新建空结构仍返回 `1`，不能把它解释为“增加了一个用户”。即使带元素，返回 `1` 也不是精确新增人数，返回 `0` 也不证明输入一定是重复事件——新元素可能没有提高任何寄存器的统计值。不能用 PFADD 返回值或两次 PFCOUNT 的差值计算精确新增 UV。[PFADD 定义](https://redis.io/docs/latest/commands/pfadd/) · [7.2.0 pfaddCommand](https://raw.githubusercontent.com/redis/redis/7.2.0/src/hyperloglog.c)

合并统计结构可以估计去重并集。两天各自 UV 直接相加则没有去掉跨天重复；两个 HLL 数字相减也不提供通用精确差集。[PFCOUNT](https://redis.io/docs/latest/commands/pfcount/)

还要注意旧目标是否已经含有统计状态。下面用另一组新键，先给目标写入 old-user，再合并两天的数据：

```redis
PFADD demo:uv:period old-user
PFADD demo:uv:day1 user-a user-b
PFADD demo:uv:day2 user-b user-c
PFMERGE demo:uv:period demo:uv:day1 demo:uv:day2
PFCOUNT demo:uv:period
```

三次 PFADD 预期返回 `1`，合并返回 `OK`。原 period 中的 old-user **也参与合并**，业务精确并集为 old-user、user-a、user-b、user-c 四人，最后返回的是该并集的估计数量。源码会逐寄存器取参与结构的最大统计值，而不是把 PFCOUNT 数字相加。

目标不存在时，PFMERGE 创建新 HLL；目标已存在时，先把目标也作为源参与，再将合并状态写回目标，不是无条件从空状态重建。若要完全重算，可选全新的目标键；确需删除旧目标时，必须先确认其数据不再需要，且它不是本次需要保留的源，再在无并发写入的受控流程中处理，不能随手先删再合并。[PFMERGE 目标语义](https://redis.io/docs/latest/commands/pfmerge/) · [7.2.0 pfmergeCommand](https://raw.githubusercontent.com/redis/redis/7.2.0/src/hyperloglog.c)

| 命令         | 官方复杂度特点                           |
| ------------ | ---------------------------------------- |
| PFADD        | 每个输入元素 O(1)，一批 K 个元素为 O(K)  |
| PFCOUNT 单键 | O(1)，平均常数很小，可复用缓存的估计值   |
| PFCOUNT 多键 | O(N)，合并 N 个 HLL 后估计，常数明显更大 |
| PFMERGE      | O(N)，合并 N 个 HLL，常数较大            |

N 是参与的 HLL 数量，K 是本次输入元素数量；固定寄存器规模作为常数处理，不代表多键操作没有成本。Redis Cluster（Redis 集群）中，多键 PFCOUNT 的所有源、PFMERGE 的目标及所有源都需满足同一 Hash Slot（哈希槽）要求。上面的多键示例用于单实例；在 Cluster 中应先设计一致的 Hash Tag（哈希标签），不能直接照搬这些不带标签的键名。[PFADD](https://redis.io/docs/latest/commands/pfadd/) · [PFCOUNT](https://redis.io/docs/latest/commands/pfcount/) · [PFMERGE](https://redis.io/docs/latest/commands/pfmerge/) · [Cluster 同槽规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

## 3. 标准误差与输入统计口径 {#_3-误差怎样理解}

Redis Open Source 7.2.0 使用 16384 个寄存器。HLL 的相对标准误差 SE（Standard Error，标准误差，用于描述估计波动）可用下式近似理解：

```text
SE ≈ 1.04 / sqrt(16384) ≈ 0.008125 = 0.8125%
```

sqrt 表示平方根。约 0.81% 是统计误差指标，不是单次绝对误差上限，也不保证每次估计都处于真实值的 ±0.81% 内；实际样本还需实验验证。它也不是“成员查询误判概率”，因为 HLL 根本不提供成员查询。[官方误差说明](https://redis.io/docs/latest/develop/data-types/probabilistic/hyperloglogs/) · [原始论文中的误差近似](https://algo.inria.fr/flajolet/Publications/FlFuGaMe07.pdf)

统计质量还依赖输入口径：同一用户是否采用稳定标识，机器人和匿名会话如何区分，重复事件与跨端用户怎样定义。算法正确也不能修复输入定义不一致。

## 4. 内存与删除边界

Redis HLL 用 String（字符串）保存统计结构。Redis Open Source 7.2.0 的 16384 个寄存器，每个使用 6 bit（二进制位）。Dense Encoding（稠密编码）将寄存器固定排布，寄存器数据占 12288 字节，加上 16 字节头部，字符串有效载荷共 12304 字节：

```text
16 + (16384 × 6 / 8) = 12304 bytes
```

这不包括 Redis 对象、键名、字符串管理信息和分配器等全部开销，不能理解为每个 HLL 的总内存永远精确固定为 12304 字节。

Sparse Encoding（稀疏编码）压缩尚未明显变化的寄存器及连续重复状态，适合较小规模统计。状态变复杂时可能转为稠密表示；7.2.0 的 `hll-sparse-max-bytes` 默认 `3000` 字节，稀疏状态超过适用容量阈值，或统计值超出稀疏表示能力时会转换，并非按某个固定用户人数切换。稠密载荷随后相对稳定，但大量日期、地区分桶仍要累计预算。[7.2.0 头部、寄存器与转换实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/hyperloglog.c) · [7.2.0 配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

不能像 Set 那样从 HLL 安全删除一个成员。需要可修正的统计时，应保留权威事件或按时间分桶后重新计算，不把 HLL 当成唯一原始数据源。

## 5. 对照精确基数验收估计结果 {#_5-如何验收}

对同一批样本分别计算精确去重结果和 HLL 估计值，在不同基数与分布下比较误差。同时记录采样时间、用户标识规则和是否经过合并，不能只挑选一个接近的结果来证明效果。

适用于趋势报表的误差，未必适用于财务结算或唯一业务事件判定。

| 业务场景               | 是否适合 HLL                 |
| ---------------------- | ---------------------------- |
| 网站每日 UV 趋势       | 适合，前提是接受数量误差     |
| 搜索关键词独立数量估算 | 适合，不需要完整词表时       |
| 活跃用户大致规模       | 适合，先统一用户标识口径     |
| 财务结算               | 不适合承担要求精确的业务计数 |
| 判断订单是否处理过     | 不适合，无法精确查询成员身份 |
| 需要完整用户名单       | 不适合，无法还原成员列表     |

[返回本册目录](/collections/redis/)
