---
id: os-buffer-io
title: 第十一章 bread、缓冲区与 I/O 等待
description: 原笔记通过 Linux 0.11 的 bread 解释“进程发磁盘请求后睡眠，中断完成后唤醒”。这一思路正确，但未展开缓存命中、缓冲区获取和完成后的错误检查。本章依据原版 fs/buffer.c 核对，区分代码片段与完整实现。
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - 操作系统
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: operating-systems
series: os-learning
order: 11
---

# 第十一章 bread、缓冲区与 I/O 等待

> 阅读标签：Linux0.11 buffer cache历史案例。

原笔记通过 Linux 0.11 的 bread 解释“进程发磁盘请求后睡眠，中断完成后唤醒”。这一思路正确，但未展开缓存命中、缓冲区获取和完成后的错误检查。本章依据原版 fs/buffer.c 核对，区分代码片段与完整实现。

## 1. 缓冲区先存在，才能提交请求

原片段声明 buffer_head *bh 后立即使用它，缺少初始化。真实 bread 先通过 getblk(dev,block) 获取相应缓冲区，再判断 b_uptodate。未初始化指针不是简写可以直接执行的程序。

[![Linux 0.11 bread：命中直接返回，失效才读设备](/assets/notes/operating-systems/os-bread.png)](/assets/notes/operating-systems/os-bread.png)

如果缓存数据已有效，就直接返回对应缓冲，无需每次访问磁盘。缓存键、引用计数、锁定与数据有效性分别承担不同职责。

## 2. 缓存未命中的路径

```text
取得指定设备和块号的缓冲
如果数据有效：返回缓冲
提交 READ 请求
等待相关缓冲操作结束
如果数据有效：返回缓冲
否则释放引用并返回失败
```

这是按源码语义改写的伪代码，不是逐行拷贝，也没有实际读取用户磁盘。调用方还要按 API 管理返回缓冲的生命周期。

## 3. 等待为什么循环检查 b_lock？

wait_on_buffer 在原历史实现的同步条件下检查缓冲锁，并通过 sleep_on 等路径等待。被唤醒不代表条件必然仍满足，也不表示当前任务立即获得 CPU，因此重新检查不可省略。

cli/sti 的使用依赖当时单 CPU 与中断模型，不应从这段代码推导现代 SMP 下只关本地中断就保护了所有缓冲路径。现代锁与等待设施要另外阅读。

在0.11中，时钟路径还会因内核CPL返回而不直接抢占该内核执行；等待缓冲时则由sleep_on等显式让出。两条历史要分开：缓存命中直接返回，不进入设备等待；缓存失效才提交READ，完成后即使被唤醒也要复查b_uptodate，失败返回NULL。[调度条件联读](/articles/os-context-switching.html)

## 4. sleep_on 的栈上变量起什么作用？

0.11 的 sleep_on 保存原等待指针到当前调用栈上的 tmp，将自己接入等待关系，调度回来后按代码唤醒先前等待者。原笔记中的 t->state 应核对为实际变量 tmp，不是另一个未声明任务。

这种历史实现并不等于现代通用等待队列 API，也不能只凭“好像构成链表”就随意移植到多核或可中断场景。[Linux 0.11 源码](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)中的 kernel/sched.c 与 fs/buffer.c 应合读。

## 5. 中断完成与业务完成

驱动完成请求后更新状态、解锁并唤醒适用等待者；等待者之后获得调度，复查有效性与错误。read 返回可能还包含后续数据复制与调用层处理，不能把一次设备中断直接当作应用全部业务完成。

设备出错时也可能唤醒等待者，因此“被唤醒”并不意味着读取成功。它与分布式系统中“收到响应不等于业务成功”的区分具有相似的分层思路，但两者并不是同一种协议。

## 联读

这是0.11历史案例；现代文件路径见[文件对象](/articles/os-file-descriptors-persistence.html)和[页缓存/read/mmap](/articles/os-mmap-page-cache.html)，不把两套缓存实现混为同一源码。

[返回本册目录](/collections/operating-systems/)
