---
id: kafka-c-producer
title: 第 16 章：C 生产者、回调与背压
description: 客户端的后台线程负责网络 I/O，因此不能说“不 poll 就完全不发消息”。不过，应用仍需持续调用 poll 或处理相应队列中的事件，让投递报告和其他事件得到处理；否则，应用无法获知结果，消息资源也不能及时回收，最终可能形成背压。
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
order: 16
---

# 第 16 章：C 生产者、回调与背压

> 版本导航：librdkafka v2.8.0 C API。
>
> 学习目标：识别立即入队结果和最终投递结果，正确管理 Payload 与回调。片段为教学示例，不是已编译运行的完整程序。

## 1. 同一次发送有两个观察阶段

`rd_kafka_produce()` 返回 0 表示接受进入适用的异步发送流程；返回 -1 表示发生立即错误，应读取客户端错误码。接受入队后仍可能最终失败，必须通过 Delivery Report 了解最终结果。

客户端的后台线程负责网络 I/O，因此不能说“不 poll 就完全不发消息”。不过，应用仍需持续调用 poll 或处理相应队列中的事件，让投递报告和其他事件得到处理；否则，应用无法获知结果，消息资源也不能及时回收，最终可能形成背压。

[![librdkafka Producer：COPY、FREE 与借用所有权](/assets/notes/kafka/kf-cproducer.svg)](/assets/notes/kafka/kf-cproducer.svg)

## 2. 三种 Payload 归属

COPY 表示库会复制 Payload，调用返回后，原缓冲可按应用规则继续使用。FREE 表示成功接受后由库按契约负责释放，因此必须传入可按该契约释放的分配，不能传入栈内存。若立即返回失败，即使使用了 FREE，Payload 仍由调用方负责。

两种标记都不使用时，Payload 的底层内存需要保持有效且不被修改，直到适用投递回调发生。不能发送指向循环里复用的一块缓冲，然后下一次迭代就改写内容。COPY 和 FREE 不应同时设置。

## 3. 回调只观察借用消息

以下片段假定 opaque 指向仍存活的应用计数对象，且回调在应用选择的受控线程中被服务。多线程扩展要自行同步计数。没有在本机编译执行。

```c
struct delivery_counts { size_t ok; size_t failed; };

static void on_delivery(rd_kafka_t *rk,
                        const rd_kafka_message_t *m, void *opaque) {
    struct delivery_counts *counts = opaque;
    (void)rk;
    if (m->err) counts->failed++;
    else        counts->ok++;
    /* m is borrowed: do not destroy or retain its payload pointer. */
}
```

实际程序还需在创建客户端前注册回调与 opaque，检查所有配置错误，并将投递失败交给明确的恢复路径。这里的计数不会自动保存失败消息内容，也不替业务完成持久化待发记录。

## 4. Queue Full 需要可结束的策略

立即失败为队列满时，可服务事件并有界等待，再按剩余预算重试；也可停止接收上游负载。无上限忙循环会占用 CPU、放大故障，并可能让真正需要执行的回调得不到机会。

若使用 BLOCK 标记，更要满足库对持续处理回调的要求。否则，发送线程可能一直等待空闲空间，而空间的释放又依赖同一线程已无法执行的回调。生产者队列、应用待发队列和业务重试存储应分别设置边界。

## 5. Flush 与成功统计一起检查

结束前先停新输入，再使用有界 flush 并检查返回值。即使队列排空，里面也可能有最终失败的记录，因此仍需检查投递报告与失败计数。flush 超时后直接 destroy 会留下未完成数据，必须记录并走应用的恢复策略。

不要把“flush 返回后没有崩溃”当成全部订单事件已可靠写入。前面的 Outbox 或稳定事件记录可帮助识别未确认工作，但重发时仍要考虑业务重复。

## 参考

- [v2.8.0 Producer API 与内存标记](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)
- [librdkafka 消息可靠性与线程模型](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
