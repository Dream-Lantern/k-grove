---
id: os-version-references
title: 附录 A：版本与技术依据
description: "汇总 Linux 0.11、现代 Linux、POSIX 与体系结构资料的来源，区分历史实现、跨平台概念和待核验细节。"
date: '2026-10-25'
updated: '2026-11-04'
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

核对日期：**2026-11-04**。范围为本册第 1～21 章及附录 A/B，共 23 篇；以当前工作树为准，不用远程旧稿覆盖已完成修订。下面区分原始源码、接口规范、现代实现、数值模型与实际实验。发布日期不代表每个实验都曾运行。

## 1. Linux 0.11 源码范围

固定使用 [kernel.org Linux 0.11 原始历史包](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)。本轮重新只读核对以下 11 个文件，并将本地解压文件与压缩包成员逐字节比较；未编译、启动或修改历史内核。

| 源文件                     | 实际定位与本册用途                                                 |
| -------------------------- | ------------------------------------------------------------------ |
| boot/bootsect.s            | start、引导搬移与转入 setup；第 2 章                               |
| boot/setup.s               | lmsw 设置 PE、远跳转进入保护模式；第 2 章                          |
| boot/head.s                | startup_32、setup_paging、进入 _main；第 2、13、17 章              |
| init/main.c                | main、move_to_user_mode、首次 fork、init；第 2、17 章              |
| kernel/sched.c             | schedule、do_timer、sleep_on、wake_up；第 6、7、9、11 章           |
| kernel/system_call.s       | _system_call、_timer_interrupt、ret_from_sys_call；第 3、6 章      |
| kernel/fork.c              | copy_process、copy_mem、任务槽段基址；第 4、17 章                  |
| include/linux/sched.h      | tss_struct、INIT_TASK、switch_to(n) 与 ljmp；第 6、17 章           |
| mm/memory.c                | copy_page_tables、un_wp_page、do_wp_page、do_no_page；第 17、18 章 |
| fs/buffer.c                | getblk、bread、bread_page、wait_on_buffer；第 11、18 章            |
| kernel/blk_drv/ll_rw_blk.c | ll_rw_block、make_request；第 11 章                                |

本轮对本地 `linux-0.11.tar.gz` 计算的 SHA-256 为：

```text
660997a6b1f03ee5aadce0ac806ffa653dedf1dea6d82c6731f9c9ddf0092673
```

用途是标识此次核对的压缩包字节、帮助复核版本，不是数字签名或独立第三方认证。读者应从上述公开来源自行获取、核验文件；本地处理记录不能替代公开源码依据。

四条历史边界尤其重要：

- 原版 switch_to 使用 TSS（Task State Segment，任务状态段）与远跳转；课程改写成软件内核栈切换时，应引用该课程自己的完整版本，不能倒推原版已经这样做。
- schedule 扫描普通任务槽，counter 为零与没有普通可运行候选是不同分支；do_timer 的被中断 CPL 判断限制的是该时钟路径，内核仍可显式等待并调度。
- copy_page_tables 的 `from==0`、0xA0 项和低内存分支影响任务 0 首次 fork；它不能代替普通受管理页的写时复制（COW，Copy-On-Write）模型。
- do_wp_page 中代码区拒绝分支在该原版里被 `#if 0` 禁用；do_no_page 按 executable/end_data 等历史字段处理，并没有现代虚拟内存区域（VMA，Virtual Memory Area）的完整权限流程。准确顺序见第 17、18 章。

## 2. 对照资料

### 章节到技术来源

表内“源码/文档”表示事实依据类型，不意味着整个章节已获形式化证明或动态验收；计算与实验状态见后表。

