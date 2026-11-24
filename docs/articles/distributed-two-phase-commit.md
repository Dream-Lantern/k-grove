---
id: distributed-two-phase-commit
title: 第二十一章 两阶段提交与故障恢复状态机
description: "Two-Phase Commit（2PC，两阶段提交）用于协调多个事务资源，让它们接受同一个提交或中止决定。流程分为准备与决定两个阶段：参与者先保存可提交的承诺，协调者收集结果后持久化全局决定，再通知各方完成。"
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
order: 21
---

# 第二十一章 两阶段提交与故障恢复状态机

> 阅读标签：经典2PC原子提交 / 产品示例另标。

Two-Phase Commit（2PC，两阶段提交）用于协调多个事务资源，让它们接受同一个提交或中止决定。流程分两步：协调者先挨个问参与者“这笔能不能提交”，参与者把答案连同崩溃后恢复所需的信息写到盘上，再回答；协调者收齐答复后，把最终决定也写到盘上，然后逐个通知参与者执行。下面沿这条主线观察故障恢复。

## 1. 角色与前提

协调者管理本次事务决定，参与者分别处理自己负责的资源。比如一次转账要同时改两个数据库，这两个数据库就是两个参与者；每个数据库内部本来就有副本，副本不逐个算参与者，它们对外只交一个“准备好了”的答复。

事务 ID 贯穿准备、决定、重试与恢复。原子提交不自动规定隔离级别；参与者如何锁定或保留资源，依赖其并发控制实现。

## 2. 准备阶段的 YES 是持久承诺

[![2PC：准备请求、参与者投票与全局决议](/assets/notes/distributed-systems/dist-2pc.svg)](/assets/notes/distributed-systems/dist-2pc.svg)

