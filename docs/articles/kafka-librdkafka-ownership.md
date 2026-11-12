---
id: kafka-librdkafka-ownership
title: 第 15 章：librdkafka 对象与内存所有权
description: "rd_kafka_t 是客户端实例；rd_kafka_conf_t 是全局客户端配置；rd_kafka_topic_t 是本地 Topic 句柄；rd_kafka_topic_partition_list_t 是 Topic-Partition 条目容器。"
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
order: 15
---

# 第 15 章：librdkafka 对象与内存所有权

> 版本导航：librdkafka v2.8.0 C API。
>
> 学习目标：从接口清单进一步理解对象关系与生命周期。范围固定为 librdkafka v2.8.0 C API；cppkafka、Python 封装和 Java 不是同一个接口。

## 1. 四类对象及其职责 {#_1-四类对象先建立心智模型}

`rd_kafka_t` 是客户端实例；`rd_kafka_conf_t` 是全局客户端配置；`rd_kafka_topic_t` 是本地 Topic 句柄；`rd_kafka_topic_partition_list_t` 是 Topic-Partition 条目容器。它们不是网络上某个实体的直接指针，也不应由应用自行复制内部结构。

创建本地 Topic 句柄不等于显式执行 Admin CreateTopics。后续访问元数据时是否触发自动创建 Topic，还取决于服务端和客户端设置，因此不能把 `rd_kafka_topic_new()` 当成可靠的集群建 Topic 操作。

![C 对象与归属规则](/assets/notes/kafka/kf-ownership.svg)

所有权（Ownership）决定谁负责最终释放。借用（Borrowing）只允许在原对象有效期内访问。以下以 v2.8.0 的具体入口区分：

| 对象                              | 来源与初始归属                                                                                                                  | 释放与失效                                                                                                |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| `rd_kafka_conf_t`                 | `rd_kafka_conf_new()` 创建，归应用                                                                                              | `rd_kafka_new()` 成功即消费配置，失败时应用用 `rd_kafka_conf_destroy()` 清理                              |
| `rd_kafka_t`                      | `rd_kafka_new()` 成功返回客户端句柄，失败返回 NULL                                                                              | 应用按角色完成收尾后调用 `rd_kafka_destroy()`，先释放依赖客户端的句柄                                     |
| `rd_kafka_topic_conf_t`           | `rd_kafka_topic_conf_new()` 创建，归应用                                                                                        | 传给 `rd_kafka_topic_new()` 后即失效。未传入时由应用调用 `rd_kafka_topic_conf_destroy()`                  |
| `rd_kafka_topic_t`                | `rd_kafka_topic_new()` 成功返回一个应用持有的引用，失败返回 NULL                                                                | 每次成功取得的引用对应一次 `rd_kafka_topic_destroy()`，借用的句柄或内部字符串随持有方失效                 |
| `rd_kafka_topic_partition_list_t` | `rd_kafka_topic_partition_list_new()` 或 `rd_kafka_topic_partition_list_copy()` 返回自有列表，回调或 Event 中也可能给出借用列表 | 只销毁自有列表。借用列表超出回调或 Event 生命周期后失效，内部条目也可能因扩容而失效                       |
| `rd_kafka_message_t`              | Consumer Poll 返回自有对象。投递回调和 Event 返回借用对象                                                                       | 自有对象用 `rd_kafka_message_destroy()`，借用对象随回调返回或 Event 销毁而失效                            |
| `rd_kafka_event_t`                | `rd_kafka_queue_poll()` 返回自有 Event 或 NULL                                                                                  | 用 `rd_kafka_event_destroy()`，其消息和借用分区列表同时失效                                               |
| `rd_kafka_error_t`                | 例如 `rd_kafka_commit_transaction()` 失败返回自有错误对象，成功返回 NULL                                                        | 自有对象用 `rd_kafka_error_destroy()`，`rd_kafka_error_string()` 返回的文本随之失效。普通错误码值无需释放 |

## 2. 配置对象在什么情况下转移

配置 setter 可能因名字未知或值非法而失败，必须检查结果并保留错误说明。`rd_kafka_new()` 成功后接管配置，调用方不得再使用或销毁它；创建失败则由调用方清理仍然持有的配置。

Topic 配置的消费契约不应照抄全局配置：`rd_kafka_topic_new()` 文档规定传入的 Topic 配置由该调用消费，之后应用不再释放。建议把创建和失败清理集中在少量函数里，显式标记哪个指针已转移。

全局配置的 Double Free（重复释放）常见于成功创建客户端后，错误清理分支仍销毁原配置。应仅在成功时把全局配置指针置空。Topic 配置则应在调用返回后立即置空，即使返回 NULL。两种指针都不能再解引用或交给清理函数。

## 3. 分区列表的容量、条目与释放 {#_3-列表是有容量的容器-不是固定长度链表}

`rd_kafka_topic_partition_list_new(size)` 的 size 用于初始容量，条目可通过 add 增加；不要把它理解成已经生成了 size 个有效订阅。条目中 Topic、Partition、Offset 等字段是否参与操作，要看具体 API。

