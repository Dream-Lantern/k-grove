---
id: distributed-raft-log-replication
title: 第十章 Raft 日志复制、提交与冲突修复
description: 日志记录操作顺序与恢复历史，并不意味着其中所有条目都已执行。理解 Raft 时，应区分收到条目、持久保存、确认提交和应用到状态机四个阶段。若将它们统称为一个 ACK，就可能误判故障时哪些内容可以删除，以及能向客户端作出何种承诺。
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
order: 10
---

# 第十章 Raft 日志复制、提交与冲突修复

> 阅读标签：Raft2014 / 日志安全。

日志记录操作顺序与恢复历史，并不意味着其中所有条目都已执行。理解 Raft 时，应区分收到条目、持久保存、确认提交和应用到状态机四个阶段。若将它们统称为一个 ACK，就可能误判故障时哪些内容可以删除，以及能向客户端作出何种承诺。

## 1. 三个位置各自表示什么？

日志条目有 index 与 term。commitIndex 表示已知提交的日志边界，lastApplied 表示已经应用到状态机的位置。节点可能已保存更长日志，但尚不知道其中哪些已提交；应用进度也可能落后于提交进度。

![从接收到应用的不同阶段](/assets/notes/distributed-systems/dist-raft-log.svg)

通常要等业务命令提交并取得应用结果后，才能向客户端返回成功，不能在 Leader 刚将请求放入内存时就确认。具体 API 承诺了什么，仍需检查实际实现。

## 2. AppendEntries 为什么携带前缀信息？

Leader 用 prevLogIndex、prevLogTerm 指明新条目前面的那个位置。Follower 检查本地前缀是否匹配，不匹配则拒绝；匹配后才按规则合并新条目。重复消息不应导致重复追加相同日志。

发现同一索引条目的任期冲突时，删除冲突条目及其后缀，再追加来自 Leader 的相应新条目。不是“收到一个成功 RPC 就清空本地所有日志”，更不能覆盖已经提交的合法前缀。[Raft 扩展论文 §5.3—5.4、图 2](https://raft.github.io/raft.pdf)

## 3. nextIndex 与 matchIndex 是每个 Follower 的状态

基础算法中新 Leader 的 nextIndex 初值是自身最后日志索引加一，表示下一次尝试从哪里发送；matchIndex 表示已确认匹配到哪里。某 Follower 拒绝时，Leader 对它回退，而不是等待所有 Follower 同时一致才推进每个位置。

匹配推演，数字为日志 term：

```text
index       1  2  3  4
Leader      1  2  4  4
Follower    1  2  3
```

若索引 3 的前缀检查发生冲突，回到可匹配的索引 2，再用正确后缀修复。这里不暗示 term=3 的条目已提交；合法 Raft 不应靠删除提交条目完成修复。

## 4. 多数保存为什么还不够？

Leader 通过副本计数直接推进提交边界时，要找到满足多数复制且属于自己当前任期的条目。该条目提交后，前面的条目随前缀间接提交。旧任期条目即使已经出现在多数上，也不能脱离这条规则直接认定提交。

原因是未来选举中的日志新旧比较可能允许另一条历史接管。论文图 8 展示的反例正是为了限制这个推断。不能把这项条件省略成“超过半数 Follower 回复，就全部生效”。

## 5. 冲突加速与字段名称

原笔记的 XTerm/XIndex/XLen 是课程或实现采用的优化字段，不是所有 Raft RPC 的统一接口。常见意图是返回冲突任期、该任期首位置，或日志过短时的有效结束边界，让 Leader 跳过一段失败尝试。

日志过短时，应推导“Follower 最后索引+1”这样的边界，不能在未定义索引起点时就将 XLen 解释为“空白槽位数量”。存在快照前缀时，还需结合快照基准，不能直接把数组下标当作日志绝对索引。

## 6. 教学验收不变量

同一已提交索引的命令不能在合法后继 Leader 中改变；状态机按顺序应用已提交命令；重复业务请求仍需请求身份去重。共识日志防止历史分叉，不自动防止客户端把同一扣款请求写成两个不同条目。

[返回本册目录](/collections/distributed-systems/)
