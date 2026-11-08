---
id: kafka-c-producer
title: 第 16 章：C 生产者、回调与背压
description: "rd_kafka_produce() 返回 0 表示接受进入适用的异步发送流程；返回 -1 表示发生立即错误，应读取客户端错误码。"
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
> 学习目标：识别立即入队结果和最终投递结果，正确管理 Payload 与回调。

## 1. 同一次发送有两个观察阶段

`rd_kafka_produce()` 返回 0 表示接受进入适用的异步发送流程；返回 -1 表示发生立即错误，应读取客户端错误码。接受入队后仍可能最终失败，必须通过 Delivery Report 了解最终结果。

客户端后台线程负责网络 I/O，应用通过持续 poll 或处理相应事件队列，服务投递报告与其他事件。这两条工作线共同完成发送和结果回收；事件长期未处理时，应用无法及时获知结果或回收消息资源，可能形成背压。

[![librdkafka Producer：COPY、FREE 与借用所有权](/assets/notes/kafka/kf-cproducer.svg)](/assets/notes/kafka/kf-cproducer.svg)

以订单事件为例，应用线程调用 `rd_kafka_produce()`，成功入队后由后台线程组装并发送 Produce 请求。Broker 按确认策略处理请求，客户端可在消息时限内重试适用错误。成功或最终失败后，客户端安排 Delivery Report（投递报告）。应用线程通过 `rd_kafka_poll()` 服务回调并更新订单事件的发送状态，退出前再回收剩余结果。立即失败的消息没有入队，也没有对应的投递报告。入队、Broker 投递和下游订单处理是三个独立阶段。

## 2. 三种 Payload 归属

COPY 表示库会复制 Payload，调用返回后，原缓冲可按应用规则继续使用。FREE 表示成功接受后由库按契约负责释放，因此必须传入可按该契约释放的分配，不能传入栈内存。若立即返回失败，即使使用了 FREE，Payload 仍由调用方负责。

两种标记都不使用时，Payload 的底层内存需要保持有效且不被修改，直到适用投递回调发生。不能发送指向循环里复用的一块缓冲，然后下一次迭代就改写内容。COPY 和 FREE 不应同时设置。

以下片段假定 `topic`、长度 `len` 和合法缓冲已准备好。Key 在 `rd_kafka_produce()` 返回后可复用，以下标志只影响 Payload。

```c
/* COPY：stack_buf 可在调用返回后改写，两种结果都不转移原缓冲。 */
int rc = rd_kafka_produce(topic, RD_KAFKA_PARTITION_UA,
                         RD_KAFKA_MSG_F_COPY, stack_buf, len, NULL, 0, NULL);

/* FREE：heap_buf 来自与库兼容的 malloc 分配。 */
rc = rd_kafka_produce(topic, RD_KAFKA_PARTITION_UA,
                      RD_KAFKA_MSG_F_FREE, heap_buf, len, NULL, 0, NULL);
if (rc == -1)
    free(heap_buf); /* 也可保留后按预算重试。 */
heap_buf = NULL;

/* 借用：成功后保留 borrowed，直到报告处理时再由应用回收。 */
rc = rd_kafka_produce(topic, RD_KAFKA_PARTITION_UA,
                      0, borrowed, len, NULL, 0, borrowed);
if (rc == -1)
    free(borrowed);
```

借用示例要求投递回调在使用完报告中的 Payload 后释放其 `m->_private` 指向的自有缓冲，或者由应用在 Destroy 后清理没有报告的缓冲。FREE 不能传栈缓冲，借用也不能传调用返回后立即失效的栈地址。COPY 和 FREE 不能组合。投递回调只在调用期间借用消息和其中的 Key、Payload，无权销毁消息或释放库持有的内存。

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

## 4. Queue Full 时的有界等待与上游背压 {#_4-queue-full-需要可结束的策略}

立即失败为队列满时，可服务事件并有界等待，再按剩余预算重试；也可停止接收上游负载。无上限忙循环会占用 CPU、放大故障，并可能让真正需要执行的回调得不到机会。

若使用 BLOCK 标记，更要满足库对持续处理回调的要求。否则，发送线程可能一直等待空闲空间，而空间的释放又依赖同一线程已无法执行的回调。生产者队列、应用待发队列和业务重试存储应分别设置边界。

