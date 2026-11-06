---
id: redis-data-modeling
title: 第二章 数据建模、键命名与命令入门
description: "选择 Redis 类型前，应先写清楚需要读取什么、如何更新、何时失效，以及哪些结果不能丢失。同一个业务对象既可以序列化为一个 String，也可以拆成 Hash 字段，具体取决于访问模式和一致性边界。"
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
order: 2
---

# 第二章 数据建模、键命名与命令入门

选择 Redis 类型前，应先写清楚需要读取什么、如何更新、何时失效，以及哪些结果不能丢失。同一个业务对象既可以序列化为一个 String（字符串），也可以拆成 Hash（哈希）字段，具体取决于访问模式和一致性边界。

## 1. 键名是一份小型数据契约

键名通常包含用途、对象标识和必要的分区信息，使读取、排查与生命周期管理能定位同一业务对象。教学例子：

```text
demo:user:42:profile
demo:rank:weekly
demo:rate:sms:user-42
```

`demo:` 表示教学命名空间，不对应真实业务。前缀方便排查，但不是访问控制；敏感标识直接进入键名，还可能出现在日志、监控与备份中。

键名应在可理解与容量间权衡。把所有名称压成难以辨认的几个字母，节省的空间未必值得；把大段 JSON（JavaScript Object Notation，JavaScript 对象表示法）放进键名也会增加数据与网络成本。

## 2. 按访问和生命周期选类型

| 需求                     | 可考虑的类型 | 必须继续问的问题                 |
| ------------------------ | ------------ | -------------------------------- |
| 整体缓存一个对象         | String       | 是否每次都需要整体序列化和更新？ |
| 读取、修改对象的部分字段 | Hash         | 字段数量与过期策略是否可控？     |
| 简单的有序队列           | List         | 弹出后失败，任务如何恢复？       |
| 需要消费进度的消息流     | Streams      | 是否需要确认、重放与故障接管？   |
| 精确成员关系             | Set          | 基数是否过大，是否需要列出成员？ |
| 排名与分数范围           | Sorted Set   | 同分、精度与分页如何定义？       |
| 近似统计不重复元素数量   | HyperLogLog  | 是否接受误差且不需要成员列表？   |

