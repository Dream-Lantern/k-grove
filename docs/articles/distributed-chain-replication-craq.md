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

原始链复制由 Tail 回复客户端；CRAQ 论文实现为了复用客户端 TCP 连接，由确认沿链返回后让 Head 回复。两者要按抽象与实现分别描述，不能把“只能由 Tail 直接回复”当作不变接口。[CRAQ 2009 §2.2](https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf)

链复制（Chain Replication，CR）将同一对象的副本排列为有序链，头节点（Head）接收更新，经各后继逐步传递，尾节点（Tail）接收并处理后定义提交状态。基础 CR 的查询直接到 Tail，让它在同一个对象上为读写建立顺序：

```text
写：Client → Head A → B → Tail C
基础 CR 的读：Client → Tail C → Client
基础 CR 的写回复：Tail C → Client
CRAQ 论文实现的写回复：C → B → A → Client
```

读取 Head 的未提交新值可能让不同客户端观察到互相矛盾的进度；基础协议用 Tail 集中读来避免这个问题。CR 2004 的服务语义针对单个对象，不自动提供多个对象同时提交的事务。[CR 2004 §2～3](https://www.usenix.org/legacy/event/osdi04/tech/full_papers/renesse/renesse_html/)

## 2. 用 clean/dirty 状态选择读取路径 {#_2-craq-怎样安全地分散读}

[![CRAQ：写传播与读选择是两条不同路径](/assets/notes/distributed-systems/dist-craq.png)](/assets/notes/distributed-systems/dist-craq.png)

节点可保留对象的多个版本。新写到达非 Tail 节点时先标 dirty；到达 Tail 后提交并产生反向确认，节点收到确认将对应版本标 clean。

若对象处于适用的 clean 状态，可以在本地直接返回；若存在 dirty 新版本，则向 Tail 查询当前已提交版本号，再返回相应版本。dirty 不是损坏，而是本节点尚不能仅凭本地状态确定提交边界。

CRAQ（Chain Replication with Apportioned Queries，分摊查询的链复制）通过多版本和提交状态，让读多写少时的查询分布到不同副本。Clean（已确认提交）和 Dirty（本地尚未确认提交）是**版本状态**，不是校验结果或磁盘是否脏：

| 阶段               | 非 Tail 节点                             | Tail                               |
| ------------------ | ---------------------------------------- | ---------------------------------- |
| 初始已提交 v5      | v5 Clean                                 | v5 Clean                           |
| 收到新 v6          | 保留 v5 Clean，添加 v6 Dirty，并前向转发 | 尚未收到时仍只有 v5                |
| v6 到达 Tail       | 在确认到达前仍可能标 Dirty               | 将 v6 标 Clean，提交并发出反向 ACK |
| ACK 逐节点向前传播 | 把对应 v6 标 Clean，可回收其之前的旧版本 | v6 已提交                          |

强一致读的本地快路径要求**最新已知版本是 Clean**；仅仅存在一个旧 Clean 版本还不够。最新版本 Dirty 时，节点可能尚未收到 ACK，也可能写入确实还在途中，须向 Tail 发版本查询（Version Query），再从本地返回 Tail 指定的版本内容。为此，在获得安全的提交确认前必须保留必要旧版本；Tail 返回的是小的版本信息，不必把整个对象再传一遍。[CRAQ §2.3](https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf)

## 3. 用一次在途写入推演

教学例子：对象原为 clean v5，新写 v6 到达 Head，但尚未到 Tail。此时 Head 不能把 v6 当作已经完成的最新状态直接返回；它查询 Tail，Tail 仍可能确认 v5。随后 v6 到达并提交，新的读取按合法顺序观察 v6。

节点保留必要的旧版本，是为了在获知已提交版本后返回相应内容。如果立即删除所有旧版本，只留下未经确认的新对象，即使查询到版本号，也无法返回所需数据。

**场景 A：v6 尚未到 Tail。** 以下是独立的教学观察时刻 tA：

```text
A / Head：v5 Clean，v6 Dirty
B / Middle：v5 Clean，v6 Dirty
C / Tail：v5 Clean
```

Client 向 B 发起强一致读；B 不能擅自返回 Dirty v6，也不能直接假设旧 v5 仍是最新提交值。它查询 C，C 此刻确认最新提交为 v5，B 便从保留的本地版本返回 v5。

**场景 B：v6 已到 Tail。** 在后一个时刻 tB，C 接收 v6、标 Clean 并提交，ACK 由 C→B→A 反向传播。B 尚未收到 ACK 时若读到来，查询 C 将得到 v6，并返回自己的 v6；ACK 到达后，最新版本已 Clean，满足条件的后续读可以直接本地返回。A 与 B 的确认进度不必同时变化。

如果 C 回答版本 v6 后又提交 v7，而 B 稍后才把 v6 返回 Client，该读仍可排在 Tail 处理版本查询的时刻，位于 v7 之前；这笔并发写与读操作的时间区间重叠。强一致性不要求响应抵达瞬间再次追赶所有并发写。版本回收与读取也必须正确协调，不能把正在返回的对象内容先删掉。[CRAQ §2.3，版本查询后的说明](https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf)

### 按请求选择读取一致性

CRAQ 2009 §2.4 允许为读取标注一致性要求，准确名称与语义如下：

| 论文模式                                                                                | 返回版本与 Tail 查询                                            | 成本及分区边界                                                                                                   |
| --------------------------------------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| Strong Consistency（强一致，默认）                                                      | 最新已知版本 Clean 时本地返回；Dirty 时查询 Tail 的最新提交版本 | Dirty 查询增加往返；无法取得所需提交或配置权威时不能随意降级后仍称强一致                                         |
| Eventual Consistency（最终一致）                                                        | 可返回本节点已知的最新版本，包括 Dirty，不为每次读强制查询 Tail | 节省查询；换节点读取可能倒退，论文只在同一节点会话内维持相应单调观察                                             |
| Eventual Consistency with Maximum-Bounded Inconsistency（具有最大不一致界限的最终一致） | 允许读未提交新值，但偏差受本地时间或绝对版本号等界限约束        | 链可用时可能是比最新提交**更新**的版本；分区节点也可能比当前提交更旧；不是任意网络下永久可用且固定时限最新的承诺 |

第三种模式不是只给普通旧读增加一个标签；必须落实所选的界限规则及条件。论文跨数据中心方案还按是否指定主数据中心、是否具有全链多数等条件限制分区写入，不能只凭“节点还能收请求”就独立构造多个写链。这些保证主要针对对象级读写；论文讨论的事务扩展是另一个主题。[CRAQ §2.4、§3.1、§4](https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf)

## 4. 链成员变化与在途更新恢复 {#_4-链成员变化不只是删除一个数组元素}

Head、Tail 或中间节点故障时，链的前后关系与在途更新都需重建。中间节点可能接收了尚未转发的请求；新链需要依据确认状态补传，不能假设所有幸存节点天然具有相同进度。

配置管理器（Configuration Manager）提供配置权威；但一个权威存在，不代表旧节点和旧客户端已经收到新配置。配置代际、旧资格隔离、重试和网络分区必须共同处理。它自身也需要一致、可恢复的实现，不能说“因为只有一个角色决策，所以绝不会脑裂”。

### 原始 CR：故障模型与传播前缀

CR 2004 采用停止式故障（Fail-stop Failure）：故障服务器停止而不做错误状态转换，环境能检测其停止。它不等于任意网络分区中“超时就证明对方已停止”。论文以可靠配置管理服务 Master 组织变化，原型用 Paxos 复制该服务；这与 GFS 中名为 Master 的具体角色并非同一个系统。

正常 FIFO（First In, First Out，先进先出）传播使后继的已接收更新历史是前驱历史的前缀。反向确认使前驱能够删去已完成记录，并用 `Sent` 列表保留已转发但尚未获 Tail 确认的更新。故障时要恢复这些前缀和在途请求，不能只改链地址。

| 原链 A→B→C→D | 新链  | 恢复动作及未完成请求                                                                                                           |
| ------------ | ----- | ------------------------------------------------------------------------------------------------------------------------------ |
| Head A 故障  | B→C→D | 配置服务指定 B 为新 Head；仅存在 A、尚未转发的请求可能消失，未成功请求由客户端按语义处理重试；已传播部分继续完成               |
| Tail D 故障  | A→B→C | 指定 C 为新 Tail。C 的历史包含 D 的已提交前缀，也可能包含 D 尚未处理的更新；这些更新可在新 Tail 上完成，不是清空全部未确认请求 |
| 中间 C 故障  | A→B→D | 配置服务先通知后继 D，取得它最后收到的更新序号，再通知前驱 B；B 从 Sent 补传 D 缺失的有序后缀，之后才继续发送新接收的更新      |

例如更新 u7 已到 A、B、C，却未到 D，C 停止后 B 仍保存待确认记录。新连接 B→D 必须先把 u7 等缺失前缀补齐，不能直接跳到 u8。论文 Figure 3 的序号握手用于减少重复补传；没有这些状态，删除 C 可能悄悄丢失已被前驱接受的更新。[CR 2004 §3 Coping with Server Failures、Figure 3](https://www.usenix.org/legacy/event/osdi04/tech/full_papers/renesse/renesse_html/)

[![Chain Replication 三类故障、配置权威与在途更新恢复](/assets/notes/distributed-systems/dist-chain-reconfiguration.png)](/assets/notes/distributed-systems/dist-chain-reconfiguration.png)

在该 Fail-stop 模型中，被移除节点已停止；迁移到会恢复运行或发生分区的环境时，还要证明旧节点不再以旧 Head/Tail 服务，旧请求被拒绝、转发或重新定位，并使新链按安全条件生效。配置代际与隔离是这类实现的要求，不能冒充原论文已经给出了某种通用 token 字段。恢复期间可以暂停相关请求，强一致不等于切换零中断。

### CRAQ：ZooKeeper 配置与双向状态同步

CRAQ 2009 用 ZooKeeper 维护节点成员与链元数据，通过 Watch 获知相关变化，再由节点执行 CRAQ 的数据恢复。ZooKeeper 是配置管理依赖，不负责逐个对象的前向写入、Tail 提交或反向确认；它自身也需要可靠部署。论文中的成员临时节点应按会话语义理解：短暂断连不等于立即删除，相关机制见[第十三章](/articles/distributed-zookeeper-zab.html#_4-会话失联与会话过期)。[CRAQ §3.4、§5.1](https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf)

原始 CR 主要描述在 Tail 增加副本；CRAQ 采用分布式哈希表（Distributed Hash Table，DHT）组织节点布局，允许新成员在由此确定的其他位置加入，不能简化成普通链表插入。依据 §5.3，新节点需要从前驱接收前向传播（Forward Propagation），也可能从后继接收反向状态传播（Back-propagation）。后者不是仅一个 ACK，而是**最新 Clean 版本与所有更高的待确认 Dirty 版本**；恢复用前向传播也可传完整对象状态。

例如 X 进入原有 A→B 之间，对需要同步的对象，A 向 X 前传，B 向 X 反传相关完整状态；X 在与后继就该对象达成一致之前拒绝它的客户端读取。若恢复期间 B 又故障，还需要从新的后继继续恢复，不能因“已经收到一个最新值”就宣告完成。

节点退出也会触发两种方向的补传：前驱可能要补给新后继那些在故障节点上未转发的更新；后继可能要向新前驱补全因 ACK 丢失或此前反传中断而缺少的状态。论文固定长度链的 DHT 布局还可能改变原 Tail 的参与资格，因此上表是 CR 的简单缩链教学例子，不是 CRAQ 所有成员变化后的精确链集合。[CRAQ §2.5、§5.3](https://www.usenix.org/legacy/event/usenix09/tech/full_papers/terrace/terrace.pdf)

## 5. 结合负载比较复制与读取成本 {#_5-和-raft-比较时看负载-而不是判定谁永远更快}

链把逐节点传输成本分散出去，CRAQ 在读多、clean 比例高等条件下增加本地读机会；Raft 则以领导者日志复制和多数规则组织提交。两者的故障恢复、读路径与复制确认集合不同。

增加副本会同时增加存储与传播成本；写入频繁时 dirty 查询也会增加 Tail 压力。因此不写“副本数翻倍读吞吐必定翻倍”，更不把论文特定实验结果伪装成个人环境收益。

学习和验收时，除了无故障读写，还应覆盖新旧配置交接、dirty 期间的读取，以及失败请求重试。

[返回本册目录](/collections/distributed-systems/)
