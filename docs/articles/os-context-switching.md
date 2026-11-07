---
id: os-context-switching
title: 第六章 上下文切换、中断与内核栈
description: "上下文切换的目标是保存当前任务的执行进度，并恢复另一个任务的进度。理解完整路径时，可以依次观察进入内核、保存陷入状态、是否需要调度、恢复执行这几个环节。"
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
order: 6
---

# 第六章 上下文切换、中断与内核栈

> 阅读标签：通用入口模型 / 0.11 TSS与抢占条件。

第五章让两个线程分别统计数据。如果线程 A 读取的数据尚未就绪，CPU 可以先执行线程 B；等 A 再次运行时，它必须接着先前的读取继续，而不能借用 B 的返回地址。上下文切换的目标就是保存当前任务的执行进度，并恢复另一个任务的进度。

理解这条路径，要区分进入内核、处理事件、是否需要调度、切换任务和返回用户态。它们可以相邻发生，却不是同一个操作。本章的 A/B 案例采用现代 1:1 线程的教学模型；Linux 0.11 部分另按该版本的单处理器任务实现分析，不把它写成拥有现代 pthread 的系统。

## 1. 陷入状态与调度上下文的保存 {#_1-哪些状态要保存}

| 操作             | 触发与涉及的状态                                         | 是否更换任务                                           |
| ---------------- | -------------------------------------------------------- | ------------------------------------------------------ |
| 用户态进入内核态 | 系统调用或适用的事件入口；建立返回所需现场与内核执行环境 | 不必；仍可由同一个任务执行内核代码                     |
| 中断或异常处理   | 设备、时钟事件或当前指令触发；保存必要现场并处理事件     | 不必；中断后可以返回被中断任务。事件也可能发生在内核态 |
| 任务上下文切换   | 调度选择另一个可运行任务；保存当前续接状态并恢复被选任务 | 是；若调度仍选原任务，则不必做一次不同任务间的切换     |

例如一个本次无需等待的短读取：A 的用户代码进入内核，内核取得可用数据、复制并返回，CPU 始终替 A 执行。这里有入口状态保存与特权环境转换，却没有必然更换任务。如果发生其他抢占条件，仍可能调度，因此“无需等待”也不是绝不切换的承诺。

[![上下文切换：异常入口、唤醒与调度](/assets/notes/operating-systems/os-context.svg)](/assets/notes/operating-systems/os-context.svg)

图中把无需调度的返回与需要调度的续接分开；等待任务被唤醒之后，仍需再次被选中才能执行。下面三类记录也应分开理解：

| 记录                             | 保存什么、解决什么问题                                                 | 不应怎样理解                                                     |
| -------------------------------- | ---------------------------------------------------------------------- | ---------------------------------------------------------------- |
| 陷入帧（Trap Frame）             | 架构入口与软件保存的返回位置、标志、寄存器等，用于恢复被打断的执行环境 | 不是每次建立它就立刻切换任务；各内核名称与布局不同               |
| 调度上下文（Scheduling Context） | 任务在内核中暂停时的续接点、栈位置和必须保留的状态，用于日后接着执行   | 不是把用户返回帧再完整复制一遍；与硬件任务切换的存放方式也不相同 |
| 任务资源描述                     | 地址空间、文件、身份等对象及其引用，回答任务使用哪些资源               | 不是每次调度都复制整个堆或文件内容                               |

“陷入帧”在这里是跨入口理解现场的教学名称，不代表所有架构都有同名结构。现场由硬件、入口汇编、普通调用约定和切换机制分层保存；阅读 `switch_to` 必须结合这些相邻环节，而不能要求一个函数独自保存所有信息。

## 2. 进入内核时的栈与返回状态 {#_2-从用户态进入内核时-压到哪一个栈}

