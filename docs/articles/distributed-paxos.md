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

共识协议要解决的是：多个节点对同一件事各有答案时，怎样只定下一个值，并且让后来的提案改不掉它。Basic Paxos 可以先只盯一个槽位：提议者先问一圈“你们答应过什么、接受过什么”，再发起接受请求。弄清一个槽位里多轮提案怎样互相约束，再扩展到连续日志。

## 1. 三种角色可以在同一进程中

提议者（Proposer）发起提案，接受者（Acceptor）保存承诺与接受状态，学习者（Learner）获知选定结果。这三个只是逻辑角色，实际可以跑在同一个进程里。本章假设节点不会撒谎（非拜占庭故障），只会崩溃或变慢，消息可能延迟或丢失，而必要状态可以写到磁盘上保存。

提案包含唯一、有序的编号 n 和值 v。一个 Acceptor 可以先后接受多个编号的提案，但要守住两条规则：不再接受比承诺更小的编号，以及按已接受的历史继承值。这两条合起来，保证已选定的值不会被后来的提案换成别的。[Paxos Made Simple §2](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

提案编号（Proposal Number）需要具有可比较的全序，并保证不同 Proposer 不会生成相同编号；同一实例内同一编号不能绑定两个不同值。教学上可以让每个 Proposer 各用一段互不重叠的编号，或者用 `(counter, proposer_id)` 这样的组合按字典序比大小；组合编号只是其中一种做法。重启后还要防止计数器回退造成编号复用，见 [原论文 §2.5](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)。

## 2. Prepare 阶段收集承诺与已接受值 {#_2-第一阶段为什么要询问历史}

Proposer 发送准备请求 `Prepare(n)`，这一步只询问承诺与历史，还不涉及接受业务值。对满足条件的编号，Acceptor 返回承诺（Promise）：不再接受编号小于 n 的新提案，并报告自己已接受的最高编号提案及其值（如果存在）。如果这个编号比自己已承诺的编号小，或者不满足其他条件，Acceptor 可以忽略，也可以明确拒绝。Proposer 收到针对本轮 n 的多数 Promise 后，才能按历史选择阶段二的值。

独立的教学推演：该 Acceptor 尚未接受任何值，当前最高 Promise 为 5，且没有其他并发消息：

```text
收到 Prepare(8)
    → 持久化 Promise=8，回复 Promise(8, accepted=无)
收到 Accept(6, red)
    → 6 < 8，违反已作出的承诺，拒绝
收到 Accept(8, blue)
    → 若没有更高 Promise，且提案遵循协议，可接受
```

Promise 的含义只有一条：不再接受比这个编号更小的提案。它既不代表接受了某个值，也不等于后面的 Accept。Acceptor 只负责检查“有没有违背之前许下的承诺”，“该继承哪个值”则由 Proposer 根据阶段一收到的历史来定，两边各管一件事。[原论文 §2.2](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

![Prepare、值继承、Accept 与选定](/assets/notes/distributed-systems/dist-paxos.svg)

若回复中包含已接受的值，阶段二沿用最高接受编号对应的值；若没有，才可选自己的值。任意两个多数派至少有一个节点是重叠的。新提案只要问到重叠的那部分节点，就能看到上一轮可能已经被接受的值；值继承规则正是利用这个重叠，保证已选定的值不会被换掉。

这里的“没有”指本轮已收集的多数回复全部没有已接受提案；只看其中一个空回复不够。若回复分别报告 `(5, blue)` 与 `(7, red)`，就继承编号更大的 7 号提案，也就是 red。这个例子假定各提案的历史本身合法：合法历史里，blue 一旦被选定，就不会再选出一个 red。

阶段二发送接受请求 `Accept(n,v)`。Acceptor 只有在不违反更高编号承诺等协议条件时才接受，并在持久化接受状态后回复。Prepare 收到多数 Promise 只完成了阶段一，值尚未选定。

## 3. 用三 Acceptor 推演

教学例子：A、B 接受了提案 `(5, blue)`，已达到三个 Acceptor 中的多数。新的 Proposer 发起 `Prepare(8)`，从 B、C 收到 Promise；B 报告已接受 `(5, blue)`，C 没有接受值。新提案必须继承蓝色 blue，编号更大只决定轮次，值仍要继承。

| 节点 | Promise | Accepted  |
| ---- | ------- | --------- |
| A    | 5       | (5, blue) |
| B    | 8       | (5, blue) |
| C    | 8       | 无        |

这张状态表表示新一轮 Prepare 已完成、Accept 尚未开始的教学时刻。下一步应发送 `Accept(8, blue)`。原多数 `{A,B}` 与新多数 `{B,C}` 的交集为 `{B}`，因此新轮次能从 B 得到接受历史。若 B 报告了更高编号的已接受提案，就按最高编号规则继承；协议的安全性保证合法历史中的这些继承不会推翻已选定值。

注意“某个节点接受了”和“多数节点选定了”是两种状态。即使新 Proposer 手上拿不出多数证据，继承规则仍然会保护那些可能已经选定的值。恢复时必须依据已经持久化的记录来判断；“我猜上次没成功”这种印象不能作为恢复的依据。

### Accepted、Chosen 与 Learned

| 概念               | 定义                                                                |
| ------------------ | ------------------------------------------------------------------- |
| 已接受（Accepted） | 某个 Acceptor 已接受某编号及其值，这是单节点事实                    |
| 已选定（Chosen）   | 同一实例中，同一个提案 `(n,v)` 已被多数 Acceptor 接受，这是协议事实 |
| 已获知（Learned）  | 某个 Learner 已有足够证据知道值被选定，这是该观察者的知识状态       |

教学消息丢失案例：A、B 已接受 `(5, blue)`，所以 blue 已 Chosen；通知 Learner 的消息却丢失，它仍未 Learned。后续没有及时收到结果，不会把已选定值变回未选定。

Learner 可以收集同一实例、同一提案编号的多数接受通知，或由指定学习者收集后再分发结果。如果恢复时只能查询当前接受记录，部分节点已不可达或记录已前进到更高提案，旧多数证据可能重建不出来；此时可通过新一轮合法提案重新选定并获知受保护的值，避免凭猜测判断先前结果。[原论文 §2.3](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

## 4. 用持久化保护历史，用提议者协调改善进展 {#_4-持久化与活性分别影响什么}

在允许崩溃重启的模型中，Acceptor 必须先把依赖的协议状态写入稳定存储（Stable Storage），再发送相应响应，主要包括已响应的最高 Prepare 编号，以及已接受的最高编号提案及其值。[原论文 §2.5](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

若已回复 Promise(8) 却在重启后忘记承诺，就可能再次接受编号 6；若忘记已接受的 blue，新 Proposer 可能收到错误的“无历史”回复。这会破坏后续继承依赖的事实。这些状态需要稳定存储；仅把响应发出去，再异步保存它们，留下了响应与持久化之间的崩溃窗口。

多个 Proposer 不断以更高编号互相抢占，可能长期无法完成阶段二。安全性只保证不会选出两个不同的值；至于能不能最终选出一个值，还要看活性条件。实际系统通常指定一个稳定的提议者，减少互相抢占。只数消息轮次就宣称 Paxos 永远比 Raft 慢一倍，缺乏依据。

例如 P 完成 Prepare(8)，Q 又完成 Prepare(9)，使 P 的 Accept(8, blue) 被拒绝；P 再提高到 10，又抢在 Q 的阶段二之前取得承诺，过程就可能反复。稳定的指定提议者（Distinguished Proposer）减少这种竞争，但活性仍需多数 Acceptor 可通信、提案编号足够高，且必要的进程和网络最终能够推进；任意异步调度下是否终止，取决于这些条件能否满足。[原论文 §2.4](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

## 5. 从单值走向日志

真实系统要执行的是一连串命令，而不是一个值。于是把日志切成一个个槽位，每个槽位跑一次 Paxos 来选一条命令；随之还要处理槽位顺序、中间空洞、客户端重试造成的重复、日志快照和成员变更。Multi-Paxos 在稳定领导者等条件下复用阶段一的工作，但阶段一并未消失。

Basic Paxos 又称单决议 Paxos（Single-Decree Paxos），本章的蓝色、红色之争只针对一个槽位。多槽位 Paxos（Multi-Paxos）可让稳定领导者为一组槽位复用阶段一（Phase 1）的承诺工作，正常处理新命令时主要执行阶段二（Phase 2）。新领导者仍要恢复、确认相关历史，继承已有接受值并处理空洞。同一领导者轮次的编号可用于不同槽位，仍须保证每个槽位内同号不提不同值；复用阶段一之后，Prepare 仍在领导者切换和恢复时使用。[原论文 §3](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)

本章用于理解协议，不提供可直接部署的实现。练习时，可记录每个 Acceptor 的 promise 与 accepted 状态，推演消息乱序、重启和更高编号接管。需要验证的不变量只有一条：同一个槽位不能选出两个不同的值。

[返回本册目录](/collections/distributed-systems/)
