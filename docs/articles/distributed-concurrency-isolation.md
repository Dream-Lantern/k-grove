---
id: distributed-concurrency-isolation
title: 第二十章 并发控制、隔离级别与可串行化
description: "原子提交决定一笔事务最终提交还是中止，并发控制则规定多笔事务交错执行时允许观察到什么、产生什么结果。二者相关，但并不相同。"
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
order: 20
---

# 第二十章 并发控制、隔离级别与可串行化

> 阅读标签：事务隔离模型 / PostgreSQL17示例。

原子提交决定一笔事务最终提交还是中止，并发控制则规定多笔事务交错执行时允许观察到什么、产生什么结果。二者相关，但并不相同。即使跨节点原子提交正确，较弱的隔离仍可能让两个业务检查同时通过。

## 1. 可串行化约束事务结果 {#_1-可串行化不是单线程运行}

可串行化要求已提交事务的结果等价于某个串行顺序，而不要求物理执行时一个事务完全结束后才启动下一个。读写不冲突的事务可以并行；冲突由锁、验证或其他机制处理。

严格可串行化再要求保留事务之间的实时先后。单对象线性一致性、SQL 隔离级别和应用业务不变量需要分别说明，不能统一写成“强一致”。

### SQL 隔离级别与 PostgreSQL 17 的区别

隔离级别（Isolation Level）规定事务允许观察到哪些并发现象。先区分四种现象：脏读（Dirty Read）读到其他事务尚未提交的数据；不可重复读（Nonrepeatable Read）两次读同一行得到不同已提交值；幻读（Phantom Read）重复条件查询时，匹配行集合改变；序列化异常（Serialization Anomaly）指一组已提交事务的结果无法对应任何串行执行顺序。

下表是 SQL 标准层面的基本限制，由 PostgreSQL 17 文档对标准的说明整理，**不是每个产品的实际行为表**：

| 隔离级别 | 脏读 | 不可重复读 | 幻读 | 序列化异常 |
| --- | --- | --- | --- | --- |
| Read Uncommitted（读未提交） | 标准允许 | 可能 | 可能 | 可能 |
| Read Committed（读已提交） | 不允许 | 可能 | 可能 | 可能 |
| Repeatable Read（可重复读） | 不允许 | 不允许 | 标准允许 | 可能 |
| Serializable（可串行化） | 不允许 | 不允许 | 不允许 | 不允许 |

具体数据库可以提供比该级别最低要求更强的保证。PostgreSQL 17 的行为是：

| PostgreSQL 17 级别 | 实际观察规则 |
| --- | --- |
| Read Uncommitted | 按 Read Committed 实现，不读取别人的未提交数据 |
| Read Committed | 普通查询使用语句开始时的新快照；同一事务不同语句可能看到不同提交进度 |
| Repeatable Read | 采用快照隔离，基于事务中第一个非事务控制语句取得的快照；不是简单在 BEGIN 的墙钟时刻固定 |
| Serializable | 在快照隔离上增加序列化异常检测，可能中止事务并要求整体重试 |

