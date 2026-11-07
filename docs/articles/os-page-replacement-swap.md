---
id: os-page-replacement-swap
title: 第十九章 页面置换、工作集、swap 与颠簸
description: "虚拟内存提供地址抽象、保护与受控共享。物理内存压力增大时，系统通过回收和置换为新请求腾出空间。页面的后备来源、脏状态与引用条件决定其回收方式，下面先按页面类型区分去向，再比较置换策略。"
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
order: 19
---

# 第十九章 页面置换、工作集、swap 与颠簸

> 阅读标签：经典页面置换教学模型；现代 Linux 回收按页面类型、内核版本和配置另行限定。

服务的活跃数据增长后，物理内存不一定够放下所有页面。页面回收（Page Reclaim）的目标是在可回收条件满足时释放或重新利用物理内存，满足新需求。虚拟内存仍负责地址抽象、保护和受控共享；回收不是“把所有页面写到 swap”。

## 1. 不同页有不同去向

| 页面来源及状态         | 典型处理与限制                                                                      |
| ---------------------- | ----------------------------------------------------------------------------------- |
| 干净文件后备页         | 数据可从文件重新获取，满足引用、映射等条件时可回收；不需要把已有文件内容另存到 swap |
| 脏文件后备页           | 修改不能直接丢弃，通常先完成适用写回；正在写回或暂时不能回收时还需等待/跳过         |
| 私有匿名页             | 私有内容不能像干净文件内容一样重读；可能借助 swap 等后备机制，也可能暂时保留        |
| 共享内存、tmpfs 页     | 按具体共享、后备与配置处理；tmpfs 并不意味着永远不能交换                            |
| 锁定、固定或设备特殊页 | 锁定、引用、固定和特殊映射可能限制回收，不能强行按普通文件缓存处理                  |

[![依据文件、匿名或特殊来源及脏状态选择回收、写回或暂不回收](/assets/notes/operating-systems/os-reclaim.svg)](/assets/notes/operating-systems/os-reclaim.svg)

交换空间（swap）可以有不同后备和压缩实现，不能断言每个匿名页都一定写入物理磁盘。没有 swap 仍有虚拟内存，但可回收选择和分配失败风险不同。干净也不是唯一条件：还要处理有效使用关系、映射、锁定和正在进行的操作。[Linux 6.6 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)

## 2. FIFO、OPT 与 LRU 的选择依据 {#_2-fifo、opt、lru-分别看什么}

- 先进先出（FIFO，First-In, First-Out）：淘汰最早装入者，命中不改变进入顺序。
- 最近最少使用（LRU，Least Recently Used）：看最近过去的使用，命中也更新使用历史。
- 最优页面置换（OPT/MIN，Optimal Page Replacement）：淘汰下一次使用最远、或未来不再使用者；依赖未来信息，只作理论最优对照。

精确 LRU 可在某些受控缓存维护，不是理论上不可实现；对全部处理器访存逐次维护全局精确顺序成本高，实际内核采用近似或其他策略。[OSTEP 页面策略](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-beyondphys-policy.pdf)

### 同一个输入，完整观察每次决策

统一访问序列为 `1,2,3,4,1,2,5,1,2,3,4,5`。初始为空，分别给 3、4 个页框；每次缺页装入目标页，全部页可淘汰，无预载，不计脏写回、共享、预读和其他开销。页框槽位从左到右编号；先填最低空槽，OPT 同样远时选低槽位。**槽位顺序不是 FIFO 队列顺序**。

FIFO、3 页框的全部步骤如下：

| 步骤 | 访问页 | 结果 | 淘汰页 | 当前槽位 | 累计缺页 |
| ---- | ------ | ---- | ------ | -------- | -------- |
| 1    | 1      | 缺页 | —      | 1,—,—    | 1        |
| 2    | 2      | 缺页 | —      | 1,2,—    | 2        |
| 3    | 3      | 缺页 | —      | 1,2,3    | 3        |
| 4    | 4      | 缺页 | 1      | 4,2,3    | 4        |
| 5    | 1      | 缺页 | 2      | 4,1,3    | 5        |
| 6    | 2      | 缺页 | 3      | 4,1,2    | 6        |
| 7    | 5      | 缺页 | 4      | 5,1,2    | 7        |
| 8    | 1      | 命中 | —      | 5,1,2    | 7        |
| 9    | 2      | 命中 | —      | 5,1,2    | 7        |
| 10   | 3      | 缺页 | 1      | 5,3,2    | 8        |
| 11   | 4      | 缺页 | 2      | 5,3,4    | 9        |
| 12   | 5      | 命中 | —      | 5,3,4    | 9        |

[![FIFO、LRU、OPT 在 3 和 4 页框下的十二次访问、命中、淘汰和累计缺页](/assets/notes/operating-systems/os-replacement-trace.svg)](/assets/notes/operating-systems/os-replacement-trace.svg)