先固定一个具体路径：**Linux 0.11 的 32 位 x86，普通任务在 ring 3 执行时遇到时钟中断，经 IDT 的中断门进入 ring 0**。IDT（Interrupt Descriptor Table，中断描述符表）定位事件入口，TSS（Task State Segment，任务状态段）在此提供内核栈信息。

1. 中断前，CPU 使用用户栈，里面仍有用户函数的调用链；寄存器记录当前执行位置与计算状态。
2. CPU 根据中断门和目标特权级进行转移，从当前任务 TSS 的 `SS0:ESP0` 取得 ring 0 栈。在新栈保存旧 `SS/ESP`、`EFLAGS`、`CS/EIP`，建立返回用户态所需的硬件现场；中断门还会清除 IF，使可屏蔽中断暂时关闭。此时硬件并未替内核保存全部通用寄存器。
3. `kernel/system_call.s` 的 `_timer_interrupt` 再保存 `DS/ES/FS` 与 `EDX/ECX/EBX/EAX` 等它需要保护的寄存器，设置适用段寄存器，更新时钟计数并调用 `do_timer()`。普通 C 调用还按编译约定保护其他必须保留的状态。
4. 若这条路径不调度其他任务，就沿返回代码恢复软件保存的寄存器，最终 `iret` 从硬件现场恢复用户执行环境。原用户栈上的调用链没有被搬成 B 的栈。

如果需要调度，当前内核调用链和入口现场要留存，并保存可以续接它的状态；下次选回此任务时，先恢复它自己的内核执行，再根据入口返回路径回到用户代码。Linux 0.11 普通任务的内核栈位于任务分配页中，`kernel/fork.c:copy_process()` 为其设置 `tss.esp0`；不能因此推广成所有内核都把任务结构和内核栈放在同一页。

这条说明只适用于指定的跨特权级入口。同级中断不应照抄一遍跨特权级切栈步骤；不同异常还可能包含错误码。Linux 0.11 的 `int 0x80` 使用允许用户调用的陷阱门，不能把中断门的 IF 行为也直接套过去。

现代原生 **x86-64 `SYSCALL` 本身不自动切换 RSP**：硬件把返回位置与标志保存在指定寄存器，内核入口软件再保存用户栈指针、切换适用栈并组织现场。额外的中断栈、异常专用栈与页表隔离也须按版本和入口讨论。对照 [Linux 6.12 entry_64.S 的 entry_SYSCALL_64](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/entry_64.S)与 [Intel 架构手册](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html) Volume 3A 的 Interrupt and Exception Handling、Task Management，不能拼接成所有 CPU 的通用压栈程序。

## 3. 阻塞、调度与唤醒后的继续执行 {#_3-阻塞怎样让出-cpu}

假设同一现代进程中的线程 A 正在读取并统计数据，线程 B 已可运行；为看清交替，图中只观察一个 CPU 核。指定本次 read 确实需要等待，且调度器在 A 等待后选择 B。这是一条可能路径，不是每次读取的固定时序。

| 时点 | A 的状态与保存位置                                           | CPU 上的执行                                                        |
| ---- | ------------------------------------------------------------ | ------------------------------------------------------------------- |
| T1   | A 在用户态运行，用户栈保留统计函数调用链                     | 执行 A                                                              |
| T2   | A 发起 read，进入内核；入口现场保留用户返回状态              | 仍执行 A 的内核路径                                                 |
| T3   | 条件未满足，A 按等待协议登记并进入等待；保留内核栈与续接状态 | 调度选择 B，切换 A → B                                              |
| T4   | A 等待                                                       | 恢复 B 先前的执行位置；B 可先从自己的内核续接处继续，再回到用户代码 |
| T5   | 条件满足，A 被唤醒，成为可运行任务                           | 不保证立刻切到 A，B 或其他任务仍可能执行                            |
| T6   | A 再获调度，恢复自己的内核续接点，重新检查条件并完成读取     | 切回 A，处理返回前工作，再返回 A 的用户统计函数                     |

