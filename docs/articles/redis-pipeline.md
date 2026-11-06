---
id: redis-pipeline
title: 第十七章 Pipeline、批量命令与背压
description: "如果每发一条命令都等待回复，网络等待会反复出现在调用路径上。Pipeline 的基本做法是先提交一批命令，再依次读取回复，让请求发送和结果接收重叠。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - redis
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: redis
series: redis-learning
order: 17
---

# 第十七章 Pipeline、批量命令与背压

[返回本册目录](/collections/redis/)

如果每发一条命令都等待回复，网络等待会反复出现在调用路径上。Pipeline（流水线）的基本做法是先提交一批命令，再依次读取回复，让请求发送和结果接收重叠。它是一种通信组织方式，不是新的事务机制。

本章以 Redis Open Source 7.2.0 和 hiredis v1.2.0 为参照。代码和性能计算都是教学材料，未连接实例、未编译 C 程序、未运行压测。

![Pipeline 的请求与回复](/assets/notes/redis/redis-study-pipeline.svg)

## 1. 先比较单命令与批量通信

同一数据类型有现成的多参数命令时，先判断能否用 MGET、MSET、HMGET、HSET 等直接表达。它们和 Pipeline 不是一回事：前者是一条命令，后者包含多条独立命令。Redis Cluster（集群）下还要检查多 Key 命令涉及的键是否位于同一 Hash Slot（哈希槽）。

教学示意：

```text
逐条等待：发送 GET A → 等回复 → 发送 GET B → 等回复
Pipeline：提交 GET A、GET B → 依次取回 A、B 的回复
```

