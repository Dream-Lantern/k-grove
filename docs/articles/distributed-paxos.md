---
id: distributed-paxos
title: 第八章 Paxos 的提案、承诺与选定值
description: "共识协议在既定故障模型下，为某个决定选定合法值，并保护已选定结果免受冲突提案覆盖。Basic Paxos 可以先按单个槽位理解：提议者收集承诺与历史，再发起接受请求。"
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
order: 8
---

# 第八章 Paxos 的提案、承诺与选定值

> 阅读标签：Basic Paxos / 2001论文。

共识协议在既定故障模型下，为某个决定选定合法值，并保护已选定结果免受冲突提案覆盖。Basic Paxos 可以先按单个槽位理解：提议者收集承诺与历史，再发起接受请求。掌握一槽多轮提案后，再将它扩展到连续日志。

## 1. 三种角色可以在同一进程中

提议者（Proposer）发起提案，接受者（Acceptor）保存承诺与接受状态，学习者（Learner）获知选定结果。它们是逻辑角色，不要求三种独立服务器。这里采用非拜占庭、消息可延迟或丢失、必要状态可持久化的模型。

提案包含唯一、有序的编号 n 和值 v。Acceptor 可以接受多个编号的提案，同时遵守承诺与值继承规则，保护已经选定的值不被后续不同值替换。[Paxos Made Simple §2](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

提案编号（Proposal Number）需要具有可比较的全序，并保证不同 Proposer 不会生成相同编号；同一实例内同一编号不能绑定两个不同值。教学上可给 Proposer 分配互不重叠的编号集合，或使用 `(counter, proposer_id)` 按字典序比较；组合编号不是 Paxos 强制的格式。重启后还要防止计数器回退造成编号复用，见 [原论文 §2.5](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)。

## 2. Prepare 阶段收集承诺与已接受值 {#_2-第一阶段为什么要询问历史}

Proposer 发送准备请求 `Prepare(n)`，不是让 Acceptor 接受某个业务值。对满足条件的编号，Acceptor 返回承诺（Promise）：不再接受编号小于 n 的新提案，并报告自己已接受的最高编号提案及其值（如果存在）。对已承诺更高编号等不满足条件的 Prepare，可以忽略或拒绝。Proposer 收到针对本轮 n 的多数 Promise 后，才能按历史选择阶段二的值。

独立的教学推演：该 Acceptor 尚未接受任何值，当前最高 Promise 为 5，且没有其他并发消息：

```text
收到 Prepare(8)
    → 持久化 Promise=8，回复 Promise(8, accepted=无)
收到 Accept(6, red)
    → 6 < 8，违反已作出的承诺，拒绝
收到 Accept(8, blue)
    → 若没有更高 Promise，且提案遵循协议，可接受
```

Promise 不等于接受值，Prepare 也不是 Accept。Acceptor 的准入检查要遵守此前承诺；Proposer 则负责按阶段一历史正确选择值，两边的职责不能互相代替。[原论文 §2.2](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

![Prepare、值继承、Accept 与选定](/assets/notes/distributed-systems/dist-paxos.svg)

若回复中包含已接受的值，阶段二沿用最高接受编号对应的值；若没有，才可选自己的值。多数交集让后续提案能够接触到必要历史，值继承规则把这个交集转化为安全约束。

这里的“没有”指本轮已收集的多数回复全部没有已接受提案，不是只看其中一个空回复。若回复分别报告 `(5, blue)` 与 `(7, red)`，就应继承编号 7 的 red；这个例子假定各提案历史本身合法，不意味着已经选定 blue 后还能合法选定 red。

阶段二发送接受请求 `Accept(n,v)`。Acceptor 只有在不违反更高编号承诺等协议条件时才接受，并在持久化接受状态后回复。Prepare 收到多数 Promise，不代表这个值已经选定。

## 3. 用三 Acceptor 推演

教学例子：A、B 接受了提案 `(5, blue)`，已达到三个 Acceptor 中的多数。新的 Proposer 发起 `Prepare(8)`，从 B、C 收到 Promise；B 报告已接受 `(5, blue)`，C 没有接受值。新提案必须继承蓝色 blue，不能因为编号更大就换成红色 red。

| 节点 | Promise | Accepted |
| --- | --- | --- |
| A | 5 | (5, blue) |
| B | 8 | (5, blue) |
| C | 8 | 无 |

这张状态表表示新一轮 Prepare 已完成、Accept 尚未开始的教学时刻。下一步应发送 `Accept(8, blue)`。原多数 `{A,B}` 与新多数 `{B,C}` 的交集为 `{B}`，因此新轮次能从 B 得到接受历史。若 B 报告了更高编号的已接受提案，就按最高编号规则继承；协议的安全性保证合法历史中的这些继承不会推翻已选定值。

注意“被某个节点接受”和“被多数选定”不同。即使新 Proposer 不能立即证明先前是否已经达到多数，继承规则仍会保护潜在的既定选择。恢复协议不能只记录“我猜没有成功”。

### Accepted、Chosen 与 Learned

| 概念 | 定义 |
| --- | --- |
| 已接受（Accepted） | 某个 Acceptor 已接受某编号及其值，这是单节点事实 |
| 已选定（Chosen） | 同一实例中，同一个提案 `(n,v)` 已被多数 Acceptor 接受，这是协议事实 |
| 已获知（Learned） | 某个 Learner 已有足够证据知道值被选定，这是该观察者的知识状态 |

教学消息丢失案例：A、B 已接受 `(5, blue)`，所以 blue 已 Chosen；通知 Learner 的消息却丢失，它仍未 Learned。后续没有及时收到结果，不会把已选定值变回未选定。

Learner 可以收集同一实例、同一提案编号的多数接受通知，或由指定学习者收集后再分发结果。如果恢复时只能查询当前接受记录，部分节点已不可达或记录已前进到更高提案，就未必能直接重建旧多数证据；可通过新一轮合法提案重新选定并获知受保护的值，而不是猜测先前失败。[原论文 §2.3](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

## 4. 用持久化保护历史，用提议者协调改善进展 {#_4-持久化与活性分别影响什么}

在允许崩溃重启的模型中，Acceptor 必须先把依赖的协议状态写入稳定存储（Stable Storage），再发送相应响应，主要包括已响应的最高 Prepare 编号，以及已接受的最高编号提案及其值。[原论文 §2.5](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

若已回复 Promise(8) 却在重启后忘记承诺，就可能再次接受编号 6；若忘记已接受的 blue，新 Proposer 可能收到错误的“无历史”回复。这会破坏后续继承依赖的事实。这些状态不是普通内存缓存；仅把响应发出去，再异步保存它们，留下了响应与持久化之间的崩溃窗口。

多个 Proposer 不断以更高编号互相抢占，可能长期无法完成阶段二。安全不等于必然立即选出值；实际系统通常需要稳定提议者等机制改善进展。不能只数消息轮次就宣称 Paxos 永远比 Raft 慢一倍。

例如 P 完成 Prepare(8)，Q 又完成 Prepare(9)，使 P 的 Accept(8, blue) 被拒绝；P 再提高到 10，又抢在 Q 的阶段二之前取得承诺，过程就可能反复。稳定的指定提议者（Distinguished Proposer）减少这种竞争，但活性仍需多数 Acceptor 可通信、提案编号足够高，且必要的进程和网络最终能够推进；它不保证任意异步调度下都终止。[原论文 §2.4](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

## 5. 从单值走向日志

一系列状态机操作需要多个槽位，每个槽选择相应命令，并处理顺序、空洞、客户端重复、快照和成员变更。Multi-Paxos 在稳定领导者等条件下复用阶段一的工作，但不是把 Basic Paxos 的所有环节永久删除。

Basic Paxos 又称单决议 Paxos（Single-Decree Paxos），本章的蓝色、红色之争只针对一个槽位。多槽位 Paxos（Multi-Paxos）可让稳定领导者为一组槽位复用阶段一（Phase 1）的承诺工作，正常处理新命令时主要执行阶段二（Phase 2）。新领导者仍要恢复、确认相关历史，继承已有接受值并处理空洞。同一领导者轮次的编号可用于不同槽位，仍须保证每个槽位内同号不提不同值；不能把复用阶段一理解为永久删除 Prepare。[原论文 §3](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

本章用于理解协议，不提供可直接部署的实现。练习时，可记录每个 Acceptor 的 promise 与 accepted 状态，推演消息乱序、重启和更高编号接管。需要验证的不变量是同一槽不能选出两个不同值，而不是“每个节点只收到过一条提案”。

[返回本册目录](/collections/distributed-systems/)
