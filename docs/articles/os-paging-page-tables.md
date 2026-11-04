---
id: os-paging-page-tables
title: 第十五章 分页与多级页表的地址计算
description: "分页把虚拟空间分为页，把物理内存分为页框，再通过页表连接两者。地址翻译先确定虚拟页对应的物理页框，再保留页内偏移。相邻虚拟页可以映射到不相邻的物理页框，从而把虚拟连续与物理连续分开管理。"
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
order: 15
---

# 第十五章 分页与多级页表的地址计算

> 阅读标签：x86 32 位非 PAE、4 KiB 页、4 字节表项、两级分页，不使用大页的教学模型。

程序需要连续的虚拟空间，并不意味着系统总能找到同样连续的物理内存。分页把虚拟空间分为页，把物理内存分为页框，再通过页表连接两者；相邻虚拟页可以映射到不相邻物理页框。以下统一把平坦分段下的虚拟地址作为线性地址讨论，历史分段生成线性地址的过程见上一组章节。

本章关闭物理地址扩展（PAE，Physical Address Extension），只分析 32 位地址和普通 4 KiB 页。它不是所有中央处理器（CPU，Central Processing Unit）及现代 Linux 的通用结构。相关硬件规则依据 [Intel 手册 Volume 3A 的 Paging 章节](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)。

## 1. 页号、页框号与页内偏移 {#_1-页号和页内偏移怎样分开}

`4 KiB = 4096 = 2^12` 字节，所以地址低 12 位在页内定位，高位标识虚拟页。KiB 是 1024 字节，MiB 是 1024 KiB，GiB 是 1024 MiB。对 `0x00002240`：

```text
0x00002240 = 2 × 0x1000 + 0x240
虚拟页号 = 2，页内偏移 = 0x240
```

商是页号、余数是偏移；整个 `0x2000～0x2FFF` 都在虚拟页 2，偏移从 0 到 `0xFFF`。两级结构把页号再拆为两个索引，不能把虚拟页号 2 不加说明地当成所有模型中的页表索引。

```text
32 位地址：0000 0000 0000 0000 0010 0010 0100 0000
字段拆分：0000000000 | 0000000010 | 001001000000
             10 位        10 位         12 位
```

| 字段       | 位范围 | 计算                 | 结果    |
| ---------- | ------ | -------------------- | ------- |
| 页目录索引 | 31～22 | `va >> 22`           | 0       |
| 页表索引   | 21～12 | `(va >> 12) & 0x3FF` | 2       |
| 页内偏移   | 11～0  | `va & 0xFFF`         | `0x240` |

`0x2240` 小于 `0x400000`，最高 10 位全为 0；去掉低 12 位后是 2，所以第二个字段为 2；最低三个十六进制数位组成偏移 `0x240`。若映射到物理页框 7，结果应为 `0x7000 + 0x240 = 0x7240`；第三节再展开“从哪里得到 7”。这是纸面计算，不是访问真实地址。

## 2. 单级页表的规模计算 {#_2-单级页表为什么可能很大}

固定上述参数，完整平坦单级页表需要为所有虚拟页各留一个条目：

```text
地址空间大小 = 2^32 字节 = 4 GiB
每页大小     = 2^12 字节 = 4 KiB
虚拟页数量   = 2^32 / 2^12 = 2^20
每项 4 字节  → 2^20 × 4 = 2^22 字节 = 4 MiB
```

4 MiB 是覆盖整个 32 位虚拟页空间的**完整平坦表**的规模，不表示进程已使用 4 GiB 物理内存。即使程序只映射很少几页，这种完整平坦结构也要保留全部条目，这正是引入按需分层的动机。

页表项大小、地址宽度和页尺寸必须固定，不能把此数推广到任意 64 位机器。页表本身占用内核管理的物理内存，不是应用可以随意修改的普通数组。

## 3. 两级表按需建立

页目录项（PDE，Page Directory Entry）指向适用的二级页表；页表项（PTE，Page Table Entry）在本模型中描述数据页映射。每张表 1024 项、每项 4 字节，因此目录和每张二级表各占 4 KiB；一张二级表覆盖 `1024 × 4 KiB = 4 MiB` 虚拟范围。

[![0x2240 的 10/10/12 位拆分、PDE/PTE 物理位置与 0x7240 结果](/assets/notes/operating-systems/os-paging.svg)](/assets/notes/operating-systems/os-paging.svg)

为把遍历落到具体位置，再人为设定页目录物理基址 `0x1000`、二级表物理基址 `0x2000`；这些表地址及数据页框均是教学假设：