同一连接的命令与回复保持相应顺序，但多个客户端的请求仍可能在批次的命令之间执行。Pipeline 不提供整批隔离，也不是“整个批次只用一个 TCP（Transmission Control Protocol，传输控制协议）包”。分包、拥塞、服务端缓冲和回复大小都会影响实际通信。[官方 Pipeline 原理](https://redis.io/docs/latest/develop/using-commands/pipelining/)

RTT（Round-Trip Time，往返时间）是请求发出至对应回复返回的往返通信时间。假设 RTT 为 2 ms，要发送 100 条独立 GET，暂时忽略执行、数据传输和其他开销：逐条等待约为 `100 × 2 = 200 ms`；单批 Pipeline 理想情况下可以摊掉逐条等待，网络往返等待项接近一个 RTT。后者不是总耗时必为 2 ms：每条命令仍需执行，批次还受带宽、缓冲和服务端负载影响。

这是教学估算，不是性能实测。连续通信还可能减少部分读写系统调用，但不会消除服务端执行成本，也不保证只有一个 TCP 包。[RTT 与系统调用开销](https://redis.io/docs/latest/develop/using-commands/pipelining/)

| 机制                   | 主要目的                   | 网络交互           | 连续执行保证                            |
| ---------------------- | -------------------------- | ------------------ | --------------------------------------- |
| MGET/MSET 等多参数命令 | 单命令处理多个键           | 通常减少往返       | 按单命令语义执行                        |
| Pipeline               | 批量发送独立命令           | 减少逐条等待       | 不提供整批隔离                          |
| MULTI/EXEC             | 连续执行预先排好的命令     | 可结合批量发送     | EXEC 中的事务命令不被其他客户端命令插入 |
| Lua                    | 在服务端执行组合判断与操作 | 通常减少客户端交互 | 脚本执行期间正常客户端命令不能插入      |

MGET 是一条命令，Pipeline 中多个 GET 是多条命令。把 MULTI、业务命令和 EXEC 一起批量发送时，保证来自事务机制，不能归功于 Pipeline；错误和回滚边界见 [第 18 章](/articles/redis-transactions-lua-functions.html)。

## 2. hiredis 中的请求累积与回复读取 {#_2-hiredis-需要成对管理提交与取回}

同步 hiredis 可以用 `redisAppendCommand` 等接口累积请求，再调用 `redisGetReply` 取回结果。应用必须检查提交结果、取回结果和每个回复的类型。下面是流程，不是完整可运行代码：

```text
for 每个有界批次:
    对每条命令编码并提交，记录成功提交数量
    按协议取回这些回复，逐项检查 Redis 错误
    若连接或读取失败，标记未确认命令为结果未知
    回收回复对象，更新批次耗时和积压指标
```

在 hiredis v1.2.0 的同步阻塞上下文中，`redisAppendCommand` 将命令编码成 RESP（Redis Serialization Protocol，Redis 序列化协议）并追加到本地输出缓冲。返回 REDIS_OK 只确认追加成功，不代表已经发送或执行。

`redisGetReply` 先尝试从解析器取得已有完整回复；若没有，才按需要将输出缓冲写入 Socket（套接字），读取网络数据并解析出一个回复。因此“每取一个回复就新发一次请求”也不准确。[v1.2.0 请求缓冲与回复读取源码](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/hiredis.c)

以下是函数教学片段，不是完整程序，需使用第 15 章的头文件和连接设置。调用者把一条健康、独占、无未读回复的同步阻塞连接 `c` 的所有权交给函数；函数在所有路径都释放它，调用者之后不得继续使用。仅用于隔离实例，会覆盖示例键，未编译、未运行：

```c
int pipeline_example(redisContext *c) {
    int ok = 1;
    if (c == NULL) return 1;
    if (c->err ||
        redisAppendCommand(c, "SET demo:a 10") != REDIS_OK ||
        redisAppendCommand(c, "GET demo:a") != REDIS_OK) {
        redisFree(c); /* Do not flush a partially prepared batch blindly. */
        return 1;
    }
    for (int i = 0; i < 2; ++i) {
        void *raw = NULL;
        if (redisGetReply(c, &raw) != REDIS_OK || raw == NULL) {
            freeReplyObject(raw);
            redisFree(c); /* Unconfirmed commands may already have executed. */
            return 1;
        }
        redisReply *r = raw;
        if (r->type == REDIS_REPLY_ERROR) {
            ok = 0;
            fputs("Redis command error: ", stderr);
            if (r->str != NULL) fwrite(r->str, 1, r->len, stderr);
            fputc('\n', stderr);
        } else {
            int expected = i == 0
                ? r->type == REDIS_REPLY_STATUS && r->str != NULL
                  && r->len == 2 && memcmp(r->str, "OK", 2) == 0
                : r->type == REDIS_REPLY_STRING && r->str != NULL
                  && r->len == 2 && memcmp(r->str, "10", 2) == 0;
            if (!expected) ok = 0;
        }
        freeReplyObject(r);
    }
    redisFree(c);
    return ok ? 0 : 1;
}
```

没有并发修改和服务端错误时，预期依次读到 SET 的 OK、GET 的字符串 `10`；这些是示意结果。收到完整错误回复时继续检查剩余回复；通信失败则停止盲读并丢弃上下文。`freeReplyObject(NULL)` 在 v1.2.0 中可安全调用，但不能因此解引用 NULL。

某条命令返回 WRONGTYPE，并不会自动取消后续命令。若连接仍然有效，应按客户端协议处理剩余回复；如果直接归还连接池，下一位使用者可能读到上一批遗留的结果。

这与超时、断连不是同一种状态：完整错误回复可以逐项消费；通信失败后则有未确认命令，不能把连接当成干净连接回池。见 [第 15 章的失败状态表](/articles/redis-hiredis.html)。

## 3. 用命令数、字节与等待时间确定批次 {#_3-批次大小要看字节和尾延迟}

同为 1000 条命令，读取很小的计数器与读取数兆字节的值，负载完全不同。批次至少有三种边界：命令数、请求及预期回复字节、等待时间。

例如读取 1000 个键，按以下批次切分仅用于比较，不代表 100 条最优：

| 每批命令数 | 批次数 | 主要取舍                       |
| ---------- | -----: | ------------------------------ |
| 10         |    100 | 单批缓冲较小，往返等待较多     |
| 100        |     10 | 在吞吐和内存之间折中，仍需实测 |
| 1000       |      1 | 往返较少，可能增加缓冲及尾延迟 |

批次过小，无法充分摊薄通信开销；批次过大，则会增加服务器输出缓冲、应用内存占用和其他请求的等待时间。交互式请求与离线导入也不宜不加区分地共用一套参数。

合理的验证方法是先固定数据大小和并发，逐步改变批次，同时观察吞吐、P95/P99、客户端积压和服务器内存。不要用某次吞吐提升推导所有业务都应该使用同一批次。

P95/P99 是 95%/99% 请求延迟不超过的分位值，用于观察较慢请求。还应记录 RTT、带宽、服务端执行时间和 CPU（Central Processing Unit，中央处理器）占用。Backpressure（背压）可按“准备请求 → 检查在途数量、字节和排队时间 → 未超限才提交，否则等待、限流或拒绝”实现，上限要按业务验证。

下面是隔离学习环境中的 Shell 实验设计，不是 Redis 命令，**未经实测**。使用 Redis Open Source 7.2.0 的 redis-benchmark，并预先准备代表业务大小的数据；默认目标为本机 6379，不能把未命中 GET 的成绩当作实际载荷测试：

```bash
redis-benchmark -n 100000 -c 10 -t get -P 1 -q
redis-benchmark -n 100000 -c 10 -t get -P 10 -q
redis-benchmark -n 100000 -c 10 -t get -P 100 -q
```

`-n` 为总请求数，`-c` 为连接数，`-t get` 选择 GET，`-P` 为每连接 Pipeline 深度，`-q` 为简要输出。比较时保持数据、负载和环境一致；吞吐之外需另行采集延迟分布、CPU、客户端和服务端内存，不能从简要输出推导完整延迟分布。本章不提供虚构的性能数字或提升比例。[官方基准测试说明](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/benchmarks/)

Pipeline 减少通信等待，不消除每条命令占用的串行执行成本。响应时间与执行时间倒数的限定推导见 [第 29 章](/articles/redis-slow-queries.html)。

## 4. 部分成功与 Cluster

发送十条写命令后，如果连接断开，服务端可能尚未执行任何一条，也可能已执行部分或全部。Pipeline 本身无法提供断线前后的完整执行清单，因此重试需要依靠业务幂等或可查询的操作状态，不能把无条件重发整批命令当作安全恢复。

```text
客户端提交 INCR、INCR、INCR → Redis 已执行前两条 → 网络断开
                            第三条可能未执行，也可能已执行
```

这是故障推演，不是断网实测。若客户端没有收到完整回复，不能从“服务端已执行前两条”的上帝视角推断自己的已确认清单；实际只能按已收到的完整回复判断，余下标为未知。INCR 重发会再次递增，需要幂等（Idempotency，重复请求不重复产生业务副作用）或可查询状态；通信失败后不能直接归还连接池，连接恢复要求见第 2 节引用的第 15 章。

Cluster 客户端可能将命令按目标节点分组。不同连接之间没有天然的全局执行顺序，重定向和重试会进一步影响观察结果。不要为了让所有请求走一个 Pipeline，把整个业务的键都放进同一个 Hash Tag（哈希标签）；那会把分片退化成热点集中。

同槽限制属于 MGET/MSET、事务和脚本等涉及多个键的操作，不能泛化为“所有 Pipeline 命令必须同槽”：支持 Cluster 路由的客户端可以把独立单键命令分发到不同节点，但简单 hiredis 不会自动提供完整的 Cluster 路由。Hash Tag（哈希标签）可以让相关键同槽，应控制范围。[Cluster 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/)

Pipeline 适合减少独立小命令的通信等待。若逻辑要求“根据当前值判断后再写”，应转向单命令、WATCH 或短小服务端逻辑，而不是期待更快的发送速度消除并发竞态。
