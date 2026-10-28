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

## 2. 通知后的重读与任务分发 {#_2-收到通知之后怎样处理}

教学伪代码，省略实际客户端异常类型：

```text
连接可用且会话有效时：
    读取当前对象，同时注册所需 Watch
    校验版本、内容与本地缓存，按当前状态协调
收到通知：安排重读，不假定通知携带全部新数据
短暂失联：按业务策略暂停依赖新鲜状态的操作
会话过期：丢弃旧资格，重新建立会话及所需状态
```

回调中应避免执行无界慢操作，以免阻塞后续通知。将变更线索交给受控工作队列，再依据最新状态重新计算，通常比每收到一次通知就无条件执行一次业务动作更容易恢复。

## 3. 用对象版本约束条件更新 {#_3-条件更新如何防止丢失修改}

两个客户端都读到计数 10，若直接 setData(11)，会丢失一次增加。对**同一个未被删除重建的znode**，带版本条件可使仍与读取版本匹配的更新成功，失败方重新读取并有界重试。

反例是同路径的ABA：A读取`/counter`，version=0；B删除该节点并在同路径创建新节点，新对象version重新为0；A迟到的`setData(...,0)`可能匹配新节点。路径相同、版本相同，不代表仍是原对象世代。

`czxid`可帮助识别创建世代，但普通setData的version参数不同时原子检查czxid；先读czxid再setData仍有竞态。教学起点可约定权威控制节点在生命周期内不删除重建，只更新数据版本；确需重建时，应设计不被随意重置的权威代际或唯一版本路径，并明确原子校验边界，而不是随便增加一个字段。

这一反例由[ZooKeeper 3.9.3 setData契约](https://zookeeper.apache.org/doc/r3.9.3/apidocs/zookeeper-server/org/apache/zookeeper/ZooKeeper.html)及[release-3.9.3 DataTree.createStat](https://github.com/apache/zookeeper/blob/release-3.9.3/zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java)中新对象版本初始化规则推导，未运行服务。

这种方式并不自动得到高吞吐计数器：热点冲突会带来重试，连接丢失还可能导致更新结果未知。版本失败、权限失败和连接失败需要分别处理，不能一概认为“重试即可”。

## 4. 从 Ready 标记到不可变版本发布 {#_4-ready-文件为什么不是通用原子发布}

“删除 ready → 更新多个节点 → 重建 ready”可以提示发布阶段，但各次读取之间仍有时间间隔：读者可能先看到旧 ready，再读到混合配置；Watch 也可能在使用后才到达。要保持一套配置的版本身份，需要在发布与读取协议中共同约束。

本章采用的教学方案是：写入不可变配置版本 v7，验证完整后，只切换一个 current 指针；读取者固定版本后读该版本下的内容。不变的是一整套配置的版本身份，而不是每读一项都重新追最新。

## 5. 大内容、版本回收与失败恢复 {#_5-发布协议还要补哪些边界}

配置数据很多时不一定能放进一次 multi；大内容可存外部对象，ZooKeeper 只保存经验证的版本引用。对有限更新，multi/check 等构件可以保护适用的检查与更新，但不能覆盖外部文件原子性。

旧版本回收需要确认没有仍在使用的读者或有适用保留期；切换超时需要查询 current 的事实状态；回退应切回一个完整版本，不直接修改已被读取的不可变内容。这是应用发布协议，不宣称 ZooKeeper 自动实现了这些步骤。

配套构件可参照 [ZooKeeper 3.9.3 Recipes](https://zookeeper.apache.org/doc/r3.9.3/recipes.html)。

[返回本册目录](/collections/distributed-systems/)
