---
id: distributed-raft-log-replication
title: 第十章 Raft 日志复制、提交与冲突修复
description: "Raft 日志把命令按顺序组织成可恢复的历史。一条命令从请求进入 Leader 到影响状态机，会经历收到条目、持久保存、确认提交和应用四个阶段。"
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
order: 10
---

# 第十章 Raft 日志复制、提交与冲突修复

> 阅读标签：Raft2014 / 日志安全。

Raft 日志把命令按顺序组织成可恢复的历史。一条命令从请求进入 Leader 到影响状态机，会经历收到条目、持久保存、确认提交和应用四个阶段。沿着这些阶段观察索引与副本状态，可以理解响应时机、故障恢复和冲突修复。

## 1. 日志末尾、commitIndex 与 lastApplied {#_1-三个位置各自表示什么}

日志条目有 index 与 term。commitIndex 表示已知提交的日志边界，lastApplied 表示已经应用到状态机的位置。节点可能已保存更长日志，但尚不知道其中哪些已提交；应用进度也可能落后于提交进度。

| 阶段 | 含义 | 不能据此判断什么 |
| --- | --- | --- |
| 已收到（Received） | 条目到达某节点，进入接收或内存处理阶段 | 收到网络消息不等于已写入稳定存储；Leader 收到客户端请求还需创建条目 |
| 已持久保存（Persisted） | 该节点按协议把条目写入可跨崩溃恢复的稳定存储 | 本地保存不等于集群已提交 |
| 已提交（Committed） | 通过 Raft 提交规则确定，合法后继 Leader 不能再用不同命令覆盖这个位置 | 各节点未必已经获知提交，也未必已执行命令 |
| 已应用（Applied） | 节点按索引顺序把已提交命令交给状态机，产生状态和结果 | 客户端未必已收到结果；外部服务副作用还需相应协议 |

