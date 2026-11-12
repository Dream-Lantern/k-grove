---
id: redis-fork-copy-on-write
title: 第二十章 fork、写时复制与资源峰值
description: "后台保存通过子进程推进工作，父进程仍要承担 fork 的准备和后续写时复制成本。理解资源峰值时，分别观察 fork 暂停、父子资源竞争，以及变化页产生的额外内存，再把它们放到同一时间线上。"
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
order: 20
---

# 第二十章 fork、写时复制与资源峰值

[返回本册目录](/collections/redis/)

后台保存通过子进程推进工作，父进程仍要承担 fork 的准备和后续写时复制成本。理解资源峰值时，分别观察 fork 暂停、父子资源竞争，以及变化页产生的额外内存，再把它们放到同一时间线上。

本章以 Linux 进程模型和 Redis Open Source 7.2.0 为教学背景，不推广为所有操作系统的相同行为。fork 是创建子进程的系统调用；COW（Copy-on-Write，写时复制）是在共享页面需要修改时再产生适用副本的机制。数字按示例条件计算。持久化流程见 [第 19 章](/articles/redis-rdb-aof.html)。

RDB（Redis Database，数据库快照）保存和 AOF（Append Only File，只追加文件）重写是本章关注的典型后台任务。

[![fork 与写时复制：按变化页产生额外开销](/assets/notes/redis/redis-study-cow.png)](/assets/notes/redis/redis-study-cow.png)

配图中的“内存未额外增加”和“读取不会产生额外开销”，只用于说明共享数据页尚未产生 COW 副本；不包含页表、进程管理或读取本身的成本，不能理解为 fork 和只读操作完全没有资源开销。

## 1. fork 建立共享页，写入触发按页复制 {#_1-fork-并非立即复制全部数据}

fork 需要创建子进程并处理页表等内存管理结构。初始阶段父子进程有各自的虚拟地址空间，但通常共享适用的物理页；当父进程修改仍共享的页面时，COW 才为相关页面产生额外副本。因此不能简单说“fork 立刻占用双倍内存”，也不能说“COW 保证永远不会接近双倍”。

```text
fork 刚完成：父进程 ─┐
                     ├─ 共享物理页 A
             子进程 ─┘

父进程写入后：父进程 ── 新物理页 A'
               子进程 ── 原物理页 A
```

