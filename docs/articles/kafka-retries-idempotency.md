---
id: kafka-retries-idempotency
title: 第 9 章：重试、幂等与超时的未知结果
description: 客户端发出请求后发生网络故障，可能有三种事实：Broker 尚未处理、已经处理但确认未返回、处理结果仍未确定。应用仅看到一个超时，不能据此可靠区分这些事实。
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
order: 9
---

# 第 9 章：重试、幂等与超时的未知结果

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：理解超时不等于没写入，分清客户端协议重试去重和应用业务去重。

## 1. 最容易被忽视的是“结果未知”

客户端发出请求后发生网络故障，可能有三种事实：Broker 尚未处理、已经处理但确认未返回、处理结果仍未确定。应用仅看到一个超时，不能据此可靠区分这些事实。

如果确认丢失，普通重新发送可能产生重复；若不重试，又可能遗漏业务事实。可靠协议要显式处理不确定窗口，而不是假设每个请求都会得到准确的“成功或完全没发生”二选一结果。

[![Kafka 幂等：协议重试与新业务请求](/assets/notes/kafka/kf-idempotence.svg)](/assets/notes/kafka/kf-idempotence.svg)

## 2. 幂等生产者去掉哪一类重复

Kafka 幂等生产利用生产者身份、Epoch 和分区序列等机制识别适用的协议重试，避免同一批次因重发在日志中形成重复效果。它不是根据 JSON 的 order_id 自动比较全部历史。

如果应用在超时后重新构造并发送一条业务消息，或在重启后重新扫描待发业务，而又没有共享的业务去重协议，就不能保证这次 send 与上次属于“同一条”协议消息。因此，持久事件 ID、Outbox 状态和消费端幂等仍有价值。

## 3. 顺序与最大在途请求相关

未使用幂等时，多个在途批次可能出现前一批失败重试、后一批先成功的情况，从而改变原来的发送顺序。启用幂等也必须满足客户端对确认、重试和在途请求数量的约束。

本册不建议通过随意关闭重试来“修复重复”，也不把每种客户端的默认设置混成一行。Java 3.9 在无冲突配置时默认启用幂等；librdkafka v2.8.0 默认关闭。具体设置不兼容时可能被拒绝或改变行为，启动时的配置检查不能省略。

具体约束是acks=all、retries>0、max.in.flight.requests.per.connection≤5。Java3.9未显式启用幂等时，显式冲突值可能使默认幂等失效；显式true且冲突则配置异常。C2.8显式启用后会调整用户未设置的相关参数，用户自己设置不兼容值则实例创建失败。默认值、自动调整与显式冲突不能混为一列；[第19章配置组合表](/articles/kafka-client-configuration.html)给出合法与冲突例子。

## 4. 超时有不同层次

聚合等待、单次请求、整体消息投递以及事务超时，各自约束的过程不同。把所有 timeout 都设得很大，可能导致故障后长期堆积；都设得很小，又可能带来无效重试和误判。

以 librdkafka 为例，消息投递超时约束本地等待与重试过程，不能用 poll 的等待毫秒数替代。poll 的等待时长主要影响调用线程处理事件和等待的方式，不会自动把消息的可靠投递时限设为相同的毫秒数。

## 5. 重试策略还需要边界

区分可恢复错误、配置错误、权限错误和致命状态。过大的消息、错误认证或不支持的参数不会因为立即重复一百万次而恢复。重试需要退避、预算、告警和可恢复的失败记录，避免形成放大故障的重试风暴。

对业务暴露结果时，也应区分已确认、已拒绝和待查证。若业务要求严格追踪，可以用稳定 event_id 关联发送记录、投递报告和消费效果，而不是仅依赖进程退出码。

## 参考

- [Java 3.9 幂等与在途请求约束](https://kafka.apache.org/39/configuration/producer-configs/#enable.idempotence)
- [librdkafka v2.8.0 可靠性说明](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)

## 联读

通用未知结果与重试预算见[分布式RPC主文](/articles/distributed-rpc-retries-idempotency.html)；本章聚焦Kafka协议重试。
