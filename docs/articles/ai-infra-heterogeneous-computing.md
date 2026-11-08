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

异构系统把不同类型的处理器组合起来。CPU（Central Processing Unit，中央处理器）擅长通用操作和复杂控制流。GPU（Graphics Processing Unit，图形处理器）借助大量并行工作获得高吞吐。CPU 同样支持多核、多线程和 SIMD（Single Instruction, Multiple Data，单指令多数据），例如用一条向量指令同时对多组元素做加法。

NPU（Neural Processing Unit，神经网络处理器）专门加速神经网络运算。FPGA（Field-Programmable Gate Array，现场可编程门阵列）允许部署者配置硬件逻辑，例如为固定的数据处理流程构造专用流水线。

离散 GPU 常经 PCIe（Peripheral Component Interconnect Express，外设高速互连标准）连接主机。NVLink 是 NVIDIA 的高速互连，可用于 GPU 间通信，部分系统也用它连接 CPU 和 GPU。集成式系统还可能采用共享物理内存。是否共享地址、是否自动搬运数据，取决于硬件与软件配置。

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

下表使用假设数据，暂不计准备、收尾和阶段重叠。

| 阶段          | 假设耗时 |
| ------------- | -------: |
| H2D           |  0.15 ms |
| Kernel Launch |  0.02 ms |
| GPU 计算      |  0.01 ms |
| D2H           |  0.15 ms |
| 合计          |  0.33 ms |

计算只占约 3%。即使把计算时间降到零，这条串行路径也还要 0.32 ms。把多个小任务合批可以摊薄提交开销，让中间数据驻留显存则可以减少往返搬运。实际流水线存在重叠时，应沿请求的关键路径计时。上面的 Amdahl 推演也假设其余耗时固定，新增搬运或重叠后要重新核算。

### 一次大模型推理请求

下面以典型的自回归大语言模型（Large Language Model，LLM）推理服务为例，假设 CPU 负责服务编排，GPU 执行模型计算。具体框架可把分词、调度和输出处理放在不同进程或设备上。

1. 客户端发送提示词和生成参数。服务端解析请求，CPU 上的分词器执行 Tokenization（分词与编码），把文本拆成模型处理的单位（token），再转换为对应的整数 ID。
2. 调度器根据排队情况、显存预算和已有任务选择本轮参与计算的请求，把它们组织成 Batch（批次），准备 token ID、序列信息及所需的设备缓冲区。
3. GPU 执行 Prefill（预填充），处理输入上下文，建立 KV Cache（键值缓存），保存后续注意力计算可复用的键和值，并为生成首个 token 提供分数。
4. GPU 进入 Decode（逐步解码）。典型路径每步为每条序列生成一个新 token，读取已有 KV Cache 并追加新位置的键和值。调度器可以在迭代间调整批次。
5. 服务端把生成的 token 转回文本，处理停止条件并通过网络返回。流式客户端可逐段接收，非流式客户端在生成结束后接收完整响应。

端到端延迟还包含网络、排队、分词、批次准备和结果处理。GPU 空闲可能源于请求不足，也可能在等 CPU 预处理、调度或数据。模型加载成功只表明具备运行前提，仍需用目标并发和输入输出长度验证吞吐与延迟。预填充、解码及缓存的细节见[第 19 章](/articles/ai-infra-prefill-decode-kv-cache.html)。

## 3. 先分清四种问题

| 层次 | 要回答的问题                   | 常见证据                         |
| ---- | ------------------------------ | -------------------------------- |
| 功能 | GPU 能否被发现、计算结果对不对 | 错误码、最小用例、结果校验       |
| 性能 | 时间消耗在搬运、提交还是计算   | 时间线、kernel 报告、业务延迟    |
| 共享 | 多个任务如何复用一张卡         | MIG、MPS、调度器和限额策略       |
| 服务 | 请求是否达到容量和质量目标     | TTFT、TPOT、吞吐、错误率、质量集 |

TTFT（Time to First Token，首 Token 延迟）衡量从发出请求到收到首个有效输出 token 的时间。TPOT（Time per Output Token，每输出 Token 耗时）在一种常用口径下取首末 token 的接收时间差，再除以输出 token 数减一，因此只输出一个 token 时没有该值。端到端延迟覆盖从发出请求到收到完整输出。比较工具时应确认起止点、空响应或流结束标记的处理以及聚合方式。详见[第 19 章指标解释](/articles/ai-infra-prefill-decode-kv-cache.html#_3-ttft、tpot-和吞吐不是一个数字)及 [NVIDIA NIM Benchmarking LLM 1.0.0 指标文档](https://docs.nvidia.com/nim/benchmarking/llm/1.0.0/metrics)。NVIDIA 已将 1.0.0 标记为 Deprecated，此处引用其历史指标口径。

GPU 利用率只提供设备活动的一部分信息，功能正确性、资源隔离与用户响应还需分别使用对应证据判断。

## 4. 本册的版本边界

CUDA 基础 API 以 [12.8.1 归档编程指南](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html)及上述同版本同步语义、最佳实践文档为机制参考；第 1 节的在线 CUDA 平台页面用于概念说明，不是 12.8.1 归档。

[第 2 章](/articles/ai-infra-gpu-architecture.html)从设备内部继续解释计算吞吐和数据供给。

## 理解检查

- 在 0.33 ms 的假设例中，把 GPU 计算时间减半能节省多少时间？
- 如果首 token 变慢而后续输出速度稳定，可以在哪几个阶段查找新增等待？
