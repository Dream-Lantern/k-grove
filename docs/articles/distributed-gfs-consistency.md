---
id: distributed-gfs-consistency
title: 第十七章 GFS 读写、Record Append 与一致性
description: "GFS 将数据传输与写入排序分开组织：客户端先找到副本并推送数据，再由 Primary 协调 mutation 的执行顺序。"
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
order: 17
---

# 第十七章 GFS 读写、Record Append 与一致性

> 阅读标签：GFS2003历史案例 / 数据路径与一致性。

GFS 将数据传输与写入排序分开组织：客户端先找到副本并推送数据，再由 Primary 协调 mutation 的执行顺序。本章沿读取、普通写入和 Record Append 的过程，观察各阶段的状态与失败后的一致性含义。

## 1. 查询块位置后直接读取副本 {#_1-一次读取怎样找到数据}

客户端根据文件名与 chunk 索引查询 Master，获得 handle 与副本位置，并缓存适用元数据。之后向选定 Chunkserver 读取所需范围。若跨 chunk，客户端需要组织多个请求，不是所有数据必然由某个“GFS 服务器”统一拼成一个缓冲再返回。

副本位置缓存可能过时，读取失败或发现信息落后时，需要刷新并重试。即使具有版本与副本机制，也不能保证缓存的路由始终正确。

## 2. 写入的数据流与控制流

[![GFS写入：数据链与控制链](/assets/notes/distributed-systems/dist-gfs-write.png)](/assets/notes/distributed-systems/dist-gfs-write.png)

客户端查询租约 Primary 和适用副本，先把待写数据推送到副本的数据流水线；推送顺序按网络等条件选择，不必先到 Primary。随后客户端向 Primary 发控制请求，Primary 决定 mutation 顺序，其他副本按一致顺序执行。

数据流水线负责高效传输内容，Primary 负责确定 mutation 顺序。沿这两条路径分别观察，可以区分数据已经接收与写入已经应用的阶段。[GFS 论文 §3.1—3.2](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)

一次修改操作（Mutation）可能是普通写或记录追加。以下按 GFS 2003 §3.1、Figure 2 展开普通写，假设 Primary 为 A，Secondary 为 B、C：

1. Client 查询 Master，得到当前 Primary、Secondary 及适用版本信息；若尚无租约，由 Master 按协议授予。
2. Client 向所有副本推送数据。Chunkserver 按拓扑把数据沿流水线转发，先进入内部数据缓存。图用 `Client→A→B→C` 举例，也允许 `Client→B→C→A` 等顺序；到达数据流水线最前端不代表获得 Primary 资格。
3. 所有副本确认数据接收后，Client 才向 A 发送引用这些数据的 mutation 控制请求。接收 ACK 不等于文件修改已经完成。
4. A 为收到的 mutation 分配连续序号，并按序本地执行；多个客户端的控制请求也在这里统一排序。
5. A 把带执行顺序的写控制请求发给 B、C；Secondary 按同样序号执行，再返回完成或错误结果。
6. A 汇总 Secondary 的结果并回复 Client。成功路径要求这次相关副本执行完成；任一副本错误都应报告，不能仅因 A 写成功就报告整笔成功。

推送顺序优化的是数据搬运，mutation 顺序决定的是文件状态。两个副本可先后收到相同数据，但最终必须按 Primary 指定的同一顺序应用；数据路径与控制路径不是两套独立决定写入先后的协议。[GFS §3.1～3.2](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)

## 3. 普通写入与 Record Append 不同

普通 write 的偏移由客户端指定；Record Append 由系统选择记录放置位置，并在成功语义下提供原子追加至少一次的保证。这有助于并发生产者不用自行竞争同一个文件尾偏移，但不提供业务恰好一次。

失败、重试或块尾填充可能留下重复记录和无效区域。教学例子：同一 event_id 的记录追加成功，但回复丢失，客户端重试后再次出现。读者需依据记录 ID、校验或格式识别允许的重复与填充，不能只按“追加成功次数”计算业务事件数量。

原子记录追加（Atomic Record Append）让应用只提交记录内容，由 Primary 选定偏移，并让 Secondary 在同一偏移写入。多个生产者因而不必先自行锁定文件尾。论文把一条追加记录限制为最大 chunk 大小的四分之一；64 MB 的块对应最大 16 MB 记录，以控制最坏情况下的碎片。

若当前块已用 60 MB，要追加 8 MB，记录本身未超 16 MB 限制，但剩余 4 MB 装不下它。Primary 将块填充（Padding）到 64 MB，通知 Secondary 同样处理，并告诉 Client 到下一个块重试，而不是把这条原子记录拆成两半跨块放置。若剩余空间足够，则由 Primary 决定偏移，所有副本按该偏移写完后返回成功。[GFS §3.3](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)

**教学时序：** `event_id=order-1001` 的记录已成功写入，但回复在途中丢失；Client 无法区分“未写入”和“写入后回复丢失”，重试可能在更后偏移再追加一条完整相同记录。至少一次（At-Least-Once）语义保留完整成功记录，却不提供恰好一次（Exactly-Once）业务效果。

