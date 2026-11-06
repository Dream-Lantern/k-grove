---
id: redis-cluster-routing
title: 第二十三章 Cluster、槽路由与重定向
description: "Redis Cluster 用槽把键分布到多个主节点，各主节点再通过副本支持故障处理。一次请求先由键确定槽，再由客户端找到当前负责节点；槽迁移或拓扑变化时，通过重定向更新访问路径。"
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
order: 23
---

# 第二十三章 Cluster、槽路由与重定向

[返回本册目录](/collections/redis/)

Redis Cluster 用槽把键分布到多个主节点，各主节点再通过副本支持故障处理。一次请求先由键确定槽，再由客户端找到当前负责节点；槽迁移或拓扑变化时，通过重定向更新访问路径。[第二十二章 Sentinel](/articles/redis-sentinel.html) 管理非 Cluster 复制组的切换，不承担这里的数据分片职责。本章以 Redis Open Source 7.2.0 为机制核对基线，其他版本边界单独标明。

[![Redis Cluster：MOVED与ASK](/assets/notes/redis/redis-study-cluster-slots.png)](/assets/notes/redis/redis-study-cluster-slots.png)

图中的“稳定重定向”指 MOVED 会促使客户端更新路由，不表示槽归属此后永远不变；拓扑再次变化时仍需刷新。

## 1. 键、16,384 个槽与节点归属 {#_1-16-384-个槽不是一致性哈希环}

Hash Slot（哈希槽）是键和节点之间的分配单位。Redis Cluster 用 CRC16（16-bit Cyclic Redundancy Check，16 位循环冗余校验）的 XMODEM 算法计算键，再映射到固定的 16,384 个槽：

```text
slot = CRC16(key) % 16384
```

槽号是 0～16383，数量不随节点数变化。主节点负责一组槽，副本跟随相应主节点。这个中间层使扩容可以移动部分槽及数据，无需改变全部键的计算规则；16,384 是协议选定的固定数量，不是当前主节点数，也不是业务应部署的节点数量。

Hash Tag（哈希标签）让相关键按同一段内容计算槽，例如：

```text
user:{42}:profile
user:{42}:cart
user:{42}:orders
```

规则是找到第一个 `{`，再找其右侧第一个 `}`；中间至少有一个字节才使用括号内内容，否则对完整键计算。因此这三个键都用 `42` 计算；`foo{}{bar}` 的首对括号为空，要计算完整键，不能跳过空括号改用 `bar`。

以下是 Redis 命令，需在启用 Cluster 的实例执行；本章命令均未实际运行，结果说明是预期而非实测：

```redis
CLUSTER KEYSLOT user:{42}:profile
CLUSTER KEYSLOT user:{42}:cart
```

