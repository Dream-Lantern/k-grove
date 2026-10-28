---
id: os-version-references
title: 附录 A：版本与技术依据
description: "汇总 Linux 0.11、现代 Linux、POSIX 与体系结构资料的来源，区分历史实现、跨平台概念和待核验细节。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: reference
tags:
  - 操作系统
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: operating-systems
series: os-learning
order: 90
---

# 附录 A：版本与技术依据

核对日期：2026-10-22。本册按历史实现、跨平台概念和现代 Linux 接口分别组织依据，尚未指定实际安装环境。查阅寄存器、结构体或参数时，应先定位文章对应的版本与平台。

## 1. Linux 0.11 源码范围

采用 [kernel.org 的原始历史压缩包](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)，只读核对如下文件，没有编译、启动或修改系统。下载指纹保存在私有处理记录，不冒充独立签名验证。

| 文件                                          | 对应主题                                       |
| --------------------------------------------- | ---------------------------------------------- |
| boot/bootsect.s、setup.s、head.s、init/main.c | 启动阶段、早期地址环境、任务 0 与 init         |
| kernel/sched.c、include/linux/sched.h         | counter 调度、sleep_on、wake_up、TSS 切换      |
| kernel/system_call.s、kernel/fork.c           | 入口、进程建立、段基址、子返回值               |
| mm/memory.c                                   | copy_page_tables、写保护、引用计数、do_no_page |
| fs/buffer.c、kernel/blk_drv/ll_rw_blk.c       | bread、缓冲状态、请求与完成                    |

课程修改版可能以软件内核栈切换替代原版机制，阅读时需使用该课程的完整源码，与原版路径分别对照。正文使用机制说明和已注明的伪代码，未提供编译通过记录。

## 2. 对照资料

| 内容             | 主要依据                                                                                                                                                                                      | 条件                                 |
| ---------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ |
| 进程、线程与 API | [fork](https://man7.org/linux/man-pages/man2/fork.2.html)、[pthreads](https://man7.org/linux/man-pages/man7/pthreads.7.html)、[syscall](https://man7.org/linux/man-pages/man2/syscall.2.html) | 现代 Linux API，不反向证明历史特例   |
| 条件变量         | [POSIX pthread_cond_wait](https://man7.org/linux/man-pages/man3/pthread_cond_wait.3p.html)                                                                                                    | 原子释放并等待、返回重持锁、重查谓词 |
| 锁               | [Linux 6.6 spinlocks](https://docs.kernel.org/6.6/locking/spinlocks.html)、[OSTEP Locks](https://pages.cs.wisc.edu/~remzi/OSTEP/threads-locks.pdf)                                            | 多核、内存顺序与上下文条件           |
| 信号量与死锁     | [OSTEP Semaphores](https://pages.cs.wisc.edu/~remzi/OSTEP/threads-sema.pdf)、[Concurrency Problems](https://pages.cs.wisc.edu/~remzi/OSTEP/threads-bugs.pdf)                                  | 教学模型，具体 API 另行核对          |
| 地址与回收       | [Linux 6.6 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)、[Page Tables](https://docs.kernel.org/mm/page_tables.html)                                                    | 页大小、级数与架构不同               |
| 分配与置换       | [OSTEP 空闲管理](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-freespace.pdf)、[页面策略](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-beyondphys-policy.pdf)                                        | 算法抽象，不是当前内核唯一策略       |
| 现代演进         | [EEVDF](https://docs.kernel.org/scheduler/sched-eevdf.html)、[6.6 Multi-Gen LRU](https://docs.kernel.org/6.6/admin-guide/mm/multigen_lru.html)                                                | 索引与版本对照，不自动启用功能       |
| 文件、缺页统计   | [mmap](https://man7.org/linux/man-pages/man2/mmap.2.html)、[fsync](https://man7.org/linux/man-pages/man2/fsync.2.html)、[getrusage](https://man7.org/linux/man-pages/man2/getrusage.2.html)   | 按 Linux 口径，不与 Windows 逐项等同 |
| 另一教学架构     | [xv6 RISC-V 2024 教材](https://pdos.csail.mit.edu/6.1810/2024/xv6/book-riscv-rev4.pdf)                                                                                                        | 不混抄 x86 寄存器与陷入实现          |

现代 UEFI 的具体固件调用顺序尚待对应规范核验，这里仅介绍引导阶段的职责。POSIX 名称不用于证明所有系统调用都采用 int 0x80；硬件权限也没有简化成适用于所有指令的单一 DPL 不等式。

原图涉及第三方资料，授权尚未逐一核实；新图则是重新表达机制的教学抽象。本地候选稿并不意味着已获公开发布授权，文中的代码与系统参数也不代表操作授权。

[返回本册目录](/collections/operating-systems/)

## 关键规则的来源定位 {#本轮复核的精确定位}

- C11数据竞争：[WG14 N1570 §5.1.2.4 ¶25](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)，抽象交错不等于未同步C程序的合法结果清单。
- 多线程fork：[fork(2) DESCRIPTION中的线程与异步信号安全限制](https://man7.org/linux/man-pages/man2/fork.2.html)。
- Linux0.11：kernel/sched.c的do_timer、kernel/fork.c的copy_mem、mm/memory.c的copy_page_tables与include/linux/sched.h的页目录字段，核查方式为只读源码对照。
- 普通文件映射同步：[msync(2) DESCRIPTION / VERSIONS](https://man7.org/linux/man-pages/man2/msync.2.html)，生命周期不代替持久化屏障。
