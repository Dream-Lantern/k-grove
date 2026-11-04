---
id: os-memory-allocation
title: 第十四章 内存分配、碎片与分区算法
description: "内存分配需要从空闲空间中找到满足请求的区域。能否分配成功，既取决于剩余总量，也取决于连续性要求、空闲块的组织方式与合并策略。"
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
order: 14
---

# 第十四章 内存分配、碎片与分区算法

> 阅读标签：通用连续空闲区管理教学模型；不是现代 malloc 或内核分配器的完整实现。

上一章解释了地址属于哪个空间。现在程序调用 `malloc(20)`，要从哪里找出这一块空间？分配能否成功既取决于剩余总量，也取决于连续性要求、空闲块的组织方式与合并策略。本章先用合成单位观察布局，再区分应用对象、虚拟映射与物理内存管理。

## 1. 内部碎片与外部碎片

内部碎片是已分配单元中未被有效使用的部分。例如最小分配粒度 8 字节，请求 13，向上取整后占用 16，内部浪费 `16 − 13 = 3` 字节。这忽略了分配器元数据等额外开销，不是对真实 malloc 开销的测量。

外部碎片发生在空闲区域之间。设布局为 `空闲6 | 已占用2 | 空闲4 | 已占用2 | 空闲8`，空闲总量 `6+4+8=18`，但请求连续 10 单位仍失败，最大空闲块只有 8；中间的已占用区域不能忽略。

[![按大小比例绘制的内部浪费和不相邻空闲块](/assets/notes/operating-systems/os-fragmentation.svg)](/assets/notes/operating-systems/os-fragmentation.svg)

外部碎片与所管理空间的连续性要求有关。分页能缓解普通虚拟连续映射对**物理连续**的需求，但用户态分配器仍需管理虚拟连续对象，物理连续分配与大页也有额外约束。分页不消除所有碎片，固定大小页还可能有页内未使用空间。

## 2. First、Best 与 Worst fit 的选择规则 {#_2-first-fit-不天然是-o-1}

首次适应（First Fit）按固定扫描顺序选择第一个足够大的空闲块；最佳适应（Best Fit）选足够且最小的空闲块；最坏适应（Worst Fit）选最大的足够空闲块。名称说明的是选择规则，不是对长期效果的保证。[OSTEP Free-Space Management](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-freespace.pdf)

本章约定按地址从低到高扫描，每次从头开始；大小相同则选低地址块；从所选块的低地址端切出请求大小，余部仍为空闲。三种策略都使用同样的规则比较，不能中途改变扫描起点或平局处理。

算法成本取决于数据结构：线性空闲链表可能扫描多个候选，因此 First Fit 不天然是 O(1)；Best/Worst Fit 若线性搜索，也可能需要看完整表，若用大小索引或树结构则成本不同。分级索引、位图和维护元数据也有自身代价，不能只凭算法名字给出固定复杂度。

## 3. 一个可以手算的例子

以半开区间 `[起点, 终点)` 表示地址，完整空间 `[0,30)` 的初始布局是：

```text
[0,12) 空闲12 | [12,14) 固定占用2 | [14,19) 空闲5
              | [19,21) 固定占用2 | [21,30) 空闲9
```

空闲块按地址顺序为 `[12,5,9]`，固定占用区在整个实验中不释放。请求依次为 A=4、B=8、C=6，允许分割，暂不释放；忽略对齐、元数据与最小余块大小。

| 策略      | 请求 A=4 后的三个原空洞余量 | 请求 B=8 后             | 请求 C=6 后                  | 第四次 D=6           |
| --------- | --------------------------- | ----------------------- | ---------------------------- | -------------------- |
| First Fit | `[8,5,9]`，从 12 切出 4     | `[0,5,9]`，用完首洞余 8 | `[0,5,3]`，从 9 切出 6       | 失败，最大空洞 5     |
| Best Fit  | `[12,1,9]`，从 5 切出 4     | `[12,1,1]`，从 9 切出 8 | `[6,1,1]`，从 12 切出 6      | 成功，取第一个洞余 6 |
| Worst Fit | `[8,5,9]`，从 12 切出 4     | `[8,5,1]`，从 9 切出 8  | `[2,5,1]`，从首洞余 8 切出 6 | 失败，最大空洞 5     |

表中的 0 只是表示该原空洞已用完，不是仍保留一个零长块。三种策略前三次都分配了 18 单位，剩余均为 `26−18=8`，但剩余布局不同，决定了下一次连续 6 能否满足。本例 Best Fit 成功不说明它对所有负载都更优；许多小余块和搜索开销也需要考虑。

