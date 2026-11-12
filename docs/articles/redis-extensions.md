---
id: redis-extensions
title: 第三十三章 Bloom Filter、JSON、Search 与扩展边界
description: "Redis 的扩展能力包括近似成员过滤、结构化 JSON 与索引查询等不同用途。本章先解释 Bloom Filter 的查询语义和更新条件，再介绍 JSON、Search 与发行方式，便于按需求选择和验证。"
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
order: 33
---

# 第三十三章 Bloom Filter、JSON、Search 与扩展边界

[返回本册目录](/collections/redis/)

Redis 的扩展能力包括近似成员过滤、结构化 JSON 与索引查询等不同用途。本章先解释 Bloom Filter 的查询语义和更新条件，再介绍 JSON、Search 与发行方式，便于按需求选择和验证。

## 1. Bloom Filter 回答“可能存在”

[![Bloom Filter：只检查本次命中的位](/assets/notes/redis/redis-study-bloom.svg)](/assets/notes/redis/redis-study-bloom.svg)

Bloom Filter（布隆过滤器）用位数组近似判断成员是否可能已加入。加入元素时，由多个 Hash Functions（哈希函数，把元素映射到数组位置的函数）派生的位置被置为 1；查询时，只要相关位置中有一个为 0，在结构正确、元素已经按协议加入且没有破坏性修改等假设下，就能判定它未被加入。全部位置为 1 只表示可能存在，因为不同元素可能共用位置。

