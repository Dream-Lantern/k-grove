---
id: redis-strings
title: 第三章 String、计数与原子过期
description: "String 保存字节序列，可以是文本、序列化对象、整数表示或二进制。Redis 不会因为里面看起来是 JSON，就自动知道其字段结构；修改其中一个属性可能仍需要整体读写。"
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
order: 3
---

# 第三章 String、计数与原子过期

String（字符串）保存字节序列，可以是文本、序列化对象、整数表示或二进制。Redis 不会因为里面看起来是 JSON（JavaScript Object Notation，JavaScript 对象表示法），就自动知道其字段结构；修改其中一个属性可能仍需要整体读写。

本章的原子性（Atomicity）指一次操作执行时，其他客户端命令不能插入其执行过程、看到中间状态；它不等于数据已经落盘。单条 Redis 命令的原子性，也不意味着连续发送多条命令就自动组成一个原子操作。

## 1. SET 与 GET 的基本语义

本章 `redis` 代码块是可在 `redis-cli` 交互环境输入的 Redis 命令，不是 Shell 命令或客户端 API（Application Programming Interface，应用程序编程接口）。以下按 Redis Open Source 7.2.0 语义教学，假定示例键起初不存在、无其他客户端修改，且在过期前完成读取。`text` 代码块是预期返回示意。

```redis
SET demo:profile:42 "{\"name\":\"Lin\"}" EX 120
GET demo:profile:42
SET demo:token:42 temporary-value NX EX 30
```

对应三条命令的预期返回，采用 `redis-cli` 风格展示：

```text
OK
"{\"name\":\"Lin\"}"
OK
```

EX 的单位是秒，PX 的单位是毫秒。NX 要求键不存在时才写入，XX 要求键存在时才写入。需要区分条件未满足时的返回结果和网络错误。

