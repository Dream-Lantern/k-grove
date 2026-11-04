---
id: os-deadlocks
title: 第十章 死锁条件、避免与恢复
description: "死锁是相关活动相互等待、无法自行继续的状态；饥饿指某个活动长期得不到执行机会；活锁则表现为持续动作，却没有有效进展。三者现象可能相似，但处理方式不同。"
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
order: 10
---

# 第十章 死锁条件、避免与恢复

> 阅读标签：通用死锁模型与教学算法；不在真实主机制造死锁。

上一章讨论了如何等待条件。如果等待的条件只能由另一个也在等待的任务改变，系统还能前进吗？死锁是相关活动相互等待、无法自行继续的状态；饥饿指某个活动长期得不到执行机会；活锁则表现为持续动作，却没有有效进展。三者现象可能相似，但处理方式不同。

## 1. 四个经典必要条件

先限定模型：线程 A、B 竞争独占互斥锁 L1、L2，每把锁只有一个实例，持有者正常执行到解锁处才释放；不存在安全强夺所有权或自动撤销工作的机制。

| 时刻 | 线程 A               | 线程 B               |
| ---- | -------------------- | -------------------- |
| T1   | 获得 L1              | 未持锁               |
| T2   | 持有 L1              | 获得 L2              |
| T3   | 请求 L2，等待 B 释放 | 持有 L2              |
| T4   | 持有 L1、等待 L2     | 请求 L1，等待 A 释放 |
| T5   | 到不了后续解锁代码   | 到不了后续解锁代码   |

这里对应四个经典必要条件：互斥（Mutual Exclusion），同一把锁不能同时分给两者；占有并等待（Hold and Wait），拿着一把继续等另一把；不可抢占（No Preemption），不能任意夺走锁而保证数据一致；循环等待（Circular Wait），A 等 B，B 又等 A。“不可抢占”说的是资源所有权，不是 CPU 不能切换任务。

[![死锁：资源分配图与循环等待](/assets/notes/operating-systems/os-deadlock.svg)](/assets/notes/operating-systems/os-deadlock.svg)

