---
id: ai-infra-green-context
title: 第 5 章 Context、Module 与 Green Context 的边界
description: "理解 CUDA Context 与 Green Context 的资源归属、SM 资源划分和生命周期，区分资源配置与实际性能验证。"
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
order: 5
---

# 第 5 章 Context、Module 与 Green Context 的边界

Context 可以理解为 CUDA 资源和状态的管理环境。一个进程可以使用多张设备，也可以管理多个 context；因此需要明确对象归属和生命周期。

## 1. Runtime API 与 Driver API

Runtime API 常见前缀为 `cuda`，负责较多隐式管理；Driver API 常见前缀为 `cu`，提供更明确的 context 和 module 操作。Runtime 通常使用设备的 primary context。混用两套 API 时，应先明确当前线程使用哪个 context，不要每个组件都自行创建、销毁一套互不知情的环境。[Driver 与 Runtime 的差异](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/driver-vs-runtime-api.html)

[![Context：所有权与当前线程](/assets/notes/ai-infra/context-ownership.png)](/assets/notes/ai-infra/context-ownership.png)

`cuCtxSetCurrent()` 设置的是调用它的宿主线程的当前 context，不是一个“整个 GPU 当前只能选中谁”的全局开关。context 所属、宿主线程当前状态、硬件此刻执行哪个任务，是三个不同问题。[Context API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__CTX.html)

### 设备、上下文与宿主线程

Device 是 CUDA 可见的硬件执行目标。Context 管理该目标上的 CUDA 执行状态、已加载代码及相关资源。Primary Context（主上下文）在进程内按设备共享，Runtime 通常在没有已绑定的 Driver Context 时按需初始化并使用它。Host Thread（宿主线程）是执行 CPU 代码并发起 API 调用的线程，Current Context（当前上下文）是该线程当前绑定的对象。进程可使用多个设备，也可在同一设备管理多个 Context。图中展示绑定和对象归属，Device 与对象的销毁次序由下面的流程补充。

例如主程序持有设备 0 的 Primary Context P，另有一个显式创建的 Context Q。宿主线程 T1 调用 `cuCtxSetCurrent(P)`，T2 调用 `cuCtxSetCurrent(Q)`，两条线程各自看到自己的绑定。T1 改绑或解除绑定并不会改变 T2 的状态，也不会因此取得 Q 的所有权或取消已提交工作。GPU 实际何时执行各自工作仍由调度决定。

### 两套 API 共用执行环境时

Driver API 由应用显式调用 `cuInit(0)` 初始化，并通过 `cuDevicePrimaryCtxRetain()` 持有 Primary Context，或通过 `cuCtxCreate()` 建立自有 Context。Runtime API 负责较多初始化、模块及启动管理。按 12.8.1 的互操作规则，调用线程已有兼容的当前 Driver Context 时，相关 Runtime 调用可以在该 Context 上工作。混用时约定哪一方持有 Context、谁负责设置与恢复当前绑定、哪个组件创建和同步 Stream。引用持有者配对调用 `cuDevicePrimaryCtxRelease()`，显式 Context 则由其所有者最终销毁。共享场景中，组件退出时只清理自己负责的对象。

## 2. Module、Function、Stream 与分配的对象关系 {#_2-module、function、stream-不是同一种对象}

| 对象       | 表示什么             | 需要记录的归属               |
| ---------- | -------------------- | ---------------------------- |
| Context    | CUDA 执行和资源环境  | 设备及生命周期管理者         |
| Module     | 已加载的设备代码     | 加载时的相关 context         |
| Function   | 可启动的设备函数句柄 | 所属代码及有效生命周期       |
| Stream     | 有顺序约束的工作队列 | 创建环境和使用约束           |
| Allocation | 已分配的内存         | 分配方式、可访问方和释放时机 |

PTX 是中间表示，cubin 是面向相应 GPU 架构的设备二进制。fat binary 可以携带多个目标版本。不能由“文件里有 PTX”推断任何驱动都能 JIT 它；兼容性仍受驱动和 PTX 版本约束。

跨进程通信也不是只能复制回 CPU。CUDA IPC、外部内存、设备间访问等提供特定能力，但需要满足设备、句柄、安全和生命周期条件。初学示例默认各进程管理自己的分配，不依赖隐式共享。

### 从设备代码到一次提交