`rd_kafka_last_error() == RD_KAFKA_RESP_ERR__QUEUE_FULL` 表示该次没有入队。队列条数由 `queue.buffering.max.messages` 限制，字节预算由 `queue.buffering.max.kbytes` 限制，后者在 v2.8.0 配置中优先。输入比网络出队快时，先停止接收新工作，服务回调，再用有限次数和递增的 Poll 等待重试当前未入队记录。预算耗尽后把未入队事件留在 Outbox（持久化待发记录）或向上游明确返回失败。已入队的事件由库按配置内部重试。收到最终失败后再决定业务恢复，重发使用稳定事件 ID。

错误的单线程结构是先执行带 `RD_KAFKA_MSG_F_BLOCK` 的 Produce，再指望同一线程下一行 Poll 腾出空间。队列满时这一行可能永远到不了。需要 BLOCK 时，应先启动独立的事件服务线程持续 Poll，发送线程停止取入新事件后，仍让该线程服务已接受的消息，直到发送线程退出并完成收尾，再停止并 join 服务线程。BLOCK 自身没有单次等待参数，停机标志不能解除已阻塞的 Produce。需要可控入队预算时，使用下方的非 BLOCK 方案。若 Flush 也会服务回调，须约束回调线程或同步共享状态。

## 5. Flush 与成功统计一起检查

结束前先停新输入，再使用有界 flush 并检查返回值。即使队列排空，里面也可能有最终失败的记录，因此仍需检查投递报告与失败计数。flush 超时后直接 destroy 会留下未完成数据，必须记录并走应用的恢复策略。

结束时结合 flush 返回值、投递报告与失败计数确认发送结果。Outbox 或稳定事件记录可用于找出未确认工作，再按业务去重协议恢复发送。

### 实践：发送带稳定事件 ID 的订单

用 Kafka 3.9 和 librdkafka v2.8.0。在 Linux 安装 GCC、pkg-config 以及固定版本的 librdkafka 开发头文件和库，例如检出官方 `v2.8.0` 后按其构建说明安装。确认 `pkg-config --modversion rdkafka` 输出 2.8.0。若实验 Topic 已存在，先确认它有三个分区。

```bash
bin/kafka-topics.sh --bootstrap-server localhost:9092 --create \
  --topic review-orders --partitions 3 --replication-factor 1
cc -std=c11 -Wall -Wextra -Wpedantic orders_producer.c \
  $(pkg-config --cflags --libs rdkafka) -o orders_producer
./orders_producer localhost:9092 run01
```

将下面保存为 `orders_producer.c`。每个实验使用新的运行前缀。恢复同一批事件时保留原前缀。示例仅用内存保存投递状态，退出时用事件 ID 输出恢复线索，生产应用应持久化待发事件及其结果。