图是教学抽象：任务节点与资源节点交替出现，任务 → 资源表示请求，资源 → 任务表示分配。沿 A → L2 → B → L1 → A 得到完整环。在上述模型下，没有外部恢复，两者都不能推进。四条件针对这类资源分配死锁；不能把条件变量丢失通知、任意通信协议等待都不加分析地套进此图。[OSTEP：并发问题](https://pages.cs.wisc.edu/~remzi/OSTEP/threads-bugs.pdf)

### 三种“不前进”有什么不同

| 类型               | 简短时间线                              | 是否仍有操作         | 有效进展                 |
| ------------------ | --------------------------------------- | -------------------- | ------------------------ |
| 死锁（Deadlock）   | A 等 B 放 L2 → B 等 A 放 L1 → 双方停住  | 相关任务可能全部阻塞 | 相关工作不能自行继续     |
| 饥饿（Starvation） | C 等锁 → D 抢先 → E 抢先 → C 继续等     | 其他任务持续执行     | 系统有进展，C 长期无进展 |
| 活锁（Livelock）   | A、B 同时退让 → 同时重试冲突 → 再次退让 | 双方持续改变状态     | 双方始终没完成工作       |

活锁例子假定双方一直同步重试；随机退避可降低这种风险，但不能当作任意协议的进展证明。排查时要看具体任务、持有与请求关系，不能只看 CPU 利用率。

## 2. 预防：事先破坏条件

| 方法               | 作用阶段           | 依据与动作                         |
| ------------------ | ------------------ | ---------------------------------- |
| 预防（Prevention） | 设计资源使用规则时 | 破坏必要条件，如统一加锁顺序       |
| 避免（Avoidance）  | 每次分配之前       | 根据最大需求，试算分配后是否仍安全 |
| 检测（Detection）  | 系统运行中         | 根据当前请求与持有关系识别死锁     |
| 恢复（Recovery）   | 确认死锁之后       | 在一致性协议支持下中止、回滚或重启 |

统一锁顺序是容易落实的预防方式：

| 方案     | A 的获取顺序 | B 的获取顺序 | 可能结果                           |
| -------- | ------------ | ------------ | ---------------------------------- |
| 逆序     | L1 → L2      | L2 → L1      | 可形成上一节的等待环               |
| 统一顺序 | L1 → L2      | L1 → L2      | B 若等 L1，就尚未持有 L2，A 可继续 |

只要所有路径严格按同一个全局次序获取这组不同的锁，等待就只能指向更高次序的锁，无法回到较低次序而成环。这保证的是对应锁集合不产生逆序等待环，不能保证整个程序没有其他死锁。回调、异常处理和库内部隐藏锁也必须纳入检查；同一非递归锁的重复获取另需处理。

一次申请全部资源可破坏“占有并等待”，但可能降低并发与利用率。不是所有资源都能安全抢占；超时也不会自动撤销已经写到一半的数据。[互斥与锁的联读](/articles/os-atomic-locks.html)

## 3. 避免：分配前检查安全序列 {#_3-避免-安全状态不是已发生死锁}

银行家算法（Banker's Algorithm）在已知最大需求、资源数量固定、同类实例可互换、任务能在满足需求后有限时间完成并归还资源等假设下，检查分配后是否仍有安全安排。它不是现代 Linux 对所有锁使用的通用算法。原始论证可读 [Dijkstra 的 EWD623](https://www.cs.utexas.edu/~EWD/transcriptions/EWD06xx/EWD623.html)；下面将单类资源的思路教学性扩展为二维向量，比较必须逐分量进行。

Available 是当前未分配资源；Allocation 是各任务已持有量；Max 是预先声明的最大同时需求；Need = Max − Allocation 是剩余最大需求。本例 R1、R2 总量各为 3：

| 进程 | Allocation | Max   | Need  |
| ---- | ---------- | ----- | ----- |
| P1   | (1,0)      | (2,1) | (1,1) |
| P2   | (1,1)      | (2,2) | (1,1) |
| P3   | (0,1)      | (1,2) | (1,1) |

Available = (1,1)，已分配总量为 (2,2)，相加为 (3,3)，资源守恒。安全性检查使用副本 Work = Available，不实际运行或释放进程：

| 步骤 | 选择条件                | 假设完成后更新 Work                  |
| ---- | ----------------------- | ------------------------------------ |
| 初始 | Work = (1,1)            | 尚未选择任务                         |
| P1   | Need (1,1) ≤ Work (1,1) | (1,1) + Allocation[P1] (1,0) = (2,1) |
| P2   | Need (1,1) ≤ Work (2,1) | (2,1) + (1,1) = (3,2)                |
| P3   | Need (1,1) ≤ Work (3,2) | (3,2) + (0,1) = (3,3)                |

[![银行家安全性检查的 Work 向量变化](/assets/notes/operating-systems/os-banker-safety.svg)](/assets/notes/operating-systems/os-banker-safety.svg)

为什么加 Allocation，而不是 Max？假设先借出 Need，完成后再归还全部 Max，净变化为 −Need + Max = 原 Allocation。Work 是模拟量，不要把每一步写成真实 Available 已变化。

安全序列 P1 → P2 → P3 证明在模型中存在可完成的安排，不代表中央处理器（CPU，Central Processing Unit）必须按此顺序调度，也不代表只有这一个序列。不安全则是无法在最大需求假设下给出保证，**不等于此刻已经死锁**；任务若不再申请最大需求，仍可能完成。

### 一次批准，再一次暂缓

对请求 Request 依次检查：是否非负且不超过该进程 Need；是否不超过 Available；试分配后能否通过安全性检查。超过 Need 是模型外的无效请求，Available 不足则暂等；只有试算安全才提交新状态，否则撤销试算。

| 请求                             | 检查与试算                                                                                                       | 决策                                           |
| -------------------------------- | ---------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| 初始状态下 P1 请求 (1,0)         | 在 Need 和 Available 内；试后 Available=(0,1)，P1 Need=(0,1)，仍可先完成 P1                                      | 批准；P1 Allocation=(2,0)                      |
| 在上述已批准状态下 P2 请求 (0,1) | 也未超过 Need 或 Available；试后 Available=(0,0)，三者 Need 分别为 (0,1)、(1,0)、(1,1)，谁都不能按最大需求先完成 | 暂缓；恢复试算前 Available=(0,1) 及 Allocation |

第二行不是重新从初始状态试算。此时“不安全”依然是对未来最大需求的判定，不是检测到所有进程已经发出了那些请求。

### 安全的纯 Python 实验

保存为 `banker.py`，运行 `python3 banker.py`。程序仅模拟整数向量，不创建线程、不锁定系统资源；输入断言用于教学检查，不作为生产 API 的完整参数校验。

```python
def safety(available, allocation, maximum):
    # Inputs: nonnegative integer matrices, Allocation <= Max.
    n, m = len(allocation), len(available)
    assert len(maximum) == n and m > 0
    assert all(len(a) == len(b) == m for a, b in zip(allocation, maximum))
    assert all(isinstance(x, int) and x >= 0 for x in available)
    assert all(isinstance(a, int) and isinstance(b, int) and 0 <= a <= b
               for row, cap in zip(allocation, maximum)
               for a, b in zip(row, cap))
    need = [[b - a for a, b in zip(row, cap)]
            for row, cap in zip(allocation, maximum)]
    work, finished, sequence = list(available), set(), []
    while len(finished) < n:
        for i in range(n):
            if i not in finished and all(need[i][j] <= work[j] for j in range(m)):
                work = [work[j] + allocation[i][j] for j in range(m)]
                finished.add(i)
                sequence.append(i)
                break
        else:
            return False, sequence
    return True, sequence


def request(available, allocation, maximum, i, amount):
    # Return a new state only on success; never mutate the caller's state.
    assert 0 <= i < len(allocation) and len(amount) == len(available)
    need = [b - a for a, b in zip(allocation[i], maximum[i])]
    if any(not isinstance(x, int) or x < 0 or x > need[j]
           for j, x in enumerate(amount)):
        return "invalid", None
    if any(x > available[j] for j, x in enumerate(amount)):
        return "wait-available", None
    new_available = [a - x for a, x in zip(available, amount)]
    new_allocation = [list(row) for row in allocation]
    new_allocation[i] = [a + x for a, x in zip(allocation[i], amount)]
    safe, _ = safety(new_available, new_allocation, maximum)
    return ("granted", (new_available, new_allocation)) if safe else ("wait-unsafe", None)


available = [1, 1]
allocation = [[1, 0], [1, 1], [0, 1]]
maximum = [[2, 1], [2, 2], [1, 2]]
assert [available[j] + sum(row[j] for row in allocation) for j in range(2)] == [3, 3]
assert safety(available, allocation, maximum) == (True, [0, 1, 2])
status, state = request(available, allocation, maximum, 0, [1, 0])
assert status == "granted"
v, a = state
assert v == [0, 1] and a[0] == [2, 0]
assert request(v, a, maximum, 1, [0, 1]) == ("wait-unsafe", None)
assert not safety([0, 0], [[2, 0], [1, 2], [0, 1]], maximum)[0]
assert request(available, allocation, maximum, 0, [2, 0])[0] == "invalid"
assert request(v, a, maximum, 1, [1, 0])[0] == "wait-available"
assert available == [1, 1] and allocation == [[1, 0], [1, 1], [0, 1]]
print("safe sequence:", " -> ".join("P" + str(i + 1) for i in safety(available, allocation, maximum)[1]))
print("request checks: granted / wait-unsafe / invalid / wait-available: PASS")
```

本轮已运行上述断言；输出为 `safe sequence: P1 -> P2 -> P3`，四类请求检查 PASS。不安全用例只是资源矩阵，不会在宿主机制造死锁。

## 4. 检测：分析当前持有与请求关系 {#_4-检测与避免不是同一个算法调用}

资源分配图同时画任务与资源；等待图则把“任务等某资源，而该资源由另一任务持有”折叠成任务之间的边。对于每种资源都只有一个实例、等待必须获准相应请求才能继续且无外部解除的模型，等待图中的环表明死锁。

多实例反例：R1 有两个实例，R2 有一个。A 持有一个 R1、请求 R2；B 持有 R2、请求一个 R1；C 持有另一个 R1，不再请求资源且可以完成。虽然资源类型图上有 A → R2 → B → R1 → A，C 完成释放 R1 后，B 可以取得它、完成并归还 R2，随后 A 也能完成。因此只看资源类型之间的环会误判。

多实例检测要结合数量与**当前请求**：模拟能满足当前请求的任务完成、归还其已分配量，再看是否仍有不能消除的持有者。银行家安全性检查用的是**剩余最大需求**，目标是分配前避免风险，二者不能当成同一个算法调用。普通输入/输出（I/O，Input/Output）等待可能由设备完成而解除；低利用率、空闲或单个任务阻塞都不能直接证明死锁。[条件等待联读](/articles/os-semaphores-conditions.html)

## 5. 恢复：中止、回滚与受控重启 {#_5-恢复不能任意删除锁}

例如 A 已预留库存却还没写完订单，B 也持有业务资源，随后二者逆序等锁。直接把互斥锁内部字段改为“空闲”，会让其他任务读到半成品。恢复必须先确定哪段工作可以撤销：数据库可能中止事务并按日志回滚；普通线程没有自动回滚能力，可能只能协作取消并清理，或停止相关服务、依据日志恢复一致状态后受控重启。强行结束线程本身不保证业务安全。

选择受害者要考虑已做工作、恢复成本、优先级、资源影响与反复被选的饥饿风险；无法撤销的外部操作需要补偿或人工恢复。操作系统任务、数据库事务与分布式作业各有恢复协议，本章不展开完整事务实现。

## 本章小结与联读

从“谁持有什么、正在等什么”识别死锁；预防改变规则，避免检查未来上界，检测分析当前等待，恢复负责一致性。下一章以[设备 I/O 等待](/articles/os-buffer-io.html)说明可由外部完成事件解除的正常阻塞。

[返回本册目录](/collections/operating-systems/)
