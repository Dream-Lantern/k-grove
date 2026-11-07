---
id: redis-memory-eviction
title: 第二十五章 内存核算、淘汰与碎片诊断
description: "分析 Redis 内存时，先区分数据对象、分配器统计和操作系统驻留内存三种口径，再判断压力来自对象、缓冲、保留页还是主机峰值。"
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

分析 Redis 内存时，先区分数据对象、分配器统计和操作系统驻留内存三种口径，再判断压力来自对象、缓冲、保留页还是主机峰值。确定来源后，才能评估容量、淘汰或碎片处理方案。

本章指标和实现以 Redis Open Source 7.2.0 为基线，8.6.0 的新策略另行标注。下文命令是 Redis 命令，不是 Shell；均未实际运行，数值案例均为教学假设。

![四种观察口径](/assets/notes/redis/redis-study-memory.svg)

## 1. 从数据到进程 RSS

键名、值、过期信息和对象元数据都占空间，客户端缓冲、复制、持久化相关结构也需要内存。`used_memory` 不是“纯 value 字节”；`MEMORY USAGE` 针对单键估算，也不是整个实例的 RSS。

RSS（Resident Set Size，常驻内存大小）是操作系统观察到的进程驻留物理内存。分配器保留页、代码和其他开销，会使它与 used_memory 不同。Allocator（内存分配器）负责向 Redis 分配内存，并管理底层页面；释放对象并不代表页面立即还给操作系统。

下面各指标均可在 Redis Open Source 7.2.0 的 `INFO memory` 中观察，字节量以 bytes 为单位；分配器相关值的可用性和精度取决于构建及分配器：

| 指标                        | 含义                                                           | 用途                                       |
| --------------------------- | -------------------------------------------------------------- | ------------------------------------------ |
| `used_memory`               | Redis 分配接口统计的已分配内存，包含对象及运行开销             | 判断对象、缓冲等分配是否增长               |
| `used_memory_rss`           | 操作系统报告的主进程 RSS                                       | 对照进程驻留与主机压力，不含全部子进程预算 |
| `used_memory_peak`          | 已分配内存的历史峰值                                           | 判断是否曾暴涨后回落；不是当前 RSS 峰值    |
| `allocator_allocated`       | 分配器统计的已分配字节，包含内部取整开销，通常接近 used_memory | 观察分配器底层分配量                       |
| `allocator_active`          | 分配器活跃页的总字节，包含页内尚未使用空间                     | 与 allocated 对比，判断外部碎片            |
| `allocator_resident`        | 分配器驻留内存，包含保留页及管理开销                           | 与 active 对比，观察驻留膨胀               |
| `mem_fragmentation_ratio`   | 进程 RSS 与已分配内存的比率                                    | 总体差异线索，不是纯碎片率                 |
| `allocator_frag_ratio`      | active / allocated                                             | 观察分配器外部碎片                         |
| `allocator_rss_ratio`       | resident / active                                              | 观察活跃页之外的分配器驻留开销、保留页面   |
| `rss_overhead_ratio`        | 进程 RSS / allocator resident                                  | 观察非分配器部分，如代码、栈、共享库等     |
| `mem_not_counted_for_evict` | 不计入淘汰判定的部分缓冲内存                                   | 对照淘汰口径，仍要计入实际容量预算         |

同一采样口径下，可按以下关系理解，分母必须非零：

```text
mem_fragmentation_ratio = used_memory_rss / used_memory
allocator_frag_ratio    = allocator_active / allocator_allocated
allocator_rss_ratio     = allocator_resident / allocator_active
rss_overhead_ratio      = used_memory_rss / allocator_resident
```

