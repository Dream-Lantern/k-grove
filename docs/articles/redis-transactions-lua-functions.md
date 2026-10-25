---
id: redis-transactions-lua-functions
title: 第十八章 事务、WATCH、Lua 与 Functions
description: 返回本册目录
date: '2026-10-25'
updated: '2026-10-25'
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

Redis 中的原子执行，通常指一段命令执行期间不会插入其他客户端的命令，并不等于关系数据库式的自动回滚。原笔记中“全部成功或全部失败”的说法需要分情况理解，否则容易据此写出错误的补偿逻辑。

![组合操作的选择](/assets/notes/redis/redis-study-transaction.svg)

## 1. MULTI / EXEC 实际保证什么

MULTI 后的命令先进入事务队列；EXEC 让队列内命令连续执行。排队阶段发生语法或命令参数错误，现代版本会拒绝执行该事务；但执行阶段发生类型错误，并不会撤销已经成功的命令，也不会阻止后续命令继续执行。[事务错误处理](https://redis.io/docs/latest/develop/using-commands/transactions/)

以下仅用于隔离教学数据库，会修改示例键：

```redis
SET demo:tx:value text
MULTI
INCR demo:tx:count
LPUSH demo:tx:value item
SET demo:tx:finished yes
EXEC
```

中间 LPUSH 会因为键是 String 而失败，但不能因此断言计数没有增加、最后一条 SET 没有执行。客户端必须逐项检查 EXEC 返回的数组。DISCARD 用于放弃尚未执行的队列，不是撤销已经提交的写入。

预期推演：若示例计数键原先不存在，没有并发修改、权限或资源错误，EXEC 的三个位置依次是整数 1、WRONGTYPE 错误、OK；计数键为 1，finished 键为 yes。若计数键已有值，第一项不能继续写死为 1；若它不是可递增的整数，也会单独报错。这里解释的是事务逐项执行语义，不是本机实测输出。

## 2. WATCH 是乐观并发控制

典型流程是在同一连接上 WATCH 键，读取旧值，在应用中计算，再 MULTI/EXEC 提交。被监视的键发生相关变化时，EXEC 可以不执行队列；客户端需要识别冲突并有界重试，而不是把空结果当作业务成功。

WATCH 的正确性不能在任意借还连接的过程中得到保证，因为监视状态属于连接；发生网络故障时，还需要另外判断“提交是否成功”。版本边界也应明确：从 Redis 6.0.9 起，被监视键过期会使事务中止；在此之前，过期本身不会触发这一结果。不能用现行行为反推早期版本。[WATCH 的过期版本注记](https://redis.io/docs/latest/develop/using-commands/transactions/)

如果 GET 后只想增加一个整数，直接使用 INCR 通常比自己实现 WATCH 循环简单。只有确实需要读—判断—写时，再引入协调机制。

## 3. Lua 把判断移近数据

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

脚本中的 SET 会采用普通 SET 的 TTL 语义；若业务需要保留 TTL，应另外设计并核对所用版本。不要把示例误读成任意对象的通用更新协议。

键名通过 KEYS 声明，参数通过 ARGV 传入；不要动态拼接脚本文本。Cluster 仍有键访问和同槽约束。脚本运行中出现错误，也不自动撤销之前的写操作，因此应尽量在写入前完成校验。

脚本应该短小、有界，不能用长循环代替后台任务。`SCRIPT KILL` 只适用于尚未执行写操作的相关运行中脚本；已经写入后不能依靠它安全回滚。[SCRIPT KILL 的限制](https://redis.io/docs/latest/commands/script-kill/)

## 4. 脚本缓存与 Functions 的区别

`SCRIPT LOAD` 的参数是脚本文本，不是服务器上的文件路径。`EVALSHA` 调用缓存标识时要处理 NOSCRIPT；重启、故障切换和缓存管理都可能要求重新加载。脚本缓存不能当成可靠的软件部署仓库。

从 Redis 7.4 起，通过 EVAL / EVAL_RO 引入的缓存脚本会按适用的 LRU 机制淘汰；这不等于所有脚本入口都采用同一种淘汰规则。通过 SCRIPT LOAD 显式载入的脚本不属于这条 LRU 路径，但 SCRIPT FLUSH、重启、目标节点切换等仍需单独处理。[EVAL 缓存版本说明](https://redis.io/docs/latest/commands/eval/) · [SCRIPT LOAD](https://redis.io/docs/latest/commands/script-load/)

如果 EVALSHA 位于 Pipeline 中，收到 NOSCRIPT 时，其后的其他命令可能已经执行，不能简单地插入一次加载再重发整个批次。应事先明确加载与调用顺序、逐项检查结果，并区分“已明确失败的脚本调用”和“断连后结果未知的写操作”；后者需要业务幂等，而不是无条件重试。

Redis 7.0 引入 Functions，将函数组织成库，通过 FUNCTION LOAD 和 FCALL 等管理调用。函数库可以随数据持久化、向副本复制，但仍受持久化与复制边界约束；在 Cluster 中也要覆盖相应主节点的部署与版本一致性。Functions 不是任意语言线程池，更不会把跨数据库业务操作变成分布式事务。[Functions 官方说明](https://redis.io/docs/latest/develop/programmability/functions-intro/)

选择时，可以先判断单命令是否足够，再考虑是否需要 WATCH；若需要在数据附近执行有限的判断逻辑，可考虑 Lua 或 Functions。无论选择哪种方式，都仍需单独处理未知结果、重试上限和外部业务幂等。