图中完整列出六组过程，末尾实验输出每步的相同字段。独立运行得到：

| 算法 | 3 页框 | 4 页框 |
| ---- | ------ | ------ |
| FIFO | 9      | 10     |
| LRU  | 10     | 8      |
| OPT  | 7      | 6      |

例如 FIFO 的第 8、9 步命中 1、2，却不会把它们变成“最新装入”；第 10 步仍按进入时间淘汰 1。LRU 则会改变最近使用关系；OPT 需要向后看完整剩余序列。

### Belady 异常

Belady 异常（Belady's Anomaly）指某些策略中增加页框反而增加缺页。本例 FIFO 从 3 页框的 9 次变成 4 页框的 10 次；LRU 和 OPT 的对照值均下降。不能把这组教学结果推导为“现代 Linux 增加物理内存普遍会变慢”。这些计数只在上述固定模型内成立，不是当前内核的回收次数。

## 3. Clock 的第二次机会

时钟置换（Clock）把候选排成环，访问位 R 记录自上次清位以来是否被访问。这里定义命中置 R=1、不移动指针；缺页时从指针扫描，R=1 就清零继续，R=0 或空槽可用；装入页的 R=1，指针移到下一槽。

初始 A/B/C 的 R 分别为 1/1/0，指针在 A，要装入 D：

| 扫描动作           | A   | B   | 第三槽   | 指针/结果 |
| ------------------ | --- | --- | -------- | --------- |
| 初始               | A,1 | B,1 | C,0      | A         |
| 看 A，给第二次机会 | A,0 | B,1 | C,0      | B         |
| 看 B，给第二次机会 | A,0 | B,0 | C,0      | C         |
| 看 C，R=0          | A,0 | B,0 | C 被淘汰 | 选第三槽  |
| 装入 D             | A,0 | B,0 | D,1      | 下一槽 A  |

[![Clock 环形扫描中 A/B 清访问位、C 淘汰、D 装入及指针回到 A](/assets/notes/operating-systems/os-clock.svg)](/assets/notes/operating-systems/os-clock.svg)

R 位提供近期访问线索，而非精确的全局最近使用排序，所以是近似。真实实现还要考虑脏、锁定、引用与其他约束，清位/扫描时机也影响结果；图不代表现代 Linux 唯一算法。

