---
id: redis-cluster-operations
title: 第二十四章 Cluster 扩缩容、故障恢复与迁移规划
description: "Cluster 扩容依次涉及新节点加入、复制关系建立、槽与数据迁移、客户端拓扑更新和业务验收。沿着这些阶段记录状态，才能判断变更停在哪里、是否能够继续，以及回退需要恢复哪些数据。"
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
order: 24
---

# 第二十四章 Cluster 扩缩容、故障恢复与迁移规划

[返回本册目录](/collections/redis/)

Cluster 扩容依次涉及新节点加入、复制关系建立、槽与数据迁移、客户端拓扑更新和业务验收。沿着这些阶段记录状态，才能判断变更停在哪里、是否能够继续，以及回退需要恢复哪些数据。

本章传统迁移以 Redis Open Source 7.2.0 为核对基线；第五节单独讨论 8.4.0 引入的 ASM（Atomic Slot Migration，原子槽迁移）。本文命令均未实际运行，带 `<...>` 的内容是必须替换的占位符；流程图和预期结果都是教学说明，不是生产迁移脚本或实测记录。

![传统槽迁移的主要步骤](/assets/notes/redis/redis-study-reshard.svg)

## 1. 变更前确定目标、容量与恢复条件 {#_1-变更前先回答五个问题}

首先确定目标是缓解内存、CPU（Central Processing Unit，中央处理器）负载、热点还是恢复时间。若瓶颈在不能拆分的热点键，平均迁槽对该瓶颈的帮助有限。

其次核算目标节点与剩余节点的变更峰值，包括数据、复制缓冲、COW（Copy-On-Write，写时复制）、临时文件和网络流量，稳定态 `used_memory` 只是其中一项。资源峰值见[第二十章](/articles/redis-fork-copy-on-write.html)，备份和恢复验证见[第十九章](/articles/redis-rdb-aof.html)。

再验证客户端的重定向、地址发现和有界重试，尤其在迁移前确认 ASK 处理路径。

随后确认备份可恢复，并定义暂停、继续和回退方式。键已经分散到两端时，需要同时处理数据与元数据状态。

