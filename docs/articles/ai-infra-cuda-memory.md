---
id: ai-infra-cuda-memory
title: 第 4 章 显存与最小 CUDA 程序：先保证结果正确
description: "CUDA 内存模型同时涉及数据的作用域、存放位置和访问条件。先区分线程私有数据、块内共享数据与设备可访问分配，再沿分配、传输、执行和结果校验理解一个最小程序。"
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
order: 4
---

# 第 4 章 显存与最小 CUDA 程序：先保证结果正确

CUDA 内存模型同时涉及数据的作用域、存放位置和访问条件。先区分线程私有数据、块内共享数据与设备可访问分配，再沿分配、传输、执行和结果校验理解一个最小程序。局部变量的语法作用域与最终存放位置分别判断。

## 1. 常见内存层次

[![内存：作用域与访问方式](/assets/notes/ai-infra/memory-scopes.svg)](/assets/notes/ai-infra/memory-scopes.svg)

| 类型               | 典型作用域           | 使用要点                         |
| ------------------ | -------------------- | -------------------------------- |
| 寄存器             | 单线程               | 数量有限；压力过高可能发生 spill |
| Shared memory      | 线程块               | 显式协作，配合正确同步           |
| Global memory      | 设备可访问的分配     | 容量大；布局和访问方式影响性能   |
| Local memory       | 逻辑上的线程私有数据 | 可能落到设备内存，不等于高速缓存 |
| Host pinned memory | 页锁定主机内存       | 有利于特定异步搬运；不宜无限分配 |

Unified Memory 提供统一的编程模型，但不意味着“所有数据永远同时在 CPU/GPU 本地”。迁移、缺页和访问策略仍可能带来开销。先掌握显式分配与拷贝，再学习统一内存，有助于判断数据移动的成本。

## 2. 完整教学例：向量加法

下面是新增的最小 CUDA C++ 示例，面向 Linux + CUDA Toolkit 的独立学习环境。错误检查失败时，进程退出并由系统回收资源；正常路径则显式释放资源。

```cpp
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <vector>
#define CHECK(expr) do { cudaError_t e=(expr); if(e!=cudaSuccess) { \
  std::fprintf(stderr, "%s: %s\n", #expr, cudaGetErrorString(e)); \
  std::exit(1); } } while(0)

__global__ void add(const float* a, const float* b, float* c, int n) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  if (i < n) c[i] = a[i] + b[i];
}
int main() {
  const int n = 1000;
  const size_t bytes = n * sizeof(float);
  std::vector<float> a(n, 1.0f), b(n, 2.0f), c(n);
  float *da = nullptr, *db = nullptr, *dc = nullptr;
  CHECK(cudaMalloc(&da, bytes));
  CHECK(cudaMalloc(&db, bytes));
  CHECK(cudaMalloc(&dc, bytes));
  CHECK(cudaMemcpy(da, a.data(), bytes, cudaMemcpyHostToDevice));
  CHECK(cudaMemcpy(db, b.data(), bytes, cudaMemcpyHostToDevice));
  add<<<(n + 255) / 256, 256>>>(da, db, dc, n);
  CHECK(cudaGetLastError());          // 检查 launch 配置等即时错误
  CHECK(cudaDeviceSynchronize());     // 在这里检查异步执行错误
  CHECK(cudaMemcpy(c.data(), dc, bytes, cudaMemcpyDeviceToHost));
  bool ok = true;
  for (float x : c) if (x != 3.0f) ok = false;
  CHECK(cudaFree(dc)); CHECK(cudaFree(db)); CHECK(cudaFree(da));
  std::puts(ok ? "PASS" : "FAIL");
  return ok ? 0 : 2;
}
```

把它保存为 `vector_add.cu` 后，可在已准备好的实验环境用 `nvcc vector_add.cu -o vector_add` 编译。

## 3. 分别检查提交与异步执行结果 {#_3-为什么检查两次错误}

launch 返回主要表示工作已提交；执行可能晚于 CPU 继续运行。只在 launch 后调用一次 `cudaGetLastError()`，不能证明设备端计算已经成功。同步点是观察异步错误的重要位置，但它发现的错误也可能由更早的工作引起。[CUDA API 同步语义](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/api-sync-behavior.html)

这里使用简单的同步拷贝，先建立正确性基线。优化时再引入 pinned memory、stream 和分块流水线，每次只改变一个因素，并持续校验结果。[CUDA 最佳实践：内存与数据移动](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-best-practices-guide/index.html)

## 4. 内存范围、同步范围和进度保证要一起写

| 场景           | 通信介质                 | 同步/可见性                     | 进度前提                     |
| -------------- | ------------------------ | ------------------------------- | ---------------------------- |
| 同一普通 block | shared/global 等合法内存 | 正确的 block barrier 或原子协议 | 参与线程合法到达同步点       |
| 不同普通 block | global 等合法内存        | 原子及相应内存顺序，或拆 kernel | 不假定所有 block 同时常驻    |
| 不同 stream    | 有效且可访问的分配       | event 等显式依赖                | 对象活到最后一次使用完成     |
| 不同进程/设备  | IPC、peer 等受支持路径   | 显式共享契约与同步              | 设备、驱动和生命周期条件成立 |

共享数据时，依次确认分配有效、访问被允许、写入对读取方可见，以及通信双方有推进机会。内存范围、同步范围和进度前提共同决定程序能否正确完成。
