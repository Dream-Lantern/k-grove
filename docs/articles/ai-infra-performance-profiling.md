---
id: ai-infra-performance-profiling
title: 第 12 章 性能分析：先看时间线，再看 Kernel
description: GPU 利用率很高，模型服务却仍然缓慢时，应先定位耗时环节，再选择测量工具。本章区分“系统时间线”“kernel 内部效率”和“长期监控”，避免同时启用所有 profiler。
date: '2026-10-25'
updated: '2026-10-25'
category: gpu-infra
type: explanation
tags:
  - ai-infra
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 12
---

# 第 12 章 性能分析：先看时间线，再看 Kernel

GPU 利用率很高，模型服务却仍然缓慢时，应先定位耗时环节，再选择测量工具。本章区分“系统时间线”“kernel 内部效率”和“长期监控”，避免同时启用所有 profiler。

## 1. 工具分工

| 工具           | 优先回答的问题                 | 典型输出                 |
| -------------- | ------------------------------ | ------------------------ |
| Nsight Systems | CPU/GPU 在等待什么，哪里有空隙 | CUDA、CPU、NVTX 等时间线 |
| Nsight Compute | 选定 kernel 为什么慢           | 指令、访存、占用率等分析 |
| NVML/DCGM      | 长期状态与资源是否异常         | 设备、实体和采样指标     |
| 业务压测       | 用户实际得到了什么             | 延迟分位数、吞吐和错误率 |

![性能分析的证据分支](/assets/notes/ai-infra/profiling-decision.svg)

## 2. 先做一份有限窗口的时间线

下面是 Linux 文档示例，`app.py` 为占位应用；实际采集会运行应用、产生报告并带来开销。

```bash
nsys profile --trace=cuda,nvtx --delay=5 --duration=10 \
  --output=trial python app.py
nsys stats trial.nsys-rep
```

保留原文 NVTX 自定义标记的思路：用请求处理、prefill、decode、数据加载等业务阶段对齐时间线。先预热并关注稳定区间，避免把首次 JIT 或模型加载误当作每次请求成本。[Nsight Systems User Guide](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)

## 3. 再缩小到一个 Kernel

```bash
ncu --set basic --launch-count 1 --output=kernel-trial python app.py
```

该命令只展示最小采集思路，不保证首个 kernel 就是目标，实际使用时应按名称和启动范围筛选。Nsight Compute 可能通过 replay 收集多组计数器，因此测得的时间不等于无采集条件下的业务延迟。metric 名称也会随硬件和版本变化，应查询支持列表后再选择。[Nsight Compute Profiling Guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html)

## 4. Occupancy 和 Roofline 怎么用

较高的 Occupancy 可能有助于隐藏延迟，但它本身不是优化目标。如果增加常驻 warp 导致寄存器溢出，运行反而可能更慢。判断时需要综合考虑共享内存、寄存器和 block 数的约束。

Roofline 用算术强度 `I = 运算次数 / 数据字节数` 连接计算峰值与带宽峰值，可建立 `性能上界 ≈ min(计算峰值, 带宽 × I)`。这里必须注明数据来自哪一层、使用哪种精度。它是帮助提出瓶颈假设的模型，不是精确预测器。

## 5. 一次可复查的优化实验

固定版本和输入 → 正确性基线 → 无采集端到端基线 → 定位热点 → 只改一个因素 → 同样负载复测。报告同时列出均值和尾延迟、重复次数、预热、并发及是否启用 profiler。删掉“开启某选项就固定快 3 倍”这样的无条件承诺，保留可复现实验方法。

## 6. Trace、GPU Metrics 和 Replay 分开标注

`nsys --trace=cuda,nvtx` 提供相应 API/活动与标记时间线，不代表默认已经取得所有 SM occupancy、DRAM 带宽和硬件指标。若额外启用 GPU metrics，核对硬件支持、采样配置和权限，并在报告中列为另一项采集配置。

`ncu` 的 kernel 选择、replay 与缓存控制则可能改变观测条件。不要把多 pass 得到的计数器直接视为该服务某次无干扰请求的完整现场。对“多个 GPU kernel 同时重叠”的问题，应保留 Systems 时间线作为背景，再选择需深入的 kernel；不同工具报告的百分比也不能在不核对分母时相互验证。
