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

Redis 提供事务队列、WATCH 和服务端脚本这几种“把多条操作凑成一组”的方式。它们保证的东西不一样，看的时候要分别问：命令什么时候排队、什么时候真正执行、出错怎么返回、并发条件在哪里检查。其中“原子执行”只保证执行过程中插不进其他客户端的命令；至于出错后是否自动撤销已经写进去的修改，是另一回事，需要单独确认。

本章以 Redis Open Source 7.2.0 为基本参照，脚本缓存变化单独标注 7.4.0。这里的 Atomic Execution（原子执行）强调执行过程不被其他正常客户端命令穿插；“发生错误时撤销所有修改”属于另一层语义。`redis` 代码块可在交互客户端中输入，`lua` 是脚本源码，`text` 是推演或占位模板。

![组合操作的选择](/assets/notes/redis/redis-study-transaction.svg)

## 1. MULTI 排队与 EXEC 连续执行 {#_1-multi-exec-实际保证什么}

MULTI 后的命令先进入事务队列；EXEC 让队列内命令连续执行。排队阶段发生语法或命令参数错误，Redis Open Source 2.6.5 起会拒绝执行该事务；但执行阶段发生类型错误时，已成功的命令保留，后续命令继续执行。[事务错误处理与历史版本](https://redis.io/docs/latest/develop/using-commands/transactions/)

| 情况                      | 发生阶段      | 结果                                      |
| ------------------------- | ------------- | ----------------------------------------- |
| 命令不存在、参数数量错误  | 排队阶段      | 2.6.5 起标记事务出错，EXEC 拒绝执行该队列 |
| WRONGTYPE（值类型不匹配） | EXEC 执行阶段 | 对应命令返回错误，其他命令继续            |
| WATCH 的键发生相关变化    | EXEC 检查时   | 整个事务队列不执行，返回空回复            |
| 网络断开                  | 通信阶段      | 客户端可能不知道 EXEC 是否已执行          |

QUEUED（已排队）只表示进入队列，执行结果要看 EXEC 返回值。正常执行的 EXEC 返回与排队顺序对应的结果数组，必须逐项检查；WATCH 冲突返回的是空回复，与成功的空数组不同。Redis 不提供关系型数据库式的通用自动回滚。

以下仅用于隔离教学数据库，会修改示例键：

```redis
# 将字符串键 demo:tx:value 写为 text；键已存在时覆盖原值；普通 SET 会清除原有键 TTL
SET demo:tx:value text
# 开始当前连接的事务队列；无额外参数，后续命令先入队，等待 EXEC 执行
MULTI
# 将整数计数键 demo:tx:count 增加 1；键不存在从 0 开始，返回计算后的值
INCR demo:tx:count
# 将 item 插入 List demo:tx:value 左端；本例已将该键设为字符串，用于演示 EXEC 中的 WRONGTYPE 错误
LPUSH demo:tx:value item
# 将字符串键 demo:tx:finished 写为 yes；键已存在时覆盖原值；普通 SET 会清除原有键 TTL
SET demo:tx:finished yes
# 执行当前连接中已入队的事务命令；无额外参数，返回逐条结果；WATCH 冲突时返回空结果，执行期错误不会回滚其他命令
EXEC
```

中间 LPUSH 因键是 String 而失败时，其余命令仍按事务执行规则处理。客户端应逐项检查 EXEC 返回数组，分别确定计数与最后一条 SET 的结果。DISCARD 只放弃尚未执行的队列，已经提交的写入不受影响。

预期推演：若示例计数键原先不存在，没有并发修改、权限或资源错误，EXEC 的三个位置依次是整数 1、WRONGTYPE 错误、OK；计数键为 1，finished 键为 yes。若计数键已有值，第一项按实际计数变化；若它不是可递增的整数，也会单独报错。

## 2. WATCH 是乐观并发控制

Optimistic Concurrency Control（乐观并发控制）先假定冲突不频繁，不在读取时锁住所有操作，而在提交时检查数据是否已变化。

典型流程分三步：先在一条连接上 WATCH 要改的键，再读取旧值、在应用里算出新值，最后 MULTI/EXEC 提交；提交时如果这个键期间被别人改过，EXEC 就不执行队列。客户端要能识别这种冲突并有上限地重试，空结果表示冲突，要按业务失败处理。

WATCH 的监视状态属于连接，连接池借出再归还时，后续命令可能落到另一条连接上，监视随之失效；发生网络故障时，还需要另外判断“提交是否成功”。版本边界也应明确：从 Redis 6.0.9 起，被监视键过期会使事务中止；在此之前，过期本身不会触发这一结果。现行行为不能反推早期版本。[WATCH 的过期版本注记](https://redis.io/docs/latest/develop/using-commands/transactions/)

以下是双客户端教学推演，未运行，要求没有其他并发修改。先初始化：

```redis
# 将字符串键 demo:balance 写为 100；键已存在时覆盖原值；普通 SET 会清除原有键 TTL
SET demo:balance 100
```

客户端 A 用同一条连接依次执行：

```redis
# 监视键 demo:balance；若它在 EXEC 前被其他客户端修改，本次事务将放弃执行，须在同一连接操作
WATCH demo:balance
# 读取字符串键 demo:balance 的完整值；键不存在返回 nil，非字符串类型会报错
GET demo:balance
```

此时 A 预期读到 `100`，计划扣减 20。提交前，客户端 B 执行：

```redis
# 将字符串键 demo:balance 写为 120；键已存在时覆盖原值；普通 SET 会清除原有键 TTL
SET demo:balance 120
```

A 再在原连接上执行：

```redis
# 开始当前连接的事务队列；无额外参数，后续命令先入队，等待 EXEC 执行
MULTI
# 将字符串键 demo:balance 写为 80；键已存在时覆盖原值；普通 SET 会清除原有键 TTL
SET demo:balance 80
# 执行当前连接中已入队的事务命令；无额外参数，返回逐条结果；WATCH 冲突时返回空结果，执行期错误不会回滚其他命令
EXEC
```

预期 SET 得到 QUEUED，但 EXEC 因 B 的修改而中止，最终余额仍为 `120`。A 应重新 WATCH、读取、计算，再有界重试；直接重发旧值 `80` 会覆盖 B 的写入。WATCH 必须在 MULTI 之前；EXEC 无论执行还是因冲突中止都会清理监视，DISCARD 也清理事务及监视，UNWATCH 可显式取消监视。连接关闭同样不会保留旧监视状态。[WATCH 生命周期](https://redis.io/docs/latest/develop/using-commands/transactions/)

如果 GET 后只想增加一个整数，直接使用 INCR 通常比自己实现 WATCH 循环简单。只有确实需要读—判断—写时，再引入协调机制。单命令基础见 [第 3 章 String 与计数](/articles/redis-strings.html)。

## 3. Lua 把判断移近数据

Lua 是 Redis 内嵌的脚本语言；EVAL 自 Redis Open Source 2.6.0 提供，让读取、条件判断和更新在服务端一次调用中完成。脚本执行期间不会插入其他正常客户端命令，长脚本也在当前调用中同步执行完毕。[Lua 执行模型](https://redis.io/docs/latest/develop/programmability/eval-intro/) · [EVAL](https://redis.io/docs/latest/commands/eval/)

下面是新增的条件更新示例，不包含外部系统副作用：

```lua
-- KEYS[1]: 示例键；ARGV[1]: 预期值；ARGV[2]: 新值
-- GET 读取 KEYS[1] 指定键的值，与 ARGV[1] 比较；匹配后 SET 写入 ARGV[2]，清除原 TTL。
local current = redis.call('GET', KEYS[1])
if current ~= ARGV[1] then
    return 0
end
redis.call('SET', KEYS[1], ARGV[2])
return 1
```

对应的完整 Redis 调用示例。先把隔离教学实例中的键设为 old，再按顺序调用：

```redis
# 将字符串键 demo:cas 写为 old；键已存在时覆盖原值；普通 SET 会清除原有键 TTL
SET demo:cas old
# 执行引号中的 Lua 脚本；脚本后的 1 表示有 1 个键：demo:cas 传入 KEYS[1]
# old、new 分别传入 ARGV[1]、ARGV[2]；仅当旧值等于 old 时写入 new，返回 1 表示成功、0 表示不匹配
EVAL "local current = redis.call('GET', KEYS[1]); if current ~= ARGV[1] then return 0 end; redis.call('SET', KEYS[1], ARGV[2]); return 1" 1 demo:cas old new
# 读取字符串键 demo:cas 的完整值；键不存在返回 nil，非字符串类型会报错
GET demo:cas
```

EVAL 脚本后的 `1` 是键数量，demo:cas 对应 KEYS[1]，old/new 对应 ARGV[1]/ARGV[2]。没有其他写入时，预期依次得到 OK、整数 `1`、字符串 `new`；再用同样 old 条件调用会返回 `0`。CAS（Compare-and-Set，比较后设置）在这里比较的是当前值，值改变后又恢复的情况不会被发现。

脚本中的 SET 会采用普通 SET 的 TTL（Time to Live，生存时间）语义，成功覆盖会清除旧期限；若业务需要保留 TTL，可按 Redis Open Source 6.0.0 起的 KEEPTTL 支持另行设计。示例只针对一个键的字符串值，通用更新协议要另行设计。

键名通过 KEYS 声明，参数通过 ARGV 传入；脚本文本保持固定，变化的部分走参数。Redis Cluster（集群）里，脚本访问的键仍然要落在同一个哈希槽。脚本运行中出现错误，也不自动撤销之前的写操作，因此应尽量在写入前完成校验。

| Lua 接口    | Redis 命令错误如何处理                            |
| ----------- | ------------------------------------------------- |
| redis.call  | 抛出 Lua 错误，未捕获时结束脚本并向客户端返回错误 |
| redis.pcall | 将错误作为带 err 字段的对象返回，供脚本判断       |

pcall 只做错误捕获，此前的写入仍然保留。应尽量先完成参数、类型和业务条件校验，再执行写入。[Lua 错误接口](https://redis.io/docs/latest/develop/programmability/lua-api/)

脚本应该短小、有界，长循环不是后台任务的替代品。`SCRIPT KILL` 只适用于尚未执行写操作的相关运行中脚本；已经写入的脚本，`SCRIPT KILL` 回滚不了已生效的修改。[SCRIPT KILL 的限制](https://redis.io/docs/latest/commands/script-kill/)

在 Redis Open Source 7.0.0 和 7.2.0 中，`busy-reply-threshold` 使用毫秒配置长脚本进入忙状态的阈值，旧名 `lua-time-limit` 保留为别名；7.2.0 默认值为 5000 ms。阈值不是自动终止时间：达到阈值后，服务端可处理受限的管理请求，其他正常命令可能收到 BUSY（忙碌错误）。SCRIPT KILL 同样撤销不了写入。脚本不承担后台任务，等待外部服务或长循环都不适合放在这里。[7.0.0 配置定义](https://raw.githubusercontent.com/redis/redis/7.0.0/src/config.c) · [7.2.0 长脚本配置说明](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)

## 4. 脚本缓存与 Functions 的区别

`SCRIPT LOAD` 的参数是脚本文本，不是服务器上的文件路径。`EVALSHA` 调用缓存标识时要处理 NOSCRIPT；重启、故障切换和缓存管理都可能要求重新加载。脚本缓存只是运行时缓存，软件部署仍要靠版本化源码。

SCRIPT LOAD 返回 SHA1（Secure Hash Algorithm 1，安全散列算法 1）摘要，用作脚本标识。可以按以下流程理解，摘要需使用实际加载返回值，占位符只用于说明流程：

```text
应用启动 → SCRIPT LOAD 脚本文本 → 得到 SHA1 → EVALSHA SHA1 键数量 键和参数
                                               ├─ 成功：处理结果
                                               └─ NOSCRIPT：重新加载，再有界调用
```

NOSCRIPT 明确表示目标节点没有该缓存脚本，这次脚本没有执行；断网后的未知结果与 NOSCRIPT 不同。重新加载也要确保使用正确的脚本文本；缓存缺失与业务错误要分开处理。

从 Redis Open Source 7.4.0 起，通过 EVAL / EVAL_RO 引入的缓存脚本会按 LRU（Least Recently Used，最近最少使用）机制淘汰；其他脚本入口的淘汰规则可能不同。通过 SCRIPT LOAD 显式载入的脚本不属于这条 LRU 路径，但 SCRIPT FLUSH、重启、目标节点切换等仍需单独处理。[EVAL 缓存版本说明](https://redis.io/docs/latest/commands/eval/) · [SCRIPT LOAD](https://redis.io/docs/latest/commands/script-load/) · [7.4.0 缓存实现](https://raw.githubusercontent.com/redis/redis/7.4.0/src/eval.c)

如果 EVALSHA 位于 Pipeline 中，收到 NOSCRIPT 时，其后的其他命令可能已经执行，简单插入一次加载再重发整个批次会造成重复执行。应事先明确加载与调用顺序、逐项检查结果，并区分“已明确失败的脚本调用”和“断连后结果未知的写操作”；后者需要业务幂等，而不是无条件重试。

Redis Open Source 7.0.0 引入 Functions（服务端函数），将函数组织成库，通过 FUNCTION LOAD 和 FCALL 等管理调用。函数库可以随数据持久化、向副本复制，但仍受持久化与复制边界约束；在 Redis Cluster（集群）中也要覆盖相应主节点的部署与版本一致性。Functions 是存在 Redis 服务端的一组函数，由 FCALL 调用；它不是应用侧的线程池，也不会因为把代码搬进 Redis，就让跨数据库的业务操作变成分布式事务。[Functions 官方说明](https://redis.io/docs/latest/develop/programmability/functions-intro/)

例如定义一个把指定键递增的函数库，以下是 Lua 源码，不是单独输入的 Redis 命令：

```lua
#!lua name=demo_review
-- keys[1] 是 FCALL 传入的第一个键；INCR 将其整数值加 1，并返回新值。
redis.register_function('demo_incr', function(keys, args)
    return redis.call('INCR', keys[1])
end)
```

下面是加载同一函数并调用的完整 Redis 命令示例。要求 Redis Open Source 7.0.0 或更高版本的隔离实例中没有同名库及函数；示例会设置计数键：

```redis
# 加载 Lua 函数库；name=demo_review 指定库名，\n 分隔声明行与代码，demo_incr 是注册的函数名（Redis 7.0+）
FUNCTION LOAD "#!lua name=demo_review\nredis.register_function('demo_incr', function(keys, args) return redis.call('INCR', keys[1]) end)"
# 将字符串键 demo:function:count 写为 0；键已存在时覆盖原值；普通 SET 会清除原有键 TTL
SET demo:function:count 0
# 调用函数 demo_incr；1 表示后面有 1 个键，demo:function:count 传入 keys[1]，本例没有额外 args
FCALL demo_incr 1 demo:function:count
# 读取字符串键 demo:function:count 的完整值；键不存在返回 nil，非字符串类型会报错
GET demo:function:count
```

redis-cli 的双引号参数把 `\n` 解释为真实换行；通过客户端 API（Application Programming Interface，应用程序编程接口）调用时应传入包含真实换行的源码。`#!lua` 指定执行引擎，name 指定库名，FCALL 的 `1` 表示随后一个键。预期返回库名 demo_review、OK、整数 `1`、字符串 `1`。默认 FUNCTION LOAD 不覆盖同名库；变更库需按部署方案处理。[FUNCTION LOAD](https://redis.io/docs/latest/commands/function-load/)

FCALL 可调用允许写入的函数；FCALL_RO 只接受声明 `no-writes` 且不执行写命令的只读函数，本例会写入，FCALL_RO 不适用。函数需要显式接收它访问的键，Cluster 多键访问仍受同槽约束；函数库持久化和副本恢复取决于实际配置、复制进度及故障状态，加载成功只说明当前节点可用。[函数标志与部署](https://redis.io/docs/latest/develop/programmability/functions-intro/) · [FCALL_RO](https://redis.io/docs/latest/commands/fcall_ro/)

| 需求                     | 优先考虑           | 组合逻辑在哪里执行         |
| ------------------------ | ------------------ | -------------------------- |
| 简单整数自增             | INCR               | 单条命令已经满足           |
| 多条已确定命令连续执行   | MULTI/EXEC         | 客户端提前准备队列         |
| 客户端读取后判断更新     | WATCH + MULTI/EXEC | 客户端判断，提交时检测冲突 |
| 根据读取结果决定后续写入 | Lua                | 服务端完成判断和更新       |
| 长期部署复用的服务端逻辑 | Functions          | Redis 管理函数库           |

这几种方式的差别不在快慢，而在三件事：判断在哪一侧做（客户端还是服务端）、代码存在哪里（应用仓库还是 Redis 里）、失败后留下什么状态。

选择时，可以先判断单命令是否足够，再考虑是否需要 WATCH；若需要在数据附近执行有限的判断逻辑，可考虑 Lua 或 Functions。无论选择哪种方式，都仍需单独处理未知结果、重试上限和外部业务幂等。

| 概念                    | 需要单独判断的问题                             |
| ----------------------- | ---------------------------------------------- |
| 原子执行                | 这段执行能否被其他正常客户端命令插入           |
| Isolation（并发隔离）   | 其他客户端能否观察到执行中的中间状态           |
| Rollback（自动回滚）    | 错误后是否撤销已经发生的修改；需按具体机制确认 |
| Durability（持久性）    | 故障后已执行写入能否恢复                       |
| Idempotency（业务幂等） | 重试是否重复产生业务副作用                     |

MULTI/EXEC 的连续执行与 Lua/Functions 的不被插入执行，都不提供通用自动回滚。故障恢复取决于持久化和复制配置，见 [第 19 章 RDB/AOF](/articles/redis-rdb-aof.html)；RDB（Redis Database，数据库快照）与 AOF（Append Only File，只追加文件）承担的是持久化，外部数据库事务另有职责。跨系统副作用及重试仍需设计，见 [第 28 章锁、条件更新与幂等](/articles/redis-locks-rate-limits.html)。