应用可把稳定 event_id、长度和校验和放入自描述记录：格式及校验用于识别完整记录、碎片和填充，event_id 用于去重。**校验和不是去重 ID**，两条内容完整且校验正确的重复记录仍需识别；若消费会扣款，还须把业务去重与实际效果放进适当的原子恢复协议。[GFS §2.7.2、§3.3](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)

## 4. consistent 与 defined 的区别

论文中的 consistent 指相关副本上的区域观察一致；defined 进一步要求包含完整 mutation 的结果。它们不等价于一般数据库的全部事务语义。

| 普通 write 的情况 | 文件区域状态的教学概括                      |
| ----------------- | ------------------------------------------- |
| 无并发干扰且成功  | defined，因此也 consistent                  |
| 并发写入均成功    | 可以 consistent，但结果可能混合而 undefined |
| 写入失败          | 可能 inconsistent，不应假定全部回滚         |

Record Append 的成功记录区域另有定义保证，区域之间仍可能有填充或重复，不能机械套进普通覆盖写的每一行。依据为论文 §2.7 的状态划分与 §3.3 的追加语义。

可以用不同观察范围理解：普通写把 `ABCDEF` 无并发地完整写入后成功，相关副本该区间都是 ABCDEF，区域已定义（Defined），也就一致（Consistent）。如果两个较大的并发覆盖写被拆为多次 chunk 写并交错，副本可以具有同样的混合结果，因此一致，却未必等于任何一个完整请求的内容，属于未定义（Undefined）。这不意味着单个块内所有小写入都会任意撕裂，而是要分析完整请求涉及的实际 mutation 范围。

| 观察对象                                    | 按论文分析的区域状态                                           |
| ------------------------------------------- | -------------------------------------------------------------- |
| 无并发的成功普通 Write                      | Defined，因而 Consistent                                       |
| 并发普通 Write 均成功的相关区域             | Consistent，但可能 Undefined                                   |
| 失败普通 Write 的修改区域                   | 可能 Inconsistent，不保证回滚                                  |
| 成功 Record Append 返回偏移处的完整记录区间 | Defined；成功要求在相关副本相同偏移完整写入                    |
| 包含失败尝试、填充等间隔的整个追加范围      | Defined 的成功记录之间可穿插 Inconsistent、Undefined 区域      |
| 重复记录                                    | 可能每份都是 Defined，但业务意义重复；“重复”本身不等于字节损坏 |

Table 1 对连续或并发 Record Append 的概括是 **defined interspersed with inconsistent**。这是整个追加区域的混合状态，与“某一条成功记录的连续字节区间是 Defined”并不矛盾。论文没有保证各副本的整个 chunk 逐字节相同；失败重试可能让间隔、碎片和重复出现差异。[GFS §2.7.1 Table 1、§3.3](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)

## 5. 失败后的重试、版本筛选与修复 {#_5-出错后为什么不能只换副本就结束}

请求失败可能留下不同副本的局部修改，需要按协议重试、版本筛选和修复。成功返回、数据通过校验、业务记录无重复，分别是不同层次的验收。

客户端缓存位置尚未刷新时，仍可能接触落后副本。分析读取结果时，需要同时考虑 Master 的副本筛选与客户端缓存窗口；刷新位置并重试后，再依据当前副本信息继续。

具体故障例子：A 已将偏移 p 写为 X，B 也执行成功，C 执行失败而仍保留旧值。A 汇总后向 Client 报错，此时 A、B 的修改不会自动撤销；读不同副本可能得到不同字节，修改区域已不一致（Inconsistent）。即使错误回复丢失，Client 也只能知道结果不确定，不能推断所有副本均未动过。

论文客户端先对数据推送至执行步骤做若干次重试，再必要时从查询阶段重来；副本有效性、坏块检测与重复制则由相应恢复机制处理。重试可能让操作最终成功，但它不是对前一次部分效果的事务回滚。块版本也不能单独检测同一次租约中每笔部分失败写入。[GFS §3.1、§4.5、§5.2](https://storage.googleapis.com/gweb-research2023-media/pubtools/4446.pdf)

## 6. 学习检查

练习时，可以在纸面上标记各副本在数据推送、顺序确定、应用与回复阶段的状态，再分别模拟回复丢失、Secondary 失败和租约交接。重点是判断哪些区域可能不完整、如何识别业务有效记录，而不是将文件存储视为无条件提供 ACID 的数据库。

这套取舍来自论文的大文件、顺序读取、大量并发追加和高吞吐工作负载，同时假设普通机器故障频繁。系统把追加位置选择和完整记录的至少一次保存交给存储层，把重复识别、自校验记录及应用恢复留给上层；由此减少生产者间的额外协调。它服务的是明确的应用契约，不能只用“一致性能力不足”概括，也不能把契约推广成任意覆盖写、计数或跨文件事务的保证。以上例子均为教学推演，未运行 GFS 故障实验。

## 联读

GFS2003案例下半课，先读[工作负载、Master与恢复](/articles/distributed-gfs-architecture.html)。

[返回本册目录](/collections/distributed-systems/)
