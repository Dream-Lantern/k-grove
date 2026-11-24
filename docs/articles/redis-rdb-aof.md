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

RDB（Redis Database，数据库快照）直接存某个时刻的整份数据，加载文件就能恢复；AOF（Append Only File，只追加文件）存的是“改过哪些数据”的命令流水，恢复时要把这些命令按顺序重放一遍。本章以 Redis Open Source 7.2.0 为参照，多部分 AOF 自 7.0.0 提供。命令和时间线均为教学说明。

![RDB 与 AOF 的侧重点](/assets/notes/redis/redis-study-persistence.svg)

## 1. RDB：某个时间点的数据快照

RDB 保存数据集的快照。恢复时不必逐条重放全部历史命令，加载文件即可得到那一刻的数据；每份文件对应一个时点，因此适合按恢复点留存。代价是两次成功快照之间的变化，可能没有可恢复记录。

SAVE 在主执行路径同步生成快照，可能长时间阻塞请求。BGSAVE 通常通过 fork 后由子进程工作，但 fork 本身仍可能造成暂停，后台写盘也会与业务争用资源。“后台”只说明执行位置不同，资源争用仍然存在。

定时 save 条件不是“每个键都按时备份”的承诺。条件是否满足、后台任务是否成功、磁盘是否有空间，都影响实际恢复点。验收时应看成功完成时间和业务可接受的数据损失窗口，配置文本只是起点。

BGSAVE 成功完成说明生成了一份可用快照，其数据时点通常对应更早的 fork（创建子进程）时刻，文件写完时已经是更晚的时间。子进程生成快照时，父进程可以继续处理写入，这些后续变化不在该快照内。fork 和 COW（Copy-on-Write，写时复制）的资源成本见 [第 20 章](/articles/redis-fork-copy-on-write.html)。

## 2. AOF：记录适用写入并选择刷盘策略

AOF 按顺序追加每条改动数据的命令，恢复时重放这些命令。但“把内容交给操作系统”和“内容真正写进磁盘”是两个时刻：交出去只是进了内核的写缓冲，断电仍可能丢；只有 fsync（文件同步系统调用）才要求内核把它写到存储上。`appendfsync always`、`everysec`、`no` 就是在这两步之间选不同的等待时机。

一条写入要经过几段：先在内存里执行，再进入 Redis 的 AOF 缓冲，然后交给操作系统的缓冲，最后 fsync 把它写到存储上。客户端拿到回复，可能发生在 fsync 之前，也可能在之后，取决于策略。7.2.0 的 always 路径在发送相应回复前同步，everysec 通常不等待本次后台 fsync 完成才回复。

everysec 常被概括为通常约一秒的数据风险窗口，但其范围取决于故障类型、存储设备和系统停顿。要结合 fsync 延迟、磁盘可靠性、重写期间配置与故障模型判断。操作系统或硬件不兑现持久写入保证时，配置名补不上这一层能力。

AOF 重写不看旧日志里写过什么，而是照着内存里的当前数据重新写一份更短的日志，和逐行删除“重复命令”不是一回事。比如同一个键被反复 INCR，重写后只留一条表示当前值的写入，而不是把每次 INCR 都保留；重写与业务并发期间，还必须保存新的变化。[持久化机制与策略](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/)

用同一故障场景比较，以下时刻、命令和结果均是假设：

```text
12:00:00  BGSAVE 成功，留下一份可用快照
12:00:10  SET order:1 paid
12:00:20  SET order:2 paid
12:00:25  Redis 所在机器故障
```

| 配置         | 可能的恢复结果                                                       |
| ------------ | -------------------------------------------------------------------- |
| 仅 RDB       | 回到这份成功快照的数据时点，两条后续 SET 都可能缺失                  |
| AOF everysec | 通常保留更多近期写入，但取决于实际完成的同步，丢失上限随同步情况变化 |
| AOF always   | 对已确认写入提供更强的同步保证，仍受设备与故障模型影响               |
| RDB + AOF    | 7.2.0 正常启动配置下优先按有效 AOF 文件集合恢复                      |

