---
id: distributed-chain-replication-craq
title: 第十八章 Chain Replication 与 CRAQ 读扩展
description: "链复制把副本排成有序链，写入由 Head 向 Tail 传播。CRAQ 在此基础上维护版本的 clean/dirty 状态，使部分读取可以由链上的其他节点处理。"
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
order: 18
---

# 第十八章 Chain Replication 与 CRAQ 读扩展

> 阅读标签：Chain Replication / CRAQ2009论文。

链复制把副本排成有序链，写入由 Head 向 Tail 传播。CRAQ 在此基础上维护版本的 clean/dirty 状态，使部分读取可以由链上的其他节点处理。理解它的过程，可以先跟踪一笔写入如何提交，再看读请求怎样选择已提交版本。

## 1. 基础 Chain Replication

Head 接收写入并向后继传递，逐步到达 Tail；基础协议将到达 Tail 的写视为提交，读从 Tail 得到提交状态。Head 与 Tail 分担部分工作，但链长、网络、写入比例和数据大小仍影响成本。

原始链复制可由 Tail 回复客户端；CRAQ 论文实现为了复用客户端 TCP 连接，由确认沿链返回后让 Head 回复。两者要按抽象与实现分别描述，不能把“只能由 Tail 直接回复”当作不变接口。[CRAQ 论文 §2.2](https://www.cs.princeton.edu/courses/archive/fall22/cos418/papers/craq.pdf)

## 2. 用 clean/dirty 状态选择读取路径 {#_2-craq-怎样安全地分散读}

[![CRAQ：写传播与读选择是两条不同路径](/assets/notes/distributed-systems/dist-craq.png)](/assets/notes/distributed-systems/dist-craq.png)

节点可保留对象的多个版本。新写到达非 Tail 节点时先标 dirty；到达 Tail 后提交并产生反向确认，节点收到确认将对应版本标 clean。

若对象处于适用的 clean 状态，可以在本地直接返回；若存在 dirty 新版本，则向 Tail 查询当前已提交版本号，再返回相应版本。dirty 不是损坏，而是本节点尚不能仅凭本地状态确定提交边界。

## 3. 用一次在途写入推演

教学例子：对象原为 clean v5，新写 v6 到达 Head，但尚未到 Tail。此时 Head 不能把 v6 当作已经完成的最新状态直接返回；它查询 Tail，Tail 仍可能确认 v5。随后 v6 到达并提交，新的读取按合法顺序观察 v6。

节点保留必要的旧版本，是为了在获知已提交版本后返回相应内容。如果立即删除所有旧版本，只留下未经确认的新对象，即使查询到版本号，也无法返回所需数据。

## 4. 链成员变化与在途更新恢复 {#_4-链成员变化不只是删除一个数组元素}

Head、Tail 或中间节点故障时，链的前后关系与在途更新都需重建。中间节点可能接收了尚未转发的请求；新链需要依据确认状态补传，不能假设所有幸存节点天然具有相同进度。

Configuration Manager 提供配置权威；但一个权威存在，不代表旧节点和旧客户端已经收到新配置。配置代际、旧资格隔离、重试和网络分区必须共同处理。它自身也需要一致、可恢复的实现，不能说“因为只有一个角色决策，所以绝不会脑裂”。

## 5. 结合负载比较复制与读取成本 {#_5-和-raft-比较时看负载-而不是判定谁永远更快}

链把逐节点传输成本分散出去，CRAQ 在读多、clean 比例高等条件下增加本地读机会；Raft 则以领导者日志复制和多数规则组织提交。两者的故障恢复、读路径与复制确认集合不同。

增加副本会同时增加存储与传播成本；写入频繁时 dirty 查询也会增加 Tail 压力。因此不写“副本数翻倍读吞吐必定翻倍”，更不把论文特定实验结果伪装成个人环境收益。

学习和验收时，除了无故障读写，还应覆盖新旧配置交接、dirty 期间的读取，以及失败请求重试。

[返回本册目录](/collections/distributed-systems/)
