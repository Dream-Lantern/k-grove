---
id: os-tlb
title: 第十六章 TLB、地址空间标识与失效
description: "TLB 缓存地址翻译及相关属性，而非文件内容或普通数据。它可避免每次内存访问都完整遍历页表，但命中、未命中、权限异常和缺页仍需分别理解。"
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
order: 16
---

# 第十六章 TLB、地址空间标识与失效

> 阅读标签：翻译缓存的一般原理、x86 硬件案例与现代 Linux 失效接口；数值模型不代表硬件实测。

上一章已经从页目录和页表算出物理地址。程序反复读取一个变量，难道每次都得把页表再查一遍？翻译后备缓冲（TLB，Translation Lookaside Buffer）缓存地址翻译及相关属性，可省去适用的完整遍历。它不是保存文件内容或普通数据的数据缓存。

## 1. TLB 命中与页表遍历

延续 32 位非物理地址扩展（PAE，Physical Address Extension）、两级分页、4 KiB 页的案例：虚拟地址 `0x2240`，虚拟页号 2，偏移 `0x240`，映射到物理页框号（PFN，Page Frame Number）7。假设映射有效、权限满足，且两次访问间翻译没有被淘汰或失效。遍历对象是页目录项（PDE，Page Directory Entry）与页表项（PTE，Page Table Entry）。

| 阶段       | 第一次：未命中（TLB Miss）                                             | 第二次：命中（TLB Hit）                    |
| ---------- | ---------------------------------------------------------------------- | ------------------------------------------ |
| 查询       | 中央处理器（CPU，Central Processing Unit）未找到当前地址空间的适用翻译 | 找到该页的适用缓存翻译                     |
| 翻译与检查 | 在本 x86 模型中遍历 PDE[0]、PTE[2]，取得页框 7，检查存在性及权限       | 使用缓存的页框和权限属性，仍须允许本次访问 |
| 缓存       | 在适用条件下填入翻译                                                   | 不必重新完整遍历页表                       |
| 数据访问   | `7×4096+0x240=0x7240`                                                  | 同样访问 `0x7240`                          |

[![TLB 命中和未命中分别检查翻译与权限，失败才走异常](/assets/notes/operating-systems/os-tlb.svg)](/assets/notes/operating-systems/os-tlb.svg)

TLB Miss 不等于页故障（Page Fault，常称缺页异常），更不等于读取磁盘。有效页表可以直接提供翻译；TLB Hit 若缓存的权限不允许访问，也可触发保护异常。其他架构可能使用软件管理的翻译缓存，不能把 x86 硬件遍历说成所有 CPU 的唯一机制。

图和表是简化路径。真实处理器可能有多级 TLB、页表遍历缓存、数据缓存和重叠执行，不能逐框当成固定串行时钟序列。[Intel 软件开发手册 Volume 3A，Caching Translation Information](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)

## 2. 简化有效访问时间公式

设 TLB 查询时间 t=1 ns，一次内存访问 m=100 ns，页表层数 n=2，命中率 h。有效访问时间（EAT，Effective Access Time）使用以下**纸面假设**：串行计算、无数据/页表缓存效果、无预取和重叠、不发生页故障，所有 Miss 都能通过有效页表完成。

```text
T_hit  = t + m = 101 ns
T_miss = t + (n+1)×m = 301 ns
EAT    = h×T_hit + (1-h)×T_miss
```

Miss 的 n 次页表访问之外还有一次数据访问，所以是 n+1。独立计算得到：

| 命中率 h | 代入                  | EAT    |
| -------- | --------------------- | ------ |
| 90%      | `0.90×101 + 0.10×301` | 121 ns |
| 95%      | `0.95×101 + 0.05×301` | 111 ns |
| 99%      | `0.99×101 + 0.01×301` | 103 ns |

提高 h 减少昂贵路径的权重。现实中的缓存命中、遍历层级、并行访问与执行流水线改变成本，因此这些不是当前机器测得的延迟，TLB 命中率增加也不意味着程序吞吐量按同一比例增加。

## 3. 用地址空间身份区分翻译结果 {#_3-切换地址空间为什么要区分缓存身份}

