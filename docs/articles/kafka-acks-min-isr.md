---
id: kafka-acks-min-isr
title: 第 5 章：acks、minISR 与可靠性边界
description: 这些值有各自的协议含义，不是可随意填写 2、3、4 的计数器。可靠性还取决于副本的运行状态：若允许 ISR 只有 Leader，all 也不代表写入了三份副本。
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
order: 5
---

# 第 5 章：acks、minISR 与可靠性边界

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：解释 RF=3、minISR=2、acks=all 能做到什么，以及超时、断电和副本故障下仍有什么限制。

## 1. acks 不是任意的“收到 N 个回复”

`acks=0` 不等待 Broker 的生产确认，应用可能无法从该发送结果判断 Broker 是否接受数据。`acks=1` 等待 Leader 本地追加的相应确认，不等待同样的 Follower 复制条件。`acks=all`，也称 `-1`，要求满足当前 ISR 的相应复制确认条件。

这些值有各自的协议含义，不是可随意填写 2、3、4 的计数器。可靠性还取决于副本的运行状态：若允许 ISR 只有 Leader，`all` 也不代表写入了三份副本。

## 2. minISR 提供可靠写入门槛

`min.insync.replicas` 配合 `acks=all` 规定所需的最小同步副本条件。它不是指定“只需这些副本回复即可，不用管其他仍在 ISR 的副本”，也不会强制落后副本瞬间追上。

[![RF=3、minISR=2、acks=all 的含义](/assets/notes/kafka/kf-acks.png)](/assets/notes/kafka/kf-acks.png)

教学例子采用 RF=3、minISR=2。当 ISR 为 A、B、C 时，按当前同步集合确认；C 离开后，A、B 仍可能满足门槛。若只剩 A，则应拒绝不能满足门槛的可靠写入，而不是静默降级。操作发生前后 ISR 变化还可能影响返回错误，不能据某次快照推断完整执行历史。

## 3. 拒绝写入与丢失数据不是同一个结论

遇到副本不足相关错误时，应先判断应用需要重试、退避，还是停止接收上游请求，不能只修改 minISR 来消除报错。降低门槛可能恢复写入能力，但也会改变已接受数据的容错条件。

没有收到成功确认，也不一定表示记录没有追加。请求可能已经执行了一部分，只是确认尚未返回；此时重试可能导致重复。可靠性设计需要同时考虑丢失、重复、未知结果和业务恢复，不能用“失败就无限重发”代替状态管理。

## 4. 复制确认不是同步落盘到所有物理介质

Kafka 利用操作系统页缓存，复制到其他 Broker 和在每份磁盘上完成同步 `fsync` 是不同保证。`acks=all` 不等于每份副本已在响应前同步刷新到持久介质。

因此，需要说明故障假设：独立 Broker 故障、同时断电、存储控制器行为、机架或机房故障，各自带来的风险不同。更频繁地刷盘会改变性能与持久化行为，但无法排除任意硬件故障。不能从教学公式推导出“永不丢失”。

## 5. 一套设置之外还需要什么

检查生产回调、幂等配置、副本跨故障域分布、禁止无意脏选举、监控与演练，以及消费侧提交和外部幂等。Topic 的重要覆盖项应与 Broker 默认值一起核对，不能只看一个服务端配置文件。

思考题：三副本已有两个掉线，为什么不能既坚持 minISR=2 的写入约束，又要求继续单副本成功写入？这不是参数技巧问题，而是已经接受了不同的容错与可用性选择。

## 参考

- [Java Producer：acks](https://kafka.apache.org/39/configuration/producer-configs/#acks)
- [Topic：min.insync.replicas 与 flush 配置](https://kafka.apache.org/39/configuration/topic-level-configs/)

## 联读

共同课程下半课：[先读RF/ISR与故障切换](/articles/kafka-replication-isr.html)；文件持久化背景见[OS文件与fsync](/articles/os-file-descriptors-persistence.html)。
