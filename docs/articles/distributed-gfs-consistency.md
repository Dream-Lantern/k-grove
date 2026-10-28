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

数据流水线负责高效传输内容，Primary 负责确定 mutation 顺序。沿这两条路径分别观察，可以区分数据已经接收与写入已经应用的阶段。[GFS 论文 §3.1—3.2](https://research.google.com/archive/gfs-sosp2003.pdf)

## 3. 普通写入与 Record Append 不同

普通 write 的偏移由客户端指定；Record Append 由系统选择记录放置位置，并在成功语义下提供原子追加至少一次的保证。这有助于并发生产者不用自行竞争同一个文件尾偏移，但不提供业务恰好一次。

失败、重试或块尾填充可能留下重复记录和无效区域。教学例子：同一 event_id 的记录追加成功，但回复丢失，客户端重试后再次出现。读者需依据记录 ID、校验或格式识别允许的重复与填充，不能只按“追加成功次数”计算业务事件数量。

## 4. consistent 与 defined 的区别

论文中的 consistent 指相关副本上的区域观察一致；defined 进一步要求包含完整 mutation 的结果。它们不等价于一般数据库的全部事务语义。

| 普通 write 的情况 | 文件区域状态的教学概括                      |
| ----------------- | ------------------------------------------- |
| 无并发干扰且成功  | defined，因此也 consistent                  |
| 并发写入均成功    | 可以 consistent，但结果可能混合而 undefined |
| 写入失败          | 可能 inconsistent，不应假定全部回滚         |

Record Append 的成功记录区域另有定义保证，区域之间仍可能有填充或重复，不能机械套进普通覆盖写的每一行。依据为论文 §2.7 的状态划分与 §3.3 的追加语义。

## 5. 失败后的重试、版本筛选与修复 {#_5-出错后为什么不能只换副本就结束}

请求失败可能留下不同副本的局部修改，需要按协议重试、版本筛选和修复。成功返回、数据通过校验、业务记录无重复，分别是不同层次的验收。

客户端缓存位置尚未刷新时，仍可能接触落后副本。分析读取结果时，需要同时考虑 Master 的副本筛选与客户端缓存窗口；刷新位置并重试后，再依据当前副本信息继续。

## 6. 学习检查

练习时，可以在纸面上标记各副本在数据推送、顺序确定、应用与回复阶段的状态，再分别模拟回复丢失、Secondary 失败和租约交接。重点是判断哪些区域可能不完整、如何识别业务有效记录，而不是将文件存储视为无条件提供 ACID 的数据库。

## 联读

GFS2003案例下半课，先读[工作负载、Master与恢复](/articles/distributed-gfs-architecture.html)。

[返回本册目录](/collections/distributed-systems/)
