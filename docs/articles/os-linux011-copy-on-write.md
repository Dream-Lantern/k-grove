---
id: os-linux011-copy-on-write
title: 第十七章 Linux 0.11 段页结合与写时复制
description: "Linux 0.11 先通过分段把任务的逻辑地址放入相应线性范围，再用分页联系物理页。fork 时，父子可以暂时共享数据物理页；写入时再根据权限与引用状态处理。"
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
order: 17
---

# 第十七章 Linux 0.11 段页结合与写时复制

> 阅读标签：固定 Linux 0.11 原始源码；现代用户态实验另行标注，不是旧内核动态验收。

fork 后父子最初拥有相同数据，为什么不立刻复制全部物理页？写时复制（COW，Copy-On-Write）先共享适用数据页并撤销写权限，直到写入才处理分离。本章先区分逻辑位置、页表对象与数据页，再严格按原始代码说明普通受管理页和启动低内存特例。

主要依据 [kernel.org 的 Linux 0.11 原始源码](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)：`kernel/fork.c`、`mm/memory.c`、`mm/page.s`、`init/main.c`，并合读 `boot/head.s` 与 `include/linux/sched.h`。以下地址和页框是纸面假设，不是旧内核运行日志。

## 1. 进程的逻辑视图与线性位置

`copy_mem(nr,p)` 读取旧代码/数据段基址与界限，要求代码、数据基址相同且数据范围不小于代码范围。随后设 `new_data_base = new_code_base = nr×0x4000000`，更新 `p->start_code` 与局部描述符表（LDT，Local Descriptor Table）的代码/数据段基址。

nr 是任务数组槽号，不是任意进程标识符（PID，Process ID）；64 MiB 是历史线性范围间隔，不是每个任务已经占用的物理内存数量。固定 32 位非物理地址扩展（PAE，Physical Address Extension）、4 KiB 页：

| 项目                              | 槽 1         | 槽 2         |
| --------------------------------- | ------------ | ------------ |
| 逻辑偏移                          | `0x2240`     | `0x2240`     |
| 段基址                            | `0x04000000` | `0x08000000` |
| 线性地址                          | `0x04002240` | `0x08002240` |
| 目录索引 `linear >> 22`           | 16           | 32           |
| 二级索引 `(linear >> 12) & 0x3FF` | 2            | 2            |
| 页内偏移 `linear & 0xFFF`         | `0x240`      | `0x240`      |

[![Linux 0.11 两个任务槽通过不同线性范围、公共页目录和不同二级表共享数据页](/assets/notes/operating-systems/os-linux011-layout.svg)](/assets/notes/operating-systems/os-linux011-layout.svg)

原版 `_pg_dir` 位于物理地址 0，初始任务状态段（TSS，Task State Segment）中的 CR3 指向它，后续任务继承相应根信息。公共页目录的 PDE[16] 与 PDE[32] 可指向不同二级页表；各自 PTE[2] 又可暂时映射同一个物理数据页。页目录项（PDE，Page Directory Entry）、页表项（PTE，Page Table Entry）和数据页不能混为同一对象。

**共享页目录、不同二级表、共享数据页是三种关系。** 现代 Linux 不必采用同样 LDT 布局；也不能把这里的公共根直接说成现代父子永远共享同一套可变页表。

## 2. copy_page_tables 建立子映射 {#_2-copy-page-tables-复制什么}

`copy_mem()` 调用 `copy_page_tables(old_data_base,new_data_base,data_limit)`。沿 `mm/memory.c` 的真实顺序看：

