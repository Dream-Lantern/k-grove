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

```redis
INFO server
INFO clients
INFO stats
INFO memory
INFO persistence
INFO replication
INFO commandstats
```

这些是观察示例，实际权限和产品可能限制字段。缺失字段应记录为不可用，而不是自动填成零。[INFO 字段参考](https://redis.io/docs/latest/commands/info/)

## 2. 用症状选择证据

| 症状       | Redis 侧线索                          | 还需核对                    |
| ---------- | ------------------------------------- | --------------------------- |
| 连接失败   | 连接数、拒绝连接计数、错误类型        | DNS、网络、TLS、ACL、连接池 |
| 延迟升高   | Slowlog、命令统计、持久化状态         | 应用排队、网络、CPU、磁盘   |
| 内存异常   | 数据、缓冲、allocator、淘汰与过期计数 | RSS、容器限制、COW、交换    |
| 副本读旧值 | 链路、同步状态、偏移变化              | 请求路由、时间窗、业务版本  |

表中的指标只是线索。`evicted_keys` 和 `expired_keys` 分别是淘汰与过期的累计数，需要观察其变化率，并结合业务结果判断，不能仅因数值非零就认定刚刚发生了故障。

## 3. 根据连接类别解释缓冲增长 {#_3-输入与输出缓冲为什么增长}

输入侧可能因大请求、Pipeline 积压或处理速度不足出现压力；输出侧则可能因大回复、慢读客户端、订阅者消费慢或复制链路落后而增长。

CLIENT LIST 中的字段能帮助定位特定连接，但字段和含义依版本演进。应按连接类别分析，不能用一条连接的缓冲数代表整个实例。客户端输出缓冲限制也可能区分类别、硬阈值和持续时间软阈值，不存在所有部署统一的“固定 1 GB”结论。[CLIENT LIST](https://redis.io/docs/latest/commands/client-list/)

直接断开连接可能丢失未确认结果或订阅消息。处置前先确认客户端身份、业务影响与恢复方式，不把 CLIENT KILL 当成只读排障命令。

## 4. 常见错误先按层分类

NOAUTH/WRONGPASS 指向认证；NOPERM 指向权限；WRONGTYPE 指向键模型或命令使用；MOVED/ASK 指向 Cluster 路由；READONLY 可能说明写到了只读副本；OOM 需要结合策略和内存判断。具体文字与产品版本可能不同。

`nil` 或空结果不等同异常，它可能是键不存在、范围没有元素或事务冲突等正常协议结果。客户端必须结合命令语义解释，而不是统一返回“Redis 连接失败”。

例如 [MGET](/articles/redis-strings.html) 对非 String 键也可能给出逐键 nil；[HTTL](/articles/redis-hashes.html) 则有字段期限与缺失状态码。NOPERM 还应区分命令、键和频道授权，见 [ACL 范围](/articles/redis-security-maintenance.html)，不能只看到一个错误就扩大账号权限。

## 5. 形成可复核的诊断记录

一份有效的诊断记录可以包含症状与时间、业务影响、只读采样、候选原因、反证、拟采取的最小变更，以及回退和验收方式。先定位问题再调整参数，有助于避免将短暂恢复误认为根因已经解决。

监控数据、客户端地址和命令参数可能敏感，公开材料使用合成示例。真实部署信息保留在私有来源，公开材料不据此补写架构。
