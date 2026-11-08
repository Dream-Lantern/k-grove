---
id: kafka-delivery-semantics
title: 第 13 章：投递语义与外部系统幂等
description: "一条事件可能被发送两次、在 Kafka 日志中出现一次、被应用读取三次，但最终数据库更新只生效一次。这些描述分别对应发送、存储、读取和业务效果，并不矛盾。"
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
order: 13
---

# 第 13 章：投递语义与外部系统幂等

> 版本基线：Kafka Broker 3.9、Java Client 3.9 与 librdkafka v2.8.0。
>
> 学习目标：结合处理、提交与故障恢复的先后关系，理解 At Most Once、At Least Once、Exactly Once 各自覆盖的范围。

## 1. 先定义“做一次”指什么

一条事件可能被发送两次、在 Kafka 日志中出现一次、被应用读取三次，但最终数据库更新只生效一次。这些描述分别对应发送、存储、读取和业务效果，并不矛盾。

谈语义要先指定边界：Producer 到 Kafka、Kafka 到 Consumer，还是源数据库到外部支付服务。还需声明允许的故障与恢复方式。没有这些条件，“绝不丢、绝不重复”没有可验证含义。

以订单支付确认事件为例，先把计数边界放在消费者到订单状态更新这一段：

| 语义                      | 常见做法                                                         | 崩溃恢复与代价                                                                                                 |
| ------------------------- | ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| At Most Once（最多一次）  | 确认位点提交成功后才执行一次业务尝试，假设事件没有在源头重复出现 | 崩溃可能漏更新。适合允许丢样本的统计，处理链简单，但无法靠回放补漏                                             |
| At Least Once（至少一次） | 业务完成后提交位点，失败时重试或重放                             | 只要事件仍可恢复且最终能处理成功，就能补做失败任务。可能反复调用业务，订单系统要承担去重和重试成本             |
| Exactly Once（恰好一次）  | 在明确边界内原子提交结果与进度，或通过重试加去重约束最终效果     | 同一支付事件可以交付多次，订单累计金额只增加一次。需要明确事件身份、持久化原子性和恢复条件，增加存储与协调成本 |

## 2. 处理与提交的两种故障窗口

先提交位点再处理，若中间崩溃，恢复时会越过尚未完成的业务，形成遗漏风险。先处理再提交，若效果已完成但提交尚未成功，恢复后会重复处理。

![处理与提交的故障窗口](/assets/notes/kafka/kf-semantics.svg)

自动提交不能简单归类为“默认就是最多一次”。它和真实处理的时序取决于客户端、交付方式和应用逻辑；异步处理尤其容易让位点领先。应画出实际顺序，再判断风险。

设 P0 的已提交位置原为 100，事件仍在保留范围内。以下为故障时序推演：

| 场景         | 崩溃前的顺序                                                      | 从哪里恢复 | 可能的结果                                                |
| ------------ | ----------------------------------------------------------------- | ---------- | --------------------------------------------------------- |
| A · 先提交   | 取到 100 → Broker 确认 101 → 数据库更新前崩溃                     | 101        | 跳过 100，订单遗漏更新                                    |
| B · 先处理   | 取到 100 → 数据库提交 → 位点仍为 100 时崩溃                       | 100        | 事件重放。只有数据库再次应用变更时才产生重复业务效果      |
| C · 异步处理 | Poll 交付 100–102 → Worker 尚未完成 100 → 应用提前提交 103 → 崩溃 | 103        | 跳过所有尚未完成的任务，即使 102 已成功也不能据此提交 103 |

提交响应丢失时，恢复以 Broker 实际保存的位置为准。异步处理应关闭可能提前推进的自动提交，按[第 11 章的分区连续完成前沿](/articles/kafka-offset-watermarks.html)提交。

## 3. 在数据库事务中联合提交去重与业务效果 {#_3-外部数据库怎么约束重复}

一个常见方案是事件含稳定 `event_id`，消费者在同一个数据库事务中写入去重记录与业务更新；去重记录具有唯一约束。重复事件到达时按已处理路径返回，而不是重复扣减。

关键条件是：去重判断、去重记录和业务变更需要具有共同的原子性。如果先查询“没处理过”，再在没有事务保护的情况下修改数据，多个并发消费者仍可能重复执行。设计去重表时，还需考虑保留期限、状态失败后的重试，以及不同业务操作的 ID 范围。

### PostgreSQL 16 原子去重示例

用新建的实验数据库和 `psql -v ON_ERROR_STOP=1` 执行下面的建表和事务。输入是事件 `evt-1001`，订单 `order-001`，类型 `PAYMENT_CONFIRMED`，金额为 100 个最小货币单位。应用应先校验事件类型和金额，实际代码使用绑定参数。