1. from/to 必须按 4 MiB 对齐，检查掩码 `0x3FFFFF`；不是仅 4 KiB 对齐。
2. 页目录在地址 0，所以目录项指针可由 `(address >> 20) & 0xFFC` 计算。槽 1、2 的对应首项偏移分别为 `0x40`、`0x80`，等于目录索引乘 4。
3. size 按 `(size+0x3FFFFF)>>22` 向上取整为目录项数量。每轮推进源、目标目录指针；源 PDE 不存在就跳过，目标 PDE 已存在则 panic。
4. 源 PDE 存在时，用 `get_free_page()` 分配并清零目标二级表，再令目标 PDE 为 `表地址 | 7`。7 表示存在（Present）、可写（Read/Write）、允许用户访问（User）三个低位均置 1。
5. 普通来源每轮看 1024 个 PTE，首次 `from==0` 的特殊数量见第四节。源 PTE 不存在则跳过；存在则取 `this_page`、清可写位 `this_page &= ~2`，写入目标 PTE，保留其余适用地址与属性。
6. 原版判断是 **`if (this_page > LOW_MEM)`**，比较对象是带属性位的条目。对合法、存在的受管理页，这一路还把源 PTE 改为同样的只读条目，并增加 `mem_map[(this_page-LOW_MEM)>>12]`。低于 LOW_MEM 的特殊页不走这次源写保护与计数更新，但目标条目已经只读。
7. 成功结束调用 `invalidate()`，使翻译后备缓冲（TLB，Translation Lookaside Buffer）中的旧缓存翻译失效。它没有立即复制这些用户数据页的内容。

普通受管理页的状态如下，设原先可写、只有这一个适用引用：

| 阶段 | 源 PTE                   | 目标 PTE                                   | 数据页引用 |
| ---- | ------------------------ | ------------------------------------------ | ---------- |
| 之前 | Present=1，RW=1，PFN1066 | 尚未建立                                   | 1          |
| 之后 | Present=1，RW=0，PFN1066 | Present=1，RW=0，PFN1066；位于另一张二级表 | 2          |

分配目标二级表失败时函数返回 −1，可能已经有部分目标映射和源写保护；调用者 `copy_mem()` 通过 `free_page_tables(new_data_base,data_limit)` 清理已建目标表与引用，再返回错误。外层 `copy_process()` 清任务槽并释放任务结构页。源权限不必逐项回滚成原先可写；后来独占写可走恢复权限路径。不要把它说成该函数自己完整撤销一切，也不要把部分失败忽略。

## 3. 写保护异常与私有页分离 {#_3-写入时发生什么}

[![Linux 0.11 背景下共享物理页、复制与独占恢复写权限的机制示意](/assets/notes/operating-systems/os-cow.png)](/assets/notes/operating-systems/os-cow.png)

原 PNG 和对应 SVG 均原样保留，正文继续用 PNG。它是 COW 机制抽象，不是 `un_wp_page()` 每条指令的执行顺序；图中引用计数判断针对适用受管理页，不能套到低内存特殊映射。图中“页表”也须结合第一节区分公共根与独立二级表。

### 先纠正页框编号的适用范围

原版 `LOW_MEM=0x100000`，`mem_map` 按物理页地址减去 LOW_MEM 后索引。4 KiB 下绝对物理页框号（PFN，Page Frame Number）42、99 都低于 1 MiB，不能拿来演示普通受管理页引用由 1 变 2。这里改用**假设已合法分配、在实际可用内存范围内**的 PFN1066（`0x42A000`）和 PFN1123（`0x463000`）；不是说该版本一定会按此顺序分配。

| 阶段       | 父映射与内容     | 子映射与内容     | 引用状态                   |
| ---------- | ---------------- | ---------------- | -------------------------- |
| fork 前    | PFN1066，可写，A | 无               | PFN1066=1                  |
| fork 后    | PFN1066，只读，A | PFN1066，只读，A | PFN1066=2                  |
| 子写 B 后  | PFN1066，只读，A | PFN1123，可写，B | 两页各 1                   |
| 父随后写 C | PFN1066，可写，C | PFN1123，可写，B | 两页仍各 1；父这次不必复制 |

[![受管理页从 fork 共享到子复制、父独占恢复写权限的四阶段状态](/assets/notes/operating-systems/os-linux011-cow-states.svg)](/assets/notes/operating-systems/os-linux011-cow-states.svg)

