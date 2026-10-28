---
id: kafka-replication-isr
title: 第 4 章：副本复制、ISR 与故障切换
description: "假设 Topic 的 P0 配置在 Broker A、B、C，复制因子 RF 为 3。这三份是同一个分区的副本，而不是各自保存该分区三分之一的消息。"
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
order: 4
---

# 第 4 章：副本复制、ISR 与故障切换

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：把配置副本、同步副本和可被选为 Leader 的条件分开，理解“有三份副本”并非无条件的三份可靠数据。

## 1. Replica 保存同一分区的日志 {#_1-replica-是日志副本-不是分区的子分片}

假设 Topic 的 P0 配置在 Broker A、B、C，复制因子 RF 为 3。这三份是同一个分区的副本，而不是各自保存该分区三分之一的消息。副本消耗额外存储和网络，换取故障后的接管能力。

Leader 接收相应的生产请求，Follower 主动发出 Fetch 拉取复制数据。由于复制存在延迟，三份副本的末端位置不一定始终相同。不能把异步复制描述成每写一条记录，就立即对所有副本进行同步远程调用。

![复制与 ISR 流程](/assets/notes/kafka/kf-replica.svg)

## 2. ISR 随复制进度动态变化 {#_2-isr-是动态资格-不是固定数量}

ISR 表示符合相应同步要求的副本集合，包含 Leader。副本长期跟不上或失去适用连接条件时，可以离开 ISR；恢复并追上后，可按协议重新加入。RF 是分配数量，ISR 是运行时状态，两者不能互换。

按落后消息条数判断等旧参数需结合历史版本理解。观察现代副本恢复时，除了 Offset 进度，还要核对对应版本的同步判断、连接状态和配置机制。

## 3. LEO 与 HW 描述不同边界

LEO 可理解为某副本日志末端的下一位置，因此每份副本都可有自己的 LEO。HW 是复制提交相关的重要边界，不等于 Leader 最新刚接收的数据位置。读侧可见性还可能受事务稳定边界影响，第 14 章再展开。

教学例子：Leader 已追加到下一位置 105，Follower 尚未追上。不能仅看到 Leader 文件里有记录 104，就断言普通消费者一定能够读到，或故障接管后一定保留它。需要结合复制提交状态和选举条件。

## 4. 干净选主与数据风险

常规的干净故障切换会从合格的同步副本中选择新 Leader，以保留已提交的历史。若所有合格副本都不可用，就需要在等待其恢复和使用落后副本接管之间取舍。Unclean leader election 可能提高某些故障下的可用性，却也会引入丢失已确认数据的风险。

这不是“任何一台机器活着，三副本集群就能继续可靠写入”。还要满足控制面、网络、ISR 与 `min.insync.replicas` 等条件。故障模型若包含同机架断电、全部磁盘损坏或操作误删，单纯增加同一故障域的副本无法解决。

## 5. 从分区可用性到副本恢复的监控 {#_5-副本监控应该如何看}

先区分离线分区、欠复制分区和低于最小同步副本数的分区：它们反映的问题严重程度和受影响操作不同。再关联副本 Fetch 延迟、磁盘与网络压力、Leader 变更以及 ISR 变化。

恢复后不能只确认 Broker 进程重新出现，还应检查副本是否重新同步、分区领导关系是否正常，以及业务能否读写。补副本期间的网络与磁盘流量可能影响正常请求，因此需要一起规划恢复速度和业务容量。

## 参考

- [Kafka 3.9 复制设计](https://kafka.apache.org/39/design/design/#replication)
- [Kafka 3.9 监控](https://kafka.apache.org/39/operations/monitoring/)

## 联读

共同课程“复制与可靠写入”上半课：[acks/minISR与确认下半课](/articles/kafka-acks-min-isr.html)。两课共用A/B/C三副本例子；[4.0 ELR旁注](/articles/kafka-connect-streams.html)不反推3.9。