两条命令预期返回相同槽号，不要求它们已经存在。订单也可以按业务对象分组：`order:{1001}:detail`、`order:{1001}:items`、`order:{1001}:payment`。若全部订单统一使用 `{order}`，会集中在一个槽，容易形成热点。标签解决同槽问题，需要在多键操作便利性和分片均衡之间权衡。[Hash Tag 精确匹配规则](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

同一个节点可能负责很多槽。两把键恰好在同节点，不代表跨键命令一定可用；约束通常是同槽，迁移中还可能出现额外状态与错误。Cluster 也只使用数据库 0，不能用 SELECT 切换逻辑数据库分摊数据。[Cluster 协议规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)

## 2. 客户端维护槽与节点映射 {#_2-客户端应该懂-cluster}

客户端通常先发现拓扑，缓存槽与节点的映射，再直接连接负责相应槽的节点。Redis 节点并不是替客户端转发任意请求的透明代理；普通单机客户端可能无法正确处理地址变化、重定向和多节点连接。

| 命令             | Redis Open Source 版本                      | 用途                                     |
| ---------------- | ------------------------------------------- | ---------------------------------------- |
| `CLUSTER SLOTS`  | 3.0.0 引入；7.0.0 起标记 Deprecated（弃用） | 传统槽到节点映射接口；弃用不等于立即删除 |
| `CLUSTER SHARDS` | 7.0.0 引入                                  | 新的分片拓扑接口，新客户端优先考虑       |

客户端要按服务端版本和自身能力选择接口；旧环境仍可能需要 SLOTS。能 PING 一个入口，不代表能处理多节点连接、认证和通告地址。[SHARDS](https://redis.io/docs/latest/commands/cluster-shards/)、[SLOTS 的版本与弃用说明](https://redis.io/docs/latest/commands/cluster-slots/)

Pipeline（命令流水线，即批量发送命令以减少往返等待）也要先按节点路由，不能把分属不同节点的命令全部发往同一入口。见[第十七章](/articles/redis-pipeline.html)；事务和脚本的多键同槽约束见[第十八章](/articles/redis-transactions-lua-functions.html)。

## 3. MOVED 与 ASK 不同

![两种重定向的处理分支](/assets/notes/redis/redis-study-redirect.svg)

MOVED 表示当前已知的槽归属在别处，客户端应重试并更新相关拓扑认知。ASK 常出现在传统迁移过程，要求本次请求临时去目标节点，先在同一连接发送 ASKING，再发送被重定向的命令；不能因此立刻把该槽永久改到目标节点。

| 响应       | 含义                                 | 客户端处理                                                    |
| ---------- | ------------------------------------ | ------------------------------------------------------------- |
| `MOVED`    | 当前节点认为槽归其他节点负责         | 更新本地槽路由，必要时刷新拓扑，并有界重试                    |
| `ASK`      | 传统迁移中，本次请求需临时访问目标   | 在目标的同一连接先发 `ASKING`，紧接当前命令；不永久更改槽映射 |
| `TRYAGAIN` | 迁移中多键请求暂时不能在一个节点完成 | 稍后有限重试，超出预算则向业务报告                            |

教学假设：槽 S 正从 A 迁到 B，`user:{42}:profile` 仍在 A，`user:{42}:cart` 已在 B。两键都存在且属于同槽，客户端向源端 A 发出：

```redis
MGET user:{42}:profile user:{42}:cart
```

此时预期为 TRYAGAIN 错误，因为数据暂时分布在两端，不能在 A 完成这次多键读取。这不是跨槽的 CROSSSLOT 错误，也不是换个地址就能解决；迁移完成并收敛后可恢复。迁移时涉及不存在键的多键操作也可能受限。[TRYAGAIN 官方说明](https://redis.io/docs/latest/develop/reference/errors/common/tryagain/)

客户端还应限制重定向次数，并正确处理连接错误和未知的写入结果，不能因为拓扑正在变化就无限循环重试。一次请求涉及多个键时，还需要为跨槽错误设计业务处理方式，不能随机换个节点就重试。

## 4. 分片容量与单键热点的不同处理 {#_4-分片解决不了所有热点}

槽数平衡不代表数据字节、请求数或 CPU（Central Processing Unit，中央处理器）负载平衡。一万个小冷键可能远轻于一个热点大 Hash。单个键通常由一个分片负责，增加节点不会自动把该键内部拆开。

是否拆分热点，或采用本地缓存、请求合并和限流，需要结合数据模型判断。拆分后，跨分片聚合与一致性成本也会上升，因此不能仅因架构图中节点更多，就认定容量会线性增长。

## 5. 可用性依赖主节点视图和副本条件

Cluster 通过 Gossip（流言传播，即节点互换彼此观察到的状态）收集故障信息。Node Timeout（节点超时，对应 `cluster-node-timeout`）影响探测与故障处理，但不是固定恢复时间。

PFAIL（Possible Failure，疑似故障）是本地怀疑；FAIL（Failure，确认故障状态）需要相应多数主节点报告，接到 FAIL 消息的节点也会更新状态。报告有有效期，不是所有主节点必须在同一瞬间一致投票。故障判断只是启动后续处理的依据，不能等同于提升已经完成。

其逻辑流程为：

```text
主节点 A 不可达 → 节点探测超时，作出本地 PFAIL 判断
→ Gossip 收集有效期内的故障报告
→ 满足多数主节点条件，标记并传播 FAIL
→ 合格副本发起选举，取得多数有槽主节点授权
→ 副本提升，使用新的配置纪元公布槽归属
```

Config Epoch（配置纪元）是槽归属配置的版本号，用来解决不同节点声明同一槽时的冲突。自动提升还要求旧主有槽、副本数据足够新、未禁止自动提升，并获得多数有槽主节点的当轮授权；复制进度影响候选尝试时机。Redis Open Source 7.2.0 中，新鲜度受 `cluster-replica-validity-factor` 等配置影响，设为 0 可关闭该年龄检查，不应写成跨版本固定秒数。[Cluster 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#replica-election-and-promotion)、[7.2.0 故障检测与选举实现](https://github.com/redis/redis/blob/7.2.0/src/cluster.c)

**Cluster 的故障报告与选举不是 Sentinel 的 quorum 算法。** 不在这里配置 Sentinel 的 `down-after-milliseconds` 或 quorum。三个主节点各配一个副本只是常见教学拓扑，不能把副本也算成同等授权票。

Redis Open Source 7.2.0 默认 `cluster-require-full-coverage yes`，槽未分配或其主节点被判 FAIL 时，会使相应节点视图中的集群状态失败，默认拒绝正常数据请求。设为 `no` 允许在缺槽时继续服务可用槽，但不会恢复丢失槽的数据，也不能绕过主节点多数可达的要求。

假设三个分片 A、B、C 各有一主一副本，C 主副本均失效：A、B 仍有 2/3 主节点多数；全槽覆盖开启时，缺失 C 的槽会影响整体服务；关闭时，A、B 的槽可能继续服务，C 的槽仍不可用。若再失去 B，A 无法形成主节点多数，关闭全槽覆盖也不能让它无条件继续服务。[7.2.0 配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf)、[clusterUpdateState 实现](https://github.com/redis/redis/blob/7.2.0/src/cluster.c)

副本可用于读扩展。在 Cluster 副本连接上发送：

```redis
READONLY
```

这是该连接接受读取可能过旧数据的声明，允许读取其主节点负责槽的数据，不提供强一致性，也不会把副本变成可写主节点。重连后需要重新设置；拓扑变化或访问其他槽时仍须处理重定向。[副本读扩展](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#scaling-reads-using-replica-nodes)

异步复制仍有确认写入丢失窗口。故障域、客户端、认证、数据端口与集群总线可达性，都属于完整架构。

[第二十四章](/articles/redis-cluster-operations.html)继续说明迁移命令、扩缩容与回退；这里的图是职责和路由示意，不包含真实私有部署地址。