| 步骤 | 查找或检查                                                    | 本例结果                                                 |
| ---- | ------------------------------------------------------------- | -------------------------------------------------------- |
| 1    | 从 x86 CR3 的相关地址位取得页目录基址，忽略本例不展开的控制位 | 页目录在物理 `0x1000`，不是把整个寄存器值都当裸地址      |
| 2    | 目录项地址 = 基址 + 目录索引 × 4                              | `0x1000 + 0×4 = 0x1000`，读取 PDE[0]                     |
| 3    | 检查 PDE 存在、保留位合法且指向普通页表，提取表基址           | PDE 的地址部分为 `0x2000`，不是把属性位加进地址          |
| 4    | 页表项地址 = 二级表基址 + 页表索引 × 4                        | `0x2000 + 2×4 = 0x2008`，读取 PTE[2]                     |
| 5    | 检查 PTE 存在，并结合层级权限与访问类型检查                   | 允许本例用户访问；物理页框号（PFN，Page Frame Number）=7 |
| 6    | 页框基址 = PFN × 4096，保留页内偏移                           | `0x7000 + 0x240 = 0x7240`                                |

PDE/PTE 保存的是地址信息和属性，不能把整个条目的数值都当页框号。允许用户写入不能只看叶子 PTE，还需相应 PDE 的用户/写权限允许；内核态写入另受适用控制位等规则影响。此处限定正常用户态访问，未完整展开所有保护功能。

