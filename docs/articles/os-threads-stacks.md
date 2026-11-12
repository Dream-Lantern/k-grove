---
id: os-threads-stacks
title: 第五章 用户线程、内核调度实体与栈
description: "线程是可独立推进的执行上下文。多个线程通常共享所属进程的地址空间和资源，各自维护执行所需的栈、寄存器与线程局部状态。线程切换要保存当前执行位置和上下文，使它日后能够沿原来的调用链继续。"
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
order: 5
---

# 第五章 用户线程、内核调度实体与栈

> 阅读标签：通用线程模型 / 现代线程概念。

假设 Web 服务正在处理请求 A，需要等待外部文件或网络数据；此时请求 B 到达，只需对内存中的数据做少量统计。如果只有一个串行执行流，A 的阻塞可能使 B 也无法开始。多个线程让不同请求保留自己的执行进度：在适用的调度模型下，A 等待时 B 仍可以运行。

线程是可独立推进的执行上下文。多个线程通常共享所属进程的地址空间和资源，各自维护栈、寄存器与线程局部状态。这样减少了部分资源复制和进程间传递，但也使共享数据需要同步。多线程不是实现并发的唯一方法：事件循环与非阻塞 I/O 也能组织多个请求，采用哪种方式取决于工作负载与运行时。

## 1. 调用栈保存各自的执行进度 {#_1-为什么不能随意共用一个调用栈}

第四章通过不同进程处理文件统计；这里先把数据准备在同一进程内，再交给两个执行流。它们不必各自建立完整的资源保护环境，却必须分别记住“当前执行到哪一步”。

| 通常共享的进程资源                                         | 每个线程独立维护的状态                                          |
| ---------------------------------------------------------- | --------------------------------------------------------------- |
| 虚拟地址空间，以及其中的代码、全局数据和堆                 | 程序计数器（Program Counter，PC）与适用寄存器状态               |
| 文件描述符表；某线程关闭描述符会影响同进程其他线程使用该项 | 调用栈、栈指针（Stack Pointer，SP）与函数返回所需状态           |
| 进程身份、当前目录与信号处理方式等                         | TLS（Thread-Local Storage，线程局部存储），例如各线程的 `errno` |
| 共享对象的内容；共享不代表允许无同步地任意修改             | 线程信号屏蔽字等线程属性                                        |

