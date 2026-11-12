---
id: redis-slow-queries
title: 第二十九章 慢查询、延迟与热点大键
description: "客户端超时可能发生在连接池、应用事件循环、网络、服务端排队、命令执行或持久化竞争等阶段。排查时先拆分时间，再选择对应证据；Slowlog 用于观察命令执行，端到端等待还需结合客户端与系统指标。"
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
order: 29
---

# 第二十九章 慢查询、延迟与热点大键

[返回本册目录](/collections/redis/)

客户端超时可能发生在连接池、应用事件循环、网络、服务端排队、命令执行或持久化竞争等阶段。排查时先拆分时间，再选择对应证据；Slowlog 用于观察命令执行，端到端等待还需结合客户端与系统指标。

![请求主链路与资源竞争](/assets/notes/redis/redis-study-latency.svg)

## 1. Slowlog 的执行时间与其他等待 {#_1-slowlog-看不到所有等待}

Slowlog 记录符合阈值的命令执行耗时，不包括与客户端通信的全部时间。阈值和结果中的耗时使用微秒，不能把 1000 微秒误读成 1000 毫秒。

Slowlog（Slow Log，慢命令日志）只看请求的一部分。端到端（End-to-end）指应用发起请求直到取得可用结果；可按以下逻辑链路拆分，具体线程调度和等待顺序随客户端实现变化：

```text
客户端请求 → 连接池等待 → 应用线程等待 → 网络发送
→ Redis 排队 → 命令执行 → 网络返回 → 客户端解码 → 业务获得结果
```

例如以下互不重叠的教学耗时，假定应用线程等待、Redis 排队及其他未列阶段为零：

| 阶段                 |    耗时 |
| -------------------- | ------: |
| 连接池等待           |   30 ms |
| 请求网络发送         |   10 ms |
| Redis 命令执行       |  0.5 ms |
| 响应传输与客户端解码 |    5 ms |
| 合计                 | 45.5 ms |

这里的 10 ms 仅指请求发送，不能再包含已算入 5 ms 的响应传输。即使命令执行只有 0.5 ms，应用依然可能超时。实际应依据各阶段计时，不能把不同分布的 P99 直接相加。P99（99th Percentile，第 99 百分位数）表示约 99% 样本不超过的耗时。

以下 `redis` 代码块是 Redis 命令，观察示例以 Redis Open Source 7.2.0 为基线，版本例外另标。

```redis
SLOWLOG LEN
SLOWLOG GET 10
CONFIG GET slowlog-log-slower-than
CONFIG GET slowlog-max-len
```

