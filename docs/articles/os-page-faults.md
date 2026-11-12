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

> 阅读标签：现代 Linux 的概念与统计、x86 异常信息，以及单独标注的 Linux 0.11 历史源码。

程序已经申请了一个合法虚拟区域，为什么第一次写入还会进入内核？系统可以把物理页准备工作推迟到真正访问时；临时写保护也可以驱动私有数据分离。缺页处理既可能完成正常的延迟工作，也可能报告不可恢复的访问，不能把所有情况都理解成“内存不够，去读磁盘”。

## 1. TLB miss、Page Fault 与非法地址

翻译后备缓冲（TLB，Translation Lookaside Buffer）缓存翻译和属性。中央处理器（CPU，Central Processing Unit）没找到缓存翻译时，不必立刻进入内核：在本章 x86 硬件分页语境中，页表有效且权限满足就可以完成翻译。页故障异常（#PF，Page-Fault Exception，常称缺页异常）则与当前指令的访问相关，是**同步异常**，不同于异步外设中断。

| 情况                  | 当前状态                                      | 可能结果                                   |
| --------------------- | --------------------------------------------- | ------------------------------------------ |
| TLB Miss              | 没有适用缓存翻译                              | 页表有效则补翻译继续，不属于一次内核页故障 |
| 可以恢复的 Page Fault | 当前存在性/权限需内核处理，且访问符合相应规则 | 分配、建映射、加载数据或写时复制后恢复     |
| 无法修复的访问        | 地址或权限等条件不允许访问                    | 进入适用信号或内核错误路径                 |

[![正常翻译、TLB 未命中和页故障后合法恢复或拒绝访问的层次](/assets/notes/operating-systems/os-fault.svg)](/assets/notes/operating-systems/os-fault.svg)

Page Fault 不等于必读存储，也不等于程序必有错误；反过来，不是所有非法访问都以相同异常形式出现，例如 x86-64 非规范地址可能先触发其他异常。内核不能对所有未知地址自动分配页。[第十五章分页](/articles/os-paging-page-tables.html)、[第十六章 TLB](/articles/os-tlb.html)

### x86 页故障错误码怎样读

以下重点介绍现代 Intel x86 的有关字段，故障线性地址由 CR2 等相关机制提供；字段描述的是故障原因和访问，不是把整个页表项（PTE，Page Table Entry）原样报告：

| 位/字段   | 含义与边界                                                                                            |
| --------- | ----------------------------------------------------------------------------------------------------- |
| bit0 P    | 普通常见情形下，0 为不存在翻译所致，1 为保护违规；现代保留位违规等也按手册报告，不能只读 P 就断定 COW |
| bit1 W/R  | 故障访问为写时通常为 1，读为 0；描述访问类型，不等于页表可写位                                        |
| bit2 U/S  | 用户模式访问为 1，特权模式访问为 0；描述访问来源，不等于 PTE 的 User 位                               |
| bit3 RSVD | 使用的分页结构中存在适用保留位违规；不是普通缺少数据页                                                |
| bit4 I/D  | 在支持并启用相应报告条件时标识指令获取；不是所有模式都能据此识别取指                                  |

例如普通用户写入的 non-present 故障低三位是 `110₂=0x6`；用户写只读页的保护故障是 `111₂=0x7`。0x7 本身不能证明该页合法可做 COW，内核还要检查映射意图。

按本轮核对的 Intel Volume 3A 第 5.7 节，I/D 置 1 还要求故障由取指引起，且满足 `CR4.SMEP=1` 或 `CR4.PAE=1 且 IA32_EFER.NXE=1`。SMEP（Supervisor Mode Execution Prevention）是特权模式执行保护，PAE（Physical Address Extension）是物理地址扩展，NXE（No-Execute Enable）是不执行使能。这些不是早期 80386 的全部固有字段；早期 80386 主要使用 P、W/R、U/S。不能把现代 RSVD、I/D 乃至更高位的语义无条件套进 Linux 0.11 的历史环境。[Intel 架构手册 Volume 3A，Page-Fault Exceptions](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)

