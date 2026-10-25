---
id: distributed-version-references
title: 附录 A：论文与版本依据
description: 本册围绕原笔记中的经典系统展开，技术核对始于 2026-10-21，整理完成日期另存于私有处理记录。论文描述的是发表时的设计，不能据此直接推断同名产品当前的内部实现。下表仅提供阅读入口，无需按清单安装软件。
date: '2026-10-25'
updated: '2026-10-25'
category: distributed-systems
type: reference
tags:
  - 分布式系统
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: distributed-systems
series: distributed-learning
order: 90
---

# 附录 A：论文与版本依据

本册围绕原笔记中的经典系统展开，技术核对始于 2026-10-21，整理完成日期另存于私有处理记录。论文描述的是发表时的设计，不能据此直接推断同名产品当前的内部实现。下表仅提供阅读入口，无需按清单安装软件。

| 主题            | 基线与主要依据                                                                                                                                                                                                                               | 阅读时关注                                        |
| --------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------- |
| 事件顺序        | [Lamport 1978](https://lamport.azurewebsites.net/pubs/time-clocks.pdf)                                                                                                                                                                       | 因果偏序、逻辑时钟，逆命题不成立                  |
| 线性一致性      | [Herlihy、Wing 1990](https://cs.brown.edu/~mph/HerlihyW90/p463-herlihy.pdf)                                                                                                                                                                  | 调用区间、实时约束、对象顺序规范                  |
| CAP             | [Gilbert、Lynch 2012 回顾](https://groups.csail.mit.edu/tds/papers/Gilbert/Brewer2.pdf)                                                                                                                                                      | 分区与请求保证，不是任意三选二                    |
| FLP             | [Fischer、Lynch、Paterson 1985](https://groups.csail.mit.edu/tds/papers/Lynch/jacm85.pdf)                                                                                                                                                    | 完全异步、确定性与终止限制                        |
| Paxos           | [Paxos Made Simple，2001](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)                                                                                                                                                           | 单槽提案、承诺和值继承                            |
| Raft            | [2014 扩展论文](https://raft.github.io/raft.pdf)                                                                                                                                                                                             | §5 选举与安全，§6 成员，§7 快照，§8 客户端        |
| VMware FT       | [历史 FT 论文](https://pdos.csail.mit.edu/6.824/papers/vm-ft.pdf)                                                                                                                                                                            | vSphere 4.0 时代，非确定性、输出与接管            |
| Dynamo          | [2007 论文](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)                                                                                                                                                           | sloppy quorum、版本与修复；不是当前 DynamoDB 手册 |
| ZooKeeper       | [3.9.3 Programmer's Guide](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html)、[Internals](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html)、[Recipes](https://zookeeper.apache.org/doc/r3.9.3/recipes.html) | Zab、会话、Watch、版本与锁边界                    |
| GFS             | [2003 论文](https://research.google.com/archive/gfs-sosp2003.pdf)                                                                                                                                                                            | §2.7 一致性，§3 数据与控制路径                    |
| CRAQ            | [2009 论文](https://www.cs.princeton.edu/courses/archive/fall22/cos418/papers/craq.pdf)                                                                                                                                                      | §2 clean/dirty 与 Tail 版本查询                   |
| WAL 与 SQL 隔离 | [PostgreSQL 17 WAL](https://www.postgresql.org/docs/17/wal-intro.html)、[隔离](https://www.postgresql.org/docs/17/transaction-iso.html)                                                                                                      | 产品举例，不替其他引擎证明相同实现                |
| 原子提交        | [Gray、Lamport 的提交分析](https://lamport.azurewebsites.net/video/consensus-on-transaction-commit.pdf)                                                                                                                                      | Prepared、持久决定、阻塞与共识的层次              |
| Saga / Outbox   | [Saga 原论文](https://www.cs.cornell.edu/andru/cs711/2002fa/reading/sagas.pdf)、[Outbox 模式](https://microservices.io/patterns/data/transactional-outbox.html)                                                                              | 补偿不是物理回滚；可靠传递仍可能重复              |
| Aurora          | [2017 论文](https://cdn.amazon.science/dc/2b/4ef2b89649f9a393d37d3e042f4e/amazon-aurora-design-considerations-for-high-throughput-cloud-native-relational-databases.pdf)                                                                     | 保护组、redo、正常读与恢复读不同                  |
| Frangipani      | [1997 论文](https://rcs.uwaterloo.ca/papers/frangipani.pdf)                                                                                                                                                                                  | 元数据日志、缓存锁、恢复与租约限制                |
| PBFT            | [1999 原论文网页](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/castro.html)                                                                                                          | 身份、故障预算、阶段定义及视图切换                |
| PoW             | [Bitcoin 原论文](https://bitcoin.org/bitcoin.pdf)                                                                                                                                                                                            | 算力与传播假设，不是节点数量多数                  |

新增工程说明基于应用协议推演，并非作者亲历的实验记录。文中未虚构实例规格、软件参数、性能数值或故障测试结果；各系统的安装、升级与安全配置也不在本次整理范围内。

原截图包含课程画面或第三方图片，来源授权尚未逐一核实。本地候选稿采用重新表达机制的图，并不因此获得原图片的转载权；技术核对也不能替代公开授权和敏感信息审查。

[返回本册目录](/collections/distributed-systems/)

## 2026-10-22复核定位

- Raft2014扩展论文§8：当前任期提交前提、针对读取的多数领导权确认，以及应用进度与读边界。
- [PBFT1999 §4.1—4.2](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node4.html)：prepared、committed-local与客户端回复分别计数。
- [ZooKeeper release-3.9.3 DataTree.createStat](https://github.com/apache/zookeeper/blob/release-3.9.3/zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java)：新对象version初始化为0，结合setData API推导同路径重建ABA。
- [PostgreSQL17同步/异步提交](https://www.postgresql.org/docs/17/wal-async-commit.html)：提交记录的持久化屏障与成功回复。
- fencing资源尚未看到新代际、Outbox发布逆序等为有前提的应用历史推演，不冒充论文规定的通用实现。
