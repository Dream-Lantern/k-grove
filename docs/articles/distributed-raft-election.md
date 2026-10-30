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

跟随者（Follower）响应协议请求；候选人（Candidate）正在争取选票；领导者（Leader）协调日志复制。任期（Term，逻辑纪元）是递增编号，每个任期以一次选举开始，不是固定时间租约；稳定 Leader 可以一直处于同一任期。分票（Split Vote）时没有人取得多数，该任期就可能没有 Leader。

不同节点观察任期变化的时间可以不同，也可能跳过某些任期。`currentTerm` 是本服务器已知的最新任期，`lastLogTerm` 是本地最后一条日志所属任期；即使节点已参加新选举，也可能尚未追加本任期日志，二者不能混用。[Raft §5.1～5.2](https://raft.github.io/raft.pdf)

更高任期的信息使旧角色退回 Follower，但一个与外界隔绝的旧 Leader 可能暂时仍以为自己是 Leader。协议要求的是它不能绕过规则提交冲突状态，不是所有节点每时每刻都知道同一个领导者。

## 2. 从选举超时到发起 RequestVote {#_2-一轮选举如何开始}

![从怀疑到选举再到领导者](/assets/notes/distributed-systems/dist-raft-election.svg)

Follower 在选举超时后成为 Candidate，开始一轮选举：`currentTerm` 加一，将 `votedFor` 设为自己，重置随机选举计时器，然后向其他成员发送投票请求 `RequestVote`。任期与自投票必须先持久化，再对外发起依赖它们的请求，避免重启后重复使用旧状态。[Raft 图 2、§5.2](https://raft.github.io/raft.pdf)

### 任期有效性与日志匹配分开处理

追加条目请求 `AppendEntries` 也用于心跳。以下规则基于非拜占庭模型中的协议消息，先判断任期与角色，再检查日志是否匹配：

| 收到的消息 | 角色、状态与计时器处理 |
| --- | --- |
| 任意 RPC 请求或响应带来更高 Term | 更新 `currentTerm`、清除旧任期投票并退回 Follower；持久化后按具体消息继续处理 |
| 低于 `currentTerm` 的 AppendEntries | 拒绝；不能靠旧领导者消息无限重置选举计时器 |
| 当前或更高任期的合法领导者 AppendEntries | 按该任期领导者消息处理并重置选举计时器；Candidate 退回 Follower；更高任期还要先更新任期 |
| 满足授票条件的 RequestVote | 记录并持久化本任期投票，授票时重置计时器 |
| 没有授票的 RequestVote | 不能只因收到投票请求就重置选举计时器；若任期更高，仍要执行前述任期更新规则 |

例如，Candidate 收到同任期领导者的 AppendEntries，应退回 Follower；即使 `prevLogIndex/prevLogTerm` 检查不通过，仍可拒绝本次追加并等待日志修复。这种失败不等于否认消息的任期有效性。反过来，低任期的追加请求即使内容碰巧与本地日志匹配，也不能让旧 Leader 恢复权威。规则依据见 [Raft 图 2、§5.2～5.3](https://raft.github.io/raft.pdf)。

随机超时可以减少反复分票，但不保证在任意网络环境下都能选出 Leader。计时器应根据有效消息与投票规则重置，不能让任意旧任期的 AppendEntries 无限压制选举。[Raft 扩展论文 §5.2、图 2](https://raft.github.io/raft.pdf)

### 崩溃重启需要保留的状态

| 持久化状态 | 为什么需要保留 |
| --- | --- |
| `currentTerm` | 重启后不能退回旧任期并接受过期权威 |
| `votedFor` | 重启后仍记得本任期投给谁，防止同任期投给不同候选人 |
| `log` | 恢复已记录的命令及任期，继续参与日志资格判断与复制 |

这些是论文图 2 列出的持久化状态，更新必须在发送依赖它们的 RPC 响应前落入稳定存储。教学反例：某节点投给 B 后立即崩溃，如果投票只在内存里，重启后又投给 C，就可能破坏“一任期一票”的前提。

## 3. 固定投票成员中的多数计算 {#_3-多数包含谁}

固定 N 个投票成员，多数计算为 `majority = floor(N / 2) + 1`，候选人自己的票也计入；同一成员的重复回复不能重复计票。

| 固定投票成员数 N | 多数票 | 仍可保持多数的最大失效成员数 |
| --- | --- | --- |
| 3 | 2 | 1 |
| 4 | 3 | 1 |
| 5 | 3 | 2 |

上述容忍数量以其余成员可通信并满足进展条件为前提。三成员的两票不是“两个 Follower 之外再加 Leader”。成员变更涉及联合共识，不能直接套用一份固定配置的票数表，留待后续章节。

偶数成员同样可以运行 Raft。三和四成员都只能在适用条件下容忍一个投票成员失效仍保持多数，第四个成员没有增加同样数量的故障容忍，却增加复制开销，这才是常见奇数部署的原因之一。

## 4. 按最后日志任期与索引判断新旧 {#_4-日志资格不能只看长度}

投票需要比较候选人最后日志的任期；任期相同时，再比较最后索引，候选人应至少一样新。这里比较的是最后日志条目的 term，不是简单比较服务器当前 currentTerm。

以下均为教学日志状态，不是运行记录，元组表示 `(lastLogTerm, lastLogIndex)`：

| 本地最后日志 | 候选人最后日志 | 仅按日志资格判断 |
| --- | --- | --- |
| (term=6, index=12) | (term=7, index=10) | 候选人更“新”，因为最后日志任期更高，不能只按长度判断 |
| (term=7, index=12) | (term=7, index=10) | 任期相同但候选人索引较小，不够新 |
| (term=6, index=12) | (term=6, index=11) | 同样不够新 |

教学伪代码如下，未执行；参数中的 term 都指**最后日志任期**，不指 `currentTerm`：

```python
def is_candidate_up_to_date(
    candidate_term,
    candidate_index,
    local_term,
    local_index,
):
    if candidate_term != local_term:
        return candidate_term > local_term

    return candidate_index >= local_index
```

这只是日志新旧判断，不是完整授票实现。授票还要检查请求任期、`votedFor` 是否为空或已经投给同一候选人，并正确持久化状态。[Raft §5.4.1、RequestVote 规则](https://raft.github.io/raft.pdf)

## 5. 多数交集只是证明的一部分

任意两个多数集合都有交集，但仅凭“有一个重叠节点”，还不能证明新 Leader 包含全部已提交日志。投票限制、日志匹配和正确的提交规则也必须同时成立。第 10 章将解释，为什么不能只根据副本数直接提交旧任期条目。

| 性质 | 保证什么 | 关键机制 |
| --- | --- | --- |
| 选举安全性（Election Safety） | 同一个 Term 最多选出一个 Leader | 每个成员每任期至多投给一个候选人、持久化投票、获多数当选 |
| 领导者完整性（Leader Completeness） | 某条目在一个任期提交后，会存在于所有更高任期 Leader 的日志中 | 日志新旧授票限制、日志匹配与提交规则共同保护已提交历史 |

日志匹配（Log Matching）指：若两个日志在某索引处具有相同任期的条目，则该位置的命令及此前全部条目都相同。它配合投票资格与提交条件，才让多数交集中的节点能够保护已提交历史；“拿到多数票”不是独立于这些约束的日志完整性证明。[Raft 图 3、§5.4](https://raft.github.io/raft.pdf)

## 6. 超时参数不是通用常量

若多个节点同时超时，它们可能各自投给自己并分散其他选票，形成分票。每轮重新随机选择选举超时，让某个候选人有机会更早发起请求并在其他节点超时前取得多数；这降低反复撞车的概率，不是无条件成功证明。

网络延迟、RPC 往返、磁盘持久化停顿、调度暂停和故障恢复目标都会影响超时选择。心跳 100 ms、每轮从 300～600 ms 选一个选举超时，仅是有前提的教学参数，不是通用推荐配置。论文讨论广播耗时、选举超时与平均故障间隔的关系，见 [Raft §5.2、§5.6](https://raft.github.io/raft.pdf)。

没有多数时，选举可以持续失败；这不授权少数自行确认写入。读请求也不能只因节点自称 Leader 就自动获得线性一致保证，参见第 11 章。

选举解决由谁协调日志复制。下一章继续解释 `AppendEntries`、提交索引 `commitIndex`、日志冲突修复，以及为什么旧任期日志不能简单根据多数副本直接判定为已提交。

[返回本册目录](/collections/distributed-systems/)
