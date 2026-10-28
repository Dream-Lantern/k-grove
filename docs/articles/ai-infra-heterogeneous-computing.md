---
id: ai-infra-heterogeneous-computing
title: 第 1 章 异构计算全景：从 CPU 到模型服务
description: "异构系统可以组合 CPU、GPU、NPU、FPGA 等不同处理器。CPU 适合复杂控制流、通用操作和低延迟任务；GPU 通过大量并行工作获得高吞吐。"
date: '2026-10-25'
updated: '2026-10-28'
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
order: 1
---

# 第 1 章 异构计算全景：从 CPU 到模型服务

## 1. 异构处理器的分工与连接 {#_1-异构指的是处理器分工-不只是-cpu-加-gpu}

异构系统可以组合 CPU、GPU、NPU、FPGA 等不同处理器。CPU 适合复杂控制流、通用操作和低延迟任务；GPU 通过大量并行工作获得高吞吐。CPU 同样支持多核并行、SIMD 和多线程；比较两者时，应观察任务组织、控制流与吞吐特点。

离散 GPU 常经 PCIe 连接主机，但这不是所有系统的固定结构。集成式系统、CPU/GPU 一致性互连、GPU 间的 NVLink 等属于不同层次，是否共享地址、是否自动搬运数据都要具体分析。

[![异构计算：软件栈与跨层调用](/assets/notes/ai-infra/hetero-stack.svg)](/assets/notes/ai-infra/hetero-stack.svg)

图中箭头表示工作提交的层次，不表示应用每次都必须逐层调用所有库。数学库也可能直接使用 Driver API。CUDA 是 NVIDIA 的并行计算平台及编程体系，不等于一张显卡，也不等于某个 Python 包。[CUDA 平台说明](https://docs.nvidia.com/cuda/cuda-programming-guide/01-introduction/cuda-platform.html)

## 2. 从输入准备到设备计算与结果返回 {#_2-一次加速工作经历什么}

以向量加法为教学例：CPU 准备输入 → 把数据放到 GPU 可访问的内存 → 提交 kernel → 等待所需结果 → CPU 继续处理。kernel 是设备端计算函数的一次执行，而不是操作系统内核。

在简单串行实现中，可用 `T总 = T准备 + TH2D + T提交 + T计算 + TD2H + T收尾` 建立开销账本。实际流水线可能重叠这些阶段，不能把各工具报告的重叠时间再相加当作端到端延迟。

如果只有一小部分工作能被加速，加速后的收益仍受未加速部分限制。例如原程序 20% 时间是必须串行的，即使其他部分无限快，整体加速比也不会超过 5。这个算例只用于说明 Amdahl 定律，不是本机测量。

## 3. 先分清四种问题

| 层次 | 要回答的问题                   | 常见证据                         |
| ---- | ------------------------------ | -------------------------------- |
| 功能 | GPU 能否被发现、计算结果对不对 | 错误码、最小用例、结果校验       |
| 性能 | 时间消耗在搬运、提交还是计算   | 时间线、kernel 报告、业务延迟    |
| 共享 | 多个任务如何复用一张卡         | MIG、MPS、调度器和限额策略       |
| 服务 | 请求是否达到容量和质量目标     | TTFT、TPOT、吞吐、错误率、质量集 |

GPU 利用率只提供设备活动的一部分信息，功能正确性、资源隔离与用户响应还需分别使用对应证据判断。

## 4. 本册的版本边界

CUDA 基础 API 以 12.8.1 归档文档为机制参考。
