---
id: kafka-c-consumer
title: 第 17 章：C 消费者、处理完成与提交
description: "先配置 group.id、创建消费者并设置相应的消费队列，再订阅 Topic。Subscribe 返回并不表示消费组已经完成协调，也不表示每个 Topic 都已获授权；错误还可能通过后续事件报告。"
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
order: 17
---

# 第 17 章：C 消费者、处理完成与提交

> 版本导航：librdkafka v2.8.0 C API。
>
> 学习目标：建立一条明确的串行处理路线，再理解异步扩展需要增加哪些状态。本章使用 High-level Consumer，不混用 legacy Simple Consumer API。

## 1. 配置、订阅与持续处理消费事件 {#_1-订阅后不一定立即有分配}

先配置 group.id、创建消费者并设置相应的消费队列，再订阅 Topic。Subscribe 返回并不表示消费组已经完成协调，也不表示每个 Topic 都已获授权；错误还可能通过后续事件报告。

持续调用 `rd_kafka_consumer_poll()`，既读取业务消息，也服务适用客户端事件。返回 NULL 表示这次等待没有取得消息，不是 Topic 已永久结束。非 NULL 也可能表示错误，先检查 err，不能直接解析 Payload。

[![C Consumer：连续完成前沿与 Offset Store](/assets/notes/kafka/kf-cconsumer.svg)](/assets/notes/kafka/kf-cconsumer.svg)

初始化使用 `rd_kafka_poll_set_consumer()`，把主事件队列重定向到 High-level Consumer 队列，使消费线程也能服务相关回调。重定向后使用 `rd_kafka_consumer_poll()`，不得再对同一客户端调用 `rd_kafka_poll()`。库默认处理分配，注册自定义 Rebalance Callback 后则由应用履行分配契约。停止信号通过应用标志处理，NULL 本身不表示停止。

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

### 实践：串行处理订单并验证重放

使用 Kafka 3.9、Linux C11、GCC、pkg-config 和 librdkafka v2.8.0 开发包。创建三分区的 `review-orders`，发送[第 16 章](/articles/kafka-c-producer.html)的示例事件。若采用单 Broker，还需满足[内部位点 Topic 的创建条件](/articles/kafka-log-model.html)。以下程序只接受该示例的固定 JSON 格式。它用打开事件 ID 对应的空文件（追加模式但不写入）作为可检查的幂等业务效果，验证进程重启时的重复投递。文件必须位于受控的持久目录。这个实验不模拟主机掉电，也没有把其他业务副作用纳入文件操作。正式写库可使用[第 13 章](/articles/kafka-delivery-semantics.html)的原子去重事务。

保存为 `orders_consumer.c`。正常运行时收到 SIGINT 或 SIGTERM 后退出。设置 `FAIL_EVENT` 可在业务前注入失败，设置 `EXIT_BEFORE_COMMIT` 可在文件已建立后模拟进程突然退出。