SLOWLOG LEN 查看保留记录数，GET 10 最多取最近 10 条；`slowlog-log-slower-than` 是微秒阈值，负数禁用、0 记录所有命令，`slowlog-max-len` 是保留条数。Slowlog 为空，仍可能存在服务端排队、网络拥塞、客户端停顿，或日志被截断、阈值未覆盖问题。参见 [SLOWLOG GET](https://redis.io/docs/latest/commands/slowlog-get/) 与 [7.2.0 配置](https://github.com/redis/redis/blob/7.2.0/redis.conf)。

慢日志可能包含键名、参数和客户端信息，导出时应脱敏，避免将真实业务标识直接贴到公开博客。降低阈值或增加日志长度，也会改变采集开销，不能认为任意强度的采集都没有成本。

还可以从具体记录、聚合统计和事件三个角度观察，口径不要混用：

| 工具              | 观察内容                                            | 用途与边界                               |
| ----------------- | --------------------------------------------------- | ---------------------------------------- |
| SLOWLOG           | 超阈值的命令执行记录                                | 定位具体命令与参数，覆盖受阈值和容量限制 |
| INFO commandstats | calls 调用数、usec 累计微秒、usec_per_call 平均微秒 | 看命令资源消耗；平均值不是 P99           |
| INFO latencystats | 各命令执行延迟分位数，单位微秒                      | 看命令延迟分布，不是客户端端到端分布     |
| LATENCY 事件监控  | command、fork 等服务端事件尖峰                      | 看事件历史与关联，不覆盖所有请求阶段     |

```redis
INFO commandstats
INFO latencystats
CONFIG GET latency-tracking
CONFIG GET latency-tracking-info-percentiles
```

INFO latencystats 自 Redis Open Source 7.0.0 提供，需要启用 `latency-tracking` 且对应命令已产生样本；7.0.0、7.2.0 默认启用，默认分位配置为 50、99、99.9，即 P50/P99/P999（P99.9）。实际字段形如 `p99.9`。它来自执行耗时直方图，不是从 calls/usec 平均值推导，也不能把两次分位数相减当区间分位数。版本与单位见 [7.0.0 配置](https://github.com/redis/redis/blob/7.0.0/redis.conf)、[7.0.0 server.c](https://github.com/redis/redis/blob/7.0.0/src/server.c) 与 [7.2.0 分位输出实现](https://github.com/redis/redis/blob/7.2.0/src/server.c)。

LATENCY 事件监控自 Redis Open Source 2.8.13 引入，与上面的命令延迟跟踪是不同机制：

```redis
CONFIG GET latency-monitor-threshold
LATENCY LATEST
LATENCY HISTORY command
LATENCY DOCTOR
LATENCY GRAPH command
```

阈值单位为毫秒，7.2.0 默认 0 表示关闭，不能期待已经存在历史数据。LATEST 列出现有事件及最近/最大耗时，HISTORY 查看某事件的历史，DOCTOR 给出事件分析，GRAPH 绘制文本图；`command` 只是事件名示例，应先按 LATEST 实际返回选择。开启阈值需结合业务与监控成本评估，本章只展示读取配置，未修改配置。参见 [官方延迟事件监控](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/latency-monitor/)。

## 2. 按对象规模与访问集中度区分大键和热键 {#_2-大键与热键不是同一种问题}

大键是尺寸或元素规模过大；热键是访问集中。一个很小的计数器可以极热，一个很大的归档对象也可能很冷。它们会通过不同路径造成 CPU（Central Processing Unit，中央处理器）、网络、内存、复制或迁移压力。

教学对比：一个约 20 MiB、每小时读一次的归档对象是大键但未必热；一个约 64 字节、每秒访问 20000 次的计数器是热键但未必大。若两者叠加，单次成本与请求量会一起放大。

以下是 Shell（命令解释环境）中执行的 redis-cli 工具命令，不是 Redis 服务端命令。以 Redis Open Source 7.2.0 配套 CLI（Command Line Interface，命令行界面）为依据，连接地址、认证与加密参数需按实际环境配置，不在命令行暴露真实密码：

```bash
redis-cli --bigkeys -i 0.1
redis-cli --memkeys -i 0.1
redis-cli --hotkeys -i 0.1
```

`--bigkeys` 区分类型统计：String 看字节，Hash/List/Set 等看字段或元素数，不能统一读成内存字节；`--memkeys` 通过 MEMORY USAGE 估算键内存。两种模式去掉 `-i 0.1` 也可运行，但这里显式节流。`--hotkeys` 使用 LFU（Least Frequently Used，最不经常使用）访问频率计数，要求实例已使用 `allkeys-lfu` 或 `volatile-lfu` 策略；计数带衰减且近似，并非精确 QPS（Queries Per Second，每秒请求数）。不要为了检测就切换生产淘汰策略。CLI 选项与节奏见 [官方工具文档](https://redis.io/docs/latest/develop/tools/cli/) 和 [7.2.0 redis-cli.c](https://github.com/redis/redis/blob/7.2.0/src/redis-cli.c)。

在这些 7.2.0 扫描模式中，`-i 0.1` 表示每 100 次 SCAN 命令暂停 0.1 秒，不是每个 Key 暂停。SCAN（游标式分步遍历）仍会对整个扫描范围产生请求与计算开销，应限制时间窗和总工作量，并可中止；数据变化时结果不是一致性快照，可能重复或遗漏变化中的元素。扫描针对所连接实例，Cluster 要分别计划各主节点的采样，`-c` 不会自动扫描整个集群。

需要查看单键时可用：

```redis
MEMORY USAGE archive:demo SAMPLES 5
```

[MEMORY USAGE](https://redis.io/docs/latest/commands/memory-usage/) 自 Redis Open Source 4.0.0 提供，结果为键和值所需的分配内存字节，包含管理开销；嵌套结构通常按样本估算，SAMPLES 0 遍历全部嵌套值，成本更高。它不等于整个进程的驻留内存，也不是客户端响应大小。编码与内存取舍见 [第 26 章内部编码](/articles/redis-internal-encoding.html) 和 [第 25 章内存](/articles/redis-memory-eviction.html)。

默认检查不应包括全库 KEYS、直接全量读取巨大集合，或对生产库执行无约束扫描。SCAN 虽可分步执行，但仍需控制总工作量、返回值尺寸和扫描节奏。

MONITOR 会持续输出命令，增加开销且可能泄露参数；KEYS 会一次遍历并阻塞普通命令处理；即便是只读批量读取，也可能造成大回复。三者都不应成为生产环境无条件的第一步。

## 3. 删除和读取都可能产生尖峰

大对象的成本不只出现在删除时。一次 HGETALL 或 LRANGE 取回大量结果，同样会占用执行时间、输出缓冲、网络和客户端解码资源。应先检查数据模型与访问范围，再考虑分页、拆分或只读取必要字段。

表中的键均为虚构示例，替代方式也要限制批量和总扫描量：

| Redis 命令               | 潜在问题                        | 替代方式                                       |
| ------------------------ | ------------------------------- | ---------------------------------------------- |
| `HGETALL user:demo`      | 返回整个 Hash                   | HMGET 指定字段，或 HSCAN 分步遍历              |
| `LRANGE jobs:demo 0 -1`  | 返回整个 List                   | 按业务范围分段 LRANGE                          |
| `SMEMBERS tags:demo`     | 返回整个 Set                    | SSCAN 分步遍历                                 |
| `ZRANGE rank:demo 0 -1`  | 返回整个 Sorted Set（有序集合） | 限定索引或分值范围与数量                       |
| `XRANGE events:demo - +` | 返回大量 Stream 消息            | 如 `XRANGE events:demo - + COUNT 100` 限量读取 |

HSCAN/SSCAN 不提供一致性快照，COUNT 只是工作量提示，不是严格的返回元素上限；List 按索引分页时也要考虑并发插入造成位置变化。大响应还会占用客户端内存。命令边界可对照 [HSCAN](https://redis.io/docs/latest/commands/hscan/)、[SSCAN](https://redis.io/docs/latest/commands/sscan/)、[LRANGE](https://redis.io/docs/latest/commands/lrange/)、[ZRANGE](https://redis.io/docs/latest/commands/zrange/) 与 [XRANGE](https://redis.io/docs/latest/commands/xrange/)。

[UNLINK](https://redis.io/docs/latest/commands/unlink/) 自 Redis Open Source 4.0.0 提供：先从键空间移除，再将适用对象的内存释放交给后台；主线程仍有摘除、判断等工作，后台释放也消耗资源，并非零成本。它不能消除大读取、复制和网络成本。RSS（Resident Set Size，驻留内存大小）不立即下降也不证明删除失败，内存分配器可能保留已释放内存供后续使用。

## 4. 带宽、吞吐与排队要分开算

1 Gbit/s ÷ 8 = 125 MB/s。MB 按十进制 10⁶ 字节计，约等于 119.2 MiB/s（MiB 为 2²⁰ 字节）；实际还要扣除协议和链路开销。大回复即使计算很快，也可能使网络先达到瓶颈。

若 1 ms 是客户端端到端响应时间，不能直接取倒数当作服务器吞吐上限。若明确限定为单个串行执行路径，每条命令实际占用该路径 1 ms，忽略其他开销时，理论容量约为 1000 条/秒；增加客户端并发或 Pipeline 不消除这部分执行成本。

即 QPS ≈ 1 / 0.001 = 1000，是纸面服务能力。Pipeline（流水线批量发送）通过不逐条等待回复减少通信等待，不提供命令并行执行保证。

混合负载应按命令执行时间和比例估算服务需求，再考虑其他瓶颈。这是带假设的纸面模型。[第 17 章 Pipeline](/articles/redis-pipeline.html) 主要摊薄通信等待，不让占用同一串行路径的 CPU 工作凭空并行。

持久化资源竞争要并行检查：fork（创建子进程）本身可能暂停主进程，后台写盘也会竞争资源；AOF（Append Only File，追加写日志）的写入与 fsync（文件同步落盘系统调用）影响取决于策略，不能画成每条命令都必经的串行后续阶段，见 [第 19 章持久化](/articles/redis-rdb-aof.html)。

## 5. 压测不是诊断的第一动作

先保存版本、数据规模、实际命令分布与时间窗，再提出假设。需要实验时，在隔离环境控制并发、连接、值大小和 Pipeline。redis-benchmark 中 `-p` 是端口，`-P` 是 Pipeline 数量，大小写不能混淆。

redis-cli 的 `--raw` 倾向原始输出，`--no-raw` 倾向便于阅读的格式。

教学超时案例：假设应用超时设为 40 ms，观测到上文拆分的 45.5 ms，但 Slowlog 无记录。先核对阈值，再比对同一时间窗的池等待、重试次数、commandstats 与 latencystats、CLIENT LIST 缓冲、网络与系统负载。若池等待明显升高，而执行耗时分布与网络均稳定，可提出“连接占用或池容量导致等待”的假设；若连接持有时间稳定且池不饱和，则应推翻它。隔离环境中只调整一个连接使用因素，比较等待时间、超时率与服务端负载，再决定是否上线及回退。这个流程没有在生产执行，Slowlog 为空本身不能锁定根因；完整记录方式见 [第 30 章分层排障](/articles/redis-observability.html)。
