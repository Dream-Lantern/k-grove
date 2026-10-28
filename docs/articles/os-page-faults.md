---
id: os-page-faults
title: 第十八章 缺页异常与按需分配
description: "当内存访问无法依据当前翻译或权限完成时，处理器会报告缺页异常。内核先检查地址与访问类型，再判断是建立合法映射、完成按需分配或写时复制，还是处理无法修复的访问。"
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
order: 18
---

# 第十八章 缺页异常与按需分配

> 阅读标签：通用缺页分类 / Linux统计口径。

当内存访问无法依据当前翻译或权限完成时，处理器会报告缺页异常。内核先检查地址与访问类型，再判断是建立合法映射、完成按需分配或写时复制，还是处理无法修复的访问。这个过程既可能完成正常的延迟工作，也可能报告程序错误。

## 1. TLB miss、Page Fault 与非法地址

TLB 未命中可以通过有效页表完成翻译；页表存在性或权限等条件不满足才可能触发缺页异常。缺页与当前指令访问相关，属于同步异常，与异步的外设中断分别理解。

[![Page Fault：合法缺页与权限异常](/assets/notes/operating-systems/os-fault.svg)](/assets/notes/operating-systems/os-fault.svg)

进入异常处理后，内核会检查内存区域与访问类型。不能只要找不到页框就分配新页，否则可能错误放行越界访问。

## 2. 三类合法延迟工作

匿名内存首次使用可以建立适用的零填充页面；文件映射可以联系页缓存或读取文件；写时复制可以在写保护异常时分离私有数据。swap 中的匿名页又有其读取路径。

不需要读盘的情况也会有开销：分配、清零、映射、同步与 TLB 更新都可能消耗时间。不能把 minor fault 写成“没有成本，只补一下 MMU 表”。[Linux 6.6 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)

## 3. minor 与 major 的计数口径

Linux 的 minor fault 一般指未要求从磁盘加载页面的缺页处理，涵盖零页、某些 COW 或已有缓存页等情况，不只是“别的进程已经载入”。major fault 则涉及相应页面加载 I/O 的情况。

这些指标是系统口径，不应与 Windows 的 hard/soft fault 每项完全画等号。累计 major fault 非零也不代表当前正在颠簸，要看时间窗和负载。[getrusage(2)](https://man7.org/linux/man-pages/man2/getrusage.2.html)

## 4. 无法修复的访问与信号处理 {#_4-非法访问怎样结束}

对无效地址或不允许的访问，内核可能向任务发送适用信号；Linux 常见 SIGSEGV，特定映射错误也可能是 SIGBUS。不能把任何空指针访问或越界都写成“永远同一种信号且立即整个系统停止”。

线程可能有信号处理机制，但不能凭捕获信号就认定任意损坏程序可安全继续。权限错误是访问错误，不能由普通分配自动“修复”。

## 5. Linux 0.11 的 do_no_page 路径 {#_5-原-do-no-page-片段的校正}

0.11 中相应偏移计算采用 address-current->start_code，结合条件比较确定访问位置；后续根据状态选择共享可执行页、分配零页或读取后备块。

阅读各分支时，先确认它的地址条件、映射状态与错误检查。异常成功处理后，可以返回原指令重试；无法修复时则进入内核错误路径。这里只解释源码路径，不提供缺少上下文的可运行 C 片段。

[返回本册目录](/collections/operating-systems/)
