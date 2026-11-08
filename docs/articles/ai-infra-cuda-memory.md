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

### 一个线程块怎样处理输入

考虑一维相邻求和 `y[i] = x[i] + x[min(i + 1, n - 1)]`。输入输出使用独立的全局缓冲区。每块有 256 个线程并处理至多 256 个输出，使用 257 个共享内存元素暂存当前块和右侧邻居。

1. 各线程按连续索引从 Global Memory 读入自己的元素，放入 `tile[threadIdx.x]`。无效线程只写入占位值。线程 0 额外将 `x[min(base + 256, n - 1)]` 放入 `tile[256]`。
2. 所有线程执行 `__syncthreads()`。即便尾块有无效线程，它们也要参加这个屏障，保证共享数据写完后再被其他线程读取。
3. 有效线程把两个加数读到私有变量。若 `i == n - 1`，直接复用自己的加数实现边缘复制。计算结果写回 `y[i]`。空输入由主机跳过启动。

Shared Memory 在普通用法下由同一个 Block 的线程共享。这个例子让相邻输出复用已暂存的输入，但也增加了屏障和共享内存占用。连续布局使一个 warp 的地址有机会合并为较少的内存事务。Global Memory 访问还可能命中缓存，具体取决于指令、硬件和访问模式。是否值得显式分块应结合实际流量与执行时间判断。

