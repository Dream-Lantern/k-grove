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

Hash（哈希）在一个键下保存 field-value（字段—值）映射，适合需要按字段读取、更新的对象。它不要求每个对象拥有完全相同的字段集合，但也不自动提供关系型数据库的约束和关联查询。整份对象存为 String（字符串）与拆成 Hash 的对比，见 [第 2 章：数据建模](/articles/redis-data-modeling.html)。

本章 `redis` 代码块是可在 `redis-cli` 交互环境输入的 Redis 命令，不是 Shell 命令。所有示例均未实际运行；预期返回与结构图都是教学推演。使用独立学习实例，假定示例键起初不存在、无其他客户端修改，并在所设期限内完成操作；字段过期部分另有最低版本要求。

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

上述示例预期依次返回新增字段数 `2`、`"Lin"`、`["Lin", "3", nil]`、存在标记 `1`、字段总数 `2`。HSET 返回本次新增的字段数，而不是最终的总字段数；更新已有字段可以成功，但不会因此增加返回值。

HMGET 的结果位置与请求字段一一对应；nil（空值，表示没有对应数据）与空字符串不是同一种结果：

| 情况                   | HMGET 的返回                             |
| ---------------------- | ---------------------------------------- |
| 字段存在，值为 hello   | 对应位置为 `"hello"`                     |
| 字段存在，值为空字符串 | 对应位置为 `""`                          |
| 字段不存在             | 对应位置为 nil                           |
| Key 不存在             | 每个请求字段的位置均为 nil               |
| Key 存在但不是 Hash    | 整条命令返回 WRONGTYPE（类型不匹配错误） |

