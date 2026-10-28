---
id: distributed-saga-tcc-outbox
title: 第二十二章 Saga、TCC、Outbox 与跨服务一致性
description: "跨服务业务通常分多步改变订单、支付和库存状态。各步的提交、外部可见与补偿方式可能不同，因此需要记录过程并设计恢复路径。Saga、TCC 和 Outbox 分别从补偿、资源预留和事件发布入手，处理这些边界上的一致性问题。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - 分布式系统
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: distributed-systems
series: distributed-learning
order: 22
---

# 第二十二章 Saga、TCC、Outbox 与跨服务一致性

> 阅读标签：通用协议/应用模型，具体前提见本章。

跨服务业务通常分多步改变订单、支付和库存状态。各步的提交、外部可见与补偿方式可能不同，因此需要记录过程并设计恢复路径。Saga、TCC 和 Outbox 分别从补偿、资源预留和事件发布入手，处理这些边界上的一致性问题。

## 1. 先缩小真正需要原子的范围

如果一个不变量可以在同一个事务资源内完成，优先考虑减少跨边界协调。拆成三个服务不是目的；把库存预留和可售数量一起约束，有时比事后对账更直接。

确需跨服务时，区分“全局原子提交”和“通过多步可恢复流程达到业务终态”。二者都可能有合理用途，但不能把后者也宣传成每个瞬间全局 ACID。

## 2. Saga：提交分步发生，失败靠补偿

Saga 将长流程拆为局部事务及对应补偿。订单教学流程为：预留库存 → 请求支付 → 确认订单；若支付明确失败，则取消预留。各步骤可能已对外可见，补偿是新的业务操作，不是时间倒流。[Saga 原论文](https://www.cs.cornell.edu/andru/cs711/2002fa/reading/sagas.pdf)

退款可能延迟，补偿可能失败，重试也可能重复执行。因此需要记录流程状态、步骤 ID、调用结果与补偿进度。支付结果未知时，应先查询或对账，不能在退款的同时无条件再次扣款。

## 3. TCC：先预留，再确认或取消

Try 预留业务资源，Confirm 消耗预留，Cancel 释放预留。它把可回退性设计进接口，例如把库存从“可售”转为“已预留”，而不是直接发货。

实现需要处理重复 Confirm/Cancel、Cancel 先于迟到 Try、空回滚和资源悬挂；这些不是三段函数名自动带来的保证。具体框架有相应状态与防护机制，采用时必须固定版本验证。[Apache Seata 的 TCC 模式说明](https://seata.apache.org/docs/dev/mode/tcc-mode/)

## 4. Outbox 原子保存业务数据与事件意图 {#_4-outbox-解决哪个双写问题}

先提交订单再发事件，中间崩溃会丢事件；先发事件再提交订单，事务回滚后消费者可能处理一笔不存在的订单。Outbox 把业务数据与待发送事件放进同一个本地事务，后续通过 relay 或 CDC 发布。

![业务提交、Outbox 与幂等消费](/assets/notes/distributed-systems/dist-outbox.svg)

教学伪代码，仅表达原子边界：

```text
同一本地事务：
    写入订单 o-42 的状态
    写入 outbox 事件 e-42 与订单版本
提交
独立发布器：读取已提交事件，发送并按协议记录进度
消费者：在自己的事务中去重 e-42 并更新本地业务
```

发布器可能发送成功但尚未记录进度就崩溃，因此仍可能重复发送；消费者要幂等，事件顺序也需设计。Outbox 原子地保住“业务状态与待发布意图”，并不原子提交所有消费者数据库。[Transactional Outbox 模式原始说明](https://microservices.io/patterns/data/transactional-outbox.html)

### 发布顺序与消费去重分别处理 {#去重不修复发布乱序}

同一订单先提交E1(version=1)，再提交E2(version=2)。若两个relay先发布E2、再发布E1，即便Kafka Key都为同一个order_id，日志也只是忠实记录这个错误发布顺序。Key不恢复数据库里的业务版本顺序，event_id去重也不会阻止不同ID的旧版本覆盖新状态。

可按业务聚合串行发布，或选择并验证保留所需提交顺序的CDC路径；消费者还应识别同ID重复、旧版本、版本缺口。遇到version=2而尚缺version=1时，是等待、补取还是采用允许跳变的状态快照，要由业务定义。

在本章选用的数据库幂等方案中，去重记录与业务效果**必须在同一本地事务内提交**，并用唯一约束等处理并发；不是“尽量”放在一起。外部HTTP副作用无法加入该事务时，需要对端幂等键或其他替代协议，不能把两步独立写当成同样保证。[Kafka中的对应推演](/articles/kafka-order-events.html)

## 5. 按业务条件比较协调路线 {#_5-不要混淆选择条件}

| 路线   | 主要协调方式                   | 仍需承担的边界                          |
| ------ | ------------------------------ | --------------------------------------- |
| 2PC    | 参与资源准备并接受统一提交决定 | Prepared 资源占用、故障恢复与参与者能力 |
| Saga   | 局部提交与可恢复补偿           | 中间可见、补偿失败、业务终态            |
| TCC    | 业务资源预留与确认/取消        | 接口侵入、乱序与幂等                    |
| Outbox | 本地数据与事件意图原子保存     | 传递重复、消费状态和投影延迟            |

这些机制并不相互排斥，例如 Saga 可以通过 Outbox 发送事件。选择时应依据不变量、可逆性与容错目标，而不是看哪个缩写更流行。

## 联读

Outbox后的异步查询投影见[CQRS工程入口](/articles/distributed-cqrs-cache-ids.html)；Kafka实现边界见[订单事件案例](/articles/kafka-order-events.html)。

[返回本册目录](/collections/distributed-systems/)