```sql
CREATE TABLE processed_order_event (
    event_id text PRIMARY KEY
);

CREATE TABLE order_payment (
    order_id text PRIMARY KEY,
    paid_amount bigint NOT NULL
);

BEGIN ISOLATION LEVEL READ COMMITTED;
WITH accepted AS (
    INSERT INTO processed_order_event (event_id)
    VALUES ('evt-1001')
    ON CONFLICT (event_id) DO NOTHING
    RETURNING event_id
)
INSERT INTO order_payment AS current_payment (order_id, paid_amount)
SELECT 'order-001', 100 FROM accepted WHERE true
ON CONFLICT (order_id) DO UPDATE
SET paid_amount = current_payment.paid_amount + EXCLUDED.paid_amount;
COMMIT;

SELECT order_id, paid_amount FROM order_payment;
```

重复执行事务块，预期金额仍为 100。两个 Consumer 同时处理该事件时，唯一索引让冲突的插入等待另一事务结束。先执行的事务提交后，另一个事务的 `accepted` 为空，业务写入无输入。先执行的事务回滚时，另一事务可以取得处理资格。普通 SELECT 在两边都可能读到“未处理”。若业务修改先行且已独立提交，随后唯一约束拦下去重记录也无法撤销之前的修改。

应用流程是收到事件后执行上述数据库事务。数据库报错则回滚，保持该分区前沿不动并按错误类型重试。COMMIT 响应丢失也用同一个事件 ID 重试。确认提交后，把当前记录标为完成，再按前沿提交 Kafka 位点。Kafka 提交失败导致重放时，数据库按同一 ID 去重。

相同事件 ID 必须对应同一个事件。不同事件 ID 若可能引用同一笔支付，需另用稳定的支付操作 ID 约束业务唯一性。保留去重记录的时间要覆盖回放范围。对于支付 HTTP 调用，可由接收方用操作 ID 去重。发送邮件等外部效果可用事务内 Outbox（待发送记录表）保存发送意图，再由投递端重试并结合接收方能力控制重复。该 SQL 为教学实验，尚未在 PostgreSQL 实测。

## 4. Kafka 事务与外部系统的协调范围 {#_4-exactly-once-的范围不能外推}

Kafka 事务可以协调适用的 Kafka 输出与输入消费位点，服务 Kafka 到 Kafka 的处理语义。它不会自动将任意 MySQL 更新、HTTP 调用或邮件发送纳入同一个 Kafka 事务。

写入外部系统时，需要对方提供配合机制，例如在事务内保存输出与恢复位置，或提供幂等接口、唯一约束及其他明确协议。数据库事务完成但位点提交失败时，可以允许重读，再通过业务去重维持单次效果。

| 机制                               | 保证覆盖的操作                                                                           |
| ---------------------------------- | ---------------------------------------------------------------------------------------- |
| Producer Idempotence（生产者幂等） | `enable.idempotence=true` 在适用条件下去除发送重试导致的重复追加，数据库写入仍由业务控制 |
| Kafka Transaction（Kafka 事务）    | 协调 Kafka 输出和适用的消费位点，见[第 14 章](/articles/kafka-transactions.html)         |
| Business Idempotency（业务幂等）   | 下游通过唯一键、原子状态更新或幂等协议，让重复操作维持同一业务效果                       |

## 5. 异常隔离、位点推进与修复路径 {#_5-死信与异常处理不等于成功完成}

不可解析事件可以隔离，但隔离记录要包含足够的来源与错误线索，同时保护敏感数据。是否随后推进位点，取决于业务是否接受人工修复或补偿路径，不能为压低 lag 把所有失败都静默送死信。

重试 Topic 可能改变原 Key 的严格处理顺序；一条失败后让后续事件先完成，可能破坏状态机。设计时应在可用性、顺序和修复效率之间做明确选择。第 24 章把这些条件放回同一个案例。

Dead Letter Queue（死信队列，DLQ）保留需要另行处置的失败事件。不可解析消息应保留可定位的原始来源及错误。可重试业务错误和暂时性外部故障可先按上限和退避策略重试。永久失败或重试耗尽的事件，按明确规则转入 DLQ 并告警。需维持同 Key 顺序时，可以让后续事件等待，或由业务状态机验证是否允许越过失败项。

只有在隔离记录已持久化、业务接受后续修复，且该分区前序工作也已完成或按策略处置时，才推进位点。独立写 DLQ 再提交位点会有重复隔离窗口，可用原始 Topic、Partition、Offset 去重，或在同一 Kafka 事务内提交 DLQ 写入与位点。DLQ 持久化表示失败已移交，原业务仍待处理。重放应保留原事件 ID，修正坏数据后验证业务状态。已产生且不能撤销的副作用需要按业务规则人工核对或补偿。

## 参考

- [PostgreSQL 16 INSERT 与 ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html)
- [PostgreSQL 16 事务隔离](https://www.postgresql.org/docs/16/transaction-iso.html)

- [Kafka 3.9 消息语义设计](https://kafka.apache.org/39/design/design/#message-delivery-semantics)
- [Kafka Streams 语义说明](https://kafka.apache.org/39/streams/core-concepts/)
