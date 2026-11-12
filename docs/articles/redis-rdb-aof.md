---
id: redis-rdb-aof
title: 第十九章 RDB、AOF 与恢复边界
description: "持久化回答的是“进程或机器失效后，可以从哪些文件恢复到什么状态”。它不是备份的同义词：误删除也可能被及时写进持久化文件，而同一块损坏的磁盘可能同时带走数据和文件。"
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
order: 19
---

# 第十九章 RDB、AOF 与恢复边界

[返回本册目录](/collections/redis/)

持久化回答的是“进程或机器失效后，可以从哪些文件恢复到什么状态”。它不是备份的同义词：误删除也可能被及时写进持久化文件，而同一块损坏的磁盘可能同时带走数据和文件。

RDB（Redis Database，数据库快照）保存某个数据时点的状态，AOF（Append Only File，只追加文件）保存用于重建状态的记录。本章以 Redis Open Source 7.2.0 为参照，多部分 AOF 自 7.0.0 提供。命令和时间线均为教学说明。

![RDB 与 AOF 的侧重点](/assets/notes/redis/redis-study-persistence.svg)

## 1. RDB：某个时间点的数据快照

RDB 保存数据集的快照。恢复时不必逐条重放全部历史命令，文件也适合按恢复点留存；代价是两次成功快照之间的变化，可能没有可恢复记录。

SAVE 在主执行路径同步生成快照，可能长时间阻塞请求。BGSAVE 通常通过 fork 后由子进程工作，但 fork 本身仍可能造成暂停，后台写盘也会与业务争用资源。因此“后台”不等于零影响。

定时 save 条件不是“每个键都按时备份”的承诺。条件是否满足、后台任务是否成功、磁盘是否有空间，都影响实际恢复点。验收时应看成功完成时间和业务可接受的数据损失窗口，而不只看配置文本。

BGSAVE 成功完成说明生成了一份可用快照，其数据时点通常对应更早的 fork（创建子进程）时刻，而不是文件写完的时刻。子进程生成快照时，父进程可以继续处理写入，这些后续变化不在该快照内。fork 和 COW（Copy-on-Write，写时复制）的资源成本见 [第 20 章](/articles/redis-fork-copy-on-write.html)。

## 2. AOF：记录适用写入并选择刷盘策略

AOF 通过追加日志支持数据重建。Redis 将内容交给操作系统，与要求内容持久写入介质，是两个不同的时刻；`appendfsync always`、`everysec`、`no` 分别在性能与风险之间作出不同取舍。

fsync（文件同步系统调用）要求操作系统把适用文件数据同步到存储。业务写入在内存执行、进入 Redis/AOF 缓冲、写入操作系统缓冲、完成 fsync、客户端取得回复，是相关但不同的阶段；回复与 fsync 的先后关系要看策略。7.2.0 的 always 路径在发送相应回复前同步，everysec 通常不等待本次后台 fsync 完成才回复。

everysec 常被概括为通常约一秒的数据风险窗口，但这不是所有故障、存储设备和系统停顿下都成立的硬上限。要结合 fsync 延迟、磁盘可靠性、重写期间配置与故障模型判断。操作系统或硬件不兑现持久写入保证时，配置名也不能补足这一层能力。

AOF 重写依据当前数据生成较精简的恢复表示，不是简单逐行删除“重复命令”。例如大量 INCR 最终可以被表示成当前值；重写与业务并发期间，还必须保存新的变化。[持久化机制与策略](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)

用同一故障场景比较，以下时刻、命令和结果均是假设：

```text
12:00:00  BGSAVE 成功，留下一份可用快照
12:00:10  SET order:1 paid
12:00:20  SET order:2 paid
12:00:25  Redis 所在机器故障
```

| 配置         | 可能的恢复结果                                                 |
| ------------ | -------------------------------------------------------------- |
| 仅 RDB       | 回到这份成功快照的数据时点，两条后续 SET 都可能缺失            |
| AOF everysec | 通常保留更多近期写入，但取决于实际完成的同步，不能写死丢失上限 |
| AOF always   | 对已确认写入提供更强的同步保证，仍受设备与故障模型影响         |
| RDB + AOF    | 7.2.0 正常启动配置下优先按有效 AOF 文件集合恢复                |

