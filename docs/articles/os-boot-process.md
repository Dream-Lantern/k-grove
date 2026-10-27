---
id: os-boot-process
title: 第二章 从引导到首个进程
description: “装入内核后跳到 main”只描述了启动过程的一部分。执行环境、地址解释、异常入口、设备和首个用户任务，都需要按依赖顺序准备。本章复盘 Linux 0.11 的 BIOS/x86 启动路线，不作为现代 UEFI 设备的操作说明。
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
order: 2
---

# 第二章 从引导到首个进程

> 阅读标签：Linux0.11 / x86历史启动案例。

“装入内核后跳到 main”只描述了启动过程的一部分。执行环境、地址解释、异常入口、设备和首个用户任务，都需要按依赖顺序准备。本章复盘 Linux 0.11 的 BIOS/x86 启动路线，不作为现代 UEFI 设备的操作说明。

## 1. 启动前 CPU 不是已经处在普通应用环境

固件与引导程序提供最初的执行条件，后续代码逐步建立内核预期的环境。原笔记中的文件名应为 bootsect.s，不是 bootset.s；setup.s、head.s 和 init/main.c 承担不同阶段工作。

[![Linux 0.11：从 bootsect 到 main](/assets/notes/operating-systems/os-boot.svg)](/assets/notes/operating-systems/os-boot.svg)

这些阶段不能任意交换：在相关表和地址环境建立之前，普通 C 代码不能假定栈、地址映射和异常处理已经可用。

## 2. bootsect 与 setup 关注什么？

在该历史版本中，bootsect.s 负责引导装载的早期工作；setup.s 收集部分 BIOS 硬件信息，准备后续内核环境并推进保护模式相关切换。大部分现代操作系统启动还会有其他加载器、内核格式与固件协议，不沿用相同文件名。

本册不提供写启动扇区、修改固件或重装引导的命令。源码阅读中的“磁盘”“段地址”也不能直接对应用户电脑上的 C、D 盘分区。

## 3. head.s 为什么在 main 前？

head.s 组织早期描述符、中断表、分页与进入 C 入口所需条件。GDT、IDT、页目录不是同一张表：一张用于适用段描述，一张用于异常/中断入口，一组用于地址翻译。

学习时，可以为每一步记录它为后续代码建立了哪些前提，例如“下一段代码使用什么地址”“发生异常跳到哪里”“当前栈在哪里”。这比单纯记忆汇编标签更有效。

## 4. main 之后不是整个系统停在一个死循环

0.11 的 main 初始化内存、异常、块设备、终端、调度及其他子系统，随后进入用户态相关路线并 fork 出执行 init 的任务。任务 0 在没有其他可运行任务时承担空闲行为，其循环不能概括为“初始化完成后 CPU 什么也不做”。

init 再处理根设备设置、终端与启动脚本、shell 等工作。精确顺序已按原版 init/main.c 核对，不将课程精简版当成同一份完整代码。[Linux 0.11 源码包](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)

## 5. 与现代启动怎样对照？

可以保留“固件/加载器 → 内核运行条件 → 内核初始化 → 用户空间管理程序”这组概念层次，但不能断言所有平台都先执行 int 0x80、都切换到同一保护模式或都从相同扇区加载。

具体 UEFI 配置、安全启动、initramfs 与系统管理器需要另外固定平台和版本。本轮未逐项验证这些现代启动细节，也没有为原笔记补造安装环境。

[返回本册目录](/collections/operating-systems/)