不同进程的虚拟页号可以相同，但映射不同：

| 地址空间 | 虚拟页号 | 物理页框 | 教学缓存键   |
| -------- | -------- | -------- | ------------ |
| A        | 5        | 20       | `(身份A, 5)` |
| B        | 5        | 80       | `(身份B, 5)` |

[![相同虚拟页号用不同地址空间身份匹配不同翻译](/assets/notes/operating-systems/os-tlb-tags.svg)](/assets/notes/operating-systems/os-tlb-tags.svg)

若只用页号 5 匹配，就可能把 A 的页框 20 错用于 B，破坏正确性和保护。处理器与内核需要刷新旧翻译或正确区分缓存身份。

进程上下文标识符（PCID，Process-Context Identifier）是适用 x86 配置下的机制；地址空间标识符（ASID，Address Space Identifier）是其他架构常用的名称和机制类别，不能认为两者硬件格式与失效规则完全相同。上表的“身份”只是共同原理的抽象键，不是完整硬件标签格式；全局映射、页尺寸和具体上下文规则还需另查。

同一进程的线程通常共享地址空间，线程切换不天然要求清空全部 TLB；使用标识符时，切换到其他地址空间也可能保留此前翻译。但页表变化、权限收紧、标识符回收复用仍需正确失效。PCID/ASID 不等于永久免刷新，也不能直接把操作系统进程号当作硬件标识符。[Linux 页表概览](https://docs.kernel.org/mm/page_tables.html)

## 4. 页表更新与 TLB 失效 {#_4-页表更新后为什么需要失效}

TLB 跨处理器失效协调（TLB Shootdown）用于让相关 CPU 不再使用旧翻译。以内核把同一地址空间中 V→PFN7 的映射从可写改成只读为例：

| 时刻 | 内存中的页表                     | CPU0 / CPU1 的缓存与协调                        |
| ---- | -------------------------------- | ----------------------------------------------- |
| T0   | V→PFN7，可写                     | 两者都可能缓存可写翻译                          |
| T1   | 内核在适用锁与顺序保证下改为只读 | 写页表不表示两者旧翻译已经消失                  |
| T2   | 新 PTE 已发布给相关操作          | 发起适用本地失效，并使远端相关 CPU 执行所需失效 |
| T3   | 等待所需协调完成                 | 两者达到协议要求，不再使用被撤销的旧可写翻译    |
| T4   | 操作完成后才依赖只读状态         | 后续重新翻译/检查；写访问走相应保护路径         |

[![双 CPU 从旧可写翻译到只读 PTE、失效请求与完成确认的时序](/assets/notes/operating-systems/os-tlb-shootdown.svg)](/assets/notes/operating-systems/os-tlb-shootdown.svg)

在协调完成之前，不能宣称旧写权限已经全部撤销。物理页生命周期还要单独管理：如果是解除或重定向映射，旧页不能在仍有合法引用或可被使用的旧翻译时就复用于无关数据；只收紧权限也不意味着该页可以回收。

真实内核可根据地址空间在哪些 CPU 上运行过等信息缩小范围，并采用架构相关指令、处理器间通知或其他支持机制；不一定每次通知所有 CPU。表中的确认是协议完成条件，不是所有 Linux 版本都逐字使用同一组消息。更新 PTE、本地失效、远端协调与页面回收是不同动作。[Linux Cache and TLB Flushing](https://docs.kernel.org/core-api/cachetlb.html)

### 失效范围与成本

| 范围               | 典型取舍                                               |
| ------------------ | ------------------------------------------------------ |
| 单页               | 保留其他翻译；大量页面逐一处理可能有较高指令与协调成本 |
| 地址范围           | 只覆盖受影响范围；实际实现可能按页或选择更大刷新       |
| 地址空间或更大范围 | 实施次数可能较少，却淘汰无关翻译，后续要重新填充       |

x86 的 INVLPG、INVPCID 或写 CR3 各有模式、标签、全局映射等规则，不是所有架构的统一接口。不要把 Linux 0.11 的单 CPU CR3 重载等同于现代多核 Shootdown。[Linux x86 TLB 文档](https://docs.kernel.org/arch/x86/tlb.html)

## 5. 优化是多目标权衡

假设恰有 64 个可用翻译项，4 KiB 页的理论覆盖为 `64×4 KiB=256 KiB`；若每项映射 2 MiB，则为 `64×2 MiB=128 MiB`。这只是同项数假设，不代表任何实际 CPU 对各页尺寸都有相同的 TLB 容量。

大页可减少所需翻译项，但可能增加物理连续性、内部浪费与回收管理成本。还需固定工作负载和硬件，区分 TLB Miss、数据缓存 Miss 与 Minor/Major Fault，不能把“页越大越好”当成一般优化结论。

## 6. 软件模拟：标签、旧翻译和双缓存失效

保存为 `tlb.py`，运行 `python3 tlb.py`。只用字典模拟页表和两个 CPU 缓存，不读写主机页表。先故意修改页表而不失效，展示两个旧可写条目仍被模型使用；再使两个缓存失效，确认写入被拒绝。

```python
class Fault(Exception):
    pass


class CPU:
    def __init__(self):
        self.cache = {}  # (abstract address-space identity, VPN) -> (PFN, writable)

    def access(self, tables, space, va, write=False):
        key = (space, va >> 12)
        hit = key in self.cache
        if not hit:
            if key not in tables:
                raise Fault("not-present")
            self.cache[key] = tables[key]
        frame, writable = self.cache[key]
        if write and not writable:
            raise Fault("protection")
        return ("hit" if hit else "miss"), (frame << 12) | (va & 0xfff)

    def invalidate(self, space, vpn):
        self.cache.pop((space, vpn), None)


tables = {("A", 2): (7, True), ("A", 5): (20, True), ("B", 5): (80, True)}
cpu0, cpu1 = CPU(), CPU()
assert cpu0.access(tables, "A", 0x2240) == ("miss", 0x7240)
assert cpu0.access(tables, "A", 0x2240) == ("hit", 0x7240)
assert cpu0.access(tables, "A", 0x5000)[1] == 20 * 4096
assert cpu0.access(tables, "B", 0x5000)[1] == 80 * 4096
assert cpu0.access(tables, "A", 0x5000)[0] == "hit"
cpu1.access(tables, "A", 0x2240, write=True)
tables[("A", 2)] = (7, False)
# Deliberately demonstrate the broken protocol before invalidating BOTH caches.
assert cpu0.access(tables, "A", 0x2240, write=True)[0] == "hit"
assert cpu1.access(tables, "A", 0x2240, write=True)[0] == "hit"
for cpu in (cpu0, cpu1):
    cpu.invalidate("A", 2)
for cpu in (cpu0, cpu1):
    try:
        cpu.access(tables, "A", 0x2240, write=True)
    except Fault as error:
        assert str(error) == "protection"
    else:
        raise AssertionError("stale writable entry survived")
try:
    cpu0.access(tables, "A", 0x9000)
except Fault as error:
    assert str(error) == "not-present"
else:
    raise AssertionError("missing mapping accepted")
for h, expected in [(0.90, 121), (0.95, 111), (0.99, 103)]:
    assert abs(h * 101 + (1 - h) * 301 - expected) < 1e-9
assert 64 * 4096 == 256 * 1024
assert 64 * (2 * 1024**2) == 128 * 1024**2
print("miss -> hit / tags / stale entries / two-cache invalidation / faults: PASS")
print("EAT: 121 / 111 / 103 ns; coverage: 256 KiB / 128 MiB: PASS")
```

本轮已运行全部断言。`Fault` 表示模拟中的访问错误。

## 本章小结与联读

TLB 保存翻译和属性；命中仍受权限约束，Miss 可正常查表。页表改变后要完成适用失效，才可依赖新映射或权限。接着看[第十七章写时复制](/articles/os-linux011-copy-on-write.html)如何主动撤销写权限，再到[第十八章缺页处理](/articles/os-page-faults.html)分析异常恢复。[分页计算回顾](/articles/os-paging-page-tables.html)

[返回本册目录](/collections/operating-systems/)