```c
#include <librdkafka/rdkafka.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static volatile sig_atomic_t stopping;
static void stop(int sig) { (void)sig; stopping = 1; }

static int apply(const rd_kafka_message_t *m, char id[64]) {
    char payload[256], path[96];
    int parsed = 0;
    if (!m->payload || m->len >= sizeof(payload))
        return -1;
    memcpy(payload, m->payload, m->len);
    payload[m->len] = '\0';
    if (sscanf(payload, "{\"event_id\":\"%63[a-zA-Z0-9_-]\","
                       "\"order_id\":\"order-001\","
                       "\"event_type\":\"PAYMENT_CONFIRMED\",\"amount\":100}%n",
               id, &parsed) != 1 || (size_t)parsed != m->len)
        return -1;
    const char *fail = getenv("FAIL_EVENT");
    if (fail && strcmp(fail, id) == 0)
        return -1;
    snprintf(path, sizeof(path), "order-effects/%s", id);
    FILE *effect = fopen(path, "a");
    return effect && fclose(effect) == 0 ? 0 : -1;
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s BROKERS GROUP\n", argv[0]);
        return EXIT_FAILURE;
    }
    if (signal(SIGINT, stop) == SIG_ERR || signal(SIGTERM, stop) == SIG_ERR) {
        perror("signal");
        return EXIT_FAILURE;
    }
    char error[512];
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    rd_kafka_t *rk = NULL;
    rd_kafka_topic_partition_list_t *topics = NULL;
    int status = EXIT_FAILURE;
    const char *settings[][2] = {
        {"bootstrap.servers", argv[1]}, {"group.id", argv[2]},
        {"group.protocol", "classic"}, {"auto.offset.reset", "earliest"},
        {"enable.auto.commit", "false"}, {"enable.auto.offset.store", "false"},
        {"allow.auto.create.topics", "false"}
    };
    for (size_t i = 0; i < sizeof(settings) / sizeof(settings[0]); ++i) {
        if (rd_kafka_conf_set(conf, settings[i][0], settings[i][1],
                              error, sizeof(error)) != RD_KAFKA_CONF_OK) {
            fprintf(stderr, "%s: %s\n", settings[i][0], error);
            goto cleanup;
        }
    }
    rk = rd_kafka_new(RD_KAFKA_CONSUMER, conf, error, sizeof(error));
    if (!rk) {
        fprintf(stderr, "consumer: %s\n", error);
        goto cleanup;
    }
    conf = NULL;
    rd_kafka_resp_err_t err = rd_kafka_poll_set_consumer(rk);
    if (err) {
        fprintf(stderr, "redirect poll: %s\n", rd_kafka_err2str(err));
        goto cleanup;
    }
    topics = rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(topics, "review-orders", RD_KAFKA_PARTITION_UA);
    err = rd_kafka_subscribe(rk, topics);
    rd_kafka_topic_partition_list_destroy(topics);
    topics = NULL;
    if (err) {
        fprintf(stderr, "subscribe: %s\n", rd_kafka_err2str(err));
        goto cleanup;
    }

    status = EXIT_SUCCESS;
    while (!stopping) {
        rd_kafka_message_t *m = rd_kafka_consumer_poll(rk, 200);
        if (!m)
            continue;
        if (stopping) {
            rd_kafka_message_destroy(m);
            break;
        }
        if (m->err) {
            switch (m->err) {
            case RD_KAFKA_RESP_ERR__PARTITION_EOF:
                break;
            case RD_KAFKA_RESP_ERR__TRANSPORT:
            case RD_KAFKA_RESP_ERR__ALL_BROKERS_DOWN:
                fprintf(stderr, "waiting for broker: %s\n", rd_kafka_message_errstr(m));
                break;
            case RD_KAFKA_RESP_ERR__UNKNOWN_TOPIC:
            case RD_KAFKA_RESP_ERR_UNKNOWN_TOPIC_OR_PART:
            case RD_KAFKA_RESP_ERR_TOPIC_AUTHORIZATION_FAILED:
            case RD_KAFKA_RESP_ERR_GROUP_AUTHORIZATION_FAILED:
                fprintf(stderr, "check Topic and ACL: %s\n", rd_kafka_message_errstr(m));
                status = EXIT_FAILURE;
                break;
            case RD_KAFKA_RESP_ERR__AUTO_OFFSET_RESET:
            case RD_KAFKA_RESP_ERR_OFFSET_OUT_OF_RANGE:
                fprintf(stderr, "check recovery offset: %s\n", rd_kafka_message_errstr(m));
                status = EXIT_FAILURE;
                break;
            default:
                fprintf(stderr, "stop on consumer error: %s\n", rd_kafka_message_errstr(m));
                status = EXIT_FAILURE;
                break;
            }
        } else {
            char id[64] = {0};
            if (apply(m, id)) {
                fprintf(stderr, "business failure P%d offset %lld\n",
                        (int)m->partition, (long long)m->offset);
                status = EXIT_FAILURE;
            } else {
                printf("business complete %s P%d offset %lld\n",
                       id, (int)m->partition, (long long)m->offset);
                const char *crash = getenv("EXIT_BEFORE_COMMIT");
                if (crash && strcmp(crash, id) == 0)
                    _Exit(2); /* 故障注入，故意跳过正常收尾。 */
                err = rd_kafka_commit_message(rk, m, 0);
                if (err) {
                    fprintf(stderr, "commit %s: %s\n", id, rd_kafka_err2str(err));
                    status = EXIT_FAILURE;
                }
            }
        }
        rd_kafka_message_destroy(m);
        if (status != EXIT_SUCCESS)
            break;
    }

cleanup:
    if (topics) rd_kafka_topic_partition_list_destroy(topics);
    if (rk) {
        rd_kafka_resp_err_t close_err = rd_kafka_consumer_close(rk);
        if (close_err) {
            fprintf(stderr, "close: %s\n", rd_kafka_err2str(close_err));
            status = EXIT_FAILURE;
        }
        rd_kafka_destroy(rk);
    }
    if (conf) rd_kafka_conf_destroy(conf);
    return status;
}
```

```bash
pkg-config --modversion rdkafka
cc -std=c11 -Wall -Wextra -Wpedantic orders_consumer.c \
  $(pkg-config --cflags --libs rdkafka) -o orders_consumer
mkdir -p order-effects
EXIT_BEFORE_COMMIT=run01-0 ./orders_consumer localhost:9092 review-c-orders
./orders_consumer localhost:9092 review-c-orders
```

使用新组做实验，重启时保留同一工作目录和组 ID。预期 `run01-0` 被重新读取，同一事件 ID 的文件仍只有一个。另用新组设置 `FAIL_EVENT=run01-1`，预期失败项没有提交，移除环境变量重启后可继续处理。

分区 EOF 只是当前读到末端。临时传输或 Broker 不可达错误可以继续 Poll 等待重连。Topic 不存在或授权失败应停下核对名称、ACL 和订阅。初始位置缺失或越界时，示例的 `earliest` 会应用重置策略。若不能接受自动跳过保留范围外的历史，应改用 `error`，把 `RD_KAFKA_RESP_ERR__AUTO_OFFSET_RESET` 等位置错误转入人工恢复。本例对其余错误停机，保留已提交恢复点。