## 2. 三类合法延迟工作

以下是现代 Linux 的通用教学路径。虚拟内存区域（VMA，Virtual Memory Area）记录合法范围、权限与后备关系；内核结合区域和实际访问类型判断能否修复，不能只看某个页表项缺失。[Linux Process Addresses](https://docs.kernel.org/mm/process_addrs.html)

| 案例                              | 初始状态及触发访问                               | 内核可能的处理                                                               | 恢复结果                         |
| --------------------------------- | ------------------------------------------------ | ---------------------------------------------------------------------------- | -------------------------------- |
| A：匿名页首次写                   | 已有合法可写匿名映射，但该页尚未建立适用物理映射 | 触发异常，核验范围与权限，分配并清零适用页，建立可写映射                     | 返回后重试写指令                 |
| B：文件映射                       | 合法文件映射中当前页未建立适用映射               | 已在页缓存时可复用；若需要后备存储加载则发起并等待有关 I/O，处理错误后建映射 | 成功则重试访问，失败不能假装成功 |
| C：写时复制（COW，Copy-On-Write） | 合法私有可写映射临时以只读 PTE 共享页，一方写入  | 核验 COW 条件；必要时分配复制，也可能独占复用，更新映射与适用失效            | 重试后保留各自私有视图           |

[![匿名首次写、文件缓存或加载、COW 的初始状态与恢复路径对照](/assets/notes/operating-systems/os-fault-cases.svg)](/assets/notes/operating-systems/os-fault-cases.svg)

匿名首次**读**可能使用共享零页等优化，不能断言一定立即分配独占页；交换空间（swap）中的匿名数据又有对应读回路径。输入/输出（I/O，Input/Output）不是所有恢复的必经步骤，即使不需要读存储，分配、清零、复制、锁同步和页表更新也有成本。[Linux 6.6 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)

第十七章的现代私有映射实验演示可见语义；其中 Linux 0.11 的 do_wp_page 缺少现代完整 VMA 检查，不能把本表的现代判断直接写进旧函数。[写时复制与历史边界](/articles/os-linux011-copy-on-write.html)

## 3. minor 与 major 的计数口径

Linux `getrusage()` 的次缺页异常（Minor Page Fault）统计未要求从磁盘加载页面的缺页处理，主缺页异常（Major Page Fault）统计需要相应加载的处理。它们是内核统计口径，不是简单的“物理页存在/不存在”。[getrusage(2)](https://man7.org/linux/man-pages/man2/getrusage.2.html)

| 场景                                 | 常见统计倾向，而非每次访问的绝对保证 |
| ------------------------------------ | ------------------------------------ |
| 匿名内存首次写、某些 COW             | Minor                                |
| 文件数据已在页缓存，当前需要建立映射 | Minor                                |
| 需要文件或适用后备存储加载           | Major                                |
| 有效页表完成 TLB Miss                | 不因此记一次 Page Fault              |

Minor 也可能很昂贵；Major 非零不证明当前正在颠簸，要结合时间窗、负载、缓存和内存压力。COW 的 Minor 次数不等于物理页复制次数：独占恢复可能不复制，运行时的栈和库也可能缺页。Windows hard/soft fault 不应与 Linux 两项逐项画等号。

可用 `getrusage(RUSAGE_SELF,...)` 看当前进程统计；`/proc/<PID>/stat` 有 minflt/majflt 等字段，但进程名字段含括号、可能包含空格，不能随便按空格拆开再数列；环境提供时也可运行 `/usr/bin/time -v ./faults`。这些累计数需取对应时间窗差值。[proc_pid_stat(5)](https://man7.org/linux/man-pages/man5/proc_pid_stat.5.html)

## 4. 无法修复的访问与信号处理 {#_4-非法访问怎样结束}

非法地址或违反访问权限的用户访问，Linux 常见结果是段错误信号（SIGSEGV）；某些文件映射访问超出底层文件有效范围可能得到总线错误信号（SIGBUS）。例如文件末页之后的整页映射区域访问可能触发 SIGBUS，但末尾不满一页的规则不能简单当成“文件大小外任一字节都立即同样报错”。[mmap(2)](https://man7.org/linux/man-pages/man2/mmap.2.html)

CPU 异常是硬件到内核的控制转移，用户信号是内核报告事件的机制，两者不等同。也不是所有越界都保证立即触发同一种信号，可能仍落在某个可访问映射内。捕获信号不表示可以安全跳过错误继续处理已损坏数据。

## 5. Linux 0.11 的 do_no_page 路径 {#_5-原-do-no-page-片段的校正}

这一节只读 [Linux 0.11 原始源码](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz) 的 `mm/memory.c`、`mm/page.s` 与 `fs/buffer.c`，不套用现代 VMA、页缓存函数或权限验证调用链。

1. `mm/page.s` 根据错误码 P 位为 0 转入 `do_no_page(error_code,address)`，address 是 CR2 的故障线性地址。
2. `address &= 0xFFFFF000` 向下对齐到页；`tmp = address-current->start_code` 得到相对该任务线性基址的偏移。end_data 在这条判断中是相对数据范围，不是可直接拿来替代 address 的绝对线性地址。
3. **`!current->executable || tmp >= current->end_data`** 时走 `get_empty_page(address)`，申请清零页并用 put_page 建映射，然后返回。此函数没有现代 VMA 合法性查找，不能解释成“未知地址都合法”。历史段范围等条件要另外分析。
4. 其他情况先尝试 `share_page(tmp)`：同一个可执行 inode 至少有适用其他引用，再扫描使用同一 executable 的其他任务。`try_to_share()` 要求来源页存在且未脏，检查 `(entry & 0x41)==0x01`，并限制在受管理物理范围。满足时建立目标表、使双方适用 PTE 只读、invalidate 并增加 mem_map 计数，成功直接返回；需要目标二级表却分配失败时，也会进入 oom。
5. 不能共享才 `get_free_page()`；失败调用 oom。然后 `block=1+tmp/BLOCK_SIZE`，为原版可执行文件格式跳过一个头部块，依次用 bmap 查 4 个文件逻辑块，再 `bread_page(page,dev,nr)` 处理它们。BLOCK_SIZE=1024，四块组成 4096 字节页，不是现代 ELF 装载规则。
6. 用 `i=tmp+4096-current->end_data` 计算超出数据结尾的尾部字节数；i>0 时从新物理页末尾向前清零，避免把有效数据范围之外的内容当成初始化数据。
7. `put_page(page,address)` 成功则返回；映射需要的新二级表分配失败时返回 0，调用者释放新页再 oom。`get_empty_page()` 也检查申请和映射结果。这里 oom 打印错误并调用 `do_exit(SIGSEGV)`，不是现代 OOM killer 的完整策略。

[![Linux 0.11 do_no_page 中空页、共享可执行页、读四块及映射/失败路径](/assets/notes/operating-systems/os-linux011-no-page.svg)](/assets/notes/operating-systems/os-linux011-no-page.svg)

数值例子：start_code=`0x04000000`、故障地址=`0x04002240`，对齐后为 `0x04002000`，tmp=`0x2000`。若有 executable 且 end_data=`0x2900`，会先尝试共享，不能共享时从逻辑块 `1+0x2000/1024=9` 起查询 9～12 四块；页尾超出部分为 `0x2000+0x1000−0x2900=0x700` 字节，需清零。这里假设相关块可取得，不代表设备实测。

还要保留一个历史限制：`bread_page()` 返回 void，只在有关缓冲有效时复制对应块，`do_no_page()` 没有检查现代风格的整页读取状态返回值。不能凭教学需要虚构“读失败已通过返回码统一终止任务”的分支。get_free_page 的预清零、空洞块处理和旧缓冲读取实现要结合看；不把这种错误处理能力当作现代 Linux 的保证。

`share_page()` 是缺失映射时尝试复用其他任务的干净可执行文件页；第十七章 fork 则从父页表复制适用映射。二者都可能形成只读共享，但入口条件和建立关系的过程不同。put_page 在本例新映射路径中建立页目录/表项，源码注明无需 invalidate；不能把重定向已有翻译的刷新规则机械贴到每个空映射安装上。

成功路径返回 `mm/page.s`，恢复保存状态并 iret，相关指令重试；不可恢复路径不会伪装成已完成用户访问。本轮逐函数静态核验，没有运行历史内核或生成虚构 I/O 日志。

## 6. 安全观察：只映射和首次逐页写入

保存为 `faults.c`，用 `gcc -std=c11 -O2 -Wall -Wextra -Werror faults.c -o faults` 编译并运行 `./faults`。仅映射 16 个系统页，不做内存压力测试；volatile 访问避免写入被优化掉。先记录映射但不触碰，再每页写一次、再写一次，通过 getrusage 记录相邻阶段差值。

```c
#define _DEFAULT_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <unistd.h>

static int snapshot(struct rusage *r)
{
    if (getrusage(RUSAGE_SELF, r) == -1) {
        perror("getrusage");
        return -1;
    }
    return 0;
}

int main(void)
{
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0 || (size_t)page_size > SIZE_MAX / 16) {
        fputs("invalid page size\n", stderr);
        return EXIT_FAILURE;
    }
    size_t length = (size_t)page_size * 16;
    struct rusage before, mapped, touched, repeated;
    if (snapshot(&before)) return EXIT_FAILURE;
    volatile unsigned char *p = mmap(NULL, length, PROT_READ | PROT_WRITE,
        MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) {
        perror("mmap");
        return EXIT_FAILURE;
    }
    int ok = 0;
    if (snapshot(&mapped)) goto cleanup;
    for (size_t i = 0; i < length; i += (size_t)page_size) p[i] = 1;
    if (snapshot(&touched)) goto cleanup;
    for (size_t i = 0; i < length; i += (size_t)page_size) p[i] = 2;
    if (snapshot(&repeated)) goto cleanup;
    printf("mapped bytes=%zu, pages=16\n", length);
    printf("mmap only: minor=%ld major=%ld\n",
        mapped.ru_minflt-before.ru_minflt, mapped.ru_majflt-before.ru_majflt);
    printf("first write: minor=%ld major=%ld\n",
        touched.ru_minflt-mapped.ru_minflt, touched.ru_majflt-mapped.ru_majflt);
    printf("second write: minor=%ld major=%ld\n",
        repeated.ru_minflt-touched.ru_minflt, repeated.ru_majflt-touched.ru_majflt);
    ok = 1;    /* No assertion equates fault counts with physical page counts. */
cleanup:
    if (munmap((void *)p, length) == -1) {
        perror("munmap");
        ok = 0;
    }
    if (fflush(stdout) == EOF || ferror(stdout)) ok = 0;
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}
```

本轮已在 WSL2/Linux 中编译运行；具体输出见交付报告。映射仅 16 页，没有真实内存耗尽、危险页表操作或全局缓存清理。计数受运行时预热、内核页尺寸策略、透明大页、环境与其他缺页活动影响，不断言首次恰好 16 次，也不把差值等同精确物理分配数。

## 本章小结与联读

TLB Miss、可恢复页故障与非法访问需要分开；错误码描述硬件观察，内核再判断访问意图及恢复路径，统计又是另一个层次。下一步读[第十九章置换、工作集与 swap](/articles/os-page-replacement-swap.html)及[第二十章 mmap 与页缓存](/articles/os-mmap-page-cache.html)。本章保留恢复的基本分类，不提前展开完整置换和文件映射实现。

[返回本册目录](/collections/operating-systems/)
