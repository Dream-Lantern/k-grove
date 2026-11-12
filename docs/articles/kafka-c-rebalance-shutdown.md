---
id: kafka-c-rebalance-shutdown
title: 第 18 章：C 重平衡回调与优雅关闭
description: "客户端可以自动处理适用分区分配；一旦注册自定义 rebalance callback，应用就必须按所选协议履行分配和撤销契约，同时完成自己的业务交接。"
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
order: 18
---

# 第 18 章：C 重平衡回调与优雅关闭

> 版本导航：librdkafka v2.8.0 C API。
>
> 学习目标：让业务生命周期服从分区所有权，避免撤销后继续写入、回调使用已释放上下文和销毁时丢失未确认工作。

## 1. 自动分配与自定义回调的职责 {#_1-没有回调与自定义回调的责任不同}

客户端可以自动处理适用分区分配；一旦注册自定义 rebalance callback，应用就必须按所选协议履行分配和撤销契约，同时完成自己的业务交接。

固定 v2.8.0 中，range、roundrobin 等 eager 路线使用 `rd_kafka_assign()` 设置或清空完整分配；cooperative-sticky 等增量路线使用对应的 incremental assign/unassign。增量函数返回的错误对象也有独立归属，不能忽略或按普通整数错误码处理。

| 事件/状态，C v2.8.0 Classic       | eager自定义回调                      | cooperative自定义回调                    | 业务状态                           |
| --------------------------------- | ------------------------------------ | ---------------------------------------- | ---------------------------------- |
| ASSIGN_PARTITIONS                 | assign设置完整分配                   | incremental_assign加入指定集合           | 初始化这些分区的队列与完成前沿     |
| REVOKE_PARTITIONS，仍有可交接资格 | 停派工作，提交安全前沿后assign(NULL) | 只处理撤销集合，然后incremental_unassign | 未撤销分区继续，禁止提交未完成任务 |
| 所有权已丢失                      | 不假定旧提交仍有效                   | 同样不假定有效                           | 隔离迟到结果，允许新持有者重放     |
| closing，close可能触发回调        | 履行相同完整分配契约                 | 履行相同增量契约                         | opaque与需要的状态必须仍存活       |

正常回调的 `partitions` 是库持有的借用列表，返回时库会销毁它。回调中需要保留信息时复制 Topic、Partition 等字段，或用 `rd_kafka_topic_partition_list_copy()` 取得自有副本。修改原列表仅用于设置每个分区的初始 Offset，别用位置查询覆盖它。见[第 15 章的所有权表](/articles/kafka-librdkafka-ownership.html)。

若 `err` 既非 ASSIGN 也非 REVOKE，v2.8.0 回调契约要求用 `rd_kafka_assign(rk, NULL)` 同步本地分配状态。这个异常清理分支与正常 Cooperative 撤销使用的增量 API 不同。回调返回类型是 `void`，操作失败要记录在应用状态中，由正常控制流处理。

## 2. 撤销分区先撤销工作资格

先停止向被撤销分区派发新任务，清点已完成与在途任务，再在可用预算内排空或取消剩余任务，并在仍有提交资格时提交安全前沿。对于没有被撤销的分区，cooperative 路线不应无条件清除全部状态。

若客户端报告所有权已丢失，旧实例不能假定自己仍有提交资格。外部正在执行的 HTTP 或数据库请求也不会因为回调发生自动消失，必须用幂等、任务取消或下游 fencing 处理迟到结果。

在撤销回调中应先读 `rd_kafka_assignment_lost()`，因为设置或修改分配的 API 会重置该标志。会话失效等异常可能让新成员已经取得分区。检查结果为 0 时仍应检查实际提交结果，所有权可能在操作期间变化。迟到的 Worker 结果需要带分区和本地分配世代，匹配当前世代才可推进前沿。旧请求已经发往数据库或 HTTP 服务时，下游要用业务事件 ID 幂等，或者在写入时原子校验 Fencing Token。

| 应用状态 | 允许的动作                                                 | 退出条件                                  |
| -------- | ---------------------------------------------------------- | ----------------------------------------- |
| ACTIVE   | 按容量派发，处理完成结果，提交安全前沿                     | 撤销进入 REVOKING，丢失进入 LOST          |
| REVOKING | 停止该分区新派发，取消尚未启动的工作                       | 转入 DRAINING 或 LOST                     |
| DRAINING | 有界接收当前世代已在途的完成结果，仅在仍有权时提交安全前沿 | 任务完成或预算耗尽后交还，丢失则跳过提交  |
| RELEASED | 不再处理或提交该世代的位点                                 | 下次取得分区时生成新世代，重新进入 ACTIVE |
| LOST     | 立即隔离旧世代结果，不提交。仍按协议清理本地分配           | 清理完成进入 RELEASED                     |

