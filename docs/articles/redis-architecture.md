---
id: redis-architecture
title: 第一章 Redis 架构、执行模型与版本边界
description: "Redis 用键及其对应的数据类型组织数据，通过命令完成读取与修改。理解一次调用，需要同时观察客户端连接、服务端执行、持久化和复制：它们分别影响响应时机、资源占用与故障恢复。"
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
order: 1
---

# 第一章 Redis 架构、执行模型与版本边界

Redis 用键及其对应的数据类型组织数据，通过命令完成读取与修改。理解一次调用，需要同时观察客户端连接、服务端执行、持久化和复制：它们分别影响响应时机、资源占用与故障恢复。本章先串起请求路径，再介绍后续各部分的职责。

本册从请求处理逐步讲到数据、持久化、复制和应用设计。基础命令采用稳定语义；Redis 2.x/3.x 实现按历史背景阅读，新能力单独标明最低版本。本文不假定实际实例已经升级，也没有执行 Redis 命令。

## 1. 从客户端连接到命令执行与回复 {#_1-一次请求会经过哪些环节}

客户端先获取或建立连接，按 RESP（Redis Serialization Protocol，Redis 序列化协议）将命令编码后发送。服务端读取请求、解析协议，处理命令，再将回复发回客户端。客户端只有收到并正确解析结果，才能知道这次调用返回了什么。[RESP 规范](https://redis.io/docs/latest/develop/reference/protocol-spec/)

事件循环（Event Loop）不断等待网络连接的就绪通知，再处理可读、可写事件和定时任务。非阻塞输入/输出（Non-blocking Input/Output，非阻塞 I/O）表示一次读写暂时无法继续时就返回，稍后再处理，不为某个慢连接一直等待。但命令本身执行很久，仍会占住处理其他命令的时间。

端到端延迟包含连接池等待、网络、排队、执行和回复处理。以 Redis Open Source 7.2.0 为准，SLOWLOG（Slow Log，慢日志）统计服务端实际执行命令的耗时，不包含客户端通信、读取请求和发送回复等网络 I/O，也不包含连接池等待和命令开始前的排队。因此“服务器没有慢日志”和“用户没有超时”不是一回事。[7.2.0 慢日志说明](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf#L1679-L1700)

超时尤其要谨慎：连接断了或客户端不再等待，不会自动撤销已经送达的写命令。重试一个 INCR，可能把业务计数加两次。这个边界会贯穿后面的客户端与幂等章节。

## 2. 普通命令执行与后台、I/O 工作的分工 {#_2-单线程到底指什么}

以 Redis Open Source 7.2.0 为参照，普通命令的数据操作主要由主线程串行执行。但 Redis 还有后台线程、可选的 I/O 线程，以及用于持久化的子进程，不能把“单线程”外推到所有工作。

`io-threads` 默认是 `1`，表示只使用主线程，不启用额外的 I/O 工作线程。配置为大于 `1` 时，可将适用的网络写出工作分给 I/O 线程；`io-threads-do-reads` 默认是 `no`（源码布尔值为 `0`，即 false），读取和协议解析仍由主线程处理。只有在启用多个 I/O 线程并设为 `yes` 时，适用的网络读取和协议解析才交给 I/O 线程。它们没有把普通命令执行改成多核并行；实际是否分派还受运行条件影响。[7.2.0 配置说明](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf#L1192-L1234) · [默认值注册](https://raw.githubusercontent.com/redis/redis/7.2.0/src/config.c#L2794-L2892) · [I/O 分派实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/networking.c)

理解后台分工前，先认识几个术语：AOF（Append Only File，追加日志文件）记录用于恢复数据的写操作；RDB（Redis Database，Redis 数据库快照）保存某一时刻的数据；fsync（File Synchronization，文件同步系统调用）请求将文件数据同步到持久存储。fork（创建子进程的系统调用）让后台子进程处理任务；COW（Copy-on-Write，写时复制）让父子进程起初共享内存页，修改时再复制受影响的页。

下图展示普通写命令与复制、持久化的分工，**不是客户端请求的完整时序图**。复制和 AOF 仅在相应功能启用时参与；快照和重写有独立触发条件，不是每次写命令的必经步骤。

[![Redis Open Source 7.2.0：普通写命令、复制与持久化分工](/assets/notes/redis/redis-study-architecture.svg)](/assets/notes/redis/redis-study-architecture.svg)

普通写命令在主线程更新内存后，按配置传播给副本并写入 AOF 缓冲区。AOF 追加写文件由主线程推进；`appendfsync always` 在主线程执行同步，`everysec` 通常由后台线程约每秒同步，`no` 则交由操作系统决定刷盘时机。回复成功不自动等于副本已确认或数据已落盘。[7.2.0 AOF 实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/aof.c)

RDB 后台快照由 `BGSAVE` 或配置的 `save` 条件等触发；AOF 重写由 `BGREWRITEAOF` 或满足自动重写阈值等触发。在支持 fork 的系统上，这两类后台任务由独立子进程生成文件，后台线程则与主线程处在同一进程，二者不能混称。fork 的停顿、COW 增加的内存以及磁盘竞争仍可能影响前台；这也不意味着快照与重写可任意同时启动。同步 `SAVE` 会阻塞主线程，不属于图中的后台快照路径。[7.2.0 配置与触发条件](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf) · [RDB 后台实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/rdb.c)

## 3. 快的原因，也给出了边界

数据通常驻留内存，命令由相应的数据结构实现，连接可以复用，网络处理则采用事件驱动方式。这些因素都有助于降低常见调用的成本，但不能据此推断“所有操作都是微秒级”“瓶颈永远是网络”或“内存访问时延就是一次 Redis 请求时延”。

一个遍历几十万元素的命令，即使全部读内存，也可能占用明显的 CPU（Central Processing Unit，中央处理器）和回复带宽；一个小 GET 也可能因为前面的大命令排队而超时。QPS（Queries Per Second，每秒查询数）是吞吐量指标；后续会结合返回量、算法与环境解释成本，而不使用一个固定 QPS 代表 Redis。

## 4. 数据类型与内部编码

对外类型决定可执行的命令，例如 String（字符串）、Hash（哈希）、List（列表）、Set（集合）、Sorted Set（有序集合）；内部编码决定某个版本怎样表示该对象，例如 int（整数编码）、embstr（Embedded String，嵌入式字符串）、listpack（紧凑列表）、quicklist（快速列表）。

`TYPE` 看类型，`OBJECT ENCODING` 看该对象当前编码。小 Hash 的内部表示变化，并不意味着它在应用看来变成了 List。数据库保存全部键的字典，也不是某个 Hash 键内部的字段字典。

Redis Open Source 7.2.0 的 `object.c` 分别保存对象类型与编码，`OBJECT ENCODING` 返回当前编码名称。后续在 [第 26 章：内部编码](/articles/redis-internal-encoding.html) 展开，入门阶段无需记忆阈值。[7.2.0 对象实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/object.c)

新增只读查询示意，需在获准环境中自行替换键名：

```redis
TYPE demo:user:42
OBJECT ENCODING demo:user:42
INFO server
```

## 5. 单机、复制、Sentinel、Cluster 分别增加什么

| 形态          | 解决的主要问题                              | 没有自动解决的事         |
| ------------- | ------------------------------------------- | ------------------------ |
| 单实例        | 单个数据集的访问与管理                      | 节点故障后的自动接替     |
| 主副本复制    | 数据副本、适用的读扩展                      | 零延迟、强一致、完整备份 |
| Sentinel      | 非 Cluster 形态的监控、主节点发现与故障转移 | 数据分片和业务请求代理   |
| Redis Cluster | 按槽分片与适用故障恢复                      | 任意跨槽事务、单热键拆分 |

Sentinel（哨兵）监控非 Cluster 部署，发现主节点并协调副本晋升。自动故障转移需要达到配置的 quorum（故障判定所需的哨兵数量），还要获得多数哨兵授权；若 quorum 更高，也必须满足它，并且要有可晋升的副本。单个哨兵超时不等于一定完成切换。[Sentinel 故障判定与授权](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/#quorum)

Cluster（集群）负责按哈希槽分片和集群内故障转移，不需要 Sentinel。正常自动故障转移要求主节点被标记为 `FAIL`、存在满足数据新鲜度等条件且允许自动晋升的副本，并由该副本取得有投票权主节点的多数授权。只有主节点、没有副本，或少数分区无法取得多数授权时，不能据此恢复故障主节点的服务。两种部署都依赖异步复制，切换仍有丢失已确认写入的风险。[Cluster 故障检测与选举规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#replica-election-and-promotion)

多进程放在同一台主机上，不会自动产生独立故障域。多个逻辑 DB（Database，数据库）也不提供 CPU、内存或安全隔离。

## 6. 怎样阅读本册的版本说明

旧 ziplist 阈值、redis-trib.rb、长期固定超时和内存配置，不直接作为新环境建议。核心机制会说明适用条件；6.2、7.0、7.4 与 8.x 新能力有独立版本标签。

官方资料区分 Redis Open Source、Redis Software、Redis Cloud 等产品，版本号不能跨产品直接比较。[Redis Open Source 发布目录](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/)提供新特性索引；升级目标仍需结合兼容性、发布记录与恢复测试选择。

阅读时可以沿问题跳转：[连接与未知结果](/articles/redis-hiredis.html)、[延迟与吞吐](/articles/redis-slow-queries.html)、[持久化加载源](/articles/redis-rdb-aof.html)、[fork 与资源峰值](/articles/redis-fork-copy-on-write.html)。高可用则先区分 [Sentinel](/articles/redis-sentinel.html) 和 [Cluster](/articles/redis-cluster-routing.html) 的职责，避免把它们当成同一种部署模式。

[返回本册目录](/collections/redis/)
