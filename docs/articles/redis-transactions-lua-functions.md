---
id: redis-transactions-lua-functions
title: 第十八章 事务、WATCH、Lua 与 Functions
description: "Redis 提供事务队列、WATCH 和服务端脚本等组合操作方式。理解它们时，可以分别观察命令何时排队、何时执行、错误如何返回，以及并发条件如何检查。"
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
order: 18
---

# 第十八章 事务、WATCH、Lua 与 Functions

[返回本册目录](/collections/redis/)

Redis 提供事务队列、WATCH 和服务端脚本等组合操作方式。理解它们时，可以分别观察命令何时排队、何时执行、错误如何返回，以及并发条件如何检查。原子执行约束其他客户端命令的插入，自动回滚则是另一项需要单独确认的语义。

本章以 Redis Open Source 7.2.0 为基本参照，脚本缓存变化单独标注 7.4.0。这里的 Atomic Execution（原子执行）强调执行过程不被其他正常客户端命令穿插，并不自动包含“发生错误时撤销所有修改”。`redis` 代码块可在交互客户端中输入，`lua` 是脚本源码，`text` 是推演或占位模板。

![组合操作的选择](/assets/notes/redis/redis-study-transaction.svg)

## 1. MULTI 排队与 EXEC 连续执行 {#_1-multi-exec-实际保证什么}

