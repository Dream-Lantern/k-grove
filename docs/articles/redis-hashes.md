---
id: redis-hashes
title: 第四章 Hash、对象字段与字段过期
description: "Hash 在一个键下保存 field-value 映射，适合需要按字段读取、更新的对象。它不要求每个对象拥有完全相同的字段集合，但也不自动提供关系型数据库的约束和关联查询。"
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
order: 4
---

# 第四章 Hash、对象字段与字段过期

Hash 在一个键下保存 field-value 映射，适合需要按字段读取、更新的对象。它不要求每个对象拥有完全相同的字段集合，但也不自动提供关系型数据库的约束和关联查询。

![Hash 对象、字段与两层过期关系](/assets/notes/redis/redis-study-hash-model.svg)

## 1. 字段的读写与返回

新增示例，未运行：

```redis
HSET demo:user:42 name Lin level 3
HGET demo:user:42 name
HMGET demo:user:42 name level missing
HEXISTS demo:user:42 level
HLEN demo:user:42
```

HSET 返回的整数通常表示本次新增的字段数，而不是最终的总字段数；更新已有字段可以成功，但不会因此增加返回值。HMGET 的结果位置与请求字段对应，缺失字段应按空值处理。

较新的用法优先采用可接收多组字段的 HSET，不再把 HMSET 当作唯一的批量写入入口。HKEYS、HVALS、HGETALL 的返回量会随字段数增长，使用方便并不代表可以不受限制地调用。

## 2. HINCRBY 需要整数表示

```redis
HINCRBY demo:user:42 score 5
HINCRBY demo:user:42 score -2
```

键或字段不存在时可从 0 开始，值必须是命令可接受的整数表示。字段内部本来就是字节串，所以“字符串一定不能 HINCRBY”过于笼统；应区分合法整数字符串与普通文本。

浮点增量使用 HINCRBYFLOAT；整数增量需要遵守有符号 64 位范围与溢出检查。[HINCRBY 定义](https://redis.io/docs/latest/commands/hincrby/)

## 3. 键级 TTL 与字段 TTL

整个 Hash 可以通过 EXPIRE 设置期限。键到期意味着整个对象生命周期结束，不是只删除某个字段。

Redis 7.4 开始提供字段 TTL。以下新增流程先准备字段，再设置并查询期限，未运行：

```redis
HSET demo:user:42 session demo-session
HEXPIRE demo:user:42 300 FIELDS 1 session
HTTL demo:user:42 FIELDS 1 session
HSET demo:user:42 session replacement-session
HTTL demo:user:42 FIELDS 1 session
```

新增预期推演：在键与字段没有其他并发变化、键级期限未先到达的前提下，HEXPIRE 对该字段返回数组中的 1，第一次 HTTL 返回相应秒数。普通 HSET 覆盖 session 后会清除它的字段 TTL，最后一次 HTTL 对应值为 -1。已有字段被覆盖时，HSET 新增字段数可以为 0，但更新仍然成功。[HEXPIRE 更新规则](https://redis.io/docs/latest/commands/hexpire/)

| HTTL 的逐字段结果 | 含义                                     |
| ----------------- | ---------------------------------------- |
| 剩余秒数          | 存在并具有字段期限；不是键级 TTL         |
| -1                | 字段存在但没有字段期限                   |
| -2                | 相应字段不存在，包括 Hash 键不存在的情况 |

HTTL 使用秒，HPTTL 使用毫秒。官网中的某些旧示例和客户端注释存在不一致，本例按 [Redis 7.4.0 httlGenericCommand](https://raw.githubusercontent.com/redis/redis/7.4.0/src/t_hash.c) 的逐字段数组语义说明，不把网页输出复制成实测记录。整个 Hash 的键级期限不会因普通 HSET 自动被清除；不要将它与字段期限混淆。Redis 8.0+ 的 [HSETEX](https://redis.io/docs/latest/commands/hsetex/) 可在适用规则下组合字段写入与过期，但不属于上述 7.4 流程。

旧实例不支持此命令，不能只更新客户端文档就直接发送。使用字段过期后，复制、备份恢复和回退版本也要验证兼容。

## 4. 大 Hash 与热点粒度

把十万个对象放进一个 Hash，可能减少某些开销，也会把访问集中到同一个键；Cluster 不会把这个 Hash 的字段自动分到不同节点。

读取部分字段可用 HMGET；遍历可用 HSCAN，但 HSCAN 仍不是稳定快照，COUNT 也不是严格页大小。大量字段和很长值会影响查询、编码转换与删除。

若需要对字段独立授权、独立淘汰，或大量单独迁移，单个大 Hash 可能并不合适。按用户、时间或业务分组拆分时，应同时考虑热点与过期范围，而不是机械地按每组 1000 个处理。

这里的“独立授权”尤其需要区分应用校验与 Redis 键级 ACL：允许访问这个 Hash 键，并不意味着 Redis 会自动为每个 field 建立单独的授权规则。相关边界见 [第 31 章](/articles/redis-security-maintenance.html)。

## 5. 按版本观察内部编码与阈值 {#_5-内部编码不要沿用旧参数名}

历史版本使用 ziplist、hashtable 等表示，新版本可能使用 listpack 或后续结构。field 名、值大小与字段数共同影响紧凑表示条件。

`hash-max-ziplist-entries` 等参数按其版本查阅，配置名称以目标版本的有效参数为准。调整阈值也不会统一、立即把所有对象变成你想要的编码。

对于内存优化，记录 Redis 精确版本、OBJECT ENCODING、字段分布、MEMORY USAGE 以及命令成本；相关实现演进在第二十六章展开。[内存优化说明](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/memory-optimization/)

[返回本册目录](/collections/redis/)
