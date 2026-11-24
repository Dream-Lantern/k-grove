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

核对日期：**2026-11-04**。范围为本册第 1～21 章及附录 A/B，共 23 篇；以当前工作树为准，不用远程旧稿覆盖已完成修订。下面把依据按类型分开：翻过的原始源码、官方接口规范、现代实现的文档、算出来的数值模型、真正跑过的实验。这几类能证明的事情不一样，表里会分别标注；发布日期不代表每个实验都曾运行。

## 1. Linux 0.11 源码范围

固定使用 [kernel.org Linux 0.11 原始历史包](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)。本轮重新只读核对以下 11 个文件，并将本地解压文件与压缩包成员逐字节比较。

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

用途是标识此次核对的压缩包字节，便于复核版本；数字签名或独立第三方认证需要另行取得。读者应从上述公开来源自行获取、核验文件，本地处理记录只是维护者的核对痕迹。

四条历史边界尤其重要：

- 原版 switch_to 靠 TSS（Task State Segment，任务状态段）加远跳转完成切换：TSS 是每个任务保存寄存器现场和栈指针的内存结构，远跳转让 CPU 走一次任务切换。课程把它改写成软件内核栈切换时，应引用该课程自己的完整版本。
- schedule 逐个查看普通任务槽：某个任务的 counter 已经为零就跳过它，扫完一圈仍没有可运行候选才走另一条分支——“counter 为零”和“根本没有候选”不是同一件事。do_timer 里判断被中断时的 CPL，只约束这条时钟路径；内核在别处仍可以主动等待并触发调度。
- copy_page_tables 的 `from==0`、0xA0 项和低内存分支影响任务 0 首次 fork；普通受管理页的写时复制（COW，Copy-On-Write）模型另见第 17、18 章。
- do_wp_page 中代码区拒绝分支在该原版里被 `#if 0` 禁用；do_no_page 按 executable/end_data 等历史字段处理，并没有现代虚拟内存区域（VMA，Virtual Memory Area）的完整权限流程。准确顺序见第 17、18 章。

## 2. 对照资料

### 章节到技术来源

表内“源码/文档”表示事实依据类型，各章的验证程度差别很大；计算与实验状态见后表。

