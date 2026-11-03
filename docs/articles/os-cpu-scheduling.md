---
id: os-cpu-scheduling
title: 第七章 CPU 调度与 Linux 0.11 复盘
description: "调度从当前可运行的实体中选择下一个使用 CPU 的任务。算法会影响任务首次得到服务的时间、完成时间和 CPU 分配方式，因此需要结合交互响应、平均周转、公平、吞吐或截止期等目标评价。"
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
order: 7
---

# 第七章 CPU 调度与 Linux 0.11 复盘

> 阅读标签：教学调度算法 / 0.11源码 / 现代Linux旁注。

假设三个数据统计任务同时准备好，但只有一个 CPU 核。先把最长任务算完，还是先让每个任务运行一小段？两种安排都可能最终完成全部工作，却会让用户看到不同的首次响应和完成时间。

调度从当前可运行的实体中选择下一个使用 CPU 的任务。第六章解释选中后怎样恢复执行，本章解释选择策略及评价指标。交互响应、平均周转、公平、吞吐或截止期等目标之间存在取舍，不能只凭一个平均数判断所有负载。

## 1. 先定义三个时间指标

对任务记录到达时刻 a、首次执行时刻 s、完成时刻 f，以及总 CPU 执行时间 b：

| 指标                                     | 定义                            | 本章计算方式                                                                     |
| ---------------------------------------- | ------------------------------- | -------------------------------------------------------------------------------- |
| 响应时间（Response Time）                | 从到达到首次获得 CPU 的延迟     | s − a；不是整个请求的网络响应耗时                                                |
| 周转时间（Turnaround Time）              | 从到达到完成的总时间            | f − a                                                                            |
| 就绪等待时间（Ready Queue Waiting Time） | 可运行却没有占用 CPU 的累计时间 | 统计处于就绪状态的区间；无 I/O、无其他等待且忽略切换成本时，才可直接用 f − a − b |

例如任务到达于 0，首次运行于 4，共用 CPU 2 个时间单位，并在 6 完成：响应为 4，周转为 6，在上述简化模型中就绪等待为 4。如果期间还阻塞等待设备，就不能把所有没有执行 CPU 的时间都算成就绪等待。