把写入和期限放在同一 SET 中，可以消除“先写入成功，来不及 EXPIRE 就崩溃”的窗口。分开两条命令放进 Pipeline 仍不等于获得同样的原子保证。[SET 的参数与返回](https://redis.io/docs/latest/commands/set/)

Pipeline（流水线）是客户端连续发送多条命令，不逐条等待回复，再批量读取结果的方式，可减少网络往返等待。服务端仍逐条执行，没有把这些命令包成不可分割的操作；其他客户端的命令可能穿插，连接中断也可能只执行了其中一部分。因此需要组合原子性时，不能只使用 Pipeline。[官方 Pipeline 说明](https://redis.io/docs/latest/develop/using-commands/pipelining/)

## 2. 覆盖写入、保留期限与读取续期 {#_2-覆盖值会怎样影响-ttl}

TTL（Time to Live，生存时间）表示距离过期还有多久。不带过期选项的普通 `SET` 成功覆盖后，会清除原 TTL，使键变成不过期；`SET ... EX/PX` 设置新期限，`SET ... KEEPTTL` 则保留原期限。条件不满足、没有写入时，不会因此清除 TTL。给一个不存在的键 EXPIRE，不会替你创建值。

普通 `SET` 还会覆盖已有的非 String 类型键，例如把 Hash 整体替换成 String，而不是返回 WRONGTYPE（类型不匹配错误）。但使用 `SET ... GET` 时，需要读取旧 String；若旧值不是 String，会返回类型错误并中止写入。[SET 行为](https://redis.io/docs/latest/commands/set/)

下列最低版本均指 Redis Open Source，已按固定版本的命令定义与官方版本记录核对：

| 能力              | 最低版本 | 用途                         |
| ----------------- | -------- | ---------------------------- |
| `SET ... KEEPTTL` | 6.0.0    | 覆盖值时保留原期限           |
| `SET ... GET`     | 6.2.0    | 设置新值并返回旧值           |
| `GETEX`           | 6.2.0    | 读取 String 并按选项修改期限 |

[7.2.0 SET 历史记录](https://raw.githubusercontent.com/redis/redis/7.2.0/src/commands/set.json) · [6.2.0 Release Notes](https://raw.githubusercontent.com/redis/redis/6.2.0/00-RELEASENOTES) · [GETEX 版本与语义](https://redis.io/docs/latest/commands/getex/)

GETSET 是历史常见读旧值再替换方式，符合版本要求时可用 `SET ... GET` 表达适用需求。GETEX 把读取与修改期限组合起来，因此它是可能改变状态的命令，不应当成普通 GET 的无副作用替代。

以下示例在过期前连续执行，预期最后的 `TTL` 返回 `-1`，表示键存在但没有过期时间：

```redis
SET demo:ttl-reset value EX 120
SET demo:ttl-reset replacement
TTL demo:ttl-reset
```

```text
OK
OK
(integer) -1
```

滑动过期会让热键长时间存活，是否符合隐私、库存或会话规则需要由业务决定，不能只因为访问频繁就不断延长。

## 3. 计数先用原生命令

```redis
INCR demo:counter
INCRBY demo:counter 5
DECRBY demo:counter 2
```

不存在的计数键从 0 开始参与运算；非整数内容、格式不合法或超出范围可能报错。Redis 的整数计数有范围，不能当作任意精度金额系统。

INCR 的单命令原子性，避免了先 GET、再在本地加一、最后 SET 所造成的典型丢更新问题，但无法解决“客户端不知道第一次是否成功，重试又加一次”的情况。后者仍需要业务事件标识与去重。

浮点命令也不应直接承担对精确十进制有严格要求的金额计算。可以按业务单位编码为整数，但仍需核对溢出、舍入与交易语义。

## 4. 固定时间窗计数的原子边界 {#_4-固定时间窗的计数不是两条命令随手拼}

限流常需要“窗口首次创建时设置期限，后续只增加计数”。若把 INCR 和 EXPIRE 分开，崩溃会留下无期限计数；每次都刷新过期又可能变成另一种窗口规则。

Redis Lua 服务端脚本是交给 Redis 内嵌 Lua 解释器执行的一段逻辑，可在服务器内完成判断与多步更新，避免其他客户端命令穿插。但脚本执行期间会阻塞其他命令，必须控制工作量，不能把长耗时任务直接搬进去。脚本的使用与错误边界见 [第 18 章：事务、Lua 与 Functions](/articles/redis-transactions-lua-functions.html)。[官方 Lua 说明](https://redis.io/docs/latest/develop/programmability/eval-intro/)

应先明确窗口规则，再选择单命令、Lua 或其他协调方式。[第 28 章：锁、限流与业务幂等](/articles/redis-locks-rate-limits.html) 会进一步讨论；本章只分析分开计数和设置期限的问题，SET NX 例子也不是完整的防刷方案。

## 5. MGET、MSET 与数据规模

MGET、MSET 减少了命令数量，但请求和回复仍有字节成本。MGET 涉及的键很多或值很大，依然可能造成排队与带宽压力。

MGET 有一个值得单独记住的返回例外：不存在的键、以及存在但不是 String 的键，都在对应结果位置返回 nil。GET 读取非 String 键时的 WRONGTYPE，不能原样套到 MGET。

下面三条命令假定 missing 键不存在；键名中的 `{42}` 是 Hash Tag（哈希标签），使这些键在 Cluster 中落到同一槽：

```redis
SET demo:{42}:name Lin
HSET demo:{42}:profile city Hangzhou
MGET demo:{42}:name demo:{42}:profile demo:{42}:missing
```

```text
OK
(integer) 1
1) "Lin"
2) (nil)
3) (nil)
```

后两个 nil 的原因不同。因此 nil 不足以证明键不存在，也可能提示键模型冲突。此处描述的是数据类型语义，不表示调用永远不报错；ACL（Access Control List，访问控制列表）、连接和 Cluster 约束仍可导致失败。[MGET 返回定义](https://redis.io/docs/latest/commands/mget/)

MSET 是单条原子命令：它设置的多个值不会被其他客户端看到只更新一部分的中间状态；把多个 SET 放入 Pipeline 没有这项组合保证。在 Redis Open Source 7.2.0 Cluster 中，MGET、MSET 的所有键必须位于同一哈希槽，否则会报 CROSSSLOT 错误。客户端把跨节点多个 GET 聚合成一个 API，不意味着服务端执行了一个跨槽原子 MGET。[MSET 原子性](https://redis.io/docs/latest/commands/mset/) · [Cluster 多键规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#implemented-subset)

Redis Open Source 7.2.0 默认限制单个 String 最大为 512 MB（512 × 1024 × 1024 字节），对应 `proto-max-bulk-len` 默认配置及 String 长度检查。实际业务不应按理论上限规划对象；大值会影响复制、持久化、网络和删除，应按延迟与资源预算控制尺寸。[7.2.0 配置默认值](https://raw.githubusercontent.com/redis/redis/7.2.0/src/config.c#L2943) · [String 长度检查](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_string.c#L37-L49)

## 6. 编码只作为诊断线索

String 紧凑编码的阈值属于版本实现细节。以 Redis Open Source 7.2.0 为参照，`createStringObject` 的 embstr（Embedded String，嵌入式字符串）创建阈值为 44 字节，长度小于等于该值走适用的紧凑创建路径；整数编码、更新和其他创建路径还需分别考虑。它不是业务协议，也不保证所有长度相同的值最终编码都一样。[Redis 7.2.0 对象实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/object.c)

先观察实际对象与读写模式，再决定是否压缩或拆分；压缩节省的内存还要付出 CPU、编解码和调试成本。

[返回本册目录](/collections/redis/)
