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

图可按左、中、右三栏阅读：应用与框架组织高层算子和服务，编译与运行时负责代码编译及执行管理，设备与系统提供驱动、通信和硬件支持。这些职责划分不表示应用每次都必须逐层调用所有库。数学库也可能直接使用 Driver API。CUDA 是 NVIDIA 的并行计算平台及编程体系，不等于一张显卡，也不等于某个 Python 包。[CUDA 平台说明](https://docs.nvidia.com/cuda/cuda-programming-guide/01-introduction/cuda-platform.html)

## 2. 从输入准备到设备计算与结果返回 {#_2-一次加速工作经历什么}

以向量加法为教学例：CPU 准备输入 → 把数据放到 GPU 可访问的内存 → 提交 kernel → 等待所需结果 → CPU 继续处理。在本文采用的 CUDA 12.8.1 语境中，kernel 是在 GPU 上执行的计算函数，与操作系统内核不同；kernel launch 是对该函数的一次启动，通常由多个线程分别处理数据。[kernel 定义与调用](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#kernels)

下面限定为离散 GPU、显式分配与拷贝的简单路径，做一次数据推演，不是实测：

1. CPU 在主机内存准备 `A=[1,2]`、`B=[3,4]`，并为设备端的 A、B、C 分配内存。
2. 将 A、B 从主机拷贝到设备，这一步称为 H2D（Host to Device）。此时设备端已有输入，C 尚未得到计算结果。
3. 启动加法 kernel，让两个线程分别计算 `C[0]=1+3=4` 和 `C[1]=2+4=6`。两个元素的计算互不依赖，可以并行处理；这也是向量加法能随数据量增加而组织更多并行工作的原因。
4. kernel launch 对主机异步，提交返回时设备可能尚未完成计算。这条简单路径在同步等待成功、确认设备计算完成后，再把 C 从设备拷贝回主机，即 D2H（Device to Host）。CPU 在回传完成后逐元素与预期的 `[4,6]` 比较；提交返回本身不能证明结果正确。[CUDA API 同步语义](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/api-sync-behavior.html)

在简单串行实现中，可用 `T总 = T准备 + TH2D + T提交 + T计算 + TD2H + T收尾` 建立开销账本：准备包含输入与内存准备，H2D/D2H 对应上述两次搬运，收尾包含结果校验与资源释放。实际流水线可能重叠这些阶段，不能把各工具报告的重叠时间再相加当作端到端延迟。

只有两个元素时，计算量很小，搬运与提交开销可能超过节省的计算时间，因此即使 GPU 计算更快，端到端也可能更慢。是否获益要比较完整路径的耗时，不能只看 kernel 时间。[主机与设备间的数据搬运](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-best-practices-guide/index.html#data-transfer-between-host-and-device)；显式分配、拷贝、同步与校验的完整代码见[第 4 章](/articles/ai-infra-cuda-memory.html)第 2 节“完整教学例：向量加法”。

如果只有一小部分工作能被加速，加速后的收益仍受未加速部分限制。例如原程序 20% 时间是必须串行的，即使其他部分无限快，整体加速比也不会超过 5。这个算例只用于说明固定问题规模下的 [Amdahl 定律](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-best-practices-guide/index.html#strong-scaling-and-amdahl-s-law)，不是本机测量。

## 3. 先分清四种问题

| 层次 | 要回答的问题                   | 常见证据                         |
| ---- | ------------------------------ | -------------------------------- |
| 功能 | GPU 能否被发现、计算结果对不对 | 错误码、最小用例、结果校验       |
| 性能 | 时间消耗在搬运、提交还是计算   | 时间线、kernel 报告、业务延迟    |
| 共享 | 多个任务如何复用一张卡         | MIG、MPS、调度器和限额策略       |
| 服务 | 请求是否达到容量和质量目标     | TTFT、TPOT、吞吐、错误率、质量集 |

对于生成式语言模型，token 是模型处理和生成文本的单位；TTFT 关注从请求到首个输出 token 前的等待，TPOT 关注后续输出 token 的平均耗时，分别反映首次响应和持续生成的速度。比较指标时需声明具体计时与聚合口径，详见[第 19 章指标解释](/articles/ai-infra-prefill-decode-kv-cache.html#_3-ttft、tpot-和吞吐不是一个数字)及 [NVIDIA NIM Benchmarking LLM 1.0.0 指标文档](https://docs.nvidia.com/nim/benchmarking/llm/1.0.0/metrics)。

GPU 利用率只提供设备活动的一部分信息，功能正确性、资源隔离与用户响应还需分别使用对应证据判断。

## 4. 本册的版本边界

CUDA 基础 API 以 [12.8.1 归档编程指南](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html)及上述同版本同步语义、最佳实践文档为机制参考；第 1 节的在线 CUDA 平台页面用于概念说明，不是 12.8.1 归档。