页表遍历和数据访问都经过硬件相关机制；真实 CPU 可能命中翻译后备缓冲（TLB，Translation Lookaside Buffer），从缓存中取得翻译而避免每次完整遍历。相邻虚拟页 3 也可映射页框 9，使 `0x3000` 对应 `0x9000`，无需接在页框 7 后面。[Linux Page Tables](https://docs.kernel.org/mm/page_tables.html)

## 4. 多级页表的空间与遍历成本 {#_4-多加一级不是永远更省}

若某个目录覆盖的 4 MiB 范围完全不需要叶子映射，可以不建立对应二级页表；但只要建了二级表，就占完整的 4 KiB，不能把其中每个无效条目当成不占空间。

| 映射分布（仅统计表结构）         | 完整平坦单级表 | 本模型两级结构                              |
| -------------------------------- | -------------- | ------------------------------------------- |
| 只映射 `0x2000` 所在一页         | 4 MiB          | 目录 4 KiB + 1 张二级表 4 KiB = 8 KiB       |
| 映射 `0x2000` 和 `0x400000` 两页 | 4 MiB          | 分属目录项 0 与 1：4 KiB + 2×4 KiB = 12 KiB |
| 两页都在同一个目录项覆盖范围     | 4 MiB          | 仍可只需 1 张二级表，合计 8 KiB             |
| 全部 1024 个目录项都需要二级表   | 4 MiB          | 4 KiB + 1024×4 KiB = 4 MiB + 4 KiB          |

[![完整平坦页表与稀疏两级页表的表结构开销对照](/assets/notes/operating-systems/os-page-table-cost.svg)](/assets/notes/operating-systems/os-page-table-cost.svg)

这些数值不含被映射的数据页、VMA 或其他内核开销；仅映射一页时的 8 KiB 不包括那一页数据本身。可见节省来自“未使用范围不分配下级表”，不是“所有多级表永远比单级小”。更深层级增加遍历工作，稠密程度、表页大小、大页与缓存都会影响实际成本。

### 与现代结构对照

| 模型或抽象       | 基本含义与边界                                                                 |
| ---------------- | ------------------------------------------------------------------------------ |
| 本章 32 位非 PAE | 普通 4 KiB 页按 10/10/12 拆分，硬件两级                                        |
| x86-64 四级      | 普通 4 KiB 页通常每级 9 位索引，使用适用的规范地址规则，不能照抄 32 位地址拆分 |
| x86-64 五级      | 在支持并启用的硬件/系统配置下增加一级，扩展可用线性地址范围                    |
| Linux 软件抽象   | PGD → P4D → PUD → PMD → PTE，按架构和配置折叠不需要的层级                      |

这些软件层名分别指 Page Global Directory（全局页目录）、Page 4th-level Directory（第四级目录）、Page Upper Directory（上层目录）、Page Middle Directory（中间目录）与页表项层。软件有五级抽象，不等于机器一定启用了五级硬件分页。适用大页可以在更高层级结束遍历。CR3 是 x86 的控制寄存器机制，不是所有平台通用的“页表寄存器”。[Linux 页表层级与折叠](https://docs.kernel.org/mm/page_tables.html)

## 5. 翻译也包含保护

内存管理单元（MMU，Memory Management Unit）不仅计算目标地址，也执行适用检查。对于本章已形成合法线性地址的普通用户数据访问，不存在相应 present 映射或违反页级权限，都会进入 x86 页故障异常（Page Fault，常称缺页异常）路径；“页故障”不只指数据不在内存。

| 情况                         | 硬件观察                                      | 内核可能如何处理                                                            |
| ---------------------------- | --------------------------------------------- | --------------------------------------------------------------------------- |
| 存在且允许访问               | 对应层级存在位与权限满足                      | 正常完成访问                                                                |
| PDE/PTE 不存在               | 当前无法直接翻译，进入缺页异常                | 若在合法区域内，可能按需分配或建立映射，不一定有磁盘 I/O                    |
| 页存在但只读，用户请求写     | 页级保护不满足，也进入缺页异常                | 合法写时复制（COW，Copy-On-Write）可分配/复制后更新映射；真正不允许写则拒绝 |
| 文件后备页尚未准备好         | 当前映射不足以完成访问                        | 可能复用已有缓存，也可能读取存储                                            |
| 地址没有允许该访问的合法区域 | 硬件只见地址及页表状态，不认识 VMA 的业务含义 | Linux 通常不能修复，会向进程报告适用错误或信号                              |

[![映射有效、映射缺失与权限不足后由内核判定能否恢复的分支](/assets/notes/operating-systems/os-page-access.svg)](/assets/notes/operating-systems/os-page-access.svg)

访问若先违反分段规则，会在分页之前走其他异常；x86-64 非规范地址也不能一律叫缺页。本节只讨论已限定的分页访问。TLB 未命中仅表示缓存中没找到可用翻译，页表有效时仍可成功遍历，不等于缺页，更不等于必读磁盘。[Intel Volume 3A：Access Rights 与 Page-Fault Exceptions](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)

## 6. Python 两级页表模拟

保存为 `paging.py`，运行 `python3 paging.py`。用字典模拟目录与表，条目用 `(页框号, present, user, writable)` 表示。二级表页框 2 与数据页框 7 是不同对象；映射页框 9 用于边界和只读案例。

```python
def translate(va, directory, tables, write=False, user=True):
    # Each entry is (frame_number, present, user_allowed, writable).
    # Directory frame numbers index tables; leaf frame numbers identify data.
    if not isinstance(va, int) or not 0 <= va < 2**32:
        raise ValueError("not a 32-bit address")
    di, ti, offset = va >> 22, (va >> 12) & 0x3ff, va & 0xfff
    pde = directory.get(di)
    if pde is None or not pde[1]:
        return (di, ti, offset), "missing-PDE"
    pte = tables[pde[0]].get(ti)
    if pte is None or not pte[1]:
        return (di, ti, offset), "missing-PTE"
    if (user and not (pde[2] and pte[2])) or (write and not (pde[3] and pte[3])):
        return (di, ti, offset), "permission"
    return (di, ti, offset), (pte[0] << 12) | offset


directory = {0: (2, True, True, True)}
tables = {2: {2: (7, True, True, True), 3: (9, True, True, False)}}
assert translate(0x2240, directory, tables) == ((0, 2, 0x240), 0x7240)
assert translate(0x2000, directory, tables)[1] == 0x7000
assert translate(0x2fff, directory, tables)[1] == 0x7fff
assert translate(0x3000, directory, tables)[1] == 0x9000
assert translate(0x400000, directory, tables)[1] == "missing-PDE"
assert translate(0x1000, directory, tables)[1] == "missing-PTE"
assert translate(0x3000, directory, tables, write=True)[1] == "permission"
restricted = {0: (2, True, True, False)}
assert translate(0x2240, restricted, tables, write=True)[1] == "permission"
supervisor = {0: (2, True, False, True)}
assert translate(0x2240, supervisor, tables)[1] == "permission"
assert translate(0x2240, supervisor, tables, user=False)[1] == 0x7240
assert 2**20 * 4 == 4 * 1024**2
assert (1 + 1) * 4096 == 8192
assert (1 + 2) * 4096 == 12288
print("0x2240 ->", hex(translate(0x2240, directory, tables)[1]))
print("boundaries / missing PDE-PTE / permissions / 4 MiB / 8-12 KiB: PASS")
```

本轮运行的正常结果为 `0x2240 -> 0x7240`，边界、缺失 PDE/PTE、上下级写权限和用户权限、页表开销断言通过。模拟仅简化用户/写权限；即使提供 `user=False` 也不模拟真实内核态写保护规则。它不检查所有保留位、不实现硬件异常优先级、访问/脏位、完整 MMU 或 TLB，不修改主机真实页表；返回的字符串是教学诊断，不是 CPU 页故障错误码。

## 本章小结与联读

页号通过页表找到页框，偏移保持不变；两级结构按范围分配下级表，适合某些稀疏布局，但不保证总是更省。地址能否使用还取决于存在性和权限。接着阅读[第十六章 TLB](/articles/os-tlb.html)、[第十七章写时复制](/articles/os-linux011-copy-on-write.html)和[第十八章缺页处理](/articles/os-page-faults.html)，分别展开翻译缓存、受控共享与异常恢复。

[返回本册目录](/collections/operating-systems/)