这些是官方字段的比率关系。7.2.0 的比率使用定时采样缓存，`used_memory` 则可在查询时重新取得，因此用同一次 INFO 展示值相除，也可能因采样时点和舍入而不完全一致。三个 allocator/RSS 比率不能混用，也不能直接相加。[INFO 字段定义](https://redis.io/docs/latest/commands/info/)、[7.2.0 getMemoryOverheadData](https://github.com/redis/redis/blob/7.2.0/src/object.c)

`mem_fragmentation_ratio` 不能简单等同“纯分配器碎片率”。尤其在数据量很小时，固定开销就可能造成高比例；应同时看绝对字节、allocator 指标和变化过程。

比率小于 1 不足以证明已经发生 Swap（内存换出到交换空间）；应进一步看系统交换、页错误、进程驻留和采样时刻。比率大于 1 也不能直接推出需要重启。[INFO memory 字段解释](https://redis.io/docs/latest/commands/info/)

## 2. maxmemory 的核算范围与角色差异 {#_2-maxmemory-不是-rss-硬上限}

maxmemory 用于 Redis 内存管理，部分缓冲统计有特殊处理；实际进程与主机内存还需要预留持久化、复制、COW（Copy-On-Write，写时复制）、其他进程和操作系统空间。

排查时把“特殊处理”落实到 INFO memory 的 `mem_not_counted_for_evict`：它描述未计入相应淘汰判定的缓冲量，应与 used_memory、RSS、分配器和主机峰值共同观察。不要把这些交叠口径直接相加，也不把 maxmemory 减去该指标的某个静态值当成永久容量公式。[淘汰与缓冲核算](https://redis.io/docs/latest/develop/reference/eviction/)

在 7.2.0 中，可用 `max(used_memory - mem_not_counted_for_evict, 0)` 理解相应淘汰判定的逻辑内存量。排除部分复制和 AOF（Append Only File，只追加文件）缓冲，是为了避免淘汰产生更多删除传播、缓冲越大又触发更多淘汰的反馈循环。**不是所有复制内存都被排除**：共享复制缓冲中，按 backlog 预算计入的部分仍会计数。[7.2.0 freeMemoryGetNotCountedMemory / getMaxmemoryState](https://github.com/redis/redis/blob/7.2.0/src/evict.c)

教学假设：机器有 16 GiB（Gibibyte，2³⁰ 字节）内存，maxmemory=10 GiB，used_memory=9.5 GiB，RSS=12 GiB：

| 观察                          | 可以得出的结论                                                    |
| ----------------------------- | ----------------------------------------------------------------- |
| used_memory 小于 maxmemory    | 单看这一时点，没有超过该内存管理阈值                              |
| RSS 比 used_memory 多 2.5 GiB | 需要继续查分配器活跃页、保留页和进程额外开销，不能全算成碎片      |
| RSS 比 maxmemory 多 2 GiB     | maxmemory 不是 RSS 硬上限；这个差值也不是碎片大小                 |
| 机器总内存 16 GiB             | 不能把剩余 4 GiB 全部承诺给业务，还要扣除其他进程、系统及后续峰值 |

这四个数字不足以反推出数据对象和缓冲各占多少，应结合 MEMORY STATS 的 dataset、overhead 和缓冲字段。复制、AOF 缓冲通常已包含在相应已分配统计中，不能再重复相加；它们未来的增长仍需预留。fork（创建子进程的系统调用）产生后台子进程后，写入共享页可能产生 COW 副本，进一步提高整机峰值。[第二十章](/articles/redis-fork-copy-on-write.html)解释 COW，[第十九章](/articles/redis-rdb-aof.html)解释持久化任务。

节点角色也会影响行为。例如 Redis 7.2.0 默认 `replica-ignore-maxmemory yes`，副本通常不会像主节点那样按本地 maxmemory 执行淘汰，内存占用可能超过该设置。因此，为主副本配置相同数值，并不意味着它们有相同的硬性保护；副本提升为主后，还需按新的角色重新判断。[7.2.0 副本配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

Redis 返回 OOM（Out Of Memory，内存不足）错误，与系统 OOM Killer 杀掉进程，是不同故障。前者可发生在某些命令被策略拒绝时；后者意味着操作系统或容器的 cgroup（Control Groups，Linux 控制组）内存压力，不能只通过换成 allkeys-lru 解决。

## 3. 淘汰策略先决定候选范围

[![Redis 内存淘汰与操作系统 OOM](/assets/notes/redis/redis-study-eviction.svg)](/assets/notes/redis/redis-study-eviction.svg)

allkeys 类策略在全部适用键中选择；volatile 类策略只在具有 TTL（Time To Live，剩余生存时间）的候选键中选择。volatile 不是“只删除已经过期的键”，没有足够候选时，也可能无法腾出所需空间。

| 策略方向                                     | 适用理解                                   | 容易误解之处                               |
| -------------------------------------------- | ------------------------------------------ | ------------------------------------------ |
| noeviction                                   | 不为内存压力淘汰键，相关增内存命令可能报错 | 不是所有读取或所有写操作一律失败           |
| LRU（Least Recently Used，最近最少使用）     | 近似选择较久未访问的键，适合近期访问热点   | 不是维护全局严格访问排序                   |
| LFU（Least Frequently Used，最不经常使用）   | 根据访问频度及衰减，适合较稳定的长期热点   | 不是精确业务计数；Open Source 4.0.0 引入   |
| LRM（Least Recently Modified，最近最少修改） | 根据最近修改时间，适合更关注更新热度的场景 | Open Source 8.6.0 引入；读取不刷新修改时间 |
| random                                       | 在相应候选范围内随机选择                   | 不识别业务重要性                           |
| volatile-ttl                                 | 偏向期限较近的候选键                       | 不等于主动过期机制                         |

Redis Open Source 7.2.0 支持 `allkeys-lru` / `volatile-lru` 和 `allkeys-lfu` / `volatile-lfu`，不支持 LRM；8.6.0 增加 `allkeys-lrm` / `volatile-lrm`。LRU、LFU 通过采样等机制近似实现。LRM 关注修改时间，读得频繁但很久没更新的键仍可能优先淘汰，是否适合必须结合业务目标判断。选择前先确认哪些数据可以丢弃。[淘汰策略与 LFU 版本](https://redis.io/docs/latest/develop/reference/eviction/)、[8.6 发布说明](https://redis.io/docs/latest/develop/whats-new/8-6/)、[8.6.0 配置枚举](https://github.com/redis/redis/blob/8.6.0/src/config.c)

## 4. 用分配器与 RSS 证据定位碎片 {#_4-碎片处理要从证据出发}

大量大小不一对象反复创建删除后，可能出现分配器空洞。应先按以下路径诊断，不凭一个比率直接处理：

```text
发现内存增长 → 核对 maxmemory、策略、节点角色及容器限制
→ 比较 used_memory、RSS 与历史峰值 → 检查 allocator 指标
→ 检查普通客户端、复制和 AOF 缓冲
→ 检查 COW、持久化子进程、系统及其他进程
→ 确定对象增长 / 缓冲积压 / 碎片 / 保留页 / 主机峰值
→ 选择对应措施，并观察处理后的字节量和业务延迟
```

以下为 Redis Open Source 7.2.0 可用的只读检查示例；MEMORY 系列这些子命令均从 4.0.0 提供：

```redis
CONFIG GET maxmemory
CONFIG GET maxmemory-policy
INFO memory
INFO stats
INFO persistence
MEMORY STATS
MEMORY DOCTOR
MEMORY USAGE demo:object
```

| 命令                       | 用途及边界                                                        |
| -------------------------- | ----------------------------------------------------------------- |
| `INFO memory`              | 对照上述内存指标和客户端、复制、AOF 缓冲                          |
| `INFO stats`               | 观察 evicted_keys、expired_keys 等累计统计，结合时间差看变化      |
| `INFO persistence`         | 对照后台任务与当前、上次 COW 指标                                 |
| `MEMORY STATS`             | 详细内存构成；字段名如 allocator.active，与 INFO 的下划线命名不同 |
| `MEMORY DOCTOR`            | 根据指标给辅助诊断建议，不是自动根因分析                          |
| `MEMORY USAGE demo:object` | 估算单键及相关管理开销，不是实例总内存；键不存在返回 nil          |

MEMORY USAGE 对嵌套结构可采样，默认采样 5 个；`SAMPLES 0` 表示遍历全部元素，大对象可能带来明显开销，不作为默认检查。分配器字段缺失或使用回退统计时，更要结合操作系统证据。[STATS](https://redis.io/docs/latest/commands/memory-stats/)、[DOCTOR](https://redis.io/docs/latest/commands/memory-doctor/)、[USAGE](https://redis.io/docs/latest/commands/memory-usage/)

处理方式要与原因匹配。CPU（Central Processing Unit，中央处理器）开销、回收成本和可用性都需要纳入取舍：

| 方式                          | 原理与适用场景                                 | 成本及局限                                                             |
| ----------------------------- | ---------------------------------------------- | ---------------------------------------------------------------------- |
| Active Defrag（主动碎片整理） | 渐进搬移仍存活的分配并释放旧位置，减少外部碎片 | 需要额外 CPU；7.2.0 依赖适配的 jemalloc 构建，不能解决真实数据无限增长 |
| `MEMORY PURGE`                | 要求适用分配器尝试归还空闲页，适合保留页较多   | 可能慢，不压缩存活对象，不保证 RSS 立即下降                            |
| `UNLINK`                      | 从数据库移除键，适用对象的内存回收交给后台线程 | 是删除数据；回收仍有 CPU/内存成本，小对象也可能直接释放                |
| 重启                          | 在恢复或重新加载时重建内存布局                 | 涉及恢复时间、切换与数据风险，不是默认诊断动作                         |

Active Defrag、MEMORY PURGE、UNLINK 均在 Open Source 4.0.0 引入。上表是机制对比，示例未经实测，不表示已验证整理、PURGE、删除或重启效果。[7.2.0 主动整理配置](https://github.com/redis/redis/blob/7.2.0/redis.conf)、[PURGE](https://redis.io/docs/latest/commands/memory-purge/)、[UNLINK](https://redis.io/docs/latest/commands/unlink/)

简明决策：对象确实过多 → 优化模型、生命周期或容量；缓冲积压 → 查慢客户端与复制链路；外部碎片明显 → 评估主动整理；空闲页保留明显 → 评估归还页面；主机峰值过高 → 调整容量与后台任务计划。每一步先看证据，再验证处理效果。

容量规划宜从样本分布推算：键数量 × 每键实际占用，再加非数据开销和峰值。用一个小键的占用乘全部键数，或者只对 value 长度求和，往往低估真实成本。

例如教学假设：100 万个普通键，平均 value 为 200 字节，但按实际类型、键名和管理开销估出的每键占用是 400 字节；另有 100 个大键，每个 1 MiB（Mebibyte，2²⁰ 字节）。对象基线约为 `1000000 × 400 + 100 × 1048576 = 504857600` 字节，约 0.47 GiB，而只算普通 value 长度仅约 0.19 GiB。

若再假设运行缓冲及实例其他分配共 0.5 GiB，分配器与进程额外驻留 0.4 GiB，额外 COW 峰值 0.8 GiB，系统和其他进程预留 1 GiB，则教学预算约为 `0.47 + 0.5 + 0.4 + 0.8 + 1 = 3.17 GiB`。这里刻意使用不重复的预算分项，均不是实测；真实规划要覆盖大键尾部分布、并发后台任务和增长余量。

编码如何影响每键占用见[第二十六章](/articles/redis-internal-encoding.html)，集群迁移的额外资源与阶段验收见[第二十四章](/articles/redis-cluster-operations.html)。
