---
id: distributed-paxos
title: 第八章 Paxos 的提案、承诺与选定值
description: 共识并非让所有节点“尽量意见相同”，而是在既定故障模型下，确保只能选定合法值，且不能选定相互冲突的结果。先理解单个日志槽的 Basic Paxos，再讨论连续日志，有助于区分同一槽中的多轮提案与多个业务操作。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 8
---

# 第八章 Paxos 的提案、承诺与选定值

> 阅读标签：Basic Paxos / 2001论文。

共识并非让所有节点“尽量意见相同”，而是在既定故障模型下，确保只能选定合法值，且不能选定相互冲突的结果。先理解单个日志槽的 Basic Paxos，再讨论连续日志，有助于区分同一槽中的多轮提案与多个业务操作。

## 1. 三种角色可以在同一进程中

Proposer 发起提案，Acceptor 保存承诺与接受状态，Learner 学习选定结果。它们是逻辑角色，不要求三种独立服务器。这里采用非拜占庭、消息可延迟或丢失、必要状态可持久化的模型。

提案包含唯一、有序的编号 n 和值 v。原笔记“每个 Acceptor 只能批准一个提案”不成立：它可以接受多个编号的提案，但必须遵守规则，让已经选定的值不会被后续不同值替换。[Paxos Made Simple §2](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

## 2. 第一阶段为什么要询问历史？

Proposer 发送 Prepare(n)。接受该编号的 Acceptor 承诺不再接受更小编号的新提案，并报告自己已接受的最高编号提案（如果存在）。Proposer 收到多数回复后，不能忽略这些历史，任意提出想要的新值。

![Prepare、值继承、Accept 与选定](/assets/notes/distributed-systems/dist-paxos.svg)

若回复中包含已接受的值，阶段二沿用最高接受编号对应的值；若没有，才可选自己的值。多数交集让后续提案能够接触到必要历史，值继承规则把这个交集转化为安全约束。

## 3. 用三 Acceptor 推演

教学例子：A、B 接受了提案 (5,蓝色)，已达到三节点中的多数。新的 Proposer 以编号 8 询问 B、C；B 报告已接受 (5,蓝色)，C 没有接受值。新提案必须继承蓝色，不能因为编号更大就改成红色。

注意“被某个节点接受”和“被多数选定”不同。即使新 Proposer 不能立即证明先前是否已经达到多数，继承规则仍会保护潜在的既定选择。恢复协议不能只记录“我猜没有成功”。

## 4. 持久化与活性分别影响什么？

Acceptor 若在崩溃后丢失承诺或接受状态，就可能违反前后约束。这些必须保存的状态并非普通缓存，不能以优化性能为由随意省略。

多个 Proposer 不断以更高编号互相抢占，可能长期无法完成阶段二。安全不等于必然立即选出值；实际系统通常需要稳定提议者等机制改善进展。不能只数消息轮次就宣称 Paxos 永远比 Raft 慢一倍。

## 5. 从单值走向日志

一系列状态机操作需要多个槽位，每个槽选择相应命令，并处理顺序、空洞、客户端重复、快照和成员变更。Multi-Paxos 在稳定领导者等条件下复用阶段一的工作，但不是把 Basic Paxos 的所有环节永久删除。

本章用于理解协议，不提供可直接部署的实现。练习时，可记录每个 Acceptor 的 promise 与 accepted 状态，推演消息乱序、重启和更高编号接管。需要验证的不变量是同一槽不能选出两个不同值，而不是“每个节点只收到过一条提案”。

[返回本册目录](/collections/distributed-systems/)
