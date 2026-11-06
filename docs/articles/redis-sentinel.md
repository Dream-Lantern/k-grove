---
id: redis-sentinel
title: 第二十二章 Sentinel、仲裁与故障转移
description: "Sentinel 为非 Cluster 复制组提供监控、故障转移与主节点发现。它先观察节点状态并形成下线判断，再取得转移授权、选择副本和传播新主地址。"
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
order: 22
---

# 第二十二章 Sentinel、仲裁与故障转移

[返回本册目录](/collections/redis/)

Sentinel 为非 Cluster 复制组提供监控、故障转移与主节点发现。它先观察节点状态并形成下线判断，再取得转移授权、选择副本和传播新主地址。业务数据仍由 Redis 数据节点处理，客户端根据发现结果建立连接。

本章以 Redis Open Source 7.2.0 的自动故障转移为核对基线；复制的数据安全边界见[第二十一章](/articles/redis-replication-psync.html)。需要分片时，应另看[第二十三章 Cluster](/articles/redis-cluster-routing.html)，不要把两套故障处理机制混用。

![Sentinel 与业务连接的关系](/assets/notes/redis/redis-study-sentinel.svg)

## 1. 查询主节点地址后连接数据节点 {#_1-业务流量不经过-sentinel-转发}

客户端先向 Sentinel 查询主节点名称对应的地址，再连接实际的 Redis 数据节点。切换发生后，客户端仍需发现新地址，处理旧连接和未知结果。如果只配置了固定的主节点网络地址，即使部署了 Sentinel，也不会自动获得正确的故障处理能力。

一组 Sentinel 可以监控多个命名复制组；每个组在正常视图下有一个当前主节点和若干副本。组之间数据并不会自动分片或复制。

下面是客户端发现流程，箭头表示查询或连接关系，不是业务请求经 Sentinel 转发：

```text
应用 → 多个 Sentinel 地址中可访问的一个
     → SENTINEL GET-MASTER-ADDR-BY-NAME demo-primary
     ← 当前主节点地址
应用 → Redis 数据节点：认证、确认角色、建立业务连接
发生断线或角色变化 → 重新查询 Sentinel → 更新连接池
```

