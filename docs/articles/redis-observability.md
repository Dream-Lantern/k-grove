---
id: redis-observability
title: 第三十章 INFO、客户端缓冲与分层排障
description: "INFO 提供实例、客户端、复制和内存等状态线索。诊断时先确定实例身份与症状，再在同一时间窗内关联客户端、Redis 和操作系统的证据，逐步形成可验证的原因与处置方案。"
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
order: 30
---

# 第三十章 INFO、客户端缓冲与分层排障

[返回本册目录](/collections/redis/)

INFO 提供实例、客户端、复制和内存等状态线索。诊断时先确定实例身份与症状，再在同一时间窗内关联客户端、Redis 和操作系统的证据，逐步形成可验证的原因与处置方案。

![分层建立排障假设](/assets/notes/redis/redis-study-triage.svg)

## 1. 先确定自己在看哪个实例

记录版本、运行模式、角色、运行时长和采样时间。刚重启的实例累计计数较低，不代表负载一直很低；连接了副本也不能按主节点预期解释所有指标。

CPU（Central Processing Unit，中央处理器）的累计耗时需要用区间差值观察。以下 `redis` 代码块是发给 Redis 的观察命令，不是 Shell（命令解释环境）命令；基线为 Redis Open Source 7.2.0，例外另标，不能据此推断 Redis Software 或 Redis Cloud 的能力。本章未连接实例执行命令，案例数字均为教学假设。

```redis
INFO server
INFO clients
INFO stats
INFO memory
INFO persistence
INFO replication
INFO commandstats
INFO latencystats
INFO cpu
INFO keyspace
```