这些是应用状态。Cooperative 只让受影响的分区离开 ACTIVE，其他分区继续工作。

## 3. 回调中的有界排空与恢复 {#_3-回调不要承载无限阻塞业务}

在回调里等待一个无法结束的任务，会阻碍客户端事件处理，甚至引发新的超时。因此，应提前设计有界排空、状态标记和重试恢复方式。回调中允许调用哪些 API，需要按固定版本文档核对，不能默认所有公共方法都可递归调用。

简化方案可以先采用串行业务和库自动分配，确认基础语义后再增加自定义回调。复杂回调不等于更可靠；若无法描述每个状态的进入、退出和失败路径，应先减少并发范围。

例如为撤销预留 250 ms 的单调时钟预算。先取消还在队列里的任务，只收集在途任务的完成结果。按任务年龄检查最老请求，超过任务本身时限就发取消信号。排空预算用尽时，把剩余任务归为未完成，交接后依靠重放恢复。无法取消的外部调用继续受下游幂等或隔离协议约束。这个 250 ms 只约束应用等待，不能用作同步 Commit 或 Close 的硬超时。若整体回调时限不允许等待提交，可定期提前提交前沿，撤销时直接交接，接受剩余重放。

### Classic 回调示例

以下是第 17 章串行程序的可嵌入片段，限定 `review-orders` 的 P0–P2。串行版本进入回调时没有 Worker 在途，故无需排空。若改为批次提交，`next` 只记录连续完成前沿。回调仅收集撤销列表中有进度的分区，已丢失时跳过提交。

```c
struct handoff {
    int active[3];
    int64_t next[3]; /* -1 表示尚无可提交位置 */
    int failed;
};

static void rebalance(rd_kafka_t *rk, rd_kafka_resp_err_t event,
                      rd_kafka_topic_partition_list_t *partitions, void *opaque) {
    struct handoff *state = opaque;
    rd_kafka_resp_err_t err = RD_KAFKA_RESP_ERR_NO_ERROR;
    rd_kafka_error_t *incremental_error = NULL;

    if (event != RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS &&
        event != RD_KAFKA_RESP_ERR__REVOKE_PARTITIONS) {
        fprintf(stderr, "unexpected rebalance: %s\n", rd_kafka_err2str(event));
        memset(state->active, 0, sizeof(state->active));
        state->failed = 1;
        err = rd_kafka_assign(rk, NULL);
    } else {
        const char *protocol = rd_kafka_rebalance_protocol(rk);
        int cooperative = protocol && strcmp(protocol, "COOPERATIVE") == 0;
        if (!cooperative && (!protocol || strcmp(protocol, "EAGER") != 0)) {
            fprintf(stderr, "missing Classic rebalance protocol\n");
            memset(state->active, 0, sizeof(state->active));
            state->failed = 1;
            err = rd_kafka_assign(rk, NULL);
        } else if (event == RD_KAFKA_RESP_ERR__ASSIGN_PARTITIONS) {
            if (cooperative)
                incremental_error = rd_kafka_incremental_assign(rk, partitions);
            else
                err = rd_kafka_assign(rk, partitions);
            if (!err && !incremental_error) {
                for (int i = 0; i < partitions->cnt; ++i) {
                    const rd_kafka_topic_partition_t *p = &partitions->elems[i];
                    if (strcmp(p->topic, "review-orders") == 0 &&
                        p->partition >= 0 && p->partition < 3) {
                        state->active[p->partition] = 1;
                        state->next[p->partition] = -1;
                        printf("assigned P%d\n", (int)p->partition);
                    }
                }
            }
        } else {
            int lost = rd_kafka_assignment_lost(rk);
            rd_kafka_topic_partition_list_t *safe =
                rd_kafka_topic_partition_list_new(partitions->cnt);
            for (int i = 0; i < partitions->cnt; ++i) {
                const rd_kafka_topic_partition_t *p = &partitions->elems[i];
                int partition = p->partition;
                if (strcmp(p->topic, "review-orders") != 0 ||
                    partition < 0 || partition >= 3)
                    continue;
                if (!lost && state->active[partition] && state->next[partition] >= 0)
                    rd_kafka_topic_partition_list_add(safe, p->topic, partition)
                        ->offset = state->next[partition];
                state->active[partition] = 0;
                state->next[partition] = -1;
                printf("%s P%d\n", lost ? "lost" : "revoked", partition);
            }
            if (safe->cnt && !rd_kafka_assignment_lost(rk)) {
                rd_kafka_resp_err_t commit_err = rd_kafka_commit(rk, safe, 0);
                if (commit_err) {
                    fprintf(stderr, "handoff commit: %s\n",
                            rd_kafka_err2str(commit_err));
                    state->failed = 1;
                }
            }
            rd_kafka_topic_partition_list_destroy(safe);
            if (cooperative)
                incremental_error = rd_kafka_incremental_unassign(rk, partitions);
            else
                err = rd_kafka_assign(rk, NULL);
        }
    }
    if (err) {
        fprintf(stderr, "assignment: %s\n", rd_kafka_err2str(err));
        state->failed = 1;
    }
    if (incremental_error) {
        fprintf(stderr, "incremental assignment: %s\n",
                rd_kafka_error_string(incremental_error));
        rd_kafka_error_destroy(incremental_error);
        state->failed = 1;
    }
}
```

