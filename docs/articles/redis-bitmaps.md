---
id: redis-bitmaps
title: 第八章 Bitmap 与位运算
description: Bitmap 利用 String 的位表示布尔状态。若用户 ID 可以映射到受控的整数范围，一个位表示当天是否活跃，就能紧凑地保存某类精确标记。
date: '2026-10-25'
updated: '2026-10-25'
category: distributed-systems
type: explanation
tags:
  - redis
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: redis
series: redis-learning
order: 8
---

# 第八章 Bitmap 与位运算

Bitmap 利用 String 的位表示布尔状态。若用户 ID 可以映射到受控的整数范围，一个位表示当天是否活跃，就能紧凑地保存某类精确标记。

## 1. 先确定偏移映射

新增示例，未执行：

```redis
SETBIT demo:active:day-1 42 1
GETBIT demo:active:day-1 42
BITCOUNT demo:active:day-1
```

42 是 bit offset，不是第 42 个字节。位图长度受最大偏移影响，不只受值为 1 的人数影响；若直接使用一个极大的稀疏 ID，第一次写入就可能分配很大的字符串。

因此，需要明确映射规则、ID 上界，以及映射在不同时间段之间是否保持一致。如果映射已经改变，却继续对旧位图做集合运算，结果就会在业务上失效。

## 2. 字节区间与位区间

BITCOUNT 的传统 start/end 区间按字节解释；Redis 7.0+ 可通过相应 BYTE/BIT 参数选择单位，不能只换一组数字就认为单位也变了。[BITCOUNT](https://redis.io/docs/latest/commands/bitcount/)

命令 BITPOS 查找首个指定 bit 的位置，原文 bitos 是拼写错误；查询范围单位、未找到和超出数据的语义要按具体参数理解。[BITPOS](https://redis.io/docs/latest/commands/bitpos/)

## 3. 交并与精确统计

BITOP 可以对位图做适用逻辑运算并写入目标键。相同映射下，每天活跃位图取 AND 可表示连续覆盖，OR 表示期间出现过。

目标结果会消耗空间，命令处理量与参与字符串长度有关。大范围操作即使没有输出很多成员，仍可能占用执行时间；Cluster 多键操作还受同槽约束。

Bitmap 能精确统计位，但不直接提供业务 ID 名单。若要找出所有置位 ID，还需扫描和映射；若只需要近似人数，下一章的 HyperLogLog 可能更合适。

## 4. 生命周期与异常

位图属于一个 String 键，可设置键级过期。不能单独给其中一位设置普通 EXPIRE。若业务按天统计，按日分键通常比给每位模拟过期更清楚。

未设置的位读作 0，但业务不能据此断定“这个用户身份一定不存在”。键遗失、过期或过滤条件变更，也可能使查询结果为 0。

## 5. 容量估算

新增算例：若覆盖偏移 0—999999，为一百万个连续位置各保留一位，原始位数据为 125000 字节，约 122.1 KiB，还未计入对象、键名和分配开销。这个纸面估算依赖连续且有界的偏移，不是“一百万活跃用户一定只占这么多”；用户 ID 稀疏且最大偏移很大时，应按最大偏移而不是活跃人数计算。

先确认最大 offset 和映射规则，再检查实际 MEMORY USAGE 与读写模式。评估内存收益时，也要一起考虑大键的复制、持久化和删除成本。

[返回本册目录](/collections/redis/)