| 章节                                                           | 关键机制                       | 版本/平台与核心依据                                                                                                                                                                                                                                            | 验证性质                                       |
| -------------------------------------------------------------- | ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| [1 职责与执行](/articles/os-overview.html)                     | 抽象、隔离、并发与读取         | [OSTEP 教材](https://pages.cs.wisc.edu/~remzi/OSTEP/)及 read 接口                                                                                                                                                                                              | 文档、教学流程                                 |
| [2 启动](/articles/os-boot-process.html)                       | BIOS→保护模式→分页→任务 0/1    | 上表 boot 三文件、init/main.c；[Intel 手册](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)                                                                                                                               | 源码、架构文档；未启动旧内核                   |
| [3 系统调用](/articles/os-system-calls.html)                   | 用户/内核入口与返回            | 0.11 system_call.s；[Linux v6.12 entry_64.S](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/entry_64.S)、[syscall(2)](https://man7.org/linux/man-pages/man2/syscall.2.html)                                                                       | 源码与接口，区分 x86-32/64                     |
| [4 进程](/articles/os-process-lifecycle.html)                  | fork/exec/wait、打开文件描述   | [fork(2)](https://man7.org/linux/man-pages/man2/fork.2.html)、[execve(2)](https://man7.org/linux/man-pages/man2/execve.2.html)、[waitpid(2)](https://man7.org/linux/man-pages/man2/waitpid.2.html)                                                             | 文档；正文实验有明确边界                       |
| [5 线程](/articles/os-threads-stacks.html)                     | 共享空间、独立栈、映射模型     | [pthreads(7)](https://man7.org/linux/man-pages/man7/pthreads.7.html)、[pthread_create(3)](https://man7.org/linux/man-pages/man3/pthread_create.3.html)                                                                                                         | 接口与模型；地址/顺序不固定                    |
| [6 上下文](/articles/os-context-switching.html)                | 陷入帧、调度现场、TSS          | 0.11 sched.h、sched.c、system_call.s；Intel Vol.3                                                                                                                                                                                                              | 源码与架构；现代实现另见对应章节               |
| [7 调度](/articles/os-cpu-scheduling.html)                     | FCFS/SJF/RR、counter、公平调度 | 0.11 schedule/do_timer；[Linux 6.12 CFS](https://docs.kernel.org/6.12/scheduler/sched-design-CFS.html)、[EEVDF](https://docs.kernel.org/6.12/scheduler/sched-eevdf.html)                                                                                       | 源码、数值模拟                                 |
| [8 原子与锁](/articles/os-atomic-locks.html)                   | 数据竞争、原子和发布           | [WG14 N1570 §5.1.2.4、§7.17](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)、[Linux 6.6 锁类型](https://docs.kernel.org/6.6/locking/locktypes.html)                                                                                               | 标准草案依据、平台实现另限                     |
| [9 同步等待](/articles/os-semaphores-conditions.html)          | 谓词、条件变量、信号量         | [POSIX 条件变量语义](https://man7.org/linux/man-pages/man3/pthread_cond_wait.3p.html)、[sem_overview(7)](https://man7.org/linux/man-pages/man7/sem_overview.7.html)                                                                                            | 接口、时序模型                                 |
| [10 死锁](/articles/os-deadlocks.html)                         | 等待环、安全状态、避免         | [Dijkstra EWD623](https://www.cs.utexas.edu/~EWD/transcriptions/EWD06xx/EWD623.html)、[OSTEP 并发问题](https://pages.cs.wisc.edu/~remzi/OSTEP/threads-bugs.pdf)                                                                                                | 模型、整数模拟；Linux 通用锁算法另有实现       |
| [11 缓冲 I/O](/articles/os-buffer-io.html)                     | getblk/bread、锁与有效位       | 0.11 fs/buffer.c、ll_rw_blk.c                                                                                                                                                                                                                                  | 源码、三路径时序；现代 page cache 另见第 20 章 |
| [12 FD 与保存](/articles/os-file-descriptors-persistence.html) | 共享偏移、短写、fsync/rename   | [open(2)](https://man7.org/linux/man-pages/man2/open.2.html)、[write(2)](https://man7.org/linux/man-pages/man2/write.2.html)、[fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)、[rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html) | 接口与受限实验；断电认证未覆盖                 |
| [13 地址与分段](/articles/os-address-spaces-segmentation.html) | 逻辑/线性/物理、段检查、VMA    | Intel Vol.3 保护模式；[Linux 6.6 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)                                                                                                                                                           | 架构、地址模拟                                 |
| [14 分配](/articles/os-memory-allocation.html)                 | Fit、分割合并、malloc 层次     | [OSTEP Free-Space](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-freespace.pdf)、[malloc(3)](https://man7.org/linux/man-pages/man3/malloc.3.html)                                                                                                                  | 模型和整数模拟                                 |
| [15 页表](/articles/os-paging-page-tables.html)                | 10/10/12 拆分、层级与权限      | Intel Vol.3；[Linux 页表](https://docs.kernel.org/mm/page_tables.html)                                                                                                                                                                                         | 固定 x86-32 非 PAE 模型、数值模拟              |
| [16 TLB](/articles/os-tlb.html)                                | 翻译缓存、标记、失效与 EAT     | Intel Vol.3 Caching Translation Information；[Linux TLB 接口](https://docs.kernel.org/core-api/cachetlb.html)                                                                                                                                                  | 架构与模拟，非真实硬件时延                     |
| [17 COW](/articles/os-linux011-copy-on-write.html)             | 任务槽、只读共享、独占写       | 0.11 copy_mem/copy_page_tables/un_wp_page                                                                                                                                                                                                                      | 源码、引用状态推演；普通 fork 实验另限         |
| [18 缺页](/articles/os-page-faults.html)                       | 不存在/保护、匿名/文件后备     | 0.11 mm/page.s、do_no_page/do_wp_page；[getrusage(2)](https://man7.org/linux/man-pages/man2/getrusage.2.html)                                                                                                                                                  | 源码、现代接口实验；两类路径分开               |
| [19 回收](/articles/os-page-replacement-swap.html)             | 置换、工作集与 OOM             | [OSTEP 页面策略](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-beyondphys-policy.pdf)、[Linux 6.6 MGLRU](https://docs.kernel.org/6.6/admin-guide/mm/multigen_lru.html)                                                                                             | 纯模拟与版本文档                               |
| [20 映射](/articles/os-mmap-page-cache.html)                   | read/mmap、可见性与同步        | [mmap(2)](https://man7.org/linux/man-pages/man2/mmap.2.html)、[msync(2)](https://man7.org/linux/man-pages/man2/msync.2.html)、[Page Cache](https://docs.kernel.org/mm/page_cache.html)                                                                         | 文档与临时文件实验                             |
| [21 排查](/articles/os-troubleshooting.html)                   | CPU/内存/等待证据              | [PSI](https://docs.kernel.org/accounting/psi.html)、[cgroup v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)、[proc(5)](https://man7.org/linux/man-pages/man5/proc.5.html)                                                                              | 接口、只读兼容检查；Case 为假设                |

### 各资料的版本边界

Linux 0.11 固定历史版本；Linux 6.6/6.12 文档按标题给出版本；不带版本的 docs.kernel.org 和在线 man-pages 是本次查阅的滚动资料，内容随版本演进，引用旧版本行为时要另找对应版本文档。POSIX 接口与 C 语言内存模型各有规则：N1570 是公开的 C11 委员会草案，最终标准正文另有正式出版物；man-pages 的 3p 页面提供 POSIX 语义参考，具体版本见页面 STANDARDS/版权说明。

x86 32 位保护模式、x86-64 长模式与 [xv6 RISC-V 2024 教材](https://pdos.csail.mit.edu/6.1810/2024/xv6/book-riscv-rev4.pdf)在寄存器和陷入行为上各不相同：同一段保存现场的代码，换一种架构就不是同一组寄存器、也不是同一个入口，不能直接对照套用。PCID（Process-Context Identifier，进程上下文标识）是 x86 的特定机制；ASID（Address Space Identifier，地址空间标识）用于其他相应架构语境，两者是两套标识机制。四/五级分页取决于架构、硬件及配置，本文的非 PAE 两级纸面模型只覆盖固定配置。

EEVDF 从 Linux 6.6 开始替代部分公平调度选择机制；实时类别仍然存在，当前运行环境是否采用要看内核版本与配置。MGLRU 的支持与启用另有配置要求。PREEMPT_RT（实时抢占配置）下部分锁语义发生变化，须同时区分 spinlock_t 和 raw_spinlock_t，普通配置下的锁结论要重新核对。

现代 UEFI 固件的具体调用次序仍需对应平台规范；正文仅作职责对照。同样是读一个文件，历史 bread 走块缓冲，现代普通读走页缓存，Direct I/O 绕开页缓存直接和设备打交道，DAX（Direct Access，直接访问）则把持久内存直接映射进地址空间。四条路径的差别在于数据放在哪里、要不要经过页缓存，看到的现象也就不同。

### 验证状态与本次实际检查

| 状态     | 含义与限制                                                |
| -------- | --------------------------------------------------------- |
| 源码核验 | 已阅读并定位明确版本的文件/函数；编译启动成功是另一项结论 |
| 文档核验 | 官方接口、架构手册或明确版本文档支持；注意平台与标准版本  |
| 数值复核 | 计算或纯模拟断言通过；真实硬件测量是另一回事              |
| 实验通过 | 在注明环境运行了具体程序及检查；覆盖范围限于所示路径      |
| 教学抽象 | 为解释而限定或省略细节                                    |
| 待验证   | 缺少环境、来源或证据，保留限制说明                        |

本次检查覆盖 23 篇的元数据、排序、旧锚点、站内引用和实际配图，以及 Linux 0.11 上表源码。调度、地址/分配/页表/TLB/置换和银行家算法按正文程序重新复核。前序局部实验使用 WSL2 Ubuntu、x86_64、Linux 5.15.167.4、GCC 11.4.0/Python 3.10.12；这些是站点维护者的本地记录，结果随环境变化。

已运行的 mmap 临时文件实验观察到：私有写 X 不改变文件 ABCDEFGH，共享写 Y 可由普通读取观察，MS_SYNC 返回成功。该实验的范围限于进程内可见的映射行为，断电恢复、其他文件系统与多字段事务都未覆盖。只读命令兼容检查只验证接口可用，真实业务根因诊断要另行进行；该 WSL 环境没有 PSI 接口，v2 所需内存/配额控制器也不可用，相关指标仍待支持环境验证。

Linux 0.11 未进行动态运行；真实 OOM、颠簸、死锁、SIGBUS、断电恢复、mmap/read 性能对比均未执行。质量脚本和最终本地构建的命令、退出状态与集成检查结果见本轮交付报告；构建成功支持的是站点集成，技术结论仍以各章依据为准。

## 关键规则的来源定位 {#本轮复核的精确定位}

- C11 数据竞争：N1570 §5.1.2.4 ¶25；不同线程的两个操作访问同一对象、至少一个不是原子操作、又没建立起 happens-before 关系，就构成数据竞争，结果属于未定义行为。把“可能发生的执行交错”列一遍说明不了没有竞争——没列到的交错同样算。
- 多线程 fork：fork(2) DESCRIPTION 中只有调用线程复制到子进程及 exec 前异步信号安全限制；父进程其他线程持有的锁状态在子进程中保持原样，需要应用自行处理。
- 条件变量：pthread_cond_wait 的原子解锁并等待、返回前重新持锁；应用应按谓词用 while 重查；通知只表示状态可能变化，不是资源计数。
- Linux 0.11：schedule 的 `if (c) break`、do_timer 的 `if (!cpl) return`、copy_page_tables 的首次 fork 分支和 do_wp_page 的禁用检查，以原包实际语句为准。
- 映射同步：msync(2) DESCRIPTION/VERSIONS；Linux 2.6.19 起 MS_ASYNC 实际为 no-op，不具备 MS_SYNC 等待保证。fsync 文件数据之外，目录同步仍是单独一步。

## 图片来源与公开使用边界

清单以**正文实际引用**为准，以下链接是文件入口，现有 PNG 保持原样。全部路径前缀为 `docs/public/assets/notes/operating-systems/`；正文形式统一为 `![说明](/assets/notes/operating-systems/文件名)`，部分外层还有同路径链接以打开原图。共 55 张：52 SVG、3 PNG，未把不在页面显示的同名配对图重复计入。

状态说明：

- **项目绘图**：可从本项目修订图源/生成过程核对为教学机制绘图，未发现外部图像引用或嵌入位图。
- **待确认**：既有资产的原始作者、材料或公开使用授权不足以从当前资料确认；可能含第三方表达，需人工核实。核实完成前，既不认定侵权，也不视为已获授权。
- 所有“待确认”项均为**发布阻塞事项**。既有 PNG 及其同名 SVG 按要求保持原样，替换需走审定流程。应由维护者补充出处/授权或另行审定原创替代方案。

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

os-bread.png、os-file.png、os-cow.png 分别继续用于第 11、12、17 章；同名 SVG 仍在资产目录，均未修改。配对文件的存在与生成关系、授权范围都无关，两者需分别核查。未被正文引用的配对 SVG 仍需在分发资产前一并核查，不算页面图片数量。

[返回本册目录](/collections/operating-systems/)
