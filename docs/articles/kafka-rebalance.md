---
id: kafka-rebalance
title: 第 12 章：Rebalance、心跳与消费协议
description: 成员加入、离开或失效，订阅或分区变化，都可能需要重新计算所有权。Rebalance 的目标是让适用成员继续承担分区，不是把 Broker 的日志文件搬到消费机器，也不是回滚旧消费者已经发出的外部请求。
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
order: 12
---

# 第 12 章：Rebalance、心跳与消费协议

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：将分区交接当成业务生命周期事件，而不是只通过调大超时隐藏问题。经典协议、新协议和客户端支持阶段分开阅读。

## 1. 为什么需要重新分配

成员加入、离开或失效，订阅或分区变化，都可能需要重新计算所有权。Rebalance 的目标是让适用成员继续承担分区，不是把 Broker 的日志文件搬到消费机器，也不是回滚旧消费者已经发出的外部请求。

因此，交接发生时，旧消费者在线程池中尚未完成的任务，可能与新持有者的任务重叠。组协议能管理分区所有权，但外部系统若没有去重或 fencing，就无法仅凭 group.id 拒绝旧任务延迟到达的写入。

![分区交接与在途工作](/assets/notes/kafka/kf-rebalance.svg)

## 2. 心跳存活与业务推进是两件事

Session相关超时用于判断成员的心跳存活。`max.poll.interval.ms`限制的是相关消费API调用间隔，不是后台业务任务的进度检测器。

| 纸面历史                           | 组协议看到什么                          | 业务仍需监测什么                                 |
| ---------------------------------- | --------------------------------------- | ------------------------------------------------ |
| 同步处理阻塞，主线程长时间不再poll | 可能超过max.poll.interval并失去成员资格 | 单条处理时间、恢复与重复窗口                     |
| 主线程持续poll，工作线程卡在数据库 | 消费API仍活跃，可能继续保持成员资格     | 连续完成前沿停滞时间、最老在途任务年龄、有界队列 |

pause 分区后仍需处理客户端事件，但继续 poll 不等于业务健康。静态成员超过 max.poll.interval 后，也不一定立即转交分区，还要结合停止心跳及 session timeout 等后续条件判断。[Java 3.9 max.poll.interval.ms](https://kafka.apache.org/39/configuration/consumer-configs/#max.poll.interval.ms)

配置大超时可以容忍慢任务，却也拉长某些故障恢复窗口。正确方案还包括拆分有界任务、限制在途量、暂停适用分区而持续服务客户端事件，以及确保队列不会无限增长。不要仅以“后台线程还在发心跳”证明业务健康。

## 3. Eager 与 Cooperative 不可混用回调

Eager 交接可能先撤销完整分配；Cooperative 则采用增量交接，减少不必要的全量停止。两者对回调内分配操作的要求不同，不能直接拼接分别采用这两种方式的示例代码。

对本册 librdkafka v2.8.0，eager 路线使用完整 assign/clear，cooperative 路线使用相应 incremental assign/unassign。若注册自定义回调，必须承担协议要求；没有回调时库可自动处理适用分配。业务清理应只作用于被撤销的范围。

## 4. Kafka 4.0 的新消费协议

Kafka 4.0 的 KIP-848 Consumer 协议进入 GA，分配计算与部分超时配置职责发生变化；Classic 仍存在。不能据服务端 4.0 支持，就断言任意旧客户端已完整支持。

固定到 librdkafka v2.8.0 时，其该协议仍标为 Early Access，缺少部分能力。因此本册 C 路线保持 Classic，不推荐直接把 `group.protocol=consumer` 加进旧示例当作升级完成。未来升级需重新核对客户端发布说明、回调契约和兼容矩阵。

## 5. 交接时怎样处理位点

停止向被撤销分区派发新工作，识别已完成的连续区间，有界等待或取消剩余任务，并按仍然有效的所有权条件提交。所有权已经丢失时，不能把旧实例的提交成功视为必然。

自检：如果写数据库的任务无法取消，至少应通过业务 ID 幂等或下游 fencing 控制重叠效果。仅调用 pause 不会撤回已经发到外部系统的请求，也不会替你完成线程池排空。

## 参考

- [Kafka 4.0 Consumer Rebalance Protocol](https://kafka.apache.org/40/operations/consumer-rebalance-protocol/)
- [librdkafka v2.8.0 KIP-848 支持阶段](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md#next-generation-of-the-consumer-group-protocol-kip-848)
