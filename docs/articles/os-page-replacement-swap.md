---
id: os-page-replacement-swap
title: 第十九章 页面置换、工作集、swap 与颠簸
description: 虚拟内存提供地址抽象、保护与受控共享，不以持续换入换出为定义。物理内存压力增大时，系统才需要更积极地回收；回收也不意味着每个页面都写入 swap。
date: '2026-10-25'
updated: '2026-10-25'
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

> 阅读标签：教学置换模型 / 现代Linux回收旁注。

虚拟内存提供地址抽象、保护与受控共享，不以持续换入换出为定义。物理内存压力增大时，系统才需要更积极地回收；回收也不意味着每个页面都写入 swap。

## 1. 不同页有不同去向

![按页面类型理解回收](/assets/notes/operating-systems/os-reclaim.svg)

条件允许时，干净文件页可以丢弃，后续再从文件读取；脏文件页则需要相应写回。匿名页可能借助 swap 回收，也可能因锁定、引用或配置等条件无法立即回收。没有 swap 仍能使用虚拟内存，但回收选择及内存压力的后果会有所不同。

原笔记“换入换出都是磁盘读写、每次淘汰都先写盘”过度概括。文件页缓存、匿名内存与设备特殊映射要分开分析。[Linux 6.6 内存概念](https://docs.kernel.org/6.6/admin-guide/mm/concepts.html)

## 2. FIFO、OPT、LRU 分别看什么？

FIFO 参考进入顺序；OPT/MIN 淘汰未来下一次使用最远的页，不是简单选择历史使用率最低的页，它需要未来信息，通常作理论对照；LRU 参考最近过去的访问。

精确 LRU 可以在某些受控缓存中维护，不宜说成理论上不可实现；对所有 CPU 内存访问逐次维护精确全局顺序成本很高，所以操作系统采用近似或其他策略。[OSTEP 页面策略](https://pages.cs.wisc.edu/~remzi/OSTEP/vm-beyondphys-policy.pdf)

## 3. Clock 的第二次机会

简化 Clock 用环形候选和访问位；扫描遇到已访问页，清位并继续，遇到适用未访问页可作为候选。还需检查脏页、锁定与其他状态；扫描速度和更新时机影响近似效果。

它不是现代 Linux 唯一通用实现。Multi-Gen LRU 等路线按版本、构建和运行时支持提供不同的回收管理；文档中的开关不在本次自动修改范围。[Linux 6.6 Multi-Gen LRU](https://docs.kernel.org/6.6/admin-guide/mm/multigen_lru.html)

## 4. 工作集与颠簸

工作集表示某时间窗口内活跃使用的页面集合。多个任务总工作集超出可用资源时，刚换出的页很快又被请求，I/O 与缺页等待占据大量时间，有效业务进展下降。

以纸面推演为例：两个任务反复访问的页面范围各自超过可驻留预算，即使 CPU 计算量不大，也可能持续等待。继续提高并发或盲目增加任务，可能让情况恶化；应综合分析并发、局部性、内存限制与回收行为。

## 5. OOM 与 swap 调参的边界

内核或容器限制下无法满足分配，可能触发相应拒绝或 OOM 处理。全机剩余空间、某容器上限和单进程虚拟大小不是一个指标，RSS 也不能与所有缓存统计重复相加。

不能仅因电脑卡顿，就直接建议清缓存、关闭 swap 或调高某个参数。实际变更前还需定位问题、备份并验证。本章仅补充理论与观察方法，未执行回收、交换或杀进程操作。

[返回本册目录](/collections/operating-systems/)