Sentinel 自身也可能不可达，因此客户端要配置多个入口，并限制单次连接等待时间。切换后，连接池可能仍持有旧主连接，需要失效并重建；连接成功后还应确认数据节点角色。未收到写请求回复，只能说明结果未知，重试前要考虑幂等性，即同一业务操作重复执行不会重复扣款等。[Sentinel 客户端规范](https://redis.io/docs/latest/develop/reference/sentinel-clients/)

## 2. SDOWN、ODOWN 与选举是不同判断

SDOWN（Subjectively Down，主观下线）是单个 Sentinel 的本地故障判断。ODOWN（Objectively Down，客观下线）针对主节点，需要该 Sentinel 自己认为主节点下线，并收集到足够故障报告，达到 quorum（法定数量，即故障意见门槛）。后续还要选出 Leader（领导者，即执行此次故障转移的 Sentinel）；同一轮的授权票数必须同时达到已知 Sentinel 的多数和配置 quorum。

![两类门槛不能合并](/assets/notes/redis/redis-study-sentinel-votes.svg)

例如三个 Sentinel、quorum=2：两个认为主节点下线，满足相关 ODOWN 条件；执行转移还要满足多数授权。若 quorum=1，单个 Sentinel 可以达到下线意见门槛，但它孤立时仍不能单方面完成正常故障转移。

下面是逻辑时序示意，不是严格源码调用顺序。假设 A、B、C 监控同一主节点，quorum=2；A、B 探测失败而 C 仍能访问主节点：

```text
Sentinel A          Sentinel B          Sentinel C          Redis 主节点
    | 连续探测失败      | 连续探测失败      | 探测成功             |
    | SDOWN            | SDOWN            |                     |
    |<------ 交换故障报告、各自更新本地视图 ------>|                |
    | A 收到 B 的下线意见，达到 ODOWN 门槛                       |
    |<------ 在同一选举轮次请求授权并统计票数 ---->|                |
    | 假设 A 获得足够授权，成为 Leader                          |
    | → 过滤并选择副本 → 提升新主 → 重配置其他副本                |
    | → 传播新主地址 → 客户端重新发现并连接新主                   |
```

C 没有报告主节点下线，不代表 A、B 永远不能形成 ODOWN；关键是意见数量和授权条件。Sentinel 不代理任何业务请求。

| 阶段       | 主要问题                          | 结果                                |
| ---------- | --------------------------------- | ----------------------------------- |
| 探测       | 是否持续收到可接受响应            | 更新可达性记录                      |
| SDOWN      | 当前 Sentinel 是否认为实例异常    | 本地判断                            |
| ODOWN      | 对主节点的下线意见是否达到 quorum | 客观下线判断                        |
| 授权       | 是否获得同轮足够选票              | 获得执行故障转移的许可              |
| 选举       | 哪个 Sentinel 获胜                | 确定 Leader，与授权属于同一选举过程 |
| 提升       | 哪个合格副本成为新主              | 角色切换                            |
| 重配置     | 其他副本应跟随谁                  | 更新复制关系                        |
| 客户端发现 | 如何找到新主                      | 重建业务连接                        |

下面的教学表假设已知 Sentinel 数 N=5，包含自己，且各方视图一致：

| 配置 quorum | 普通多数 | 至少需要的领导者授权票数 |
| ----------- | -------- | ------------------------ |
| 2           | 3        | 3                        |
| 3           | 3        | 3                        |
| 4           | 3        | 4                        |
| 5           | 3        | 5                        |

票数门槛可记为 `max(floor(N/2)+1, quorum)`，但它不是全部切换条件。还要考虑当前轮次、网络视图和副本资格；表中总数不代表实际部署已被验证。[Sentinel quorum 与授权](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/#quorum)

quorum 不会被自动“修正成多数”。它过高可能导致无法达到客观下线门槛；过低也不取消授权约束。[Redis 7.2.0 Sentinel 配置注释](https://raw.githubusercontent.com/redis/redis/7.2.0/sentinel.conf)

N 不是此刻在线的进程数，而是该 Sentinel 当前已知的本组 Sentinel 总数。可用数量小于 quorum 时无法达到意见门槛；即便达到 quorum，也可能不足多数授权。投票数量、网络可达性和故障域独立性需要分别检查。

| 配置项                    | Redis Open Source 7.2.0 中的作用                                         |
| ------------------------- | ------------------------------------------------------------------------ |
| `down-after-milliseconds` | 连续没有可接受的 PING 响应超过该毫秒阈值后，判断主观下线；不是总恢复时间 |
| `failover-timeout`        | 用于故障转移的多个超时、重试和副本重配置判断，不是统一的停机时限         |
| `parallel-syncs`          | 故障转移中允许同时重配置、同步到新主的副本数量                           |

这些配置不能简单相加推算固定恢复时间。授权、选举、提升、其他副本同步与客户端重连都会受实际状态影响。[7.2.0 配置中的时间参数](https://raw.githubusercontent.com/redis/redis/7.2.0/sentinel.conf)

## 3. 按副本资格、优先级与进度选择候选 {#_3-提升候选不是只看谁的数字最大}

先过滤，再排序，才能避免选中优先级高但数据过旧的副本。按 Redis Open Source 7.2.0 的 `sentinelSelectSlave`，下线、Sentinel 到副本连接已断、最近可接受响应或 INFO 信息过旧、优先级为 0 的副本会被排除。还要检查副本报告的主从链路断开时长：

```text
允许的最大断开时长 = 10 × 主节点 down-after-milliseconds
                   + 当前 Sentinel 观察到的主节点 SDOWN 已持续时长

副本报告的 master_link_down_time > 上述阈值 → 排除
```

只有主节点处于 SDOWN 时才加入其已持续时长，否则该项为 0。这里是加法，不是取最大值；恰好等于阈值不会被这一条过滤，但仍须满足其他资格。时间比较使用统一单位，也不是“副本一失联就不能提升”。

合格候选按以下顺序比较：`replica-priority` 越小越优先；相同则 Replication Offset（复制偏移量，即已处理复制流的位置）越大越优先；仍相同则选择 Run ID（进程运行标识）按不区分大小写的字典序较小者。Run ID 不是业务优先级，也不是复制历史 ID。[7.2.0：sentinelSelectSlave 与 compareSlavesForPromotion](https://github.com/redis/redis/blob/7.2.0/src/sentinel.c)

假设以下副本都通过其他资格检查，数字仅用于教学：

| 副本 | Priority | Replication Offset | 是否参与提升 |
| ---- | -------: | -----------------: | ------------ |
| A    |      100 |              10000 | 是           |
| B    |       50 |               9500 | 是           |
| C    |       50 |              10500 | 是           |
| D    |        0 |              12000 | 否           |

D 被排除；B、C 的优先级高于 A；C 的偏移量高于 B，因此选 C。本例不需要比较 Run ID，不能据此认为每次都只选偏移量最大的副本。

转移大致包括确认下线、取得授权、选择并提升副本、让其他副本跟随新主、传播新地址。每一步都可能受到网络、权限和节点状态影响，因此不能把探测阈值直接当成总恢复时间。

## 4. 在独立故障域部署并管理通信身份 {#_4-三个进程不等于三个故障域}

常见方案使用三个独立故障域的 Sentinel，以便损失一处后仍可能形成多数。如果三个进程都在同一主机，断电仍会同时失效。

认证需要按通信方向分别配置。下面以 Redis Open Source 7.2.0 为基线；ACL（Access Control List，访问控制列表）用于划分身份和命令权限：

| 通信方向                        | 身份配置关系                                                                               |
| ------------------------------- | ------------------------------------------------------------------------------------------ |
| Sentinel → 数据主节点及副本     | 该监控组的 `sentinel auth-user` / `sentinel auth-pass`；要能监控并重配置可能互换角色的节点 |
| Redis 副本 → 主节点             | 数据节点的 `masteruser` / `masterauth`，切换后也要适配新主                                 |
| Sentinel → 其他 Sentinel        | `sentinel sentinel-user` / `sentinel sentinel-pass` 对应接收端的认证配置                   |
| 业务客户端 → Sentinel、数据节点 | 分别提供两类连接所需的凭据和权限                                                           |

Redis Open Source 6.2.0 起 Sentinel 支持 ACL。不能假设上述通信共用一套密码；使用旧式 `requirepass` 时还有 Sentinel 之间密码配套要求，需按部署方式核对。[7.2.0 Sentinel 认证配置](https://raw.githubusercontent.com/redis/redis/7.2.0/sentinel.conf)

Sentinel 会更新自己的动态状态文件。文件不可写、节点身份重复、容器宣布了客户端不可达地址，都可能让“进程在运行”与“系统可用”分离。

## 5. 先观察节点视图与仲裁条件 {#_5-如何验证-而不是立刻强制切换}

在对应 Sentinel 端点，可以按权限使用这些只读观察命令。代码块是 Redis 命令，不是 Shell 命令或客户端函数；本章所有命令均未实际运行：

```redis
SENTINEL MASTERS
SENTINEL REPLICAS demo-primary
SENTINEL SENTINELS demo-primary
SENTINEL GET-MASTER-ADDR-BY-NAME demo-primary
SENTINEL CKQUORUM demo-primary
```

`demo-primary` 是教学组名，不代表现有部署。先确认各节点视图、互相发现和仲裁条件，再审查客户端重连行为。FAILOVER、RESET 等会改变状态，不能作为默认诊断步骤。

| 命令                                   | 用途                                                             |
| -------------------------------------- | ---------------------------------------------------------------- |
| `MASTERS`                              | 查看监控主节点及其状态                                           |
| `REPLICAS demo-primary`                | 查看该组已发现的副本                                             |
| `SENTINELS demo-primary`               | 查看该组已发现的其他 Sentinel，不含自己                          |
| `GET-MASTER-ADDR-BY-NAME demo-primary` | 查询当前视图中的主节点地址                                       |
| `CKQUORUM demo-primary`                | 检查当前已知视图下，可用 Sentinel 是否足以满足 quorum 和多数授权 |

CKQUORUM 检查的是可行性，不代表已经选出 Leader、存在合格副本或故障转移已经完成。[Sentinel 官方接口与机制](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/)

## 6. 自动切换不保证零数据损失

Sentinel 依赖异步复制。旧主刚确认的写入可能尚未到达最终提升的副本；网络分区中，旧主还可能在一段时间内被部分客户端访问。限制写入的配置可以降低某些风险，却不是严格一致性的替代品。

验收不能只看新主是否出现，还应检查业务是否完成重连、是否发生重复写入、关键状态是否丢失，以及旧主回归后是否已正确重新配置。本次仅整理方案，未向任何 Sentinel 发出命令或进行故障演练。
