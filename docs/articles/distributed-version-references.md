---
id: distributed-version-references
title: 附录 A：论文与版本依据
description: "本册按经典论文、版本化 API 与应用协议组织阅读依据，技术核对始于 2026-10-21。论文对应发表时的设计，产品行为按注明版本理解。"
date: '2026-10-25'
updated: '2026-10-28'
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

本册按经典论文、版本化 API 与应用协议组织阅读依据，技术核对始于 2026-10-21。论文对应发表时的设计，产品行为按注明版本理解。下表用于查阅各主题的来源与前提，无需按清单安装软件。

| 主题                 | 基线与主要依据                                                                                                                                                                                                                                                                          | 阅读时关注                                                                             |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------- |
| 事件顺序             | [Lamport 1978](https://lamport.azurewebsites.net/pubs/time-clocks.pdf)                                                                                                                                                                                                                  | 因果偏序、逻辑时钟，逆命题不成立                                                       |
| Linux 时间 API       | [Linux man-pages 6.9.1：clock_gettime(2)，Debian trixie](https://manpages.debian.org/trixie/manpages-dev/clock_gettime.2.en.html)                                                                                                                                                       | REALTIME 可跳变；MONOTONIC 受频率调整、不计挂起；BOOTTIME 计入挂起                     |
| NTPv4                | [RFC 5905 基础规范](https://datatracker.ietf.org/doc/html/rfc5905)、[IETF 更新状态](https://datatracker.ietf.org/doc/rfc5905/)                                                                                                                                                          | 同步误差与时钟模型；需结合后续更新阅读                                                 |
| 线性一致性           | [Herlihy、Wing 1990](https://cs.brown.edu/~mph/HerlihyW90/p463-herlihy.pdf)                                                                                                                                                                                                             | 调用区间、实时约束、对象顺序规范                                                       |
| CAP                  | [Gilbert、Lynch 2012 回顾](https://groups.csail.mit.edu/tds/papers/Gilbert/Brewer2.pdf)                                                                                                                                                                                                 | 分区与请求保证，不是任意三选二                                                         |
| FLP                  | [Fischer、Lynch、Paterson 1985](https://groups.csail.mit.edu/tds/papers/Lynch/jacm85.pdf)                                                                                                                                                                                               | 完全异步、确定性与终止限制                                                             |
| Paxos                | [Paxos Made Simple，2001](https://lamport.azurewebsites.net/pubs/paxos-simple.pdf)                                                                                                                                                                                                      | 单槽提案、承诺和值继承                                                                 |
| Raft                 | [2014 扩展论文](https://raft.github.io/raft.pdf)                                                                                                                                                                                                                                        | §5 选举与安全，§6 成员，§7 快照，§8 客户端                                             |
| VMware FT            | [历史 FT 论文](https://pdos.csail.mit.edu/6.824/papers/vm-ft.pdf)                                                                                                                                                                                                                       | vSphere 4.0 时代，非确定性、输出与接管                                                 |
| Dynamo               | [2007 论文](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)                                                                                                                                                                                                      | sloppy quorum、版本与修复；不是当前 DynamoDB 手册                                      |
| ZooKeeper            | [3.9.3 Programmer's Guide](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html)、[Internals](https://zookeeper.apache.org/doc/r3.9.3/zookeeperInternals.html)、[Recipes](https://zookeeper.apache.org/doc/r3.9.3/recipes.html)                                            | Zab、会话、Watch、版本与锁边界                                                         |
| GFS                  | [2003 论文](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)                                                                                                                                                                                                   | §2.7 一致性，§3 数据与控制路径                                                         |
| CRAQ                 | [2009 论文](https://www.usenix.org/event/usenix09/tech/full_papers/terrace/terrace.pdf)                                                                                                                                                                                                 | §2 clean/dirty 与 Tail 版本查询                                                        |
| WAL 与 SQL 隔离      | [PostgreSQL 17 WAL](https://www.postgresql.org/docs/17/wal-intro.html)、[隔离](https://www.postgresql.org/docs/17/transaction-iso.html)                                                                                                                                                 | 产品举例，不替其他引擎证明相同实现                                                     |
| 原子提交             | [Gray、Lamport 的提交分析](https://lamport.azurewebsites.net/video/consensus-on-transaction-commit.pdf)                                                                                                                                                                                 | Prepared、持久决定、阻塞与共识的层次                                                   |
| Saga / Outbox        | [Saga 原论文](https://www.cs.cornell.edu/andru/cs711/2002fa/reading/sagas.pdf)、[Outbox 模式](https://microservices.io/patterns/data/transactional-outbox.html)                                                                                                                         | 补偿不是物理回滚；可靠传递仍可能重复                                                   |
| Aurora               | [2017 论文](https://cdn.amazon.science/dc/2b/4ef2b89649f9a393d37d3e042f4e/amazon-aurora-design-considerations-for-high-throughput-cloud-native-relational-databases.pdf)                                                                                                                | 保护组、redo、正常读与恢复读不同                                                       |
| Frangipani           | [1997 论文](https://rcs.uwaterloo.ca/papers/frangipani.pdf)                                                                                                                                                                                                                             | 元数据日志、缓存锁、恢复与租约限制                                                     |
| PBFT                 | [1999 原论文网页](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/castro.html)                                                                                                                                                     | 身份、故障预算、阶段定义及视图切换                                                     |
| PoW                  | [Bitcoin 原论文](https://bitcoin.org/bitcoin.pdf)                                                                                                                                                                                                                                       | 算力与传播假设，不是节点数量多数                                                       |
| RPC、截止时间与重试  | [gRPC Deadlines](https://grpc.io/docs/guides/deadlines/)、[AWS 超时、重试与退避](https://aws.amazon.com/builders-library/timeouts-retries-and-backoff-with-jitter/)、[幂等 API](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)                      | 第 2、26 章：请求超时不证明未执行；重试需身份与预算                                    |
| 顺序一致性与会话保证 | [Lamport 1979](https://lamport.azurewebsites.net/pubs/multi.pdf)、[Terry 等人 1994](https://www.cs.cornell.edu/courses/cs734/2000FA/cached%20papers/SessionGuaranteesPDIS_1.html)                                                                                                       | 第 4 章：程序顺序、读己之写与单调读；会话不是全局最新读                                |
| 一致性哈希           | [Karger 等人 1997](https://people.csail.mit.edu/karger/Papers/web.pdf)                                                                                                                                                                                                                  | 第 6 章：最少扰动的映射，不替代迁移与复制协议                                          |
| Chain Replication    | [van Renesse、Schneider 2004](https://www.cs.cornell.edu/home/rvr/papers/OSDI04.pdf)                                                                                                                                                                                                    | 第 18 章：Tail 提交、确认与成员恢复；与 CRAQ 的读扩展分别理解                          |
| Lease 与 Fencing     | 上表 Frangipani 1997 §6；[Kleppmann 2016 的作者说明](https://martin.kleppmann.com/2016/02/08/how-to-do-distributed-locking.html)                                                                                                                                                        | 第 15、24、25 章：客户端租约检查与资源端拒绝旧资格不是同一步                           |
| TCC                  | [Apache Seata TCC 模式](https://seata.apache.org/docs/dev/mode/tcc-mode/)、[官方对 1.5.1 TCC Fence 的分析](https://seata.apache.org/blog/seata-tcc-fence/)                                                                                                                              | 第 22 章：空回滚、幂等与悬挂；文档入口随站点演进，1.5.1 是历史实现例子                 |
| CQRS 与缓存          | [Microsoft CQRS](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs)、[Cache-Aside](https://learn.microsoft.com/en-us/azure/architecture/patterns/cache-aside)                                                                                                          | 第 25 章：可选异步投影、写后读与迟到回填边界                                           |
| Bloom Filter         | [Summary Cache 论文的位数组说明](https://pages.cs.wisc.edu/~cao/papers/summary-cache/node8.html)、[计数式更新](https://pages.cs.wisc.edu/~cao/papers/summary-cache/node9.html)                                                                                                          | 第 25 章：假阳性、正确插入前提与删除；这是后续论文的作者原文，不冒称 Bloom 1970 原论文 |
| 全局 ID              | [RFC 9562 §5.7、§6](https://datatracker.ietf.org/doc/html/rfc9562)、[Twitter Snowflake 历史源码](https://github.com/twitter-archive/snowflake/blob/snowflake-2010/src/main/scala/com/twitter/service/snowflake/IdWorker.scala)                                                          | 第 25 章：UUIDv7 字段、时钟回退与节点身份；唯一、有序和不可猜测分别判断                |
| Web Session          | [OWASP Session Management](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)                                                                                                                                                                          | 第 25 章：Web 会话、身份认证、授权与凭据生命周期；区别于 ZooKeeper 协议会话            |
| 可观测性             | OpenTelemetry [Traces](https://opentelemetry.io/docs/concepts/signals/traces/)、[Metrics](https://opentelemetry.io/docs/concepts/signals/metrics/)、[上下文传播](https://opentelemetry.io/docs/concepts/context-propagation/)、[采样](https://opentelemetry.io/docs/concepts/sampling/) | 第 26 章：Trace/Span、分布与基数，传播与采样分别处理                                   |
| 过载与故障验证       | Google SRE [Handling Overload](https://sre.google/sre-book/handling-overload/)、[Addressing Cascading Failures](https://sre.google/sre-book/addressing-cascading-failures/)                                                                                                             | 第 26 章：限流、负载丢弃、重试预算；故障记录模板是教学设计，不是已执行实验             |

PostgreSQL 17 是本册 WAL、MVCC 与隔离的**教学基线**，不表示当前最新版本；MVCC 的快照与隔离边界以该版本文档为准。ZooKeeper 资料固定为 3.9.3；Dynamo 2007、Aurora 2017、Frangipani 1997 和 vSphere 4.0 时代的 VMware FT 都按历史设计阅读，不推断今天产品的全部实现。

GFS 另有[作者机构入口](https://research.google/pubs/the-google-file-system/)，CRAQ 另有[USENIX 2009 会议入口](https://www.usenix.org/conference/usenix-09/object-storage-craq-high-throughput-chain-replication-read-mostly-workloads)，可用于定位论文与出版信息。Outbox 已有模式作者原文，不要求额外采用某个 CDC 产品；实际连接器保证仍应按具体版本核对。

新增工程说明主要基于应用协议推演；个别已执行的单机教学例子以对应章节的环境、命令与结果记录为准，不扩写成分布式故障实验。文中未虚构实例规格、软件参数、性能数值或故障测试结果；各系统的安装、升级与安全配置也不在本次整理范围内。

原截图包含课程画面或第三方图片，来源授权尚未逐一核实。本地候选稿采用重新表达机制的图，并不因此获得原图片的转载权；技术核对也不能替代公开授权和敏感信息审查。

[返回本册目录](/collections/distributed-systems/)

## 2026-10-22 核查的关键规则定位 {#_2026-10-22复核定位}

- Raft2014扩展论文§8：当前任期提交前提、针对读取的多数领导权确认，以及应用进度与读边界。
- [PBFT1999 §4.1—4.2](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node4.html)：prepared、committed-local与客户端回复分别计数。
- [ZooKeeper release-3.9.3 DataTree.createStat](https://github.com/apache/zookeeper/blob/release-3.9.3/zookeeper-server/src/main/java/org/apache/zookeeper/server/DataTree.java)：新对象version初始化为0，结合setData API推导同路径重建ABA。
- [PostgreSQL17同步/异步提交](https://www.postgresql.org/docs/17/wal-async-commit.html)：提交记录的持久化屏障与成功回复。
- fencing资源尚未看到新代际、Outbox发布逆序等为有前提的应用历史推演，不冒充论文规定的通用实现。

## 2026-10-30 时间资料核查 {#_2026-10-30时间资料核查}

- Linux：上述手册的 DESCRIPTION 各时钟条目支持第三章的 Linux 行为表；文档版本为 man-pages 6.9.1，未在本机执行 Linux API 或挂起实验。
- NTP：RFC 5905 §6 描述时钟偏移、频率与误差模型；它是 NTPv4 基础规范，不是无后续修订的最新完整规范。核查时 IETF 状态页列出更新：[RFC 7822](https://datatracker.ietf.org/doc/html/rfc7822)（扩展字段格式）、[RFC 8573](https://datatracker.ietf.org/doc/html/rfc8573)（MAC 算法）、[RFC 9109](https://datatracker.ietf.org/doc/html/rfc9109)（端口随机化）、[RFC 9748](https://datatracker.ietf.org/doc/html/rfc9748)（更新 NTP 注册表）、[RFC 9769](https://datatracker.ietf.org/doc/html/rfc9769)（NTP 交错模式）。具体实现还应结合相关更新与勘误，不能从“使用 NTP”推导任意节点时间完全一致。