[![单核观察下 A 等待、B 运行与 A 再次恢复的时间线](/assets/notes/operating-systems/os-context-timeline.svg)](/assets/notes/operating-systems/os-context-timeline.svg)

A 被唤醒并重新获得调度后，会沿自身等待结束后的路径继续执行，而不是跳到 B 的用户返回地址。每个执行流的栈都必须与其续接点匹配。等待协议还要避免“条件刚满足却错过唤醒”的竞态，唤醒后通常需要重新检查条件，不能把伪时间线当作完整同步算法。

这条路径区分两种“返回”：切换机制使 A 从自己的内核暂停点恢复；系统调用返回机制之后才把 A 带回用户态。两线程共享地址空间，所以更换执行线程不等于必然切换成另一个进程的地址空间。

### Linux 0.11：时钟耗尽不必立即抢占内核

`_timer_interrupt` 从保存的 `CS` 中取最低两位，传给 `do_timer(long cpl)`。这里的 cpl 表示**被中断代码**的 CPL（Current Privilege Level，当前特权级），不是说正在执行的 `do_timer` 仍处于用户态。原版 `kernel/sched.c` 中该函数的末尾为：

```c
if ((--current->counter)>0) return;
current->counter=0;
if (!cpl) return;
schedule();
```

`counter` 是该历史调度器使用的剩余计数。计数仍大于 0 时直接返回；耗尽后归零，若中断前 CPL 为 0，就不在这条时钟路径直接调用 `schedule()`；从用户态进入且计数耗尽时才沿此处调度。

所以“内核代码正在执行 → 时钟一到 → 立刻从任意内核位置切走”不是原版 0.11 的模型。但内核代码**仍可显式阻塞并调度**：例如 `fs/buffer.c` 的 `bread()` 会经过适用的 `wait_on_buffer()`，后者在缓冲区仍锁定时调用 `sleep_on()`；`kernel/sched.c:sleep_on()` 设置等待状态后主动调用 `schedule()`。系统调用退出检查等路径也需要另行观察，不能把时钟末尾的一次 return 当作整个内核永不调度的证据。

这些结论限定于原版 0.11。现代 Linux 的可抢占配置、并发控制和多处理器实现已经不同，也不能把历史代码中关本地中断的做法当成现代 SMP（Symmetric Multiprocessing，对称多处理）系统的完整同步方案。

## 4. 中断返回恢复特权与执行状态 {#_4-中断返回不等于普通-ret}

| x86 返回方式                  | 恢复的核心内容                                                           | 与调度的关系                                             |
| ----------------------------- | ------------------------------------------------------------------------ | -------------------------------------------------------- |
| 本例的普通近返回 `ret`        | 从当前调用栈取函数返回位置，按调用约定接回调用者；不自动恢复完整特权现场 | 可以出现在调度函数或普通函数的返回中，不是“切换任务指令” |
| 本例的 32 位 `iret` / `iretd` | 从中断返回现场恢复 `EIP/CS/EFLAGS`；适用的跨特权级返回还恢复 `ESP/SS`    | 可以返回原任务，也可以在选定任务恢复后返回其用户上下文   |

内核入口软件保存的通用寄存器仍需由软件恢复，不能指望 `iret` 自动理解所有软件栈帧。名称和操作数宽度随汇编语法及模式变化，现代 64 位还有 `iretq` 等路径；RISC-V 等架构又有自己的返回指令。原版 0.11 的 TSS 任务切换本身使用后文的 `ljmp` 路线，不是简单地拿 `iret` 替换一条普通 `ret`。

内核正在处理一个可立即完成的系统调用时，可能完全不调度其他任务。因此“从用户栈到内核栈”不等于“地址空间发生一次进程切换”。

## 5. Linux 0.11 与课程改写版

### 从 schedule() 到硬件任务切换

