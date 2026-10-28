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

Redis Cluster 用槽把键分布到多个主节点，各主节点再通过副本支持故障处理。一次请求先由键确定槽，再由客户端找到当前负责节点；槽迁移或拓扑变化时，通过重定向更新访问路径。Sentinel 主要管理复制组切换，与这里的数据分片职责分别理解。

[![Redis Cluster：MOVED与ASK](/assets/notes/redis/redis-study-cluster-slots.png)](/assets/notes/redis/redis-study-cluster-slots.png)

## 1. 键、16,384 个槽与节点归属 {#_1-16-384-个槽不是一致性哈希环}

Redis Cluster 根据键计算 CRC16，再映射到 16,384 个槽。主节点负责一定范围或集合的槽；副本跟随相应主节点。扩容时移动槽及其数据，而不是把整个键空间重新平均计算成新节点数量。

hash tag 可以使相关键按同一段内容计算槽，例如：

```text
demo:order:{42}:header
demo:order:{42}:items
```

这两类示例键可以被设计为同槽，从而支持相应多键操作。但把全部业务统一写成同一个 tag，会形成集中负载，失去分片收益。

同一个节点可能负责很多槽。两把键恰好在同节点，不代表跨键命令一定可用；约束通常是同槽，迁移中还可能出现额外状态与错误。Cluster 也只使用数据库 0，不能用 SELECT 切换逻辑数据库分摊数据。[Cluster 协议规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)

## 2. 客户端维护槽与节点映射 {#_2-客户端应该懂-cluster}

客户端通常先发现拓扑，缓存槽与节点的映射，再直接连接负责相应槽的节点。Redis 节点并不是替客户端转发任意请求的透明代理；普通单机客户端可能无法正确处理地址变化、重定向和多节点连接。

较新版本可通过 CLUSTER SHARDS 获取分片视图，老环境与客户端也可能使用 CLUSTER SLOTS。应核对双方能力，不能仅因命令行能 PING 一个入口就认定应用支持 Cluster。[CLUSTER SHARDS：7.0+](https://redis.io/docs/latest/commands/cluster-shards/)

## 3. MOVED 与 ASK 不同

![两种重定向的处理分支](/assets/notes/redis/redis-study-redirect.svg)

MOVED 表示当前已知的槽归属在别处，客户端应重试并更新相关拓扑认知。ASK 常出现在传统迁移过程，要求本次请求临时去目标节点，先在同一连接发送 ASKING，再发送被重定向的命令；不能因此立刻把该槽永久改到目标节点。

客户端还应限制重定向次数，并正确处理连接错误和未知的写入结果，不能因为拓扑正在变化就无限循环重试。一次请求涉及多个键时，还需要为跨槽错误设计业务处理方式，不能随机换个节点就重试。

## 4. 分片容量与单键热点的不同处理 {#_4-分片解决不了所有热点}

槽数平衡不代表数据字节、请求数或 CPU 平衡。一万个小冷键可能远轻于一个热点大 Hash。单个键通常由一个分片负责，增加节点不会自动把该键内部拆开。

是否拆分热点，或采用本地缓存、请求合并和限流，需要结合数据模型判断。拆分后，跨分片聚合与一致性成本也会上升，因此不能仅因架构图中节点更多，就认定容量会线性增长。

## 5. 可用性依赖主节点视图和副本条件

Cluster 的故障判断与提升不是所有进程平等投票。持有槽的主节点、多数条件、候选副本状态和超时共同决定是否能恢复。三个主节点各配一个副本是常见教学拓扑，不是所有部署都必须恰好六个进程。

关闭全槽覆盖要求，也不表示丢失主节点多数后，其他槽必定持续可用。异步复制同样存在确认写入丢失窗口。故障域、客户端、认证、数据端口与集群总线可达性，都属于完整架构，而不只是创建集群时的一条命令。

下一章从运维角度讨论扩缩容与迁移；这里的图是职责和路由示意，不包含真实私有部署地址。