这几种模式都还要考虑本事务自己的写入等可见性规则。PostgreSQL 17 的 Repeatable Read 不出现标准定义的幻读，却仍允许某些序列化异常，所以不能把它当成 Serializable。[PostgreSQL 17 §13.2 与 Table 13.1](https://www.postgresql.org/docs/17/transaction-iso.html)

### Serializable、严格可串行化与线性一致

可串行化（Serializable）说明事务结果等价于某个串行顺序；严格可串行化（Strict Serializability）进一步要求尊重不重叠事务的真实时间先后。线性一致性（Linearizability）通常讨论对象或服务操作在调用与返回之间的实时顺序；把操作扩展为多步事务时，还必须明确事务范围。

教学时间线：T1 完成提交并返回之后，T2 才开始。严格可串行化要求 T1 排在 T2 前；单凭“存在某个串行顺序”这一条件，还没有陈述这条现实时间约束。并发事务的时间区间若重叠，则需要依据其实际依赖选择相容顺序。PostgreSQL 17 的 `SERIALIZABLE` 本章按官方文档的可串行化保证解释，不据其名称额外宣传严格可串行化或跨多个外部服务的事务保证。

## 2. 丢失更新与写偏差

教学例子一：两个事务都读到库存 10，分别计算 9 再写回，可能丢失一次扣减。适用的原子更新或版本条件可帮助解决，但它没有覆盖所有多行约束。

教学例子二：值班表要求至少一人值班。A、B 两事务都从快照看到两人在线，各自把自己设为离线，写不同记录，可能最终无人值班。这是写偏差思路，说明“没有写同一行”不等于不会破坏跨行不变量。

### Lost Update：同一行的读、计算、覆盖

丢失更新（Lost Update）发生在一个更新覆盖了另一个更新的效果。设 PostgreSQL 17 使用 Read Committed，应用先读再计算并写常量，没有额外锁或版本检查；库存行 id=1 初值为 10：

| 时刻 | T1 | T2 |
| --- | --- | --- |
| t1 | 读取 stock=10 | |
| t2 | | 读取 stock=10 |
| t3 | 应用计算 10−1=9 | |
| t4 | | 应用计算 10−1=9 |
| t5 | `UPDATE inventory SET stock=9 WHERE id=1`，提交 | |
| t6 | | 同样写入常量 9，提交 |

最终库存为 9，两次各减一原本应得到 8。数据库可以正确串行执行这两个“写入 9”，却无法从这个常量推断应用真正要做两次扣减。较强隔离或显式冲突检查可能中止其中一笔，因此该时间线不能不加条件地推广到全部隔离级别。

对这个特定的单行库存问题，可将检查和扣减放进一条语句：

```sql
UPDATE inventory
SET stock = stock - 1
WHERE id = 1 AND stock > 0;
```

PostgreSQL 17 的 Read Committed 下，同一行有并发更新时，后来的更新者可能先等待；前者提交后，它会对更新后的行重新判断 WHERE，并基于适用的新行执行更新。上述两笔成功扣减可得到 10→9→8；若库存已为 0，后者不再匹配。应用仍须检查受影响行数，区分扣减成功与条件不满足。更高隔离级别下还可能需要处理序列化失败。[PostgreSQL 17 Read Committed 的 UPDATE 规则](https://www.postgresql.org/docs/17/transaction-iso.html#XACT-READ-COMMITTED)

这只把同一行的“检查并修改”放在一个数据库操作里，不自动保护“多件库存之和”“至少一人值班”等跨行条件。

### Write Skew：写不同的行仍破坏共同条件

写偏差（Write Skew）关注的是读取条件与不同记录上的写入相互影响。以下为 PostgreSQL 17 Repeatable Read 的教学调度；假设表 `duty(doctor, on_call)` 初始有 A、B 两行且都为 true，没有额外约束或显式保护共同条件的锁：

| 时刻 | T1 | T2 |
| --- | --- | --- |
| t1 | `BEGIN ISOLATION LEVEL REPEATABLE READ` | 同样开始事务 |
| t2 | `SELECT count(*) FROM duty WHERE on_call`，得到 2 | 同样查询得到 2 |
| t3 | 应用判断人数大于 1，允许 A 下班 | 应用判断人数大于 1，允许 B 下班 |
| t4 | `UPDATE duty SET on_call=false WHERE doctor='A'` | `UPDATE duty SET on_call=false WHERE doctor='B'` |
| t5 | COMMIT 可以成功 | COMMIT 也可以成功 |

两笔写没有更新同一行，因此单纯的写写冲突规则未必阻止它们。最终 A=false、B=false，违反“至少一名医生值班”。若按 T1→T2 串行执行，T2 应看到人数为 1 并拒绝下班；反向串行时 T1 应拒绝，因此两笔都成功的结果不等价于任一串行顺序。

![相同快照下的 Write Skew，以及 Serializable 的依赖检测与中止分支](/assets/notes/distributed-systems/dist-isolation-write-skew.svg)

换为 PostgreSQL 17 Serializable 并使有关事务遵守该协议后，数据库跟踪读写依赖：T1 对 B 值班状态的读取与 T2 对 B 的写入相冲突；T2 对 A 的读取又与 T1 对 A 的写入相冲突。检测到可能导致序列化异常的不安全结构时，至少需要使其中一笔不能成功提交；具体中止对象和时点不是应用应依赖的接口。

应用对被中止者重新执行**整个事务**。假设 T1 已提交、T2 重试，新的查询看到只有 B 值班，应保留 B。这里不是两笔先成功提交后再由数据库撤销其中一笔，而是可串行化路径阻止不安全历史全部成功。[PostgreSQL 17 Serializable](https://www.postgresql.org/docs/17/transaction-iso.html#XACT-SERIALIZABLE)、[Berenson 等，1995：快照隔离与写偏差](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)

## 3. 两阶段锁的两个阶段

基础 Two-Phase Locking 的增长阶段获取锁、缩减阶段释放锁，进入缩减后不再获取新锁。Strict 2PL 通常至少把排他锁保持到事务结束；把全部锁都保持到结束是更强的变体，不应不加说明地当成所有 2PL 的唯一定义。

它与 Two-Phase Commit 是不同机制：前者负责并发控制，后者负责原子提交。系统既可以同时使用二者，也可以采用其他并发控制机制配合 2PC。

死锁处理可使用受控锁顺序、检测和中止等策略。超时有助于解除等待，但中止必须有正确恢复机制；不能随意清理他人的锁来“修复”一致性。

两阶段锁（Two-Phase Locking，2PL）通过锁的获取、释放规则约束事务交错。下表采用区分 Strict 与 Rigorous 的术语约定；有些资料将更强的保持全部锁方案也简称为 strict，阅读时应核对实际释放规则：

| 类型 | 锁释放规则 |
| --- | --- |
| Basic 2PL（基础两阶段锁） | 先增长、后缩减；第一次释放锁后不再获取任何新锁 |
| Strict 2PL（严格两阶段锁） | 遵守两阶段规则，并将排他写锁保持到提交或中止 |
| Rigorous 2PL（严谨两阶段锁） | 将全部读写锁保持到提交或中止 |

```text
基础 2PL 教学例子：
增长：取得 A 的读锁 → 取得 B 的写锁 → 取得 C 的读锁
缩减：释放 A → 释放 B → 释放 C
一旦释放 A，不能再去申请 D 的新锁。
```

正确覆盖冲突访问范围的 2PL 保证冲突可串行化；范围查询可能还需要谓词或范围保护，不能仅锁已经存在的几行就声称覆盖所有插入冲突。Strict 2PL 保持写锁到事务结束，能防止其他事务读到尚未提交的写入，但仍可能死锁：T1 持有 A 等 B，T2 持有 B 等 A。锁顺序、死锁检测和中止恢复处理的是这类等待环，并不改变两阶段规则。[Eswaran 等，1976](https://jimgray.azurewebsites.net/papers/On%20the%20Notions%20of%20Consistency%20and%20Predicate%20Locks%20in%20a%20Database%20System%20CACM.pdf)、[Berenson 等，1995 §3 的锁与持续时间](https://www.microsoft.com/en-us/research/wp-content/uploads/2016/02/tr-95-51.pdf)

### 2PL 与 2PC 分属不同层次

| 比较项 | 2PL | 2PC |
| --- | --- | --- |
| 英文与中文 | Two-Phase Locking，两阶段锁 | Two-Phase Commit，两阶段提交 |
| 主要职责 | 并发控制 | 分布式原子提交 |
| 解决问题 | 多事务交错执行中的冲突 | 多资源接受同一个提交或中止决定 |
| 主要机制 | 获取锁、释放锁 | Prepare、Commit、Abort |
| 能否独立完成跨库原子提交 | 不能 | 在相应持久化与恢复协议下协调完成 |

例如某分布式事务访问数据库 A、B：各库可用 2PL 管理本地冲突，外部协调者再用 2PC 统一提交决定。也可以采用 MVCC 等其他并发控制与 2PC 组合；并发隔离和原子提交必须分别分析。下一章将解释 Prepared 期间为何仍要保留资源。

## 4. 乐观控制与 MVCC

乐观控制通常允许先计算，在提交时验证冲突；验证失败需要重试或返回失败。它也有记录版本、验证和争用成本，不等于完全没有锁或协调。

MVCC 保存适用的多个版本，让读取按可见性规则选择；它本身不是固定隔离级别。PostgreSQL 17 的 Repeatable Read 采用快照隔离，Serializable 增加对不能串行化的依赖的检测，并可能要求重试。[PostgreSQL 17 隔离说明](https://www.postgresql.org/docs/17/transaction-iso.html)

多版本并发控制（Multi-Version Concurrency Control，MVCC）保存适用的旧版本，让并发读取根据快照（Snapshot）选择可见数据。例如余额从 100 改为 80 后提交，已经持有旧快照的事务仍可能需要看到 100，旧版本不能仅因新写提交就立即删除。

在 PostgreSQL 17 中，Read Committed 的两次普通 SELECT 可以先后取得不同快照，因而可能先读 100、再读 80；Repeatable Read 固定适用的事务快照，可继续看到原来的版本。快照不是按墙钟时间简单筛选行，而是结合事务状态、本事务修改等规则判断可见性。快照隔离（Snapshot Isolation，SI）因此能稳定观察，却仍不能排除上一节修改不同记录的 Write Skew。[PostgreSQL 17 MVCC 与隔离级别](https://www.postgresql.org/docs/17/mvcc-intro.html)

PostgreSQL 17 使用可串行化快照隔离（Serializable Snapshot Isolation，SSI）增加依赖检测。它以 SIREAD 谓词锁记录适用的读范围和依赖线索，在 `pg_locks` 中可看到 `SIReadLock`。这些锁主要用于冲突检测，**不以普通排他锁的方式阻塞写入**；数据库仍会使用其他必要锁，但 Serializable 并不是“把查询涉及的所有行都锁成排他”。

检测到可能形成序列化异常的结构时，SSI 可以保守地中止事务，应用必须准备重试；不能把每次中止都理解为已证明存在一个最终发生的业务错误。SIREAD 的粒度还受查询计划与内部合并等因素影响，不保证恰好一条谓词对应一把独立锁。[PostgreSQL 17 SSI 与谓词锁](https://www.postgresql.org/docs/17/transaction-iso.html#XACT-SERIALIZABLE)

## 5. 以事务为单位重新读取与执行 {#_5-重试的单位应是什么}

如果数据库中止了整个事务，通常需要重新读取并执行整个事务，而不是只重发失败的最后一条语句。重试期间如果已经调用不可回滚的外部支付或邮件接口，就会引入重复副作用。

教学设计示例：在本地事务里记录“需要发邮件”的 outbox，而不是直接发完邮件后假定事务不会回滚；消费者再次执行也要幂等。第 22 章展开这种跨边界设计。

## 6. 根据冲突范围与业务不变量选择 {#_6-怎么选-不靠-读多写少-一句话}

选择时，需要评估冲突范围、事务持续时间、热点、不变量、允许的重试量和尾延迟。悲观控制可能增加等待，乐观控制则可能产生无效重算；不能脱离具体实现断言哪一种更快。本章未提供压测数据，也未修改任何数据库的隔离参数。

前一章的 [WAL 与崩溃恢复](/articles/distributed-transactions-wal.html) 处理一台数据库怎样恢复状态；本章处理并发观察与不变量；下一章的 [2PC](/articles/distributed-two-phase-commit.html) 处理多个事务资源怎样接受统一决定。这些机制能组合使用，职责不能互换。

[返回本册目录](/collections/distributed-systems/)