因此它有假阳性，不是精确 Set。基础 Bloom Filter 不能直接把某元素对应的位清零来删除：那些位可能也被其他元素使用。容量与期望误报率越严格，空间和计算成本的权衡越重要。[Bloom Filter 官方说明](https://redis.io/docs/latest/develop/data-types/probabilistic/bloom-filter/)

FPR（False Positive Rate，假阳性率）描述未加入元素被判为“可能存在”的概率；Expected Capacity（预期容量）是预先规划的元素规模。目标 FPR 越低，通常需要更多位和哈希计算；容量估小也会增加后续扩容成本。这不是精确去重或成员列表，不能代替 Set 枚举成员，建模区别见 [第 2 章](/articles/redis-data-modeling.html)。

以下是 Redis 命令，不是 Shell（命令解释环境）或客户端方法；以已包含这些能力的 Redis Open Source 8.0.0 统一发行包为教学基线。旧版需要相应模块，见第 4 节。整数返回按 RESP2（Redis Serialization Protocol 2，Redis 序列化协议第 2 版）说明，客户端封装可能不同。仅用于隔离环境，会创建或修改 `demo:` 示例结构，假定对应键与索引尚不存在：

```redis
BF.RESERVE demo:bloom:items 0.01 10000
BF.ADD demo:bloom:items item-42
BF.EXISTS demo:bloom:items item-42
BF.EXISTS demo:bloom:items item-99
BF.INFO demo:bloom:items
```

0.01 是配置的目标误报率参数，不是“每 100 次查询必然刚好错 1 次”。也不要为不存在元素预先写死 BF.EXISTS 的肯定输出。

`demo:bloom:items` 是过滤器键（Key），0.01 为目标 FPR，10000 为初始预期容量。空环境中 RESERVE 成功预期为 OK，首次 ADD item-42 预期为 1，随后 EXISTS item-42 预期为 1；item-99 未插入，EXISTS 仍可能为 0 或假阳性的 1。对已存在键再次 RESERVE 会报错，不要无条件重复整段创建命令。

| 命令      | 返回语义与边界                                                                         |
| --------- | -------------------------------------------------------------------------------------- |
| BF.ADD    | 1 表示添加成功；0 表示可能已经存在，不能严格证明此前已插入                             |
| BF.EXISTS | 1 表示可能存在；0 表示在正确维护的过滤器中一定未加入                                   |
| BF.INFO   | 查看容量、分配字节、子过滤器数量、插入计数和扩容因子；插入计数也不是精确业务唯一用户数 |

语法与返回依据为 [BF.RESERVE](https://redis.io/docs/latest/commands/bf.reserve/)、[BF.ADD](https://redis.io/docs/latest/commands/bf.add/)、[BF.EXISTS](https://redis.io/docs/latest/commands/bf.exists/)和 [BF.INFO](https://redis.io/docs/latest/commands/bf.info/)。命令页面的早期版本号属于扩展组件的版本历史，不能误写为 Redis 核心从 1.0.0 就内置这些能力。

Redis 的可扩展过滤器达到容量后会新增 Sub-filter（子过滤器），而不是简单把原位数组拉长后沿用全部哈希位置。Expansion（扩容因子）决定新子过滤器相对前一个的容量增长，`EXPANSION 2` 表示约按两倍增长，默认也是 2：

```text
初始容量 10000 → 插入规模增长 → 达到容量
→ 创建新子过滤器（EXPANSION 2 时容量 20000）→ 继续插入
```

插入前需要识别已有元素，查询可能检查多个子过滤器：任一子过滤器给出“可能存在”，整体即可能存在；要判不存在则必须排除所有子过滤器。子过滤器越多，查询和维护的内存、计算成本越高。`NONSCALING` 禁止新增子过滤器，容量满后不能继续接纳新元素，会报错；它不是免费扩容。应按数据增长和目标 FPR 预留容量，内存预算见 [第 25 章](/articles/redis-memory-eviction.html)。

Cuckoo Filter（布谷鸟过滤器）保存 Fingerprint（指纹，元素的短哈希摘要），放入候选 Bucket（桶，存放若干指纹的位置）；插入时可能搬移已有指纹，查询时检查候选桶。

| 维度     | Bloom Filter                       | Cuckoo Filter                     |
| -------- | ---------------------------------- | --------------------------------- |
| 假阳性   | 存在                               | 存在，指纹也会碰撞                |
| 插入     | 哈希置位                           | 放入指纹，满桶时可能搬移或扩容    |
| 查询     | 检查命中位，扩容后可能遍历子过滤器 | 检查候选桶，扩容后也有额外成本    |
| 删除     | 基础版本不能按元素安全清位         | 支持删除已知加入的元素            |
| 适用场景 | 大量插入、近似存在性判断           | 需要成员删除且能维护插入/删除协议 |

删除优势有前提：不能仅凭“可能存在”就删除一个从未确认加入的元素，否则指纹碰撞可能使其他元素消失，产生假阴性；重复插入还需匹配删除次数。高占用下插入搬移也有成本，不能断言所有场景都比 Bloom 更快或更省内存。参见 [Cuckoo Filter](https://redis.io/docs/latest/develop/data-types/probabilistic/cuckoo-filter/)与 [CF.DEL 的删除警告](https://redis.io/docs/latest/commands/cf.del/)。

## 2. 放在缓存入口时，重点是更新协议

过滤器可以减少进入数据库的无效查询，但如果权威记录已经创建，而过滤器漏写，业务就会错误地拒绝真实记录。因此，需要明确数据写入顺序、失败重试、重建期间的策略，以及过滤器丢失后的降级方式。

“数据结构在理论假设下无假阴性”和“整个业务系统不会漏掉存在数据”是两件事。初始化不完整、异步更新滞后或恢复错版本，都会破坏业务假设。

以用户注册为例，教学正常流程是“数据库创建用户成功 → 把用户编号加入过滤器 → 确认添加成功 → 后续查询使用过滤器”。若数据库已提交但 Redis 写入失败，用户真实存在，过滤器却可能返回 0；此时直接拦截会误伤真实用户。这是业务漏写，不是哈希计算突然违反理论性质。

一种可恢复设计是在数据库提交用户的同一事务中保存 Outbox（事务发件箱，待投递事件），可靠地更新过滤器；失败后重试、补偿并监测进度。在异步滞后、过滤器丢失或状态未知期间，采用回源查询权威数据库等安全降级，而不是无条件相信负结果。若业务要求负结果立即可靠，必须先解决更新完成前的可见性窗口；“用了 Outbox”本身不会消除异步延迟。

重建时也要处理并发新写入，以下是协议流程，不是可直接执行的命令：

```text
建立新一代过滤器 → 按一致快照或明确水位加载权威数据
→ 重放快照水位之后的新增事件 → 追平并校验遗漏
→ 切换新一代 → 保留观察/回退窗口 → 回收旧一代
```

重建期间应保留可靠增量日志或协调双写，并在切换边界处理仍在途的新事件；一边全量扫描、一边任意切换会漏掉扫描已越过位置的新记录。未追平前对负结果回源，按代记录就绪状态，不能把半成品当成完整集合。与缓存穿透的关系见 [第 27 章](/articles/redis-cache-patterns.html)。

## 3. JSON 结构化操作与 Search 索引查询 {#_3-json-与-search-不是字符串格式的别名}

JSON（JavaScript Object Notation，JavaScript 对象表示法）描述结构化数据。把 JSON 文本存入 String，Redis 默认只看见字节序列；JSON 类型能力则支持相应路径上的结构化操作。Search 进一步通过索引与查询模型提供全文、标签、范围或向量等检索能力。

| 维度     | JSON 存入 String                            | Redis JSON                                                |
| -------- | ------------------------------------------- | --------------------------------------------------------- |
| 数据形态 | 序列化字节串                                | 结构化 JSON 值                                            |
| 获取字段 | 应用读取后解析                              | 支持 JSONPath（JSON 路径表达式）选择                      |
| 修改字段 | 通常读改后整体写回，需处理并发覆盖          | 可按路径修改                                              |
| 原子操作 | 单条 SET 原子，但应用多步读改写不会自动原子 | JSON.NUMINCRBY 等单条结构化命令原子执行，多条命令仍需协议 |
| 内存     | 与序列化内容有关                            | 结构化表示可能增加开销，不能保证比 String 省内存          |

下面创建一件商品、读取根值并给价格加 10：

```redis
JSON.SET demo:product:1001 $ '{"name":"Redis Guide","category":"database","price":99}'
JSON.GET demo:product:1001 $
JSON.NUMINCRBY demo:product:1001 $.price 10
```

`$` 表示 JSON 根路径。SET 成功预期为 OK；GET 使用 `$` 路径，返回包含该根对象的单元素 JSON 数组文本；NUMINCRBY 修改匹配的数值字段，预期返回 JSON 数组文本 `[109]`。这是协议中的字符串内容，不是客户端 API 必然直接返回同一类型的数组。参见 [JSON.SET](https://redis.io/docs/latest/commands/json.set/)、[JSON.GET](https://redis.io/docs/latest/commands/json.get/)、[JSON.NUMINCRBY](https://redis.io/docs/latest/commands/json.numincrby/)和 [JSON 内存说明](https://redis.io/docs/latest/develop/data-types/json/ram/)。

Search Index（搜索索引）根据选定字段建立辅助查询结构，避免每次查询遍历全部原始商品。继续写入第二件商品，再定义索引；下面 FT.CREATE 必须作为一条完整 Redis 命令发送，没有 Shell 的反斜线续行：

```redis
JSON.SET demo:product:1002 $ '{"name":"Python Guide","category":"programming","price":79}'
FT.CREATE demo:idx:products ON JSON PREFIX 1 demo:product: SCHEMA $.name AS name TEXT $.category AS category TAG $.price AS price NUMERIC
FT.INFO demo:idx:products
```

JSON 存储原文，FT.CREATE 为 `demo:product:` 前缀下的 JSON 定义字段：`AS` 指定查询别名，Search 构建辅助索引。创建成功预期为 OK，但已有数据的后台初始扫描可能尚未结束；先用 FT.INFO 检查索引进度、文档数量与索引错误，再验证结果。假定只有上述两件商品且索引已完成、无错误：

```redis
FT.SEARCH demo:idx:products '@category:{database}' NOCONTENT
FT.SEARCH demo:idx:products '@price:[100 120]' NOCONTENT
```

两次预期都只匹配 `demo:product:1001`，因为其价格已改为 109。在 RESP2 中，NOCONTENT 让结果只含总匹配数及键名，示意为 `[1,"demo:product:1001"]`；不同协议与客户端封装需分别解析。语法见 [FT.CREATE](https://redis.io/docs/latest/commands/ft.create/)、[FT.INFO](https://redis.io/docs/latest/commands/ft.info/)与 [FT.SEARCH](https://redis.io/docs/latest/commands/ft.search/)。

| 索引字段类型    | 用途                               |
| --------------- | ---------------------------------- |
| TEXT（文本）    | 分词后的全文检索                   |
| TAG（标签）     | 精确标签匹配，不按全文分词语义理解 |
| NUMERIC（数值） | 数值范围筛选                       |
| GEO（地理空间） | 地理距离等查询                     |
| VECTOR（向量）  | 向量相似性检索                     |

原始文档变化后，Search 需要维护相应索引。索引会占用额外内存，写入带来维护开销，初建、重建和错误排查也有成本；查询结果需结合版本的索引可见性、过期与超时语义解释，不能把“支持索引”当作无成本或跨系统强一致保证。Hash 也可作为索引源，见 [第 4 章](/articles/redis-hashes.html)；按分数排序与搜索索引的区别可对照 [第 7 章 Sorted Set](/articles/redis-sorted-sets.html)。

这些能力会增加索引、更新、内存和恢复成本。使用前，应明确一致性与查询语义、索引的建立方式、数据的演进方式，并确认客户端和权限是否覆盖相应命令。能够执行 GET，并不代表支持所有 JSON/FT 命令。

Redis Search 中的向量字段与 Vector Set（向量集合）也不是同一种数据模型：

| 维度     | Redis Search Vector                                               | Vector Set                         |
| -------- | ----------------------------------------------------------------- | ---------------------------------- |
| 数据模型 | Hash/JSON 文档中的向量字段及索引                                  | 独立的向量集合数据结构             |
| 主要定位 | 文档索引和混合查询                                                | 围绕向量集合进行相似性操作         |
| 查询组织 | 向量检索结合文本、标签、数值条件                                  | 向量相似性及其支持的属性过滤等操作 |
| 适用方向 | RAG（Retrieval-Augmented Generation，检索增强生成）、商品混合检索 | 独立向量集合管理、相似项查询       |

需要同时按商品名称、价格、分类和向量相似度查找时，可优先研究 Search 的文档索引；重点是向量集合本身时，再研究 Vector Set。Redis Open Source 8.0.0 以 Beta（测试阶段）引入 Vector Set，[8.10.0 README](https://github.com/redis/redis/blob/8.10.0/README.md)仍标为 beta，不能因 Redis 8.10 本身已 GA（General Availability，正式发布）就把该能力也写成 GA。本文不提供未经核实的 Vector Set 命令示例。

## 4. 发行版与版本边界

旧环境可能通过模块或 Redis Stack 获得能力；Redis 8 的统一发行方式又有变化。应核对实际安装包、产品、构建和命令可用性，而不是简单宣称“Redis 天生都有”或“必须手工下载动态库”。升级后的 ACL 类别变化也可能影响扩展命令权限。[Redis 8.0 能力与兼容性变化](https://redis.io/docs/latest/develop/whats-new/8-0/)

| 环境                         | 扩展能力获取方式                                                       |
| ---------------------------- | ---------------------------------------------------------------------- |
| Redis 7.x Open Source        | 按需要安装兼容模块，或选择包含它们的 Redis Stack 发行包                |
| Redis Stack 7.x              | 打包集成相应扩展，仍需核对具体组件版本                                 |
| Redis 8.x Open Source        | 从 8.0.0 起，统一发行包整合多种原 Stack 能力；构建选项和安装包仍需核对 |
| Redis Software / Redis Cloud | 根据产品版本、配置和实际开放能力验证，不能只看核心版本号               |

统一发行不等于模块扩展机制消失，也不意味着所有托管环境同步开放相同命令。可先进行命令发现：

```redis
COMMAND INFO BF.RESERVE
COMMAND INFO JSON.SET
COMMAND INFO FT.CREATE
```

[COMMAND INFO](https://redis.io/docs/latest/commands/command-info/) 返回命令描述或不存在的结果；能发现命令仍不等于自己有权执行，也不证明客户端、参数和持久化行为兼容。ACL（Access Control List，访问控制列表）类别及产品边界应纳入 [第 32 章升级矩阵](/articles/redis-upgrade-validation.html)。

外部扩展需要检查来源、支持版本、架构、许可证、持久化兼容性与安全维护。来源不明的二进制不应因教程里有一条 MODULE LOAD 就直接加载到真实服务。

本章提供选择与验证框架，尚无扩展下载、编译或安装记录。实践时先用有限数据验证命令、索引和恢复行为，再决定部署方式。

| 需求                 | 优先研究                               |
| -------------------- | -------------------------------------- |
| 大规模成员存在性判断 | Bloom Filter，接受假阳性并设计更新协议 |
| 成员判断且需要删除   | Cuckoo Filter，确认删除对象确实加入    |
| 结构化文档存储       | Redis JSON                             |
| 文本检索             | Redis Search                           |
| 标签与数值过滤       | Redis Search                           |
| 文本与向量混合查询   | Redis Search                           |
| 独立向量集合操作     | Vector Set，并核对测试阶段限制         |

实践验证还须覆盖：命令存在及版本支持、是否需要模块、ACL 允许/拒绝路径、客户端支持、持久化和恢复兼容，以及恢复后索引是否可用或需要重建。这些是选型检查项，不是本次已通过的部署实验。
