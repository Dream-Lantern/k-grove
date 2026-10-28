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

[![Redis 数据结构编码：需要固定版本](/assets/notes/redis/redis-study-encoding.svg)](/assets/notes/redis/redis-study-encoding.svg)

## 1. 小对象的紧凑布局与规模变化 {#_1-为什么小对象采用紧凑编码}

哈希表、指针和独立分配都有元数据成本。元素较少、内容较短时，紧凑连续布局可以节约空间并改善局部性；代价是某些查找或更新要扫描、搬移数据。规模扩大后，Redis 可以转换编码，不能把小对象时的性能结论直接外推。

ziplist 按其历史版本理解。较新版本的 Hash、Sorted Set 常见 listpack 路线，7.2 还为 Set 提供相应紧凑编码配置。List 的 quicklist 与内部紧凑节点也应按版本理解，不再统一描述成一条普通双向链表。[带版本的内存编码说明](https://redis.io/docs/latest/operate/oss_and_stack/management/optimization/memory-optimization/)

## 2. SDS、整数编码与 embstr

SDS 使用显式长度描述字节序列，而不只依赖结尾零字节；容量信息支持适用的增长管理。Redis String 可以保存二进制内容，但业务仍需约定序列化格式与字符编码。

能表示成适用整数的值、较短字符串和较长字符串，可能采用不同内部编码。以固定标签 Redis 7.2.0 的 object.c 为例，适用的字符串创建路径以 44 字节为 embstr 阈值，长度小于等于 44 时进入对应创建分支。这个数字不是应用协议：整数优化、其他命令路径以及后续更新都可能影响最终编码，不能仅按创建时的长度推断所有对象布局。

```redis
SET demo:encoding:number 123
SET demo:encoding:text hello
OBJECT ENCODING demo:encoding:number
OBJECT ENCODING demo:encoding:text
MEMORY USAGE demo:encoding:text
```

这是会写入示例键的教学观察，实际输出随版本、构建和配置变化。OBJECT ENCODING 不是稳定的跨版本业务接口。[Redis 7.2.0 对象实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/object.c)

## 3. 紧凑阈值中的空间与延迟权衡 {#_3-调大紧凑编码阈值不是纯收益}

为了节省内存而大幅扩大线性扫描结构，可能使查询、更新和编码转换产生明显的尾延迟。因此，评估时应覆盖数据分布、读写比例、转换瞬间和最坏规模，不能只比较静态内存占用。

也不能笼统保证“元素删除后所有编码都会自动退回”。不同类型、版本和操作路径的转换行为不同；需要观察实际对象和匹配源码。

## 4. 渐进 rehash 解决一次搬迁过重

![两张哈希表的过渡](/assets/notes/redis/redis-study-rehash.svg)

扩容或收缩需要将条目搬到新的桶位置。一次搬完可能造成长暂停，渐进 rehash 则让旧表与新表在过渡期间共同存在，按步骤迁移桶和条目；查找与更新要正确处理两表状态。

以 Redis 7.2.0 的字典实现为例，普通操作可以推进迁移，后台工作也有时间预算；迁移完成后，旧表被释放，结构进入稳定状态。这里的“渐进”并不意味着迁移必然由异步线程独立完成，更不代表零额外内存、零延迟。[Redis 7.2.0 dict.c](https://raw.githubusercontent.com/redis/redis/7.2.0/src/dict.c)

应用层通常不应依赖某个装载因子或迁移步数。学习源码时应固定标签，理解约束和数据结构；优化线上负载时，仍先检查键模型、对象大小、访问热点与实际延迟。