[HMGET 返回定义](https://redis.io/docs/latest/commands/hmget/)

Redis Open Source 4.0.0 起，HSET 支持多组 field-value 参数；HMSET 同时被标记为 deprecated（已弃用，仍保留兼容但不推荐新代码使用）。符合版本要求时优先使用 HSET，例如：

```redis
HSET demo:user:42 name Lin age 30 city Beijing
```

接续前面的示例，name 被更新而 age、city 新增，预期返回 `2`。HKEYS、HVALS、HGETALL 的返回量会随字段数增长，使用方便并不代表可以不受限制地调用。[HSET 版本记录](https://redis.io/docs/latest/commands/hset/#history) · [HMSET 弃用说明](https://redis.io/docs/latest/commands/hmset/)

## 2. HINCRBY 需要整数表示

```redis
HINCRBY demo:user:42 score 5
HINCRBY demo:user:42 score -2
```

键或字段不存在时可从 0 开始，值必须是命令可接受的整数表示。字段内部本来就是字节串，所以“字符串一定不能 HINCRBY”过于笼统；应区分合法整数字符串与普通文本。

上述两条命令预期依次返回 `5`、`3`。HINCRBY 使用整数增量，必须遵守有符号 64 位范围与溢出检查；HINCRBYFLOAT 使用浮点增量，适合允许近似数值的场景。浮点表示不能精确表达所有十进制小数，这是通用计算机数值表示问题，不是 Redis 独有问题。严格精确的金额可考虑按最小货币单位存为整数，例如以分保存金额，再核对范围、舍入和业务规则。[HINCRBY](https://redis.io/docs/latest/commands/hincrby/) · [HINCRBYFLOAT](https://redis.io/docs/latest/commands/hincrbyfloat/)

## 3. 键级 TTL 与字段 TTL

TTL（Time to Live，生存时间）表示数据距离过期还有多久。Key TTL 是整个键的期限，可用 EXPIRE 设置；Field TTL 是某个字段的独立期限，用来让临时属性先于对象消失，例如用户对象中的临时 session（会话）。两者的作用范围不同：

```text
demo:user:42
├── Key TTL = 3600s（整个 Hash 的期限）
└── Field Mapping（字段映射）
    ├── name = Lin       → 无独立字段 TTL
    ├── score = 100      → 无独立字段 TTL
    └── session = token-001 → Field TTL = 300s
```

这是生命周期结构示意，不是实测状态：键级 TTL 到期会删除整个 Hash；字段 TTL 到期只删除对应字段，不会延长 Key TTL。最后一个字段被删除或过期后，Hash Key 也会消失，因此“无字段 TTL”并不意味着字段一定永久存在。

Redis Open Source 7.4.0 起提供字段 TTL。以下流程接续本章用户示例，先准备字段，再设置并查询期限，未运行：

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

HTTL 使用秒，HPTTL 使用毫秒。本例按 [Redis Open Source 7.4.0 httlGenericCommand](https://raw.githubusercontent.com/redis/redis/7.4.0/src/t_hash.c) 的逐字段数组语义说明，不把网页输出复制成实测记录。整个 Hash 的键级期限不会因普通 HSET 自动被清除；不要将它与字段期限混淆。Redis Open Source 8.0.0 起的 [HSETEX](https://redis.io/docs/latest/commands/hsetex/) 可在适用规则下组合字段写入与过期，但不属于上述 7.4.0 流程。

HPERSIST 可主动清除字段 TTL，同时保留字段和值。以下仍要求 Redis Open Source 7.4.0 或更高版本；必须在期限到达前执行，不能用它找回已经过期的字段：

```redis
HSET demo:user:42 session token-001
HEXPIRE demo:user:42 300 FIELDS 1 session
HPERSIST demo:user:42 FIELDS 1 session
HTTL demo:user:42 FIELDS 1 session
```

接续前面的示例，预期依次为 `0`（更新已有 session）、`[1]`（设置成功）、`[1]`（移除字段期限成功）、`[-1]`（字段存在但没有字段 TTL）。HPERSIST 不会清除或延长整个 Hash 的 Key TTL。普通 HSET 覆盖字段同样会清除该字段原 TTL，不能把它当作“保留期限的更新”。[HPERSIST](https://redis.io/docs/latest/commands/hpersist/) · [HTTL](https://redis.io/docs/latest/commands/httl/) · [7.4.0 字段过期与空 Hash 清理实现](https://raw.githubusercontent.com/redis/redis/7.4.0/src/t_hash.c)

旧实例不支持此命令，不能只更新客户端文档就直接发送。使用字段过期后，复制、备份恢复和回退版本也要验证兼容。

## 4. 大 Hash 与热点粒度

把十万个对象放进一个 Hash，可能减少某些开销，也会把访问集中到同一个键；Cluster 不会把这个 Hash 的字段自动分到不同节点。

读取部分字段可用 HMGET；HSCAN 则通过 cursor（游标，即继续遍历的位置标记）分批遍历字段和值。初始传入 `0`，之后使用上次返回的游标，直到返回游标 `0` 才表示本轮结束。COUNT 是工作量提示，不是严格分页大小；一次可能返回空结果而游标仍不为 `0`，不能因此停止。完整遍历可能出现重复字段，数据变化时也不保证快照一致性，它不是传统数据库的 OFFSET/LIMIT（按偏移与条数取页）分页。[HSCAN](https://redis.io/docs/latest/commands/hscan/) · [官方 SCAN 遍历保证](https://raw.githubusercontent.com/redis/redis-doc/master/commands/scan.md)

大量字段和很长值会影响查询、编码转换与删除。

若需要对字段独立授权、独立淘汰，或大量单独迁移，单个大 Hash 可能并不合适。按用户、时间或业务分组拆分时，应同时考虑热点与过期范围，而不是机械地按每组 1000 个处理。

这里的“独立授权”尤其需要区分应用校验与 Redis 键级 ACL（Access Control List，访问控制列表，用于限制命令和键访问）：允许访问这个 Hash 键，并不意味着 Redis 会自动为每个 field 建立单独的授权规则。相关边界见 [第 31 章](/articles/redis-security-maintenance.html)。

## 5. 按版本观察内部编码与阈值 {#_5-内部编码不要沿用旧参数名}

内部编码（Internal Encoding）是 Redis 保存对象的具体方式，不会改变 Hash 对外的字段语义。小 Hash 将字段和值紧凑排列，可减少指针和分配开销；hashtable（哈希表）需要更多空间，但适合较大对象的字段查找。ziplist（压缩列表）是旧紧凑结构，listpack（紧凑列表）是后续替代结构。

以下列出已核对的 Redis Open Source 固定版本，不把“6.2 及以前”理解成所有历史版本都完全相同：

| 版本参照     | Hash 相关表示                                                                         |
| ------------ | ------------------------------------------------------------------------------------- |
| 6.2.0        | 小 Hash 使用 ziplist，较大时使用 hashtable                                            |
| 7.0.0、7.2.0 | 紧凑表示改为 listpack，较大时使用 hashtable                                           |
| 7.4.0        | 保留 listpack、hashtable；字段过期还涉及 listpackex（扩展紧凑列表）及哈希表过期元数据 |

[6.2.0 t_hash.c](https://raw.githubusercontent.com/redis/redis/6.2.0/src/t_hash.c) · [7.0.0 t_hash.c](https://raw.githubusercontent.com/redis/redis/7.0.0/src/t_hash.c) · [7.2.0 t_hash.c](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_hash.c)

以 Redis Open Source 7.2.0 为例，`hash-max-listpack-entries` 默认 `512`，限制紧凑 Hash 的字段数量；`hash-max-listpack-value` 默认 `64` 字节，限制单个字段名或值的长度。增长超出适用阈值时会转成 hashtable，源码还会检查紧凑结构的容量安全条件。配置名中的 value 不意味着字段名可以无限长。调整阈值不会立即重编码全部已有对象。[7.2.0 配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf) · [转换检查](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_hash.c)

Redis Open Source 7.4.0 在紧凑 Hash 上使用字段过期命令时，可转成 listpackex，保存字段、值和过期信息；hashtable 路径也会维护过期元数据和索引。因此新增字段过期并非零内存开销，也不是所有 Hash 一律变成 listpackex。[7.4.0 t_hash.c](https://raw.githubusercontent.com/redis/redis/7.4.0/src/t_hash.c) · [listpackEx 定义](https://raw.githubusercontent.com/redis/redis/7.4.0/src/server.h) · [编码名称](https://raw.githubusercontent.com/redis/redis/7.4.0/src/object.c)

紧凑结构省空间，却仍需扫描定位字段；扩大阈值可能增加操作成本。大 Hash 还会集中热点、迁移和淘汰粒度，不能只比较键的数量。优化时记录精确版本、`OBJECT ENCODING`、字段分布、`MEMORY USAGE` 与命令成本，进一步见 [第 26 章：内部编码](/articles/redis-internal-encoding.html) 和 [官方内存优化说明](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/memory-optimization/)。

[返回本册目录](/collections/redis/)
