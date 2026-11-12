---
id: redis-bitmaps
title: 第八章 Bitmap 与位运算
description: "Bitmap 利用 String 的位表示布尔状态。若用户 ID 可以映射到受控的整数范围，一个位表示当天是否活跃，就能紧凑地保存某类精确标记。"
date: '2026-10-25'
updated: '2026-10-28'
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

记录用户当天是否活跃时，每人只需一个“是/否”状态。Bitmap（位图）利用 String（字符串）的 bit（二进制位，取值为 0 或 1）保存这些标记，**不是独立的 Redis 数据类型**。用户标识能映射到紧凑、有界的位置时，这种存法可以节省空间，String 基础见 [第 3 章](/articles/redis-strings.html)。

本章 `redis` 代码块是可在 `redis-cli` 交互环境输入的 Redis 命令，预期结果是教学推演，假定各示例新键起初不存在、无并发修改；同节接续命令沿用前文数据。以 Redis Open Source 7.2.0 为基准，新参数另标最低版本。

## 1. 先确定偏移映射

offset（位偏移）是从 `0` 开始的位置编号。Redis 使用 MSB-first（Most Significant Bit First，最高有效位在先）位序：第一个字节的最高有效位 MSB 是 offset `0`，最低有效位 LSB（Least Significant Bit）是 `7`；第二个字节的 MSB 是 offset `8`。

```text
第一个字节的位偏移：0 1 2 3 4 5 6 7
仅 offset 0 置为 1：1 0 0 0 0 0 0 0
二进制：10000000    十六进制：0x80

byteIndex = floor(offset / 8)
bitIndex  = 7 - (offset % 8)
```

公式是位置换算，不是 Redis 命令。byteIndex 是从 0 开始的字节索引；bitIndex 是字节内从低位算起的移位数，floor 表示向下取整，`%` 表示取余。因此 offset 0 对应字节 0 内的第 7 位，即最高位。[7.2.0 SETBIT/GETBIT 位序实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/bitops.c)

![Bitmap 位偏移与字节内位权映射](/assets/notes/redis/redis-study-bitmap.svg)

先在新键上只设置 offset 0：

```redis
SETBIT demo:bitmap 0 1
GETBIT demo:bitmap 0
GET demo:bitmap
```

