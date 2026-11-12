---
id: redis-internal-encoding
title: 第二十六章 内部编码、SDS、listpack 与渐进 rehash
description: "Redis 的对外类型规定可执行命令，内部编码规定对象在某种规模下的存储布局。一个类型可以根据大小和内容选择不同编码。下面先看紧凑布局，再联系 String 表示与字典 rehash，理解空间、访问成本和转换过程。"
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
order: 26
---

# 第二十六章 内部编码、SDS、listpack 与渐进 rehash

[返回本册目录](/collections/redis/)

Redis 的对外类型规定可执行命令，内部编码规定对象在某种规模下的存储布局。一个类型可以根据大小和内容选择不同编码。下面先看紧凑布局，再联系 String 表示与字典 rehash，理解空间、访问成本和转换过程。

本章以 Redis Open Source 7.2.0 为源码基线；历史变化单独标注。以下代码块使用 Redis 命令；内部编码可以观察，但不能作为跨版本业务协议。

[![Redis 数据结构编码：需要固定版本](/assets/notes/redis/redis-study-encoding.svg)](/assets/notes/redis/redis-study-encoding.svg)

## 1. 小对象的紧凑布局与规模变化 {#_1-为什么小对象采用紧凑编码}

哈希表、指针和独立分配都有元数据成本。元素较少、内容较短时，紧凑连续布局可以节约空间并改善局部性；代价是某些查找或更新要扫描、搬移数据。规模扩大后，Redis 可以转换编码，不能把小对象时的性能结论直接外推。

下面区分对外类型、OBJECT ENCODING 可见名称与内部结构，均以 7.2.0 的适用路径为准：

| Redis 类型 | 内部编码                            | 说明                                                                |
| ---------- | ----------------------------------- | ------------------------------------------------------------------- |
| String     | `int`                               | 值可按适用范围内的整数表示                                          |
| String     | `embstr`                            | 对象头与短字符串数据连续分配                                        |
| String     | `raw`                               | 对象头与动态字符串分别分配                                          |
| List       | `listpack` / `quicklist`            | 小 List 可直接使用 listpack；较大 List 使用节点链式容器             |
| Hash       | `listpack` / `hashtable`            | 紧凑字段值序列或哈希表                                              |
| Set        | `intset` / `listpack` / `hashtable` | 根据内容、规模及创建路径选择                                        |
| Sorted Set | `listpack` / `skiplist`             | 紧凑序列或跳表加字典，后者支持排序和成员查询                        |
| Stream     | `stream`                            | 内部由 Radix Tree（基数树）索引 listpack 消息块，并含消费者组等结构 |