这张表采用 POSIX 线程的常见语义；TLS 提供每线程的对象实例，不是额外的硬件保护域。[pthreads(7)](https://man7.org/linux/man-pages/man7/pthreads.7.html)

[![同一地址空间内的共享数据与两条调用栈](/assets/notes/operating-systems/os-threads.svg)](/assets/notes/operating-systems/os-threads.svg)

图把栈画成同一虚拟地址空间中的不同区域，线程上下文中的寄存器则是运行时由 CPU 使用、暂停时按实现保存的状态，不是另外两块隔离地址空间。

### 两条函数调用链怎样分别返回

假设 A 是初始线程，调用 `main → process_request → read_data`；B 从工作函数开始，调用 `worker → calculate → sum`。当前 A 在 `read_data` 等待数据，B 在 `sum` 计算：

| 执行流 | 当前执行位置                             | 示意调用栈与后续返回顺序                                        |
| ------ | ---------------------------------------- | --------------------------------------------------------------- |
| A      | `read_data` 内部的当前位置，之后可能等待 | 栈上保留调用关系；read_data 返回到 process_request，再返回 main |
| B      | `sum` 内部的当前位置                     | sum 返回到 calculate，再返回 worker                             |

函数调用按 ABI（Application Binary Interface，应用二进制接口）保存必要的返回地址与调用者状态，可能还使用栈帧（Stack Frame）容纳参数、临时值或溢出到内存的寄存器值。**局部变量也可能放在寄存器中，编译器还可能内联或省略某些栈帧**，图示不是优化后机器码的固定布局。

SP 标记当前栈的使用位置；暂停执行时，必须保留它和对应续接位置。函数返回地址说明“本次函数结束后去哪里”，暂停点则说明“尚未结束的函数从哪里继续”，二者不能混为一谈。如果两个执行流未经管理地复用同一段可变栈，B 的压栈和返回可能覆盖 A 尚未使用的返回地址或数据，A 恢复时便会沿损坏的调用链执行。

独立栈使两条调用链可以分别推进，**不意味着它们之间存在硬件内存隔离**。同进程线程通常可通过有效指针访问另一线程的栈；传递栈上对象的地址时，要保证函数尚未返回、对象仍存活，并处理并发访问。协程、分段栈和无栈状态机另有执行状态管理方式，不能统一套用图中的固定栈帧。

## 2. 用户级调度的 M:1 情况

用户级执行流由运行时安排；**内核调度实体**是内核能独立选择、暂停和恢复的任务。M、N 表示数量，映射描述的是执行流由谁承载，不是它访问了几块内存。

若 M 个用户级线程只由 1 个内核调度实体承载，运行时可以在用户态保存栈和寄存器并选择另一执行流，无需每次都请求内核更换任务。但当这个唯一承载者执行阻塞系统调用而进入等待时，其余用户线程暂时也没有承载者可以运行。在这一映射下，这些执行流不能同时占据多个 CPU 核。

[![M:1、1:1、M:N 中用户级执行流与内核实体的映射](/assets/notes/operating-systems/os-thread-models.svg)](/assets/notes/operating-systems/os-thread-models.svg)

图中箭头表示承载关系，不是固定调用顺序。M:N 的连线表示由运行时把多个可运行执行流分派到多个承载者；不表示同一个执行流可以同时在多个承载者上执行。

运行时可以用非阻塞 I/O 与事件循环避免独占承载者的等待，也可以改用多个内核调度实体承载用户任务。这些选择改变了阻塞行为，不能把 M:1 的限制扩大成“所有用户级线程都无法利用多核”。

## 3. 常见 1:1 模型

现代 Linux 常用的 NPTL（Native POSIX Threads Library，原生 POSIX 线程库）采用 **1:1**：每个 pthread 对应一个内核可独立调度的实体。一个线程阻塞不必让其他可运行线程全部停止；若有多个 CPU 核和适用的调度机会，它们可以并行。创建线程并不保证立刻运行或必然并行。[pthreads(7) 的实现说明](https://man7.org/linux/man-pages/man7/pthreads.7.html)

**M:N** 则由运行时把 M 条用户级执行流安排到 N 个内核调度实体，内核再决定这些承载者在哪些 CPU 核上运行。只要仍有可用承载者，某个承载者的等待不必阻止全部用户任务推进；但如果承载者都被阻塞，或者共享锁形成依赖，也可能整体停滞。运行时调度与内核调度分属两层，阻塞恢复和执行流迁移需要额外协调。

因此用户级线程不必然等于 M:1；具体语言的协程或任务也不能仅凭名字归入一种模型，应查看其运行时如何使用内核调度实体。

三种映射的概念可对照 [Oracle 的历史 Multithreading Models 文档](https://docs.oracle.com/cd/E19455-01/806-3461/6jck06gqk/index.html)。其中的 Solaris/JDK 实现仅作历史实例，不用于推断现代 Java 或 Linux 必然采用哪一种映射。

## 4. 内核线程与有用户线程的任务不同

“内核线程”有时被用来指承载用户执行的内核任务，有时特指只执行内核工作的线程。为避免歧义，本章区分三种角色：

| 角色                 | 谁安排执行                         | 是否执行用户程序                                   |
| -------------------- | ---------------------------------- | -------------------------------------------------- |
| 运行时用户级线程     | 运行时选择，再由内核承载者获得 CPU | 执行用户代码，不必逐个成为内核可见任务             |
| 内核可调度的用户线程 | 内核独立调度，例如 NPTL 的 pthread | 既有用户态执行状态，也有进入内核时所需的内核上下文 |
| 纯内核线程           | 内核调度                           | 运行内核工作，不需要用户程序的调用栈               |

例如 Linux 6.12 的普通纯内核线程不拥有自己的用户地址空间，可能借用地址环境运行；这不表示它没有任何页表或不能使用内核虚拟地址。不能统一写成“每个内核线程必然配一对用户栈、内核栈”。实现可对照 [Linux 6.12 调度器的 context_switch()](https://github.com/torvalds/linux/blob/v6.12/kernel/sched/core.c)，其中区分内核线程与用户任务的地址空间处理。

TCB（Thread Control Block，线程控制块）是组织线程状态的教学抽象。保存哪些寄存器、TLS 怎样恢复、栈如何初始化，取决于 ABI、编译器和运行时。只在堆里分配一块内存，再把函数地址放上去，不足以构成可移植、正确的线程创建实现。

## 5. 教学切换示意

```text
保存当前执行流必须保留的寄存器与栈位置
选择下一条可运行执行流
恢复它的栈位置及约定的保存状态
从它先前保存的续接点继续
```

这段伪代码只展示保存与恢复的顺序。可运行的实现还要处理中断、信号、异常展开、向量寄存器、栈对齐和清理函数，具体要求取决于 ABI 与运行时。

学习时，先画出各执行流的调用链和栈，再分析共享资源，有助于区分“执行切换”与“资源隔离”。

## 6. 实验：两个 pthread 读取同一份数据

环境为现代 Linux 的 NPTL/pthread 实现，任意可用架构，需 GCC。把程序保存为 `threads-demo.c`。A 统计单词，B 统计字节；它们只读同一个全局数组，各自使用局部计数器，避免把无保护的共享写入当成正确用法。

```c
#include <pthread.h>
#include <stdio.h>
#include <string.h>

static const char text[] = "red blue\nred";

static void *count_words(void *unused) {
    (void)unused;
    size_t words = 0;
    int in_word = 0;
    for (const char *p = text; *p; ++p) {
        int space = *p == ' ' || *p == '\n' || *p == '\t';
        if (!space && !in_word) ++words;
        in_word = !space;
    }
    printf("A: words=%zu shared=%p local=%p\n",
           words, (const void *)text, (void *)&words);
    return NULL;
}

static void *count_bytes(void *unused) {
    (void)unused;
    size_t bytes = strlen(text);
    printf("B: bytes=%zu shared=%p local=%p\n",
           bytes, (const void *)text, (void *)&bytes);
    return NULL;
}

static int report_error(const char *operation, int error) {
    if (error == 0) return 0;
    fprintf(stderr, "%s: %s\n", operation, strerror(error));
    return 1;
}

int main(void) {
    pthread_t a, b;
    int error = pthread_create(&a, NULL, count_words, NULL);
    if (report_error("pthread_create A", error)) return 1;
    error = pthread_create(&b, NULL, count_bytes, NULL);
    if (report_error("pthread_create B", error)) {
        report_error("pthread_join A", pthread_join(a, NULL));
        return 1;
    }
    int failed = report_error("pthread_join A", pthread_join(a, NULL));
    failed |= report_error("pthread_join B", pthread_join(b, NULL));
    return failed;
}
```

```bash
uname -srmo
gcc --version
gcc -std=c11 -Wall -Wextra -O0 -pthread threads-demo.c -o threads-demo
./threads-demo
```

`pthread_create()` 建立线程并让它从指定函数开始；`pthread_join()` 等待适用的可连接线程结束，并回收其所需资源。大部分 pthread 接口直接返回错误号，不能统一用 `perror()` 读取 `errno` 来解释。编译和链接都使用 `-pthread`。[pthread_create(3)](https://man7.org/linux/man-pages/man3/pthread_create.3.html)、[pthread_join(3)](https://man7.org/linux/man-pages/man3/pthread_join.3.html)

观察 A 报告的 3 个单词与 B 报告的 12 字节；两行的 shared 指针表示同一个数组，local 指针对应各自函数中仍存活的局部对象。输出顺序不保证 A 在 B 前，先 join A 也不代表先让 A 执行。地址取决于实际布局、栈分配与地址随机化，不能在预期输出中写死；顺序创建线程也不能证明它们确实同时运行。

本轮已在 Ubuntu 22.04 / WSL2、Linux `5.15.167.4-microsoft-standard-WSL2`、x86-64、GCC 11.4.0、glibc 2.35 下，用额外的 `-Werror` 严格编译并运行 3 次。每次均得到 words 为 `3`、bytes 为 `12`、两线程 shared 地址相同且 local 对象地址不同的结果。各次运行的地址值与线程输出顺序可能不同。

例子不把局部变量地址保存到线程结束之后，也不从线程返回局部对象的地址。若改成分别读取文件，两线程共享描述符表和可能的文件偏移，仍要按第四章的资源语义设计；若改成并发写同一个统计值，则需第八章介绍的同步机制。

## 联读

上一章[进程生命周期](/articles/os-process-lifecycle.html)介绍独立进程；本章解释同一进程内的执行流。下一章[入口、内核续接与切换](/articles/os-context-switching.html)将继续追踪两个线程的状态怎样保存和恢复。

## 本章小结

- 线程可以独立推进，却通常共享进程资源；共享数据的正确访问需要额外约束。
- 各自的调用栈、寄存器和 TLS 用于保留执行进度，独立栈不构成强隔离边界。
- M:1、1:1、M:N 区分用户执行流与内核承载者的映射，不能只看“用户线程”这个名字。
- 纯内核线程与可在用户态执行的内核调度实体不同，栈与地址环境应按实现讨论。

[返回本册目录](/collections/operating-systems/)
