---
id: redis-ttl-lifecycle
title: 第十三章 TTL、主动过期与删除生命周期
description: "TTL 决定数据何时不再有效；过期检查、对象删除和内存归还则是不同步骤。把它们当成同一时刻，容易误判内存和定时任务行为。"
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
order: 13
---

# 第十三章 TTL、主动过期与删除生命周期

TTL（Time to Live，生存时间）决定数据何时不再有效；过期检查、对象删除和内存归还则是不同步骤。把它们当成同一时刻，容易误判内存和定时任务行为。

本章以 Redis Open Source 7.2.0 的键级过期为参照，Hash 字段过期单独标注 7.4.0。`redis` 代码块是在交互客户端中输入的 Redis 命令，不是 Shell 命令；示例均未执行，返回结果只作教学推演。

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

TTL 返回秒，PTTL 返回毫秒精度的剩余时间。Redis Open Source 2.8.0 起可区分以下返回值；更早版本不能仅靠 -1 区分“不存在”和“没有期限”：[PTTL](https://redis.io/docs/latest/commands/pttl/)

| 返回值 | 含义                                 |
| ------ | ------------------------------------ |
| 正整数 | 按该命令单位表示的剩余时间           |
| 0      | 按该精度表示为 0，不等于键已经不存在 |
| -1     | 键存在，没有过期时间                 |
| -2     | 键不存在，包括访问时已判为过期的情况 |

短期限示例，未执行：

```redis
SET demo:ttl value PX 500
TTL demo:ttl
PTTL demo:ttl
```

如果查询时还剩约 400 毫秒，TTL 可以返回 `0`，紧接着的 PTTL 仍可能是正数。不能断言这段代码一定返回某个结果：命令之间时间会流逝，可能已经过期；在 7.2.0 中 TTL 按 `(剩余毫秒 + 500) / 1000` 取整，刚好剩 500 毫秒时也可能返回 `1`，并非简单向下截断。PTTL=0 也不能当作永久键。[7.2.0 TTL 实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/expire.c)

设置期限时，还要区分相对时长和绝对时刻：

| 命令      | 参数含义             |
| --------- | -------------------- |
| EXPIRE    | 从现在起的秒数       |
| PEXPIRE   | 从现在起的毫秒数     |
| EXPIREAT  | 绝对 Unix 秒时间戳   |
| PEXPIREAT | 绝对 Unix 毫秒时间戳 |

Unix 时间戳表示自 1970-01-01 00:00:00 UTC 起经过的时间。Redis Open Source 2.6.0 起以绝对毫秒时间戳保存期限，支持毫秒级过期精度；它不代表后台删除和通知也有毫秒级准时保证。停机期间时间仍会流逝，系统时钟向前或向后跳变会影响过期判断；把 RDB（Redis Database，数据库快照）搬到另一台机器时，要关注两端时钟偏差。[期限精度与时钟](https://redis.io/docs/latest/commands/expire/)

为不存在的键设置期限不会生成新数据。EXPIRE/PEXPIRE 使用非正时长，或 EXPIREAT/PEXPIREAT 指定过去时刻时，会立即删除已存在的键；这与正常到期事件不同，见第 6 节。

## 2. 更新操作可能保留或清除期限

不同更新操作按各自规则处理期限，可以分别观察覆盖、原地修改与重命名：

| 操作                                    | 键级 TTL 的适用语义                                                    |
| --------------------------------------- | ---------------------------------------------------------------------- |
| 普通 SET 成功覆盖，未指定期限或 KEEPTTL | 清除旧 TTL；条件不满足而未写入，不等于已经清除                         |
| SET … KEEPTTL                           | Redis Open Source 6.0.0 起可保留已有 TTL；不存在键时不会凭空生成旧期限 |
| SET key value EX 60                     | 写入值并设置新的 60 秒 TTL                                             |
| SET key value PX 60000                  | 写入值并设置新的 60000 毫秒 TTL                                        |
| INCR、HSET 等适用的原地修改             | 保留键级 TTL，不等于保留所有成员级期限                                 |
| RENAME                                  | 期限随源键转移；覆盖目标时不能继续沿用目标的旧 TTL                     |

普通 SET 替换整个值，成功写入时若没有新期限或 KEEPTTL，旧 TTL 就会清除。KEEPTTL 自 Redis Open Source 6.0.0 提供；若 SET 的 NX/XX 条件未满足，值和 TTL 都不改。[SET](https://redis.io/docs/latest/commands/set/)

Redis Open Source 7.0.0 起，EXPIRE 的条件可控制是否更新期限：

| 条件 | 何时设置                 |
| ---- | ------------------------ |
| NX   | 键存在且尚无 TTL         |
| XX   | 键已经有 TTL             |
| GT   | 新截止时刻晚于原截止时刻 |
| LT   | 新截止时刻早于原截止时刻 |

GT/LT 比较时，无 TTL 的键视作期限无限远，因此 GT 不为其设置有限期限，而 LT 可以。以 7.2.0 的参数解析为准：NX 不能与 XX、GT、LT 组合；GT 与 LT 互斥；XX 可以与 GT 或 LT 组合。例如 `EXPIRE demo:temporary 180 XX GT` 只延长已有期限，成功返回 `1`，条件未满足或键不存在返回 `0`。[EXPIRE 条件与版本](https://redis.io/docs/latest/commands/expire/) · [7.2.0 组合校验](https://raw.githubusercontent.com/redis/redis/7.2.0/src/expire.c)

以上是键的期限。Redis Open Source 7.4.0 的 Hash field（哈希字段）TTL 是另一层：普通 HSET 覆盖某个字段会清除该字段的 TTL，Hash 键级 TTL 则保留。键级期限到达会影响整个 Hash，字段期限只影响相应字段，不能互相替代。它也不意味着 List、Set 或 GEO 都有统一的成员过期命令。示例闭环见 [第 4 章 Hash 字段过期](/articles/redis-hashes.html)；版本及覆盖行为依据 [7.4.0 HEXPIRE 定义](https://raw.githubusercontent.com/redis/redis/7.4.0/src/commands/hexpire.json)和 [7.4.0 Hash 实现](https://raw.githubusercontent.com/redis/redis/7.4.0/src/t_hash.c)。

## 3. 访问检查与主动处理

过期键可以在访问等路径中被识别，主动过期机制则在预算内检查并删除相应数据，而不是每个调度周期都遍历整个键空间。

在普通主节点上，可先用两个简化流程理解：

```text
被动过期：客户端访问键 → 检查截止时刻
                       ├─ 未过期：正常返回
                       └─ 已过期：删除键，按不存在处理

主动过期：周期性工作 → 从有期限的键中抽样检查
                     → 删除已过期键 → 在时间和工作量预算内继续
```

只靠访问检查，永远不再访问的过期数据可能一直占内存。主动检查逐步处理过期字典中的候选，避免每次扫描所有键；又因为检查和删除会消耗 CPU（Central Processing Unit，中央处理器）时间，必须限制每轮工作，给请求处理留出机会。

以 Redis Open Source 7.2.0 为准，`hz` 影响周期性维护调度的基准频率；`dynamic-hz` 开启后实际频率还会随负载调整，主动过期也有快、慢周期，不能说“每秒固定扫描整个数据库若干次”。`active-expire-effort` 调整主动过期的抽样和时间预算，范围 1～10，默认 1；提高它会更积极清理，也可能增加请求延迟。这里的“后台”是主事件循环中的维护工作，不等于另开一个过期扫描线程。[7.2.0 过期周期](https://raw.githubusercontent.com/redis/redis/7.2.0/src/expire.c) · [7.2.0 调度配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

复制时还要分清职责：正常跟随主节点的副本，通常由主节点协调过期删除并接收相应删除传播；副本保留期限信息，读路径可能把逻辑过期键视为不存在，但不会照搬主节点的自主删除流程。提升为主节点后，它才承担主动过期等职责。传播到副本或写入 AOF（Append Only File，只追加文件），不等于各端物理内存都在同一时刻释放。[过期与复制](https://redis.io/docs/latest/commands/expire/)

大量具有相同 TTL 的键集中到期，还可能造成集中回源或清理压力。在业务允许时，可以按其容忍度加入过期抖动，但不应随意延长具有严格时效要求的数据。

## 4. 过期与淘汰有不同原因

expired_keys 与 evicted_keys 表示不同机制。前者与期限相关，后者与内存策略有关；volatile 策略的候选是有 TTL 的键，不是只剩已经过期的键。

可以在有相应权限的学习环境中观察以下命令，均未运行：

```redis
INFO stats
INFO memory
```

`expired_keys` 统计因过期被删除的键；`evicted_keys` 统计因 maxmemory 内存上限和淘汰策略被移除的键。例如键 A 到期且被过期机制删除，会增加前者；键 B 尚未到期却为腾出内存被淘汰，会增加后者。逻辑到期但尚未检查删除时，不能先认定 expired_keys 已增加；生产中还有其他键活动，应观察一段时间内的变化，不能据此归因于单个键。[INFO 指标](https://redis.io/docs/latest/commands/info/)

逻辑上看不到键，也不保证 RSS（Resident Set Size，进程驻留内存）立即下降。分配器可能保留页面供后续复用，COW（Copy-on-Write，写时复制）或其他进程开销也会改变内存观察。继续参见 [第 25 章内存淘汰](/articles/redis-memory-eviction.html)和 [第 30 章可观测性](/articles/redis-observability.html)。

## 5. DEL 与 UNLINK

DEL 会按对象和实现执行删除，释放复杂大对象可能明显占用主要路径；UNLINK 将适用的内存回收移到异步路径，键的可见性先改变。

| 维度           | DEL，默认同步删除配置 | UNLINK                                 |
| -------------- | --------------------- | -------------------------------------- |
| 从键空间移除   | 在命令路径完成        | 先在命令路径解除键空间引用             |
| 值对象内存回收 | 主要在当前执行路径    | 对释放成本较高的适用对象交给后台线程   |
| 复杂大对象     | 可能长时间占用主路径  | 可减少主路径释放工作                   |
| 成本           | 当前路径的 CPU 工作   | 仍有后台队列、CPU 与等待回收的内存成本 |

UNLINK 自 Redis Open Source 4.0.0 提供，不能写成“永不阻塞且免费”。7.2.0 实现按释放成本等条件判断是否异步，少量分配的对象可能直接释放，并非每次都入后台队列；DEL 也可能因 `lazyfree-lazy-user-del` 配置改变默认释放路径。维护前仍要核对权限、对象和容量。[UNLINK](https://redis.io/docs/latest/commands/unlink/) · [7.2.0 异步释放实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/lazyfree.c) · [7.2.0 lazyfree 配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

## 6. 期限通知与可恢复的业务调度 {#_6-过期不应充当唯一业务调度器}

键空间通知可能有延迟、断线和投递边界。到期通知不是一个永久记录且必达的任务队列，也不保证精确时刻触发。

Keyspace Notifications（键空间通知）需要启用相应的 `notify-keyspace-events` 配置。例如配置值 `Ex` 表示发布键事件频道的过期事件；这是配置值说明，不是已经执行的配置变更。启用后可按下面的过程理解：

```text
逻辑期限到达 → 等待访问检查或主动检查 → 实际删除键
            → 产生 expired 事件 → 在线订阅者可能收到
```

这里的“删除”是从键空间移除，不是等待所有内存归还操作系统。TTL 归零不保证立刻产生通知；EXPIRE/PEXPIRE 的非正时长或过去的绝对期限导致立即删除时，产生的是 `del`，不是 `expired`，还需开启通用命令事件类别才能订阅到 del。通知使用 PubSub（Publish/Subscribe，发布订阅），断线期间没有自动补发；Redis Cluster（集群）的通知是节点局部事件，要覆盖相关节点并处理拓扑变化。[通知配置、事件与触发时间](https://redis.io/docs/latest/develop/pubsub/keyspace-notifications/)

需要按时执行和失败追踪的业务，应采用可恢复的调度与任务状态设计。Redis TTL 可以参与清理和状态表达，但过期通知不能单独承担支付、订单超时等关键业务调度。

[返回本册目录](/collections/redis/)