MULTI 后的命令先进入事务队列；EXEC 让队列内命令连续执行。排队阶段发生语法或命令参数错误，Redis Open Source 2.6.5 起会拒绝执行该事务；但执行阶段发生类型错误，并不会撤销已经成功的命令，也不会阻止后续命令继续执行。[事务错误处理与历史版本](https://redis.io/docs/latest/develop/using-commands/transactions/)

| 情况                      | 发生阶段      | 结果                                      |
| ------------------------- | ------------- | ----------------------------------------- |
| 命令不存在、参数数量错误  | 排队阶段      | 2.6.5 起标记事务出错，EXEC 拒绝执行该队列 |
| WRONGTYPE（值类型不匹配） | EXEC 执行阶段 | 对应命令返回错误，其他命令继续            |
| WATCH 的键发生相关变化    | EXEC 检查时   | 整个事务队列不执行，返回空回复            |
| 网络断开                  | 通信阶段      | 客户端可能不知道 EXEC 是否已执行          |

QUEUED（已排队）只表示进入队列，不代表执行成功。正常执行的 EXEC 返回与排队顺序对应的结果数组，必须逐项检查；WATCH 冲突的空回复不是“成功的空数组”。Redis 不提供关系型数据库式的通用自动回滚。

以下仅用于隔离教学数据库，会修改示例键：

```redis
SET demo:tx:value text
MULTI
INCR demo:tx:count
LPUSH demo:tx:value item
SET demo:tx:finished yes
EXEC
```

中间 LPUSH 因键是 String 而失败时，其余命令仍按事务执行规则处理。客户端应逐项检查 EXEC 返回数组，分别确定计数与最后一条 SET 的结果。DISCARD 用于放弃尚未执行的队列，不是撤销已经提交的写入。

预期推演：若示例计数键原先不存在，没有并发修改、权限或资源错误，EXEC 的三个位置依次是整数 1、WRONGTYPE 错误、OK；计数键为 1，finished 键为 yes。若计数键已有值，第一项不能继续写死为 1；若它不是可递增的整数，也会单独报错。

## 2. WATCH 是乐观并发控制

Optimistic Concurrency Control（乐观并发控制）先假定冲突不频繁，不在读取时锁住所有操作，而在提交时检查数据是否已变化。

典型流程是在同一连接上 WATCH 键，读取旧值，在应用中计算，再 MULTI/EXEC 提交。被监视的键发生相关变化时，EXEC 可以不执行队列；客户端需要识别冲突并有界重试，而不是把空结果当作业务成功。

WATCH 的正确性不能在任意借还连接的过程中得到保证，因为监视状态属于连接；发生网络故障时，还需要另外判断“提交是否成功”。版本边界也应明确：从 Redis 6.0.9 起，被监视键过期会使事务中止；在此之前，过期本身不会触发这一结果。不能用现行行为反推早期版本。[WATCH 的过期版本注记](https://redis.io/docs/latest/develop/using-commands/transactions/)

以下是双客户端教学推演，未运行，要求没有其他并发修改。先初始化：

```redis
SET demo:balance 100
```

客户端 A 用同一条连接依次执行：

```redis
WATCH demo:balance
GET demo:balance
```

此时 A 预期读到 `100`，计划扣减 20。提交前，客户端 B 执行：

```redis
SET demo:balance 120
```

A 再在原连接上执行：

```redis
MULTI
SET demo:balance 80
EXEC
```

预期 SET 得到 QUEUED，但 EXEC 因 B 的修改而中止，最终余额仍为 `120`。A 应重新 WATCH、读取、计算，再有界重试，不能直接重发旧值 `80`。WATCH 必须在 MULTI 之前；EXEC 无论执行还是因冲突中止都会清理监视，DISCARD 也清理事务及监视，UNWATCH 可显式取消监视。连接关闭同样不会保留旧监视状态。[WATCH 生命周期](https://redis.io/docs/latest/develop/using-commands/transactions/)

如果 GET 后只想增加一个整数，直接使用 INCR 通常比自己实现 WATCH 循环简单。只有确实需要读—判断—写时，再引入协调机制。单命令基础见 [第 3 章 String 与计数](/articles/redis-strings.html)。

## 3. Lua 把判断移近数据

Lua 是 Redis 内嵌的脚本语言；EVAL 自 Redis Open Source 2.6.0 提供，让读取、条件判断和更新在服务端一次调用中完成。脚本执行期间，其他正常客户端命令不能插入，客户端也不能把长脚本当成异步后台任务。[Lua 执行模型](https://redis.io/docs/latest/develop/programmability/eval-intro/) · [EVAL](https://redis.io/docs/latest/commands/eval/)

下面是新增的条件更新示例，不包含外部系统副作用：

```lua
-- KEYS[1]: 示例键；ARGV[1]: 预期值；ARGV[2]: 新值
local current = redis.call('GET', KEYS[1])
if current ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2])
return 1
```

对应的完整 Redis 调用示例。先把隔离教学实例中的键设为 old，再按顺序调用：

```redis
SET demo:cas old
EVAL "local current = redis.call('GET', KEYS[1]); if current ~= ARGV[1] then return 0 end; redis.call('SET', KEYS[1], ARGV[2]); return 1" 1 demo:cas old new
GET demo:cas
```

EVAL 脚本后的 `1` 是键数量，demo:cas 对应 KEYS[1]，old/new 对应 ARGV[1]/ARGV[2]。没有其他写入时，预期依次得到 OK、整数 `1`、字符串 `new`；再用同样 old 条件调用会返回 `0`。CAS（Compare-and-Set，比较后设置）在这里比较的是值，不会检测值曾经改变又恢复的历史。

脚本中的 SET 会采用普通 SET 的 TTL（Time to Live，生存时间）语义，成功覆盖会清除旧期限；若业务需要保留 TTL，可按 Redis Open Source 6.0.0 起的 KEEPTTL 支持另行设计。不要把示例误读成任意对象的通用更新协议。

键名通过 KEYS 声明，参数通过 ARGV 传入；不要动态拼接脚本文本。Redis Cluster（集群）仍有键访问和同槽约束。脚本运行中出现错误，也不自动撤销之前的写操作，因此应尽量在写入前完成校验。

| Lua 接口    | Redis 命令错误如何处理                            |
| ----------- | ------------------------------------------------- |
| redis.call  | 抛出 Lua 错误，未捕获时结束脚本并向客户端返回错误 |
| redis.pcall | 将错误作为带 err 字段的对象返回，供脚本判断       |

pcall 是错误捕获，不是自动回滚；此前的写入不会因此撤销。应尽量先完成参数、类型和业务条件校验，再执行写入。[Lua 错误接口](https://redis.io/docs/latest/develop/programmability/lua-api/)

脚本应该短小、有界，不能用长循环代替后台任务。`SCRIPT KILL` 只适用于尚未执行写操作的相关运行中脚本；已经写入后不能依靠它安全回滚。[SCRIPT KILL 的限制](https://redis.io/docs/latest/commands/script-kill/)

在 Redis Open Source 7.0.0 和 7.2.0 中，`busy-reply-threshold` 使用毫秒配置长脚本进入忙状态的阈值，旧名 `lua-time-limit` 保留为别名；7.2.0 默认值为 5000 ms。它不是到时自动终止脚本：达到阈值后，服务端可处理受限的管理请求，其他正常命令可能收到 BUSY（忙碌错误）。SCRIPT KILL 也不能撤销写入。脚本不能用等待外部服务或长循环实现后台任务。[7.0.0 配置定义](https://raw.githubusercontent.com/redis/redis/7.0.0/src/config.c) · [7.2.0 长脚本配置说明](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

## 4. 脚本缓存与 Functions 的区别

`SCRIPT LOAD` 的参数是脚本文本，不是服务器上的文件路径。`EVALSHA` 调用缓存标识时要处理 NOSCRIPT；重启、故障切换和缓存管理都可能要求重新加载。脚本缓存不能当成可靠的软件部署仓库。

SCRIPT LOAD 返回 SHA1（Secure Hash Algorithm 1，安全散列算法 1）摘要，用作脚本标识。可以按以下流程理解，摘要需使用实际加载返回值，不能直接输入占位符：

```text
应用启动 → SCRIPT LOAD 脚本文本 → 得到 SHA1 → EVALSHA SHA1 键数量 键和参数
                                               ├─ 成功：处理结果
                                               └─ NOSCRIPT：重新加载，再有界调用
```

NOSCRIPT 明确表示目标节点没有该缓存脚本，这次脚本没有执行；断网后的未知结果不是 NOSCRIPT。重新加载也要确保使用正确的脚本文本，不能把缓存缺失和业务错误混为一谈。

从 Redis Open Source 7.4.0 起，通过 EVAL / EVAL_RO 引入的缓存脚本会按 LRU（Least Recently Used，最近最少使用）机制淘汰；这不等于所有脚本入口都采用同一种淘汰规则。通过 SCRIPT LOAD 显式载入的脚本不属于这条 LRU 路径，但 SCRIPT FLUSH、重启、目标节点切换等仍需单独处理。[EVAL 缓存版本说明](https://redis.io/docs/latest/commands/eval/) · [SCRIPT LOAD](https://redis.io/docs/latest/commands/script-load/) · [7.4.0 缓存实现](https://raw.githubusercontent.com/redis/redis/7.4.0/src/eval.c)

如果 EVALSHA 位于 Pipeline 中，收到 NOSCRIPT 时，其后的其他命令可能已经执行，不能简单地插入一次加载再重发整个批次。应事先明确加载与调用顺序、逐项检查结果，并区分“已明确失败的脚本调用”和“断连后结果未知的写操作”；后者需要业务幂等，而不是无条件重试。

Redis Open Source 7.0.0 引入 Functions（服务端函数），将函数组织成库，通过 FUNCTION LOAD 和 FCALL 等管理调用。函数库可以随数据持久化、向副本复制，但仍受持久化与复制边界约束；在 Redis Cluster（集群）中也要覆盖相应主节点的部署与版本一致性。Functions 不是任意语言线程池，更不会把跨数据库业务操作变成分布式事务。[Functions 官方说明](https://redis.io/docs/latest/develop/programmability/functions-intro/)

例如定义一个把指定键递增的函数库，以下是 Lua 源码，不是单独输入的 Redis 命令：

```lua
#!lua name=demo_review
redis.register_function('demo_incr', function(keys, args)
    return redis.call('INCR', keys[1])
end)
```

下面是加载同一函数并调用的完整 Redis 命令示例。要求 Redis Open Source 7.0.0 或更高版本的隔离实例中没有同名库及函数；示例会设置计数键：

```redis
FUNCTION LOAD "#!lua name=demo_review\nredis.register_function('demo_incr', function(keys, args) return redis.call('INCR', keys[1]) end)"
SET demo:function:count 0
FCALL demo_incr 1 demo:function:count
GET demo:function:count
```

redis-cli 的双引号参数把 `\n` 解释为真实换行；通过客户端 API（Application Programming Interface，应用程序编程接口）调用时应传入包含真实换行的源码。`#!lua` 指定执行引擎，name 指定库名，FCALL 的 `1` 表示随后一个键。预期返回库名 demo_review、OK、整数 `1`、字符串 `1`。默认 FUNCTION LOAD 不覆盖同名库；变更库需按部署方案处理。[FUNCTION LOAD](https://redis.io/docs/latest/commands/function-load/)

FCALL 可调用允许写入的函数；FCALL_RO 只接受声明 `no-writes` 且不执行写命令的只读函数，本例会写入，不能改用 FCALL_RO。函数需要显式接收它访问的键，Cluster 多键访问仍受同槽约束；函数库持久化和副本恢复取决于实际配置、复制进度及故障状态，并非加载后天然永久存在。[函数标志与部署](https://redis.io/docs/latest/develop/programmability/functions-intro/) · [FCALL_RO](https://redis.io/docs/latest/commands/fcall_ro/)

| 需求                     | 优先考虑           | 组合逻辑在哪里执行         |
| ------------------------ | ------------------ | -------------------------- |
| 简单整数自增             | INCR               | 单条命令已经满足           |
| 多条已确定命令连续执行   | MULTI/EXEC         | 客户端提前准备队列         |
| 客户端读取后判断更新     | WATCH + MULTI/EXEC | 客户端判断，提交时检测冲突 |
| 根据读取结果决定后续写入 | Lua                | 服务端完成判断和更新       |
| 长期部署复用的服务端逻辑 | Functions          | Redis 管理函数库           |

选择差异不只是性能，更在于谁执行判断、如何管理代码及失败结果。

选择时，可以先判断单命令是否足够，再考虑是否需要 WATCH；若需要在数据附近执行有限的判断逻辑，可考虑 Lua 或 Functions。无论选择哪种方式，都仍需单独处理未知结果、重试上限和外部业务幂等。

| 概念                    | 需要单独判断的问题                             |
| ----------------------- | ---------------------------------------------- |
| 原子执行                | 这段执行能否被其他正常客户端命令插入           |
| Isolation（并发隔离）   | 其他客户端能否观察到执行中的中间状态           |
| Rollback（自动回滚）    | 错误后是否撤销已经发生的修改；这里没有通用保证 |
| Durability（持久性）    | 故障后已执行写入能否恢复                       |
| Idempotency（业务幂等） | 重试是否重复产生业务副作用                     |

MULTI/EXEC 的连续执行与 Lua/Functions 的不被插入执行，都不提供通用自动回滚。故障恢复取决于持久化和复制配置，见 [第 19 章 RDB/AOF](/articles/redis-rdb-aof.html)；RDB（Redis Database，数据库快照）与 AOF（Append Only File，只追加文件）也不能替代外部数据库事务。跨系统副作用及重试仍需设计，见 [第 28 章锁、条件更新与幂等](/articles/redis-locks-rate-limits.html)。
