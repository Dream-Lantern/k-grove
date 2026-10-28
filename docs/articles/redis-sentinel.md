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

![Sentinel 与业务连接的关系](/assets/notes/redis/redis-study-sentinel.svg)

## 1. 查询主节点地址后连接数据节点 {#_1-业务流量不经过-sentinel-转发}

客户端先向 Sentinel 查询主节点名称对应的地址，再连接实际的 Redis 数据节点。切换发生后，客户端仍需发现新地址，处理旧连接和未知结果。如果只配置了固定的主节点 IP，即使部署了 Sentinel，也不会自动获得正确的故障处理能力。

一组 Sentinel 可以监控多个命名复制组；每个组在正常视图下有一个当前主节点和若干副本。组之间数据并不会自动分片或复制。

## 2. SDOWN、ODOWN 与选举是不同判断

SDOWN 是某个 Sentinel 根据连续不可接受的探测结果作出的主观下线判断。ODOWN 是关于主节点的客观下线判断，需要达到该组配置的 quorum 意见门槛。实际故障转移的领导者授权既要满足已知 Sentinel 的多数，也要达到配置 quorum；quorum 高于普通多数时，拿到普通多数仍不够。

![两类门槛不能合并](/assets/notes/redis/redis-study-sentinel-votes.svg)

例如三个 Sentinel、quorum=2：两个认为主节点下线，满足相关 ODOWN 条件；执行转移还要满足多数授权。若 quorum=1，单个 Sentinel 可以达到下线意见门槛，但它孤立时仍不能单方面完成正常故障转移。

新增纸面表，假设相关组的已知 Sentinel 数 N=5、视图一致：

| 配置 quorum | 普通多数 | 至少需要的领导者授权票数 |
| ----------- | -------- | ------------------------ |
| 2           | 3        | 3                        |
| 3           | 3        | 3                        |
| 4           | 3        | 4                        |

票数门槛可记为 `max(floor(N/2)+1, quorum)`，但它不是全部切换条件。还要考虑当前轮次、网络视图和副本资格；表中总数不代表实际部署已被验证。[Sentinel quorum 与授权](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/#quorum)

quorum 不会被自动“修正成多数”。它过高可能导致无法达到客观下线门槛；过低也不取消授权约束。[Redis 7.2.0 Sentinel 配置注释](https://raw.githubusercontent.com/redis/redis/7.2.0/sentinel.conf)

## 3. 按副本资格、优先级与进度选择候选 {#_3-提升候选不是只看谁的数字最大}

候选副本要满足可达性、与主节点失联时间等要求。优先级、复制进度及稳定的比较规则共同影响选择。`replica-priority` 的数值越小通常越优先，0 表示不参与提升；不能把它写成“越大越优先”。精确筛选顺序与时间条件应按对应版本核对，不适合背一个跨版本常量。[Sentinel 机制](https://redis.io/docs/latest/operate/oss_and_stack/management/sentinel/)

转移大致包括确认下线、取得授权、选择并提升副本、让其他副本跟随新主、传播新地址。每一步都可能受到网络、权限和节点状态影响，因此不能把探测阈值直接当成总恢复时间。

## 4. 在独立故障域部署并管理通信身份 {#_4-三个进程不等于三个故障域}

常见方案使用三个独立故障域的 Sentinel，以便损失一处后仍可能形成多数。如果三个进程都在同一主机，断电仍会同时失效。

认证需要覆盖多个通信方向：业务连接数据节点、Sentinel 监控数据节点、Sentinel 之间通信，以及客户端查询 Sentinel。权限应按具体版本和操作需求配置，不应直接照搬开放监听并关闭保护的沙箱设置。

Sentinel 会更新自己的动态状态文件。文件不可写、节点身份重复、容器宣布了客户端不可达地址，都可能让“进程在运行”与“系统可用”分离。

## 5. 先观察节点视图与仲裁条件 {#_5-如何验证-而不是立刻强制切换}

在对应 Sentinel 端点，可以按权限使用这些观察命令：

```redis
SENTINEL MASTERS
SENTINEL REPLICAS demo-primary
SENTINEL SENTINELS demo-primary
SENTINEL GET-MASTER-ADDR-BY-NAME demo-primary
SENTINEL CKQUORUM demo-primary
```

`demo-primary` 是教学组名，不代表现有部署。先确认各节点视图、互相发现和仲裁条件，再审查客户端重连行为。FAILOVER、RESET 等会改变状态，不能作为默认诊断步骤。

## 6. 自动切换不保证零数据损失

Sentinel 依赖异步复制。旧主刚确认的写入可能尚未到达最终提升的副本；网络分区中，旧主还可能在一段时间内被部分客户端访问。限制写入的配置可以降低某些风险，却不是严格一致性的替代品。

验收不能只看新主是否出现，还应检查业务是否完成重连、是否发生重复写入、关键状态是否丢失，以及旧主回归后是否已正确重新配置。本次仅整理方案，未向任何 Sentinel 发出命令或进行故障演练。