编译器常用 Register 保存私有操作数与中间结果。寄存器数量有限，用量会约束常驻线程数，压力过大还可能产生 spill（溢出）。Local Memory 虽然按线程私有寻址，却由设备内存支持并可经过缓存。较大的私有数组或编译器溢出的值都可能落到这里。C++ 变量的可见范围和编译器选择的物理存放位置应分别判断。[CUDA 12.8.1 内存空间与访问](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#device-memory-accesses)

### 页锁定主机内存与统一内存

| 机制                                   | 如何获得                                                        | 传输与使用边界                                                                               |
| -------------------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------- |
| Pageable Host Memory（可分页主机内存） | 普通主机分配，例如本章的 `std::vector`                          | 系统可换出页面。CUDA 传输可能需要中转缓冲及额外等待                                          |
| Pinned Host Memory（页锁定主机内存）   | `cudaHostAlloc()` 分配，使用后以 `cudaFreeHost()` 释放          | 页保持驻留，适用于需要页锁定缓冲区的异步 DMA 路径。过量占用会减少系统可分页内存              |
| Unified Memory（统一内存）             | 例如用 `cudaMallocManaged()` 创建托管分配，以 `cudaFree()` 释放 | 主机和设备可按平台规则访问。页面可能缺页、迁移或被远程访问，局部性和同步仍会影响性能与正确性 |

`cudaMemcpyAsync()` 的主机返回行为取决于参数和内存类型。即便使用页锁定内存，要与计算重叠还需设备支持相应的复制并发能力，且操作间无依赖或隐式同步。统一内存的迁移、并发访问等能力取决于设备、操作系统和驱动，可结合 `managedMemory`、`concurrentManagedAccess` 等属性核查。[CUDA 12.8.1 最佳实践的数据传输章节](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-best-practices-guide/index.html#data-transfer-between-host-and-device) · [CUDA 12.8.1 Runtime 内存管理](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__MEMORY.html)

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

### 逐阶段观察数据

| 阶段       | Host 状态                                        | 设备状态                                                                        |
| ---------- | ------------------------------------------------ | ------------------------------------------------------------------------------- |
| 初始化     | A 的 1000 个元素为 1.0f，B 为 2.0f，C 已准备接收 | 尚未分配                                                                        |
| 分配       | A、B 和 C 仍保存在主机                           | 三次 `cudaMalloc` 各分配 `n * sizeof(float)` 字节，内容尚未初始化               |
| H2D        | 输入保留                                         | 两次拷贝分别把 A、B 送到设备，同一默认流中的后续 kernel 可使用输入              |
| 计算并同步 | 主机等待执行完成，C 尚未回传                     | `(1000 + 255) / 256 = 4` 个块共启动 1024 个线程，`i < n` 拦住尾部 24 个越界线程 |
| D2H        | 同步拷贝成功返回后可读取主机 C                   | 设备 C 仍有效                                                                   |
| 校验与释放 | 检查所有 1000 个输出                             | 释放三个分配，避免资源长期占用                                                  |

[第 3 章](/articles/ai-infra-cuda-execution.html)的 Grid、Block 和 Warp 布局在这里决定索引如何覆盖输入。逐元素校验能发现漏写或算错的位置。`1.0f`、`2.0f` 和精确和 `3.0f` 均可由 FP32 精确表示，所以此例可用 `x != 3.0f`。一般浮点算法应结合误差预算使用绝对与相对容差，并明确处理非有限值。

### 在 Linux 上复现

使用 NVIDIA GPU、兼容驱动、CUDA Toolkit 12.8.1 与受支持的宿主 C++ 编译器。将上面程序保存为 `vector_add.cu`。

```bash
nvidia-smi
nvcc --version
nvcc vector_add.cu -o vector_add
./vector_add
```

正常预期输出为 `PASS`。可以分别将常量改为 1、256、1000、1025、10000 后重新编译运行，覆盖单元素、整块、尾块和较大输入。测试空输入时，应在分配及 launch 前检查 `n == 0` 并直接完成空操作，避免零字节分配和零 Block 启动。当前给出的是静态核查及预期结果。

## 3. 分别检查提交与异步执行结果 {#_3-为什么检查两次错误}

launch 返回主要表示工作已提交；执行可能晚于 CPU 继续运行。只在 launch 后调用一次 `cudaGetLastError()`，不能证明设备端计算已经成功。同步点是观察异步错误的重要位置，但它发现的错误也可能由更早的工作引起。[CUDA API 同步语义](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/api-sync-behavior.html)

这里使用简单的同步拷贝，先建立正确性基线。优化时再引入 pinned memory、stream 和分块流水线，每次只改变一个因素，并持续校验结果。[CUDA 最佳实践：内存与数据移动](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-best-practices-guide/index.html)

### 根据出错位置定位

| 现象           | 常见观察位置                         | 排查方法                                                                |
| -------------- | ------------------------------------ | ----------------------------------------------------------------------- |
| 显存分配失败   | `cudaMalloc` 返回失败                | 核对设备、分配字节数和可用显存                                          |
| 启动配置错误   | launch 后的 `cudaGetLastError()`     | 核对 grid、block、共享内存与设备上限                                    |
| 执行中非法访存 | `cudaDeviceSynchronize()` 等后续调用 | 缩小输入，核对索引和指针生命周期，用 Compute Sanitizer 的 memcheck 定位 |
| 结果不符       | 回拷后的逐元素检查                   | 找到第一个错误索引，检查数据、覆盖范围和依赖                            |

`cudaGetLastError()` 读取并清除当前主机线程的 Runtime 错误状态，可能反映更早的异步错误，它本身不等待 kernel。`cudaDeviceSynchronize()` 等待当前设备执行环境中先前提交的工作，`cudaStreamSynchronize(stream)` 只等待指定流及其依赖。同步成功说明所等工作未报告执行错误，算法正确性仍要比较输出。本例的 `CHECK` 在失败时结束整个教学进程。长生命周期组件要保留最初错误，并按实际创建和使用情况清理资源。[CUDA 12.8.1 错误处理](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__ERROR.html)

## 4. 内存范围、同步范围和进度保证要一起写

| 场景           | 通信介质                 | 同步/可见性                     | 进度前提                     |
| -------------- | ------------------------ | ------------------------------- | ---------------------------- |
| 同一普通 block | shared/global 等合法内存 | 正确的 block barrier 或原子协议 | 参与线程合法到达同步点       |
| 不同普通 block | global 等合法内存        | 原子及相应内存顺序，或拆 kernel | 不假定所有 block 同时常驻    |
| 不同 stream    | 有效且可访问的分配       | event 等显式依赖                | 对象活到最后一次使用完成     |
| 不同进程/设备  | IPC、peer 等受支持路径   | 显式共享契约与同步              | 设备、驱动和生命周期条件成立 |

共享数据时，依次确认分配有效、访问被允许、写入对读取方可见，以及通信双方有推进机会。内存范围、同步范围和进度前提共同决定程序能否正确完成。

[第 5 章](/articles/ai-infra-green-context.html)将继续追踪设备分配、代码和 Stream 由哪个 Context 管理，以及最后由谁释放。
