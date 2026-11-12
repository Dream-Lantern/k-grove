---
id: ai-infra-cuda-execution
title: 第 3 章 CUDA 执行模型：Grid、Block、Warp 与同步
description: "CUDA 程序通过 Grid、Block 和线程组织并行工作。一次 launch 定义任务布局，硬件将线程块分配到 SM，再以 warp 等粒度推进指令。"
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

CUDA 程序通过 Grid、Block 和线程组织并行工作。一次 launch 定义任务布局，硬件将线程块分配到 SM，再以 warp 等粒度推进指令。本章沿这条路径解释同步范围、资源占用和数据覆盖。

## 1. 从一次 kernel launch 看层次

一次普通 kernel launch 定义一个 grid；grid 包含多个 block，block 包含线程。线程用 `threadIdx`、`blockIdx`、`blockDim` 定位自己的工作。一维数组常用 `i = blockIdx.x * blockDim.x + threadIdx.x` 得到全局索引。

[![CUDA：Grid/Block/SM映射关系](/assets/notes/ai-infra/cuda-hierarchy.png)](/assets/notes/ai-infra/cuda-hierarchy.png)

图中的块编号和箭头示意一种分配结果。SM 会从已常驻的 warp 中调度指令，同一 SM 上的块可以同时常驻，图中的“按时间片顺序执行”可理解为资源不足时部分块分批执行。图中 Thread 方格表示逻辑线程，Warp 的 32 线程分组见第 2 节。

普通线程块整体被分配到某个 SM 上执行；同一 SM 可以容纳多个 block，数量受寄存器、共享内存和架构上限约束。block 的执行先后不可假定，更不能依赖“block 0 必须先完成”。支持 thread block cluster 的新架构还有额外协作机制，不能倒推为所有 GPU 都支持。

### 一维索引推演

设数组长度 `N = 1000`，每块 `blockDim.x = 256`，启动 `gridDim.x = ceil(1000 / 256) = 4` 个块。每块有 8 个 warp，整个 grid 定义了 1024 个逻辑线程。实际可同时执行多少工作由设备资源和调度决定。

| blockIdx.x | threadIdx.x | 全局索引 i | 有效索引 |
| ---------: | ----------- | ---------- | -------- |
|          0 | 0–255       | 0–255      | 0–255    |
|          1 | 0–255       | 256–511    | 256–511  |
|          2 | 0–255       | 512–767    | 512–767  |
|          3 | 0–255       | 768–1023   | 768–999  |

最后一个块中，`threadIdx.x = 232–255` 的 24 个线程对应索引 1000–1023。普通逐元素 kernel 必须在读写前检查 `i < N`，否则这些线程会访问数组之外的地址。

## 2. Warp 是 32 个线程的执行组织

在本册讨论的 NVIDIA CUDA 架构中，一个 warp 包含 32 个线程。SIMT 允许线程按各自数据执行相同程序。分支条件在 warp 内不一致时，会产生发散并可能降低执行效率。

从 Volta 起还需要考虑 Independent Thread Scheduling。不要假设 warp 内线程始终隐式同步；涉及 warp 内共享数据时使用正确的掩码、同步或原语。`__syncthreads()` 是线程块范围的屏障，要求该块需要参与的线程以合法方式到达，不能放在仅部分线程会进入的分支中。[CUDA 编程模型与硬件实现，12.8.1](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html)

### 案例 A：同一 Warp 走不同分支

假设一个 warp 的 32 个线程都活跃，前 16 个执行 A，后 16 个执行 B，且编译后保留了两条分支路径。执行某条路径的指令时，只有参与该路径的线程执行有效工作，可能降低每条指令的有效吞吐。如果分支在整个 warp 内一致，或编译器用谓词指令消除了分支，成本会不同。