表中的“12:00 快照”只是文件标记，实际数据截点还应追溯那次 fork；不能凭成功完成时间推断它包含之前全部写入。若日志和快照都在损坏磁盘上，也可能都不可用。everysec 不是严格一秒损失上限，原因包括同步延迟、系统停顿及 `no-appendfsync-on-rewrite` 等配置条件。[7.2.0 AOF 写入与同步](https://raw.githubusercontent.com/redis/redis/7.2.0/src/aof.c) · [7.2.0 刷盘配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

## 3. Redis 7.0+ 的 BASE、INCR 与 Manifest {#_3-redis-7-0-不要只找一个-appendonly-aof}

![多部分 AOF 的文件关系](/assets/notes/redis/redis-study-multipart-aof.svg)

Redis Open Source 7.0.0 起的多部分 AOF 由 BASE（基础文件）、INCR（Incremental，增量文件）与 Manifest（文件清单）共同组织。图中连线表示文件集关系，不是“把 Manifest 当数据日志重放”。基础文件可能采用 RDB 格式；新写入进入相应增量文件，Manifest 指定有效文件集合及加载顺序。

对已经启用 AOF 的 7.2.0 实例，重写可以按下面的高层流程理解；它不是完整源码时序，也不是旧版单文件 AOF 的拼接流程：

```text
触发重写 → 刷出当前 AOF 缓冲，打开新 INCR 并更新有效清单
         → fork
           ├─ 父进程：继续服务，将后续写入追加到新 INCR
           └─ 子进程：按 fork 时的状态生成临时 BASE
         → 子进程成功后，父进程确认并整理新文件集合
         → 持久化并原子替换 Manifest，启用新 BASE + 保留的新 INCR
         → 将不再需要的旧文件交给历史清理流程
```

重写期间的变化已经进入新 INCR，不需要在结束时把它们重新逐条拼到 BASE。7.2.0 源码在 fork 之前打开新增量文件，不能照搬旧版“父进程仅积累内存重写缓冲，最后追加到单文件”的描述。重写失败时，旧 BASE、仍有效的旧 INCR 与新增 INCR 仍用于完整重建，不可据此手工删除旧文件；首次启用 AOF 的过渡路径还另有状态处理。[多部分 AOF 机制](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) · [7.2.0 重写及清单切换实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/aof.c)

备份多部分 AOF 时，需要保存相互匹配的基础文件、增量文件和 manifest。重写期间文件集合仍可能变化，取回后应核对其完整性与对应关系。

## 4. 故障后确定加载源并校验恢复集合 {#_4-故障后-先保存现场再谈修复}

先确认启动配置实际启用了什么。正常配置下同时启用 AOF 与 RDB，重启使用 AOF 重建数据；目录中存在 dump.rdb 不说明本次从它恢复。AOF 损坏也不应假定平台自动挑选旧 RDB 作为无损回退。[AOF 与 RDB 的启动关系](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/#interactions-between-aof-and-rdb-persistence)

以下是适用于 Redis Open Source 7.2.0、有相应查询权限时的只读 Redis 命令示例。实例已停机时应从保存的配置和日志确认，不能为查询而反复启动唯一现场：

```redis
CONFIG GET appendonly
CONFIG GET appendfsync
CONFIG GET appenddirname
CONFIG GET dir
INFO persistence
LASTSAVE
```

| 检查项                    | 归属与用途，Redis Open Source 7.2.0                      |
| ------------------------- | -------------------------------------------------------- |
| appendonly                | 配置：是否启用 AOF                                       |
| appendfsync               | 配置：always、everysec 或 no                             |
| appenddirname、dir        | 配置：多部分 AOF 子目录及工作目录，共同定位文件          |
| rdb_last_bgsave_status    | INFO persistence：最近后台快照结果                       |
| aof_last_write_status     | INFO persistence：最近 AOF 写入状态                      |
| aof_last_bgrewrite_status | INFO persistence：最近后台 AOF 重写结果                  |
| aof_rewrite_in_progress   | INFO persistence：当前是否正在重写                       |
| LASTSAVE                  | 返回上次成功保存的 Unix 秒时间戳，不能替代文件完整性检查 |

appenddirname 属于 7.0.0 起的多部分 AOF 配置；其余状态也不能只看单字段下结论，例如 AOF 未启用时的默认状态不能证明有可恢复日志。[7.2.0 配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf) · [7.2.0 INFO 字段实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/server.c) · [LASTSAVE](https://redis.io/docs/latest/commands/lastsave/)

| 恢复材料        | 必须记录的加载依据                        |
| --------------- | ----------------------------------------- |
| 独立 RDB        | 实际启动配置、目标文件、版本和快照恢复点  |
| 历史单文件 AOF  | 对应版本、启用配置及日志完整性            |
| 7.0+ 多部分 AOF | 有效 manifest 与对应 BASE/INCR 的完整集合 |

AOF 尾部未完整写入与中间出现非法内容不是同一种故障，是否允许加载截断尾部还受配置影响。检查实际启动日志和加载源，不通过删除文件猜优先级，也不把重写 BASE 的 RDB 格式与独立 dump.rdb 混为一谈。

| 故障                           | 风险与检查边界                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------- |
| 最后一个 AOF 文件尾部不完整    | 7.2.0 的 aof-load-truncated 可允许加载到最后完整记录并处理截断尾部；不是无损恢复 |
| AOF 中间损坏，或非末尾文件截断 | 不能按普通尾部不完整处理；修复可能舍弃损坏位置之后的数据                         |
| Manifest 丢失或不匹配          | 不能随意猜测或拼接有效 BASE/INCR，需核对完整备份集合                             |
| 磁盘损坏                       | 本地材料可能不可用，需要独立备份或其他恢复来源                                   |

`redis-check-aof` 用于检查 AOF，修复模式可能改写或截断文件；应先在文件副本上检查，不默认使用 `--fix`，并核对目标版本对单文件和 Manifest 的输入要求。`aof-load-truncated` 不修复任意格式损坏，也不替代校验和业务验收。[AOF 截断与损坏处理](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) · [7.2.0 加载边界](https://raw.githubusercontent.com/redis/redis/7.2.0/src/aof.c)

加载失败时，应先保存原文件、日志、版本、配置与校验结果，避免反复启动或覆盖唯一副本。检查文件应使用匹配版本的工具，并在副本上操作。若修复可能截断数据，必须先明确损失范围，不能把 repair 理解为无损修复。

```text
确认版本 → 检查启动配置 → 由日志确认实际加载源和失败位置
         → 核对文件清单，保存原始文件、配置和日志
         → 在隔离文件副本上检查完整性 → 隔离恢复 → 校验业务数据
```

这里只做只读盘点和静态流程整理；修复、重写和恢复验证需要另行按维护方案执行。

恢复目标也不是“Redis 能启动就算成功”。还要核对关键键、类型、TTL（Time to Live，生存时间）、应用不变量、必要函数库或扩展，以及恢复后客户端是否误连了旧实例。恢复数据库应与生产写入隔离，防止验证过程中接收真实流量。

| 恢复后检查                          | 应确认什么                                   |
| ----------------------------------- | -------------------------------------------- |
| 键数量和类型                        | 与预期恢复点比较，数量相同仍不能证明内容一致 |
| 核心业务键值                        | 订单、去重状态等是否满足业务不变量           |
| TTL                                 | 截止时间是否合理，是否误恢复成永久键         |
| Redis Functions（服务端函数）和模块 | 函数库及所需扩展是否可用、版本匹配           |
| 持久化与复制状态                    | 当前策略、错误、角色和追赶进度是否符合方案   |
| 客户端连接目标                      | 路由及连接池是否指向已验收实例               |

本章不提供默认执行的修复或重写命令。`CONFIG SET dir` 等路径配置也不能按旧教程假定随时可改，现代版本对部分配置有保护。[Redis 7.2.0 配置源码](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

## 5. 把 RPO、RTO 写进方案

RPO（Recovery Point Objective，恢复点目标）表示最多可接受丢失多少时间范围的数据；RTO（Recovery Time Objective，恢复时间目标）表示最多可接受多长时间恢复服务。例如“允许丢失可重建的十分钟缓存”和“订单去重状态不能随意丢失”，需要完全不同的策略。

独立假设案例：业务要求 RPO=5 分钟、RTO=10 分钟。故障在 12:00，最后可用数据截点为 11:57，损失窗口为 3 分钟；若取回备份、检查、加载、业务验证和客户端切换共用 9 分钟，则该次推演满足目标。若进程第 4 分钟已启动、业务第 12 分钟才恢复，仍不满足 RTO。这里没有实际恢复计时。

恢复时间包括取回文件、校验、加载、追赶变化、切换连接与业务验收，不只是 Redis 启动耗时。副本提升可以缩短某些故障的停机，但不能替代历史备份；复制会传播误操作，多个实例也可能共享同一个故障域。

持久化与副本确认的区别继续见 [第 21 章复制、WAIT 与 WAITAOF](/articles/redis-replication-psync.html)。

最终应留下可供重复验证的恢复记录，写清所用版本、文件、恢复边界、校验内容和耗时。
