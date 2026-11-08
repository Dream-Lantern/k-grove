---
id: ai-infra-gpu-architecture
title: 第 2 章 GPU 架构：SM、Tensor Core 与资源瓶颈
description: "GPU 的计算吞吐来自执行单元、并行任务与数据供给的配合。理解硬件时，可以先以 SM 为单位观察线程调度、寄存器和共享内存，再分析任务是受计算、访存还是提交开销限制。"
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
order: 2
---

# 第 2 章 GPU 架构：SM、Tensor Core 与资源瓶颈

GPU 的计算吞吐来自执行单元、并行任务与数据供给的配合。理解硬件时，可以先以 SM 为单位观察线程调度、寄存器和共享内存，再分析任务是受计算、访存还是提交开销限制。核心数量提供硬件规模信息，实际利用程度取决于工作负载。

## 1. SM 资源与 CUDA 线程的映射 {#_1-不要把-cuda-线程直接等同于物理核心}

SM（Streaming Multiprocessor，流式多处理器）是 GPU 分配线程块和执行指令的硬件单位。CUDA Thread（线程）是程序中的执行实例。Block（线程块）包含多个线程，整个块分配给一个 SM。SM 可同时容纳多个块，每块按连续线程编号划分为 32 线程一组的 Warp（线程束），不足 32 的尾组只有部分线程有效。CUDA 线程不会独占一个 CUDA Core。

| SM 资源                          | 职责                                                                       |
| -------------------------------- | -------------------------------------------------------------------------- |
| Warp Scheduler（线程束调度器）   | 从可发射的 warp 中选择指令，交给相应执行流水线                             |
| CUDA Core                        | 执行常规算术指令，例如 FP32 加法，整数和不同精度指令的通路与吞吐因架构而异 |
| Tensor Core                      | 执行支持的矩阵乘加指令                                                     |
| Register File（寄存器文件）      | 保存常驻线程的操作数和中间结果                                             |
| Shared Memory（共享内存）        | 保存线程块内可协作访问的数据                                               |
| Load/Store Unit（加载/存储单元） | 执行访存指令，把数据在寄存器与相应存储空间之间移动                         |

Resident Warp（常驻 warp）已分配资源，可能正在等待访存、屏障或前序指令结果。Eligible Warp（就绪 warp）的下一条指令已满足发射条件。调度器从就绪集合选中 warp 并发射指令（Issued Instruction），实际发射能力及各执行单元的吞吐因架构而异。如果某个 warp 在等待数据，调度器可发射另一个就绪 warp 的指令来隐藏延迟。寄存器和共享内存按块占用，再加上 SM 的线程、warp 和块数上限，共同决定能常驻多少块。如果许多常驻 warp 同时卡在访存或同一屏障上，仍可能没有指令可发射。这是一种分析视角，具体指标见 [Nsight Compute 的 Scheduler Statistics](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html)。

[![GPU 资源：计算与数据供给](/assets/notes/ai-infra/gpu-resources.svg)](/assets/notes/ai-infra/gpu-resources.svg)

