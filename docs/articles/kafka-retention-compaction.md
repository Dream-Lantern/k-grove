---
id: kafka-retention-compaction
title: 第 7 章：保留策略、压缩清理与重放
description: 普通 delete 策略主要按时间、大小等条件清理合格日志段。消费者是否已读，不是必须先满足的删除条件。慢消费者可能在恢复时发现提交位点已经落到可保留范围之前。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 7
---

# 第 7 章：保留策略、压缩清理与重放

> 版本导航：Broker3.9 / Java3.9与C2.8按参数区分。
>
> 学习目标：区分 delete、compact 和压缩编码；能够判断“重新从头消费”是否真能恢复完整历史。

## 1. 保留期限不等待消费者

普通 `delete` 策略主要按时间、大小等条件清理合格日志段。消费者是否已读，不是必须先满足的删除条件。慢消费者可能在恢复时发现提交位点已经落到可保留范围之前。

时间保留也不是每条记录到了某秒就立即精确删除：日志段、检查周期和活动段等因素影响实际回收。容量估算不能只用“每天数据量×保留天数”，还要加入副本、索引、临时清理空间、负载变化和安全余量。

![保留与重放边界](/assets/notes/kafka/kf-retention.svg)

## 2. Compact 保留的是 Key 的状态线索

日志压缩清理会逐步清除同 Key 的旧值，适合变化日志或状态恢复等用途。它不会实时覆盖唯一键对应的记录，也不保证磁盘上每个 Key 始终只有一条记录。

例子：Key=A 先写版本 1，再写版本 2。普通事件审计可能关心两个版本；状态重建通常只需要最终状态。选择 compact 就必须接受某些中间事件不再完整可回放，不能同时把它当作永不丢历史的审计档案。

## 3. Tombstone 与“空值”要准确区分

压缩Topic中，带Key的null Value可以表达删除标记。它不同于空字符串或零长度普通字节值，序列化协议必须区分。`delete.retention.ms`控制此类删除标记的保留，Kafka 3.9文档默认86400000ms，即一天；它不是精确到某毫秒必删除的定时器。

以一段假设的历史为例：A=v1，随后 A=null。持有旧快照的消费者本地仍有 A=v1，若离线期间错过 tombstone，增量恢复时可能再也收不到删除通知，从而错误保留 A。从空状态开始扫描时，本地没有 A，与删除后的最终状态可以一致；但如果扫描很慢，先读到了 v1，而 tombstone 在被读到前已被清理，仍可能留下旧状态。因此，完整扫描也需要满足删除标记窗口等恢复前提，不能认为 earliest 天然保证最终状态正确。[3.9 delete.retention.ms](https://kafka.apache.org/39/configuration/topic-level-configs/#delete.retention.ms)

`delete,compact` 可组合使用，但组合并不意味着保留所有 Key 的最终值直到永久：普通保留仍可能淘汰旧段。恢复时间要求应和整个策略一起验收，而不只检查 cleanup.policy 的名称。

## 4. 数据压缩不是日志压缩清理

gzip、lz4、zstd 等编码压缩减少字节体积，通常不改变业务记录的逻辑含义。Compact 则依据 Key 清理旧版本，改变可保留的历史记录集合。中文里都叫“压缩”，但作用层次完全不同。

同样，副本不是独立备份：误删 Topic、错误保留设置或有权限的坏写入可能影响整套副本。灾备或归档需要独立评估版本、保留、权限与恢复能力。

## 5. 重放前先定义目标

重建查询视图前，应先明确目标：恢复最终状态，还是逐条重演完整事件。再检查数据保留范围、模式兼容、外部副作用和消费组位点，据此决定是使用独立新组、显式指定读取范围，还是受控调整位点。

不要在生产环境直接重置一个仍在线的组，然后观察“会不会好”。重放可能重复发邮件、重复调用支付接口或覆盖新的业务状态。可靠方法是隔离输出、确保幂等、记录范围，并设置人工停止与回退条件。本次没有重置任何位点。

## 参考

- [Topic 保留、cleanup.policy 与 tombstone 配置](https://kafka.apache.org/39/configuration/topic-level-configs/)
- [Kafka Log Compaction 设计](https://kafka.apache.org/39/design/design/#log-compaction)