前三者中的本地接收、持久化与节点的提交认知要分开观察。Follower 成功回复 `AppendEntries`，表示本次确认的匹配与保存条件满足，不表示客户端业务请求已经完成。[Raft 图 2、§5.3](https://raft.github.io/raft.pdf)

教学状态：`commitIndex=10、lastApplied=8` 表示该节点已知日志 1～10 提交，状态机只应用到 8，9、10 仍待应用。已提交边界可以领先于已应用边界；不能直接从“提交到 10”推导状态机已包含第 10 条命令。

![从接收到应用的不同阶段](/assets/notes/distributed-systems/dist-raft-log.svg)

通常要等业务命令提交并取得应用结果后，才能向客户端返回成功，不能在 Leader 刚将请求放入内存时就确认。具体 API 承诺了什么，仍需检查实际实现。

### 一条 SET 命令的完整教学时序

设 A 是 Term=4 的 Leader，B、C 是 Follower；共同前缀已到 index=4，其任期依次为 `1、1、2、3`。客户端执行 `SET x=100`，新条目为 `(index=5, term=4, command=SET x=100)`：

1. A 收到请求，创建条目并按协议持久保存；只有 A 一份，还未提交。
2. A 向 B、C 发送 `AppendEntries`。假设 B 先收到，持久保存后返回成功，C 的消息暂时延迟。
3. A 确认自己和 B 共两份持久副本，且 index=5 属于当前任期 4，于是把 `commitIndex` 推进到 5。此刻 B 可以还只有 `commitIndex=4`，图中展示的正是这一时刻。
4. A 按序应用条目 5，得到 x=100 和操作结果，`lastApplied` 达到 5，再按本例的成功响应契约回复客户端。
5. 后续 `AppendEntries` 携带 `leaderCommit=5`。B 在安全匹配边界内获知提交并应用；C 收到缺失条目后也可追赶。

Leader 的提交认知与 Follower 的认知可以暂时不同，提交不是同时广播给所有节点的一次瞬时变量赋值。

| A 的故障时点 | 可能的后续历史 |
| --- | --- |
| 提交前 | 未提交条目可能被后继保留并最终提交，也可能被合法冲突历史覆盖；不能保证已生效或必定丢失 |
| 提交后、应用前 | 后继 Leader 必须保有该日志；恢复安全提交认知后，状态机仍需按顺序应用，不应回滚已提交决定 |
| 已有业务结果、客户端收到回复前 | 客户端可能超时，但命令已经生效；重试要沿用稳定操作 ID 并由状态机去重 |

这些是教学故障分支，不是实测记录。`SET x=100` 本身容易重复执行，但一般业务命令不一定如此；去重与结果缓存的依据见 [Raft §8](https://raft.github.io/raft.pdf)。

## 2. AppendEntries 用前缀匹配合并日志 {#_2-appendentries-为什么携带前缀信息}

| 字段 | 本次请求携带的信息 |
| --- | --- |
| `prevLogIndex` | 新条目紧前面的日志索引 |
| `prevLogTerm` | Leader 在该索引处的日志任期 |
| `entries` | 从匹配前缀之后开始的待复制条目，可为空以发送心跳 |
| `leaderCommit` | Leader 当前已知的提交边界 |

Follower 不能盲目追加：它先检查任期，再确认本地在 `prevLogIndex` 处有 `prevLogTerm`。依据日志匹配性质，这个检查可建立共同前缀；不匹配则拒绝，本次拒绝本身不要求删除任何日志。匹配后才合并条目，并按 `leaderCommit` 和本次请求已确认匹配的末端限制本地提交推进，不能把本地额外的未知后缀一起提交。[Raft 图 2、§5.3](https://raft.github.io/raft.pdf)

发现同一索引条目的任期冲突时，删除冲突条目及其后缀，再追加来自 Leader 的相应新条目。不是“收到一个成功 RPC 就清空本地所有日志”，更不能覆盖已经提交的合法前缀。[Raft 扩展论文 §5.3—5.4、图 2](https://raft.github.io/raft.pdf)

教学修复例子，数字表示日志条目的 Term：

```text
index       1  2  3  4  5
Leader      1  1  2  3  3
Follower    1  1  4
```

这里 Leader 的**当前任期为 5**，不是最后日志任期 3；Follower 的 term=4 后缀未提交。Leader 可以从其他成员得到选票当选，不能假设持有更高日志任期的这个 Follower 曾投给它。双方已提交前缀到 2，修复只处理其后的未提交历史：

| 尝试 | nextIndex | 前缀检查 | 结果 |
| --- | --- | --- | --- |
| 1 | 6 | `prevLogIndex=5, prevLogTerm=3` | Follower 没有 index=5，拒绝 |
| 2 | 5 | `prevLogIndex=4, prevLogTerm=3` | 没有 index=4，拒绝 |
| 3 | 4 | `prevLogIndex=3, prevLogTerm=2` | 本地为 term=4，拒绝 |
| 4 | 3 | `prevLogIndex=2, prevLogTerm=1` | 匹配；用 entries[3～5] 替换从 index=3 开始的冲突后缀 |

修复后 Follower 为 `1、1、2、3、3`；这些旧任期条目被复制，不表示它们因此直接提交。重复发送同一请求时，已有相同 index、term 的条目保留，不应重复追加，也不应仅因重传就删除重建。

![任期 5 Leader 对 Follower 的前缀回退与未提交冲突修复](/assets/notes/distributed-systems/dist-raft-conflict-repair.svg)

## 3. nextIndex 与 matchIndex 是每个 Follower 的状态

| 字段 | 含义 | 维护方 |
| --- | --- | --- |
| `nextIndex[f]` | 下次准备向 Follower f 发送的起始日志索引，是尝试位置 | Leader 为每个 Follower 分别维护 |
| `matchIndex[f]` | 已确认该 Follower 与本 Leader 匹配的最高日志索引 | Leader 为每个 Follower 分别维护 |
| `commitIndex` | 本节点已知提交边界 | 每个节点 |
| `lastApplied` | 本节点状态机已应用边界 | 每个节点 |

基础算法中新 Leader 把 `nextIndex` 初始化为自己最后索引加一；图 2 的 `matchIndex` 初始化为 0，表示尚未确认该 Follower 的匹配进度。失败时降低对应的 `nextIndex`，成功后更新该 Follower 的 `matchIndex` 与下一次发送位置。在同一领导者任期内，已确认的匹配进度应单调前进，不能被迟到响应倒退；换 Leader 时会重新初始化这些状态。[Raft 图 2](https://raft.github.io/raft.pdf)

## 4. 当前任期条目与提交边界 {#_4-多数保存为什么还不够}

Leader 通过副本计数直接推进提交边界时，要找到满足多数复制且属于自己当前任期的条目。该条目提交后，前面的条目随前缀间接提交。旧任期条目即使已经出现在多数上，也不能脱离这条规则直接认定提交。

### Figure 8 的五节点反例

下面按 [Raft §5.4.2、Figure 8](https://raft.github.io/raft.pdf) 用 A～E 表示五台服务器。初始 index=1、term=1 为共同前缀，关注 index=2；多数为 3。表中每个节点的数字是它在 index=2 保存的日志任期，`—` 表示尚无该条目：

| 阶段 | 当前领导者 | A | B | C | D | E | 判断 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| a | A，Term=2 | 2 | 2 | — | — | — | 条目只复制到 A、B，未提交 |
| b | E，Term=3；A 故障 | 2 | 2 | — | — | 3 | E 得 C、D、E 的票，在同一索引写入不同命令，尚未形成多数 |
| c | A，Term=4；E 故障 | 2 | 2 | 2 | — | 3 | A 恢复当选，将旧条目复制到 C；虽有三份 term=2，仍不能仅数副本判提交 |
| d，c 的一种后续 | E，Term=5；A 再故障 | 2 | 2 | 2 | — | 3 | E 的最后日志任期 3 比 B、C 的 2 高，可获 B、C、D 等选票；随后覆盖旧的未提交 index=2 |

交集节点 B、C 确实有 term=2 条目，但投票规则比较的是**最后日志任期**，E 的 term=3 仍可能被认为更“新”。如果在 c 就把 index=2 当作提交，d 的合法选举与修复会推翻这个“提交”，所以该计数推断不成立。

另一种后续 e：A 在 Term=4 继续追加 `(index=3, term=4)`，并把前缀一起复制到 A、B、C。当前任期条目在多数上保存，才能直接提交到 3，并使之前的 index=2 间接提交。此时只持有 term=3 后缀的 E 无法从这个多数中的任何成员取得满足日志新旧规则的选票。配合日志匹配与领导者完整性证明，已提交前缀就受到保护。d 和 e 是互斥分支，不是先覆盖后再恢复的连续过程。

提交计数包含 Leader 自己，不能省略成“超过半数 Follower 回复，就全部生效”。

## 5. 冲突加速与字段名称

XTerm/XIndex/XLen 是部分课程或实现采用的优化字段，字段名称与格式应按对应实现理解。常见意图是返回冲突任期、该任期首位置，或日志过短时的有效结束边界，让 Leader 跳过一段失败尝试。

上一节修复表采用基础算法的逐一回退。论文 §5.3 也讨论按冲突任期加速：Follower 提示冲突任期及它的首位置，Leader 可跳过一段条目；若 Leader 没有这个任期，就回退到该段起点。字段是否叫 XTerm/XIndex/XLen、过短时如何编码，属于具体课程或实现约定，不是所有 Raft RPC 的统一接口。

日志过短时，应推导“Follower 最后索引+1”这样的边界，不能在未定义索引起点时就将 XLen 解释为“空白槽位数量”。存在快照前缀时，还需结合快照基准，不能直接把数组下标当作日志绝对索引。

## 6. 教学验收不变量

同一已提交索引的命令不能在合法后继 Leader 中改变；状态机按顺序应用已提交命令；重复业务请求仍需请求身份去重。共识日志防止历史分叉，不自动防止客户端把同一扣款请求写成两个不同条目。

下一章继续回答：日志无限增长时如何制作快照，重启如何恢复进度，读取如何确认安全边界，以及成员变化时如何维护配置一致性。

[返回本册目录](/collections/distributed-systems/)
