---
id: distributed-zookeeper-watch
title: 第十四章 ZooKeeper Watch、配置发布与版本校验
description: "Watch 在相关状态变化时通知客户端重新观察。典型处理顺序是读取并注册、收到通知、重新读取，再按需要注册和协调。配置读取和锁管理依赖最新对象状态，通知本身只提供变化线索，不保存完整的逐变更历史。"
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
order: 14
---

# 第十四章 ZooKeeper Watch、配置发布与版本校验

> 阅读标签：ZooKeeper3.9.3 Watch与对象生命周期。

Watch 在相关状态变化时通知客户端重新观察。典型处理顺序是读取并注册、收到通知、重新读取，再按需要注册和协调。配置读取和锁管理依赖最新对象状态，通知本身只提供变化线索，不保存完整的逐变更历史。

## 1. 传统 Watch 是一次性触发

通过适用的 exists、getData 或 getChildren 读取并注册传统 Watch，可以把观察与注册组合在一次接口操作里，减少“先读后注册”之间遗漏变化的窗口。不同接口关注的数据、存在性或子列表变化不同。

![通知、重读与重新协调](/assets/notes/distributed-systems/dist-watch.svg)

触发后应按需要重新读取并注册。两次观察之间可能发生多个变化，回调不是逐变更历史；断连时也不能假定所有创建再删除都必然逐项通知。ZooKeeper 3.6+ 另有持久、递归 Watch，不能把传统一次性规则不加区分地套用过去。[3.9.3 Watch 语义](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkWatches)

观察通知（Watch）让服务器在适用变化发生后异步提醒客户端，减少反复轮询；通知通常只告诉客户端事件类型与路径，业务状态仍需重读。读取并注册意味着“取得这次观察结果，同时为其后的适用变化设置通知”；若先普通读取，再另行注册，变化可能恰好发生在中间，客户端就不能假设缓存仍然新鲜。

以下是传统 Watch 的教学时序，v1～v3 表示该例连续的数据版本：

```text
T1  getData("/config", watch=true)：读取 v1，同时注册
T2  数据更新为 v2：触发 Watch，服务器移除这份一次性注册
T3  数据又更新为 v3：尚未重新注册，不必再有第二条通知
T4  客户端收到 T2 的通知，重读并注册，结果已经是 v3
```

T4 的回调不能当成“恰好执行一次 v1→v2 的业务动作”。它要求客户端按当前 v3 重新协调，不能靠通知重建完整的中间历史。需要逐事件处理的业务应另行使用具有相应持久化与消费协议的事件系统。

### 三个读取 API 的触发范围

| 注册方式 | NodeCreated | NodeDeleted | NodeDataChanged | NodeChildrenChanged |
| --- | --- | --- | --- | --- |
| `exists(path, watch)` | 原先不存在的节点被创建 | 已存在节点被删除 | 本节点数据改变 | 不触发 |
| `getData(path, watch)` | 不触发 | 本节点被删除 | 本节点数据改变 | 不触发 |
| `getChildren(path, watch)` | 不触发 | 本节点被删除 | 不触发 | 直接子节点列表改变 |

`exists` 可以在目标不存在时留下存在性 Watch；`getData`、`getChildren` 在目标不存在时返回 `NoNode`，不能按成功读取已注册来处理。`getChildren` 观察的是子列表，不会自动收集每个子节点的数据变更，更不保存全部后代的更新历史。[3.9.3 Semantics of Watches](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkWatches)

### 一次性、持久与递归 Watch

| 类型 | 注册与持续性 | 范围与处理 |
| --- | --- | --- |
| 标准 Watch（Standard Watch） | 通过适用读 API 注册，触发后移除 | 通知后用读取并注册重新观察 |
| 持久 Watch（Persistent Watch） | `addWatch` 注册，触发后仍保留 | 观察指定路径的适用事件，仍须读取当前状态 |
| 持久递归 Watch（Persistent Recursive Watch） | `addWatch` 选择递归模式 | 覆盖注册路径及适用后代的创建、删除、数据变化事件；不触发 `NodeChildrenChanged`，避免与后代事件重复 |

后两种模式在 3.6 引入，这里按 **3.9.3** 语义讨论。持久 Watch 的“持久”表示注册不会因触发自动移除，不表示断连期间存在供应用任意回放的可靠事件日志。其余顺序与通知保证仍按文档解释；应用重建新会话时也须恢复所需注册。[3.9.3 Persistent, Recursive Watches](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkWatches)

## 2. 通知后的重读与任务分发 {#_2-收到通知之后怎样处理}

以下为应用层教学状态机，不绑定某个 Java/Python 客户端版本，也不是完整生产实现：