下面用同一组输入算出三种策略的全部指标，区间采用左闭右开，例如 0～2 表示 `[0, 2)`。算法模型与指标的概念依据见 [OSTEP 的 Scheduling: Introduction](https://pages.cs.wisc.edu/~remzi/OSTEP/cpu-sched.pdf)，本章数值另行计算。

## 2. FCFS、SJF 与 RR

FCFS（First-Come, First-Served，先来先服务）按到达/排队顺序执行；SJF（Shortest Job First，最短作业优先）优先执行预计 CPU 工作较短的任务；RR（Round Robin，时间片轮转）在每段预算用完后，把仍有工作可做的任务放回队尾。

固定条件为单 CPU、无 I/O、忽略上下文切换成本，三个任务全部在时刻 0 到达。CPU Burst 是本次连续需要执行的 CPU 工作量，本例单位为抽象时间，不直接代表真实机器毫秒。

| 任务 | 到达时间 | CPU Burst |
| ---- | -------: | --------: |
| A    |        0 |         8 |
| B    |        0 |         4 |
| C    |        0 |         2 |

FCFS 的初始队列为 A、B、C；SJF 为非抢占式，且本例已知实际运行时长；RR 时间片为 2，初始队列同为 A、B、C。

[![相同输入下 FCFS、SJF、RR 的执行区间与时间片](/assets/notes/operating-systems/os-schedule-gantt.svg)](/assets/notes/operating-systems/os-schedule-gantt.svg)

- FCFS：A 0～8 → B 8～12 → C 12～14。长任务 A 先占用 CPU，后续短任务只能等待。
- SJF：C 0～2 → B 2～6 → A 6～14。短任务先完成，长任务 A 的首次响应推迟。
- RR：A 0～2 → B 2～4 → C 4～6 → A 6～8 → B 8～10 → A 10～12 → A 12～14。C 在第一次时间片内结束；B 再运行一片后结束；最后只有 A，仍可画出时间片边界，但 12 时刻不因此必然发生不同任务之间的切换。

逐任务计算如下；由于到达都为 0，首次运行时刻就是响应时间，完成时刻就是周转时间：

| 算法 | 任务 | 首次运行 | 完成 | CPU 时间 | 响应 | 周转 | 就绪等待 |
| ---- | ---- | -------: | ---: | -------: | ---: | ---: | -------: |
| FCFS | A    |        0 |    8 |        8 |    0 |    8 |        0 |
| FCFS | B    |        8 |   12 |        4 |    8 |   12 |        8 |
| FCFS | C    |       12 |   14 |        2 |   12 |   14 |       12 |
| SJF  | A    |        6 |   14 |        8 |    6 |   14 |        6 |
| SJF  | B    |        2 |    6 |        4 |    2 |    6 |        2 |
| SJF  | C    |        0 |    2 |        2 |    0 |    2 |        0 |
| RR   | A    |        0 |   14 |        8 |    0 |   14 |        6 |
| RR   | B    |        2 |   10 |        4 |    2 |   10 |        6 |
| RR   | C    |        4 |    6 |        2 |    4 |    6 |        4 |

例如 RR 的 A 在 2～6、8～10 就绪等待，共 6；其周转 14 减 CPU 时间 8 也得到 6。平均数分别将三项相加后除以 3，保留两位小数：

| 指标             |  FCFS |  SJF |    RR |
| ---------------- | ----: | ---: | ----: |
| 平均响应时间     |  6.67 | 2.67 |  2.00 |
| 平均周转时间     | 11.33 | 7.33 | 10.00 |
| 平均就绪等待时间 |  6.67 | 2.67 |  5.33 |

SJF 在这组同时到达、运行时间已知的任务中让短任务尽早结束，平均周转最低；RR 先轮流给每个任务机会，平均首次响应更好。FCFS 简单，但可能出现护航效应（Convoy Effect）：许多短工作被排在长工作后面。

现实中 SJF 需要估计未来工作量；持续有短任务到达时，长任务可能饥饿，本例的有限任务集合则都会完成。RR 时间片太短会增加调度和切换等开销；时间片很长、足以让任务一次完成时，在这种队列条件下趋近 FCFS。本例把这些开销设为 0，不能拿表中收益直接抵消真实切换成本。

是否抢占、到达时间和 I/O 行为都会改变结果。不能由 RR 的名称推出所有请求的硬实时响应界，也不能说 SJF 天然等于公平。

## 3. Linux 0.11 的 counter 与任务选择 {#_3-0-11-的-counter-怎样使用}

原版 [Linux 0.11 源码包](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)的 `kernel/sched.c:schedule()` 不是直接套用上面的三种算法。`counter` 是按时钟消耗的剩余预算计数，`priority` 参与补充预算；后者的数值越大，在该公式中补充越多，不要与其他系统的优先级编号方向混用。

`include/linux/sched.h` 定义 `NR_TASKS = 64`、`TASK_RUNNING = 0`。结合源码看完整选择链：

1. 先检查普通任务的 alarm、信号等条件，适用的可中断等待任务可转为 `TASK_RUNNING`。其他 I/O 唤醒路径也可能改变任务状态。
2. 每轮选择先设 `c = -1`、`next = 0`。从 `task[63]` 向 `task[1]` 扫描，跳过空槽，只比较 `state == TASK_RUNNING` 的 `counter`；用严格大于号更新最佳候选，因此相同计数时保留本轮先扫描到的候选。
3. 最大值 `c > 0` 时结束选择；若根本没有普通可运行任务，`c` 仍为 `-1`，也会结束选择，保留 `next = 0` 走特殊空闲任务。
4. **只有扫描得到的最大值为 0 时**，才对 `task[1]`～`task[63]` 中所有存在的任务重算 `counter = (counter >> 1) + priority`，然后再次扫描。这个更新不要求任务正处于 `TASK_RUNNING`，因此也会覆盖等待任务。
5. 调用 `switch_to(next)`。若目标就是当前任务，该宏可跳过实际任务切换；任务 0 没有参与上述普通任务的选择与预算重算。

这里 `if (c) break` 同时覆盖正数和 `-1`，不能误写成“只要没有可运行任务就立即重算”。任务 0 的特殊空闲行为与 TSS 切换详见[第六章](/articles/os-context-switching)。

[![Linux 0.11 普通任务扫描、预算重算与任务 0 分支](/assets/notes/operating-systems/os-schedule.svg)](/assets/notes/operating-systems/os-schedule.svg)

假设 A、B 可运行但预算耗尽，C 仍在等待，且本次信号检查未唤醒 C：

| 任务 | 状态         | 旧 counter | priority | 重算后的 counter |
| ---- | ------------ | ---------: | -------: | ---------------: |
| A    | TASK_RUNNING |          0 |        4 | (0 >> 1) + 4 = 4 |
| B    | TASK_RUNNING |          0 |        2 | (0 >> 1) + 2 = 2 |
| C    | 等待中       |          5 |        3 | (5 >> 1) + 3 = 5 |

首次扫描最大可运行预算为 0，因而重算。再次扫描选择 A 的 4；C 即使有 5，也因仍在等待而不能被这轮普通选择选中。更新预算不会代替唤醒；若 C 后续被唤醒，还需重新参与调度。

`counter` 带有剩余预算与历史调整的含义，不是每次 I/O 完成就直接执行固定加分。等待任务可在重算时保留部分旧预算，有助于解释某些交互倾向，但不保证其必然优先于所有 CPU 密集任务。

配合 `do_timer(long cpl)` 看三种路径：用户态被中断且 counter 耗尽时，该时钟末尾调用 schedule；内核态被中断且耗尽时，`if (!cpl) return` 使它不在该处直接调度；内核等待 I/O 时仍可沿 `sleep_on()` 等显式阻塞路径调度。这里 CPL（Current Privilege Level，当前特权级）来自被中断现场，不是 `do_timer` 自己在用户态执行。因此预算耗尽与实际更换任务不是在所有上下文中同一个瞬间。

## 4. 用伪代码理解选择与重新分配 {#_4-原笔记伪代码为什么不能直接编译}

下面用伪代码归纳“选择可运行任务”和“重新分配预算”两个环节。阅读实际 C 实现时，还需要跟踪数组指针的移动、空项检查、成员访问和循环边界；这些细节决定代码能否正确遍历任务。

```text
检查 alarm / 信号导致的适用唤醒
重复：
    最大值 c = -1，候选 next = 0
    从高编号向低编号扫描普通任务，跳过空槽和非 TASK_RUNNING
    只在 counter 严格大于 c 时更新 c 和 next
    若 c != 0：结束循环（c=-1 走任务 0，c>0 走普通候选）
    否则：对所有存在的普通任务重算 counter，再扫描
switch_to(next)
```

这是教学伪代码，不可当 C 程序编译；省略指针移动、具体信号判断及切换实现。真实实现定位到 `kernel/sched.c` 的 `schedule()`、`do_timer()` 和 `include/linux/sched.h` 的状态常量、`switch_to(n)`，不要把省略部分当作不存在。

## 5. 从历史调度器到现代 Linux {#_5-现代-linux-不再沿用这一个公式}

现代内核有多个调度类别、多核负载与资源控制。CFS（Completely Fair Scheduler，完全公平调度器）是 Linux 公平调度历史的重要机制，使用按权重折算的虚拟运行时间，直观上追踪任务已经得到多少 CPU 份额。它不是按静态 CPU Burst 排序的 SJF。[Linux 6.12 的 CFS 设计说明](https://docs.kernel.org/6.12/scheduler/sched-design-CFS.html)

Linux 6.6 开始引入 EEVDF（Earliest Eligible Virtual Deadline First，最早合格虚拟截止期优先）相关变化：先用获得服务的欠账等条件判断资格，再用虚拟截止期选择合格任务。这里的“截止期”是公平调度内部的虚拟量，不等于应用获得硬实时期限保证。[Linux 6.12 的 EEVDF 说明](https://docs.kernel.org/6.12/scheduler/sched-eevdf.html)

新机制关注 eligibility、虚拟截止期等条件，但本册不把滚动文档的每个实现细节反推为用户当前内核参数。研究性能先记录实际版本、调度策略、核数、亲和性和负载，再解释运行队列与等待。

## 6. 实验：模拟三个教学算法

下面是完整 Python 3.8 及以上版本程序，保存为 `schedule.py` 后运行 `python3 schedule.py`。它专门实现本章所有任务到达于 0 的固定模型，不是通用的任意到达/I/O 调度模拟器，也不修改宿主机的调度策略。`Fraction` 保留精确平均值，只在打印时四舍五入。

```python
from collections import deque
from fractions import Fraction

# All arrivals are zero; one CPU, no I/O and no switching overhead.
jobs = {"A": 8, "B": 4, "C": 2}
quantum = 2

def serial(order):
    now, intervals = 0, []
    for name in order:
        intervals.append((name, now, now + jobs[name]))
        now += jobs[name]
    return intervals

def round_robin():
    remaining = jobs.copy()
    ready = deque(jobs)
    now, intervals = 0, []
    while ready:
        name = ready.popleft()
        used = min(quantum, remaining[name])
        intervals.append((name, now, now + used))
        now += used
        remaining[name] -= used
        if remaining[name]:
            ready.append(name)
    return intervals

def metrics(intervals):
    first, finish = {}, {}
    for name, start, end in intervals:
        first.setdefault(name, start)
        finish[name] = end
    # Rows are (response, turnaround, ready waiting), since arrival == 0.
    rows = {n: (first[n], finish[n], finish[n] - jobs[n]) for n in jobs}
    means = tuple(Fraction(sum(row[i] for row in rows.values()), len(jobs))
                  for i in range(3))
    return rows, means

expected = {
    "FCFS": ((0, 8, 0), (8, 12, 8), (12, 14, 12)),
    "SJF": ((6, 14, 6), (2, 6, 2), (0, 2, 0)),
    "RR": ((0, 14, 6), (2, 10, 6), (4, 6, 4)),
}
algorithms = {
    "FCFS": serial(jobs),
    "SJF": serial(sorted(jobs, key=jobs.get)),
    "RR": round_robin(),
}
for algorithm, intervals in algorithms.items():
    rows, means = metrics(intervals)
    assert tuple(rows.values()) == expected[algorithm]
    assert intervals[0][1] == 0 and intervals[-1][2] == sum(jobs.values())
    assert all(left[2] == right[1] for left, right in zip(intervals, intervals[1:]))
    for name, burst in jobs.items():
        assert sum(end - start for n, start, end in intervals if n == name) == burst
    print(algorithm, intervals)
    print("A/B/C metrics:", rows)
    print("mean response/turnaround/waiting:",
          ", ".join(f"{float(value):.2f}" for value in means))
```

输出包含上文的执行区间、逐任务指标和三组平均值。断言检查每个任务的指标、CPU 工作量以及区间连续性；不要用 `python3 -O` 跳过断言。本轮已在 Ubuntu 22.04.5 / WSL2、x86-64、Python 3.10.12 下执行，所有断言通过，三组均值与表格一致。模拟结果不证明真实 Linux 采用同一调度次序，也没有运行 Linux 0.11 内核。

## 本章小结

- 先明确指标与负载条件，再比较算法；有 I/O 时不能直接把周转减 CPU 时间全部算成就绪等待。
- 同一组输入下，SJF 与 RR 在完成速度和首次响应方面表现不同，没有脱离条件的统一胜者。
- 0.11 区分 c=-1 的空闲路径与 c=0 的重算路径，预算更新不等于唤醒任务。

## 常见误区

时间片结束不必换到另一个任务；有预算的等待任务也不能直接运行。教学 RR、原版 0.11 和现代公平调度需要分别理解。

## 下一章衔接

任务可以交替运行后，共享统计值就可能被交错修改。[第八章](/articles/os-atomic-locks)继续解释怎样保护这些共享状态。

[返回本册目录](/collections/operating-systems/)