预期依次为旧位值 `0`、当前位值 `1`、一个字节 `0x80`。GET 返回的是二进制字符串，交互客户端可能显示为 `"\x80"`，不是四个可见字符组成的文本；GETBIT 只返回指定位置的 `0` 或 `1`。[SETBIT](https://redis.io/docs/latest/commands/setbit/) · [GETBIT](https://redis.io/docs/latest/commands/getbit/)

再看按用户位置记录活跃标记的例子：

```redis
SETBIT demo:active:day-1 42 1
GETBIT demo:active:day-1 42
BITCOUNT demo:active:day-1
```

预期依次为 `0`、`1`、`1`。42 是位偏移，不是第 42 个字节。位图空间取决于最大 offset，不是实际置位人数；写到位置 k，原始字节长度至少需要 `floor(k / 8) + 1`，中间未写的位置补零。

Redis Open Source 7.2.0 默认 String 长度限制为 512 MB（512 × 1024 × 1024 字节），对应 SETBIT offset 范围 `0` 到 `2^32-1`。源码按 `proto-max-bulk-len` 检查范围，因此这是默认配置边界，不外推为所有自定义配置的硬上限。即使只置一个 bit，接近上限的首次写入也可能分配大块连续内存、补零并造成延迟；理论上限不是业务建议。[SETBIT 分配风险](https://redis.io/docs/latest/commands/setbit/) · [7.2.0 offset 检查](https://raw.githubusercontent.com/redis/redis/7.2.0/src/bitops.c)

反例推演：用户标识 `900000000000` 直接作为 offset，理论上需要约 112.5 GB 的原始位数据，且在上述默认配置下直接超出范围、命令会报错。即使换成范围内的巨大稀疏标识，也可能浪费大量内存；不要为了演示而执行这类大偏移写入。

因此，需要明确映射规则、标识上界，以及映射在不同时间段之间是否保持一致。如果映射已经改变，却继续对旧位图做集合运算，结果就会在业务上失效。

实践中可用连续受控的内部 ID（Identifier，标识符）、稳定映射表或按业务范围分片。稀疏且无界的标识可考虑 [第 6 章：Set](/articles/redis-sets.html) 或 Hash（哈希），不必强行映射成巨大的位图。

## 2. 字节区间与位区间

BITCOUNT 统计值为 1 的位数。传统 start/end 默认按 byte（字节，每字节 8 位）索引解释；Redis Open Source 7.0.0 起可显式指定 BYTE 或 BIT，边界均包含在范围内。接续上一节仅 offset 0 置位的 `demo:bitmap`，再置位 offset 8：

```redis
SETBIT demo:bitmap 8 1
BITCOUNT demo:bitmap 0 2
BITCOUNT demo:bitmap 0 2 BYTE
BITCOUNT demo:bitmap 0 2 BIT
```

预期依次为 `0`、`2`、`2`、`1`。字节区间 0～2 涵盖现有两个字节；位区间 0～2 只含 offset 0 的那个 1。Redis Open Source 7.0.0 之前不支持 BYTE/BIT 单位选项。[BITCOUNT 参数与版本](https://redis.io/docs/latest/commands/bitcount/)

BITPOS 查找第一个指定的位值，返回**整个字符串中的绝对位偏移**，不是所选区间内的相对位置。它默认也按字节解释范围，BYTE/BIT 选项自 Redis Open Source 7.0.0 起支持：

| 查询场景                                   | 返回语义                                       |
| ------------------------------------------ | ---------------------------------------------- |
| 查找 1，范围内有置位                       | 第一个 1 的绝对 offset                         |
| 查找 1，未找到                             | -1                                             |
| 查找 0，未给 end，搜索起点位于已有字符串内 | 可把右侧视为补零，返回字符串末尾之后的第一个 0 |
| 查找 0，显式给 start/end，实际范围内全为 1 | -1，不借用范围外的零                           |

下面用 BITFIELD（位字段命令，可读写指定宽度整数，自 Redis Open Source 3.2.0 起支持）初始化一个全为 1 的八字节字符串。`i64` 表示 64 位有符号整数，`-1` 的这 64 位均为 1；直接 SET 文本 `0xffff...` 不会生成这样的二进制内容。

```redis
BITFIELD demo:full SET i64 0 -1
BITPOS demo:full 0
BITPOS demo:full 0 0 7
BITPOS demo:full 0 0 7 BIT
```

预期依次为 `[0]`（原字段值）、`64`、`-1`、`-1`。不指定范围时，前 64 位全为 1，末尾补零使首个 0 位于 64；第三条只搜索字节 0～7，第四条只搜索位 0～7，二者范围内都没有 0。

不要把补零规则扩大到所有越界情况：对已存在字符串，起点越界形成空范围时返回 `-1`。键不存在则在 7.2.0 中按不存在的数据处理，查找 0 返回 `0`，查找 1 返回 `-1`。[BITPOS 完整规则](https://redis.io/docs/latest/commands/bitpos/) · [7.2.0 实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/bitops.c)

## 3. 交并与精确统计

BITOP 对整个 String 做对应位运算并写入目标键，不是只处理一个用户位置。在相同映射下，可合并不同日期的活跃状态：

| 运算        | 位运算含义             | 业务用途               |
| ----------- | ---------------------- | ---------------------- |
| AND（与）   | 对应位都为 1 才是 1    | 两天都活跃             |
| OR（或）    | 至少一边为 1 就是 1    | 任意一天活跃           |
| XOR（异或） | 对应位不同才是 1       | 比较两天状态变化       |
| NOT（非）   | 对一个源字符串逐位取反 | 反转已分配范围内的状态 |

以下初始化两个新位图，day1 置位 1、3，day2 置位 3、4：

```redis
SETBIT demo:{active}:day1 1 1
SETBIT demo:{active}:day1 3 1
SETBIT demo:{active}:day2 3 1
SETBIT demo:{active}:day2 4 1
BITOP AND demo:{active}:both demo:{active}:day1 demo:{active}:day2
BITOP OR demo:{active}:any demo:{active}:day1 demo:{active}:day2
BITCOUNT demo:{active}:both
BITCOUNT demo:{active}:any
```

四次 SETBIT 预期均返回旧位 `0`；两次 BITOP 均返回结果字符串长度 `1` 字节，后两次计数分别为 `1`、`3`。这是命令结果推演。

AND/OR/XOR 会把较短源的缺失字节按零处理，结果长度取最长源长度；NOT 只能有一个源，结果与该源等长。缺失源按空字符串处理。NOT 也会翻转范围内未分配给用户的位置，业务仍需限制有效 ID 范围，不能直接当作“未活跃用户名单”。[BITOP](https://redis.io/docs/latest/commands/bitop/)

目标键会被结果覆盖并消耗空间，处理成本与源字符串长度及数量有关。Redis Cluster（Redis 集群）下，所有源与目标须在同一个 Hash Slot（哈希槽）；示例的 `{active}` 是 Hash Tag（哈希标签），确保按相同内容计算槽。大范围操作即使没有大回复，仍可能占用执行时间。[Cluster 同槽规则](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#hash-tags)

Bitmap 能精确统计位，但不直接提供业务 ID 名单。若要找出所有置位 ID，还需扫描和映射；若只需要近似人数，下一章的 HyperLogLog 可能更合适。

## 4. 键级期限与零值的业务解释 {#_4-生命周期与异常}

位图属于一个 String 键，可设置键级 TTL（Time to Live，生存时间，用于控制整份数据的过期）。不能单独给其中一位设置普通 EXPIRE。若业务按天统计，按日分键通常比给每位模拟过期更清楚。

未设置的位读作 0，但业务不能据此断定“这个用户身份一定不存在”。键遗失、过期或过滤条件变更，也可能使查询结果为 0。

## 5. 容量估算

容量算例：若覆盖偏移 0—999999，为一百万个连续位置各保留一位，原始位数据为 125000 字节，约 122.1 KiB，还未计入对象、键名和分配开销。这个纸面估算依赖连续且有界的偏移，不是“一百万活跃用户一定只占这么多”；用户 ID 稀疏且最大偏移很大时，应按最大偏移而不是活跃人数计算。

```text
1,000,000 bits / 8 = 125,000 bytes ≈ 122.1 KiB
```

KiB（Kibibyte，二进制千字节）等于 1024 字节。容量判断可以归纳为：

| 场景                       | 空间估算依据                          |
| -------------------------- | ------------------------------------- |
| 连续用户 ID                | 最大 offset 所需的字节数              |
| 稀疏用户 ID                | 映射后的最大 offset，不能只数置位人数 |
| 活跃用户很少但 offset 极大 | 仍需为中间位置分配空间                |

在完成前面小位图示例后，可用以下只读命令查看对象的内存占用：

```redis
MEMORY USAGE demo:bitmap
```

返回整数是内存字节数，按实际结果记录。它与原始位数据长度不同，还涉及键、对象及分配器开销；进程总内存又包含其他全局开销。[MEMORY USAGE](https://redis.io/docs/latest/commands/memory-usage/)

先确认最大 offset 和映射规则，再检查实际 MEMORY USAGE 与读写模式。评估内存收益时，也要一起考虑大键的复制、持久化和删除成本。

简短扩展：BITFIELD 还能把相邻位作为整数使用，例如新键中的一个八位计数器：

```redis
BITFIELD demo:counter SET u8 0 10
BITFIELD demo:counter INCRBY u8 0 1
BITFIELD demo:counter GET u8 0
```

预期逐条返回 `[0]`（旧值）、`[11]`（增加后值）、`[11]`。`u8` 是 8 位无符号整数，`i8` 是 8 位有符号整数；OVERFLOW 可控制溢出时环绕（WRAP）、饱和到边界（SAT）或失败（FAIL）。这些能力自 Redis Open Source 3.2.0 起提供，本章只作入口介绍。[BITFIELD](https://redis.io/docs/latest/commands/bitfield/)

[返回本册目录](/collections/redis/)
