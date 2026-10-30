---
id: distributed-zookeeper-zab
title: 第十三章 ZooKeeper 架构、Zab 与数据模型
description: "ZooKeeper 为多个进程提供共享的协调状态，适合保存配置、成员和少量控制信息。应用可以组合有序更新、版本校验与通知等构件完成协调。"
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
order: 13
---

# 第十三章 ZooKeeper 架构、Zab 与数据模型

> 阅读标签：ZooKeeper3.9.3 API与Zab模型。

ZooKeeper 为多个进程提供共享的协调状态，适合保存配置、成员和少量控制信息。应用可以组合有序更新、版本校验与通知等构件完成协调。本章先看会话和写入路径，再介绍 znode 与常用 API，版本参照 3.9.3。

## 1. 会话、Zab 与有序更新 {#_1-底层不是-raft}

![客户端会话与有序写入](/assets/notes/distributed-systems/dist-zk.svg)

ZooKeeper 使用 Zab 路线的原子广播协调写入，与 Raft 都涉及领导者和复制，但不是“ZooKeeper 就是一个 Raft 框架”。协议的恢复与顺序约束应按各自资料阅读。[ZooKeeper 3.9.3 内部原子广播](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html#sc_atomicBroadcast)

客户端连接到服务节点，写入通过适用路径协调，普通读取可以在所连节点服务。写入顺序与客户端会话保证，不等于不同客户端同时读到完全相同的最新数据。

### 集群中的角色

服务集群称为 Ensemble；客户端（Client）通过会话连接其中一台服务节点。以下教学部署有三个投票成员 A、B、C，另加非投票的 O：

| 角色 | 示例 | 职责 |
| --- | --- | --- |
| 领导者（Leader） | A | 协调事务提案、复制和提交 |
| 跟随者（Follower） | B、C | 参与选举和提案确认，学习并应用有序更新，也服务客户端 |
| 观察者（Observer） | O | 学习提交结果，服务普通读并转交写请求，不计入投票多数 |
| 法定人数集合（Quorum） | A、B，或 A、C 等 | 本例三个投票成员中至少两个；不是包括 O 后按四台机器重新计算 |

客户端连到 B 时，普通读通常直接读取 B 的本地数据树；写操作则沿请求转交路径交给 A 协调。连到 O 也能发送适用的读写请求，O 不会因此变成投票者。实际部署还支持其他 Quorum 配置，本章只用默认多数模型。[3.9.3 Observer Guide](https://zookeeper.apache.org/doc/r3.9.3/zookeeperObservers.html)、[Internals：Quorums](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html)

ZooKeeper 保存的是供多个进程共同判断的少量控制状态，例如配置版本、服务成员和锁队列。每次更新要经过复制与有序应用，大对象会增加网络、存储和处理延迟；大规模业务内容适合存入对象存储或数据库，ZooKeeper 保存引用及协调元数据。[3.9.3 Data Access](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkDataModel)

### 正常写入：提案、确认与提交

Zab（ZooKeeper Atomic Broadcast，ZooKeeper 原子广播协议）管理的是有序提案流。提案（Proposal）是需要成员达成一致的单元；ACK 是服务器记录提案后的确认；COMMIT 表示该提案可以按顺序提交、交付给状态机。以下假设 A 已完成激活，客户端通过 B 执行 `setData("/config/payment", "v7", version)`：

1. B 收到请求，按写路径转交 A；普通写不能只修改 B 的本地树就返回成功。
2. A 检查请求并形成事务提案，分配 zxid，例如 `(3,10)`，向 Follower 按相同顺序发送 Proposal。
3. B、C 按顺序接收并依协议记录提案，满足持久记录条件后返回 ACK。A 自己的记录也参与本例的多数判断。
4. 当 A 确认包括自己在内已有有效 Quorum 记录提案，例如 A、B 两台，便按序发送 COMMIT；C 可以稍后追上。
5. 副本按相同事务顺序提交并应用更新。连接客户端的 B 在相应提交、应用处理完成后返回 API 操作结果；这不要求所有副本同时完成。

ACK 与 COMMIT 之间可能隔着等待、故障和恢复，记录提案并不代表本地已经应用。FIFO（First In, First Out，先进先出）通道和顺序处理使后一个提案的确认、提交不能随意越过前面的提案；全体副本才能把相同更新流应用为相容历史。多数交集配合激活恢复约束，使新领导者能够继承已提交历史，单靠“有人回 ACK”还不够。[3.9.3 Internals：Atomic Broadcast / Active Messaging](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html#sc_atomicBroadcast)

正常广播有提案和提交两个阶段，但 Zab 还包括领导者切换、历史恢复与有序流约束，不能完全等同于跨数据库的经典两阶段提交，也不采用 Raft 的全部规则。

### Leader Activation：当选后先恢复历史

领导者激活（Leader Activation）建立新 Leader 的安全历史与新 epoch，之后才进入正常消息广播（Active Messaging）。依据 3.9.3 Internals 的协议说明，新 Leader 与跟随者同步缺失提案，落后过多时可用完整状态快照；迟到成员持有而选举 Quorum 未见的未提交后缀可能被丢弃。新 Leader 自己继承的未提交提案也可能在激活中提交，不能把“未提交”一概解释为必须删除。

教学分支如下，数字均为 zxid，不是 API 返回的实测记录：

| 时点 | A：旧 Leader | B | C |
| --- | --- | --- | --- |
| 故障前 | `(3,10)` 已提交；另有仅在 A 的 `(3,11)` | 已记录并应用到 `(3,10)` | 已记录并应用到 `(3,10)` |
| A 故障 | 暂不可达 | 与 C 形成选举 Quorum，B 当选 | 支持 B，并参与同步 |
| 激活 | 暂不参与 | 以包含已提交 `(3,10)` 的历史同步成员，建立 epoch 4 | 完成相应历史同步 |
| 激活成功后 | 若回来，须按恢复协议丢弃旧的私有 `(3,11)` 后缀 | 正常提案可从 `(4,1)` 继续 | 学习新的有序更新 |

本例 B 能当选的前提是参与选举的历史满足协议选择规则；不是任选一台最落后的服务器直接接管。旧已提交事务被旧 Quorum 记录，新选举 Quorum 与它相交，选举对历史的选择和后续同步共同保护该前缀。

文档把跟随新 Leader 的特殊提案称为 `NEW_LEADER`：它不承载普通业务消息。Follower 完成同步后才确认它；新 Leader 得到适用 Quorum 的确认并提交它，才完成激活、接受新的正常提案。如果激活无法得到 Quorum，应重新选举。以上是官方 Internals 的协议层描述，不把这些名称当成客户端字段或完整抓包格式。[3.9.3 Leader Activation 与 Summary](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html)

### zxid 的时代与顺序

ZooKeeper 事务 ID（ZooKeeper Transaction ID，zxid）可写为 `(epoch, counter)`：epoch 区分领导者时代，counter 表示该时代内的提案顺序。3.9.3 Internals 说明其实现采用 64 位编码，高 32 位为 epoch，低 32 位为 counter。

```text
(3,10) → (3,11) → (4,1)
同一 epoch 内 counter 递增；epoch 4 的事务排在 epoch 3 之后。
```

zxid 不是墙钟时间，也不是不同独立 ZooKeeper 集群间可直接比较的全局 ID。它描述事务顺序；`version` 描述某个 znode 的数据修改次数；Sequential 后缀是父节点范围内的命名计数，三者用途不同。[3.9.3 Internals：zxid](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html#sc_atomicBroadcast)

## 2. znode 是有路径的协调对象

路径类似文件系统，znode 既可以保存少量数据，也可以拥有子节点；但它不是普通磁盘文件接口。dataVersion、子节点版本和 ACL 版本具有不同用途，不能把所有变化都解释成同一个 version 加一。

| 常见类别或选项 | 主要含义                                    |
| -------------- | ------------------------------------------- |
| Persistent     | 除非被删除，否则不会随会话结束自动消失      |
| Ephemeral      | 与创建会话绑定，会话过期后由服务清理        |
| Sequential     | 创建时追加序号，可与适用的持久/临时模式组合 |

这三项并非互斥且穷尽的类别。Container、TTL 节点等还各有使用条件；顺序后缀也有其作用域与计数限制，不能视为适用于所有业务的永久全局唯一标识。临时节点通常不能有子节点。[3.9.3 数据模型](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkDataModel)

```text
/config/payment                 Persistent：配置持续存在，直到显式删除
/services/worker/worker-01      Ephemeral：随创建会话结束而清理
/locks/task/lock-0000000007    Ephemeral Sequential：会话绑定，同时自动命名
```

临时节点（Ephemeral）不允许拥有普通子节点。顺序选项（Sequential）可以与适用的持久或临时创建模式组合，并非与它们互斥的独立类别。后缀计数属于父 znode，3.9.3 文档规定使用 4 字节有符号整数，超过 `2147483647` 会溢出为负数；父路径重建也可能破坏旧计数连续性。因此排序、身份和长期令牌方案都要明确作用域与生命周期。

容器节点（Container）在最后一个子节点删除后成为后台清理候选，应用随后创建子节点时要处理 `NoNode` 并按协议重建容器。TTL（Time To Live，存活时间）节点只适用于相应持久创建模式，需要服务端启用；在指定时间内未修改且无子节点时才成为清理候选，不是保证到点瞬间删除的会话租约。[3.9.3 Sequence / Container / TTL Nodes](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkDataModel)

节点元数据由 `Stat` 返回，常用字段如下：

| 字段 | 表示什么 | 典型用途 |
| --- | --- | --- |
| `version` | 本节点数据版本 | `setData` 的条件更新 |
| `cversion` | 子节点变化版本 | 判断子列表是否变化 |
| `aversion` | ACL（Access Control List，访问控制列表）版本 | 条件修改访问控制 |
| `czxid` | 创建本节点的事务 zxid | 识别同一路径的创建世代 |
| `mzxid` | 最近修改本节点数据的事务 zxid | 定位数据更新历史 |
| `ephemeralOwner` | 临时节点所属的会话 ID；非临时节点为 0 | 判断是否属于预期会话 |

一次 `setData` 不会让所有版本字段同时递增，也不会改变节点的创建 zxid。数据、子列表和 ACL 的变化各有对应元数据；`czxid` 可用于观察创建身份，但后文的普通版本 CAS 不会顺带原子校验它。[3.9.3 Stat Structure](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#sc_zkStatStructure)

## 3. API 返回状态与条件更新 {#_3-api-的成功与错误不能二分为-存在-不存在}

create 的 NodeExists 与连接丢失不同：前者给出具体冲突，后者可能意味着创建成功但响应未到。delete、setData 的版本参数用于条件检查；指定忽略版本的用法会放弃相应并发保护。

exists、getData、getChildren 有各自返回值与 Watch 语义。multi 可组合支持的操作，构成一个原子的 ZooKeeper 更新；它不是对外部数据库和文件系统的跨系统事务。

## 4. 会话失联与会话过期

短暂断开连接，不意味着临时节点立即删除，也不保证原会话永久保留。客户端需处理连接状态变化；会话过期后，不能再将旧节点、旧锁或本地缓存视为有效资格。

纸面推演：A 失联但线程仍运行，服务端最终使会话过期并删除临时节点，B 获得下一份资格。A 恢复时必须停止以旧资格工作；外部资源还需 fencing 等机制阻止迟到写入，详见第 15 章。

把断连与过期拆开，可得到两个不同的教学分支：

| 步骤 | 连接、会话与临时节点 |
| --- | --- |
| 1 | A 在有效会话中创建临时节点，B 等待相应资格 |
| 2 | A 收到 Disconnected，表示连接丢失；节点不因此立即消失 |
| 3a：及时恢复 | A 以原会话重新连接，收到适用的 Connected 通知；重读并核对状态后继续，B 尚不能仅凭 A 曾断连取得资格 |
| 3b：会话过期 | 服务端判定会话失效并清理临时节点，B 经应用协议重新判断后获得新资格 |
| 4b：A 恢复 | A 得知 Expired，旧会话不可复用，必须建立新会话；旧节点和旧锁身份全部失效 |

这里的 Connected 是连接状态的通称，Java Watcher 的正常可读写连接事件使用 `SyncConnected`。服务端可以在客户端仍失联时判定过期，A 未必及时收到 Expired 通知；业务线程更不会被服务端强制终止。具体超时以会话协商和服务端判定为准。[3.9.3 Sessions](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkSessions)

外部数据库如何拒绝旧线程的迟到写入，见[第十五章的资源端 fencing](/articles/distributed-locks-leases-fencing.html)。

## 5. 普通读、会话视图与同步条件 {#_5-读到旧值不是随便读什么都正确}

文档定义同一会话的系统视图等保证，同时提醒跨客户端的普通读可能不同。sync 后按顺序发读是文档给出的客户端同步工具，但不能缩写成“任意客户端加一次 sync，所有未来读取永远最新”。应保留成功回调、会话与故障条件。[一致性保证](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkGuarantees)

zxid 可用于理解事务顺序；客户端 API 的参数与网络消息格式，仍需按所用客户端和协议实现分别查阅。

3.9.3 Internals 对边界作了更明确的说明：事务写入具有线性一致的顺序，普通读不是 Quorum 操作，可能读到所连副本的较旧状态。ZooKeeper 保持同一客户端的操作顺序与相容的会话视图；这不要求不同客户端在同一墙钟时刻观察到同一进度。

例如 X 通过 A 写入 `v7` 并收到成功，Y 通过尚未应用该更新的 C 普通读取，仍可能读到 `v6`。这已经说明全部普通读并不具有实时线性一致性；不能用 Zab 对写入排序的保证代替读路径分析。

`sync()` 可用来推进连接节点的同步，再在成功回调后按顺序读取，但 **3.9.3 Internals 明确指出 sync 本身不是 Quorum 操作，不能严格保证总是读到最新值**。其反例涉及两个节点暂时都认为自己是 Leader，sync 被旧权威服务。真正的 Quorum 操作与随后有序读取提供更强保证，具体方案需按协议及 API 错误处理设计，不能把 `sync + getData` 无条件命名为完整 Quorum Read。[3.9.3 Internals：Consistency Guarantees](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html#sc_consistency)

这些协调构件如何用于配置变化，见[第十四章的 Watch、对象世代与不可变版本发布](/articles/distributed-zookeeper-watch.html)。

[返回本册目录](/collections/distributed-systems/)
