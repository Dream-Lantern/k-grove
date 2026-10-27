---
id: redis-memory-eviction
title: 第二十五章 内存核算、淘汰与碎片诊断
description: 返回本册目录
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
order: 25
---

# 第二十五章 内存核算、淘汰与碎片诊断

[返回本册目录](/collections/redis/)

“Redis 用了多少内存”至少有三种口径：数据对象占用、Redis 分配器统计、操作系统看到的驻留内存。它们不相等。排障第一步不是调淘汰策略，而是确定是哪种内存压力。

![四种观察口径](/assets/notes/redis/redis-study-memory.svg)

## 1. 从数据到进程 RSS

键名、值、过期信息和对象元数据都占空间，客户端缓冲、复制、持久化相关结构也需要内存。`used_memory` 不是“纯 value 字节”；`MEMORY USAGE` 针对单键估算，也不是整个实例的 RSS。

RSS 是操作系统口径。分配器保留但尚未还给系统的页面、代码和其他开销，会使它与 used_memory 不同。`mem_fragmentation_ratio` 因此不能简单等同“纯分配器碎片率”。尤其在数据量很小时，固定开销就可能造成高比例；应同时看绝对字节、allocator 指标和变化过程。

比率小于 1 不足以证明已经 swap；应进一步看系统交换、页错误、进程驻留和采样时刻。比率大于 1 也不能直接推出需要重启。[INFO memory 字段解释](https://redis.io/docs/latest/commands/info/)

## 2. maxmemory 不是 RSS 硬上限

maxmemory 用于 Redis 内存管理，部分缓冲统计有特殊处理；实际进程与主机内存还需要预留持久化、复制、COW、其他进程和操作系统空间。

排查时把“特殊处理”落实到 INFO memory 的 `mem_not_counted_for_evict`：它描述未计入相应淘汰判定的缓冲量，应与 used_memory、RSS、分配器和主机峰值共同观察。不要把这些交叠口径直接相加，也不把 maxmemory 减去该指标的某个静态值当成永久容量公式。[淘汰与缓冲核算](https://redis.io/docs/latest/develop/reference/eviction/)

节点角色也会影响行为。例如 Redis 7.2.0 默认 `replica-ignore-maxmemory yes`，副本通常不会像主节点那样按本地 maxmemory 执行淘汰，内存占用可能超过该设置。因此，为主副本配置相同数值，并不意味着它们有相同的硬性保护；副本提升为主后，还需按新的角色重新判断。[7.2.0 副本配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

Redis 返回 OOM 错误，与系统 OOM Killer 杀掉进程，是不同故障。前者可发生在某些命令被策略拒绝时；后者意味着主机或容器层面的问题，不能只通过换成 allkeys-lru 解决。

## 3. 淘汰策略先决定候选范围

[![Redis 内存淘汰与操作系统 OOM](/assets/notes/redis/redis-study-eviction.svg)](/assets/notes/redis/redis-study-eviction.svg)

allkeys 类策略在全部适用键中选择；volatile 类策略只在具有 TTL 的候选键中选择。volatile 不是“只删除已经过期的键”，没有足够候选时，也可能无法腾出所需空间。

| 策略方向     | 适用理解                                   | 容易误解之处                     |
| ------------ | ------------------------------------------ | -------------------------------- |
| noeviction   | 不为内存压力淘汰键，相关增内存命令可能报错 | 不是所有读取或所有写操作一律失败 |
| LRU          | 近似选择较久未访问的键                     | 不是维护全局严格访问排序         |
| LFU          | 考虑访问频度与衰减                         | 不是永远累加的精确业务计数       |
| random       | 在相应候选范围内随机选择                   | 不识别业务重要性                 |
| volatile-ttl | 偏向期限较近的候选键                       | 不等于主动过期机制               |

后续版本还可能增加策略，例如第 32 章介绍的 8.6 LRM。选择策略前，应先判断哪些数据可以丢弃；仅仅“换个更聪明算法”，无法保证唯一业务状态的安全。[淘汰策略](https://redis.io/docs/latest/develop/reference/eviction/)

## 4. 碎片处理要从证据出发

大量大小不一对象反复创建删除后，可能出现分配器空洞。active defrag 的可用性与成本依构建和版本；MEMORY PURGE 则是要求适用分配器尝试归还空闲页，不能把两者写成同一功能。

先观察 allocator_allocated、active、resident 与 RSS 的关系，再判断问题来自对象过大、缓冲积压、保留页还是碎片。不能脱离上下文使用固定比率阈值，或直接认定“重启就好”；重启本身还会带来恢复耗时、流量切换和数据风险。

容量规划宜从样本分布推算：键数量 × 每键实际占用，再加非数据开销和峰值。用一个小键的占用乘全部键数，或者只对 value 长度求和，往往低估真实成本。