原版 `kernel/sched.c:schedule()` 在普通任务中寻找 `state == TASK_RUNNING` 且 `counter` 合适的候选；必要时重新分配计数，没有普通可运行任务时可选任务 0。具体选择算法放在第七章，本节关注选出编号 `next` 后的 `switch_to(next)`。

`include/linux/sched.h` 定义了 `tss_struct`，包含 `EIP`、`ESP`、通用寄存器、段选择子、CR3、特权栈信息等架构字段；任务的 TSS 还通过 GDT 描述符供 CPU 定位。GDT（Global Descriptor Table，全局描述符表）在这里负责描述这些系统结构，不等于把整个任务资源复制进去。初始化与创建路径分别安装相应描述符，调度并不是每次重新创建 TSS。

`switch_to(n)` 的关键步骤为：

1. 比较目标 `task[n]` 与 `current`；相同就跳过实际切换。
2. 把 `_TSS(n)` 选择子放入临时远指针的选择子字段，并用 `xchgl` 更新软件的 `current` 指针。`_TSS(n)` 计算的是 GDT 中的选择子，不是 TSS 在内存中的裸地址。
3. 执行 `ljmp`。目标选择子引用 TSS 描述符，因此这次远跳转走 80386 的**硬件任务切换**规则：CPU 把旧任务适用的执行状态保存到旧 TSS，装入新 TSS 中的执行环境，包含继续执行所需的指令位置与栈状态。它不是跳到远指针偏移所指定的一段普通函数代码。
4. 对曾在这条路径切走的任务，日后再被恢复时，将继续执行它自己保存的 `ljmp` 之后的代码，并返回自己的调度调用链。新创建任务的初始现场则由 `copy_process()` 等创建路径设置，不能说所有任务第一次运行都从同一条内核返回语句开始。
5. 宏还根据 `last_task_used_math` 等状态处理适用的协处理器标志。浮点状态、入口软件现场、内核调用栈和文件资源不能笼统说成由这一条指令全部保存或复制。

这说明三个保存位置可以共同工作：用户返回现场留在适用的内核栈，内核调用链留在自己的栈上，TSS 保存能重新接回这条内核路径的硬件状态。切换到 B 时不需要把 A 的调用链改写成 B 的内容。

课程可能把 `switch_to` 改为软件保存寄存器与切换内核栈；现代原生 x86-64 Linux 也不沿用 0.11 的这套硬件任务切换。两种代码不能标成同一份原版实现，更不能无实验地把性能差异归因于一句“不能利用流水线”。现代对照见 [Linux 6.12 entry_64.S 的 __switch_to_asm](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/entry_64.S)，它与系统调用入口承担不同职责。