图中箭头连接负载所依赖的资源类别和相应的性能观察项。具体芯片可按 GPC（Graphics Processing Cluster，图形处理簇）、TPC（Texture Processing Cluster，纹理处理簇）和 SM 等层级组织，图中按职责分类，未展开这些物理层级。各层数量及复制引擎、视频单元、L2 和显存的组织随芯片与 SKU 变化，完整芯片的设计数量也可能高于产品启用数量。执行资源与架构限制见 [CUDA 12.8.1 Hardware Implementation](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#hardware-implementation)。

## 2. 计算、存储与搬运资源的职责 {#_2-三类资源分别解决什么问题}

| 存储资源                  | 作用域与生命周期                                     | 典型职责                             |
| ------------------------- | ---------------------------------------------------- | ------------------------------------ |
| Register（寄存器）        | 线程私有，随线程执行分配                             | 暂存操作数和累加结果                 |
| Shared Memory（共享内存） | 普通用法下由块内线程共享，随块存在                   | 由程序显式组织的数据交换与分块复用   |
| L1 Cache（一级缓存）      | 通常位于 SM 内，缓存行随访问与替换变化               | 为采用相应缓存路径的访问提供局部复用 |
| L2 Cache（二级缓存）      | GPU 内多个 SM 共享，缓存行随访问与替换变化           | 缓存设备内存数据，减少访问显存的流量 |
| HBM/GDDR 显存             | 设备存储，分配的全局缓冲区可跨 kernel 存续，直至释放 | 保存模型权重、输入输出和中间缓冲区   |

缓存容量决定多少工作数据能留在近处，带宽决定单位时间能送达多少数据。访问路径随地址空间、指令和缓存策略变化。寄存器运算可在 SM 内完成，共享内存由程序寻址，全局访存可以采用不同的 L1 缓存策略。Copy Engine（复制引擎）可承担支持路径上的数据传输，算术操作由计算单元执行。

以 FP32 矩阵乘法 `C = A × B` 为例，假设一个块计算 C 的 16 × 16 输出块，本轮沿内积维度推进 16 个元素。每个线程计算一个输出，直接取数时会发起 16 次 A 和 16 次 B 的标量读取，256 个线程合计 8192 次输入读取。分块后，线程协作从全局内存读取 A、B 各 256 个元素，放到共享内存，经块内同步后，每个输入元素可被 16 个线程复用。此轮只需 512 次逻辑全局元素读取，共享内存占 2 KiB，输出累加值可留在寄存器中。进入下一轮覆盖共享数据前还需同步，避免读写冲突。

这是逻辑读取量推演，显存实际流量还取决于缓存命中、访存合并和事务粒度。共享内存分块增加了同步和共享访问开销。块用量过大还会减少同一 SM 可常驻的块数。参见 [CUDA 12.8.1 矩阵乘法与共享内存](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-best-practices-guide/index.html#shared-memory-in-matrix-multiplication-c-ab)。

### Tensor Core 如何做矩阵乘加

对于 `C = A × B`，每个输出是 A 的一行与 B 的一列的点积。常规执行路径可用多条标量乘加指令逐项累加。Tensor Core 支持对一小块矩阵执行乘加（Matrix Multiply-Accumulate，MMA），把结果累加到输出片段。以 Warp Matrix Functions 为例，warp 内线程协作提供输入片段并持有累加片段，多次 MMA 可覆盖较大的矩阵。

| 输入语义 | 指数位 / 显式尾数位 | 工程取舍                                                                                       |
| -------- | ------------------- | ---------------------------------------------------------------------------------------------- |
| FP32     | 8 / 23              | 单精度基线，可走常规 FP32 算术流水线                                                           |
| TF32     | 8 / 10（计算精度）  | 保留 FP32 的指数范围，降低有效精度。用于支持的 Tensor Core 运算，FP32 输入缓冲区无需改为 16 位 |
| FP16     | 5 / 10              | 16 位存储，指数范围比 FP32 窄，更容易溢出或下溢                                                |
| BF16     | 8 / 7               | 16 位存储，指数范围接近 FP32，尾数精度低于 FP16                                                |

FP32 累加可降低累加阶段的舍入误差，输入降精度时丢失的信息无法恢复。以 CUDA 12.8.1 的 Warp Matrix Functions 为例，Volta（Compute Capability 7.0）已有 FP16 矩阵路径，Ampere（8.x）开始支持 BF16 和 TF32。具体输入、累加类型和 tile 形状以目标架构和接口为准。可通过 cuBLAS 选择支持的矩阵计算模式，或用 WMMA（Warp Matrix Multiply-Accumulate）接口显式表达矩阵指令，让编译器为目标架构生成相应代码。普通标量循环不会仅因 GPU 有 Tensor Core 就自动走该路径。输入类型、形状、布局、对齐和库算法会影响可用路径与效率。验证时应同时检查结果精度及实际执行指令。参见 [CUDA 12.8.1 Warp Matrix Functions](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#warp-matrix-functions)。

## 3. 计算密集、带宽密集和提交受限

一次大型矩阵乘法可能主要受矩阵运算吞吐约束；逐元素读取大量数据而只做少量计算，往往更依赖访存带宽。大量很短的 kernel 还可能受 CPU 提交开销影响。这些是待测假设，必须结合时间线和计数器确认。

判断瓶颈时，先确认时间是否真的花在 GPU 上。如果 GPU 正在等待 CPU 预处理，换更快的 GPU 未必有效。如果耗时主要发生在 GPU 内，再检查数据供给、指令效率及并行度，不要盲目增加 block 数。

### 用 Roofline 估计上界

Arithmetic Intensity（算术强度）定义为 `I = FLOPs / Bytes`，即浮点运算次数除以穿过所选存储边界的字节数。简化 Roofline Model（屋顶线性能模型）给出 `P上界 = min(P计算峰值, I × BW)`。其中计算峰值应对应所用精度与指令路径，`BW` 是同一存储边界的带宽，乘积与峰值的单位均为 FLOP/s。

以 FP32 向量加法为例，每个输出读 A 和 B 各 4 字节、写 C 4 字节，完成一次浮点加法。在无缓存复用且只计这三笔有效数据流量的模型中，`I = 1 / 12 FLOP/Byte`。若带宽为假设的 1 TB/s，带宽侧上界约为 83.3 GFLOP/s。矩阵乘法则能让一次读取参与多次乘加，分块复用充分时算术强度更高，可能逐渐接近计算峰值。

低算术强度时带宽侧上界更低，高算术强度时可能碰到计算上界。Roofline 给出理论上界，实际值还受缓存命中、访问合并、提交、同步和指令依赖影响。用显存流量和用 L2 流量得到的强度不同，比较时要标注字节口径。GPU Utilization 仅能反映部分设备活动，定位瓶颈还需结合 CPU/GPU 时间线、访存带宽及指令发射等证据。Tensor Core 理论峰值也无法直接推导模型吞吐。参见 [Nsight Compute Roofline Charts](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html#roofline-charts)。

## 4. 比较硬件要使用相同口径

比较峰值性能必须写明 FP32、TF32、FP16、BF16 等数据类型，以及是否采用结构化稀疏。FLOPs 通常表示浮点运算次数，FLOP/s 才是每秒运算率；厂商表中的“倍数”还依赖基线和工作负载。

选型记录至少需要 GPU 型号、显存、功耗约束、互连、软件版本、输入形状和业务指标。只有固定这些条件，结果才有可比较性。

### 观察本机设备

在装有 NVIDIA 驱动的环境运行：

```sh
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv
nvidia-smi
nvcc --version
```

第一条命令记录 GPU 型号、可见显存总量和驱动版本。第二条输出顶部的 CUDA Version 是驱动支持的 CUDA 版本。第三条记录当前 PATH 选中的 Toolkit 编译器版本，需要安装 Toolkit。对于多卡环境，先确认各工具观察的是同一设备。

有 CUDA Samples 时，可使用 [CUDA Samples v12.8 的 deviceQuery](https://github.com/NVIDIA/cuda-samples/tree/v12.8/Samples/1_Utilities/deviceQuery)。也可以调用 `cudaGetDeviceProperties`，从 `major/minor` 记录 Compute Capability（计算能力），从 `multiProcessorCount` 记录可见 SM 数，从 `totalGlobalMem` 记录设备全局内存字节数。结果随可见设备和配置变化。参见 [nvidia-smi 官方文档](https://docs.nvidia.com/deploy/nvidia-smi/)。

[第 3 章](/articles/ai-infra-cuda-execution.html)会用 Grid、Block 和 Warp 把这些资源约束联系到一次实际的启动配置。

## 理解检查

- SM 上常驻了很多 warp，为什么仍可能没有指令可发射？
- 分块矩阵乘法减少了哪一层的逻辑读取？为什么不能直接拿这个数字当显存流量？
