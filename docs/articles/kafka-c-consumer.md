---
id: kafka-c-consumer
title: 第 17 章：C 消费者、处理完成与提交
description: 先配置 group.id、创建消费者并设置相应的消费队列，再订阅 Topic。Subscribe 返回并不表示消费组已经完成协调，也不表示每个 Topic 都已获授权；错误还可能通过后续事件报告。
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
order: 17
---

# 第 17 章：C 消费者、处理完成与提交

> 版本导航：librdkafka v2.8.0 C API。
>
> 学习目标：建立一条明确的串行处理路线，再理解异步扩展需要增加哪些状态。本章使用 High-level Consumer，不混用 legacy Simple Consumer API。

## 1. 订阅后不一定立即有分配

先配置 group.id、创建消费者并设置相应的消费队列，再订阅 Topic。Subscribe 返回并不表示消费组已经完成协调，也不表示每个 Topic 都已获授权；错误还可能通过后续事件报告。

持续调用 `rd_kafka_consumer_poll()`，既读取业务消息，也服务适用客户端事件。返回 NULL 表示这次等待没有取得消息，不是 Topic 已永久结束。非 NULL 也可能表示错误，先检查 err，不能直接解析 Payload。

![处理、位点与对象释放](/assets/notes/kafka/kf-cconsumer.svg)

## 2. 一条易于推理的串行路线

为避免位点先于处理，本例假定 `enable.auto.commit=false`、`enable.auto.offset.store=false`，每个分区记录按交付顺序串行处理，不含工作线程池。代码只演示一个分支，省略创建、订阅、错误分类和业务实现；没有编译运行。

```c
/* Teaching fragment: all setup/error paths are outside this snippet. */
rd_kafka_message_t *m = rd_kafka_consumer_poll(consumer, 100);
if (m != NULL) {
    if (m->err == RD_KAFKA_RESP_ERR_NO_ERROR) {
        if (apply_idempotent_business(m) == 0) {
            rd_kafka_resp_err_t err =
                rd_kafka_commit_message(consumer, m, 0);
            if (err != RD_KAFKA_RESP_ERR_NO_ERROR)
                record_commit_failure(err);
        } else {
            stop_partition_work_and_recover(m);
        }
    } else {
        handle_consumer_event(m);
    }
    rd_kafka_message_destroy(m);
}
```

`apply_idempotent_business` 等函数是待实现的业务边界，不是 librdkafka API。失败恢复函数必须在继续推进该分区前建立可靠策略，不能只是打印一行日志后继续提交后面的消息。提交消息 API 内部采用消息 Offset+1，本例不再手工加一。

## 3. 为什么不推荐逐条同步提交作为最终性能方案

逐条同步等待便于初学时理解流程，但会增加网络往返与延迟。实际可以按安全批次提交，或在保存已完成前沿后周期提交。批次越大，崩溃时可能重放的窗口也越大，因此需要结合业务幂等和恢复目标权衡。

提交失败不能随意忽略。重平衡已发生、协调者变化、超时或授权错误需要不同策略；无条件重试旧分配的提交可能没有意义。保留来源分区、位点和业务 ID 的诊断关联，但不要泄露 Payload 中的敏感内容。

## 4. 异步扩展不能只换一个线程池

异步任务要在消息对象释放前复制需要的字节，或明确延长对象生命周期。同时维护每分区的任务序列、连续完成前沿、暂停与恢复、撤销后的取消或 fencing。

即使 102 先完成，也不能让它覆盖尚未完成的 101。关闭自动 Store 是起点，不是完整答案；应用仍可能把错误的最大位置传给手动提交。第 11 章的前沿规则应成为测试用例。

另外，主线程持续调用 consumer_poll，而工作线程长期卡住时，max.poll.interval 并不会发现业务已停止推进。应分别监测前沿停滞、最老任务和队列容量；撤销和关闭时按[下一章的状态表](/articles/kafka-c-rebalance-shutdown.html)交接，不能用持续 poll 掩盖业务超时。

## 参考

- [v2.8.0 consumer_poll 与 commit_message](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)
- [v2.8.0 Auto Store 与 Auto Commit](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)

## 联读

消费生命周期联读：[分配/撤销、关闭契约与状态表](/articles/kafka-c-rebalance-shutdown.html)。