只读访问通常不触发这种复制；写入则可能只改几个逻辑字节，却复制一个完整页面。子进程继续读取旧页，便能生成 fork 时点的数据表示，父进程同时继续服务；子进程自身的适用写入也可能产生页面开销。[Linux fork 说明](https://man7.org/linux/man-pages/man2/fork.2.html)

额外开销与修改了哪些页面、子进程存活多久、页面大小、分配器行为和内核环境有关。业务只修改少量逻辑字节，也可能涉及更多物理页面。持续高写入与慢磁盘组合，会延长子进程工作时间，增加峰值风险。

教学估算：相关共享数据为 8 GiB，模型采用 4 KiB 页面；子进程存活期间，25% 的相关共享页因写入产生一个额外副本：

```text
预计额外 COW 页面内存 = 8 GiB × 25% = 2 GiB
```

GiB（Gibibyte，吉比字节）为 2³⁰ 字节，KiB（Kibibyte，千比字节）为 2¹⁰ 字节。这里的 25% 是物理页比例，不是修改键的比例，也不是每写一次都重新复制同一页。实际还要考虑页表、缓冲、分配器和内核开销。

## 2. 分别记录暂停、资源竞争与内存增长 {#_2-暂停、竞争与内存是三件事}

fork 时的暂停可能影响请求尾延迟，后台子进程运行时可能争用 CPU 和磁盘，COW 及其他缓冲则会增加内存占用。某次持久化任务变慢时，不能只凭这一现象就认定是其中某一项造成的。

CPU（Central Processing Unit，中央处理器）与磁盘竞争要结合系统观测。以下是只读 Redis 命令示例；下表字段均已按 Redis Open Source 7.2.0 核对：

```redis
INFO stats
INFO persistence
INFO memory
```

| 字段                    | INFO section | 含义与单位，Redis Open Source 7.2.0                      |
| ----------------------- | ------------ | -------------------------------------------------------- |
| latest_fork_usec        | stats        | 最近一次 fork 耗时，微秒，不是历史最大值或后台任务总时长 |
| rdb_last_cow_size       | persistence  | 最近 RDB 后台保存报告的 COW 大小，字节                   |
| aof_last_cow_size       | persistence  | 最近 AOF 重写报告的 COW 大小，字节                       |
| current_cow_size        | persistence  | 当前后台子进程报告的 COW 采样大小，字节                  |
| current_cow_peak        | persistence  | 当前后台子进程运行期间记录的 COW 峰值，字节              |
| rdb_bgsave_in_progress  | persistence  | 是否在进行后台 RDB 保存                                  |
| aof_rewrite_in_progress | persistence  | 是否在进行后台 AOF 重写                                  |
| used_memory_rss         | memory       | Redis 主进程的 RSS，字节，不包含全部子进程内存           |

当前值可能受采样间隔影响；两个 last_cow_size 分别属于不同任务，不能当作当前事件或直接相加当作本机当前额外开销。累计指标要看变化量，latest_fork_usec 则直接记录最近一次事件。应把它们与任务状态、业务 P99（第 99 百分位请求延迟）、CPU 调度和磁盘延迟放到同一时间线上。[INFO 字段说明](https://redis.io/docs/latest/commands/info/) · [7.2.0 字段输出](https://raw.githubusercontent.com/redis/redis/7.2.0/src/server.c)

RSS（Resident Set Size，驻留内存大小）统计一个进程驻留的物理页，其中包含共享页。父、子进程各自的 RSS 都可能计入同一页，直接相加会重复计算。PSS（Proportional Set Size，按共享比例分摊的内存大小）把共享页按共享比例分摊，适合辅助观察多个进程的实际占用。COW 指标也不是“系统可用内存减少量”，还需考虑缓存、分配器和其他进程。

在支持且有权限的 Linux 环境，可只读查看 `/proc/<pid>/smaps_rollup` 的 Rss、Pss、Shared/Private 等字段；`<pid>` 是实际进程号占位符，可分别观察父、子进程。若内核不提供该文件，应核对其 `/proc/<pid>/smaps` 支持；此处仅说明观察方法，不要求修改系统参数。[Linux /proc 内存统计](https://docs.kernel.org/filesystems/proc.html)

## 3. 将历史经验值放回具体测量环境 {#_3-原笔记中的固定经验值应降级为假设}

“每 GB 固定耗时多少毫秒”“单实例一律不能超过某个 GB 数”“CPU 低于某个百分比就安全”，这些判断都不能通用于不同硬件、内核和负载。它们可以作为历史环境的观测记录保留，但不能直接作为本机或新环境的容量结论。

THP（Transparent Huge Pages，透明大页）、Memory Overcommit（内存超额承诺）和 Swap（交换空间）影响不同环节：

| 机制       | 主要影响                                                                          |
| ---------- | --------------------------------------------------------------------------------- |
| THP        | 内核以较大页面管理部分内存，影响页面拆分、整理及 COW 成本；实际复制粒度依内核行为 |
| Overcommit | 内存承诺和分配检查，影响 fork 是否被允许；不是保证物理内存够用                    |
| Swap       | 内存压力下可能发生磁盘换页，造成高延迟                                            |
| 内存分配器 | 分配、碎片和页面修改模式，影响 RSS 与额外页面开销                                 |

这些设置涉及系统级权衡，不能不测量就批量修改。关闭 THP 也不能消除页表、COW、资源争用等全部 fork 风险。[官方延迟排查](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/latency/)

后台保存或重写失败时，可按以下只读排查思路定位：

```text
BGSAVE / AOF Rewrite 失败 → 检查 Redis 日志中的具体错误
 → 检查主机和容器剩余内存 → 检查内存承诺、进程及系统限制
 → 对照 fork / COW 指标 → 结合内存压力和系统日志定位
```

失败不一定发生在 fork，也可能是磁盘空间或写入错误。即使是 fork 失败，也不能只看 Redis 的 used_memory；主机可用内存、容器限制、页表和系统资源限制都可能相关。不要将允许分配等同于不会遭遇后续内存不足。

## 4. 多实例会放大同机峰值

同一机器上三个实例分别看都不大，若同时做全量复制或持久化，峰值仍可能叠加。容量预算要包括各实例的数据、客户端与复制缓冲、COW、其他进程、操作系统和安全余量。

以下仅是假设案例，不是真实生产测试：

| 实例    | 任务前常驻内存 | 同时发生的后台工作             |
| ------- | -------------: | ------------------------------ |
| Redis A |          8 GiB | BGSAVE                         |
| Redis B |          6 GiB | AOF Rewrite（AOF 重写）        |
| Redis C |          4 GiB | 作为主节点向新副本进行全量复制 |

任务前合计 18 GiB 只是预算的一部分。若三个任务重叠，COW、子进程私有内存、复制缓冲、网络及操作系统开销可能同时升高；也不能把父子 RSS 简单相加当作唯一物理内存总量。全量复制流程和资源成本见 [第 21 章](/articles/redis-replication-psync.html)。

可以评估错开高开销任务、控制写入峰值和降低单实例恢复成本等方向，但具体操作还需结合维护窗口与恢复方案。拆小实例也会增加连接、管理和故障切换的复杂度，收益并非没有代价。

学习时可在隔离环境建立可复现对照：固定数据量，分别施加低写入和高写入，记录子进程时间与峰值。没有这样的实验，就不应把估计数字写成已经验证的结论。本次整理没有执行 fork 压测或修改 Windows/Linux 系统设置。
