---
id: kafka-offset-watermarks
title: 第 11 章：消费位点、提交与连续完成水位
description: 每个 Topic-Partition 都有自己的位置。客户端可能已预先拉取一批记录到本地，应用却只处理了其中一部分，外部数据库完成的部分还可能更少。因此，网络读取进度、应用读取进度和业务完成进度不能混用。
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - kafka
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kafka
series: kafka-learning
order: 11
---

# 第 11 章：消费位点、提交与连续完成水位

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：区分已拉取、已交给应用、业务已完成、本地已保存和 Broker 已提交的位置，正确解释提交值中的“下一位置”。

## 1. 位点不是全组一个数字

每个 Topic-Partition 都有自己的位置。客户端可能已预先拉取一批记录到本地，应用却只处理了其中一部分，外部数据库完成的部分还可能更少。因此，网络读取进度、应用读取进度和业务完成进度不能混用。

提交给组的恢复位点通常采用下一读取位置口径。例如已安全完成 Offset 100，希望恢复时从 101 继续，则提交 101，而不是 100。若直接调用接受消息对象的提交 API，要先确认它是否已经内部加一，不能再人为加一次。

## 2. 并行消费需要连续完成前沿

[![异步消费：只提交连续完成的下一位置](/assets/notes/kafka/kf-frontier.png)](/assets/notes/kafka/kf-frontier.png)

假设 100、101、102 都存在，100 和 102 完成，101 仍在执行。安全提交值只能推进到 101。提交 103 会让崩溃恢复跳过尚未完成的 101。等 101 也完成，再推进到 103。

实现时通常维护分区内交给业务的记录顺序、完成标记和最前方未完成记录。不要死等每一个数学整数 Offset：compact、事务控制记录或可见性过滤可能造成应用记录的空洞，应按实际交付的记录序列及客户端位置语义推进。

## 3. Auto Store 与 Auto Commit 不是一回事

librdkafka 的本地 Offset Store 记录下一次可提交的位置；Commit 才把恢复位置提交到 Broker。`enable.auto.offset.store` 与 `enable.auto.commit` 是两个开关。

对于耗时较长或异步执行的处理，若记录一交付给应用就自动 Store，后台 Commit 就可能早于实际业务完成。可以关闭 Auto Store，在完成前沿推进后保存安全位置，再由后台提交；也可以关闭自动提交，由应用明确提交各分区的安全位点。两种做法都需要检查错误，不能只关闭一个开关就认为已经可靠。

## 4. earliest 与 latest 什么时候生效

`auto.offset.reset` 一般处理没有有效初始提交位置或请求位置越界的情况，不是每次启动都覆盖已有有效位点。`earliest` 指向当前保留范围的早端，不承诺从 Topic 创建时的第一条历史开始；`latest` 从当时末端继续，不会自动补回已过期数据。

值名也依客户端：Java 的异常路线用 `none`，本册固定的 librdkafka 使用 `error` 等受支持值，不能直接互抄。显式 seek 则是另一种位置控制，仍必须考虑保留范围和待处理任务。

## 5. 提交失败与重放窗口

业务完成后提交失败，恢复时可能重放已经完成的业务，因此需要幂等。提交成功后才处理业务，崩溃则可能永久跳过未完成工作。同步提交只是等待提交结果，不会把外部业务和位点自动放进同一个事务。

异步提交还要考虑旧结果回调延迟到达，以及失败重试与新位点交错的情况。比起设计复杂逻辑来重试每次历史提交，更安全的起点是明确维护当前安全前沿和分区所有权，再按客户端契约制定单调推进与恢复策略。

## 参考

- [librdkafka v2.8.0 消费者位点说明](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)
- [Java Consumer 起点与提交配置](https://kafka.apache.org/39/configuration/consumer-configs/)