例如 Subscribe 关心 Topic 订阅，而显式 Assign 关心分区和起点。列表使用后调用对应 destroy，不要逐个随意 free 内部借用地址。容器扩容或销毁也可能让先前保存的条目指针失效，因此不要跨生命周期保留这类内部指针。

例如先保存 `list->elems` 或第一次 `rd_kafka_topic_partition_list_add()` 返回的地址，再添加条目，底层可能扩容，原地址便不能继续使用。构造完成后可按 Topic 与 Partition 用 `rd_kafka_topic_partition_list_find()` 重新定位。需要跨回调或跨线程持有时，复制列表或只复制业务需要的字段。不要把内部地址当作快照。

## 4. 同一种消息结构也可能有不同归属

`rd_kafka_consumer_poll()` 返回的消息对象由应用在使用后释放；生产者投递回调收到的消息则是借用视图，不应调用同样的 destroy。旧 Consume Callback、Event API 还各有契约，不能因为类型名相同就统一释放。

Payload 是字节数组，不保证以零结尾。打印或解析应使用 len，不能直接当 C 字符串。消费消息释放后，其内部 Key、Payload 等指针也不能继续被工作线程使用；若要异步传递，必须复制必要内容或明确保留对象生命周期。

下面是 Consumer Poll 路径的对照。若 `m->err` 非零，先检查错误码，例如区分分区 EOF 和实际消费错误，可用 `rd_kafka_message_errstr(m)` 记录错误。包括错误消息在内，所有非 NULL 的 Poll 返回对象最后都应销毁。

```c
/* 错误：下面两行结束后，saved 可能指向已释放内存。假设 m 是正常消息。 */
const void *saved = m->payload;
rd_kafka_message_destroy(m);
/* 此后不能把 saved 交给 Worker。 */
```

```c
/* 正确：handle_bytes 在返回前消费字节，或者自行复制需要异步使用的数据。 */
if (m != NULL) {
    if (m->err)
        report_consumer_error(m->err, rd_kafka_message_errstr(m));
    else
        handle_bytes(m->payload, m->len, m->key, m->key_len);
    rd_kafka_message_destroy(m);
}
```

异步复制时同时保存长度，区分 NULL 和空内容，复制或入队失败时清理已分配的缓冲。队列成功接管副本后由 Worker 释放。也可以明确把自有 Poll 消息交给 Worker，由 Worker 在处理后销毁一次，并在关闭客户端前等待这些消息释放。两种方式都避免 Use After Free（释放后使用）。投递回调与 `rd_kafka_event_message_next()` 的借用消息不能交给 Worker 接管；只在借用期内读取，跨边界时复制数据。

### 异步生产的 Payload

`rd_kafka_produce()` 返回 0 表示已入队，最终交付结果由投递报告给出。Payload 是值字节，Key 是独立参数。以下复制和转移标志针对 Payload，调用返回后即可复用传入的 Key 内存。

| 标志                  | 返回 0 后                                                                                | 返回 -1 时                           |
| --------------------- | ---------------------------------------------------------------------------------------- | ------------------------------------ |
| `RD_KAFKA_MSG_F_COPY` | 库复制数据，原缓冲仍归应用，可立即复用或释放                                             | 原缓冲仍归应用                       |
| `RD_KAFKA_MSG_F_FREE` | 库取得缓冲的释放责任，用完调用 `free()`。只传可由库用 `free()` 释放的内存                | 转移没有发生，由应用释放或保留以重试 |
| 两者均未设置          | 库借用 Payload，应用保持它有效且内容稳定，直至该消息投递报告。普通回调模式可在报告中释放 | 未入队，应用可立即复用或释放         |

COPY 和 FREE 互斥。循环中的栈缓冲或临时可变数组适合 COPY。若选择借用，不能把 Flush 超时当成库已用完所有 Payload 的证明。

## 5. 建议的错误路径检查表

逐项检查配置设置、客户端创建、列表构造、订阅、消息错误及释放过程，确认调用失败时哪些对象仍归应用持有，哪些已由接口接管。销毁客户端前，应先完成相应的 Producer flush 或 Consumer close；回调依赖的上下文必须保留到回调不再发生为止。

| API                              | 收尾职责                                                                                                                                                                                         |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `rd_kafka_flush(rk, timeout_ms)` | Producer 有界等待在途生产完成。普通回调模式会服务 Poll 回调，超时需检查并处理剩余消息。Flush 成功表示队列排空，逐消息成功与否看投递报告。使用投递 Event 时需要另有线程服务 Event 队列            |
| `rd_kafka_consumer_close(rk)`    | 阻塞执行 Consumer 收尾，包括适用的撤销回调、位点提交和离组。检查返回码。手动管理位点的应用先停止派发并按安全前沿处理，Close 本身不了解 Worker 的完成状态                                         |
| `rd_kafka_destroy(rk)`           | 销毁客户端并等待其线程退出。v2.8.0 普通 Destroy 对配置了 `group.id` 且未显式 Close 的 Consumer 会走 Consumer Close 路径，因此仍可能触发重平衡回调。显式 Close 便于单独处理错误，之后仍要 Destroy |