[![相同初始布局下三种适应算法的四次连续请求与剩余空洞](/assets/notes/operating-systems/os-fit-sequence.svg)](/assets/notes/operating-systems/os-fit-sequence.svg)

### 分割、释放与相邻合并

换一个独立例子：`[0,6) 空闲 | [6,10) 已分配 | [10,18) 空闲`。释放中间 4 后，三个区间在地址上首尾相接，且属于同一可合并管理区域，因此可合并为 `[0,18) 空闲18`。

合并的依据是**地址相邻且规则允许**，不是空闲链表中两个节点恰好挨在一起。前三次分配留下的空洞若仍隔着已分配块或固定占用区，就不能直接相加当作一个连续块。合并也不是搬移仍在使用的对象。

空闲结构至少要记录地址和大小；分割时移除原块、登记已分配区及非零余块；释放时验证分配身份、归还区间，并按规则寻找前后相邻空洞。边界标记（Boundary Tag）可在块边界记录大小与状态，帮助找到相邻块，但具体元数据布局取决于分配器。维护“不重叠、不丢失、总量守恒”才能避免重复分配或空间泄漏；真实 C 程序重复 free 属于未定义行为。

## 4. 应用分配器与内核物理分配不同

沿 `malloc(20)` 分开三个管理层次：

| 层次                 | 管理什么                           | 可能发生什么                                                     |
| -------------------- | ---------------------------------- | ---------------------------------------------------------------- |
| 用户态分配器         | 进程中的对象、空闲块及自己的元数据 | 从已有空间切出 20 字节适用对象，可能不执行系统调用               |
| 操作系统虚拟内存管理 | 虚拟地址范围、权限与后备映射       | 分配器空间不足时可能申请或扩展映射；新范围不等于所有物理页已到位 |
| 内核物理内存管理     | 页框等物理资源                     | 在需要时分配、复用或回收页框；不要求一个小对象独占一整页         |

[![malloc 对象、用户态空闲区、虚拟映射与内核页框管理的层次](/assets/notes/operating-systems/os-allocation-layers.svg)](/assets/notes/operating-systems/os-allocation-layers.svg)