这些是观察示例，实际权限和产品可能限制字段。缺失字段应记录为不可用，而不是自动填成零。[INFO 字段参考](https://redis.io/docs/latest/commands/info/)

| 分类         | 重要字段                                        | 观察目的与单位                                                         |
| ------------ | ----------------------------------------------- | ---------------------------------------------------------------------- |
| server       | redis_version、uptime_in_seconds、redis_mode    | 版本、运行秒数、运行模式                                               |
| clients      | connected_clients、blocked_clients              | 普通客户端连接数（不含副本连接）、阻塞操作中的客户端数；阻塞不等于故障 |
| stats        | instantaneous_ops_per_sec、rejected_connections | 近期采样的每秒命令数、因 maxclients 限制被拒绝的累计连接数             |
| stats        | evicted_keys、expired_keys                      | 因内存限制淘汰、因期限到达过期的累计键数                               |
| memory       | used_memory、used_memory_rss                    | 分配器统计的 Redis 内存、操作系统看到的驻留内存，均为字节              |
| persistence  | rdb_bgsave_in_progress、aof_rewrite_in_progress | RDB 后台快照、AOF 重写是否进行中，0/1 状态                             |
| replication  | role、master_link_status、master_repl_offset    | 角色、副本到主节点的链路状态、复制流字节偏移；链路字段依角色出现       |
| commandstats | calls、usec、usec_per_call                      | 调用累计数、累计执行微秒、平均执行微秒；平均不是 P99                   |
| latencystats | p50、p99、p99.9                                 | 按命令统计的执行耗时分位数，单位微秒；默认最后一项也称 P999            |
| cpu          | used_cpu_user、used_cpu_sys                     | Redis 进程累计用户态、内核态 CPU 秒数，不是当前使用百分比              |
| keyspace     | dbN 的 keys、expires、avg_ttl                   | 键数、有期限的键数、平均剩余期限估计（毫秒），不是字段级 TTL 统计      |

RDB（Redis Database，数据库快照）保存时点数据；AOF（Append Only File，追加写日志）记录写入。持久化标记只能说明状态，需联合时长、结果、磁盘与 fork（创建子进程）观察，见 [第 19 章](/articles/redis-rdb-aof.html)。RSS（Resident Set Size，驻留内存大小）与分配器统计不必相等，内存判断见 [第 25 章](/articles/redis-memory-eviction.html)。

latencystats 自 Redis Open Source 7.0.0 提供，需启用 latency-tracking（命令延迟跟踪）且已有样本；7.2.0 默认启用，分位配置默认 50、99、99.9。分位数表示相应比例样本不超过的值，不是端到端等待；P99 即第 99 百分位数。核验依据为 [7.0.0 配置](https://github.com/redis/redis/blob/7.0.0/redis.conf)、[7.2.0 INFO 实现](https://github.com/redis/redis/blob/7.2.0/src/server.c)，工具口径见 [第 29 章](/articles/redis-slow-queries.html)。

解析程序应容忍新字段、缺失字段与角色差异，将缺失记为 N/A（Not Available，不可用）。重启、统计重置、切换实例都会破坏累计值的连续性；先确认实例身份和时间，再计算差值。版本适配方法见 [第 32 章](/articles/redis-upgrade-validation.html)。

## 2. 用症状选择证据

连接问题可能涉及 DNS（Domain Name System，域名系统）、TLS（Transport Layer Security，传输层安全协议）和 ACL（Access Control List，访问控制列表）。内存问题还需区分分配器（Allocator）与 COW（Copy On Write，写时复制，即父子进程写入共享内存页时再复制）的开销。

| 症状       | Redis 侧线索                          | 还需核对                    |
| ---------- | ------------------------------------- | --------------------------- |
| 连接失败   | 连接数、拒绝连接计数、错误类型        | DNS、网络、TLS、ACL、连接池 |
| 延迟升高   | Slowlog、命令统计、持久化状态         | 应用排队、网络、CPU、磁盘   |
| 内存异常   | 数据、缓冲、allocator、淘汰与过期计数 | RSS、容器限制、COW、交换    |
| 副本读旧值 | 链路、同步状态、偏移变化              | 请求路由、时间窗、业务版本  |

表中的指标只是线索。`evicted_keys` 和 `expired_keys` 分别是淘汰与过期的累计数，需要观察其变化率，并结合业务结果判断，不能仅因数值非零就认定刚刚发生了故障。

Counter（累计计数器）的区间平均速率为：

```text
Rate = (Counter_t2 - Counter_t1) / (t2 - t1)
```

教学假设：60 秒内 expired_keys 从 1000 到 1600，则平均每秒过期 10 个键，不代表每一秒都恰好 10 个。过期增长常属正常生命周期；淘汰增长则要结合 maxmemory（内存上限）、策略和命中率判断。计数回退、实例变化或重置后，应丢弃跨界差值重新取样，不能得到负速率后仍照常告警。

## 3. 根据连接类别解释缓冲增长 {#_3-输入与输出缓冲为什么增长}

输入侧可能因大请求、Pipeline 积压或处理速度不足出现压力；输出侧则可能因大回复、慢读客户端、订阅者消费慢或复制链路落后而增长。

```redis
CLIENT LIST
CONFIG GET client-output-buffer-limit
```

CLIENT LIST 能帮助定位连接；连接多时列举也有成本，应控制采样频率。以下内存口径对照 Redis Open Source 7.2.0：

| 字段      | 含义与单位                                   | 诊断用途                                           |
| --------- | -------------------------------------------- | -------------------------------------------------- |
| qbuf      | 当前查询输入缓冲长度，字节                   | 看尚待解析的输入                                   |
| qbuf-free | 查询缓冲剩余分配空间，字节                   | 看缓冲容量，不能当待处理请求量                     |
| argv-mem  | 为下一条命令已从查询缓冲提取的参数占用，字节 | 看解析阶段已积累的参数；不是只算参数指针数组       |
| obl       | 当前输出缓冲已用长度，字节                   | 看待发送回复                                       |
| oll       | 输出链表节点数；副本连接还涉及复制缓冲块     | 不是字节数，也不是业务消息条数                     |
| omem      | 输出链表等占用内存，字节                     | 7.2.0 不含内联回复缓冲；副本按共享复制缓冲口径计算 |
| tot-mem   | 客户端缓冲及相关结构的总内存估算，字节       | 不是上述已用长度直接相加                           |
| age       | 连接已存在的秒数                             | 区分新连接与长期连接                               |
| idle      | 空闲秒数                                     | 联合连接类别判断，不能仅据此断连                   |
| cmd       | 最近执行的命令名                             | 不保证是此刻正在执行的命令                         |

字段定义与实现参见 [CLIENT LIST](https://redis.io/docs/latest/commands/client-list/) 和 [7.2.0 networking.c](https://github.com/redis/redis/blob/7.2.0/src/networking.c)。输入增长可能是大请求、Pipeline（流水线批量发送）积压或处理不及时；输出增长可能是大回复、慢客户端，或 Pub/Sub（Publish/Subscribe，发布/订阅）订阅者读取不及时。复制连接还要看偏移推进和链路状态，缓冲增长本身不能证明 Redis 故障。

字段随版本演进，以下为 Redis Open Source 引入版本，依据官方 CLIENT LIST 的 History：

| 版本  | 新增字段                                   |
| ----- | ------------------------------------------ |
| 6.2.0 | argv-mem、tot-mem（同版还有 laddr、redir） |
| 7.0.0 | multi-mem、resp、rbs、rbp                  |
| 7.0.3 | ssub                                       |
| 7.2.0 | lib-name、lib-ver                          |
| 7.4.0 | watch                                      |
| 8.0.0 | io-thread                                  |

`client-output-buffer-limit` 按 normal（普通）、replica（副本）、pubsub（订阅）连接分类，7.2.0 配置说明允许 replica 使用旧称 slave。每类有 hard limit（硬限制，字节）、soft limit（软限制，字节）和 soft seconds（持续秒数）：达到硬限制可立即断开，持续超过软限制指定时长也会断开；0 表示相应限制不启用。不存在所有部署统一的“固定 1 GB 输出上限”。应先读取实际配置与连接类别，再关联断连日志、重连和消费速度，勿直接套用默认值。见 [7.2.0 redis.conf](https://github.com/redis/redis/blob/7.2.0/redis.conf)。

新版 INFO stats 的 `client_output_buffer_limit_disconnections` 是因输出缓冲超限断连的累计数；已核实 [7.4.0 server.c](https://github.com/redis/redis/blob/7.4.0/src/server.c) 有该字段，7.2.0 没有，不能要求旧版返回或把缺失填成 0。这里只展示只读观察，未调整限制。

直接断开连接可能丢失未确认结果或订阅消息。处置前先确认客户端身份、业务影响与恢复方式，不把 CLIENT KILL 当成只读排障命令。

## 4. 常见错误先按层分类

错误先分认证、授权、数据模型、路由和资源限制，具体文字与产品版本可能不同：

| 错误      | 常见含义                 | 优先核对                        |
| --------- | ------------------------ | ------------------------------- |
| NOAUTH    | 连接未完成所需认证       | AUTH、连接初始化                |
| WRONGPASS | 凭据无效或用户被禁用     | 用户名、密码、账号状态          |
| NOPERM    | 已认证但权限不足         | 命令、Key、Channel 授权         |
| WRONGTYPE | 键类型不适用此命令       | 写入方与数据模型                |
| MOVED     | 请求应交给槽位归属节点   | Cluster 槽位映射与连接路由      |
| ASK       | 迁移中的临时重定向       | 目标连接的 ASKING 与当前请求    |
| READONLY  | 写入了只读副本等受限连接 | 实例角色、主节点发现与路由      |
| OOM       | 内存限制阻止相应写操作   | maxmemory、淘汰策略、对象与缓冲 |

ACL 自 Redis Open Source 6.0.0 提供，NOPERM 要分别查命令、键和频道范围，不能看到错误就扩大账号权限，见 [官方 ACL](https://redis.io/docs/latest/commands/acl/) 和 [第 31 章](/articles/redis-security-maintenance.html)。

MOVED 通常要求客户端更新槽位映射；ASK 只针对当前迁移请求，应在目标节点的同一连接上先 ASKING，再发送该请求，不能据此永久改槽位映射，也不能绕过认证授权。路由协议详见 [Cluster 规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/) 与 [第 24 章集群运维](/articles/redis-cluster-operations.html)。

`nil` 或空结果不等同异常，它可能是键不存在、范围没有元素或事务冲突等正常协议结果。客户端必须结合命令语义解释，而不是统一返回“Redis 连接失败”。

例如 [MGET](/articles/redis-strings.html) 对非 String 键也会给出逐键 nil；[HTTL](https://redis.io/docs/latest/commands/httl/) 自 Redis Open Source 7.4.0 提供，查询 Hash 字段的 TTL（Time To Live，存活时间），不等于整个 Hash Key 的 TTL：

```redis
HTTL user:1001 FIELDS 3 name age status
```

返回按字段顺序排列的整数数组。正数为剩余秒数（7.4.0 按剩余毫秒向上取整），-1 表示字段存在但未设字段期限，-2 表示 Key 或字段不存在。教学假设 name 剩余约 30 秒、age 无字段期限、status 缺失，预期返回 `[30,-1,-2]`；Key 整体缺失则预期 `[-2,-2,-2]`；Key 为非 Hash 类型则报 WRONGTYPE，字段数与实参不匹配则报参数错误。这些是按语义推演的示意，不是实测。

官方页面示例曾把缺失 Key 显示成 nil，与同页返回说明不一致；此处以 [7.4.0 t_hash.c 的 httlGenericCommand](https://github.com/redis/redis/blob/7.4.0/src/t_hash.c) 为依据，保留逐字段 -2 数组。更多字段过期行为见 [Hash 章节](/articles/redis-hashes.html)。

## 5. 形成可复核的诊断记录

一份有效的诊断记录可以包含症状与时间、业务影响、只读采样、候选原因、反证、拟采取的最小变更，以及回退和验收方式。先定位问题再调整参数，有助于避免将短暂恢复误认为根因已经解决。

教学案例：应用报告 Redis 请求 P99 从 2 ms 升到 80 ms。以下只是拟定排查流程，未执行采样或验证，不宣称某个指标已证实根因：

1. 客户端侧记录连接池等待、线程等待、超时、重试次数和响应大小，确认这两个 P99 的采样范围一致。
2. 同时采集 Redis Slowlog、commandstats、latencystats、CLIENT LIST，区分执行变慢、输入积压与输出滞留；Slowlog 空也不能排除排队。
3. 关联 Redis CPU、内存、复制与持久化状态，以及 OS（Operating System，操作系统）的 CPU、调度、内存、磁盘与网络；观察 fork 暂停和后台任务的资源竞争。
4. 对齐时钟与同一时间窗，保留采样间隔、实例角色和重置事件；不能拿重启前后的累计量或不同时间段直接比较。
5. 提出可反驳的假设。例如“大回复导致慢客户端输出积压”，应同时找回复变大、omem 增长、网络或解码压力；若回复大小、缓冲和网络均稳定，应寻找其他原因。
6. 在隔离环境限定某类读取的返回量作为最小实验，比较端到端延迟、吞吐与缓冲变化；先定义回滚条件，再决定是否在生产小范围变更并验收。相关性不等于因果关系，实验结果也要记录适用范围。

区分观察和处置，命令权限允许并不意味着可以任意执行：

| 操作             | 影响                                   |
| ---------------- | -------------------------------------- |
| INFO、CONFIG GET | 读取状态或配置；仍需控制频率与信息暴露 |
| SLOWLOG GET      | 查看慢日志，可能含敏感参数             |
| CLIENT LIST      | 列举连接，连接多时也有工作量           |
| CLIENT KILL      | 断开连接，影响未确认结果和订阅         |
| CONFIG SET       | 修改运行配置                           |
| LATENCY RESET    | 清除事件观测记录，影响后续取证         |
| FLUSHDB          | 删除当前数据库数据                     |

此表后四项仅用于辨认风险，不是本次执行计划。操作语义可查 [CLIENT KILL](https://redis.io/docs/latest/commands/client-kill/)、[CONFIG SET](https://redis.io/docs/latest/commands/config-set/)、[LATENCY RESET](https://redis.io/docs/latest/commands/latency-reset/)、[FLUSHDB](https://redis.io/docs/latest/commands/flushdb/)。

排障记录可按下面的文本模板填写，未验证的结论保留为假设：

```text
故障时间与时区 / 采样间隔：
实例标识、版本、角色 / 重启或切换：
业务影响与请求范围：
客户端观测（池等待、超时、重试、响应大小）：
Redis 观测（命令、缓冲、内存、复制、持久化）：
OS 观测（CPU、内存、磁盘、网络）：
候选根因 / 支持证据 / 反证：
最小验证实验与结果（未执行则注明）：
变更方案 / 风险 / 回滚方式及触发条件：
验收时间窗、指标与结果：
```

CLIENT LIST、Slowlog 与监控数据可能含 IP、键名、命令参数、业务标识及客户端库信息。公开材料须脱敏并使用合成示例；真实部署信息保留在私有来源，公开材料不据此补写架构。