先停止并发使用客户端，再收尾和释放其依赖对象。回调的 `opaque` 上下文要保留到最后一次可能的回调结束，包括适用的 Close 或 Destroy 路径。Producer 若无法 Flush 完成，应明确处置未交付工作，并在确认库不再访问前保留借用数据。

### 实践：编译一个对象生命周期示例

保存为 `ownership.c`。使用 v2.8.0 的开发头文件、库和 `pkg-config`。程序只创建本地 Producer、Topic 句柄和分区列表，不配置 Broker、不发消息，成功路径无需 Kafka 服务。三个可选参数分别触发配置设置、客户端创建和 Topic 句柄创建的失败分支。

```c
#include <librdkafka/rdkafka.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv) {
    const char *mode = argc > 1 ? argv[1] : "";
    const char *key = strcmp(mode, "bad-config") == 0
        ? "review.invalid.property" : "client.id";
    char error[512];
    rd_kafka_conf_t *conf = rd_kafka_conf_new();
    rd_kafka_t *client = NULL;
    rd_kafka_topic_t *topic = NULL;
    rd_kafka_topic_partition_list_t *partitions = NULL;
    int status = EXIT_FAILURE;

    if (rd_kafka_conf_set(conf, key, "ownership-review",
                         error, sizeof(error)) != RD_KAFKA_CONF_OK) {
        fprintf(stderr, "configuration: %s\n", error);
        goto cleanup;
    }
    if (strcmp(mode, "bad-client") == 0 &&
        rd_kafka_conf_set(conf, "max.in.flight", "6",
                         error, sizeof(error)) != RD_KAFKA_CONF_OK) {
        fprintf(stderr, "max.in.flight: %s\n", error);
        goto cleanup;
    }
    if (strcmp(mode, "bad-client") == 0 &&
        rd_kafka_conf_set(conf, "enable.idempotence", "true",
                         error, sizeof(error)) != RD_KAFKA_CONF_OK) {
        fprintf(stderr, "idempotence: %s\n", error);
        goto cleanup;
    }

    client = rd_kafka_new(RD_KAFKA_PRODUCER, conf, error, sizeof(error));
    if (client == NULL) {
        fprintf(stderr, "client: %s\n", error);
        goto cleanup; /* 失败时 conf 仍由调用者持有。 */
    }
    conf = NULL;

    rd_kafka_topic_conf_t *topic_conf = rd_kafka_topic_conf_new();
    const char *name = strcmp(mode, "bad-topic") == 0 ? NULL : "review-orders";
    topic = rd_kafka_topic_new(client, name, topic_conf);
    topic_conf = NULL; /* 即使 topic 为 NULL，调用也已消费配置。 */
    if (topic == NULL) {
        fprintf(stderr, "topic: %s\n", rd_kafka_err2str(rd_kafka_last_error()));
        goto cleanup;
    }

    partitions = rd_kafka_topic_partition_list_new(1);
    rd_kafka_topic_partition_list_add(partitions, name, 0);
    rd_kafka_topic_partition_list_add(partitions, name, 1);
    rd_kafka_topic_partition_t *first =
        rd_kafka_topic_partition_list_find(partitions, name, 0);
    if (first == NULL) {
        fputs("partition not found\n", stderr);
        goto cleanup;
    }
    printf("%s has %d local entries\n", first->topic, partitions->cnt);
    status = EXIT_SUCCESS;

cleanup:
    if (partitions != NULL)
        rd_kafka_topic_partition_list_destroy(partitions);
    if (topic != NULL)
        rd_kafka_topic_destroy(topic);
    if (client != NULL)
        rd_kafka_destroy(client); /* 本例没有入队消息。 */
    if (conf != NULL)
        rd_kafka_conf_destroy(conf);
    return status;
}
```

```bash
pkg-config --modversion rdkafka  # 本例要求 2.8.0
cc -std=c11 -Wall -Wextra -Wpedantic ownership.c \
  $(pkg-config --cflags --libs rdkafka) -o ownership
./ownership
./ownership bad-config
./ownership bad-client
./ownership bad-topic
```

预期正常路径输出两个本地条目，三个故障路径报告相应错误并以非零状态退出。可在支持的平台给同一编译命令增加 `-g -fsanitize=address -fno-omit-frame-pointer`，用 AddressSanitizer（地址消毒器，ASan）执行四条路径。在支持 Valgrind 的 Linux 环境，另用未加 ASan 的调试版执行 `valgrind --leak-check=full --error-exitcode=99 ./ownership`，并分别传入三个故障参数。检查工具只覆盖实际运行的路径，库内部覆盖还取决于库是否经过相应插桩。

## 参考

- [librdkafka v2.8.0 公开头文件](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)
- [librdkafka 官方使用说明](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
