---
id: distributed-cqrs-cache-ids
title: 第二十五章 CQRS、缓存、会话、全局 ID 与任务
description: 原笔记列出了多种工程方案。本章分别说明它们解决的问题，不因都带有“分布式”就将其视为同一种一致性技术。这些方案可以组合使用，但也会在新的边界引入需要处理的失败状态。
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - 分布式系统
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: distributed-systems
series: distributed-learning
order: 25
---

# 第二十五章 CQRS、缓存、会话、全局 ID 与任务

> 阅读标签：通用协议/应用模型，具体前提见本章。

原笔记列出了多种工程方案。本章分别说明它们解决的问题，不因都带有“分布式”就将其视为同一种一致性技术。这些方案可以组合使用，但也会在新的边界引入需要处理的失败状态。

## 1. CQRS 是职责与模型分离

Command Query Responsibility Segregation 将改变状态的命令与读取状态的查询在职责、模型上分开。可以共用数据库，也可以采用独立的查询存储；不是必须读写跑在不同机器，更不等于普通主从复制。

[![CQRS：事件驱动同步是一种可选实现](/assets/notes/distributed-systems/dist-cqrs.svg)](/assets/notes/distributed-systems/dist-cqrs.svg)

若查询模型异步构建，订单已提交而列表尚未出现，就需要写后读与进度策略。关键库存校验不能随意依赖有延迟的查询投影。[Microsoft CQRS 模式说明](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs)

## 2. 缓存是副本与失效协议问题

缓存通过复用结果减少昂贵查询，不只是用内存替换磁盘，也可以保存远程聚合或计算结果。Cache-Aside 中的数据库更新与缓存删除不属于同一个原子事务；较早查询的结果若迟到回填，也可能重新污染缓存。

应定义权威数据、版本、TTL、失效失败恢复和回源预算。Bloom Filter 只在正确加入与未破坏等条件下提供相应否定判断；业务漏写过滤器可能误拒真实对象，基础过滤器也不应通过随意清位删除成员。更细说明可联读 Redis 分册，本章不重复所有命令。

## 3. 负载均衡与会话

轮询、权重、最少连接和延迟反馈等策略优化不同指标。连接少不一定工作量小，心跳成功也不等于下游依赖健康。排除故障节点还要处理在途请求、慢请求与新实例预热。

会话粘滞让同一用户倾向同实例，但实例故障时仍需恢复状态；共享会话存储简化多实例访问，却引入存储可用性、TTL 和凭据保护问题。IP 哈希遇到 NAT、代理或地址变化，也不能等同稳定用户身份。

## 4. 全局 ID 需要哪些性质？

唯一、时间有序、严格单调、不可猜测是不同需求。数据库序列或服务端分配需要可靠的状态与容错；Snowflake 类方案要处理工作节点编号冲突、时钟回退和序列容量，不能只背固定位数格式。

进一步阅读：RFC 9562 定义的 UUIDv7 使用毫秒时间字段，适合作为时间排序相关方案的一部分，但不是跨节点真实先后的证明；唯一性仍依赖正确生成与状态处理。ID 更不应直接当作授权秘密。[RFC 9562 §5.7、§6](https://datatracker.ietf.org/doc/html/rfc9562)

## 5. 定时任务也需要业务执行身份

多个实例都观察到“该执行了”，并不意味着每个实例都应产生一次外部效果。调度负责生成任务实例，后续还需处理工作领取、租约、重试与业务完成确认。仅增加一把带 TTL 的锁，无法阻止旧执行者恢复后重复发送账单。

设计清单：任务键可包含计划版本与时间窗口；执行尝试有独立身份；结果按任务实例幂等提交；长任务续约失败应停止使用旧资格；需要重跑、补跑和人工恢复时能查询明确状态。这是教学框架，不冒充某调度产品的完整语义。

## 6. 模式不是可以直接拼接的积木

同时采用 CQRS、缓存、会话和任务时，需要明确哪些状态是权威来源、哪些可以重建，以及允许多大延迟。高可用缓存、消息队列和锁的组合，并不自动构成正确的订单系统；恢复与验收仍须依据业务不变量。

## 联读

本章作为工程导航：CQRS联读[Outbox与投影来源](/articles/distributed-saga-tcc-outbox.html)；ID联读[时钟与因果](/articles/distributed-clocks-causality.html)；任务联读[租约与fencing](/articles/distributed-locks-leases-fencing.html)；缓存深入见[Redis分册](/collections/distributed-systems/)。负载均衡/会话保留为独立速查条目，不塞入共识协议。

[返回本册目录](/collections/distributed-systems/)