List（列表）可通过一端写入、另一端弹出实现简单队列，但弹出本身不提供处理完成确认。Streams（流）可使用 Consumer Group（消费者组）分配消息；Pending Entries（待确认条目）记录已投递但未确认的消息，保存在 PEL（Pending Entries List，待确认条目列表）中。处理后用 `XACK` 发送 ACK（Acknowledgment，确认）；消费者故障后可用 `XCLAIM` 认领符合条件的待确认消息。消费者组、确认与认领自 Redis Open Source 5.0.0 起可用，仍需应用处理重复消费。[Streams 消费者组](https://redis.io/docs/latest/develop/data-types/streams/)

HyperLogLog 是估计集合基数（不重复元素数量）的概率结构，例如估计一天有多少独立访客。它不保存可供精确查询的成员集合，不能替代 Set 的精确成员查询，也不能列出成员。[HyperLogLog 说明](https://redis.io/docs/latest/develop/data-types/probabilistic/hyperloglogs/)

集合运算是否跨 Cluster 槽、单次返回多少数据，也应在建模阶段明确。仅仅减少键的数量，并不能证明内存占用和延迟都有改善。

同一个用户对象可以有以下两种存法。下面是 Redis 命令，可在 `redis-cli` 交互环境逐条输入；不是 Shell 命令，也不是客户端 API（Application Programming Interface，应用程序编程接口）。本次没有执行：

```redis
SET demo:user:42:json '{"name":"Lin","city":"Hangzhou"}'
GET demo:user:42:json
HSET demo:user:42:hash name Lin city Hangzhou
HGET demo:user:42:hash city
HSET demo:user:42:hash city Shanghai
```

String 中的 JSON 适合整体读取和替换；修改 city 通常需要应用读取、解析后重新写入整份对象，并处理并发覆盖。Hash（哈希）把属性拆成 field（字段），可直接读取或修改 city，不必传输整个对象。Hash 字段值仍是字节串，不会自动保留 JSON 的嵌套结构和数据类型。应按实际访问方式选择，而不是认为一种存法总是更省内存。

## 3. 合并成大 Hash 的得失

把很多小 String 合成多个 Hash，可以减少某些键级开销，但可能改变热点分布、整体过期、迁移与淘汰粒度。一个超大 Hash 又可能成为大键。

TTL（Time to Live，生存时间）表示数据距离过期还有多久。Hash Key TTL 是键级过期，例如 `EXPIRE` 让整个 Hash 到期；Hash Field TTL 是字段级过期，只针对指定字段。Redis Open Source 7.2.0 支持前者，不支持后者；Redis Open Source 7.4.0 起（7.4+）增加 `HEXPIRE` 等字段过期命令。不能把旧版本缺少字段过期理解成 Hash 不能设置过期时间。[HEXPIRE 版本记录](https://redis.io/docs/latest/commands/hexpire/) · [7.4.0 Release Notes](https://raw.githubusercontent.com/redis/redis/7.4.0/00-RELEASENOTES)

Hash Tag（哈希标签）让 Cluster 按键名中符合规则的花括号内容计算哈希槽（键所属的分片单元）。例如 `user:{42}:profile` 与 `user:{42}:cart` 都按 `42` 计算，因此在同一槽，便于执行要求同槽的多键操作。若通过标签把大量键放在同一槽，负载也更容易集中。只对需要共同操作的有限范围使用，不把整个业务都塞进同一个标签。[Cluster Hash Tag 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

ACL（Access Control List，访问控制列表）用于限制用户可执行的命令和可访问的键。普通键级 ACL 不会自动把同一个 Hash 的字段分成独立授权单元。模型需要按字段隔离时，必须明确拆键或可信应用层的授权责任，见 [第 31 章](/articles/redis-security-maintenance.html)。

## 4. 逻辑 DB 的连接状态与共享资源 {#_4-逻辑-db-不是独立实例}

独立模式可以配置多个逻辑 DB（Database，数据库）。Redis Open Source 7.2.0 的 `databases` 默认是 16 个，即编号 0–15，但总数可配置。新连接默认使用 DB 0；`SELECT` 只改变当前连接选择的 DB，不会改变其他连接。连接重建后要重新选择目标 DB，不能假定服务端记得旧连接的状态；客户端连接池也必须保证每条连接使用预期 DB。[7.2.0 默认配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf) · [SELECT 连接语义](https://redis.io/docs/latest/commands/select/)

逻辑 DB 共用进程资源，某个 DB 的重命令或内存压力仍可能影响其他 DB。Redis Cluster 只使用 DB 0，也不支持靠 SELECT 切换业务库。[SELECT 语义](https://redis.io/docs/latest/commands/select/)

一台机器多实例同样共用 CPU、磁盘和物理内存，隔离需要靠实际资源约束、故障域和容量设计完成。

## 5. 学命令时同时读四个方面

每个命令至少看参数、返回值、错误、复杂度。GET 返回空值不等于空字符串；WRONGTYPE 表示键类型与操作不匹配；返回整数也可能表示新增数量、影响数量或当前值，不能一概解释成成功布尔值。

同一类读取也有例外：MGET 的逐键 nil 可以来自缺失键或非 String 键，不能直接照搬 GET 对错误类型的处理。示例见 [第 3 章](/articles/redis-strings.html)。

先在专用学习环境中使用独立前缀，避免覆盖已有数据。下面仅是语法示例，未执行：

```redis
SET demo:hello world EX 60
GET demo:hello
TTL demo:hello
TYPE demo:hello
```

命令展示采用 Redis 命令语言；`redis-cli`、shell 管道和客户端 API 属于另外的调用层，不把三层语法混在同一代码块。

## 6. 查找、删除与迁移的操作范围 {#_6-默认不提供批量删除捷径}

`FLUSHDB`、`FLUSHALL`、重命名覆盖、恢复覆盖和键迁移都可能破坏数据。`KEYS | xargs DEL` 只是“查键后批量删除”这种危险操作的概念性简写，既不是可直接执行的 Redis 命令，也不是完整可执行的 Shell 命令。`KEYS` 会阻塞扫描，Shell 管道还可能错误拆分含空格、换行或二进制内容的键名，并误删目标；批量删除需要专门设计扫描、键名传递和目标确认流程。

后面的遍历与维护章节会说明范围、预览、幂等和恢复要求。确认这些条件之前，只查找目标，不将查找结果自动传给删除命令。

类型概览可参照 [Redis 数据类型](https://redis.io/docs/latest/develop/data-types/)，命令细节以目标版本文档为准。

[返回本册目录](/collections/redis/)
