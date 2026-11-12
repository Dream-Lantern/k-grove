---
id: ai-infra-hami-core
title: 第 17 章 HAMi-core：显存限额、算力控制和安全边界
description: "从调用拦截、共享配额记录和分配检查理解 HAMi-core 的显存管理，并说明算力控制与 CUDA Graph 的验证条件。"
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
order: 17
---

# 第 17 章 HAMi-core：显存限额、算力控制和安全边界

## 1. 从分配请求到配额检查与真实调用 {#_1-一次分配如何经过控制层}

在受支持且已被正确注入的调用路径上，控制层检查并维护分配记录；超过相应配额时返回分配失败，允许时再调用真实驱动路径。多个进程需要共享和协调配额记录，不能只按一个 Python 进程的局部计数判断总用量。

这不是“应用独占整卡但用不满”，其他受管理任务仍可能共享物理设备。显存限额与硬件切片的机制不同，不应混用术语。[HAMi-core 项目说明](https://github.com/Project-HAMi/HAMi-core)

### 固定源码与加载路径

HAMi v2.10.0 的 `libvgpu` Git 子模块固定为 [`b216ba1be1b8e21488d1c7370ed3357b3049aad1`](https://github.com/Project-HAMi/HAMi-core/commit/b216ba1be1b8e21488d1c7370ed3357b3049aad1)，镜像构建文件从该目录构建并打包 `libvgpu.so`。下文分析该源码。实际集群镜像仍应记录 digest 和库哈希。后面的 main 对照单列，不能反推发布版行为。[HAMi v2.10.0 发布树](https://github.com/Project-HAMi/HAMi/tree/v2.10.0) · [镜像构建文件](https://github.com/Project-HAMi/HAMi/blob/v2.10.0/docker/Dockerfile)

第 16 章的插件挂载 `/etc/ld.so.preload` 与 `libvgpu.so`。`LD_PRELOAD` 是进程环境变量，和系统预加载文件是不同入口。以普通显存分配为例，应用可调用 Runtime `cudaMalloc()` 或直接调用 Driver API。只有实际解析到 `libvgpu.so` 中受控 Driver 符号时，才会执行检查与记账，再通过真实驱动符号返回。源码用真实 `dlsym()` 解析驱动入口，并包装 `cuGetProcAddress()` 及其 v2 版本，按版本与符号查找包装函数，未匹配则交给驱动。直接 Driver 调用、显式符号句柄、不同加载命名空间及新符号都应按实际解析路径验证。[固定提交 hook.c](https://github.com/Project-HAMi/HAMi-core/blob/b216ba1be1b8e21488d1c7370ed3357b3049aad1/src/cuda/hook.c) · [固定提交 memory.c](https://github.com/Project-HAMi/HAMi-core/blob/b216ba1be1b8e21488d1c7370ed3357b3049aad1/src/cuda/memory.c)

## 2. 提交节奏、资源限制与业务性能 {#_2-算力限制不等于精确吞吐控制}

典型软件控制通过调节提交节奏等方式影响资源使用，具体算法需定位到对应 tag 和调用路径。`grids × blocks` 估算、sleep、超时与函数位置都需要结合该版本实现解释。

即使配额值为 50，也不能保证业务性能恰好是独占时的一半。kernel 长短、CUDA Graphs、并发提交和底层共享资源都可能影响控制效果与实际观测，会有轻微的误差。

该提交的 `cuLaunchKernel` 和 `cuLaunchKernelEx` 在 PID 关联成功时进入 `rate_limiter`。传参包含 Grid 三维乘积（块数）和 Block 三维乘积（每块线程数），但限速函数实际只用 Grid 块数扣减预算。预算为进程内的每设备变量，用 CAS（Compare-And-Swap，比较并交换）更新。余额为负时每次等约 10 ms 重查，达到可提交条件后才调用真实驱动。限制关闭、配置为 0 或达到 100 的路径会跳过相应节流。

监控线程约每 120 ms 查询 NVML 进程采样，并按共享区域记录的宿主 PID 聚合 SM 活动，用实际活动相对目标值调整补充量。代码向 NVML 提供约一秒前的查询起点，实际样本可用性仍取决于驱动。这个控制回路调节后续提交节奏，无法撤回已进入队列的长 kernel。相同 Grid 可对应完全不同的运行时间，多进程还有各自的预算和共享采样反馈，因此可能短时超调或引入排队延迟。这里的周期是固定提交的配置值，实测时间可能受调度影响。[限速与采样源码](https://github.com/Project-HAMi/HAMi-core/blob/b216ba1be1b8e21488d1c7370ed3357b3049aad1/src/multiprocess/multiprocess_utilization_watcher.c) · [周期常量](https://github.com/Project-HAMi/HAMi-core/blob/b216ba1be1b8e21488d1c7370ed3357b3049aad1/src/multiprocess/multiprocess_utilization_watcher.h)

## 3. 三种视图需要分别观察

| 视图                   | 可能看到什么               | 验证目的               |
| ---------------------- | -------------------------- | ---------------------- |
| 容器内 CUDA 查询       | 受管理的可见资源或配额     | 应用得到的契约是否一致 |
| 容器内 NVML/nvidia-smi | 受注入和工具路径影响的视图 | 工具是否正确关联该任务 |
| 宿主侧监控             | 物理卡及实体的状态         | 实际占用与全局剩余量   |

观察时分别记录逻辑资源视图与物理资源视图，并检查容器内工具实际加载的库。工具和调用路径不同，看到的配额或设备状态也可能不同，应按实际注入范围解释。

## 4. 软件控制层不是完整的对抗性安全边界

拦截覆盖面、动态库解析、静态调用路径、新 CUDA API、Graph 回放以及容器权限，都会影响控制是否生效。调度器分配了配额，并不自动证明应用无法绕过。

## 5. 最小验收矩阵

分别验证单进程/多进程、分配/释放/失败、异步内存池、普通 launch/Graph、异常退出/进程重启，并对比宿主与容器视图。验收时应检查“超额时发生什么”和“退出后配额是否恢复”，不能只看某次查询显示的总量。未验证的 API 路径应明确列为限制。原记录报告：在 SGLang、vLLM 开启 CUDA Graph 的实验中，HAMi-core 未实现预期算力限制。记录未固定版本与负载条件，复用该现象前需补齐环境信息。

### Graph Replay 的专项结论

[HAMi #1445](https://github.com/Project-HAMi/HAMi/issues/1445) 的报告环境为 v2.7.0、驱动 570.86.10，驱动显示 CUDA 12.8。复现代码用向量加法捕获并重复 `cudaGraphLaunch`，报告者观察到回放走 `cuGraphLaunch` 而没有经过 `cuLaunchKernel`。Issue 后因清理长期无更新事项关闭。原有 SGLang/vLLM 观察属于另一个未固定环境的历史记录。

v2.10.0 固定提交的符号表和 `graph.c` 都含 `cuGraphLaunch`，但 wrapper 只转发真实驱动，不调用 `rate_limiter`。符号查找的通用分支还明确跳过 `cuGraph*`。核对的 [main 快照 `17212525d27a`](https://github.com/Project-HAMi/HAMi-core/commit/17212525d27ac156955ab940c5d51df33d9e0d09) 中，`cuGraphLaunch` 仍直接转发。main 增加了设备型 Graph 分配节点的预留、创建失败回滚与图记录，并为捕获中的异步分配走图记账路径。相关测试覆盖分配和生命周期，不能验证回放的算力上限。[main Graph 内存入口](https://github.com/Project-HAMi/HAMi-core/blob/17212525d27ac156955ab940c5d51df33d9e0d09/src/cuda/memory.c) · [main 捕获分配源码](https://github.com/Project-HAMi/HAMi-core/blob/17212525d27ac156955ab940c5d51df33d9e0d09/src/allocator/allocator.c)分别记录入口命中、图运行正确、图内存记账和 replay 算力限制。前一项成立无法证明后一项。[发布版 graph.c](https://github.com/Project-HAMi/HAMi-core/blob/b216ba1be1b8e21488d1c7370ed3357b3049aad1/src/cuda/graph.c) · [main graph.c](https://github.com/Project-HAMi/HAMi-core/blob/17212525d27ac156955ab940c5d51df33d9e0d09/src/cuda/graph.c) · [Graph 内存节点测试](https://github.com/Project-HAMi/HAMi-core/blob/17212525d27ac156955ab940c5d51df33d9e0d09/test/test_graph_alloc_node.c) · [异步捕获测试](https://github.com/Project-HAMi/HAMi-core/blob/17212525d27ac156955ab940c5d51df33d9e0d09/test/test_alloc_async_capture.c)

## 6. 记账设计要覆盖请求大小、预留与回滚

[![HAMi 显存配额：原子检查与预留](/assets/notes/ai-infra/hami-allocation-ledger.svg)](/assets/notes/ai-infra/hami-allocation-ledger.svg)

| 不变量/事件                              | 验收问题                                     |
| ---------------------------------------- | -------------------------------------------- |
| `used + reserved + requested` 与限额关系 | 单位、溢出、粒度和并发准入如何处理           |
| 真实分配失败                             | 预留能否按原请求撤回，是否遗留占额           |
| free / async free                        | 按什么逻辑时点释放配额，和物理内存池是否分开 |
| 进程异常退出                             | 谁检测失效记录，如何防止误清其他进程         |
| VMM/Graph/新入口                         | 是支持、拒绝还是未观测，不可默认为已覆盖     |

查设备总量时，`cuDeviceTotalMem` 是独立 API；`cuDeviceGetAttribute` 是设备属性查询。[CUDA 12.8.1 Device Management](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__DEVICE.html)

### 4096 MiB 下的并发推演

A 已用 2048 MiB，B 请求 1536 MiB，C 同时请求 1024 MiB。若各自先读到 2048，二者都可通过单次检查，最终会达到 4608 MiB。图中的设计不变量为 `used + reserved + requested <= limit`。若 B 先原子预留，则 C 只看到 512 MiB 余量，应拒绝。真实驱动失败时撤回预留，释放时按实际生命周期回收。异常退出还需识别失效进程和清理账本。

固定提交的同步路径采用**前检 → 真实分配 → 进程内 mutex 下复检并记账**。真实分配失败时未加入记录，复检拒绝时调用驱动 free 并返回 OOM。共享区域按进程槽记录设备用量，更新采用原子操作和序列计数。进程内锁与共享用量原子更新并没有把多个进程的检查及更新合成一个事务，源码也没有图中独立的全局 `reserved` 字段。因此上述竞争仍是需要联合验证的风险。同步释放先从跟踪和账本扣除，再调用实际释放，不能据此保证驱动失败会恢复账本。退出清理标记槽位，后续清扫会处理死亡进程，需验证何时重新可分配。[固定提交 allocator.c](https://github.com/Project-HAMi/HAMi-core/blob/b216ba1be1b8e21488d1c7370ed3357b3049aad1/src/allocator/allocator.c) · [共享区域记账与清扫](https://github.com/Project-HAMi/HAMi-core/blob/b216ba1be1b8e21488d1c7370ed3357b3049aad1/src/multiprocess/multiprocess_memory_limit.c)

### 内存 API 覆盖矩阵

以下状态是固定提交的静态结论。PARTIAL 表示能追踪部分入口，但生命周期、错误或底层解析有缺口。NOT VERIFIED 表示必须确认实际运行入口。两个指定 Graph/捕获测试文件在固定提交路径未找到，仅在上述 main 快照中核对。

| API                                                     | 状态                    | 固定提交证据与验证点                                                                                              |
| ------------------------------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `cudaMalloc` / `cuMemAlloc_v2`                          | NOT VERIFIED / PARTIAL  | Runtime 到 Driver 的路径要现场核实。Driver wrapper 有前检、复检、回滚和指针记录，同步 free 的失败与跨进程准入另测 |
| `cudaMallocManaged` / `cuMemAllocManaged`               | NOT VERIFIED / PARTIAL  | Driver 有前检，成功后调用 `add_chunk_only`，未检查它的失败返回。逻辑记录与 Unified Memory 实际驻留分开            |
| `cudaMallocAsync` / `cuMemAllocAsync`、Pool Async       | NOT VERIFIED / PARTIAL  | Driver 前检后调用分配，按池的 reserved high-water 差额跟踪。驱动成功后查询池失败时未见配对回滚，捕获与多池另测    |
| `cudaFreeAsync` / `cuMemFreeAsync`                      | NOT VERIFIED / PARTIAL  | 已跟踪项在主机调用路径中扣账，未等待设备到达释放点，且该分支未传播底层 free 的返回状态                            |
| `cuMemCreate` / `cuMemRelease`                          | PARTIAL                 | 设备位置分配前检并跟踪 handle，Release 成功后删记录。记账失败和引用仍被映射时另验                                 |
| VMM（Virtual Memory Management，虚拟内存管理）Map/Unmap | UNSUPPORTED（映射配额） | `cuMemMap` 转发，未见完整的 Map/Unmap 引用记账，导入可共享 handle 也走转发                                        |
| CUDA Graph Memory Nodes                                 | NOT VERIFIED            | 固定提交没有核实独立节点的准入与回收控制。main 文件存在不构成发布版证据                                           |
| IPC（Inter-Process Communication，进程间通信）          | UNSUPPORTED（导入配额） | 打开、关闭 IPC handle 的 wrapper 转发给驱动，没有相应的导入记账                                                   |
| External Memory（外部内存）                             | UNSUPPORTED（导入配额） | 导入和映射 buffer 由 wrapper 转发，未见这些入口的限额记账                                                         |

### 联合验收

在另行授权的隔离环境固定 GPU UUID、镜像 digest、驱动、CUDA、模式和负载，观察 API 返回、实际 Hook 命中、共享账本、宿主监控和吞吐或设备活动。禁止以高权限容器绕过测试前提。库挂载异常、未覆盖入口、共享状态失效及异常退出都可能改变实际约束。软件限额与 MIG 硬件资源分区分别评估。

| 测试                               | 判断标准                                                                                                                                   |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 单进程配额内、超额、真实驱动失败   | 比较成功与拒绝返回，拒绝或失败后检查占额是否遗留                                                                                           |
| 并发准入                           | 用屏障同时发起 B/C，在多次运行中检查总量和两方返回                                                                                         |
| 同步、异步释放及异常退出           | 逐阶段采集账本，区分 free 返回、流同步和池保留。重启后验证失效槽位回收                                                                     |
| Managed、VMM、IPC、External Memory | 逐入口确认是否命中、记账及释放，未知记录为未验证                                                                                           |
| Graph 内存节点及异步捕获           | 分别检查建图、实例化、回放和销毁后的分配与回收                                                                                             |
| 普通 Kernel 与 Graph Replay        | 用[第 7 章](/articles/ai-infra-cuda-graphs.html)相同工作，比较无限额与 50 限额下的两条路径。分别观察调用证据、输出、GPU 活动、吞吐与尾延迟 |

当前仅核对源码及上述验收设计。第 16 章申请的 3000 MiB 和 50 要继续与[模型显存预算](/articles/ai-infra-training-inference-finetuning.html)及实际 SLO 对照。
