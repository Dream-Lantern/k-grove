---
id: ai-infra-gpu-checkpoint-restore
title: GPU-CR / GCR：GPU Checkpoint-Restore 论文与源码学习笔记
description: "结合 VMM、CUDA 驱动 Checkpoint / Restore 与 G-CR 源码，理解状态保存、恢复流程及应用层需要补齐的依赖。"
date: '2026-10-25'
updated: '2026-10-28'
category: gpu-infra
type: explanation
tags:
  - GPU
  - CUDA
  - VMM
  - Checkpoint
  - Restore
  - NCCL
  - 系统论文
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 26
---

# GPU-CR / GCR：GPU Checkpoint/Restore 的原理与工程实现

> 阅读材料：论文 [GPU Checkpoint/Restore Made Fast and Lightweight, FAST '26](https://www.usenix.org/system/files/fast26-zeng.pdf)；项目 [gpu-os/GPU-CR](https://github.com/gpu-os/GPU-CR)。
>
> **证据约定**：**[论文]** 表示论文的设计或实验结论；**[代码]** 表示 GPU-CR 公开仓库可定位的实现；**[工程分析]** 表示对机制的解释、设计建议或风险推断。不能把论文中的研究能力直接当成当前仓库已经完整实现、经过自己复现的能力。

**整体流程**：用 CUDA VMM 分离 GPU 虚拟地址与物理显存，先将 GPU 数据高带宽转移到 Host，再释放物理显存并保留地址语义；恢复时重建物理映射和内容；GPU 控制状态交给驱动级 C/R；多 GPU 再额外修复跨进程 cuMem IPC 关系。论文还研究了通过 CPU Shadow Execution 识别 Dirty Buffer 的增量 Checkpoint。

理解恢复范围时，分别观察三个层次：VMM 维护指针与物理分配的关系，驱动 C/R 处理 CUDA 状态，应用层补齐 CPU 进程状态、外部依赖和业务校验。下面先讲地址与数据的恢复，再沿单卡、多卡的阶段顺序展开。

## 0. 恢复对象、应用场景与设计目标 {#_0-为什么值得研究-问题、目标和边界}

GPU Checkpoint/Restore（C/R，检查点与恢复）需要保存并重建两个相互关联的状态：

- **数据状态 Data State**：模型权重、KV Cache、Activation、工作区、通信缓冲等内容及其所属地址。
- **控制状态 Control State**：CUDA Context、Streams、Events、Module/Kernel 等驱动维护的执行和资源状态。CPU 进程内存、线程与文件描述符属于更广泛的进程状态，不等同于 CUDA 控制状态。

应用场景包括 GPU 作业切换、弹性推理实例、故障恢复、训练任务抢占和 GPU 多租户。在这些场景中，“能够恢复”只是正确性要求；还需要较低的 checkpoint 延迟、restore 延迟和正常执行开销，并让其他任务能够使用释放的显存。

传统方案主要有两类；GCR 将二者组合：

| 路线                                  | 优点                                       | 局限                                                                |
| ------------------------------------- | ------------------------------------------ | ------------------------------------------------------------------- |
| 驱动集成，如 NVIDIA `cuda-checkpoint` | 驱动内部管理 CUDA 状态、应用平时开销低     | 论文所测版本的 GPU 数据搬运未充分利用总线带宽；不是对未来版本的定论 |
| API 拦截，如 interception-based C/R   | 可以自行使用异步 GPU→Host 拷贝优化数据面   | 拦截大量 API、资源句柄重建复杂，正常运行有额外开销                  |
| GCR 混合方案                          | **数据面自主拷贝；控制面利用驱动集成 C/R** | 需要确保指针地址、IPC、执行同步、外部资源正确恢复                   |

[论文 §3–§4](https://www.usenix.org/system/files/fast26-zeng.pdf) 的核心价值是让两种方案各管自己擅长的部分。**数据/控制分离不等于“CPU/GPU 状态分离”**，后者容易误解。

## 1. VMM 的核心：虚拟地址（VA）与物理显存解绑

### 1.1 从普通分配到稳定虚拟地址 {#_1-1-为什么普通-cudamalloc-不够}

假设应用原先获得 `p=0x1234`，其他 GPU 数据结构和 kernel 参数中已经保存了 `p`。如果 checkpoint 后直接 `cudaFree(p)`，restore 时再 `cudaMalloc()`，即使分配大小相同，也**不保证 VA 一样**，原来指向 `0x1234` 的引用会失效。

例中的 `0x1234` 是抽象地址，用于说明指针引用；可运行的 VMM 程序需另外满足对齐要求。

**[论文]** 把 VA 的生命周期和物理分配的生命周期分离，保存 VA/页表语义，在其下替换物理分配。

### 1.2 VMM API 的职责

| CUDA Driver API       | 核心意义                                                     |
| --------------------- | ------------------------------------------------------------ |
| `cuMemAddressReserve` | 预留一段 GPU 虚拟地址，暂不分配物理显存                      |
| `cuMemCreate`         | 创建物理内存分配并获取 `CUmemGenericAllocationHandle`        |
| `cuMemMap`            | 把物理分配映射到指定 VA 区间                                 |
| `cuMemSetAccess`      | 对设备配置映射区访问权限                                     |
| `cuMemUnmap`          | 解除 VA→物理分配映射，但不释放 VA 预留                       |
| `cuMemRelease`        | 释放当前持有的物理分配 Handle 引用；真正回收还受其他引用影响 |
| `cuMemAddressFree`    | 释放 VA 预留；正常应用 free 时调用，checkpoint 时不调用      |

**VMM 生命周期：**

[![GPU-CR VMM显存生命周期与业务安全点](/assets/notes/ai-infra/gcr-vmm-lifecycle.png)](/assets/notes/ai-infra/gcr-vmm-lifecycle.png)

```text
分配： Reserve(VA) → Create(Physical) → Map(VA, Physical) → SetAccess
                      ↓ 应用一直使用相同 VA
Checkpoint：Copy GPU→Host → Unmap(VA) → Release(Physical Handle)
                         保留 VA / 地址语义
Restore： Create(New Physical) → Map(Original VA, New Physical)
                         → SetAccess → Copy Host→GPU
最终正常释放：Unmap → Release → AddressFree
```

这里的“保留 VA”应结合**驱动级 CUDA 状态冻结/恢复**来理解：论文明确说明驱动 C/R 保存 GPU 页表控制状态，换入后仍使用原始 VA，并不是声称 checkpoint 后 VA 在所有进程中永远占用、不可能被驱动回收。

**[代码]** `src/GPUs/NVIDIA/nv.cpp` 的 `cudaMalloc` Hook 使用 VMM，`releasePhysicalMemory()` 实施 `cuMemUnmap` + `cuMemRelease` 而不调用 `cuMemAddressFree`，`remapPhysicalMemory()` 重建映射。代码按 2 MiB 向上取整，是项目实现选择；不宜将此推广成所有 CUDA VMM 分配均强制 2 MiB。

**API 语义与实现选择要分开**：通用代码应通过 `cuMemGetAllocationGranularity` 查询相应分配属性的粒度，并满足各接口的对齐限制。`cuMemCreate` 属性中的 `CU_MEM_ALLOCATION_TYPE_PINNED` 也不能直接读成“Host staging 已被锁页”；还要看 `location.type`，本文设备分配使用 `CU_MEM_LOCATION_TYPE_DEVICE`。依据：[CUDA 12.8.1 VMM API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__VA.html)。

### 1.3 UVA、UVM、VMM 是三个不同概念

- **UVA（Unified Virtual Addressing）**：统一虚拟寻址模型，让 Host/Device 指针具有可区分的地址语义，并不意味着 CPU/GPU 必然共享一份物理内存。
- **UVM/Unified Memory**：更关注统一内存访问及迁移能力，如 `cudaMallocManaged`；不是此处 `cuMemCreate`/`cuMemMap` 的同义词。
- **VMM（Virtual Memory Management）**：显式管理预留 VA、物理分配、映射与权限，是本项目保持指针稳定的直接机制。

**[工程分析]** 不能单凭“支持 UVA”就断言 GPU-CR 可运行，还要检查 GPU/驱动对相关 VMM API、共享句柄和外部 checkpoint 工具的支持。

## 2. 系统架构：把两种 Checkpoint 能力组合起来

[![GPU-CR：数据路径与控制工具边界](/assets/notes/ai-infra/gcr-architecture.svg)](/assets/notes/ai-infra/gcr-architecture.svg)

图中协调器负责发指令与等待阶段完成，**实际的 IPC teardown/rebuild 在 Worker 内的 Runtime 执行**。GPU 数据经 staging 双缓冲进入快照映射区；控制消息共享区不是大容量数据快照。图只画 NVIDIA 信号路径，避免把不同后端拼成一条调用链。

**[代码]** 项目目录重点如下：

| 路径                                           | 学习入口                                                                   |
| ---------------------------------------------- | -------------------------------------------------------------------------- |
| `src/vGPU.cpp`                                 | 初始化、信号入口、`ckpt()`、`restore_ptr_and_content()`、多 GPU IPC 状态机 |
| `src/GPUs/NVIDIA/nv.cpp`                       | CUDA Runtime Hook、VMM 释放/重建、CUDA 数据传输                            |
| `src/GPUs/AMD/`                                | ROCm 后端；不要照搬 NVIDIA 的 `cuda-checkpoint` 假设                       |
| `src/backend/`、`src/comm/`                    | Host staging、内存映射、进程控制通信                                       |
| `src/ipc_hooks.cpp`、`src/ipc_fd_exchange.cpp` | cuMem IPC 动态 Hook、跨进程 FD 交换                                        |
| `src/nccl_hooks.cpp`                           | NCCL 符号发现、兼容层                                                      |
| `coordinator/cr_client.cpp`                    | 单卡命令控制                                                               |
| `coordinator/multi_cr_client.cpp`              | 多进程广播、阶段屏障、驱动冻结/解冻                                        |
| `adapters/nccl/`                               | 可选的 NCCL Plugin ABI 接口路径                                            |

### 2.1 初始化与通信

**[代码]** 被注入的 Runtime 在装载时注册信号处理与内部状态；收到初始化信号 `CR_INIT_SIGNAL` 后准备 `ShareMemComm(pid)` 控制通道、共享映射空间、Host staging 双缓冲和 GPU 后端。协调器也写入 `INIT_MSG`，但初始化分支直接按信号处理；未初始化就收到 C/R 请求时，代码还会尝试延迟初始化。

- `SHM_SIZE_GB` 默认 `25`，对应**每个 Worker** 的主快照映射长度 `25 GiB`，可在编译时覆盖；元数据也占这段空间，所以可用数据容量略小于 25 GiB。
- `STAGING_BUF_SIZE = 1 GiB`，`STAGING_BUF_NUM=2`；实际预留 Host 内存还包括双缓冲及元数据。
- `NUM_COPY_THREADS=4`，采用多个 CPU 线程执行 `memcpy`。
- `cudaHostRegister` 尝试注册的是 **2 GiB staging 区**，不是默认 25 GiB 的整个快照映射区。失败后代码记录警告并继续，但这只是实现的降级分支，不能保证原有异步性、拷贝重叠和性能不变。Hugepage、Pinned、`mmap` 是三个不同机制。

`shared_mem_fs` 保存条目数、写入偏移与各分配的地址/大小；这里的 `files[]` 是内存快照条目，不是操作系统里的独立文件。`ckpt()` 对记录的分配按 2 MiB 取整后拷贝，因此**申请字节、物理分配字节、实际 dump 字节**不一定相等。源码入口：[common.h](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/common.h)、[vGPU.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/vGPU.cpp)。

**大小预算举例（工程估算）**：若单个 Worker 主存储空间 40 GiB、双缓冲 2 GiB，4 个 Worker 的 Host 内存规划至少约 `4 × (40 + 2) = 168 GiB`，还不含操作系统、进程页、额外 IPC export buffer 和碎片开销。这些不是 GPU-CR 的通用默认占用量，而是选定部署参数时的容量预算。

## 3. 单卡 Checkpoint/Restore：数据先搬、控制后冻

[![GPU-CR单卡Checkpoint/Restore时序图](/assets/notes/ai-infra/gcr-single-sequence.png)](/assets/notes/ai-infra/gcr-single-sequence.png)

图中的“业务安全点/停止提交”和“验收后放行”是**正确使用所需的外部协作条件**，不是宣称源码已经自动实现了这些屏障。配图区分数据面、驱动控制与外部验收；完成阶段通知不代表数据或业务验收通过。

### 3.1 Checkpoint

**[代码]** 信号处理函数先同步，再进入 `vGPU.cpp::ckpt()`：

1. 调用 `syncAllKernels()`；NVIDIA 实现是 `cudaDeviceSynchronize()`，等待其作用范围内先前提交的设备任务完成，**不是暂停所有 CPU 线程，也不是阻止未来提交**；
2. 遍历拦截器记录的 `allocated_memory`，将 `ptr / size / offset` 等元数据写入共享结构；
3. 使用两个 1 GiB staging buffer，让 GPU→Host 的异步拷贝与 Host→mmap 的 CPU 拷贝尽可能重叠；
4. 通过 CUDA Event / Stream 同步，避免缓冲区还未拷完就被覆盖；
5. **先完成数据备份，再 `releasePhysicalMemory()`**，释放 GPU 物理分配但保留 VA 语义；
6. Worker 返回完成，协调器才调用 NVIDIA 的 `cuda-checkpoint` 冻结 CUDA 控制状态。

**[工程分析] 用应用安全点稳定数据与分配账本。** 如果另一个 Host 线程在同步返回后继续写显存、分配/释放内存或启动 kernel，那么遍历 `allocated_memory`、拷贝和 unmap 期间仍可能竞争。必须先在应用/调度层建立安全点，阻止相关生产者继续提交，排空必要的通信，并使分配账本稳定；这个条件应持续到恢复数据和通信并验收完成。仅看到 `cudaDeviceSynchronize()` 或一次 `FINISH_MSG`，不能证明上述条件已经满足。依据：[CUDA Device Synchronize](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__DEVICE.html)。

这里还需区分两种“锁”：`ckpt()` 内部的 `fs_mutex` 保护快照结构，并不锁住应用的所有 CUDA 调用；驱动的 `lock` 则属于另一层协议，见 §3.4。不能简单地将驱动 `lock` 移到数据拷贝之前，就认为问题已经解决，因为本进程用于数据搬运的 CUDA API 也可能被阻塞，需要专门设计可行的协作协议。

**[工程分析]** `cuMemRelease` 是引用释放，不代表无条件将该 GPU 的 _全部_ 可见 VRAM 使用量清零。未拦截的分配、其他进程映射、外部 IPC handle 和框架内部状态都可能影响实际占用；必须以 nvidia-smi / NVML 和测试场景实测。

### 3.2 Restore

恢复必须先使 CUDA 驱动控制状态可用，再调用 CUDA API 去重建物理显存并恢复内容。`restore_ptr_and_content()` 既恢复原地址与新物理分配映射，也将数据拷回。

**对本文这条混合路径，可记为：Checkpoint 先搬数据、再做驱动 checkpoint；Restore 先恢复可调用的驱动状态、再搬回数据。** 这个口诀不包含完整的一致性协议，也不是所有 GPU C/R 系统的通用顺序。驱动解除锁定后，业务线程仍应由外部安全点约束，不能抢在数据恢复之前开始工作。

### 3.3 快照后端、内存映射与持久性 {#_3-3-checkpoint-文件究竟存在哪里}

- `mmap` 仅表示把内存/文件映射到进程地址空间，并**不天然具备掉电后持久性**。
- `hugetlbfs`、`tmpfs` 主要是内存支持的文件系统，吞吐较高，但需占用较大 Host 内存，崩溃/断电恢复语义要单独确认。
- 普通磁盘文件可提供更强的数据持久性，但需要考虑写入、`fsync`、空间、带宽以及失败恢复策略。

**[代码]** [`mmap_backend.cpp`](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/backend/mmap_backend.cpp) 通过 `EXPORT_FILE_PATH` 选择文件所在目录，否则使用 `/mnt/huge-ckpt`；`mmap` 均为 `MAP_SHARED`。仅有目录名不能证明实际挂载的是 hugetlbfs；设置 `EXPORT_FILE_PATH` 也不能证明它一定落在物理磁盘。该实现没有给出完整的原子提交、持久性确认与崩溃恢复协议，且初始化会重置快照头，不能直接把遗留 `.data` 文件当成可独立重启恢复的完整镜像。

**[工程分析]** GPU-CR 当前的高性能 Host staging 和“进程仍存活的换入换出”，不应直接等同于“一台机器断电后可以恢复完整 CUDA 应用”。

### 3.4 驱动状态机：锁定、保存、恢复与解锁 {#_3-4-驱动状态机-lock-不等于-checkpoint}

[CUDA 12.8.1 Checkpoint API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__CHECKPOINT.html) 将相关状态分开：

```text
RUNNING --lock--> LOCKED --checkpoint--> CHECKPOINTED
RUNNING <--unlock-- LOCKED <--restore----- CHECKPOINTED
```

`lock` 阻止进一步 CUDA API 调用；`checkpoint` 从 LOCKED 保存并释放驱动所管 GPU 状态；`restore` 成功后仍处于 LOCKED，之后才 `unlock`。它们不是 CPU 线程 suspend/resume 的同义词。

**[代码]** 单卡 `cr_client` 使用 `--toggle`。多卡协调器可使用 `--action lock/checkpoint` 和 `--action restore/unlock`，但锁定阶段位于自管数据 dump **之后**，恢复时又在自管数据恢复**之前** unlock。因此这两种路径都不能据此推导出“整个数据面阶段自动禁止业务提交”。源码把 action 路径注释为“580 mode”，但仓库随附工具 README 已在 570 特性与帮助中列出独立 lock/action；不要把源码的分支命名当成官方功能首次引入版本。

## 4. 多 GPU 的新增困难：NCCL、IPC、P2P

### 4.1 从单卡状态扩展到跨 Rank 资源关系 {#_4-1-为什么单卡方案不能简单复制-n-遍}

在多 GPU 分布式任务中，CUDA Context 之外还有跨进程资源：

- 导出方通过 `cuMemExportToShareableHandle` 暴露某个物理分配；
- 导入方用 `cuMemImportFromShareableHandle` 得到本地 handle，再映射到自己的 VA；
- 不同 Rank 通过 NCCL/P2P、IPC Events 协作；
- 完整释放原对象并创建新物理分配后，要把跨进程关系接到**新对象**；原来的 VA 数值相同，并不意味着原来的共享对象仍可用。

因此，除了“每卡各自 dump 数据”，还必须恢复**跨 Rank 的关联拓扑和资源所有权关系**。

本文描述的是**同一 Linux 主机上的多进程路径**。共享内存、PID 与 Unix Domain Socket 不构成跨机器传输协议；不能把它直接推广成多机 NCCL/RDMA 作业可透明恢复。

### 4.2 关键 IPC Hook

**[代码]** `src/ipc_hooks.cpp` 的 `HookEntry` 和 `g_hook_table` 包含对 `cuMemCreate`、`cuMemExportToShareableHandle`、`cuMemImportFromShareableHandle`、`cuMemMap`、`cuMemUnmap`、`cuMemRelease`、`cuMemSetAccess` 的替代回调。

核心困难：NCCL 可能通过 `cudaGetDriverEntryPoint` / `cuGetProcAddress` **动态获取函数指针**，仅通过一般 ELF 符号抢占 `cuMemMap` 名字可能不足以覆盖实际调用。代码拦截获取函数指针的入口，并对指定符号替换为 Hook，同时保存真实回调以供转发。

`g_ipc_imports`、`g_ipc_exports`、local allocations 相关表记录跨进程映射关系和恢复所需元数据。记录真实句柄与映射关系比仅记录 `ptr → size` 更复杂。

### 4.3 多卡 Checkpoint：先拆 IPC，再 dump，再冻结

[![GPU-CR：多 Rank 协同阶段](/assets/notes/ai-infra/gcr-multirank-phases.svg)](/assets/notes/ai-infra/gcr-multirank-phases.svg)

```text
Coordinator: broadcast message/signals to ALL ranks → wait ALL ranks finish

1. IPC Teardown
   ├─ Sync kernels
   ├─ Unmap/Release imported IPC mappings
   ├─ Save data + teardown exported allocations
   ├─ Teardown IPC events and tracked local allocations
   └─ Disable peer access

2. Data Dump
   └─ 每个 worker 独立执行 ckpt()，拷贝其自有显存

3. CUDA Freeze
   └─ toggle 路径并行调用；action 路径先并行 lock，再并行 checkpoint
```

注意 `multi_cr_client.cpp::broadcast_and_wait` 是**先向全部 Worker 发消息/信号，再等待全部 Worker 的 FINISH_MSG**。若某阶段的操作相互依赖，改成“给一个 Rank 发信号并等待结束，再通知下一个”可能死锁。它提供的是阶段屏障，不是通信正确性或数据一致性的自动证明；安全点应在拆 IPC 前建立。

### 4.4 多卡 Restore：数据恢复之后还得重建拓扑

```text
1. CUDA Unfreeze for all workers
2. GPU data Restore for all workers
3a. IPC Re-export: rebuild physical allocations, export new handles, start UDS server
3 (exchange): coordinator exchanges per-rank export metadata via SHM
3b. IPC Re-import: each rank receives peer FDs, import+map+access, validate and reenable P2P
```

**新分配需要重新建立 Handle 与跨进程引用。** 首先，FD 是进程自己的描述符编号，把导出进程的整数 `fd=17` 写给另一个进程，并不等于传递了该对象。其次，`cuMemRelease` 不会使所有旧引用立即失效：只要还有映射、导入引用或共享引用，旧对象就可能尚未真正回收。此实现先拆引用，再为新物理分配重新导出，由导入方接收新的本地 FD、导入并映射到原 VA。**“旧 FD 未必立即失效”和“旧 FD 不能代表新分配”是两件不同的事。** 依据：[VMM 的释放语义](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__VA.html)。

**UDS 与 SCM_RIGHTS 传递共享对象引用。** `src/ipc_fd_exchange.cpp` 明确采用 Unix Domain Socket 传递 FD（`sendmsg/recvmsg` 附带 SCM_RIGHTS）。源码注释指出从 `/proc/<pid>/fd` 重新打开或通过某些替代路径不能完整保留该 CUDA 共享句柄的语义。**这并不是普通文件路径共享问题，而是内核 FD 所承载的 GPU 对象权限/引用问题。**

Linux 的 `SCM_RIGHTS` 传递的是可在接收进程中安装的对象引用，接收方得到的 FD 数字通常不同；它不负责复制 GPU 数据。源码对 `pidfd_getfd` 的兼容性注释只代表该项目路径的判断，不应推广为 Linux 所有 FD 都“只能通过 SCM_RIGHTS 传递”。另有一处文档陷阱：`ipc_hooks.h` 顶部注释还写着 teardown 会 `cuMemAddressFree`、import 使用 `pidfd_getfd`；当前 `.cpp` 的导入/导出/本地分配拆除实际保留 VA，FD 主路径也已改用 UDS。读源码时应检查实现，而不能只摘取旧注释。依据：[ipc_hooks.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/ipc_hooks.cpp)、[ipc_fd_exchange.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/ipc_fd_exchange.cpp)、[Linux unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html)。

## 5. NCCL Adapter：与信号路径相互区分

项目有两种控制方式：

| 路径               | 用户如何触发                                 | 进程内 Runtime      | 外部要求                                   |
| ------------------ | -------------------------------------------- | ------------------- | ------------------------------------------ |
| Signal-driven      | `multi_cr_client -c/-r`                      | `vGPU-NVIDIA.so`    | `LD_PRELOAD` + 对多个 worker PID 统一编排  |
| NCCL Plugin-driven | 应用调用 `ncclCommCheckpointPrepare/Restore` | `libgcr_preload.so` | 定制构建的 NCCL + `NCCL_CHECKPOINT_PLUGIN` |

这里的 checkpoint API/插件 ABI 来自项目提供的 **NCCL 修改方案**，不能当成任意官方 NCCL 安装都自带的接口。两种 `.so` 也不是随意互换的名称：Adapter 的构建只包含自己的 runtime、`ipc_hooks.cpp` 和 FD 交换代码，没有把 `vGPU.cpp`/`nv.cpp` 的整套 `cudaMalloc` Hook 与双缓冲 dump 一起链接进去。它主要自管被跟踪的 cuMem 资源；其余由驱动处理或需要另外适配。因而不能把信号路径“所有已记录 cudaMalloc 都走高速 dump”的覆盖范围和性能直接套给 Adapter。依据：[Adapter CMakeLists](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/adapters/nccl/CMakeLists.txt)、[runtime](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/adapters/nccl/runtime/gcr_checkpoint_runtime.cpp)。

Adapter 典型链路：

```text
Application calls ncclCommCheckpointPrepare
   → patched NCCL loads libnccl-checkpoint-gcr.so
   → plugin dlsym(RTLD_DEFAULT, "gcr_checkpoint_*")
   → libgcr_preload.so runtime handles IPC/data
```

环境变量与边界：

- `NCCL_CUMEM_ENABLE=1`：让 NCCL 使用可由此 Hook 覆盖的 cuMem 分配/IPC 路径；否则旧式 `cudaIpcGetMemHandle` 可能绕过管理。
- `NCCL_CUMEM_HOST_ENABLE=1`：在相应部署里使用 cuMem 的 Host 通信缓冲。
- `NCCL_P2P_DISABLE=1`：某些 vLLM 配置启用，**但不能对所有 NCCL 测试默认启用**；项目的 two-process AllReduce 案例需要 P2P 路径来验证 export/import。
- 关闭 vLLM custom all-reduce：应核对实际版本的正式配置，例如 vLLM 0.14.1 的 `--disable-custom-all-reduce` 或 Python `LLM(..., disable_custom_all_reduce=True)`；若其旧式 IPC 不兼容，再选择 NCCL 路径或另行适配。项目脚本虽设置了 `VLLM_DISABLE_CUSTOM_ALL_REDUCE=1`，但 vLLM 0.14.1 官方 `envs.py` 未定义这个开关，不能仅凭 `export` 就认为已生效；同脚本的 `VLLM_DISABLED_KERNELS=custom_all_reduce` 也不能据此当成通用关闭方式，该版本的变量说明用于量化线性 kernel 选择。应检查最终配置和运行日志。依据：[vLLM 0.14.1 CLI](https://docs.vllm.ai/en/v0.14.1/cli/serve/#--disable-custom-all-reduce)、[LLM 源码](https://github.com/vllm-project/vllm/blob/v0.14.1/vllm/entrypoints/llm.py)、[环境变量源码](https://github.com/vllm-project/vllm/blob/v0.14.1/vllm/envs.py)。
- `CUDARTLIB=cudart`：使用适合动态拦截的 CUDA Runtime 构建；NCCL 默认的静态 cudart 可能绕开 `LD_PRELOAD` Hook。

## 6. 论文的重要补充：增量 Checkpoint 与 Shadow Execution

> **[论文设计，不等于本提交已实现]** 对本文所列公开源码入口的静态核查，未确认完整的 Dirty Template 生成与 CPU Shadow Execution 链路；不能据此宣称“编译该仓库即可开启论文全部增量能力”，也不将未发现当成对所有分支/后续版本的否定。

[![论文增量机制：计算写到哪里，而非重跑数值计算](/assets/notes/ai-infra/gcr-dirty-template.png)](/assets/notes/ai-infra/gcr-dirty-template.png)

### 6.1 Full C/R 的问题

完整 Checkpoint 每次都保存全部分配：

```text
权重：只读，未改变
KV Cache：只有新 Token 的部分区域变化
临时缓冲：部分/全部变化

Full：每次拷全部 S 字节
Incremental：在已有基线之后，只拷变更的 D 字节（D << S 时有效）
```

GPU 上并没有对所有应用透明且可直接使用的、足够精细的脏页位图供该论文依赖。只凭 Kernel 的非 `const` 参数判断“整个缓冲 dirty”也会产生 Checkpoint Amplification。

### 6.2 Dirty Template 的思想

原始 Kernel 的 Store 指令：

```text
store(dest = kv_cache + offset(index), value = compute(...))
```

生成 Dirty Template 时，保留**写入目标地址和写入长度的计算**，移除无关的大量数值运算：

```text
DirtyTemplate(kernel_args, gridDim, blockDim)
    → dirty address ranges
```

关键步骤：

1. **离线**基于 PTX 对可支持的 Kernel 做符号分析；
2. 将 Store 目标地址和长度表示为 Kernel 参数/网格配置的表达式；
3. 生成可在 CPU 快速执行的代码；
4. **在线**拦截 Kernel 启动时收集参数；
5. CPU 与 GPU Kernel 并行执行 Dirty Template，产生 dirty address ranges；
6. 增量 Checkpoint 只备份必要的变化范围，并与之前的 Full Checkpoint 合并。

论文 §5 的 vLLM 实现还利用工作负载知识：初始化时标记权重和 KV Cache 的地址/长度，只对 KV 更新使用模板，其他缓冲保守包含；并非完全不感知应用的通用自动分析。按论文描述，增量结果在保存时合并到已有完整快照，而不是要求恢复时必然回放很长的增量文件链。**[工程分析]** 脏区识别不得漏记；模板、参数视图与 GPU 写入必须对应同一轮快照，不能因 CPU/GPU 并行就省略完成确认。

这样就不需要在 GPU 的主计算热路径里插入大量脏地址记录指令。

### 6.3 Shadow Execution 的适用与退化情形 {#_6-3-为什么不是所有-kernel-都适合-shadow-execution}

论文特别说明边界：

- 封闭源码但有明确 API 语义的库调用，可根据文档保守标记修改范围；
- 无法可靠知道写入行为的封闭 Kernel，可能无法启用增量 Checkpoint；
- 如果 Dirty Address 依赖 GPU 内存中的指针追踪、复杂哈希等，计算 Shadow Template 的成本可能过高；
- 遇到无法安全分析的场景，可能退化为将全部非 `const` 参数缓冲标记 dirty。

因此这是**优化兼容性受限的增量机制**，不是对任意 Kernel 都能做到细粒度脏区判断。

### 6.4 论文中的量化效果

FAST '26 论文的实验结论（原论文对其所选模型/硬件/对照系统的结果）：

| 指标                                      | 论文报告                                                                 |
| ----------------------------------------- | ------------------------------------------------------------------------ |
| 相对 cuda-ckpt 的平均 checkpoint 延迟降低 | 72.1%                                                                    |
| 相对 PhOS 的平均 checkpoint 延迟降低      | 63.6%                                                                    |
| 相对 cuda-ckpt 的平均 restore 延迟降低    | 54.2%                                                                    |
| 相对 PhOS 的平均 restore 延迟降低         | 87.1%                                                                    |
| 正常 GPU 执行额外开销                     | 低于 1%                                                                  |
| 增量 Checkpoint 大小下降                  | 相对第一次完整 checkpoint，第二次平均下降 86.6%                          |
| 增量 Checkpoint 延迟下降                  | 同一比较口径下平均下降 43.8%                                             |
| Shadow Execution 的例示计算/记录空间      | 示例约 14 µs；每轮记录脏地址与长度的 CPU 内存小于 1 MB，不是整个系统内存 |

论文 §6 的平台为 2 张 A100-40GB、NVLink、PCIe 4.0、CUDA 12.6；涉及 PyTorch 2.7.1、vLLM 0.9.1 等，对 PhOS 支持的工作负载另用 Transformers 4.30.0。增量实验在两次 checkpoint 间处理 5 个请求，每个输入 1,155 token、输出 211 token。该环境与仓库 README 后来的 580 驱动/vLLM 0.14.1 演示不是同一组实验。表内低于 1% 指正常执行开销，**不等于 checkpoint 停顿时间低于 1%**；延迟降低百分比也不是吞吐提升倍数。

[论文 PDF](https://www.usenix.org/system/files/fast26-zeng.pdf) 的适用条件和实验基线不可省略；不能拿这些百分比直接预测自己 H20/H100、vLLM/SGLang 模型的换出耗时。

## 7. 按阶段分析拷贝、冻结与恢复成本 {#_7-性能模型-优化的是哪一段}

把一次操作拆分（工程分析，非论文精确公式）：

```text
Checkpoint wall time ≈ quiesce/sync
    + dump GPU data (GPU→Host→store)
    + VMM unmap/release
    + driver CUDA-control freeze
    + multi-rank IPC teardown/coordination

Restore wall time ≈ driver CUDA-control restore
    + VMM map/access + host→GPU copy
    + IPC re-export/re-import
    + validation / resume
```

如果测量表明，几十 GiB 的参数/KV 拷贝占据了主要时间，再重点优化 GPU↔Host 链路、Host 内存带宽与后端。不能仅因模型较大就认定瓶颈在拷贝；对于小快照、较多分配、复杂 IPC 或慢驱动路径，固定开销可能占主导。上式列出的是成本组成，并非源码的严格执行顺序；多 Rank 的同一阶段更接近“最慢 Rank + 协调开销”，也不应重复累加已重叠的阶段。

双缓冲流水线的直觉：`GPU→staging A` 与 `staging B→mmap` 并行，理论流水线吞吐受最慢阶段支配，而不是简单把两个拷贝时间相加。但启动、收尾、CUDA stream/event、CPU 线程调度以及内存容量都会形成额外成本。

**不要只看 VRAM 是否降为 0**：还应测 Host 额外内存、冻结时间、恢复时间、通信恢复、请求失败率、应用恢复后 TTFT/TPOT，以及恢复后一段时间的吞吐抖动。

## 8. 已知限制和工程风险（区分事实与推断）

| 项目            | 结论与注意                                                                                                                                                                                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| 透明性          | `LD_PRELOAD` 依赖动态符号拦截，静态链接、内部动态解析、未覆盖 API、旧式 IPC 可能绕过；对所有应用“零修改”不作绝对保证                                                                                                                                                     |
| CUDA 指针       | 项目转换被拦截分配为 VMM，使用 2MiB 向上取整，可能出现内存放大和碎片损失                                                                                                                                                                                                 |
| IPC             | 导出方、导入方、事件、Peer Access 必须联合恢复；不能只 dump 自有显存                                                                                                                                                                                                     |
| 信号安全        | 实现的 signal-handler 链路调用较复杂的 CUDA、拷贝与分配行为，不属于简单异步信号安全操作；多线程时序、重入性是潜在风险                                                                                                                                                    |
| Host 容量       | 信号路径每 Worker 默认主映射 25 GiB + staging 2 GiB，另有 IPC/本地 cuMem 备份；映射长度不等于任何时刻的 RSS。约 36 GiB dump 超过默认上限，需修改编译容量并按所选后端配足资源                                                                                             |
| 指标“0 VRAM”    | 是项目在支持路径上的目标/报告，不是对任何库外分配的数学保证；要实测                                                                                                                                                                                                      |
| 多卡后端        | 当前 README 的多 GPU C/R 主要是 NVIDIA，不能推广成 AMD 多卡已支持                                                                                                                                                                                                        |
| 恢复范围        | CUDA Control C/R、GPU Data C/R、CPU 进程 C/R 是不同层次；跨故障重启需要额外持久性及进程恢复机制                                                                                                                                                                          |
| 增量 Checkpoint | 论文有 Shadow Execution 与 Dirty Template；不能在未核实源码/示例时宣称当前仓库已覆盖该完整能力                                                                                                                                                                           |
| 静态上限        | `MAX_FILE_NUM=4096` 是主快照元数据数组容量，不是“4096 个 IPC 连接”；当前检查在递增后遇到该值即退出，不能把 4096 当成已验证可保存条目数。另有 `MAX_MULTI_GPU_PROCS=32`、`IPC_MAX_EXPORTS_PER_PROC=64`；后者也限制交换时汇总到 peer block 的条目数，不是总可支持规模的保证 |
| 单进程多设备    | `nv.cpp` 的 cudaMalloc Hook 缓存首次设备/上下文，账本不是完整的按设备隔离实现；多进程多 GPU 的示例不能证明单进程任意多设备/多 Context 已覆盖                                                                                                                             |
| 恢复后验收      | 内存映射校验不等于 NCCL 集合通信和业务输出正确；还需实测通信、数据与服务状态                                                                                                                                                                                             |

信号安全的判断依据是 [Linux signal-safety(7)](https://man7.org/linux/man-pages/man7/signal-safety.7.html)；这里只指出复杂处理不具备一般异步信号安全保证，未声称已经复现某个死锁。

### 8.1 从阶段通知到可靠成功的验收条件 {#_8-1-打印完成-为什么不等于可靠成功}

以下是**该提交可定位的静态问题**，不是本机运行所得故障：

- 单卡 `cr_client.cpp` 对 `system()` 主要检查 `ret < 0`；子进程正常启动但返回非零退出码，并不会被这个条件充分识别，后续仍可能打印完成。
- 多卡 `do_checkpoint()` 记录 freeze 失败后仍会输出 `Checkpoint Complete`；`broadcast_and_wait()` 只有轮询 FINISH，没有完整的超时与逐 Rank 错误结果协议。
- `FINISH_MSG` 是阶段通知，不是携带所有子步骤结果的事务提交；部分 IPC 分支会记录警告或忽略校验返回值。peer block 超出容量时也有只警告并截断的分支。
- 恢复导出/本地 cuMem 分配之后，代码会释放相应 Host 备份缓冲。因此不能假设一次部分失败后仍能无限重试，或简单再 toggle 就一定回到一致状态。

**[工程建议]** 将外部工具退出状态、驱动状态、各 Rank 阶段结果、条目数量/容量和恢复后通信校验都作为验收条件；任一阶段结果不明就保持业务不放行、保存日志和仍有效的备份。失败回退应按实际状态设计，不能承诺原型已有完整事务回滚。源码：[cr_client.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/coordinator/cr_client.cpp)、[multi_cr_client.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/coordinator/multi_cr_client.cpp)。

## 9. 结合模型性能测试平台的实践思考

在 LLM 推理性能测评中，可将 GPU-CR 视为一种可能的**推理实例抢占/换入换出机制**，但不宜简单地将它当作新的推理优化参数。

下面是新增的**实验设计建议**：

1. **Baseline**：vLLM 服务不使用 GPU-CR，在固定 Dataset/并发/ISL/OSL 下测稳定 TTFT、ITL/TPOT、Token Throughput。
2. **Checkpoint 开销**：测 quiesce、数据拷贝、VMM 回收、CUDA freeze 分阶段耗时；记录峰值 Host/GPU 内存。
3. **Swap-out**：进程不退出时记录 GPU VRAM 实际回收量，启动第二任务验证资源可复用。
4. **Restore 开销**：测 driver restore、VMM remap、数据恢复、IPC 重建、应用重新接受请求的总时长。
5. **多卡一致性**：在 TP/PP 任务中确认所有 Rank 恢复、NCCL 通信成功且后续请求结果可用。
6. **可观测性**：区分 API checkpoint 返回成功、GPU 资源已释放、推理服务重新 Ready、首次请求成功这几个不同终点。
7. **失败注入**：Host staging 不足、某 Rank 超时、旧式 IPC、UDS FD 交换失败、驱动不匹配；观察是否有安全回退与资源泄露。

建议报告新增只与 C/R 相关的指标，而不要把普通推理 SLO 和切换过程混成一个数：

| 指标                            | 含义                                                                 |
| ------------------------------- | -------------------------------------------------------------------- |
| `checkpoint_duration_seconds`   | 从触发到安全释放显存/冻结的端到端时间，需清楚定义边界                |
| `restore_duration_seconds`      | 从恢复触发到 GPU/通信状态恢复的时间                                  |
| `service_ready_latency_seconds` | 从 Restore 开始到服务对外可用的时间                                  |
| `vram_reclaimed_bytes`          | Checkpoint 释放的实际可观测 GPU 物理显存                             |
| `host_checkpoint_bytes`         | 有效快照数据字节数；另报 staging、映射容量与峰值 RSS，避免混成一个数 |
| `post_restore_success_rate`     | 恢复后请求成功率与正确性                                             |
| `post_restore_ttft/throughput`  | 恢复后性能是否达到原水平                                             |

只要被测服务依赖分布式通信，**恢复 CPU/CUDA 控制状态成功 ≠ NCCL 通信恢复成功 ≠ 应用推理服务恢复成功**。

## 10. 八个知识要点回顾 {#_10-容易混淆的-8-个问题}

1. 普通释放后重新分配不保证原 VA；VMM 将 VA 预留与物理分配的生命周期分开管理。
2. `cuMemUnmap` 解除映射，`cuMemRelease` 释放相应 Handle 引用，`cuMemAddressFree` 释放 VA 预留，各自的回收条件分别判断。
3. UVA 提供统一寻址语义，Unified Memory 管理统一访问与迁移，VMM 提供本项目直接使用的显式映射能力。
4. 混合路径先 dump data 再保存驱动状态；应用安全点还要约束业务提交、数据变更与恢复后的放行。
5. `cuGetProcAddress` 等动态入口会影响 Hook 覆盖，需要跟踪实际函数指针的获取与转发。
6. 旧 FD 可以继续引用旧对象，新的物理分配仍需重新导出和导入；`SCM_RIGHTS` 传递可在接收进程安装的对象引用。
7. Dirty Template 保留地址与长度计算，复杂或不可分析的写入路径需要保守标记或退化处理。
8. VRAM 回收是资源状态的一项观察，完整恢复还需验证 CUDA、CPU、通信、持久化与业务状态。

## 11. 阅读索引与证据来源

**论文段落**：

- §3 传统驱动集成与 API 拦截 C/R 的性能瓶颈；
- §4.1 混合 C/R、VA/物理解绑；
- §4.2 增量 Checkpoint、Dirty Template 与 CPU Shadow Execution；
- §5 实现约束；§6 实验；§7 Discussion。

**源码阅读顺序**：

1. [README.md](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/README.md)
2. [src/common.h](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/common.h)
3. [src/GPUs/NVIDIA/nv.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/GPUs/NVIDIA/nv.cpp)
4. [src/vGPU.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/vGPU.cpp)
5. [coordinator/cr_client.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/coordinator/cr_client.cpp)
6. [coordinator/multi_cr_client.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/coordinator/multi_cr_client.cpp)
7. [src/ipc_hooks.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/ipc_hooks.cpp)
8. [src/ipc_fd_exchange.cpp](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/src/ipc_fd_exchange.cpp)
9. [adapters/nccl/README.md](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/adapters/nccl/README.md)
10. [原始论文 PDF](https://www.usenix.org/system/files/fast26-zeng.pdf)

**复核补充来源**：

- [CUDA 12.8.1 VMM](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__VA.html)：分配、映射、粒度与引用释放。
- [CUDA 12.8.1 Checkpoint API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__CHECKPOINT.html)：驱动状态机，不能与应用安全点混同。
- [仓库随附的工具说明](https://github.com/gpu-os/GPU-CR/blob/e9bbb52e1f52986587fc631217c0f2b50b46245a/cuda-checkpoint/README.md)与 [NVIDIA 主线版本说明](https://github.com/NVIDIA/cuda-checkpoint)：历史条件和后续能力分别阅读。
- [Linux unix(7)](https://man7.org/linux/man-pages/man7/unix.7.html)、[signal-safety(7)](https://man7.org/linux/man-pages/man7/signal-safety.7.html)：FD 传递与异步信号安全。

**图源**：[架构](/assets/notes/ai-infra/gcr-architecture.drawio)、[VMM 生命周期](/assets/notes/ai-infra/gcr-vmm-lifecycle.drawio)、[单卡时序](/assets/notes/ai-infra/gcr-single-sequence.drawio)、[多 Rank 阶段](/assets/notes/ai-infra/gcr-multirank-phases.drawio)、[增量机制](/assets/notes/ai-infra/gcr-dirty-template.drawio)。同名 `.mmd` 保留原逻辑图源，正文按当前引用使用 SVG 或 PNG；图源与展示图分别核对，配图用于解释机制和主干流程。