在第 17 章示例中增加 `#include <stdint.h>`，把代码放在 `main` 之前。创建客户端之前，在 `main` 中初始化 `struct handoff state = {.next = {-1, -1, -1}};`，用 `rd_kafka_conf_set_opaque(conf, &state)` 和 `rd_kafka_conf_set_rebalance_cb(conf, rebalance)` 注册。每次 Poll 返回后先检查 `state.failed`。失败则销毁本次可能返回的消息，将状态设为失败并跳出循环。处理正常消息之前检查分区在 0–2 且为 active，否则停机。保留原有逐条提交时，回调中没有额外待提交进度。测试批次模式时，才在业务成功后用 `state.next[m->partition] = m->offset + 1` 替换逐条提交，由撤销或 Close 路径提交。本实验的批次模式只在交接提交，崩溃时可能重放整个持有期间的记录。让回调和消费循环由同一线程服务，`state` 保留到 Destroy 返回。

## 4. 停止输入、完成交接再释放资源 {#_4-优雅关闭不是一个-destroy}

[![librdkafka 2.8：异步 Consumer 关闭](/assets/notes/kafka/kf-close.svg)](/assets/notes/kafka/kf-close.svg)

Producer 停止新发送，服务回调并执行有界 flush，记录仍未完成和最终失败的消息。Consumer 停止新业务派发，处理安全前沿，调用 `rd_kafka_consumer_close()` 并检查结果，随后释放客户端。显式 close 使生命周期更清楚；库在适用 destroy 路径中也可能触发 close 和回调，因此上下文不能提前释放。

| 阶段             | 接口与计时，v2.8.0                                                      | 不能推出的结论                                           |
| ---------------- | ----------------------------------------------------------------------- | -------------------------------------------------------- |
| 应用排空         | 应用自行设置工作预算、取消和恢复记录                                    | 库的close不替线程池收尾                                  |
| Producer投递排空 | rd_kafka_flush(rk,timeout_ms)                                           | 队列空不等于每条成功；仍看Delivery Report                |
| Consumer同步关闭 | rd_kafka_consumer_close(rk)，没有同名timeout参数                        | 文档大致受session.timeout.ms限制，不是任意慢回调的硬截止 |
| Consumer异步关闭 | consumer_close_queue，把事件送指定队列，持续服务直到consumer_closed为真 | 发起异步关闭不等于已经可destroy                          |
| 资源释放         | 完成关闭契约后destroy，最后清理回调上下文                               | 不从另一线程强行destroy作为通用超时补救                  |

同步 close 包含撤销分配、必要的提交和离组等动作，但回调中的业务阻塞仍需单独管理。Producer 的关闭细节见[第16章](/articles/kafka-c-producer.html)，不要把 flush 的毫秒参数误套到 Consumer close 上。

Topic 句柄、应用持有的消息、列表、客户端和回调上下文都有各自顺序。不能先 free opaque，再在 flush 或 close 中触发使用它的回调。

### 同步与异步关闭代码

使用第 17 章的信号处理器。收到信号后由 Poll 线程停止派发，串行任务结束后退出循环。若使用 Worker，先按预算排空或隔离剩余任务，把安全前沿留给回调。同步路径在同一线程调用 Close，由它服务适用回调，记录返回码，最后 Destroy。可把第 17 章原来的 Close 调用替换为以下函数，`asynchronous` 可用 `getenv("ASYNC_CLOSE") != NULL` 选择。调用方收到返回值后照常检查并 Destroy，同时也检查 `state.failed`。本片段走回调模式，注册以下错误与提交回调，使关闭队列能处理预期的回调事件。保持默认的 Event 配置，不启用 Event API 或统计事件。