协调者向各参与者发出准备请求。参与者在返回 YES 前，保存足以在故障后恢复 Prepared 状态的信息，并保留必要资源。协调者收到全体愿意提交的结果后，才具备作出 COMMIT 决定的条件。[Gray 与 Lamport 的原子提交分析 §2—3](https://lamport.azurewebsites.net/video/consensus-on-transaction-commit.pdf)

参与者返回 NO，或协调者在尚未作出提交决定时无法满足条件，可以选择 ABORT；另一类情况是决定已经存在、只是尚未收到。

准备状态（Prepared）表示参与者已将本地事务置于“可按最终决定完成”的状态。返回 YES 前，它必须完成本地检查，持久化足以在崩溃后恢复准备状态的信息，并保留数据版本、必要锁和其他资源。YES 是跨崩溃仍需遵守的承诺，与内存里投一个赞成票不同。

正确顺序是 **本地准备 → Prepared 信息持久化 → 进入 Prepared → 发送 YES**。发送 YES 后才补做持久化，会让协调者误以为参与者已经能够可靠提交，参与者重启后却可能忘记承诺。Prepared 后等待超时只是等待条件，事务原子性要求它继续服从同一个全局决定。[Gray 与 Lamport，§3.1](https://lamport.azurewebsites.net/video/consensus-on-transaction-commit.pdf)

### Participant 的恢复状态机

以下是保留显式决定日志的经典 2PC 教学模型，不包括只读投票等优化，也不要求每个产品使用相同状态字段：

```text
WORKING
  ├─ 本地不能准备 → 按协议中止并记录 → ABORTED（返回 NO）
  └─ 本地可以准备 → 持久化准备信息 → PREPARED（返回 YES）
                                         │
                                  查询 / 等待权威决定
                                  ┌──────┴──────┐
                                COMMIT         ABORT
                                  │              │
                            可靠完成并记录   可靠撤销并记录
                                  │              │
                              COMMITTED       ABORTED
                                  └──────┬──────┘
                                释放适用资源、返回 ACK
```

参与者重启后从可靠状态继续，Prepared 仍然算数。重复消息按同一事务 ID 与历史结果处理；COMMIT 表示完成已经准备好的事务，与重新调用一次扣款接口不同。记录回收后的迟到消息还要遵守第 6 节的恢复约定。

## 3. 决定必须先保存再发送

协调者将最终决定按协议持久化，再通知参与者。参与者持久化并完成相应决定，释放适用资源，返回确认。网络可能使不同参与者在不同时刻获知决定，最终结果仍只能有一个。

重复的 COMMIT/ABORT 应根据事务 ID 与已保存状态处理，重复消息按状态返回结果，不应重新执行业务。如果收到矛盾决定，应按严重协议错误处理；采用最后一条消息会掩盖冲突。

### Coordinator 的恢复状态机

协调者（Coordinator）必须可靠掌握本事务涉及的参与者及状态，才能判断“已经收到所有 YES”。沿用本章显式记录最终决定的教学模型：

```text
INIT → 建立事务与参与者恢复信息 → PREPARING → 发送 PREPARE
                                  │
             ┌────────────────────┴─────────────────────┐
       收到 NO / 适用中止条件                       收到全部 YES
             │                                          │
        持久化 ABORT                               持久化 COMMIT
             │                                          │
          ABORT                                      COMMIT
             └────────────────────┬─────────────────────┘
                        通知各参与者、重试丢失消息
                                  │
                         收到所需完成 ACK → DONE
```

选择 COMMIT 的条件是所有业务参与者均完成准备，多数投 YES 还不够。**最终 COMMIT 先持久化，再广播**；一旦决定可靠存在，后续某个 ACK 超时也不再改变它。ABORT 同样需要遵守所采用协议的日志顺序；后面介绍的 Presumed Abort 规则不同：它不写 ABORT 记录，靠“查不到记录就当前中止”来省掉一部分日志。[Gray 与 Lamport，§3.1～3.3](https://lamport.azurewebsites.net/video/consensus-on-transaction-commit.pdf)

DONE 表示所需完成确认已经收齐，处理迟到消息所需的身份和历史仍要保留。ACK 证明的是相应阶段按协议完成，收到网络包本身不满足参与者的持久完成条件。

## 4. 故障点逐项分析

| 已知状态                            | 允许怎样处理           | 为什么                      |
| ----------------------------------- | ---------------------- | --------------------------- |
| 参与者尚未承诺 YES                  | 按协议中止本地工作     | 尚未承担不可反悔的准备承诺  |
| 参与者已 Prepared，最终决定未知     | 查询权威状态或等待恢复 | 其他参与者可能已得到 COMMIT |
| 协调者持久保存 COMMIT，部分通知丢失 | 恢复后继续传播 COMMIT  | 超时不是改为 ABORT 的依据   |
| 参与者已提交，确认丢失              | 对重复决定返回相容结果 | 不再重复产生业务效果        |

参与者进入 Prepared 后，若尚未收到全局决定，应查询权威状态或等待恢复。协调者可能已经持久化 COMMIT，只是通知尚未到达；恢复判断需要依据日志与具体协议，超时本身不足以决定中止。

把协调者故障拆成完整教学时序：

```text
T1  Coordinator → P1、P2：PREPARE
T2  P1 完成本地准备，持久化并进入 PREPARED
T3  P1 → Coordinator：YES
T4  P2 完成本地准备，持久化并进入 PREPARED
T5  P2 → Coordinator：YES
T6  Coordinator 收齐 YES
T7  Coordinator 故障，P1、P2 尚未收到最终决定
```

P1、P2 此时可能面对两段无法仅凭本地观察区分的历史：一是协调者已持久化 COMMIT，但广播前崩溃；二是协调者尚未持久化最终决定便崩溃。即使它们互相确认“我也投了 YES”，本地观察仍分不清哪段历史发生了。

2PC 阻塞（Blocking）说的是参与者卡在 Prepared 上：它自己判断不了该提交还是该回滚，只能等协调者恢复，或去查可靠日志，才能知道结果。超时用于发起恢复动作，不是决定 ABORT 的证据。如果已经有 COMMIT 的可靠证明，恢复后继续传播它；协调者换机器也不改变已经持久化的决定。[Gray 与 Lamport，§3.3](https://lamport.azurewebsites.net/video/consensus-on-transaction-commit.pdf)

## 5. Prepared 状态中的资源占用与等待 {#_5-阻塞影响的是相关资源-不是所有节点停工}

Prepared 事务可能长时间占有锁或其他资源，使冲突操作等待；无关请求仍可执行。PostgreSQL 的准备事务也会继续持有适用锁，长时间遗留有运维风险。[PostgreSQL 17 PREPARE TRANSACTION](https://www.postgresql.org/docs/17/sql-prepare-transaction.html)

复制协调者状态提高了决策恢复能力，提交条件仍是所有业务参与者都同意。Raft 管的是同一份数据的多个副本要写成一样；2PC 管的是几个互相独立的数据库对“提交还是回滚”给出同一个答案。

例如 T1 已 Prepared 并保有账户 A 的写锁，T2 想更新 A，可能因锁冲突等待；T3 查询无关账户 C 则仍可能正常执行。具体读是否等待取决于隔离与版本机制，“Prepared 占资源”只影响冲突路径，整个数据库并不停工。

### 协调者高可用与 Paxos Commit

| 方案                  | 核心思想                                                           | 必须保留的边界                                                       |
| --------------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------- |
| 经典 2PC              | 一个逻辑 Coordinator 收集准备结果、保存最终决定                    | 决定权威不可达时，Prepared 参与者可能阻塞                            |
| 复制 Coordinator 状态 | 用 Raft/Paxos 等可靠复制事务列表和决定日志，再由相应领导者继续协议 | 需要旧协调者隔离与完整恢复；复制组多数不替代全体业务参与者的准备条件 |
| Paxos Commit          | 对各参与者的 Prepared/Aborted 结果分别运行共识，再导出全局决定     | 提交协议结构随之改变，外层复制替代不了这一步                         |

Gray 与 Lamport 的《Consensus on Transaction Commit》（2006 年发表）为每个资源管理者（Resource Manager，RM）建立一个 Paxos 实例，结果为 Prepared 或 Aborted。只有全部实例选择 Prepared，整体才提交；任一个选择 Aborted，整体中止。某 RM 失联时，协议可在相应 Paxos 安全规则允许的条件下为其完成 Aborted 选择，而不是永远等待它的业务 YES；若实例已经选择了 Prepared，则必须继承该结果。因此它与“少数参与者不同意也照样提交”是两回事。

论文用 `2F+1` 个协调接受者支持最多 F 个这类节点故障；当至少 `F+1` 个接受者能有效通信，且领导者选择与网络在足够长时间内满足推进条件时，协议可继续推进。多数数量只解决接受者侧的故障容忍，任意延迟、持续分区和领导者竞争仍会推迟完成；参与者恢复并完成业务还需获知结果。经典 2PC 是论文中 `F=0` 的特例，即不容忍唯一协调者不可用所带来的阻塞。这里的多数是**接受者集合**，不是业务数据库集合。[Gray 与 Lamport，§4.2、§5](https://lamport.azurewebsites.net/video/consensus-on-transaction-commit.pdf)

## 6. 决定完成后的记录回收与恢复约定 {#_6-日志回收不能靠猜测}

决定完成后何时可以遗忘事务，需要结合确认、恢复、重复消息和协议的 presumed-abort/commit 等约定设计。对于未知事务 ID 的 COMMIT，统一回复 ACK 证明不了此前已完成处理。

3PC 只在其假设的故障模型下缓解阻塞，任意网络分区下增加一轮并不足够。本章不提供手工清理 Prepared 事务的捷径；真实处置必须先确定全局权威决定，否则可能破坏原子性。

### Presumed Abort 与 Presumed Commit

预设中止（Presumed Abort，PA）和预设提交（Presumed Commit，PC）的做法是提前约定“查不到记录时默认哪一边”：PA 默认中止，PC 默认提交，靠这条约定省掉一部分日志和消息。它们的“预设”是整个恢复协议的结论，与现场运维的猜测无关。

R* 论文的 PA 在符合其记录与恢复规则的“无信息”查询情况下返回 ABORT；PC 则采用不同约定，还要求准备前等阶段的额外记录，使相应“无信息”查询可返回 COMMIT。若不知道系统采用哪种协议、记录是否按规则完整保存和回收，查不到事务时，提交与中止都还没有结论。对未知事务 ID 的 COMMIT，回复 ACK 也不等于业务完成，必须核对身份、历史和恢复约定。[Mohan、Lindsay、Obermarck，1986，§3～4](https://www.cs.cmu.edu/~15721-f24/papers/2PC.pdf)

### 3PC 的非阻塞假设

三阶段提交（Three-Phase Commit，3PC）增加中间阶段，限制不同节点可能处于的状态组合，使某些故障后能据此继续决定。它讨论的是特定故障和通信模型下的非阻塞；多一次往返解决不了所有网络问题。

Skeen 1981 原论文明确假设正常站点之间能通信、网络不发生故障，并能可靠报告站点失效；其状态模型中的故障站点停止推进，可按停止型故障（Fail-stop Failure）理解。若用超时实现这类检测，网络延迟及检测时序必须足以支撑这些假设。现实异步分区中，超时可能只是消息延迟或隔离，节点是否已死仍不确定；直接套用这些终止步骤可能破坏保证。原论文的“一个状态转换以内同步”也是协议进度性质，名称含 synchronous 只描述协议进度，与任意网络的现实时间上界无关。[Skeen，Nonblocking Commit Protocols，1981，§1、§3～5](https://www.cs.cornell.edu/courses/cs614/2004sp/papers/Ske81.pdf)

### PostgreSQL 17：准备一个本地事务

以下是单个数据库作为参与者的教学 SQL，假设 `accounts` 表及账户 id=1 已存在，并由应用验证余额、更新行数等业务条件。服务端还须为 `max_prepared_transactions` 配置非零容量，默认 0 会禁用准备事务，此参数需要按官方说明配置并重启生效。[PostgreSQL 17 资源参数](https://www.postgresql.org/docs/17/runtime-config-resource.html#GUC-MAX-PREPARED-TRANSACTIONS)

```sql
-- PostgreSQL 两阶段事务：先扣减账户余额，再以 transfer-1001 标识准备事务；PREPARE 还不是最终提交。
BEGIN;

UPDATE accounts
SET balance = balance - 100
WHERE id = 1;

PREPARE TRANSACTION 'transfer-1001';
```

PREPARE 不是最终 COMMIT。成功后，本地事务脱离原连接，保留准备状态及适用锁；原会话不再处于这笔活动事务中。可以查询准备事务视图：

```sql
-- 按 gid 查询已准备事务；prepared 为准备时间，owner/database 标识事务归属，查询不会结束事务。
SELECT gid, prepared, owner, database
FROM pg_prepared_xacts
WHERE gid = 'transfer-1001';
```

外部事务管理器根据全局权威决定，选择以下**其中一条**，在同一数据库内以具备权限的会话、在事务块外执行：

```sql
-- 按全局事务标识提交已经准备好的事务；它与下面的回滚是两种互斥决定，不能依次执行。
COMMIT PREPARED 'transfer-1001';
```

或者，在全局决定为中止时：

```sql
-- 按全局事务标识回滚已经准备好的事务；只有决定回滚的分支才执行，不接在 COMMIT PREPARED 后运行。
ROLLBACK PREPARED 'transfer-1001';
```

这些命令只处理本数据库的这一个事务，发现其他数据库、收集投票和管理全局决定仍由事务管理器负责。准备事务长期遗留会持锁、妨碍 VACUUM 回收，必须由可靠事务管理器及时完成并监控恢复；按存在时长批量回滚会破坏原子性。[PostgreSQL 17 PREPARE TRANSACTION](https://www.postgresql.org/docs/17/sql-prepare-transaction.html)、[COMMIT PREPARED](https://www.postgresql.org/docs/17/sql-commit-prepared.html)

若讨论内部存储，还要区分：PostgreSQL 17 的短期准备状态保存在共享内存与 WAL 中，跨越检查点的准备事务才记录到 `pg_twophase`；每次 PREPARE 并不立即建立独立目录文件。其可恢复性来自相应持久 WAL 等机制，某个目录是否有文件，也代替不了全局结果判断。[PostgreSQL 17 Two-Phase Transactions](https://www.postgresql.org/docs/17/two-phase.html)

从[第十九章 WAL](/articles/distributed-transactions-wal.html)到[第二十章并发控制](/articles/distributed-concurrency-isolation.html)，再到本章，依次处理本地恢复、事务交错和跨资源原子决定；Paxos/Raft 则处理相应复制状态的共识。这些构件可以组合，但不互相替代。

[返回本册目录](/collections/distributed-systems/)