Volta（计算能力 7.0）起的 Independent Thread Scheduling（独立线程调度）维护每线程执行状态，并可把同一 warp 内可运行的线程组织成 SIMT 执行组。分支中的线程可以在更细粒度上推进，仍共享 warp 的发射与执行资源。依赖线程间数据可见性或会合时，应使用符合参与规则的同步原语。参见 [CUDA 12.8.1 SIMT Architecture](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#simt-architecture)。

### 案例 B：把块屏障放在非一致分支内

下面的错误片段假定一维块启动多个线程，只有线程 0 到达屏障，其他线程会绕过它。这样的条件式屏障可能挂起或产生意外结果。

```cpp
if (threadIdx.x == 0) {
  shared_value = 42;
  __syncthreads();  // 错误：块内条件不一致
}
```

对于一维块，将写入限定在线程 0，让所有线程执行同一屏障，再读取共享值：

```cpp
__shared__ int shared_value;
if (threadIdx.x == 0) {
  shared_value = 42;
}
__syncthreads();
int value = shared_value;
```

## 3. 从常驻到就绪与指令发射 {#_3-常驻不等于每周期都执行}

常驻 warp 会占用相应硬件资源，但也可能正在等待数据或依赖；只有满足发射条件的 warp 才有机会被调度器选中。本章用“等待—就绪—选中”说明延迟隐藏。

程序正确性应建立在公开同步与执行契约上，不能依赖某种未明确保证的 warp 调度偏好。资源占用高时，所有常驻 warp 仍可能等待同类依赖，因此吞吐需要结合就绪工作和瓶颈观察。

## 4. 跨 Block 通信与进度前提 {#_4-block-之间能否通信}

可以通过合法的全局内存、原子操作或相应协作机制交换数据，但普通 kernel 内不存在一个随手可用的全 grid 屏障。简单地让一个 block 自旋等待另一个尚未被调度的 block，可能死锁。

入门时，最稳妥的设计是将不同阶段拆成多个 kernel，在同一 stream 中按序执行；需要跨块协作时，再研究 cooperative launch、cluster 等条件。先确认算法正确，再判断多一次提交是否确实造成了瓶颈。

### 案例 C：跨 Block 自旋等待

假设同一次普通启动里，Block A 占着 SM 资源，自旋等待 Block B 写入标志。如果许多 A 类块填满所有可常驻槽位，尚未启动的 B 就无法获得资源。即使标志使用了正确的原子与内存序，A 等 B、B 等资源的循环仍可能造成死锁。

例如先提交产生数据的 `produce<<<grid, block, 0, stream>>>(...)`，再提交消费数据的 `consume<<<grid, block, 0, stream>>>(...)`。同一 Stream（流）中的消费者在生产者完成后执行，消除了同一 grid 内对未调度块的等待。

需要在一次启动内全 grid 同步时，可查询 `cudaDevAttrCooperativeLaunch`，使用 `cudaLaunchCooperativeKernel` 启动，并将 grid 限制在该 kernel 能同时常驻的规模内，所有参与线程按约定调用 `grid.sync()`。Thread Block Cluster（线程块簇）需要计算能力 9.0 或以上及设备支持的簇配置，簇内块协同调度，可使用簇级屏障，范围仅限该簇。参见 [CUDA 12.8.1 Cooperative Groups](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#cooperative-groups)和[线程块簇](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#thread-block-clusters)。

## 5. 线程块大小的选择

128、256 等只是常见试验点，不是最优定律。用 occupancy API 得到候选值后，还要看访问合并、寄存器压力、尾部浪费和端到端时间。如果为了限制 grid 大小而只启动少量 block，kernel 必须采用 grid-stride loop 等方式覆盖全部数据，不能漏算剩余元素。

### 从资源预算算 Occupancy

Occupancy（占用率）是一个 SM 上活跃（常驻）warp 数与其支持的最大活跃 warp 数之比。理论值由每块线程数、寄存器和共享内存用量，以及 SM 的最大线程数、warp 数和常驻块数共同限制。计算时还要考虑寄存器和共享内存的分配粒度与架构限制。

假设教学设备每个 SM 最多容纳 2048 线程、64 warp、16 块，有 64 KiB 可供块使用的共享内存。kernel 每块 256 线程（8 warp），每块实际占用 20 KiB 共享内存，并假设按硬件规则完成分配后，寄存器预算允许至少 4 块常驻。这时共享内存只允许 3 块，线程和 warp 上限均允许 8 块，因此理论占用率为 `3 × 8 / 64 = 37.5%`。这些是假设资源，实际设备还要检查每块上限、保留资源和分配粒度。

- `cudaOccupancyMaxActiveBlocksPerMultiprocessor` 根据 kernel、块大小和每块动态共享内存，预测每个 SM 的最大常驻块数。
- `cudaOccupancyMaxPotentialBlockSize` 按理论占用率给出候选块大小和达到该占用率所需的最小 grid 大小。

**高 Occupancy 不一定意味着高性能。** 例如为提高占用率而限制寄存器，可能导致寄存器溢出到 local memory，增加访存。结合延迟、指令发射和数据访问实测选择配置。参见 [CUDA 12.8.1 Occupancy API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__OCCUPANCY.html)。

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

### 用第 4 章的主程序验证覆盖

复用[第 4 章的完整向量加法程序](/articles/ai-infra-cuda-memory.html)，把 `add` 定义替换为上面的 `add_stride`，将原 `main` 改为 `int run_case(int n)`，删除原有的 `const int n = 1000;`，并在任何分配前加入 `if (n == 0) return 0;`。将启动行替换为 `add_stride<<<4, 256>>>(da, db, dc, n);`。在启动前加上 `CHECK(cudaMemset(dc, 0, bytes));`，以便逐元素校验捕获未写入的结果。保留原程序的错误检查、同步、回拷、逐元素比较及释放，再添加：

```cpp
int main() {
  const int sizes[] = {0, 1, 1024, 1025, 10000};
  for (int n : sizes) {
    std::printf("N=%d\n", n);
    if (run_case(n) != 0) return 1;
  }
  return 0;
}
```

|     N | 预期验证                  |
| ----: | ------------------------- |
|     0 | 跳过分配与启动，成功返回  |
|     1 | 只有线程 0 写入，结果为 3 |
|  1024 | 每个线程写一次            |
|  1025 | 线程 0 多写索引 1024      |
| 10000 | 全部元素覆盖，多轮推进    |

对于 `N=10000`，因为 `10000 = 9 × 1024 + 784`，前 784 个线程各处理 10 个元素，其余 240 个各处理 9 个，共覆盖 10000 个元素。对任意有效索引除以 1024，余数唯一确定起始线程，商确定循环轮次。循环条件约束每次访问小于 `n`。

在安装 CUDA Toolkit 12.8.1、兼容驱动、NVIDIA GPU 和宿主 C++ 工具链的环境中，将合并后的代码保存为 `vector_add_stride.cu`。以下以类 Unix 终端为例，必要时用 `-arch=sm_XX` 指定 Toolkit 支持的目标计算能力：

```sh
nvcc vector_add_stride.cu -o vector_add_stride
./vector_add_stride
compute-sanitizer --tool memcheck --error-exitcode 1 ./vector_add_stride
```

Windows 终端运行对应的 `vector_add_stride.exe`。预期空输入直接通过，其余用例均输出 `PASS`，进程返回 0，memcheck 无设备内存访问错误。即时启动错误由 `cudaGetLastError()` 检查，异步执行错误由 `cudaDeviceSynchronize()` 检查，回拷后逐元素验证。这里给出的是静态推演与预期结果。

## 7. 函数限定符说的是调用与执行语义

| 限定符       | 常见含义                      | 不应理解为                      |
| ------------ | ----------------------------- | ------------------------------- |
| `__host__`   | host 端函数                   | 源码存放在 CPU 内               |
| `__device__` | device 端函数，由设备代码调用 | host 可以像普通函数一样直接调用 |
| `__global__` | device 执行的 kernel 入口     | 所有场景都只能由 host 发起      |

设备端 kernel launch 属于动态并行，须核对架构、Toolkit 与链接要求。它与设备堆上的 `malloc`，以及 host 端 `cudaMalloc` 是不同机制。[CUDA 12.8.1 编译与链接说明](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-compiler-driver-nvcc/index.html)

下面是调用关系片段。主机调用普通 host 函数，用启动语法提交 kernel。运行在设备上的 kernel 再调用 device 函数。

```cpp
__host__ int threads_per_block() { return 256; }
__device__ float twice(float x) { return x + x; }

__global__ void transform(float* result) {
  result[threadIdx.x] = twice(float(threadIdx.x));
}

void launch(float* device_result) {
  // device_result 指向至少 256 个 float 的设备缓冲区。
  transform<<<1, threads_per_block()>>>(device_result);
}
```

省略限定符的普通函数默认为 host 函数。设备端启动子 kernel 属于 CUDA Dynamic Parallelism（动态并行），在 CUDA 12.8.1 中应核对 Toolkit 支持的目标架构，按设备运行时要求启用可重定位设备代码并链接设备运行时。CUDA 12.0 起默认采用 CDP2，计算能力 9.0 及以上使用 CDP2。旧版设备侧 `cudaDeviceSynchronize()` 规则不能直接套用。详见 [CUDA 12.8.1 Dynamic Parallelism](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#cuda-dynamic-parallelism)。

## 理解检查

- 若最后一个块有线程越过数组末尾，应该怎样保护访存，同时确保块屏障合法？
- 为什么原子标志能处理一部分通信问题，却不能保证另一个块得到调度？
- 启动 1024 个线程时，索引 1024 和 9999 分别由哪个线程在第几轮处理？