## 3. 从逐条同步提交到安全批次提交 {#_3-为什么不推荐逐条同步提交作为最终性能方案}

逐条同步等待便于初学时理解流程，但会增加网络往返与延迟。实际可以按安全批次提交，或在保存已完成前沿后周期提交。批次越大，崩溃时可能重放的窗口也越大，因此需要结合业务幂等和恢复目标权衡。

提交失败不能随意忽略。重平衡已发生、协调者变化、超时或授权错误需要不同策略；无条件重试旧分配的提交可能没有意义。保留来源分区、位点和业务 ID 的诊断关联，但不要泄露 Payload 中的敏感内容。

| API 或配置                              | 语义                                                                                                    |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------- |
| `enable.auto.offset.store`              | 自动将交付进度记入本地 Offset Store（位点存储），异步业务通常关闭                                       |
| `enable.auto.commit`                    | 周期性提交本地存储位置到 Broker，与自动 Store 独立                                                      |
| `rd_kafka_offsets_store(rk, list)`      | 关闭自动 Store 后手工存入列表里的下一位置，检查整体及逐项结果。此调用本身不写 Broker                    |
| `rd_kafka_commit_message(rk, m, async)` | 用原始消息的 Offset 加一提交，调用方不再加一                                                            |
| `rd_kafka_commit(rk, list, async)`      | 列表直接填写每分区的下一位置。NULL 使用当前分配对应的本地存储位置                                       |
| `rd_kafka_conf_set_offset_commit_cb()`  | 注册提交结果回调，继续 Consumer Poll 服务。异步调用成功返回表示已安排请求，需检查回调错误及适用分区结果 |

批次伪代码：每分区业务成功时更新其安全前沿。每处理 50 条或每秒构造一个自有分区列表，仅纳入仍持有且前沿有变化的分区。若 P0 已安全处理到 100，P1 到 54，则分别填 101 和 55，调用 `rd_kafka_commit(rk, list, 0)` 后销毁列表。只在确认成功后记录相应提交进度。异步方案应限制未完成提交，保存请求位置和本地分配世代。撤销后旧回调可以记诊断信息，但不能更新新所有权的状态或触发历史位点重试。需要逐请求上下文时可用 `rd_kafka_commit_queue()`。减少提交次数会扩大重放窗口，业务幂等仍需覆盖该窗口。

## 4. 异步消费的对象生命周期与完成前沿 {#_4-异步扩展不能只换一个线程池}

异步任务要在消息对象释放前复制需要的字节，或明确延长对象生命周期。同时维护每分区的任务序列、连续完成前沿、暂停与恢复、撤销后的取消或 fencing。

即使 102 先完成，也不能让它覆盖尚未完成的 101。关闭自动 Store 是起点，不是完整答案；应用仍可能把错误的最大位置传给手动提交。第 11 章的前沿规则应成为测试用例。

另外，主线程持续调用 consumer_poll，而工作线程长期卡住时，max.poll.interval 并不会发现业务已停止推进。应分别监测前沿停滞、最老任务和队列容量；撤销和关闭时按[下一章的状态表](/articles/kafka-c-rebalance-shutdown.html)交接，不能用持续 poll 掩盖业务超时。

若 P0 的 100 已成功、101 失败而 102 已经交付，串行示例会停机，保留 101 为恢复点。若需要让其他分区继续，应只暂停 P0 并继续 Poll。已经交给应用的 P0 任务需保留或隔离。有限重试成功后再恢复，永久失败只在[隔离策略](/articles/kafka-delivery-semantics.html)满足后推进。若要 Seek，先确认仍持有分区，停止派发并清理旧缓冲和在途结果，再用 `rd_kafka_seek_partitions()` 设置有效位置，检查整体错误对象及逐分区结果。Seek 只改变读取位置，业务外部效果仍需幂等。

Worker Pool（工作线程池）使用有界队列，Poll 线程先按分区登记交付顺序，再派发必要的 Payload 和 Key 副本。容量不足时 Pause，回落后 Resume，并持续服务组事件。100 和 102 完成但 101 未完成时，前沿仍为 101。101 完成后，才可从队首连续移除 101、102，推进到 103。处理日志空洞时按实际交付的记录顺序推进，见[第 11 章](/articles/kafka-offset-watermarks.html)。撤销时停止派发，用分配世代隔离迟到结果，超时请求交由下游幂等或 Fencing（隔离旧执行者）约束。

诊断时分开观察 `rd_kafka_position()` 的交付位置、`rd_kafka_committed()` 的恢复位置和应用完成前沿。Consumer Lag 是指定末端与已提交位置的距离，受末端口径、提交批次和 Offset 空洞影响。最老任务年龄、前沿停滞时间和队列长度反映业务背压，提交错误次数反映恢复点是否能正常推进。

## 参考

- [v2.8.0 consumer_poll 与 commit_message](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)
- [v2.8.0 Auto Store 与 Auto Commit](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)

## 联读

消费生命周期联读：[分配/撤销、关闭契约与状态表](/articles/kafka-c-rebalance-shutdown.html)。