1. 初始化 Driver，选定 `CUdevice`。持有目标设备的 Primary Context 或创建自有 Context，将其绑定为当前 Context。
2. 用 `cuModuleLoad()` 加载设备代码，得到 `CUmodule`。用 `cuModuleGetFunction()` 按符号取出 `CUfunction`，供后续 kernel launch 使用。PTX（Parallel Thread Execution）是可由驱动 JIT 编译的中间表示，cubin 是针对目标架构的设备二进制，fat binary 可携带多个目标代码版本。
3. 用 `cuStreamCreate()` 创建有序提交队列，用 `cuMemAlloc()` 准备设备输入输出。把准备好的设备指针作为参数交给 `cuLaunchKernel()`，明确指定该流。
4. 在相应流上等待工作完成，回读并校验。确认所有使用者均已完成后，释放分配、销毁流并卸载 Module，恢复线程绑定，最后按持有方式释放或销毁 Context。

Module 卸载或 Context 销毁后，旧 Function 句柄失效。异步提交返回时 GPU 仍可能读写参数指向的内存，不能用返回时间推断何时可释放。如果另一组件重置共享 Primary Context，仍存活的流、分配或模块也可能随之失效。[CUDA 12.8.1 Driver API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/index.html)

## 3. Green Context 的 SM 资源划分流程 {#_3-green-context-不是更轻但仍随便抢全卡}

以 CUDA 12.8.1 文档为准，Green Context 可以把所支持的 SM 资源集合划分并提供给特定执行环境。逻辑步骤是查询资源 → 划分 SM 资源 → 生成描述符 → 创建 green context，再按 API 契约创建或使用相关 stream。

Green Context 与 MIG 提供不同层次的资源能力。解释其保证时，应分别核对 SM 划分粒度、最小数量、并发进展条件与其他 context 的关系；显存控制器、带宽和故障域的隔离还需按目标架构与 API 限制单独判断。[Green Contexts，CUDA 12.8.1](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__GREEN__CONTEXTS.html)

### 按 12.8.1 Driver API 划分并使用资源

以下是 64 位平台的教学流程。每一步检查 `CUresult`，失败后根据已成功创建的对象清理。

| 步骤                                                                | 输入与输出                                                                                        | 失败条件与生命周期                                                                                                                                                                     |
| ------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `cuDeviceGetDevResource(dev, &input, CU_DEV_RESOURCE_TYPE_SM)`      | 已初始化 Driver 和有效设备，返回 SM 资源结构                                                      | 设备、类型或参数不合法时停止                                                                                                                                                           |
| `cuDevSmResourceSplitByCount()`                                     | 传入 SM 集合、`minCount` 和 flags。可先以空 `result` 查询组数，再提供数组。返回实际组数和可选余量 | 请求必须在输入资源范围内，实际分组受粒度和簇能力限制。余量的性质可能与对称组不同                                                                                                       |
| `cuDevResourceGenerateDesc()`                                       | 将选定集合及其数量打包成不透明 `CUdevResourceDesc`                                                | 检查资源来自同一设备。多个 SM 集合须满足同一次划分等组合约束。描述符用于创建，生成它还没有配置执行环境                                                                                 |
| `cuGreenCtxCreate(&green, desc, dev, CU_GREEN_CTX_DEFAULT_STREAM)`  | 用描述符创建 `CUgreenCtx`，同时持有设备的 Primary Context                                         | 可能遇到不支持或资源不足。调用不会自动设为当前 Context。需要当前绑定时先用 `cuCtxFromGreenCtx()` 取得兼容的 `CUcontext`，再设置或压入，且同一 Green Context 一次只能在一个线程上为当前 |
| `cuGreenCtxStreamCreate(&stream, green, CU_STREAM_NON_BLOCKING, 0)` | 在显式指定的 Green Context 中建流，优先级 0                                                       | 忽略调用线程的当前绑定。失效 Context、错误参数或资源不足可导致失败                                                                                                                     |
| 执行、同步和销毁                                                    | 在正确 Context 中准备有效的 Module、Function 和分配，向关联流提交并回读校验                       | 停止提交并等待最后使用后，释放应用对象、销毁流、恢复原绑定，再调用 `cuGreenCtxDestroy()`。它释放资源配置及创建时持有的 Primary Context 引用                                            |