```c
static void closing_error(rd_kafka_t *rk, int err, const char *reason,
                          void *opaque) {
    (void)rk;
    (void)opaque;
    fprintf(stderr, "client error %d: %s\n", err, reason);
}

static void closing_commit(rd_kafka_t *rk, rd_kafka_resp_err_t err,
                           rd_kafka_topic_partition_list_t *offsets, void *opaque) {
    (void)rk;
    (void)offsets;
    struct handoff *state = opaque;
    if (err && err != RD_KAFKA_RESP_ERR__NO_OFFSET) {
        fprintf(stderr, "commit report: %s\n", rd_kafka_err2str(err));
        state->failed = 1;
    }
}

static rd_kafka_resp_err_t close_orders(rd_kafka_t *rk, int asynchronous) {
    if (!asynchronous)
        return rd_kafka_consumer_close(rk);

    rd_kafka_queue_t *queue = rd_kafka_queue_new(rk);
    rd_kafka_error_t *error = rd_kafka_consumer_close_queue(rk, queue);
    if (error) {
        rd_kafka_resp_err_t code = rd_kafka_error_code(error);
        fprintf(stderr, "start close: %s\n", rd_kafka_error_string(error));
        rd_kafka_error_destroy(error);
        rd_kafka_queue_destroy(queue);
        return code;
    }
    while (!rd_kafka_consumer_closed(rk))
        rd_kafka_queue_poll_callback(queue, 100);
    rd_kafka_queue_destroy(queue);
    return RD_KAFKA_RESP_ERR_NO_ERROR;
}
```

在创建客户端前加上 `rd_kafka_conf_set_error_cb(conf, closing_error)` 和 `rd_kafka_conf_set_offset_commit_cb(conf, closing_commit)`。关闭开始后把事件服务切换到这条专用队列。异步模式可在短 Poll 间隙更新停机指标。100 ms 是每次等待时间，完成条件是 `rd_kafka_consumer_closed()`，无需寻找名为 `consumer_closed` 的事件。异步启动失败时释放错误和队列，记录错误后走客户端清理，保留 opaque 直到 Destroy。关闭成功也只能确认客户端完成关闭流程，业务仍需核对回调记录和安全位点。

## 5. 停止信号与故障恢复

信号处理器可以设置停止标记，让正常控制流退出；不应在异步信号上下文中直接进行任意复杂的客户端与内存操作。强制杀进程或机器掉电仍可能跳过优雅关闭，设计必须允许从已提交位置重放。

练习至少覆盖四种窗口：处理前退出、业务完成但提交前退出、分区撤销时有在途工作、flush 或 close 超时。

### 实践：对照成员交接与退出

使用第 17 章相同的 Topic、事件、编译环境和启动方式，在两个终端用相同的新 `group.id` 运行集成后的程序。先让两者都使用 `partition.assignment.strategy=range`，再换新组同时改成 `cooperative-sticky`。日志关注分区 ID、回调种类、恢复 Offset 及提交结果。下表均为预期。

| 操作                                                    | 观察目标                                                                                   |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| A 稳定后加入 B                                          | Eager 全量撤销，Cooperative 只撤销实际迁移的分区。实际分配以组状态为准                     |
| 向 A 发送 SIGINT 或 SIGTERM                             | 信号处理器只写 `volatile sig_atomic_t` 标志。分别用同步和异步路径观察撤销及 B 接管         |
| 重新启动 A 后以 SIGKILL 终止它                          | A 没有关闭回调，协调器在会话超时后重新分配。从已确认的位点恢复                             |
| 在异步扩展中让 Worker 挂在受控闩锁，再加入 B            | 移动分区进入 DRAINING。超过 250 ms 后交还，未完成记录可重放                                |
| 在 Worker 等待时停掉 A 的 Poll 直至失去分配，再释放闩锁 | 拒收旧分配世代的完成结果，不推进旧位点。若已发出数据库请求，验证下游对重复或过期写入的处理 |

后两项需要第 17 章描述的 Worker 扩展。第 16 章的同 Key 输入通常集中到同一分区。若实验要让持有订单任务的分区迁移，先用组管理命令确认待迁移分区，再向该分区显式生产一条格式相同、事件 ID 未使用过的订单。串行回调示例可以验证分配与关闭，Worker 超时与迟到结果则使用状态机做故障注入。

## 参考

- [librdkafka v2.8.0 异步关闭实现](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.c)

- [v2.8.0 Rebalance callback 与销毁契约](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)
- [librdkafka 官方示例目录](https://github.com/confluentinc/librdkafka/tree/v2.8.0/examples)

## 联读

先读[串行消费与位点提交](/articles/kafka-c-consumer.html)，再处理本章的所有权交接。
