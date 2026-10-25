---
id: kafka-connect-streams
title: 第 23 章：Connect、Streams 与演进路线
description: 直接使用 Producer/Consumer API，可以控制业务处理和依赖，但需要自己维护位点、错误、模式、并发和恢复。若主要目标是把外部系统接入 Kafka，重复编写同样的连接与运行管理代码可能没有必要。
date: '2026-10-25'
updated: '2026-10-25'
category: distributed-systems
type: explanation
tags:
  - kafka
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kafka
series: kafka-learning
order: 23
---

# 第 23 章：Connect、Streams 与演进路线

> 版本导航：3.9生态入口 / 4.0演进旁注。
>
> 学习目标：在原文基础上补齐常见生态定位，并把已确认的版本变化作为索引，不把新特性清单混进旧 C API 教程。

## 1. 自写 Consumer 只是其中一条路线

直接使用 Producer/Consumer API，可以控制业务处理和依赖，但需要自己维护位点、错误、模式、并发和恢复。若主要目标是把外部系统接入 Kafka，重复编写同样的连接与运行管理代码可能没有必要。

Kafka Connect 提供连接器运行框架，由 Source 将外部数据接入 Kafka，再由 Sink 从 Kafka 写向外部。但使用同一框架，不意味着每种 Connector 都有相同的 Exactly Once 保证；最终语义仍取决于版本、Connector、运行模式及外部系统的合作契约。

![常见生态组件职责](/assets/notes/kafka/kf-ecosystem.svg)

## 2. Kafka Streams 处理的是什么

Streams 是构建 Kafka 流处理应用的 Java 库，涉及流表模型、窗口、聚合、状态存储及恢复。它不是需要另行安装在每台 Broker 上的通用 SQL 数据库，也不是 C Consumer 的同义名称。

窗口与事件时间还会引入乱序、迟到和状态保留问题。选择 Streams 时，应先理解输入输出、Key、分区和状态恢复，不要因为启用某个处理保证就忽略外部副作用。

## 3. 跨集群复制不等于同步多主事务

MirrorMaker 等复制路线用于跨集群数据流动，但复制延迟、位点映射、故障切换、循环复制和目标命名都需要单独管理。异步复制通常存在可量化的恢复点风险，不能直接宣传为两地任意切换零丢失。

设计灾备时，应先定义 RPO、RTO 和业务切换条件，再安排复制与验证。目标 Topic 已经出现，并不能证明消费恢复、权限、事务语义和外部状态都已满足立即接管的条件。

## 4. 版本演进的三条清晰边界

第一，3.9 与 4.0 的元数据模式不同：4.0 已不再支持 ZooKeeper 模式。第二，4.0 新 Consumer Rebalance 协议 GA，但客户端支持阶段独立；librdkafka 2.8.0 的对应能力仍是 Early Access。第三，默认参数会变化，应固定客户端文档而非只写“Kafka 默认”。

另一个 4.0 的补充是 Eligible Leader Replicas（ELR）：在相应协议和功能条件下，控制器可记录不在当前 ISR 内、但仍可安全接管的副本资格。因此第 4—5 章的 3.9 常规 ISR 模型不能直接外推为以后所有版本的完整选主算法。ELR 也不是允许任意落后副本无损接管。

分层存储也值得后续学习，但插件实现、版本支持、Topic 策略和运维边界需要另设专题讨论。本册只给出入口，不将其描述为已经可以替代所有本地磁盘规划。

## 5. 选择补充知识的顺序

先把单集群分区、可靠性、消费位点和幂等理解扎实，再学习状态流处理、跨集群恢复和存储演进。它们都不能绕过基础语义。

本册补充的是可持续学习路径，不是某个新版本的完整发布说明。没有核实的后续特性不作肯定结论，更不据网站“latest”导航推断本机已升级或某项配置已经可用。

## 参考

- [Kafka Connect Overview](https://kafka.apache.org/39/kafka-connect/overview/)
- [Kafka Streams Introduction](https://kafka.apache.org/39/streams/introduction/)
- [Kafka 3.9 Tiered Storage](https://kafka.apache.org/39/operations/tiered-storage/)
- [Kafka 4.0 Consumer Protocol](https://kafka.apache.org/40/operations/consumer-rebalance-protocol/)
- [Kafka 4.0 升级与 ELR 变化](https://kafka.apache.org/40/getting-started/upgrade/)