多代最近最少使用（Multi-Gen LRU，Multi-Generational Least Recently Used）按访问新近程度等信息组织代际回收。支持和启用取决于内核版本、构建及运行配置，不能把经典 Clock 或精确 LRU 直接当作当代完整实现；本轮不改开关。[Linux 6.6 Multi-Gen LRU](https://docs.kernel.org/6.6/admin-guide/mm/multigen_lru.html)

## 4. 工作集与颠簸

工作集（Working Set）是某个时间窗口内活跃使用的页面集合，窗口和访问局部性都影响它。页面颠簸（Thrashing）指大量精力消耗在反复调入/回收，业务有效进展下降。

以 FIFO、无其他干扰、连续三轮 `A→B→C→D` 为例：

| 驻留预算 | 首轮            | 后两轮                                     | 三轮累计缺页 |
| -------- | --------------- | ------------------------------------------ | ------------ |
| 4 页框   | 装入 A/B/C/D    | 都可命中                                   | 4            |
| 3 页框   | 装入 D 时淘汰 A | 下一次 A 淘汰 B，再访问 B 又缺；可持续循环 | 12           |

若被淘汰数据必须从慢后备重新取得，就可能出现频繁加载、等待增加与吞吐下降。继续增加并发可能让各任务可用驻留预算更紧。工作集超过预算只是风险条件，不保证所有负载发生相同程度的颠簸；访问模式、回收策略、存储与页面状态都会改变结果。

## 5. OOM 与 swap 调参的边界

内存压力下，系统先按适用规则寻找可回收对象，可能回收文件缓存、写回脏页或交换匿名页；仍不能满足分配时，可能拒绝分配或进入内存不足（OOM，Out of Memory）处理。并非每次内存紧张都一定杀任务，具体还受分配要求和上下文影响。

控制组（cgroup，control group）/容器的内存上限可以先于全机资源耗尽而触发局部 OOM。虚拟内存大小（VMS，Virtual Memory Size）、常驻集大小（RSS，Resident Set Size）、组内计费与实际可回收空间各有口径，不能把 RSS 与已包含的文件缓存直接相加。[cgroup v2 内存控制](https://docs.kernel.org/admin-guide/cgroup-v2.html)

已使用 swap 只说明仍有交换内容，不证明此刻正在剧烈换入换出；应观察同一时间窗的活动与压力。不能因系统卡顿就清缓存、关闭 swap、调内核参数或结束任务。本章只运行整数模拟，不在主机上制造内存压力。

## 6. Python 页面置换模拟

保存为 `replacement.py`，运行 `python3 replacement.py`。输出每步 `(步骤, 页面, H/F, 淘汰页, 槽位, 累计缺页)`；Clock 另输出 R 位、下一指针与扫描动作。H 表示命中，F 表示本模型缺页，None 表示空槽/无淘汰。

```python
REFS = [1, 2, 3, 4, 1, 2, 5, 1, 2, 3, 4, 5]


def simulate(policy, capacity, refs):
    assert policy in ("FIFO", "LRU", "OPT") and capacity > 0
    frames = [None] * capacity
    entered, used = [-1] * capacity, [-1] * capacity
    faults, rows = 0, []
    for time, page in enumerate(refs):
        hit, victim = page in frames, None
        if hit:
            slot = frames.index(page)
        else:
            faults += 1
            if None in frames:
                slot = frames.index(None)
            elif policy == "FIFO":
                slot = min(range(capacity), key=lambda j: (entered[j], j))
            elif policy == "LRU":
                slot = min(range(capacity), key=lambda j: (used[j], j))
            else:
                def next_use(j):
                    try:
                        return refs.index(frames[j], time + 1)
                    except ValueError:
                        return float("inf")
                # Same future distance: evict the lower-numbered frame slot.
                slot = min(range(capacity), key=lambda j: (-next_use(j), j))
            victim = frames[slot]
            frames[slot], entered[slot] = page, time
        used[slot] = time
        resident = [p for p in frames if p is not None]
        assert len(resident) <= capacity and len(set(resident)) == len(resident)
        rows.append((time + 1, page, "H" if hit else "F", victim, tuple(frames), faults))
    return rows


def clock(frames, bits, hand, refs):
    frames, bits = list(frames), list(bits)
    assert len(frames) == len(bits) > 0 and 0 <= hand < len(frames)
    faults, rows = 0, []
    for page in refs:
        scans, victim = [], None
        if page in frames:
            bits[frames.index(page)] = 1   # Hit does not advance the hand.
            outcome = "H"
        else:
            faults += 1
            outcome = "F"
            while frames[hand] is not None and bits[hand] == 1:
                scans.append((hand, frames[hand], "clear R"))
                bits[hand] = 0
                hand = (hand + 1) % len(frames)
            victim = frames[hand]
            scans.append((hand, victim, "replace"))
            frames[hand], bits[hand] = page, 1
            hand = (hand + 1) % len(frames)
        resident = [p for p in frames if p is not None]
        assert len(set(resident)) == len(resident)
        rows.append((page, outcome, victim, tuple(frames), tuple(bits), hand, faults, scans))
    return rows


if __name__ == "__main__":
    totals = {}
    print("references:", REFS)
    for policy in ("FIFO", "LRU", "OPT"):
        for capacity in (3, 4):
            rows = simulate(policy, capacity, REFS)
            for row in rows:
                print(policy, capacity, row)
            totals[(policy, capacity)] = rows[-1][-1]
    assert totals == {("FIFO", 3): 9, ("FIFO", 4): 10,
                      ("LRU", 3): 10, ("LRU", 4): 8,
                      ("OPT", 3): 7, ("OPT", 4): 6}
    assert totals[("FIFO", 4)] > totals[("FIFO", 3)]
    demo = clock(["A", "B", "C"], [1, 1, 0], 0, ["D"])[0]
    assert demo[2:6] == ("C", ("A", "B", "D"), (0, 0, 1), 0)
    assert demo[-1] == [(0, "A", "clear R"), (1, "B", "clear R"), (2, "C", "replace")]
    print("Clock A/B/C -> D:", demo)
    for row in clock([None] * 3, [0] * 3, 0, REFS):
        print("Clock 3", row)
    assert simulate("FIFO", 4, list("ABCD") * 3)[-1][-1] == 4
    assert simulate("FIFO", 3, list("ABCD") * 3)[-1][-1] == 12
    print("totals / Belady / capacity / unique pages / Clock / working set: PASS")
```

本轮全部断言通过：六组总数、FIFO 异常、容量/无重复驻留、Clock 初始例和工作集两例均已实际运行。代码只管理逻辑页编号，不模拟真实物理分配、写回或现代内核回收；这些 F 也不是宿主机的实际缺页日志。

## 本章小结与联读

先看页的后备、脏状态和可回收条件，再讨论选择策略；总量、访问局部性和资源限制共同决定风险。接着看[第二十章文件映射与页缓存](/articles/os-mmap-page-cache.html)，再用[第二十一章分层排查](/articles/os-troubleshooting.html)关联压力与请求延迟。[缺页统计回顾](/articles/os-page-faults.html)

[返回本册目录](/collections/operating-systems/)