| 章节                                                           | 关键机制                       | 版本/平台与核心依据                                                                                                                                                                                                                                            | 验证性质                                |
| -------------------------------------------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| [1 职责与执行](/articles/os-overview.html)                     | 抽象、隔离、并发与读取         | [OSTEP 教材](https://pages.cs.wisc.edu/~remzi/OSTEP/)及 read 接口                                                                                                                                                                                              | 文档、教学流程                          |
| [2 启动](/articles/os-boot-process.html)                       | BIOS→保护模式→分页→任务 0/1    | 上表 boot 三文件、init/main.c；[Intel 手册](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)                                                                                                                               | 源码、架构文档；未启动旧内核            |
| [3 系统调用](/articles/os-system-calls.html)                   | 用户/内核入口与返回            | 0.11 system_call.s；[Linux v6.12 entry_64.S](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/entry_64.S)、[syscall(2)](https://man7.org/linux/man-pages/man2/syscall.2.html)                                                                       | 源码与接口，区分 x86-32/64              |
| [4 进程](/articles/os-process-lifecycle.html)                  | fork/exec/wait、打开文件描述   | [fork(2)](https://man7.org/linux/man-pages/man2/fork.2.html)、[execve(2)](https://man7.org/linux/man-pages/man2/execve.2.html)、[waitpid(2)](https://man7.org/linux/man-pages/man2/waitpid.2.html)                                                             | 文档；正文实验有明确边界                |
| [5 线程](/articles/os-threads-stacks.html)                     | 共享空间、独立栈、映射模型     | [pthreads(7)](https://man7.org/linux/man-pages/man7/pthreads.7.html)、[pthread_create(3)](https://man7.org/linux/man-pages/man3/pthread_create.3.html)                                                                                                         | 接口与模型；地址/顺序不固定             |
| [6 上下文](/articles/os-context-switching.html)                | 陷入帧、调度现场、TSS          | 0.11 sched.h、sched.c、system_call.s；Intel Vol.3                                                                                                                                                                                                              | 源码与架构，非全部现代实现              |
| [7 调度](/articles/os-cpu-scheduling.html)                     | FCFS/SJF/RR、counter、公平调度 | 0.11 schedule/do_timer；[Linux 6.12 CFS](https://docs.kernel.org/6.12/scheduler/sched-design-CFS.html)、[EEVDF](https://docs.kernel.org/6.12/scheduler/sched-eevdf.html)                                                                                       | 源码、数值模拟                          |
| [8 原子与锁](/articles/os-atomic-locks.html)                   | 数据竞争、原子和发布           | [WG14 N1570 §5.1.2.4、§7.17](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)、[Linux 6.6 锁类型](https://docs.kernel.org/6.6/locking/locktypes.html)                                                                                               | 标准草案依据、平台实现另限              |
| [9 同步等待](/articles/os-semaphores-conditions.html)          | 谓词、条件变量、信号量         | [POSIX 条件变量语义](https://man7.org/linux/man-pages/man3/pthread_cond_wait.3p.html)、[sem_overview(7)](https://man7.org/linux/man-pages/man7/sem_overview.7.html)                                                                                            | 接口、时序模型                          |
| [10 死锁](/articles/os-deadlocks.html)                         | 等待环、安全状态、避免         | [Dijkstra EWD623](https://www.cs.utexas.edu/~EWD/transcriptions/EWD06xx/EWD623.html)、[OSTEP 并发问题](https://pages.cs.wisc.edu/~remzi/OSTEP/threads-bugs.pdf)                                                                                                | 模型、整数模拟；不是 Linux 通用锁算法   |
| [11 缓冲 I/O](/articles/os-buffer-io.html)                     | getblk/bread、锁与有效位       | 0.11 fs/buffer.c、ll_rw_blk.c                                                                                                                                                                                                                                  | 源码、三路径时序；不等于现代 page cache |
| [12 FD 与保存](/articles/os-file-descriptors-persistence.html) | 共享偏移、短写、fsync/rename   | [open(2)](https://man7.org/linux/man-pages/man2/open.2.html)、[write(2)](https://man7.org/linux/man-pages/man2/write.2.html)、[fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)、[rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html) | 接口与受限实验，非断电认证              |
| [13 地址与分段](/articles/os-address-spaces-segmentation.html) | 逻辑/线性/物理、段检查、VMA    | Intel Vol.3 保护模式；[Linux 6.6 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)                                                                                                                                                           | 架构、地址模拟                          |
| [14 分配](/articles/os-memory-allocation.html)                 | Fit、分割合并、malloc 层次     | [OSTEP Free-Space](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-freespace.pdf)、[malloc(3)](https://man7.org/linux/man-pages/man3/malloc.3.html)                                                                                                                  | 模型和整数模拟                          |
| [15 页表](/articles/os-paging-page-tables.html)                | 10/10/12 拆分、层级与权限      | Intel Vol.3；[Linux 页表](https://docs.kernel.org/mm/page_tables.html)                                                                                                                                                                                         | 固定 x86-32 非 PAE 模型、数值模拟       |
| [16 TLB](/articles/os-tlb.html)                                | 翻译缓存、标记、失效与 EAT     | Intel Vol.3 Caching Translation Information；[Linux TLB 接口](https://docs.kernel.org/core-api/cachetlb.html)                                                                                                                                                  | 架构与模拟，非真实硬件时延              |
| [17 COW](/articles/os-linux011-copy-on-write.html)             | 任务槽、只读共享、独占写       | 0.11 copy_mem/copy_page_tables/un_wp_page                                                                                                                                                                                                                      | 源码、引用状态推演；普通 fork 实验另限  |
| [18 缺页](/articles/os-page-faults.html)                       | 不存在/保护、匿名/文件后备     | 0.11 mm/page.s、do_no_page/do_wp_page；[getrusage(2)](https://man7.org/linux/man-pages/man2/getrusage.2.html)                                                                                                                                                  | 源码、现代接口实验；不混同路径          |
| [19 回收](/articles/os-page-replacement-swap.html)             | 置换、工作集与 OOM             | [OSTEP 页面策略](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-beyondphys-policy.pdf)、[Linux 6.6 MGLRU](https://docs.kernel.org/6.6/admin-guide/mm/multigen_lru.html)                                                                                             | 纯模拟与版本文档                        |
| [20 映射](/articles/os-mmap-page-cache.html)                   | read/mmap、可见性与同步        | [mmap(2)](https://man7.org/linux/man-pages/man2/mmap.2.html)、[msync(2)](https://man7.org/linux/man-pages/man2/msync.2.html)、[Page Cache](https://docs.kernel.org/mm/page_cache.html)                                                                         | 文档与临时文件实验                      |
| [21 排查](/articles/os-troubleshooting.html)                   | CPU/内存/等待证据              | [PSI](https://docs.kernel.org/accounting/psi.html)、[cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)、[proc(5)](https://man7.org/linux/man-pages/man5/proc.5.html)                                                                              | 接口、只读兼容检查；Case 为假设         |

### 各资料的版本边界

Linux 0.11 固定历史版本；Linux 6.6/6.12 文档按标题给出版本；不带版本的 docs.kernel.org 和在线 man-pages 是本次查阅的滚动资料，不能据此证明所有旧版本行为。POSIX 接口与 C 语言内存模型各有规则：N1570 是公开的 C11 委员会草案，不冒称最终标准正文；man-pages 的 3p 页面提供 POSIX 语义参考，具体版本见页面 STANDARDS/版权说明。

x86 32 位保护模式、x86-64 长模式与 [xv6 RISC-V 2024 教材](https://pdos.csail.mit.edu/6.1810/2024/xv6/book-riscv-rev4.pdf)不能混用寄存器和陷入行为。PCID（Process-Context Identifier，进程上下文标识）是 x86 的特定机制；ASID（Address Space Identifier，地址空间标识）用于其他相应架构语境，不能简单互换。四/五级分页取决于架构、硬件及配置，不改写本文非 PAE 两级纸面模型。

EEVDF 从 Linux 6.6 开始替代部分公平调度选择机制；不表示实时类别全部消失，也不表示当前运行环境采用了它。MGLRU 的支持与启用另有配置要求。PREEMPT_RT（实时抢占配置）下部分锁语义发生变化，须同时区分 spinlock_t 和 raw_spinlock_t，不能把普通配置结论直接搬过去。

现代 UEFI 固件的具体调用次序仍需对应平台规范；正文仅作职责对照。历史 bread 的块缓冲、现代普通文件页缓存、Direct I/O 与 DAX（Direct Access，直接访问）是不同路径，不以一张流程图包揽。

### 验证状态与本次实际检查

| 状态     | 含义与限制                                               |
| -------- | -------------------------------------------------------- |
| 源码核验 | 已阅读并定位明确版本的文件/函数；不等于编译启动成功      |
| 文档核验 | 官方接口、架构手册或明确版本文档支持；注意平台与标准版本 |
| 数值复核 | 计算或纯模拟断言通过；不等于测量了真实硬件               |
| 实验通过 | 在注明环境运行了具体程序及检查；不能外推全部故障路径     |
| 教学抽象 | 为解释而限定或省略细节，不能冒充原始执行日志             |
| 待验证   | 缺少环境、来源或证据，必须保留限制                       |

本次检查覆盖 23 篇的元数据、排序、旧锚点、站内引用和实际配图，以及 Linux 0.11 上表源码。调度、地址/分配/页表/TLB/置换和银行家算法按正文程序重新复核。前序局部实验使用 WSL2 Ubuntu、x86_64、Linux 5.15.167.4、GCC 11.4.0/Python 3.10.12；这些是站点维护者的本地记录，不是第三方证明。

已运行的 mmap 临时文件实验观察到：私有写 X 不改变文件 ABCDEFGH，共享写 Y 可由普通读取观察，MS_SYNC 返回成功。它没有证明断电恢复、任意文件系统行为或多字段事务。只读命令兼容检查不等于真实业务根因诊断；该 WSL 环境没有 PSI 接口，v2 所需内存/配额控制器也不可用，相关指标仍待支持环境验证。

Linux 0.11 未进行动态运行；真实 OOM、颠簸、死锁、SIGBUS、断电恢复、mmap/read 性能对比未执行。质量脚本和最终本地构建的命令、退出状态与集成检查结果见本轮交付报告；构建成功只能支持站点集成，不证明全部技术结论。

## 关键规则的来源定位 {#本轮复核的精确定位}

- C11 数据竞争：N1570 §5.1.2.4 ¶25；两个冲突、至少一个非原子且未建立 happens-before 的不同线程操作会导致未定义行为，不能靠列举交错穷尽结果。
- 多线程 fork：fork(2) DESCRIPTION 中只有调用线程复制到子进程及 exec 前异步信号安全限制；父进程其他线程持有的锁状态不能自动修复。
- 条件变量：pthread_cond_wait 的原子解锁并等待、返回前重新持锁；应用必须按谓词用 while 重查，而不是把通知当资源计数。
- Linux 0.11：schedule 的 `if (c) break`、do_timer 的 `if (!cpl) return`、copy_page_tables 的首次 fork 分支和 do_wp_page 的禁用检查，以原包实际语句为准。
- 映射同步：msync(2) DESCRIPTION/VERSIONS；Linux 2.6.19 起 MS_ASYNC 实际为 no-op，不具备 MS_SYNC 等待保证。fsync 文件数据也不能代替必要的目录同步。

## 图片来源与公开使用边界

清单以**正文实际引用**为准，以下链接是文件入口，不代表用 SVG 替换现有 PNG。全部路径前缀为 `docs/public/assets/notes/operating-systems/`；正文形式统一为 `![说明](/assets/notes/operating-systems/文件名)`，部分外层还有同路径链接以打开原图。共 55 张：52 SVG、3 PNG，未把不在页面显示的同名配对图重复计入。

状态说明：

- **项目绘图**：可从本项目修订图源/生成过程核对为教学机制绘图，未发现外部图像引用或嵌入位图；不把内部记录冒充第三方授权证明，也不声称做过独立法律清查。
- **待确认**：既有资产的原始作者、材料或公开使用授权不足以从当前资料确认；可能含第三方表达，需人工核实。不是断言已侵权，也绝不因仓库存在就推定获准。
- 所有“待确认”项均为**发布阻塞事项**。既有 PNG 及其同名 SVG 按要求保持原样，不能为通过验收擅自替换。应由维护者补充出处/授权或另行审定原创替代方案。

| 文件入口                                                                                 | 所属正文                                                   | 格式               | 来源/项目自绘                | 第三方素材与授权核实                               | 需人工确认     |
| ---------------------------------------------------------------------------------------- | ---------------------------------------------------------- | ------------------ | ---------------------------- | -------------------------------------------------- | -------------- |
| [os-overview.svg](/assets/notes/operating-systems/os-overview.svg)                       | [第 1 章](/articles/os-overview.html)                      | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-boot.svg](/assets/notes/operating-systems/os-boot.svg)                               | [第 2 章](/articles/os-boot-process.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-boot-tasks.svg](/assets/notes/operating-systems/os-boot-tasks.svg)                   | [第 2 章](/articles/os-boot-process.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-syscall.svg](/assets/notes/operating-systems/os-syscall.svg)                         | [第 3 章](/articles/os-system-calls.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-process.svg](/assets/notes/operating-systems/os-process.svg)                         | [第 4 章](/articles/os-process-lifecycle.html)             | SVG；Markdown 图片 | 既有来源待确认；不能确认自绘 | 材料/作者/授权均未核实，阻塞发布                   | 是             |
| [os-process-lifecycle.svg](/assets/notes/operating-systems/os-process-lifecycle.svg)     | [第 4 章](/articles/os-process-lifecycle.html)             | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-fork-exec-wait.svg](/assets/notes/operating-systems/os-fork-exec-wait.svg)           | [第 4 章](/articles/os-process-lifecycle.html)             | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-threads.svg](/assets/notes/operating-systems/os-threads.svg)                         | [第 5 章](/articles/os-threads-stacks.html)                | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-thread-models.svg](/assets/notes/operating-systems/os-thread-models.svg)             | [第 5 章](/articles/os-threads-stacks.html)                | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-context.svg](/assets/notes/operating-systems/os-context.svg)                         | [第 6 章](/articles/os-context-switching.html)             | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-context-timeline.svg](/assets/notes/operating-systems/os-context-timeline.svg)       | [第 6 章](/articles/os-context-switching.html)             | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-schedule-gantt.svg](/assets/notes/operating-systems/os-schedule-gantt.svg)           | [第 7 章](/articles/os-cpu-scheduling.html)                | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-schedule.svg](/assets/notes/operating-systems/os-schedule.svg)                       | [第 7 章](/articles/os-cpu-scheduling.html)                | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-lost-update.svg](/assets/notes/operating-systems/os-lost-update.svg)                 | [第 8 章](/articles/os-atomic-locks.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-release-acquire.svg](/assets/notes/operating-systems/os-release-acquire.svg)         | [第 8 章](/articles/os-atomic-locks.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-lock.svg](/assets/notes/operating-systems/os-lock.svg)                               | [第 8 章](/articles/os-atomic-locks.html)                  | SVG；Markdown 图片 | 既有来源待确认；不能确认自绘 | 材料/作者/授权均未核实，阻塞发布                   | 是             |
| [os-lock-wait.svg](/assets/notes/operating-systems/os-lock-wait.svg)                     | [第 8 章](/articles/os-atomic-locks.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-semaphore-condition.svg](/assets/notes/operating-systems/os-semaphore-condition.svg) | [第 9 章](/articles/os-semaphores-conditions.html)         | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-wakeup.svg](/assets/notes/operating-systems/os-wakeup.svg)                           | [第 9 章](/articles/os-semaphores-conditions.html)         | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-buffer-protocol.svg](/assets/notes/operating-systems/os-buffer-protocol.svg)         | [第 9 章](/articles/os-semaphores-conditions.html)         | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-deadlock.svg](/assets/notes/operating-systems/os-deadlock.svg)                       | [第 10 章](/articles/os-deadlocks.html)                    | SVG；Markdown 图片 | 既有来源待确认；不能确认自绘 | 材料/作者/授权均未核实，阻塞发布                   | 是             |
| [os-banker-safety.svg](/assets/notes/operating-systems/os-banker-safety.svg)             | [第 10 章](/articles/os-deadlocks.html)                    | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-buffer-state.svg](/assets/notes/operating-systems/os-buffer-state.svg)               | [第 11 章](/articles/os-buffer-io.html)                    | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-getblk.svg](/assets/notes/operating-systems/os-getblk.svg)                           | [第 11 章](/articles/os-buffer-io.html)                    | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-bread.png](/assets/notes/operating-systems/os-bread.png)                             | [第 11 章](/articles/os-buffer-io.html)                    | PNG；Markdown 图片 | 既有来源待确认；不能确认自绘 | 材料/作者/授权均未核实，阻塞发布                   | 是             |
| [os-buffer-waiters.svg](/assets/notes/operating-systems/os-buffer-waiters.svg)           | [第 11 章](/articles/os-buffer-io.html)                    | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-block-io-timeline.svg](/assets/notes/operating-systems/os-block-io-timeline.svg)     | [第 11 章](/articles/os-buffer-io.html)                    | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-file-objects.svg](/assets/notes/operating-systems/os-file-objects.svg)               | [第 12 章](/articles/os-file-descriptors-persistence.html) | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-file.png](/assets/notes/operating-systems/os-file.png)                               | [第 12 章](/articles/os-file-descriptors-persistence.html) | PNG；Markdown 图片 | 既有来源待确认；不能确认自绘 | 材料/作者/授权均未核实，阻塞发布                   | 是             |
| [os-file-publish.svg](/assets/notes/operating-systems/os-file-publish.svg)               | [第 12 章](/articles/os-file-descriptors-persistence.html) | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-address.svg](/assets/notes/operating-systems/os-address.svg)                         | [第 13 章](/articles/os-address-spaces-segmentation.html)  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-address-sharing.svg](/assets/notes/operating-systems/os-address-sharing.svg)         | [第 13 章](/articles/os-address-spaces-segmentation.html)  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-fragmentation.svg](/assets/notes/operating-systems/os-fragmentation.svg)             | [第 14 章](/articles/os-memory-allocation.html)            | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-fit-sequence.svg](/assets/notes/operating-systems/os-fit-sequence.svg)               | [第 14 章](/articles/os-memory-allocation.html)            | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-allocation-layers.svg](/assets/notes/operating-systems/os-allocation-layers.svg)     | [第 14 章](/articles/os-memory-allocation.html)            | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-paging.svg](/assets/notes/operating-systems/os-paging.svg)                           | [第 15 章](/articles/os-paging-page-tables.html)           | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-page-table-cost.svg](/assets/notes/operating-systems/os-page-table-cost.svg)         | [第 15 章](/articles/os-paging-page-tables.html)           | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-page-access.svg](/assets/notes/operating-systems/os-page-access.svg)                 | [第 15 章](/articles/os-paging-page-tables.html)           | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-tlb.svg](/assets/notes/operating-systems/os-tlb.svg)                                 | [第 16 章](/articles/os-tlb.html)                          | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-tlb-tags.svg](/assets/notes/operating-systems/os-tlb-tags.svg)                       | [第 16 章](/articles/os-tlb.html)                          | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-tlb-shootdown.svg](/assets/notes/operating-systems/os-tlb-shootdown.svg)             | [第 16 章](/articles/os-tlb.html)                          | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-linux011-layout.svg](/assets/notes/operating-systems/os-linux011-layout.svg)         | [第 17 章](/articles/os-linux011-copy-on-write.html)       | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-cow.png](/assets/notes/operating-systems/os-cow.png)                                 | [第 17 章](/articles/os-linux011-copy-on-write.html)       | PNG；Markdown 图片 | 既有来源待确认；不能确认自绘 | 材料/作者/授权均未核实，阻塞发布                   | 是             |
| [os-linux011-cow-states.svg](/assets/notes/operating-systems/os-linux011-cow-states.svg) | [第 17 章](/articles/os-linux011-copy-on-write.html)       | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-fault.svg](/assets/notes/operating-systems/os-fault.svg)                             | [第 18 章](/articles/os-page-faults.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-fault-cases.svg](/assets/notes/operating-systems/os-fault-cases.svg)                 | [第 18 章](/articles/os-page-faults.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-linux011-no-page.svg](/assets/notes/operating-systems/os-linux011-no-page.svg)       | [第 18 章](/articles/os-page-faults.html)                  | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-reclaim.svg](/assets/notes/operating-systems/os-reclaim.svg)                         | [第 19 章](/articles/os-page-replacement-swap.html)        | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-replacement-trace.svg](/assets/notes/operating-systems/os-replacement-trace.svg)     | [第 19 章](/articles/os-page-replacement-swap.html)        | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-clock.svg](/assets/notes/operating-systems/os-clock.svg)                             | [第 19 章](/articles/os-page-replacement-swap.html)        | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-mmap.svg](/assets/notes/operating-systems/os-mmap.svg)                               | [第 20 章](/articles/os-mmap-page-cache.html)              | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-mmap-modes.svg](/assets/notes/operating-systems/os-mmap-modes.svg)                   | [第 20 章](/articles/os-mmap-page-cache.html)              | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-mmap-sync.svg](/assets/notes/operating-systems/os-mmap-sync.svg)                     | [第 20 章](/articles/os-mmap-page-cache.html)              | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-triage.svg](/assets/notes/operating-systems/os-triage.svg)                           | [第 21 章](/articles/os-troubleshooting.html)              | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |
| [os-rss-pss.svg](/assets/notes/operating-systems/os-rss-pss.svg)                         | [第 21 章](/articles/os-troubleshooting.html)              | SVG；Markdown 图片 | 项目修订教学绘图             | 未发现嵌入第三方图像；项目绘图记录，非独立授权认证 | 无新增待确认项 |

os-bread.png、os-file.png、os-cow.png 分别继续用于第 11、12、17 章；同名 SVG 仍在资产目录，均未修改。配对文件的存在不说明 PNG 是由该 SVG 生成，也不证明两者获得相同授权。未被正文引用的配对 SVG 仍需在分发资产前一并核查，不算页面图片数量。

[返回本册目录](/collections/operating-systems/)
