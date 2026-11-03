---
id: os-process-lifecycle
title: 第四章 进程状态、fork、exec 与退出
description: "进程是程序运行时的资源与保护环境，包含地址空间、文件引用、身份、信号和执行状态。PCB 用于组织其中的任务信息。沿着创建、运行、阻塞和退出的过程，可以理解这些资源何时建立、共享和回收。"
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
order: 4
---

# 第四章 进程状态、fork、exec 与退出

> 阅读标签：现代Linux/POSIX进程接口。

假设一个命令行工具需要读取文件并统计单词，启动者还想继续接收输入、最后取得统计程序的退出结果。操作系统必须知道：哪个程序正在执行，哪个在等待读取，谁创建了它，以及结束后由谁领取结果。

进程提供运行中的资源与保护环境，包含地址空间、文件引用、身份、信号和执行状态。教材用 PCB（Process Control Block，进程控制块）概括相关记录；它是教学抽象，不要求所有内核都使用同名结构。本章先追踪单线程进程的创建与回收，再把多线程边界放到进阶部分。

## 1. Ready、Running 与 Waiting

![就绪、运行和等待之间的关系](/assets/notes/operating-systems/os-process.svg)

Ready 表示具备运行条件，等待调度；Running 表示当前在某 CPU 上执行；Waiting 表示等待事件。事件完成通常先使任务重新可运行，不保证立刻执行。

这些是教学状态，Linux 的 `TASK_RUNNING` 可以覆盖正在执行与可运行的含义；不能只凭名称推导每个内核状态都和图中一一对应。把创建和退出加入后，还需要下面几步：

1. **创建**：内核建立任务记录及所需资源，设置起始执行现场。创建成功、具备运行条件后，新任务进入可运行集合；创建失败则返回错误，不产生一个可以继续执行的子进程。
2. **就绪 → 运行**：调度器选中任务，CPU 恢复其执行状态。运行任务被抢占或让出执行机会后，可以重新就绪。
3. **运行 → 等待 → 就绪**：需要等待文件数据或其他条件时，任务不再参与普通的可运行选择；事件满足后被唤醒，再等待调度。唤醒不是直接把 CPU 交给它。
4. **退出**：正常结束或被终止后，任务停止执行，地址空间、文件引用等资源按退出规则释放，但内核通常仍保留退出状态和少量身份、统计信息。
5. **僵尸 → 回收**：在通常的父进程等待机制下，尚未被领取的退出记录称为僵尸（Zombie）。父进程用等待接口取得记录后，相关剩余资源才能回收，任务不再以此身份存在。

[![从创建到等待回收的进程生命周期](/assets/notes/operating-systems/os-process-lifecycle.svg)](/assets/notes/operating-systems/os-process-lifecycle.svg)