`mm/page.s` 的入口从 CR2 取得故障线性地址，按错误码最低 P 位选择 `do_no_page()` 或 `do_wp_page()`。后者定位 PTE 后调用 `un_wp_page()`：

- `old_page >= LOW_MEM && mem_map[MAP_NR(old_page)] == 1`：直接设置 PTE 可写位、invalidate、返回；不分配新数据页，不复制。
- 其他分支：申请新页，失败则 `oom()`；旧页属于受管理范围时减少旧计数；把当前 PTE 设为 `new_page | 7`，invalidate，再调用 `copy_page(old_page,new_page)` 复制 4096 字节。返回后原写指令重试，才把新页的 A 改为 B。

**源码中更新 PTE 和失效发生在 copy_page 之前**，不要为了符合抽象图的叙述顺序改写事实。这是当时单 CPU 等执行条件下的历史代码，不能原样搬到现代多核。旧页独占条件也只对受管理页走快速路径，低内存来源可能仍需另分新页。

### do_wp_page 的禁用检查不是正在运行的检查

原始源码确有以下片段，注释解释当时库会写代码空间，故暂时关闭该检查：

```c
#if 0
if (CODE_SPACE(address))
    do_exit(SIGSEGV);
#endif
```

`#if 0` 的内容不参与运行。实际函数没有先执行这段“代码空间就退出”的检查，也没有现代虚拟内存区域（VMA，Virtual Memory Area）的完整权限判定，而是进入 `un_wp_page()`。因此不能把原版函数包装成“已确认现代合法 COW 后才分离”，也不能声称真正只读代码写在这个禁用分支中已被拒绝。

通用 COW 和现代 Linux 都需要区分合法私有可写映射的临时写保护与真正禁止写入的映射；不是所有只读页都能合法变成可写。这是原版历史实现的权限边界，不能用现代语义掩盖。

## 4. 任务 0 首次 fork 是特殊情况

`copy_page_tables()` 使用 `nr = (from == 0) ? 0xA0 : 1024`。这里局部 nr 是本轮 PTE 数量，不是第一节 `copy_mem()` 的任务槽参数。首次从基址 0 复制启动映射时，`0xA0=160` 项对应 `160×4096=640 KiB`，而非一整张表所覆盖的 4 MiB。

| 项目                 | 首次从 0 复制的启动案例                           | 普通来源范围                   |
| -------------------- | ------------------------------------------------- | ------------------------------ |
| 每个适用表的遍历项数 | 160，首次数据段界限使本次通常只处理一个目录范围   | 1024                           |
| 低于 1 MiB 的源 PTE  | 源不在该循环中改成只读，也不增加普通 mem_map 计数 | 受管理来源按上一节共享计数规则 |
| 目标有效 PTE         | 清可写位后建立                                    | 清可写位后建立                 |
| 是否复制全部数据内容 | 否                                                | 否                             |

`init/main.c` 在转入用户态后首次 fork，父任务 0 留在 `for(;;) pause()`；代码特别把 fork、pause 做成内联系统调用，避免父方从普通调用返回或调用函数时继续改动仍可能被子方使用的低内存栈。子方可以进入 init 的正常工作，但不能据此推导普通父子私有栈永久共享。

源码注释中的“NO COPY ON WRITE”要结合实际分支理解：启动低内存映射没有普通受管理页那种对称的源/目标写保护和计数机制。**不表示子方任何低内存写入都不会异常**；子 PTE 已只读，写时仍可能在 un_wp_page 中获得新页。保留这些不对称条件，才能解释为何父任务 0 的栈使用必须受特殊约束。

## 5. TLB 与回收必须配套

`get_free_page()` 为合法可用受管理页设置计数 1；复制适用映射增加计数，分离减少旧页计数。`free_page()` 对低于 LOW_MEM 的地址直接返回，对受管理页递减；从 1 到 0 才成为可分配页，重复释放会进入错误处理。不能忽略仍存在的映射和引用，只按某一进程退出就回收共享页。

