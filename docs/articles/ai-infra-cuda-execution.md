---
id: ai-infra-cuda-execution
title: 第 3 章 CUDA 执行模型：Grid、Block、Warp 与同步
description: 理解 CUDA 程序，不能只停留在“线程很多”。本章进一步说明线程如何组织、哪些线程可以同步，以及 block 大小为什么会影响资源使用。
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
order: 3
---

# 第 3 章 CUDA 执行模型：Grid、Block、Warp 与同步

理解 CUDA 程序，不能只停留在“线程很多”。本章进一步说明线程如何组织、哪些线程可以同步，以及 block 大小为什么会影响资源使用。

## 1. 从一次 kernel launch 看层次

一次普通 kernel launch 定义一个 grid；grid 包含多个 block，block 包含线程。线程用 `threadIdx`、`blockIdx`、`blockDim` 定位自己的工作。一维数组常用 `i = blockIdx.x * blockDim.x + threadIdx.x` 得到全局索引。

[![CUDA：Grid/Block/SM映射关系](/assets/notes/ai-infra/cuda-hierarchy.png)](/assets/notes/ai-infra/cuda-hierarchy.png)

普通线程块整体被分配到某个 SM 上执行；同一 SM 可以容纳多个 block，数量受寄存器、共享内存和架构上限约束。block 的执行先后不可假定，更不能依赖“block 0 必须先完成”。支持 thread block cluster 的新架构还有额外协作机制，不能倒推为所有 GPU 都支持。

## 2. Warp 是 32 个线程的执行组织

在本册讨论的 NVIDIA CUDA 架构中，一个 warp 包含 32 个线程。SIMT 允许线程按各自数据执行相同程序。分支条件在 warp 内不一致时，会产生发散并可能降低执行效率。

从 Volta 起还需要考虑 Independent Thread Scheduling。不要假设 warp 内线程始终隐式同步；涉及 warp 内共享数据时使用正确的掩码、同步或原语。`__syncthreads()` 是线程块范围的屏障，要求该块需要参与的线程以合法方式到达，不能放在仅部分线程会进入的分支中。[CUDA 编程模型与硬件实现，12.8.1](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html)

## 3. 常驻不等于每周期都执行

常驻 warp 会占用相应硬件资源，但也可能正在等待数据或依赖；只有满足发射条件的 warp 才有机会被调度器选中。本章用“等待—就绪—选中”解释延迟隐藏，这并不是精确、完整的硬件状态机。

原文“调度器优先选择计算密集型 warp”缺少公开契约依据，应删除。调度策略不是应用可依赖的正确性保证。资源占用高也不保证吞吐高，因为所有常驻 warp 都可能在等待同一类瓶颈。

## 4. Block 之间能否通信

可以通过合法的全局内存、原子操作或相应协作机制交换数据，但普通 kernel 内不存在一个随手可用的全 grid 屏障。简单地让一个 block 自旋等待另一个尚未被调度的 block，可能死锁。

入门时，最稳妥的设计是将不同阶段拆成多个 kernel，在同一 stream 中按序执行；需要跨块协作时，再研究 cooperative launch、cluster 等条件。先确认算法正确，再判断多一次提交是否确实造成了瓶颈。

## 5. 线程块大小的选择

128、256 等只是常见试验点，不是最优定律。用 occupancy API 得到候选值后，还要看访问合并、寄存器压力、尾部浪费和端到端时间。如果为了限制 grid 大小而只启动少量 block，kernel 必须采用 grid-stride loop 等方式覆盖全部数据，不能漏算剩余元素。

## 6. 被限制的 Grid 需要循环覆盖

下面为 kernel 片段，它解释了覆盖协议。

```cpp
__global__ void add_stride(const float* a, const float* b,
                           float* c, size_t n) {
  size_t start = size_t(blockIdx.x) * blockDim.x + threadIdx.x;
  size_t stride = size_t(blockDim.x) * gridDim.x;
  for (size_t i = start; i < n; i += stride) {
    c[i] = a[i] + b[i];
  }
}
```

假设启动了 1024 个线程而数组有 10000 个元素，线程会按步长继续处理后续位置，而不是只算前 1024 个。这个例子假设索引和步长在 `size_t` 中可表示；超大规模还要检查乘法与递增溢出。occupancy API 只能帮助选择候选启动规模，不能代替完整覆盖和实测。

## 7. 函数限定符说的是调用与执行语义

| 限定符       | 常见含义                      | 不应理解为                      |
| ------------ | ----------------------------- | ------------------------------- |
| `__host__`   | host 端函数                   | 源码存放在 CPU 内               |
| `__device__` | device 端函数，由设备代码调用 | host 可以像普通函数一样直接调用 |
| `__global__` | device 执行的 kernel 入口     | 所有场景都只能由 host 发起      |

设备端 kernel launch 属于动态并行，须核对架构、Toolkit 与链接要求。它与设备堆上的 `malloc`，以及 host 端 `cudaMalloc` 是不同机制。[CUDA 12.8.1 编译与链接说明](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-compiler-driver-nvcc/index.html)