不能把 Stream 的内部“基数树 + listpack”当成 OBJECT ENCODING 的返回字符串。[7.2.0 对象创建实现](https://github.com/redis/redis/blob/7.2.0/src/object.c)、[Set 选择路径](https://github.com/redis/redis/blob/7.2.0/src/t_set.c)、[Stream 消息块实现](https://github.com/redis/redis/blob/7.2.0/src/t_stream.c)

ziplist（压缩列表）属于历史紧凑实现。Hash、Sorted Set 从 Open Source 7.0.0 起使用 listpack（紧凑列表）替代相应 ziplist 编码；7.2.0 为 Set 增加 listpack 路径，但没有取消整数集合 intset。**7.2.0 的小 List 也可直接使用 listpack**，超过相应限制后转为 quicklist，不能把所有 List 都写成 quicklist。[官方版本化编码说明](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/memory-optimization/)、[7.2.0 t_list.c](https://github.com/redis/redis/blob/7.2.0/src/t_list.c)

### ziplist 为什么会连锁更新

ziplist 将多个 Entry（条目）放在连续内存中，减少独立分配和指针成本。条目包含前驱条目的长度 `prevlen`、当前值编码及数据，可顺序遍历，也可向前回退。

Cascade Update（连锁更新）来自前驱长度字段：7.2.0 保留的历史 ziplist 实现中，前驱长度小于 254 字节用 1 字节记录，否则用 5 字节。教学假设：一串条目原本都长 253 字节，前面的条目增长到 254 后，后继的 prevlen 需要多 4 字节，后继自身也可能跨过阈值，进一步影响下一条，形成连续调整。[7.2.0 ziplist 格式与更新实现](https://github.com/redis/redis/blob/7.2.0/src/ziplist.c)

listpack 仍使用连续内存，但每个条目尾部的 `backlen` 记录本条目的编码长度，用于反向定位，不再依赖前驱长度链。修改一个条目不会迫使后继逐个扩展 prevlen；不过插入、删除、扩容仍可能分配内存并搬移后续字节，不能理解为更新总是 O(1)。[7.2.0 listpack 插入实现](https://github.com/redis/redis/blob/7.2.0/src/listpack.c)

| 维度     | ziplist              | listpack                 |
| -------- | -------------------- | ------------------------ |
| 内存布局 | 连续内存、编码条目   | 连续内存、编码条目       |
| 反向定位 | 本条目记录前驱长度   | 条目尾部记录自身编码长度 |
| 连锁更新 | prevlen 可能逐级扩展 | 避免这种前驱长度连锁更新 |
| 更新成本 | 仍有扩容和搬移       | 同样可能扩容和搬移       |
| 学习定位 | 历史实现             | 7.2.0 多种类型的紧凑表示 |

### quicklist 与 listpack 是不同层级

以下结构仅画出 7.2.0 的普通紧凑节点，双向箭头表示链式关系：

```text
Redis List：quicklist 编码
  head → Node 1 ↔ Node 2 ↔ Node 3 ← tail
           |        |        |
        listpack listpack listpack

小 List 的另一条路径：Redis List → 直接 listpack
```

Quicklist（快速列表）把多个节点组成双向链，每个普通 PACKED（打包）节点保存一段 listpack；特殊的大元素路径也可使用 PLAIN（单元素）节点，因此不能说所有节点无例外都是 listpack。节点还可以压缩存储，访问时再解压。这是在链式操作、指针数量和紧凑存储之间的权衡。[7.2.0 quicklist.h](https://github.com/redis/redis/blob/7.2.0/src/quicklist.h)、[quicklist.c](https://github.com/redis/redis/blob/7.2.0/src/quicklist.c)

| 7.2.0 配置               | 含义                                                                                                                          |
| ------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| `list-max-listpack-size` | 控制紧凑块大小或元素数量；默认 -2，目标大小约 8 KiB（Kibibyte，2¹⁰ 字节）；正数按元素数限制，不能视为所有单个元素的硬字节上限 |
| `list-compress-depth`    | 默认 0，不压缩；正数表示两端各保留多少层节点不压缩，内部符合条件的节点可压缩                                                  |

两者都不是整个 List 的最大长度。节点越大，链和分配开销可能越少，但扫描、搬移和压缩成本也可能提高。[7.2.0 List 配置](https://github.com/redis/redis/blob/7.2.0/redis.conf)

## 2. SDS、整数编码与 embstr

SDS（Simple Dynamic String，简单动态字符串）使用显式长度描述字节序列，而不只依赖结尾零字节；容量信息支持适用的增长管理。Redis String 可以保存二进制内容，但业务仍需约定序列化格式与字符编码。

下面是 SDS8/16/32/64 的简化布局，不是实际内存大小图：

```text
Header：len | alloc | flags
buf：   实际数据字节 ... | '\0'
```

`len` 直接记录当前字节长度，因此取长度是 O(1)，不必扫描到零字节。`alloc` 表示数据区容量，不含 Header（头部）和末尾零字节；`flags` 低 3 位指示头部类型；不同类型用不同位宽存长度和容量。`buf` 可以含任意字节，例如 A、零字节、B 的长度是 3，不会被内部零截断；末尾另留 `\0` 方便兼容适用的 C 字符串函数，不负责决定真实长度。

**SDS5 没有独立的 len、alloc 字段。** 它把长度放在 flags 的高 5 位，低 3 位仍表示类型；不能将上图直接套到 SDS5。源码通过 flags 识别具体头部，SDS 指针本身指向数据区。[7.2.0 sds.h 布局与 sdslen](https://github.com/redis/redis/blob/7.2.0/src/sds.h)

教学假设某个可变 SDS 的 `len=3`、`alloc=8`，内容是 `abc`，再追加 `de`：剩余容量足够，只需写入并更新 len 为 5；容量不够时才扩容，也可能改变头部类型。SDS5 不跟踪预留容量，不能套用这个 alloc 案例。空间预留减少部分重复分配，但不是每次追加都不分配，也不是所有字符串编码都能原地修改。[7.2.0 sds.c 的增长路径](https://github.com/redis/redis/blob/7.2.0/src/sds.c)

能表示成适用整数的值、较短字符串和较长字符串，可能采用不同内部编码。以固定标签 Redis 7.2.0 的 object.c 为例，适用的字符串创建路径以 44 字节为 embstr 阈值，长度小于等于 44 时进入对应创建分支。这个数字不是应用协议：整数优化、其他命令路径以及后续更新都可能影响最终编码，不能仅按创建时的长度推断所有对象布局。

```redis
SET demo:encoding:number 123
SET demo:encoding:text hello
OBJECT ENCODING demo:encoding:number
OBJECT ENCODING demo:encoding:text
MEMORY USAGE demo:encoding:text
```

这是会写入示例键的教学观察。假设 7.2.0 的普通 SET 路径，预期 number 的编码为 `int`，text 为 `embstr`；两次 SET 预期返回 `OK`。MEMORY USAGE 返回字节估算，不编造固定数值；较长非整数内容通常走 raw，更新路径也可能改变编码。[Redis 7.2.0 对象实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/object.c)、[OBJECT ENCODING](https://redis.io/docs/latest/commands/object-encoding/)

String 命令与业务边界见[第三章](/articles/redis-strings.html)。

## 3. 紧凑阈值中的空间与延迟权衡 {#_3-调大紧凑编码阈值不是纯收益}

为了节省内存而大幅扩大线性扫描结构，可能使查询、更新和编码转换产生明显的尾延迟。因此，评估时应覆盖数据分布、读写比例、转换瞬间和最坏规模，不能只比较静态内存占用。

也不能笼统保证“元素删除后所有编码都会自动退回”。不同类型、版本和操作路径的转换行为不同；需要观察实际对象和匹配源码。

教学示例假设键此前不存在，Redis Open Source 7.2.0 使用默认 `hash-max-listpack-entries 512`、`hash-max-listpack-value 64`，且无并发修改：

```redis
HSET demo:encoding:profile name alice
OBJECT ENCODING demo:encoding:profile
HSET demo:encoding:profile note 12345678901234567890123456789012345678901234567890123456789012345
OBJECT ENCODING demo:encoding:profile
```

预期两个 HSET 各新增一个字段，返回 1；前一次编码为 listpack，后一次为 hashtable，因为 note 的值有 65 个单字节字符，超过 64 字节阈值。虽只有两个字段，也会转换；字段数量和字段/值长度都需要检查。转换要分配哈希表、遍历并建立条目，消耗 CPU（Central Processing Unit，中央处理器）和内存。[7.2.0 hashTypeTryConversion / hashTypeSet](https://github.com/redis/redis/blob/7.2.0/src/t_hash.c)

Hash 的业务建模见[第四章](/articles/redis-hashes.html)，Sorted Set 的排序访问见[第七章](/articles/redis-sorted-sets.html)。Hash Field Expiration（Hash 字段过期）是 Open Source 7.4.0 起的独立能力，不能从本章 7.2.0 编码表推断其布局或支持情况。[HEXPIRE 版本](https://redis.io/docs/latest/commands/hexpire/)

## 4. 渐进 rehash 解决一次搬迁过重

![两张哈希表的过渡](/assets/notes/redis/redis-study-rehash.svg)

扩容或收缩需要将条目搬到新的桶位置。一次搬完可能造成长暂停，渐进 rehash 则让旧表与新表在过渡期间共同存在，按步骤迁移桶和条目；查找与更新要正确处理两表状态。

Rehash（重新散列）需要按新表容量重新确定桶位置。以下用 ht[0]、ht[1] 指代旧表、新表；7.2.0 源码实际用 `ht_table[0/1]` 等数组描述，不是照搬旧版本结构体名：

```text
稳定：ht[0] 保存全部条目，ht[1] 为空，rehashidx=-1
→ 创建新桶数组 ht[1]，开始 rehash，rehashidx=0
→ 旧表保存尚未搬迁条目，新表保存已迁移条目和新增条目
→ 查找：先查旧表，必要时再查新表
→ 按 rehashidx 逐步迁移旧表桶中的条目，重新计算新桶位置
→ 旧表条目搬空：释放旧桶数组，新表成为 ht[0]
→ 清空第二张表的描述，rehashidx 回到 -1
```

`rehashidx` 是旧表迁移进度索引，不是已迁移键数。查找、删除和替换已有条目要处理两表状态；**新增条目进入新表**，不表示每次更新都把已有条目强制搬过去。迁移通常以桶为步骤，同一桶可能有多个条目，一步不保证恒定耗时；创建新桶数组也有分配成本。[7.2.0 dictFind、dictRehash 与插入路径](https://github.com/redis/redis/blob/7.2.0/src/dict.c)

推进工作有两个来源：部分普通字典操作调用 `_dictRehashStep`；`serverCron`（服务器周期任务）的数据库维护路径也会在 `activerehashing` 开启等条件下，对数据库键和过期字典安排带时间预算的迁移。这些都在主线程相关路径执行，**不是创建独立后台线程完成所有 rehash**；时间预算也不是严格的单步延迟上限。[7.2.0 incrementallyRehash / databasesCron](https://github.com/redis/redis/blob/7.2.0/src/server.c)

安全迭代器等路径可通过 `pauserehash` 暂停推进，以免遍历时漏掉或重复条目。有 fork 子进程时，7.2.0 主进程会采用避免扩容/rehash 的策略，周期主动迁移也会避开活动子进程；但特定强制扩容条件仍可能允许增长，不能概括为“fork 期间一律不扩容”。目的是减少 COW（Copy-On-Write，写时复制），不是消除全部峰值。[7.2.0 dict.c](https://github.com/redis/redis/blob/7.2.0/src/dict.c)、[updateDictResizePolicy](https://github.com/redis/redis/blob/7.2.0/src/server.c)

应用层通常不应依赖某个装载因子或迁移步数。学习源码时应固定标签，理解约束和数据结构；优化线上负载时，仍先检查键模型、对象大小、访问热点与实际延迟。

内存指标、峰值与碎片的诊断方法见[第二十五章](/articles/redis-memory-eviction.html)。
