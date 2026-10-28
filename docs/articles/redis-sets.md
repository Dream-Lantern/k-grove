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

Set 保存不重复的成员，不提供插入顺序或按下标读取。它适合表达“某人是否属于这一组”，而不是需要稳定排名的列表。

## 1. 分别查询键、成员与集合数量 {#_1-键存在与成员存在}

新增例子，未执行：

```redis
SADD demo:tags:user-42 sports music
SISMEMBER demo:tags:user-42 sports
SCARD demo:tags:user-42
SREM demo:tags:user-42 music
```

EXISTS 检查键是否存在，SISMEMBER 检查成员，不能互相替代。SADD 返回新加入的成员数；重复添加同一成员不增加集合基数。

`SCARD` 可以读取已有的数量信息，不需要为了数成员而先 SMEMBERS。读取全部成员的回复量则随集合大小增长。

## 2. 并集、交集与差集

把用户兴趣、已完成任务或参与人群表示为集合后，可以计算共同成员与覆盖范围：

```redis
SINTER demo:{audience}:a demo:{audience}:b
SUNION demo:{audience}:a demo:{audience}:b
SDIFF demo:{audience}:a demo:{audience}:b
```

差集有方向，A 减 B 与 B 减 A 不同。STORE 版本把结果写入目标键，可能覆盖已有数据，还会消耗内存；不能把它当成纯查询。

同槽标签只用于演示 Cluster 中相应的多键约束。若所有大规模人群集合都共享同一个 tag，负载可能集中到单个节点。

## 3. 随机返回与随机删除

SRANDMEMBER 用于随机返回，SPOP 用于随机移除。前者不会因为读取而删除成员，后者会改变集合。

SRANDMEMBER 带正 count 时，返回的成员不重复，最多为集合基数；带负 count 时，允许重复，非空集合可以返回绝对值所指定的数量。带 count 的数组返回，也不同于省略 count 时的单个成员或空值。SPOP 则会移除实际返回的成员。[SRANDMEMBER](https://redis.io/docs/latest/commands/srandmember/)

教学推演：集合只有 a、b，count=3 最多返回这两个不同成员；count=-3 可以返回三个位置，其中必有重复，具体顺序不能预先确定。随机返回机制本身并不能证明商业抽奖公平，重复参与、随机来源和审计仍需在业务层考虑。

## 4. 精确集合的成本

Set 能回答精确成员关系，也能列出成员；这些能力需要相应存储。若只需要近似人数且不需要名单，HyperLogLog 可能更合适；若要快速排除不可能存在的值，Bloom Filter 又是另一种语义。

SSCAN 可以分批遍历，但不是快照分页。遍历持续变化的数据集合时，应用需要处理重复、数据变化与结束条件，不能把 COUNT 1000 理解为每页恰好返回 1000 个成员。

SMEMBERS、并交差运算都可能产生大工作量或大回复，需要按成员数、值大小和访问频率评估。

## 5. 类型与编码分开

历史实现常讲 intset 与 hashtable，但新版本还可能对某些小集合采用其他紧凑表示。intset 里的整数有序，也不意味着应用能通过 Set API 按序号访问。

整数集合阈值的配置名为 `set-max-intset-entries`，使用时核对目标版本。整数范围变化可能引起内部升级；编码的转换与回退不能一概按“所有类型永不回退”解释。

优化前先看实际版本与 OBJECT ENCODING，再比较典型负载，而不是只根据教科书里的一个阈值重组全部数据。基础成员语义见 [Set 数据类型](https://redis.io/docs/latest/develop/data-types/sets/)。

[返回本册目录](/collections/redis/)