最后核对 Redis、redis-cli、扩展与迁移工具的版本组合。Redis Open Source 5.0.0 起，原先 `redis-trib.rb` 的管理功能整合进 `redis-cli --cluster`；旧 Ruby 工具和安装步骤按历史环境查阅。新服务端不代表本机 redis-cli 同时升级，旧版管理流程也不能直接用于 8.4.0 的原子迁移。[Cluster 管理工具说明](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)、[5.0.0 redis-cli 管理子命令](https://github.com/redis/redis/blob/5.0.0/src/redis-cli.c)

## 2. 迁出、迁入与所有权传播的中间状态 {#_2-传统迁槽为什么需要中间状态}

传统机制将源槽设为迁出、目标设为迁入，分批移动实际键。迁移中源节点仍可能保有部分键；不存在于源端的相关请求可能被 ASK 引导到目标。完成数据迁移后，再完成槽所有权传播与验证。

假设槽 100 由源主节点 A 负责，要迁往目标主节点 B，两者已在同一健康集群中。下面是 Redis 命令模板，分别在指定节点执行，不能把它们全发给一个节点。

先在 **B** 声明 IMPORTING（迁入），源 ID 为 A：

```redis
CLUSTER SETSLOT 100 IMPORTING <A_NODE_ID>
```

再在 **A** 声明 MIGRATING（迁出），目标 ID 为 B：

```redis
CLUSTER SETSLOT 100 MIGRATING <B_NODE_ID>
```

在 **A** 读取一批实际键名，再迁移返回的键；以下只展示其中一个：

```redis
CLUSTER GETKEYSINSLOT 100 10
MIGRATE <target-host> <target-port> <returned-key> 0 5000
```

`0` 是目标逻辑数据库，Cluster 仅使用 DB 0；`5000` 是通信超时参数，单位毫秒，不是整个迁槽必须在五秒内完成。目标认证还需按环境配置，示例省略凭据，不代表所有部署都可直接使用。正常成功预期返回 `OK`；若键已不存在也可能返回 `NOKEY`。重复取键、迁移并核对，直到源端该槽没有遗留键。

这时在 **B、A 及其他主节点** 推进槽归属，优先让 B 接管，再更新源和其他主节点，最后核对各方视图：

```redis
CLUSTER SETSLOT 100 NODE <B_NODE_ID>
```

迁移期间，A 仍处理本地已存在键的请求；源端不存在的单键请求可能得到 ASK。B 尚处于 IMPORTING 时，客户端必须在同一目标连接先发 `ASKING`，再发该次业务命令。MIGRATE 内部的导入路径会处理目标的迁入检查，不能据此省略业务客户端的 ASK 处理。最终的 NODE 更新和配置传播是元数据变更，MIGRATE 才传输实际数据。[SETSLOT 的节点状态](https://redis.io/docs/latest/commands/cluster-setslot/)、[第二十三章重定向](/articles/redis-cluster-routing.html)

因此，不能把“槽归属变了”等同于“所有数据都安全到位”。迁移批次、键大小、网络和目标负载都会影响业务延迟。大键可能拖慢单次搬迁，也可能明显阻塞源节点与目标节点。[传统重分片说明](https://redis.io/docs/latest/operate/oss_and_stack/management/scaling/)

MIGRATE 默认迁移的核心过程是：源端序列化键 → 目标导入并确认 → 源端删除原键。其单键原子性表示正常迁移不会让其他客户端穿插观察到“搬走了一半的键值”；**不代表整个槽的分批迁移是一个原子事务，也不代表业务零停顿。** 一批多键迁移不应视为遇到错误全部回滚的事务。

大键会增加序列化、网络传输和目标导入时间，影响业务尾延迟。批次要结合键的字节大小、负载和带宽调整，不能只固定每批十个键。超时或 I/O（Input/Output，输入输出）错误后，键可能同时留在源和目标，不能假定失败就毫无变化；应核对两端及返回错误后再决定重试。不要默认加 REPLACE 覆盖目标数据。[MIGRATE 的原子性和错误语义](https://redis.io/docs/latest/commands/migrate/)

迁移中途，不要随意通过删槽、强制归属、reset 或 fix 来“消除报错”。这些操作可能破坏原本尚可解释的数据状态。应先保存现场，再根据具体问题选择处置流程。

## 3. 迁出全部槽后核对冗余并退出节点 {#_3-缩容比清空节点复杂}

缩容要迁出节点负责的全部槽，确认没有遗留键和迁移状态，再处理复制关系及节点退出。若节点是副本，也要评估退出后故障域和冗余是否仍满足要求。

同一台机器上的主副本并不能抵御整机故障。缩容时为省资源把主副本集中到同一主机，可能把容量优化变成可用性退化。

| 变更阶段     | 可能的问题                   | 回退考虑                                           |
| ------------ | ---------------------------- | -------------------------------------------------- |
| 新节点加入   | 网络或配置错误               | 暂停，核对成员和通告地址，确认未承接数据再处理退出 |
| 建立复制关系 | 同步失败或角色错误           | 检查复制状态，避免退出后失去唯一有效副本           |
| 正在迁移     | 部分键已到目标               | 同时记录两端实际数据及 IMPORTING/MIGRATING 状态    |
| 槽归属变更   | 节点视图或客户端缓存尚未收敛 | 核对所有权版本、各方视图与缓存，避免盲目反复改归属 |
| 业务验收     | 延迟、错误率或业务结果异常   | 评估有计划的反向迁移和业务补偿，不承诺一条命令回退 |

**槽所有权回退不等于数据回退。** 键已到 B 时，只把槽改回 A 不会把数据搬回来。应依据已完成阶段处理数据与元数据，再确认客户端行为。

## 4. 联合验收集群状态与业务结果 {#_4-故障恢复不能只追求-cluster-state-ok}

完整阶段验收可按以下流程推进，其中 TTL（Time To Live，剩余生存时间）也是数据检查的一部分。新主与新增副本各自的角色必须清楚，不是让接收槽的新主去跟随另一主节点：

```text
变更前 → 容量和故障域评估 → 备份与恢复验证 → 检查客户端兼容性
→ 加入新节点 → 为需要冗余的主节点配置副本并确认同步
→ 迁移槽和数据 → 检查各方拓扑 → 验证业务请求和延迟
→ 核对数据与 TTL → 完成变更
```

不能只核对键数。验收至少覆盖：

| 维度       | 检查内容                                              |
| ---------- | ----------------------------------------------------- |
| 拓扑与复制 | 槽覆盖、所有权、遗留迁移状态、复制延迟和故障域        |
| 容量与负载 | 各节点内存、CPU 利用率、键数、数据字节、热点          |
| 客户端     | 从业务网络访问通告地址、重定向次数、重试和请求错误率  |
| 延迟       | P95/P99（95/99 百分位延迟），识别少量慢请求受到的影响 |
| 数据与恢复 | 核心值、类型、TTL、持久化状态及备份可恢复性           |

槽数量平均不代表字节和负载平均。集群状态正常，却因为重试导致业务重复扣减，仍然是一次失败的业务恢复。复制状态检查见[第二十一章](/articles/redis-replication-psync.html)。

变更前后可在多个数据节点按权限执行以下只读 Redis 命令：

```redis
CLUSTER INFO
CLUSTER NODES
CLUSTER SHARDS
INFO replication
```

另有 Shell 命令模板，需替换实际入口，认证按环境设置：

```bash
redis-cli --cluster check <host>:<port>
```

| 命令                        | 用途                                           |
| --------------------------- | ---------------------------------------------- |
| `CLUSTER INFO`              | 槽覆盖、已知节点数和集群状态                   |
| `CLUSTER NODES`             | 当前节点的拓扑、角色及槽状态视图               |
| `CLUSTER SHARDS`            | 分片及节点信息，Redis Open Source 7.0.0 起支持 |
| `INFO replication`          | 主从角色、复制链路和进度                       |
| `redis-cli --cluster check` | 从入口发现节点并检查槽分配和结构               |

节点视图可能暂时不同，不能只查一个节点，也不能把工具显示正常当作业务验收。上述观察与 SETSLOT、MIGRATE、RESET、`--cluster fix` 等修改操作性质不同；后者不能当默认检查步骤。

节点地址也要从真实客户端所在网络验证。容器或 NAT（Network Address Translation，网络地址转换）环境中，节点通告了不可达地址，会导致入口能连接、重定向后失败。Redis Open Source 7.2.0 总线端口默认是数据端口加 10000，也可通过 `cluster-port` 指定，应以实际配置为准。

## 5. 8.4+ 的新能力单独看待

Redis Open Source **8.4.0** 引入 ASM 和 `CLUSTER MIGRATION`。它在后台传输槽快照并追赶期间的新写入，再交接槽所有权，减少传统逐键迁移中同槽数据散落两端的问题。它是一套新机制，不能把前面的手工 IMPORTING/MIGRATING 步骤直接套进来。[8.4 发布说明](https://redis.io/docs/latest/develop/whats-new/8-4/)

### 发起、观察与取消任务

以下以 **8.4.0 固定源码**核对语法。IMPORT 在目标主节点 B 执行，参数是成对的闭区间起止槽号，单槽也要写两次：

```redis
CLUSTER MIGRATION IMPORT 100 100
```

成功预期返回任务 ID 字符串。需要导入多个范围时，语法可以是 `CLUSTER MIGRATION IMPORT 0 1000 2000 3000`，前提是这些槽当前属于同一个源主节点，目标不是该源，且满足稳定状态等检查。**IMPORT 不传源节点 ID**，源节点由当前槽归属推断；上述四个数字示例经核实语法有效，但不代表任意集群的槽分配都允许它执行。

在 8.4.0 中，目标必须是主节点，不能残留传统手工迁移状态，槽必须有归属且范围合法、不重叠；同一节点一次只维护一个当前 ASM 任务，失败任务另有清理处理。它不是任意跨源并发导入接口。[8.4.0：validateImportSlotRanges 与 asmCreateImportTask](https://github.com/redis/redis/blob/8.4.0/src/cluster_asm.c)

以下查询在实际参与任务的节点执行；`<task-id>` 要替换为 IMPORT 返回的 ID：

```redis
CLUSTER MIGRATION STATUS ALL
CLUSTER MIGRATION STATUS ID <task-id>
```

8.4.0 实现要求提供 ALL 或 ID 参数，不能仅根据最新文档的可选参数写法省略它们。返回值是任务列表；每个任务在 RESP3（Redis Serialization Protocol version 3，Redis 序列化协议第三版）下是字段映射，RESP2 下表现为字段和值的数组。重点看：

| 字段                                    | 含义                                                             |
| --------------------------------------- | ---------------------------------------------------------------- |
| `id`、`slots`                           | 任务 ID 与槽范围                                                 |
| `source`、`dest`、`operation`           | 源、目标节点 ID，以及本地 import/migrate 角色                    |
| `state`                                 | 具体阶段；成功结束为 `completed`，不能只等一个笼统的“运行中”状态 |
| `last_error`、`retries`                 | 最近错误与重试次数                                               |
| `create_time`、`start_time`、`end_time` | 任务时间记录                                                     |
| `write_pause_ms`                        | 写暂停时长，单位毫秒，结合任务阶段和角色解释                     |

STATUS 包含当前和本地保留的归档任务，查不到 ID 可返回空列表，不是集群所有节点的全局历史。以下是**修改任务的命令模板**，不属于只读诊断：

```redis
CLUSTER MIGRATION CANCEL ID <task-id>
CLUSTER MIGRATION CANCEL ALL
```

CANCEL 返回本节点取消的当前任务数量。已完成或取消后归档的任务不属于可取消的当前任务，返回 0 不能证明另一端已经停止。在源端取消，不会自动终止目标端的导入重试；需要按目标端、源端分别查询和取消，并核对最终槽归属、清理状态和业务数据。取消不等于反向迁移，也不回滚已经完成的所有权交接。[命令接口](https://redis.io/docs/latest/commands/cluster-migration/)、[8.4.0 状态查询与取消实现](https://github.com/redis/redis/blob/8.4.0/src/cluster_asm.c)

### 交接阶段仍可能暂停写入

快照完成后，源端检查目标还没追完的复制流字节数。差距小到阈值以内时，进入交接并暂停源节点写入，让目标追完剩余数据并接管槽。原子性关注槽交接的完整性，不意味着没有等待或客户端重定向。

| Redis Open Source 8.4.0 配置项                 | 默认值                 | 作用与取舍                                                                     |
| ---------------------------------------------- | ---------------------- | ------------------------------------------------------------------------------ |
| `cluster-slot-migration-handoff-max-lag-bytes` | `1mb`，即 1048576 字节 | 剩余复制流小于阈值后触发交接；较大可较早交接，但可能暂停更久；较小可能更难追到 |
| `cluster-slot-migration-write-pause-timeout`   | `10000` 毫秒，即 10 秒 | 源节点交接写暂停的超时保护，不是任务总时限，也不是每次必停十秒                 |

目标未及时接管时，源端超时会恢复写入并认为迁移失败。**把暂停超时设得过低存在数据丢失风险**：源已恢复写入，但目标稍后仍发布接管配置，这个窗口的新增写入可能未传到目标。不能把超时恢复写入解释为无风险回退，也不能直接用默认值承诺业务延迟。[8.4.0 redis.conf 的交接说明](https://github.com/redis/redis/blob/8.4.0/redis.conf)、[config.c 的实际默认值](https://github.com/redis/redis/blob/8.4.0/src/config.c)

### 迁移中“看见多少键”也有边界

Redis Open Source 8.4.0 原子导入或清理期间，节点物理内存中可能仍有尚未归自己所有的槽数据。`KEYS`、`SCAN`、`DBSIZE` 等会过滤这类未归属槽中的键；`RANDOMKEY`、`CLUSTER GETKEYSINSLOT` 和 `CLUSTER COUNTKEYSINSLOT` 也有相应过滤。因此不能把 SCAN 结果或 DBSIZE 当成迁移内部所有键的清单。

`INFO keyspace` 仍统计本地实际存储的键，包括正在导入的数据，可能与前述可见键数不同。这是 8.4.0 ASM 场景的观察边界，不应推广为 7.x 传统迁移的统计规则。[迁移期间键可见性](https://redis.io/docs/latest/commands/cluster-migration/)、[8.4.0 db.c](https://github.com/redis/redis/blob/8.4.0/src/db.c)、[server.c 的 Keyspace 统计](https://github.com/redis/redis/blob/8.4.0/src/server.c)

本章提供变更分析框架，不提供默认可执行的脚本。实际迁移时，应先明确环境、维护窗口、恢复点与授权，再编写命令；此次没有连接或改变任何集群。
