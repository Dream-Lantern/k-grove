---
id: os-system-calls
title: 第三章 系统调用、特权级与异常入口
description: POSIX 规定一组接口与行为，不规定所有 CPU 必须通过同一条指令进入内核。系统调用、运行库函数与机器陷入入口是三个层次，读源码时应从接口契约逐步落到具体 ABI。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 3
---

# 第三章 系统调用、特权级与异常入口

> 阅读标签：通用系统调用 / 现代Linux ABI对照。

POSIX 规定一组接口与行为，不规定所有 CPU 必须通过同一条指令进入内核。系统调用、运行库函数与机器陷入入口是三个层次，读源码时应从接口契约逐步落到具体 ABI。

## 1. printf 不等于每次立即 write

printf 在用户态进行格式化，并可能受标准 I/O 缓冲影响；运行库在适当时机调用底层写接口。一次 printf 可能不立即触发 write，多次输出也可能合并为一次系统调用。

![运行库、体系结构入口与内核处理](/assets/notes/operating-systems/os-syscall.svg)

因此，“printf→int 0x80→write”这样的课堂简图，并不表示跨架构、逐次调用的一一对应关系。解释成功返回时，也需区分格式化缓冲、内核接收和最终设备完成。

## 2. x86 的 0 和 3 是特定架构的级别编号

常见 x86 系统使用 ring 0 作为内核执行级、ring 3 作为用户执行级；CPL 是 Current Privilege Level，DPL 是 Descriptor Privilege Level，RPL 是 Requestor Privilege Level。

权限检查依目标段、门、指令与分页规则而异，不能把 DPL≥CPL、DPL≥RPL 写成所有跳转和访问的通用充分条件。普通应用也不能通过给某个变量赋 0，就获得内核权限。

## 3. 受控入口做了什么？

系统设置允许用户调用的入口，硬件与入口代码按 ABI 保存返回所需状态、建立适用栈和执行环境，再根据系统调用号及参数处理请求。权限检查、用户指针访问和错误返回都属于边界。

Linux x86-32 的 int 0x80 是一种路径，x86-64 有其 syscall ABI，其他架构又不同。系统调用编号、参数寄存器和返回机制不能混抄。[Linux syscall(2) 的架构表](https://man7.org/linux/man-pages/man2/syscall.2.html)

## 4. 中断、异常和系统调用

外设中断通常由异步外部事件触发；缺页等异常与当前指令执行相关；系统调用是程序主动请求内核服务。它们可能共用部分低层入口设施，但语义不同。

进入内核不意味着一定会发生调度，也不一定立即切换地址空间。如果请求可以立即完成，原任务可直接返回；如果需要等待 I/O，则可能先调度其他任务。

## 5. 错误应按 API 解释

运行库常将底层错误转换为 -1 与 errno，但具体接口有各自返回规则。不能把所有返回 0 都理解成“成功写入全部内容”，例如 read 返回 0 往往表示到达文件末尾，write 还可能短写。

以纸面流程为例：请求写入 100 字节，但返回值表示只写入了 40 字节。调用方应根据接口和错误条件处理剩余部分，不能将第一次非负返回视为全部业务已完成。这里只解释语义，未调用实际文件或设备。

[返回本册目录](/collections/operating-systems/)