本册以 [kernel.org 原版源码](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)核对历史路径；[xv6 的陷入与调度章节](https://pdos.csail.mit.edu/6.1810/2024/xv6/book-riscv-rev4.pdf)仅作为另一架构的对照。没有编译或运行切换代码。

## 6. 实验：观察线程的上下文切换计数

现代 Linux 的 `/proc/<PID>/task/<TID>/status` 提供线程状态信息。PID 标识进程，TID（Thread ID，线程标识符）标识该目录中的内核线程；它不应直接等同于库类型 `pthread_t`。本实验使用单线程 Python 程序，所以主线程的 TID 与 PID 相同。

- `voluntary_ctxt_switches`：通常反映任务因等待等原因主动让出的切换。
- `nonvoluntary_ctxt_switches`：通常反映任务仍可运行却被换下的切换，例如抢占。

字段是累计计数，具体分类由内核实现决定；`schedule()` 被调用也不必然使计数加一，实际仍选原任务时没有发生不同任务间的切换。接口与实现依据为 [proc_pid_status(5)](https://man7.org/linux/man-pages/man5/proc_pid_status.5.html)、[proc_pid_task(5)](https://man7.org/linux/man-pages/man5/proc_pid_task.5.html)和 [Linux 6.12 __schedule() 中的 nvcsw/nivcsw 更新](https://github.com/torvalds/linux/blob/v6.12/kernel/sched/core.c)。这不是 Linux 0.11 的实验。

需具有可读 procfs 的现代 Linux、Python 3、shell 与 grep。先记录 `uname -srmo`、`python3 --version`，把以下程序保存为 `ctx-work.py`：

```python
import sys
import time

if len(sys.argv) != 2 or sys.argv[1] not in {"cpu", "sleep"}:
    raise SystemExit("usage: python3 ctx-work.py cpu|sleep")

mode = sys.argv[1]
deadline = time.monotonic() + 6.0
value = 0
while time.monotonic() < deadline:
    if mode == "sleep":
        time.sleep(0.01)
    else:
        value = (value + 1) % 1000003
```

再依次运行两种负载，在任务存活期间采两次状态：

```bash
uname -srmo
python3 --version
for mode in cpu sleep; do
    python3 ctx-work.py "$mode" &
    workload_pid=$!
    workload_tid=$workload_pid
    status_file="/proc/$workload_pid/task/$workload_tid/status"
    sleep 1
    for sample in 1 2; do
        printf '%s sample=%s pid=%s\n' "$mode" "$sample" "$workload_pid"
        if [ -r "$status_file" ]; then
            grep -E '^(voluntary|nonvoluntary)_ctxt_switches:' "$status_file"
        else
            printf 'task exited or status is inaccessible\n'
            break
        fi
        if [ "$sample" = 1 ]; then sleep 2; fi
    done
    wait "$workload_pid"
done
```

应比较每个任务两次读数的增量。sleep 负载通常更容易体现主动等待造成的切换；CPU 负载可能出现非自愿切换，但空闲多核机器上增量很小甚至为 0 也不违反原理。系统负载、CPU 数量、亲和性、调度策略、内核版本与 Python 实现都会影响结果，不能预先填写固定数值。

本轮在 Ubuntu 22.04 / WSL2、Linux `5.15.167.4-microsoft-standard-WSL2`、x86-64、Python 3.10.12 下运行上述两种负载，未额外设置 CPU 亲和性。一次实际采样如下，表中两次数值对应同一任务，不能把这组结果当成验收阈值：

| 负载  | voluntary：样本 1 → 2 | nonvoluntary：样本 1 → 2 |
| ----- | --------------------- | ------------------------ |
| cpu   | 42 → 42，增量 0       | 4 → 6，增量 2            |
| sleep | 138 → 335，增量 197   | 0 → 0，增量 0            |

CPU 任务的累计主动切换数不必从 0 开始，启动和运行时活动也可能留下历史计数；这里只比较观察区间增量。此实验展示现代内核的统计接口，不能用它验证 0.11 的 `ljmp` 任务切换。

采样并非对所有字段的原子快照；任务可能提前退出，procfs 也可能受权限限制。观察者自己执行 grep 和 sleep，不会把自己的计数写进目标线程，但会改变系统竞争情况。累计计数无法直接证明“某一次系统调用恰好切换了几次”，也不能据此还原完整 A/B 时间线。

## 联读

先读[第五章的共享资源与独立线程上下文](/articles/os-threads-stacks.html)，再用本章的保存与恢复理解执行流如何交替。接下来[第七章 CPU 调度](/articles/os-cpu-scheduling.html)讨论“应该选谁、何时再选”，与本章“选中之后怎样恢复”分工不同。

## 本章小结

- 进入内核、处理事件与切换任务是不同动作，保存入口现场不意味着一定调度。
- 用户返回现场、内核续接状态与资源描述分层维护，恢复时要配回同一任务。
- 阻塞使任务让出运行机会，唤醒通常只使其可运行，之后再由调度选中。
- 原版 Linux 0.11 经 TSS 选择子和 ljmp 进行硬件任务切换，时钟路径不从任意内核位置直接抢占，但内核仍能显式阻塞调度。

[返回本册目录](/collections/operating-systems/)