例如，假设一个计算能力 9.0 的设备在默认划分下可提供足够资源，`minCount=10` 不是要求每组精确为 10。按该版本文档的架构指南，9.0+ 默认粒度按 8 对齐，因此返回的对称组可能为 16 SM。实际以 API 返回的组数、各组的 `sm.smCount` 和创建后 `cuGreenCtxGetDevResource()` 的结果为准。细粒度划分 flag 可以放宽对齐，但可能损失大型 Cluster 等能力。

### 隔离与并发的边界

| 机制                         | 主要目的                   | 资源控制与隔离                                                          |
| ---------------------------- | -------------------------- | ----------------------------------------------------------------------- |
| CUDA Stream                  | 表达顺序和依赖             | 在执行环境内组织工作，流本身不提供资源隔离                              |
| Green Context                | 约束执行可用的 SM 集合     | 支持架构上的 SM 配置，无显存容量、显存带宽或完整故障隔离保证            |
| MPS（Multi-Process Service） | 多进程共享与执行控制       | 依架构和配置限制客户端执行资源，共享设备上的其他资源                    |
| MIG（Multi-Instance GPU）    | 在支持的设备上建立硬件分区 | 实例拥有配置所定义的计算与内存资源，仍依具体 GPU 和实例配置判断隔离范围 |

同一次 split 的对称 SM 集合可以互不相交，但 API 不保证独占这些 SM，也不保证 kernel 并发或前进。硬件工作队列连接等共享资源可能造成依赖。12.8.1 文档还列出扩大实际可用 SM 的例外，包括 Volta 及之后使用 MPS 活跃线程百分比时的扩展，以及 9.x 上加载含动态并行的模块后可能额外共享 2 个 SM。显存流量、功耗或故障影响应另行验证。[CUDA 12.8.1 Green Contexts](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__GREEN__CONTEXTS.html)

### 后续版本

CUDA 13.1.0 的 Runtime 文档列出了 Execution Context Management，包括 `cudaGreenCtxCreate()` 和 `cudaExecutionCtxStreamCreate()`。它们以 Runtime 的执行上下文句柄表达资源及流归属。该版本也文档化了工作队列（workqueue）配置，这项能力不在 12.8.1 的 SM 资源划分流程内。本章的 `CUgreenCtx` 流程采用 CUDA 12.8.1 Driver API。[CUDA 13.1.0 Execution Context Management](https://docs.nvidia.com/cuda/archive/13.1.0/cuda-runtime-api/group__CUDART__EXECUTION__CONTEXT.html)

## 4. 工程上先写清所有权

插件式程序尤其需要明确：谁初始化设备、谁持有 primary context、谁创建 stream，以及谁负责最终同步和销毁。不要让一个插件调用 reset，销毁其他插件仍在使用的环境。排查 invalid context 或失效句柄时，沿“创建线程—当前 context—传递对象—销毁时机”追踪。

### 插件 A 退出时，插件 B 仍在运行

主程序初始化并持有共享 Primary Context。A 持有模型、私有缓冲区和推理流，B 持有另一个流并提交独立计算。A 退出时先停止新请求并等待自己的任务结束。如果 B 还会使用 A 的输出，应等待最后一个消费者完成，再释放该分配。A 随后释放自己的分配、卸载私有代码并销毁自己的流。B 可以继续执行。主程序等所有组件退出后再释放 Context。若同步报告执行错误，记录首个错误，由主程序根据错误和上下文健康状态决定恢复范围。插件不自行调用 `cudaDeviceReset()` 或重置共享 Primary Context。

### 怎么验证 Green Context

1. **配置**：记录 GPU、计算能力、驱动与 Toolkit、划分 flags、请求最小值及返回资源。检查每次 `CUresult`，创建后回查 SM 数和流关联。
2. **功能**：在各关联流上提交已知输入的 kernel，分别等待并逐元素核对输出。
3. **并发**：提交两个没有数据依赖的任务，用 GPU 时间线检查执行区间有无重叠。只看主机提交时间无法判定。
4. **干扰**：分别测独跑和同跑，在固定输入、预热、采样方式和资源配置下比较延迟、吞吐，并记录显存压力及功耗。配置成功、功能正确、执行重叠与性能隔离分别判定。

[第 6 章](/articles/ai-infra-streams-events.html)继续说明 Stream 和 Event 如何表达对象的最后使用时机及跨流依赖。
