---
id: distributed-zookeeper-zab
title: 第十三章 ZooKeeper 架构、Zab 与数据模型
description: ZooKeeper 是协调服务，不是通用的大对象数据库。它适合保存配置、成员和少量协调状态，提供有序更新、版本校验与通知等构件。本章的 API 参照 3.9.3；历史课程说明另按其原始背景理解。
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
order: 13
---

# 第十三章 ZooKeeper 架构、Zab 与数据模型

> 阅读标签：ZooKeeper3.9.3 API与Zab模型。

ZooKeeper 是协调服务，不是通用的大对象数据库。它适合保存配置、成员和少量协调状态，提供有序更新、版本校验与通知等构件。本章的 API 参照 3.9.3；历史课程说明另按其原始背景理解。

## 1. 底层不是 Raft

![客户端会话与有序写入](/assets/notes/distributed-systems/dist-zk.svg)

ZooKeeper 使用 Zab 路线的原子广播协调写入，与 Raft 都涉及领导者和复制，但不是“ZooKeeper 就是一个 Raft 框架”。协议的恢复与顺序约束应按各自资料阅读。[ZooKeeper 3.9.3 内部原子广播](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html#sc_atomicBroadcast)

客户端连接到服务节点，写入通过适用路径协调，普通读取可以在所连节点服务。写入顺序与客户端会话保证，不等于不同客户端同时读到完全相同的最新数据。

## 2. znode 是有路径的协调对象

路径类似文件系统，znode 既可以保存少量数据，也可以拥有子节点；但它不是普通磁盘文件接口。dataVersion、子节点版本和 ACL 版本具有不同用途，不能把所有变化都解释成同一个 version 加一。

| 常见类别或选项 | 主要含义                                    |
| -------------- | ------------------------------------------- |
| Persistent     | 除非被删除，否则不会随会话结束自动消失      |
| Ephemeral      | 与创建会话绑定，会话过期后由服务清理        |
| Sequential     | 创建时追加序号，可与适用的持久/临时模式组合 |

这三项并非互斥且穷尽的类别。Container、TTL 节点等还各有使用条件；顺序后缀也有其作用域与计数限制，不能视为适用于所有业务的永久全局唯一标识。临时节点通常不能有子节点。[3.9.3 数据模型](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkDataModel)

## 3. API 的成功与错误不能二分为“存在/不存在”

create 的 NodeExists 与连接丢失不同：前者给出具体冲突，后者可能意味着创建成功但响应未到。delete、setData 的版本参数用于条件检查；指定忽略版本的用法会放弃相应并发保护。

exists、getData、getChildren 有各自返回值与 Watch 语义。multi 可组合支持的操作，构成一个原子的 ZooKeeper 更新；它不是对外部数据库和文件系统的跨系统事务。

## 4. 会话失联与会话过期

短暂断开连接，不意味着临时节点立即删除，也不保证原会话永久保留。客户端需处理连接状态变化；会话过期后，不能再将旧节点、旧锁或本地缓存视为有效资格。

纸面推演：A 失联但线程仍运行，服务端最终使会话过期并删除临时节点，B 获得下一份资格。A 恢复时必须停止以旧资格工作；外部资源还需 fencing 等机制阻止迟到写入，详见第 15 章。

## 5. 读到旧值不是随便读什么都正确

文档定义同一会话的系统视图等保证，同时提醒跨客户端的普通读可能不同。sync 后按顺序发读是文档给出的客户端同步工具，但不能缩写成“任意客户端加一次 sync，所有未来读取永远最新”。应保留成功回调、会话与故障条件。[一致性保证](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html#ch_zkGuarantees)

原笔记中逐请求携带 zxid 的说法，保留为理解课程的线索，不作为各客户端 API 的参数格式或精确网络协议实现说明。

[返回本册目录](/collections/distributed-systems/)
