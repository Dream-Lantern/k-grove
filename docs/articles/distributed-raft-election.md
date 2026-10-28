---
id: distributed-raft-election
title: 第九章 Raft 角色、任期与领导者选举
description: "Raft 通过选举确定协调日志复制的 Leader，再以日志与提交规则保护状态机历史。本章先沿 Follower、Candidate、Leader 的角色变化理解一轮选举，再分析任期、投票数量和日志新旧的判断。"
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
order: 9
---

# 第九章 Raft 角色、任期与领导者选举

> 阅读标签：Raft2014 / 选举。

Raft 通过选举确定协调日志复制的 Leader，再以日志与提交规则保护状态机历史。本章先沿 Follower、Candidate、Leader 的角色变化理解一轮选举，再分析任期、投票数量和日志新旧的判断。任期是逻辑编号，选举进展还取决于超时与网络条件。

## 1. 三种角色与任期

Follower 响应协议请求；Candidate 正在争取选票；Leader 协调日志复制。term 是逻辑编号，随着选举等协议事件推进，不是“每隔一分钟任期自然结束”。稳定 Leader 可以一直处于同一任期。

更高任期的信息使旧角色退回 Follower，但一个与外界隔绝的旧 Leader 可能暂时仍以为自己是 Leader。协议要求的是它不能绕过规则提交冲突状态，不是所有节点每时每刻都知道同一个领导者。

## 2. 从选举超时到发起 RequestVote {#_2-一轮选举如何开始}

![从怀疑到选举再到领导者](/assets/notes/distributed-systems/dist-raft-election.svg)

Follower 在适用的选举超时后成为 Candidate，提高任期、给自己投票并发 RequestVote。必要的 currentTerm 与 votedFor 在依赖它们的响应之前按协议持久化，避免重启后在同一任期投给不同候选人。

随机超时可以减少反复分票，但不保证在任意网络环境下都能选出 Leader。计时器应根据有效消息与投票规则重置，不能让任意旧任期的 AppendEntries 无限压制选举。[Raft 扩展论文 §5.2、图 2](https://raft.github.io/raft.pdf)

## 3. 固定投票成员中的多数计算 {#_3-多数包含谁}

固定 N 个投票成员，多数为 floor(N/2)+1，包含候选人自己的票。三成员需要两票，不是“两个 Follower 之外再加 Leader”；五成员需要三票。

偶数成员同样可以运行 Raft。三和四成员都只能在适用条件下容忍一个投票成员失效仍保持多数，第四个成员没有增加同样数量的故障容忍，却增加复制开销，这才是常见奇数部署的原因之一。

## 4. 按最后日志任期与索引判断新旧 {#_4-日志资格不能只看长度}

投票需要比较候选人最后日志的任期；任期相同时，再比较最后索引，候选人应至少一样新。这里比较的是最后日志条目的 term，不是简单比较服务器当前 currentTerm。

纸面例子：本地最后日志为 (term=6,index=12)，候选人为 (term=7,index=10)。仅就日志新旧比较，候选人更“新”；如果候选人是 (term=6,index=11)，则不够新。完整授票还须满足任期与本轮投票等其他条件。

## 5. 多数交集只是证明的一部分

任意两个多数集合都有交集，但仅凭“有一个重叠节点”，还不能证明新 Leader 包含全部已提交日志。投票限制、日志匹配和正确的提交规则也必须同时成立。第 10 章将解释，为什么不能只根据副本数直接提交旧任期条目。

## 6. 超时参数不是通用常量

网络延迟、磁盘停顿、调度暂停和故障恢复目标影响选举超时。心跳 100 ms、超时 300 ms 可以用于说明一种有前提的教学比例；实际产品的默认值和推荐配置需结合对应实现确认。

没有多数时，选举可以持续失败；这不授权少数自行确认写入。读请求也不能只因节点自称 Leader 就自动获得线性一致保证，参见第 11 章。

[返回本册目录](/collections/distributed-systems/)