箭头是管理关系，不是每次 malloc 都同步走完的调用链。`free()` 归还的是分配器层面的对象，空间可能先缓存复用，不保证马上缩小映射或降低物理占用。内核也有页级分配与小对象缓存等机制，但本章不展开其具体实现。[malloc(3)](https://man7.org/linux/man-pages/man3/malloc.3.html)

虚拟内存大小（VMS，Virtual Memory Size）反映虚拟空间规模；常驻集大小（RSS，Resident Set Size）反映当前驻留物理内存的适用统计。它们都不是应用有效对象字节数；共享页、元数据与统计口径也会影响解释。按需分配与 Linux 内存过量承诺策略影响实际获取物理页的时机，不能把 malloc 成功当作全部物理资源已经逐页保留。这里解释机制，不修改系统策略，也不以巨量分配验证内存耗尽。[Linux 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)、[Overcommit Accounting](https://docs.kernel.org/mm/overcommit-accounting.html)

## 5. 固定分区与可变分区 {#_5-固定分区不要求永远等分}

固定分区事先规定边界和大小，可以等大或不等大。假设总量 100，固定划成四个 25，每个请求只能占一个分区：

| 顺序 | 请求 | 固定分区模型             | 可变分区模型（初始连续 100）    |
| ---- | ---- | ------------------------ | ------------------------------- |
| 1    | 20   | 占一个 25，内部余 5      | 分配 `[0,20)`                   |
| 2    | 35   | 失败，没有单个分区足够大 | 分配 `[20,55)`                  |
| 3    | 15   | 占另一个 25，内部余 10   | 分配 `[55,70)`，剩余 `[70,100)` |

本表约定第二次失败后仍处理第三次请求。固定模型中即使空余总量足够，35 也不能跨分区拼接。可变分区可按需求安排边界，但后续释放和重复分配会带来外部碎片与管理成本。不能把“四个等分区”当成固定分区的唯一形式。

分页、分段、分配器及搬移压缩在不同层次缓解问题；搬移还需要解决引用更新等条件。讨论优化前先明确管理对象与连续性要求。

## 6. Python 空闲区模拟实验

保存为 `allocator.py`，运行 `python3 allocator.py`。只在 Python 中管理整数区间，不向主机申请对应大小的真实内存；所有区间使用半开边界，未覆盖范围是固定占用区。它用地址顺序列表实现三种策略，故查找成本不能代表生产级 malloc。

```python
class Arena:
    # Address intervals are [start, end); barriers are permanent allocations.
    def __init__(self, total, free):
        self.total = total
        self.free = sorted(free)
        self.used = {}
        self.check()

    def check(self):
        intervals = sorted(self.free + list(self.used.values()))
        assert all(0 <= start < end <= self.total for start, end in intervals)
        assert all(a[1] <= b[0] for a, b in zip(intervals, intervals[1:]))
        # This model treats uncovered space as fixed barriers.
        covered = sum(end - start for start, end in intervals)
        if hasattr(self, "capacity"):
            assert covered == self.capacity
        else:
            self.capacity = covered
        assert self.free == sorted(self.free)

    def allocate(self, name, size, policy):
        if size <= 0 or name in self.used or policy not in ("first", "best", "worst"):
            raise ValueError("invalid request")
        choices = [(i, end - start, start) for i, (start, end) in enumerate(self.free)
                   if end - start >= size]
        if not choices:
            return None             # Do not mutate state on failure.
        if policy == "first":
            index = choices[0][0]    # Increasing address order, restart each call.
        elif policy == "best":
            index = min(choices, key=lambda x: (x[1], x[2]))[0]
        else:
            index = min(choices, key=lambda x: (-x[1], x[2]))[0]
        start, end = self.free.pop(index)
        self.used[name] = (start, start + size)
        if start + size < end:
            self.free.append((start + size, end))
            self.free.sort()
        self.check()
        return start

    def release(self, name):
        if name not in self.used:
            raise ValueError("unknown or already released allocation")
        self.free.append(self.used.pop(name))
        merged = []
        for start, end in sorted(self.free):
            if merged and merged[-1][1] == start:
                merged[-1] = (merged[-1][0], end)
            else:
                merged.append((start, end))
        self.free = merged
        self.check()

    def holes(self):
        return [(start, end - start) for start, end in self.free]


if __name__ == "__main__":
    expected = {"first": [(14, 5), (27, 3)],
                "best": [(6, 6), (18, 1), (29, 1)],
                "worst": [(10, 2), (14, 5), (29, 1)]}
    for policy in expected:
        arena = Arena(30, [(0, 12), (14, 19), (21, 30)])
        for name, size in [("A", 4), ("B", 8), ("C", 6)]:
            assert arena.allocate(name, size, policy) is not None
            print(policy, name, arena.holes())
        assert arena.holes() == expected[policy]
        before = (list(arena.free), dict(arena.used))
        fourth = arena.allocate("D", 6, policy)
        assert (fourth is not None) == (policy == "best")
        if fourth is None:
            assert (arena.free, arena.used) == before
        print(policy, "fourth 6:", "success" if fourth is not None else "failed")
        for name in list(arena.used):
            arena.release(name)
        assert arena.free == [(0, 12), (14, 19), (21, 30)]

    arena = Arena(18, [(0, 18)])
    assert arena.allocate("left", 6, "first") == 0
    assert arena.allocate("middle", 4, "first") == 6
    assert arena.allocate("right", 8, "first") == 10
    arena.release("left")
    arena.release("right")
    assert arena.free == [(0, 6), (10, 18)]
    arena.release("middle")
    assert arena.holes() == [(0, 18)]
    before = (list(arena.free), dict(arena.used))
    try:
        arena.release("middle")
    except ValueError:
        pass
    else:
        raise AssertionError("double release accepted")
    assert (arena.free, arena.used) == before
    print("overlap / conservation / failure / release / coalescing: PASS")
```

程序逐次打印 `(空洞起点, 大小)`。本轮实测前三次之后，First 为 `[(14,5),(27,3)]`，Best 为 `[(6,6),(18,1),(29,1)]`，Worst 为 `[(10,2),(14,5),(29,1)]`；第四次仅 Best 成功。释放所有模拟对象后恢复三个原空洞；独立的 6|4|8 例子释放后合并为 `[0,18)`。不重叠、空间守恒、失败不改变状态及重复释放拒绝断言通过。输入断言是教学约束，不是生产 API 的完整校验。

## 本章小结与联读

总空闲量不能代替连续布局；选择、分割、释放和合并共同决定复用效果。对象分配、虚拟映射与物理页框管理各有职责。下一章用[分页与页表](/articles/os-paging-page-tables.html)解释虚拟连续如何映射到不连续物理页框，地址语境可回看[第十三章](/articles/os-address-spaces-segmentation.html)。

[返回本册目录](/collections/operating-systems/)