```c
#include <librdkafka/rdkafka.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum outcome { UNSENT, PENDING, DELIVERED, FAILED };
struct order { char id[64]; enum outcome state; };
struct counts { int accepted, delivered, failed; };

static void delivery(rd_kafka_t *rk, const rd_kafka_message_t *msg,
                     void *opaque) {
    (void)rk;
    struct counts *counts = opaque;
    struct order *order = msg->_private;
    order->state = msg->err ? FAILED : DELIVERED;
    if (msg->err) {
        ++counts->failed;
        fprintf(stderr, "delivery %s: %s\n", order->id,
                rd_kafka_err2str(msg->err));
    } else {
        ++counts->delivered;
        printf("delivered %s\n", order->id);
    }
}

int main(int argc, char **argv) {
    if (argc != 3 || strlen(argv[2]) > 48 ||
        strspn(argv[2], "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_")
            != strlen(argv[2])) {
        fprintf(stderr, "usage: %s BROKERS RUN_ID\n", argv[0]);
        return EXIT_FAILURE;
    }
    struct counts counts = {0, 0, 0};
    struct order orders[8];
    char error[512];
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    rd_kafka_t *rk = NULL;
    rd_kafka_topic_t *topic = NULL;
    int status = EXIT_FAILURE;
    const char *settings[][2] = {
        {"bootstrap.servers", argv[1]}, {"enable.idempotence", "true"},
        {"acks", "all"}, {"message.timeout.ms", "6000"},
        {"queue.buffering.max.messages", "1"},
        {"queue.buffering.max.kbytes", "64"}
    };
    for (size_t i = 0; i < sizeof(settings) / sizeof(settings[0]); ++i) {
        if (rd_kafka_conf_set(conf, settings[i][0], settings[i][1],
                              error, sizeof(error)) != RD_KAFKA_CONF_OK) {
            fprintf(stderr, "%s: %s\n", settings[i][0], error);
            goto cleanup;
        }
    }
    rd_kafka_conf_set_dr_msg_cb(conf, delivery);
    rd_kafka_conf_set_opaque(conf, &counts);
    rk = rd_kafka_new(RD_KAFKA_PRODUCER, conf, error, sizeof(error));
    if (!rk) {
        fprintf(stderr, "producer: %s\n", error);
        goto cleanup;
    }
    conf = NULL;
    topic = rd_kafka_topic_new(rk, "review-orders", NULL);
    if (!topic) {
        fprintf(stderr, "topic: %s\n", rd_kafka_err2str(rd_kafka_last_error()));
        goto cleanup;
    }

    for (int i = 0; i < 8; ++i) {
        snprintf(orders[i].id, sizeof(orders[i].id), "%s-%d", argv[2], i);
        orders[i].state = UNSENT;
    }

    for (int i = 0; i < 8; ++i) {
        struct order *order = &orders[i];
        char payload[256];
        const char key[] = "order-001";
        int len = snprintf(payload, sizeof(payload),
            "{\"event_id\":\"%s\",\"order_id\":\"%s\","
            "\"event_type\":\"PAYMENT_CONFIRMED\",\"amount\":100}",
            order->id, key);
        if (len < 0 || (size_t)len >= sizeof(payload))
            break;

        for (int attempt = 0; attempt < 6; ++attempt) {
            if (rd_kafka_produce(topic, RD_KAFKA_PARTITION_UA,
                                 RD_KAFKA_MSG_F_COPY, payload, (size_t)len,
                                 key, sizeof(key) - 1, order) == 0) {
                order->state = PENDING;
                ++counts.accepted;
                printf("accepted %s\n", order->id);
                break;
            }
            rd_kafka_resp_err_t err = rd_kafka_last_error();
            fprintf(stderr, "enqueue %s: %s\n", order->id, rd_kafka_err2str(err));
            if (err != RD_KAFKA_RESP_ERR__QUEUE_FULL)
                break;
            rd_kafka_poll(rk, 25 << attempt);
        }
        if (order->state == UNSENT)
            break;
        rd_kafka_poll(rk, 0);
    }

    rd_kafka_resp_err_t flush = rd_kafka_flush(rk, 3000);
    if (flush)
        fprintf(stderr, "flush: %s\n", rd_kafka_err2str(flush));
    int outstanding = counts.accepted - counts.delivered - counts.failed;
    printf("accepted=%d delivered=%d failed=%d outstanding=%d\n",
           counts.accepted, counts.delivered, counts.failed, outstanding);
    for (int i = 0; i < 8; ++i) {
        if (orders[i].state != DELIVERED)
            fprintf(stderr, "recovery %s: %s\n", orders[i].id,
                    orders[i].state == PENDING ? "unconfirmed" :
                    orders[i].state == FAILED ? "delivery-error" : "not-enqueued");
    }
    if (!flush && counts.delivered == 8)
        status = EXIT_SUCCESS;

cleanup:
    if (topic) rd_kafka_topic_destroy(topic);
    if (rk) rd_kafka_destroy(rk);
    if (conf) rd_kafka_conf_destroy(conf);
    return status;
}
```

`rd_kafka_conf_set_opaque()` 设置客户端级计数上下文。每次发送的 `msg_opaque` 由报告中的 `_private` 返回，指向数组中的对应订单。数组与计数在 Destroy 返回后才离开作用域。唯一服务回调的应用线程负责修改计数，回调只记录结果，实际系统可将耗时持久化移出回调。

正常预期 8 条被接受并收到成功报告。可用不可达的测试地址运行，观察小队列触发 Queue Full、停止收新输入以及 Flush 未确认事件。Flush 超时不能判定所有未确认事件都未写入。投递错误也应保存原始错误和事件 ID，再按故障原因决定如何恢复。以上实验尚未联机实测。

`accepted` 只计入队成功，`delivered` 和 `failed` 只计收到的报告，`outstanding` 是已接受但尚未报告的差值。v2.8.0 的 `enable.idempotence` 要求 `acks=all` 等兼容设置，`retry.backoff.ms` 控制库内部协议重试的初始退避，`message.timeout.ms` 限制库为单条消息投入的本地总时间。示例的 Poll 预算只约束入队重试，Flush 预算只约束退出等待。

## 参考

- [librdkafka v2.8.0 配置](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)
- [Kafka 3.9 Topic 管理命令](https://kafka.apache.org/39/operations/basic-kafka-operations/)

- [v2.8.0 Producer API 与内存标记](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)
- [librdkafka 消息可靠性与线程模型](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
