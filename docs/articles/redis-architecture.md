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

客户端先获取或建立连接，将命令编码后发送。服务端读取请求、解析协议，按相应的执行模型处理命令，再将回复发回客户端。客户端只有收到并正确解析结果，才能知道这次调用返回了什么。

[![Redis：命令执行、持久化与复制的开销](/assets/notes/redis/redis-study-architecture.svg)](/assets/notes/redis/redis-study-architecture.svg)

端到端延迟包含连接池等待、网络、排队、执行和回复处理。慢日志只覆盖其中一部分。因此“服务器没有慢日志”和“用户没有超时”不是一回事。

超时尤其要谨慎：连接断了或客户端不再等待，不会自动撤销已经送达的写命令。重试一个 INCR，可能把业务计数加两次。这个边界会贯穿后面的客户端与幂等章节。

## 2. 普通命令执行与后台、I/O 工作的分工 {#_2-单线程到底指什么}

经典 Redis 普通命令的主要数据操作路径通常串行推进，这让许多单命令并发语义容易理解。但 Redis 进程还可能有后台线程、I/O 线程，以及用于持久化等工作的子进程。

Redis 6 的 I/O 多线程主要针对适用的网络读写等工作，不等于所有普通命令突然可以在多核上并行执行。后台释放、扩展模块和后续版本也各有实现条件，不能把“单线程”外推到所有工作。

Redis 6 的 I/O 图用于解释该代网络处理路线，其他版本按各自的实现与有效配置分析。以固定标签 Redis 7.2.0 为例，`io-threads` 默认 1，不启用额外的 I/O 工作线程；`io-threads-do-reads` 默认 false。不能只因版本大于 6，就假定已开启多线程读写，更不能用这组默认值概括所有 8.x 实现。[7.2.0 配置](https://raw.githubusercontent.com/redis/redis/7.2.0/redis.conf) · [7.2.0 默认值注册](https://raw.githubusercontent.com/redis/redis/7.2.0/src/config.c)

## 3. 快的原因，也给出了边界

数据通常驻留内存，命令由相应的数据结构实现，连接可以复用，网络处理则采用事件驱动方式。这些因素都有助于降低常见调用的成本，但不能据此推断“所有操作都是微秒级”“瓶颈永远是网络”或“内存访问时延就是一次 Redis 请求时延”。

一个遍历几十万元素的命令，即使全部读内存，也可能占用明显的 CPU 和回复带宽；一个小 GET 也可能因为前面的大命令排队而超时。后续会按返回量、算法与环境解释成本，而不使用一个固定 QPS 代表 Redis。

## 4. 数据类型与内部编码

对外类型决定可执行的命令，例如 String、Hash、List、Set、Sorted Set；内部编码决定某个版本怎样表示该对象，例如 int、embstr、listpack、quicklist。

`TYPE` 看类型，`OBJECT ENCODING` 看该对象当前编码。小 Hash 的内部表示变化，并不意味着它在应用看来变成了 List。数据库保存全部键的字典，也不是某个 Hash 键内部的字段字典。

新增只读查询示意，需在获准环境中自行替换键名，本次未运行：

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

多进程放在同一台主机上，不会自动产生独立故障域。多个逻辑 DB 也不提供 CPU、内存或安全隔离。

## 6. 怎样阅读本册的版本说明

旧 ziplist 阈值、redis-trib.rb、长期固定超时和内存配置，不直接作为新环境建议。核心机制会说明适用条件；6.2、7.0、7.4 与 8.x 新能力有独立版本标签。

官方资料区分 Redis Open Source、Redis Software、Redis Cloud 等产品，版本号不能跨产品直接比较。[Redis Open Source 发布目录](https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/)提供新特性索引；升级目标仍需结合兼容性、发布记录与恢复测试选择。

所有新增命令序列均是教学示例，没有实测输出。生产实践还要补上确切版本、拓扑、客户端和恢复验收。

阅读时可以沿问题跳转：[连接与未知结果](/articles/redis-hiredis.html)、[延迟与吞吐](/articles/redis-slow-queries.html)、[持久化加载源](/articles/redis-rdb-aof.html)、[fork 与资源峰值](/articles/redis-fork-copy-on-write.html)。高可用则先区分 [Sentinel](/articles/redis-sentinel.html) 和 [Cluster](/articles/redis-cluster-routing.html) 的职责，避免把它们当成同一种部署模式。

[返回本册目录](/collections/redis/)