```text
首次连接 / 同一会话重连：
    进入待协调状态，安排一次 reconcile
reconcile（同一对象串行执行）：
    若连接不可用或会话失效：保持保守模式，结束本次调度
    标准 Watch：读取数据与 Stat，同时注册 Watch
    持久 Watch：先确保注册成功，再读取数据与 Stat
    若目标不存在：按协议改用 exists Watch 或处理删除状态
    校验对象世代、数据版本和内容完整性
    根据当前状态重新计算，原子替换适用的本地状态
    若运行中又收到通知：标记 dirty，至少再协调一次
收到变化通知：
    标记 dirty，向有界工作队列提交或合并 reconcile 任务
Disconnected：暂停依赖新鲜状态或当前资格的动作
同一会话恢复连接：核对状态及所需 Watch，重读后再恢复业务
Expired：丢弃旧会话、旧资格及相关任务；新会话中重新注册和读取
```

回调中应避免执行无界慢操作，以免阻塞后续通知。将变更线索交给受控工作队列，再依据最新状态重新计算，通常比每收到一次通知就无条件执行一次业务动作更容易恢复。

合并通知时不能把“任务运行中”当成忽略后续通知的理由：dirty 标记需要与任务调度协调，避免恰好漏掉最后一次变化；并发读结果也不应把较新的本地版本覆盖成较旧版本。短暂断连不自动结束会话，过期则彻底结束旧身份，区别见[第十三章的会话生命周期](/articles/distributed-zookeeper-zab.html#_4-会话失联与会话过期)。客户端库会按其规则恢复适用 Watch，应用仍应重读，特别是断连期间“创建后又删除”的存在性变化可能无法完整观察。[3.9.3 Watch 与 Sessions](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkWatches)

## 3. 用对象版本约束条件更新 {#_3-条件更新如何防止丢失修改}

两个客户端都读到计数 10，若直接 setData(11)，会丢失一次增加。对**同一个未被删除重建的znode**，带版本条件可使仍与读取版本匹配的更新成功，失败方重新读取并有界重试。

同路径删除重建会带来 ABA（A→B→A，表面条件恢复而对象身份已改变）问题。教学时间线如下，czxid 使用简化数字：

| 时点 | 操作 | 对象身份与状态 |
| --- | --- | --- |
| T1 | A 读取 `/counter` | 世代 G1：data=10，version=0，czxid=100 |
| T2 | B 删除 `/counter` | G1 结束 |
| T3 | B 在同路径重新创建 | 世代 G2：data=20，version=0，czxid=200 |
| T4 | A 以旧读值计算后执行 `setData("/counter", 11, version=0)` | 新 G2 的版本也匹配 0，迟到操作可能成功覆盖 20 |

version=0 无法区分 G1、G2。原生比较并交换（Compare-And-Set，CAS）在这里比较的是路径当前节点的数据版本，路径相同、版本相同不代表仍是原对象。

`czxid`可帮助识别创建世代，但普通setData的version参数不同时原子检查czxid；先读czxid再setData仍有竞态。教学起点可约定权威控制节点在生命周期内不删除重建，只更新数据版本；确需重建时，应设计不被随意重置的权威代际或唯一版本路径，并明确原子校验边界，而不是随便增加一个字段。

这一反例由[ZooKeeper 3.9.3 setData契约](https://zookeeper.apache.org/doc/r3.9.3/apidocs/zookeeper-server/org/apache/zookeeper/ZooKeeper.html)及[release-3.9.3 DataTree.createStat](https://github.com/apache/zookeeper/blob/release-3.9.3/zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java)中新对象版本初始化规则推导，未运行服务。

这种方式并不自动得到高吞吐计数器：热点冲突会带来重试，连接丢失还可能导致更新结果未知。版本失败、权限失败和连接失败需要分别处理，不能一概认为“重试即可”。

解决方案要连同前提一起选择：关键权威节点可由 ACL 和管理流程禁止删除重建，仅使用数据版本做 CAS；不可变对象可使用不复用的版本路径，让旧请求仍指向旧身份；确需重建同一路径，则需可靠、不回退的代际来源，以及把世代判断与效果一起提交的原子协议。例如以永久权威节点的版本作为条件，在适用的 `multi(check, …)` 中保护同一 ZooKeeper 原子边界，且所有变更者都须遵守协议。单独加一个 generation 字段、先读一次 czxid，或仅用 `multi` 检查会被重置的 version，均不足以自动解决跨世代竞态。

## 4. 从 Ready 标记到不可变版本发布 {#_4-ready-文件为什么不是通用原子发布}

“删除 ready → 更新多个节点 → 重建 ready”可以提示发布阶段，但各次读取之间仍有时间间隔：读者可能先看到旧 ready，再读到混合配置；Watch 也可能在使用后才到达。要保持一套配置的版本身份，需要在发布与读取协议中共同约束。

本章采用的教学方案是：写入不可变配置版本 v7，验证完整后，只切换一个 current 指针；读取者固定版本后读该版本下的内容。不变的是一整套配置的版本身份，而不是每读一项都重新追最新。

```text
/app/config/
    current = "v7"
    versions/
        v6/
            db
            cache
        v7/
            db
            cache
```

发布者准备 v8 时，协议按以下顺序执行：

1. 分配不复用的版本 ID，创建 `versions/v8`，写入全部 db、cache 及完整性清单；发布前还可修正，发布后内容不可变。
2. 验证必需项、格式、交叉引用与适用摘要。当前读者仍固定在 v7，不读取尚未发布的 v8。
3. 读取永久 `current` 节点及其版本；以条件 `setData` 原子地把指针从预期版本切换到 `v8`。并发发布者遇到 `BadVersion` 必须重新决策。
4. 若连接丢失导致结果未知，查询权威发布状态并核对版本或发布标识；并发发布下当前值本身未必能还原全部历史，必要时结合原子发布记录。不要把超时直接当作“未发布”而重复切换。
5. 按读者保留协议回收旧版本；失败且从未发布的草稿也须确认不再被使用后清理。

读取者则读取 `current`，在这次加载中固定得到的版本 ID，比如 v7；只读 `versions/v7` 内全部内容，验证完整后一次性替换本地生效配置。即使此时指针已改为 v8，也不能把 db 取自 v7、cache 又取自 v8。Watch 只负责调度下一次完整加载；加载工作还应串行化或校验代际，防止较早任务晚完成后覆盖更新结果。

![不可变配置版本、current 原子切换与读取者固定版本](/assets/notes/distributed-systems/dist-config-versions.svg)

这里的一致配置来自“不变内容 + 单个指针 + 固定版本读取”的应用约束，并非跨多个 `getData` 自动获得事务快照。ready 标记即使保持为真，也无法阻止其他人继续逐项改动内容；若同时缺少不可变和读取约束，仍会读到混合配置。该协议也不承诺普通读的指针必然是全局最新值，读路径的新鲜度边界沿用[第十三章](/articles/distributed-zookeeper-zab.html#_5-读到旧值不是随便读什么都正确)。

## 5. 大内容、版本回收与失败恢复 {#_5-发布协议还要补哪些边界}

配置数据很多时不一定能放进一次 multi；大内容可存外部对象，ZooKeeper 只保存经验证的版本引用。对有限更新，multi/check 等构件可以保护适用的检查与更新，但不能覆盖外部文件原子性。

旧版本回收需要确认没有仍在使用的读者或有适用保留期；切换超时需要查询 current 的事实状态；回退应切回一个完整版本，不直接修改已被读取的不可变内容。这是应用发布协议，不宣称 ZooKeeper 自动实现了这些步骤。

配套构件可参照 [ZooKeeper 3.9.3 Recipes](https://zookeeper.apache.org/doc/r3.9.3/recipes.html)。

旧版本仍可能被已固定该版本的读者加载或使用。可靠回收可使用可证明的读者引用协议或覆盖最大使用期的保留策略；若没有读取时长上界，随意保留几秒并不能证明安全。读取缺项时应保留原有完整配置或重新开始一次完整加载，不能公布半套内容。回滚只把 current 指回仍完整保留的 v7，也要做条件切换，不能原地修改已经公开的 v8。

错误处理应按含义分类，以下名称采用 ZooKeeper 3.9.3 API 的错误概念：

| 错误 | 含义与处理方向 |
| --- | --- |
| `NodeExists` | 创建目标已存在；核对其身份、内容和当前协议阶段 |
| `NoNode` | 目标或父节点不存在；区分尚未发布、已删除、回收或 Watch 观察对象消失 |
| `BadVersion` | 条件版本不匹配；重读后重新计算，按限额处理冲突 |
| `ConnectionLoss` | 连接丢失，操作结果可能未知；恢复连接后查询、核对身份与操作记录 |
| `SessionExpired` | 旧会话终止；丢弃旧临时身份，重新建立所需状态 |
| `NoAuth` | 权限不足；修复授权或调用方式，无条件重试无益 |

上述发布目录、完整性清单、恢复记录与回收步骤是应用协议，不是 ZooKeeper 自动附带的功能；`multi` 也只覆盖支持的 ZooKeeper 操作。[3.9.3 API 与错误契约](https://zookeeper.apache.org/doc/r3.9.3/apidocs/zookeeper-server/org/apache/zookeeper/ZooKeeper.html)

下一章把“通知后重读并核对资格”用于[排队锁的前驱监听](/articles/distributed-locks-leases-fencing.html)，再讨论会话过期后仍在运行的工作者。

[返回本册目录](/collections/distributed-systems/)
