---
id: redis-security-maintenance
title: 第三十一章 安全、备份、多实例与维护边界
description: "Redis 维护需要共同管理网络可达性、身份权限、数据文件与恢复条件。本章按访问控制、凭据、多实例和备份验收组织要点；示例采用占位信息，不包含真实内网地址、账号或部署清单。"
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
order: 31
---

# 第三十一章 安全、备份、多实例与维护边界

[返回本册目录](/collections/redis/)

Redis 维护需要共同管理网络可达性、身份权限、数据文件与恢复条件。本章按访问控制、凭据、多实例和备份验收组织要点；示例采用占位信息，不包含真实内网地址、账号或部署清单。

## 1. 网络、认证、授权、加密各管一层

监听地址和防火墙限制谁能到达服务；认证识别客户端；ACL（Access Control List，访问控制列表）限制可以执行的命令与访问的键；TLS（Transport Layer Security，传输层安全协议）保护适用链路的传输。AUTH 是认证命令，仅配置 AUTH 不代表传输已经加密，仅修改默认端口也不构成有效访问控制。

Redis 应放在受控网络内，由可信应用访问，不直接暴露给不可信终端。不要为解决一次连接失败，就默认关闭 protected mode（保护模式） 或允许公网无认证访问。[Redis 安全模型](https://redis.io/docs/latest/operate/oss_and_stack/management/security/)

Redis Open Source 6.0.0 起提供 ACL。应按业务需要授予最小命令和键空间权限，区分应用、运维、复制与 Sentinel（哨兵）等用途；升级时重新检查命令类别变化，而不是永久沿用过宽账号。[ACL](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/)

键范围与 Pub/Sub（Publish/Subscribe，发布/订阅）频道范围是不同规则：`~demo:*` 描述键权限；Redis Open Source 6.2.0 起的 `&demo:*` 描述适用频道权限。允许访问同名键，不等于频道已经隔离，仍需对应的命令权限。

PUBLISH/SUBSCRIBE 的频道名可按允许频道模式匹配；PSUBSCRIBE 的订阅模式则有与允许模式进行字面匹配的规则，不能简单按“两个 glob 看起来包含”推导。allchannels 等宽权限又会改变整体结果。设计后分别测试允许/拒绝的键、发布、订阅路径，不用管理员账号证明最小权限正确。

以下 `redis` 代码块是 Redis 命令，均未实际运行；修改账号、数据或备份状态的示例只适用于隔离环境。账号、键和频道使用虚构的 `demo:` 范围，口令为占位值；不要原样用于生产，也不要把 `>`、`<` 当成 Shell（命令解释环境）重定向。以 Redis Open Source 7.2.0 为例，由管理员创建专用测试用户：

```redis
ACL SETUSER demo:pub-user reset on >placeholder resetchannels &demo:news.* +subscribe +psubscribe +unsubscribe +punsubscribe
```

`reset` 清除该测试账号旧规则，`resetchannels` 去掉宽频道权限，再授权 `demo:news.*`。新连接用 `AUTH demo:pub-user placeholder` 认证后，下表是分别在独立连接测试的预期授权结果，不是实测记录：

| 命令                        | 预期授权结果     | 原因                       |
| --------------------------- | ---------------- | -------------------------- |
| `SUBSCRIBE demo:news.tech`  | 允许             | 具体频道名匹配授权模式     |
| `PSUBSCRIBE demo:news.*`    | 允许             | 订阅模式与授权模式字面相同 |
| `PSUBSCRIBE demo:news.tech` | NOPERM，权限不足 | 虽然范围更窄，字面仍不同   |
| `SUBSCRIBE demo:other.tech` | NOPERM           | 不在频道范围内             |

这不是“PSUBSCRIBE 可以绕过权限”：其模式要求字面匹配。若规则中仍有 `allchannels`（即 `&*`），频道检查将放宽，不能再得出上表的拒绝结论；命令权限仍须满足。可在 Redis Open Source 7.0.0 起使用 `ACL DRYRUN demo:pub-user PSUBSCRIBE demo:news.tech` 模拟检查，不实际订阅。匹配细节已对照 [7.2.0 acl.c](https://github.com/redis/redis/blob/7.2.0/src/acl.c)，模拟检查参见 [ACL DRYRUN](https://redis.io/docs/latest/commands/acl-dryrun/)。

新用户的频道默认值也有版本边界：Redis Open Source 6.2.0 的 `acl-pubsub-default` 默认 `allchannels`；7.0.0 改为 `resetchannels`。这是新用户初始化的默认行为，不能代替检查已加载的具体账号规则，更不能推广为 Redis Cloud 的默认权限。依据为 [6.2.0 配置](https://github.com/redis/redis/blob/6.2.0/redis.conf)与 [7.0.0 配置](https://github.com/redis/redis/blob/7.0.0/redis.conf)。

Redis Open Source 8.0.0 统一发行版还改变了类别覆盖：JSON、Time Series（时间序列）、Vector（向量）、Probabilistic（概率型结构）相关命令进入标准 `@read`、`@write` 等类别。原规则可能扩大授权，也可能因否定类别而拒绝原来可用的命令，例如 `+@all -@write` 会排除 JSON.SET。升级前后都应比较实际命令类别和账号规则，再用应用账号检查允许及拒绝路径，不能只确认 AUTH 成功。参见 [8.0 ACL 兼容变化](https://redis.io/docs/latest/develop/whats-new/8-0/#access-control-improvements)与 [第 32 章升级验证](/articles/redis-upgrade-validation.html)。

普通键级 ACL 也不会自动对一个 Hash 中的不同 field（字段）做独立授权。若权限边界需要分别控制字段，应重新评估拆键或在可信应用层授权，见 [第 2 章建模](/articles/redis-data-modeling.html)和 [第 4 章 Hash](/articles/redis-hashes.html)。本节没有修改任何账号。

## 2. 凭据的保存、轮换与公开材料检查 {#_2-凭据不要出现在命令历史与文章中}

示例使用虚构的 `demo:` 命名空间和占位参数。真实口令、证书、内部地址、客户标识不应被提交到博客仓库。命令行参数、进程列表、Slowlog、终端截图与复制日志都可能泄露信息。

轮换凭据时，还需同步考虑连接池、自动任务、复制和监控。变更认证设置前，应先确认恢复通道，避免正常维护导致集体断连。

一个 ACL 用户可以同时有多个有效密码。假设隔离环境的 `demo:app` 已使用密码 A 且已有正确权限，先增加 B，不重置其他规则：

```redis
ACL SETUSER demo:app >password-B-placeholder
```

`>password` 添加有效密码。先持久化这一中间状态，再让应用逐批切换到 B，并主动验证新连接认证；连接池旧连接、后台任务、复制、监控和故障备用配置都要纳入。CLIENT LIST 不会告诉你某条连接使用了哪个密码，不能据其用户字段断言 A 已无人使用；需结合客户端配置清点、连接更新和认证观测，排障入口见 [第 30 章](/articles/redis-observability.html)。

确认全部调用方已迁移、B 的恢复通道可用后，才删除 A 并再次持久化：

```redis
ACL SETUSER demo:app <password-A-placeholder
```

`<password` 删除指定有效密码；它不等于强制断开所有已经认证的旧连接。完整流程是“A 生效 → 增加 B → 切换调用方 → 验证新连接与认证 → 撤销 A”。删除 A 前若 B 验证失败，可让调用方切回仍有效的 A；不要先撤销唯一可用凭据。规则语义见 [ACL SETUSER](https://redis.io/docs/latest/commands/acl-setuser/)。

运行态改动不等于重启后仍保留。Redis Open Source 6.0.0 起，配置 `aclfile` 时，`ACL SAVE` 将内存中的用户规则写入该外部 ACL 文件；未配置外部文件或不可写会报错。若用户直接配置在 redis.conf 中，则用 `CONFIG REWRITE` 重写配置文件。两种用户配置方式不能混用，CONFIG REWRITE 不会自动执行 ACL SAVE；还需确认配置管理不会用旧规则覆盖文件。持久化本身也会修改文件，本文未执行，参见 [ACL SAVE](https://redis.io/docs/latest/commands/acl-save/)和 [ACL 配置文件说明](https://redis.io/docs/latest/operate/oss_and_stack/management/security/acl/#use-an-external-acl-file)。

## 3. 多实例的目录、身份与资源隔离 {#_3-多实例隔离不只有端口}

同机部署多个实例时，需要分别管理各自的配置、数据目录、日志、进程身份、端口和持久化文件，防止文件相互覆盖。现代 AOF 目录也属于实例资源，不能只修改 dbfilename 就认为已经完成隔离。

在 Linux 上，systemd（系统与服务管理器）的服务单元、运行用户、PID（Process ID，进程标识）文件、配置目录、数据目录、appenddirname（AOF 目录）与日志应分别管理。服务名称不同仍不足以隔离资源；按需要配置 CPU（Central Processing Unit，中央处理器）与内存限制，并把共享磁盘 I/O（Input/Output，输入输出）的竞争纳入评估。

CPU、内存、磁盘、网络和故障域仍然共享。maxmemory 是 Redis 的内存控制参数，不是整个进程或主机的硬上限。教学假设：16 GiB 主机上两个实例各设 6 GiB，虽然 6 + 6 < 16，剩余 4 GiB 仍可能不足以容纳操作系统、其他进程、客户端与持久化缓冲、fork（创建子进程）和 COW（Copy On Write，写时复制）峰值，从而触发 OOM（Out Of Memory，内存耗尽）。GiB 为 2³⁰ 字节；这些数字是预算示意，不是容量建议或实测。同机主副本也不能抵御主机故障，见 [第 20 章 fork/COW](/articles/redis-fork-copy-on-write.html)与 [第 25 章内存预算](/articles/redis-memory-eviction.html)。

## 4. 备份验收必须包含隔离恢复

[![备份验收：文件存在之后还要验证恢复](/assets/notes/redis/redis-study-backup.png)](/assets/notes/redis/redis-study-backup.png)

备份清单要说明版本、数据文件集合、配置、函数或扩展依赖、加密及访问权限。多部分 AOF 应取得一致的完整文件集，模块数据还要核对兼容版本。

RDB（Redis Database，数据库快照）保存时点数据；AOF（Append Only File，追加写日志）记录写操作。Redis Open Source 7.0.0 起的 MP-AOF（Multi-part AOF，多部分 AOF）由 BASE（基础文件）、后续 INCR（Incremental，增量文件）及 Manifest（文件清单）组成。AOF Rewrite（日志重写）把当前数据重新生成更紧凑的基础表示，同时新写入继续进入增量文件，最后切换清单并回收旧文件。

因此，在重写过程中逐个复制目录，可能拿到“旧清单 + 新文件”或缺少被清单引用的文件。单次 INFO 显示没有重写，也不保证复制期间不会开始重写：

```redis
INFO persistence
```

检查 `aof_rewrite_in_progress`、`aof_rewrite_scheduled` 和重写结果，并按已验证的流程协调重写窗口或使用一致性文件系统快照。备份必须包含同一恢复集合中的清单与全部被引用文件；不能将任意时刻打包 appendonlydir 当成可靠方案。机制与官方旧版备份流程见 [持久化文档](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/#backing-up-aof-persistence)，原理见 [第 19 章](/articles/redis-rdb-aof.html)。

**Redis Open Source 8.10.0 在线备份。** BACKUP 命令族由节点生成可恢复的独立文件集，调用方仍负责传输、校验和保留；不是自动完成异地备份。以下是隔离环境中的分阶段命令，必须按实际状态推进，不能一次无条件连续发送：

```redis
BACKUP START
BACKUP STATUS
```

START 打开备份窗口，在 `dir` 下的 `backupdirname` 生成基础快照；目录起初必须为空，单实例一次只有一个备份。可能先进入 pending（等待），再 snapshotting（生成快照）；直到 STATUS 返回 incrementing（累积增量），才说明 BASE 已固定。AOF 原来关闭也可使用，Redis 会临时启用相关机制而不改变配置的 appendonly 值。START 返回 OK 不表示完整备份已经就绪，见 [START](https://redis.io/docs/latest/commands/backup-start/)与 [STATUS](https://redis.io/docs/latest/commands/backup-status/)。

```redis
BACKUP LIST
```

LIST 返回已经通过硬链接固定、不会再变化的文件绝对路径。incrementing 阶段通常只有 BASE，可提前复制它，但这不是完整恢复集，不能清理或宣称备份成功，见 [LIST](https://redis.io/docs/latest/commands/backup-list/)。

```redis
BACKUP SEAL
BACKUP STATUS
BACKUP LIST
```

SEAL 将状态从 incrementing 推进到 sealed（封存），同步增量文件并固定 BASE、INCR 与独立 Manifest。恢复数据对应 **SEAL 的边界**，不是 START 时刻或仅 BASE 的时点。必须重新 LIST，复制全部最终文件并保存相对布局、大小与校验摘要；若曾提前复制 BASE，也要核对它属于这次清单。参见 [SEAL](https://redis.io/docs/latest/commands/backup-seal/)。这是节点边界，跨节点业务一致性还需要额外协调。

确认异地副本完整、校验通过且保留策略满足后，才进入清理阶段：

```redis
BACKUP CLEANUP
```

CLEANUP 清理 sealed 或 failed 状态的本地备份文件并返回 idle（空闲），不是备份上传命令。若配置了非零 `backup-sealed-ttl`，还要防止自动清理早于传输结束。未封存前需要取消时使用 `BACKUP ABORT`，适用于 pending、snapshotting、incrementing，转为 failed；先检查错误并确认残留文件处理，再重试。参见 [CLEANUP](https://redis.io/docs/latest/commands/backup-cleanup/)与 [ABORT](https://redis.io/docs/latest/commands/backup-abort/)。所有状态与路径返回均须读取真实响应；已对照 [8.10.0 aof.c 的备份状态机](https://github.com/redis/redis/blob/8.10.0/src/aof.c)，本文没有运行这些操作。

**隔离恢复。** Redis Open Source 8.10.0 的启动配置可指定此次备份 Manifest，以下为配置片段，不是 Redis 命令或 Shell 命令；路径是假定文件已完整复制到该位置：

```text
preload-file aof:/tmp/demo-restore/appendonly.aof.manifest
```

`preload-file` 格式为 `aof:路径` 或 `rdb:路径`；使用 Manifest 时还需其引用的 BASE/INCR。设置后仅加载指定目标，跳过正常 appenddirname 与 dump.rdb 加载；目标丢失或无法加载会中止启动，加载结束后继续按配置的持久化模式运行。因此它与“把文件放到普通 AOF 目录”或“指定一份 dump.rdb”不同，恢复后还应明确后续启动的数据来源。此语法见 [8.10.0 redis.conf](https://github.com/redis/redis/blob/8.10.0/redis.conf)与 [官方恢复说明](https://redis.io/docs/latest/operate/oss_and_stack/management/persistence/#restoring-a-backup)，不能套用到旧版本。

还应确认启动实际加载哪一组文件：RDB 与 AOF 同时启用时，正常启动优先使用 AOF，不能因目录里有 dump.rdb 就把它当成恢复来源。AOF 损坏也不代表自动回退旧 RDB；单文件 AOF、多部分 AOF 与故障分支见 [第 19 章](/articles/redis-rdb-aof.html)。

恢复演练应在不接收真实写入的隔离环境中进行。除确认能够启动外，还应抽查类型、TTL（Time To Live，存活时间）、关键关系与业务不变量，并记录恢复点和总耗时。恢复时已到期的数据可能不会保留，不能简单要求 TTL 与备份时相同。如果备份与源盘处于同一故障域，备份的保护价值就会降低。

| 指标                                         | 关注点                 | 验收方式                                                                   |
| -------------------------------------------- | ---------------------- | -------------------------------------------------------------------------- |
| RPO（Recovery Point Objective，恢复点目标）  | 允许丢失多少时段的数据 | 将有效恢复边界与故障时刻比较，核对业务提交记录                             |
| RTO（Recovery Time Objective，恢复时间目标） | 最长允许多久恢复可用   | 从约定的故障或中断起点到应用恢复可用计时，包含发现、决策、取回、加载与校验 |

验收清单应覆盖文件及清单完整性、加密与密钥可取得性、异地存储、保留周期、独立失败告警、恢复权限、Redis 与模块版本兼容、TTL、业务数据一致性及恢复后的应用验证。备份文件存在或 Redis 启动成功，都不等于业务恢复成功。新能力的补丁与回退验证见 [第 32 章](/articles/redis-upgrade-validation.html)。

## 5. 把操作按影响分级

INFO、ROLE 等通常用于观察；修改配置、重写日志、断开连接、复制关系变更、故障转移和迁槽都可能影响业务。FLUSHDB/FLUSHALL、破坏性文件修复或覆盖恢复更不能作为排查中的“试一下”。

维护前应有明确对象、授权、恢复点、窗口和验收标准。本文是笔记整理，不是对任何实例的操作授权。本次没有安装插件、执行数据命令、修改服务或连接真实 Redis。