图按单个进程的教学状态展开，省略停止与恢复等分支。退出与回收不是同一个动作，僵尸不再执行指令。Linux 显式忽略 `SIGCHLD` 或设置 `SA_NOCLDWAIT` 等情形可以不保留通常的僵尸记录，因此这也不是每次退出必经、且必然持续一段时间的状态。[wait(2)](https://man7.org/linux/man-pages/man2/waitpid.2.html) 说明退出状态与等待规则。

## 2. fork 创建子进程并分别返回 {#_2-fork-返回两次-不是代码从头执行两遍}

fork 创建子进程，父子从调用返回处继续，父进程得到子 PID，子进程得到 0，失败则按 API 返回错误。子进程不是重新运行 main 的一个普通函数调用。

PID（Process ID，进程标识符）用来标识进程。假设父进程 PID 为 100，调用前有普通私有变量 `value = 10`，这次成功创建的子进程 PID 为 101：

| 时点       | 父进程 100                         | 子进程 101                         |
| ---------- | ---------------------------------- | ---------------------------------- |
| fork 前    | `value = 10`，即将调用 fork        | 尚不存在                           |
| fork 返回  | 返回值为 `101`，`value` 仍为 `10`  | 返回值为 `0`，`value` 初始为 `10`  |
| 各自修改后 | 执行 `value = 20`，自己的值为 `20` | 执行 `value = 30`，自己的值为 `30` |

内核为子进程准备了从 fork 返回点继续的执行现场，并让两边得到不同返回值，所以程序可以按返回值选择父子分支。它不是让父进程从头调用两次 `main()`。表格仅表示各进程内的步骤，**不保证父进程先执行，也不保证两个修改同时发生**；失败时只有父进程收到 `-1`，可通过 `errno` 判断原因。

父子进程拥有相互独立的常规私有内存逻辑视图。现代 Linux 用 COW（Copy-on-Write，写时复制）优化 fork：暂时共享可适用的底层物理页，在一方写入时按需分离，避免立即复制全部内容。两边即使打印出相同的变量虚拟地址，也不能据此认定它们在修改同一个私有变量。显式共享内存则另按共享语义处理。[fork(2)](https://man7.org/linux/man-pages/man2/fork.2.html)

写时复制的页表细节留到[第十七章](/articles/os-linux011-copy-on-write)；本节只需要分清“私有变量的语义”和“物理页暂时共享”的不同层次。

## 3. 文件状态可能仍共享

文件描述符（File Descriptor，FD）是进程描述符表中的整数索引。打开文件描述（Open File Description）是内核管理的一次打开所对应的状态对象，其中保存文件偏移和文件状态标志。两个概念不能混为一谈。

假设父进程先打开普通文件，内容为 `ABCDEF`，偏移为 0，然后 fork。父子各自的描述符表中都有一个对应项，但它们引用**同一个打开文件描述**。按下表指定的顺序，每次请求恰好成功读取 2 字节：

| 步骤 | 操作                  | 得到的数据 | 共享文件偏移 |
| ---- | --------------------- | ---------- | ------------ |
| 初始 | 父进程打开文件后 fork | —          | 0            |
| 1    | 父进程 read 2 字节    | `AB`       | 0 → 2        |
| 2    | 子进程 read 2 字节    | `CD`       | 2 → 4        |
| 3    | 父进程再 read 2 字节  | `EF`       | 4 → 6        |

这是**指定执行顺序的纸面推演**，无同步时不能保证恰好按父、子、父交替读取；实际程序还需处理短读和错误。若父子分别重新 `open()` 同一个路径，就会各自取得新的打开文件描述，偏移可以分别从 0 推进。`dup()` 则与重新 open 不同，通常仍引用原打开文件描述。[open(2)](https://man7.org/linux/man-pages/man2/open.2.html)

因此私有内存独立，不表示内核资源全部复制成独立对象。继承的文件引用共享适用的偏移和文件状态标志；但 `FD_CLOEXEC` 这样的文件描述符标志属于描述符本身。父进程关闭自己的某个描述符，也不等于把子进程表中对应的描述符一并删除。

## 4. exec 替换当前进程映像

exec 系列成功后不返回原程序继续执行，而是在同一进程身份下装入新的程序映像，包括新的代码、数据和用户栈。以本章单线程子进程为例，`execve()` 前后 PID 保持不变；它不是再创建一个进程。哪些文件描述符会保留，受 close-on-exec 等规则约束。失败时才返回 `-1`，原程序需要处理错误，不能假装已经开始执行新程序。[execve(2)](https://man7.org/linux/man-pages/man2/execve.2.html)

shell 常采用“创建子进程，再在子进程 exec”的路径，但不同 shell、内建命令和优化的实现可能不同。这条教学流程并不是每个命令都必经的唯一源码调用栈。

以执行单词统计程序为例：父进程 fork，子进程 exec 成为统计程序；统计程序读取文件、输出结果并退出；父进程通过 `waitpid(child_pid, &status, 0)` 取得结果。父进程可以先调用 waitpid 而进入等待，也可以在子进程已经退出后立即取得状态，二者都符合这条流程。

[![父子进程中 fork、execve、退出与 waitpid 的关系](/assets/notes/operating-systems/os-fork-exec-wait.svg)](/assets/notes/operating-systems/os-fork-exec-wait.svg)

泳道只规定创建、执行替换、退出和回收之间的依赖；父子没有同步约束的活动不具有固定先后顺序。

## 5. 退出、等待与僵尸

进程退出后，一些资源被释放，父进程仍需通过等待接口取得状态；尚未被适用等待回收的退出信息形成僵尸状态。僵尸不是仍在运行、持续占用 CPU 的死循环程序。

`waitpid()` 不只是“让父进程睡一会儿”：它等待指定范围内的子进程状态变化，并返回对应 PID。对本章 `options = 0` 的普通子进程终止路径，若退出状态已经可领取，就立即完成；若尚未退出，调用线程可能阻塞；如果使用 `WNOHANG`，没有可领取状态时可以返回 `0`。不能直接把 `status` 当作退出码，应先用 `WIFEXITED`、`WIFSIGNALED` 等宏判断类型，再读取适用字段。

| 概念     | 关键事实                                 | 谁处理后续状态                                                                         |
| -------- | ---------------------------------------- | -------------------------------------------------------------------------------------- |
| 僵尸进程 | 已停止执行，但退出记录尚未回收           | 适用的父进程或接管者通过等待接口领取                                                   |
| 孤儿进程 | 原父进程先退出，并不意味着它自己已经退出 | 现代 Linux 由适用的子进程收割者或 PID 命名空间中的 init 接管；后续退出仍按回收规则处理 |

两者不是相反状态：一个正在运行的孤儿还可以继续工作，已经退出的子进程也可能需要被接管并回收。具体接管规则与系统和命名空间有关，不能一概说“所有孤儿都由整台机器的 PID 1 接管”。依据为 [wait(2) 的 NOTES](https://man7.org/linux/man-pages/man2/waitpid.2.html)。

## 6. 实验：创建统计程序并领取退出状态

环境为现代 Linux，任意可用架构，需 GCC 和 `wc`。在新的练习目录中保存下面的 `spawn-demo.c`，再创建示例文件。程序本身是单线程的；父进程只在等待成功后解释退出状态。

```c
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <stdio.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

int main(int argc, char **argv) {
    const char *path = argc > 1 ? argv[1] : "/usr/bin/wc";
    if (fflush(NULL) == EOF) {
        perror("fflush");
        return 1;
    }
    pid_t child = fork();
    if (child == -1) {
        perror("fork");
        return 1;
    }
    if (child == 0) {
        char *args[] = {"wc", "-w", "sample.txt", NULL};
        execve(path, args, environ);
        const char msg[] = "execve failed\n";
        (void)write(STDERR_FILENO, msg, sizeof msg - 1);
        _exit(127);
    }

    int status;
    pid_t result;
    do {
        result = waitpid(child, &status, 0);
    } while (result == -1 && errno == EINTR);
    if (result == -1) {
        perror("waitpid");
        return 1;
    }
    if (WIFEXITED(status)) {
        int code = WEXITSTATUS(status);
        printf("child %ld exited with %d\n", (long)result, code);
        return code;
    }
    if (WIFSIGNALED(status)) {
        printf("child %ld killed by signal %d\n",
               (long)result, WTERMSIG(status));
    }
    return 1;
}
```

```bash
uname -srmo
gcc --version
printf 'red blue\nred\n' > sample.txt
gcc -std=c11 -Wall -Wextra -O0 spawn-demo.c -o spawn-demo
./spawn-demo "$(command -v wc)"
./spawn-demo /no-such-directory/wc
```

观察正常路径的 3 个单词统计及退出码 `0`，PID 由真实系统分配。指定不存在的可执行文件时，子进程报告 `execve failed`，父进程领取本例约定的退出码 `127`；若缺少输入文件，则应由新程序 `wc` 报错并返回自己的非零退出码。`127` 是示例选择，不是所有 exec 失败的内核返回值。

本轮已在 Ubuntu 22.04 / WSL2、Linux `5.15.167.4-microsoft-standard-WSL2`、x86-64、GCC 11.4.0 下局部执行：两个指定路径分别得到 3 个单词和退出码 `0`、exec 失败和退出码 `127`。编译时还加入 `-Werror`，未出现编译警告。没有注入 fork 失败、信号中断或等待接口错误；缺少输入文件的分支仅说明预期行为，未在本轮单独执行。

fork 会复制用户态 I/O 缓冲区的逻辑内容；如果 fork 前留有尚未刷新的输出，父子之后都正常刷新时可能重复输出。例子先检查 `fflush(NULL)`，exec 失败的子进程用 `_exit()` 结束，避免刷新继承的 stdio 缓冲。错误提示仅作尽力写入，不实现通用重试策略。该程序不是一个完整 shell，也没有验证第 3 节的文件偏移顺序。

## 7. 进阶：多线程 fork 的边界

### 现代多线程进程的特殊边界

多线程进程调用 fork 后，子进程只有调用 fork 的线程，不是父进程所有线程一起继续。地址空间却可能复制着其他线程持有的互斥量状态。

纸面反例：父进程 T2 持锁 L，T1 调用 fork；子进程仅有 T1，L 却仍可能显示为已锁。子 T1 再等待 L，不能指望已不存在于子进程的 T2 释放它。现代 POSIX/Linux 的这条多线程路径要求子进程在 fork 到 exec 之间只执行异步信号安全（Async-Signal-Safe）的操作：普通库函数可能依赖继承的内部锁，不能假定它们都能安全使用。

`pthread_atfork()` 可以登记准备、父侧和子侧处理函数，以协调已知状态，但无法自动修复所有第三方库的锁关系。因此启动带后台线程的客户端库后，不应假定 fork 出的子进程可直接复用原客户端实例。这是现代多线程情景，与 Linux 0.11 的历史 fork 分开讨论。[fork(2)](https://man7.org/linux/man-pages/man2/fork.2.html)、[pthread_atfork(3)](https://man7.org/linux/man-pages/man3/pthread_atfork.3.html)

线程和锁的细节分别见[第五章](/articles/os-threads-stacks)与[第八章](/articles/os-atomic-locks)，此处先记住风险来自“线程没有全部复制，但共享内存中的锁状态被继承”。

## 本章小结

- 进程创建后参加调度；等待条件满足通常先回到可运行，退出后还可能需要等待回收。
- fork 创建子进程并分别返回，私有变量独立与底层物理页暂时共享并不矛盾。
- 继承的描述符可能共享同一个打开文件描述，因此共同推进文件偏移。
- exec 换程序而不创建新 PID，waitpid 取得子进程状态，并不总是阻塞。

## 下一章衔接

本章把文件统计交给另一个进程；[第五章](/articles/os-threads-stacks)改用同一进程中的多个线程，看看哪些资源可以共享、哪些执行状态必须各自保留。

[返回本册目录](/collections/operating-systems/)