表中的“12:00 快照”只是文件标记，实际数据截点还应追溯那次 fork；成功完成时间说明不了它包含哪些写入。若日志和快照都在损坏磁盘上，也可能都不可用。everysec 的丢失上限并不固定为一秒，原因包括同步延迟、系统停顿及 `no-appendfsync-on-rewrite` 等配置条件。[7.2.0 AOF 写入与同步](https://raw.githubusercontent.com/redis/redis/7.2.0/src/aof.c) · [7.2.0 刷盘配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

## 3. Redis 7.0+ 的 BASE、INCR 与 Manifest {#_3-redis-7-0-不要只找一个-appendonly-aof}

![多部分 AOF 的文件关系](/assets/notes/redis/redis-study-multipart-aof.svg)

Redis Open Source 7.0.0 起的 AOF 不再是一个大文件，而是一套文件：BASE（基础文件）装某一时刻的完整数据，INCR（Incremental，增量文件）装此后新追加的写入，Manifest（文件清单）写明这一套里有哪些 BASE 和 INCR、按什么顺序加载。图中连线表示文件集关系，Manifest 只记录清单，不参与数据重放。基础文件可能采用 RDB 格式；新写入进入相应增量文件。

对已经启用 AOF 的 7.2.0 实例，重写可以按下面的高层流程理解；以下只列高层步骤，与完整源码时序、旧版单文件 AOF 的拼接流程都不同：

```text
触发重写 → 刷出当前 AOF 缓冲，打开新 INCR 并更新有效清单
         → fork
           ├─ 父进程：继续服务，将后续写入追加到新 INCR
           └─ 子进程：按 fork 时的状态生成临时 BASE
         → 子进程成功后，父进程确认并整理新文件集合
         → 持久化并原子替换 Manifest，启用新 BASE + 保留的新 INCR
         → 将不再需要的旧文件交给历史清理流程
```

重写期间的变化已经进入新 INCR，不需要在结束时把它们重新逐条拼到 BASE。7.2.0 源码在 fork 之前打开新增量文件，旧版“父进程仅积累内存重写缓冲，最后追加到单文件”的描述不适用于此。重写失败时，旧 BASE、仍有效的旧 INCR 与新增 INCR 仍用于完整重建，手工删除旧文件会破坏这条路径；首次启用 AOF 的过渡路径还另有状态处理。[多部分 AOF 机制](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) · [7.2.0 重写及清单切换实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/aof.c)

备份多部分 AOF 时，需要保存相互匹配的基础文件、增量文件和 manifest。重写期间文件集合仍可能变化，取回后应核对其完整性与对应关系。

## 4. 故障后确定加载源并校验恢复集合 {#_4-故障后-先保存现场再谈修复}

先确认启动配置实际启用了什么。正常配置下同时启用 AOF 与 RDB，重启使用 AOF 重建数据；目录中存在 dump.rdb 只说明文件还在，本次从哪个文件恢复要看启动配置与日志。AOF 损坏时，平台并不会自动挑选旧 RDB 作为无损回退。[AOF 与 RDB 的启动关系](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/#interactions-between-aof-and-rdb-persistence)

以下是适用于 Redis Open Source 7.2.0、有相应查询权限时的只读 Redis 命令示例。实例已停机时应从保存的配置和日志确认，查询要以只读方式进行，不要把唯一现场反复启动：

```redis
# 读取配置 appendonly：是否启用 AOF 持久化；GET 只查询，不修改配置
CONFIG GET appendonly
# 读取配置 appendfsync：AOF 的磁盘同步策略；GET 只查询，不修改配置
CONFIG GET appendfsync
# 读取配置 appenddirname：多部分 AOF 所在目录名；GET 只查询，不修改配置
CONFIG GET appenddirname
# 读取配置 dir：持久化文件使用的工作目录；GET 只查询，不修改配置
CONFIG GET dir
# 查询 RDB/AOF 状态、后台任务及最近持久化结果；persistence 是 INFO 的信息分区名，不是键名
INFO persistence
# 查询最近一次成功保存 RDB 的 Unix 时间戳，单位秒；无额外参数
LASTSAVE
```

| 检查项                    | 归属与用途，Redis Open Source 7.2.0                    |
| ------------------------- | ------------------------------------------------------ |
| appendonly                | 配置：是否启用 AOF                                     |
| appendfsync               | 配置：always、everysec 或 no                           |
| appenddirname、dir        | 配置：多部分 AOF 子目录及工作目录，共同定位文件        |
| rdb_last_bgsave_status    | INFO persistence：最近后台快照结果                     |
| aof_last_write_status     | INFO persistence：最近 AOF 写入状态                    |
| aof_last_bgrewrite_status | INFO persistence：最近后台 AOF 重写结果                |
| aof_rewrite_in_progress   | INFO persistence：当前是否正在重写                     |
| LASTSAVE                  | 返回上次成功保存的 Unix 秒时间戳，与文件完整性是两回事 |

appenddirname 属于 7.0.0 起的多部分 AOF 配置；其余状态也要结合多个字段判断，例如 AOF 未启用时，默认状态说明不了是否存在可恢复日志。[7.2.0 配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf) · [7.2.0 INFO 字段实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/server.c) · [LASTSAVE](https://redis.io/docs/latest/commands/lastsave/)

| 恢复材料        | 必须记录的加载依据                        |
| --------------- | ----------------------------------------- |
| 独立 RDB        | 实际启动配置、目标文件、版本和快照恢复点  |
| 历史单文件 AOF  | 对应版本、启用配置及日志完整性            |
| 7.0+ 多部分 AOF | 有效 manifest 与对应 BASE/INCR 的完整集合 |

AOF 尾部未完整写入与中间出现非法内容属于不同故障，是否允许加载截断尾部还受配置影响。检查实际启动日志和加载源；删除文件猜不出优先级，重写 BASE 的 RDB 格式也与独立 dump.rdb 是两回事。

| 故障                           | 风险与检查边界                                                                         |
| ------------------------------ | -------------------------------------------------------------------------------------- |
| 最后一个 AOF 文件尾部不完整    | 7.2.0 的 aof-load-truncated 可允许加载到最后完整记录并处理截断尾部；丢失的尾部仍需评估 |
| AOF 中间损坏，或非末尾文件截断 | 与普通尾部不完整不同；修复可能舍弃损坏位置之后的数据                                   |
| Manifest 丢失或不匹配          | 有效 BASE/INCR 需核对完整备份集合后确定，猜测拼接会得到不一致的数据                    |
| 磁盘损坏                       | 本地材料可能不可用，需要独立备份或其他恢复来源                                         |

`redis-check-aof` 用于检查 AOF，修复模式可能改写或截断文件；检查应在文件副本上进行，`--fix` 需单独确认，并核对目标版本对单文件和 Manifest 的输入要求。`aof-load-truncated` 只处理尾部截断，格式损坏与业务验收都要另行处理。[AOF 截断与损坏处理](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/) · [7.2.0 加载边界](https://raw.githubusercontent.com/redis/redis/7.2.0/src/aof.c)

加载失败时，应先保存原文件、日志、版本、配置与校验结果，避免反复启动或覆盖唯一副本。检查文件应使用匹配版本的工具，并在副本上操作。若修复可能截断数据，必须先明确损失范围；repair 模式会改动文件内容，无损修复要另找途径。

```text
确认版本 → 检查启动配置 → 由日志确认实际加载源和失败位置
         → 核对文件清单，保存原始文件、配置和日志
         → 在隔离文件副本上检查完整性 → 隔离恢复 → 校验业务数据
```

这里只做只读盘点和静态流程整理；修复、重写和恢复验证需要另行按维护方案执行。

恢复目标不止于“Redis 能启动”。还要核对关键键、类型、TTL（Time to Live，生存时间）、应用不变量、必要函数库或扩展，以及恢复后客户端是否误连了旧实例。恢复数据库应与生产写入隔离，防止验证过程中接收真实流量。

| 恢复后检查                          | 应确认什么                                         |
| ----------------------------------- | -------------------------------------------------- |
| 键数量和类型                        | 与预期恢复点比较，数量相同只是第一层，内容还需核对 |
| 核心业务键值                        | 订单、去重状态等是否满足业务不变量                 |
| TTL                                 | 截止时间是否合理，是否误恢复成永久键               |
| Redis Functions（服务端函数）和模块 | 函数库及所需扩展是否可用、版本匹配                 |
| 持久化与复制状态                    | 当前策略、错误、角色和追赶进度是否符合方案         |
| 客户端连接目标                      | 路由及连接池是否指向已验收实例                     |

本章不提供默认执行的修复或重写命令。`CONFIG SET dir` 等路径配置在现代版本中受保护，旧教程的随时可改并不成立。[Redis 7.2.0 配置源码](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

## 5. 把 RPO、RTO 写进方案

RPO（Recovery Point Objective，恢复点目标）表示最多可接受丢失多少时间范围的数据；RTO（Recovery Time Objective，恢复时间目标）表示最多可接受多长时间恢复服务。例如“允许丢失可重建的十分钟缓存”和“订单去重状态不能随意丢失”，需要完全不同的策略。

独立假设案例：业务要求 RPO=5 分钟、RTO=10 分钟。故障在 12:00，最后可用数据截点为 11:57，损失窗口为 3 分钟；若取回备份、检查、加载、业务验证和客户端切换共用 9 分钟，则该次推演满足目标。若进程第 4 分钟已启动、业务第 12 分钟才恢复，仍不满足 RTO。这里没有实际恢复计时。

恢复时间包括取回文件、校验、加载、追赶变化、切换连接与业务验收，不只是 Redis 启动耗时。副本提升可以缩短某些故障的停机，历史备份仍需单独保留；复制会把误删除、误覆盖原样带到副本上，而多台实例往往在同一台机器、同一个机柜或同一块存储上，一次故障会同时带走它们，这就是共享故障域。

持久化与副本确认的区别继续见 [第 21 章复制、WAIT 与 WAITAOF](/articles/redis-replication-psync.html)。

最终应留下可供重复验证的恢复记录，写清所用版本、文件、恢复边界、校验内容和耗时。
