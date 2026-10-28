---
id: kafka-brokers-kraft
title: 第 3 章：Broker、Controller 与 KRaft
description: "Broker 承载分区副本并处理客户端请求。某分区的 Leader 负责该分区的主要读写协调，Follower 复制其日志；同一个 Broker 可以是 P0 的 Leader、P1 的 Follower。"
date: '2026-10-25'
updated: '2026-10-28'
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
order: 3
---

# 第 3 章：Broker、Controller 与 KRaft

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：分清业务数据、集群元数据和消费组协调三条路径，并理解各自的领导关系与故障条件。

## 1. 先区分四个角色

Broker 承载分区副本并处理客户端请求。某分区的 Leader 负责该分区的主要读写协调，Follower 复制其日志；同一个 Broker 可以是 P0 的 Leader、P1 的 Follower。

Controller 管理集群元数据及相关状态变更，例如分区领导关系。Group Coordinator 负责消费组协调及位点相关请求，两者职责不同。协调消费组不等于替该组处理每条业务消息。

![KRaft 控制面与业务分区复制](/assets/notes/kafka/kf-roles.svg)

图中下方的 Fetch 请求由 Follower 发起，复制数据随响应返回。上方的 Controller quorum 复制的是元数据，并不要求所有订单 Value 都先经过 Controller 再转发。

## 2. ZooKeeper 时代与现代消费组 {#_2-zookeeper-时代的笔记如何理解}

早期 Kafka 使用 ZooKeeper 保存和协调部分集群元数据；非常早期消费客户端也把组成员或位点等状态放在 ZooKeeper。这两条历史路线要分别与对应版本的客户端和 Broker 对照。

现代 Kafka 消费组通常通过 Broker 协议协调，提交位点保存在内部 Topic `__consumer_offsets`，名称是复数。客户端使用 Bootstrap Broker 获取元数据，而不是要求业务程序直接连接 ZooKeeper 才能读写消息。

## 3. KRaft 改变了什么

KRaft 把元数据管理整合进 Kafka，通过 Controller quorum 的 Raft 日志维护元数据。部署角色可以区分 Broker 与 Controller。教学用合并角色不等于生产环境应无条件合并：资源争用、故障隔离和维护策略仍需评估。

Kafka 3.9 文档同时包含 ZooKeeper 与 KRaft 路线；Kafka 4.0 已移除 ZooKeeper 模式。因此保留 3.9 机制作为本册复盘基线，并把 4.0 的差异单列，不把两种配置拼成一个“通用 server.properties”。

## 4. 两个故障域，两类多数与同步条件

Controller quorum 的可用性与其多数派有关。业务分区的数据可靠性则要看副本分配、ISR、确认策略和选主条件。不能说“Kafka用了 Raft，所以每个业务分区写入都等 RF 的多数票”。

控制面健康，并不代表每个分区都有可用 Leader；反过来，控制面故障时，部分已有读写可能短暂继续，但这也不代表集群能完成后续的所有故障切换。诊断时必须分别检查控制状态和分区状态，不能只看进程是否存活。

## 5. 迁移中的状态、回退与集群验收 {#_5-迁移不是删除一个配置项}

从 ZooKeeper 迁移到 KRaft 涉及版本、元数据迁移状态、回退边界和集群验收。不能在已有数据目录上随意格式化，然后认为会自动恢复原元数据。本册没有执行迁移或提供一键格式化脚本。

读图练习：指出消费者请求位点提交、生产者写 P0、P0 Follower 复制、Controller 元数据同步分别属于哪条路径。能说明这四条路径，就比“所有请求交给 Leader”更接近真实架构。

## 参考

- [Kafka 3.9 KRaft 运维](https://kafka.apache.org/39/operations/kraft/)
- [Kafka 4.0 KRaft 与 ZooKeeper 差异](https://kafka.apache.org/40/getting-started/zk2kraft/)