`free_page_tables()` 清 PTE、释放适用数据页引用，释放二级表并清目录项，最后失效。原版 `invalidate()` 的实现是将 0 重装进 CR3，依赖页目录就在地址 0；这是历史单 CPU 的翻译刷新，不是现代多核失效消息协议，也不是任意系统都能写 CR3=0。

普通写保护、PTE 重定向与回收必须结合引用和旧翻译理解；保留原始代码中的失效及清理上下文，而不是只复制两行赋值。

## 6. 现代 Linux 的私有映射实验

保存为 `cow.c`，以 `gcc -std=c11 -Wall -Wextra -Werror cow.c -o cow` 编译，运行 `./cow`。单线程程序只申请一个私有匿名页，先写 A 再 fork；子写 B，父在等待子退出后仍看到 A：

```c
#define _DEFAULT_SOURCE
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

int main(void)
{
    long page_size = sysconf(_SC_PAGESIZE);
    if (page_size <= 0) {
        fputs("invalid page size\n", stderr);
        return EXIT_FAILURE;
    }
    volatile unsigned char *p = mmap(NULL, (size_t)page_size,
        PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (p == MAP_FAILED) {
        perror("mmap");
        return EXIT_FAILURE;
    }
    *p = 'A';
    printf("before fork: %c\n", (int)*p);
    if (fflush(stdout) == EOF) {
        perror("stdout");
        munmap((void *)p, (size_t)page_size);
        return EXIT_FAILURE;
    }
    pid_t child = fork();
    if (child == -1) {
        perror("fork");
        munmap((void *)p, (size_t)page_size);
        return EXIT_FAILURE;
    }
    if (child == 0) {
        int ok = *p == 'A';
        printf("child initially: %c\n", (int)*p);
        *p = 'B';
        printf("child after write: %c\n", (int)*p);
        if (fflush(stdout) == EOF || ferror(stdout)) ok = 0;
        if (munmap((void *)p, (size_t)page_size) == -1) ok = 0;
        _exit(ok ? 0 : 1);
    }
    int status;
    pid_t result;
    do {
        result = waitpid(child, &status, 0);
    } while (result == -1 && errno == EINTR);
    int ok = result == child && WIFEXITED(status) && WEXITSTATUS(status) == 0;
    printf("parent after wait: %c\n", (int)*p);
    if (*p != 'A') ok = 0;
    if (munmap((void *)p, (size_t)page_size) == -1) {
        perror("munmap");
        ok = 0;
    }
    if (fflush(stdout) == EOF || ferror(stdout)) ok = 0;
    return ok ? EXIT_SUCCESS : EXIT_FAILURE;
}
```

本轮实际输出依次为 `before fork: A`、`child initially: A`、`child after write: B`、`parent after wait: A`，退出成功。它验证现代 Linux 的私有数据隔离语义，不直接展示 PFN 或精确复制次数，更不是 Linux 0.11 的启动、内核写保护处理或低内存特例动态验收。[fork(2)](https://man7.org/linux/man-pages/man2/fork.2.html)

### 固定源码的只读核对

在上述 0.11 源码根目录阅读以下定位结果所在的完整函数：

```sh
grep -nE 'copy_page_tables|LOW_MEM|mem_map|un_wp_page|do_wp_page|CODE_SPACE|invalidate|free_page' mm/memory.c
grep -nE 'copy_mem|0x4000000|free_page_tables|copy_process' kernel/fork.c
grep -nE 'inline|fork|pause|stack' init/main.c
grep -nE 'cr2|testl|do_no_page|do_wp_page|iret' mm/page.s
```

本轮完成源码静态追踪，没有编译或启动该历史内核。

## 本章小结与联读

分段先给出线性范围，独立二级表可以暂时指向相同数据页；普通 COW 的复制与独占恢复要分支理解，任务 0 和禁用检查则必须按历史代码解释。继续阅读[缺页与按需分配](/articles/os-page-faults.html)，现代翻译缓存失效可回看[第十六章](/articles/os-tlb.html)。

[返回本册目录](/collections/operating-systems/)
