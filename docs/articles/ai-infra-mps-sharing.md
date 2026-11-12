---
id: ai-infra-mps-sharing
title: 第 15 章 MPS 与其他共享方式：并发不等于硬隔离
description: "MPS（Multi-Process Service）通过协作多个 CUDA 进程复用设备资源，适合研究小任务的并发机会。"
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
order: 15
---

# 第 15 章 MPS 与其他共享方式：并发不等于硬隔离

MPS（Multi-Process Service）通过协作多个 CUDA 进程复用设备资源，适合研究小任务的并发机会。实际收益取决于负载与资源争用；它与 MIG 的资源划分方式不同，比较时应先明确复用、隔离和性能目标。

## 1. 先分清历史实现

传统 pre-Volta 路径和 Volta 起的执行及地址空间机制不同。MPS 有控制守护进程、server 与 client 运行时等角色，具体提交路径和隔离能力需按架构与实现理解。[MPS Architecture](https://docs.nvidia.com/deploy/mps/latest/architecture.html)

[![GPU 共享：需求与机制](/assets/notes/ai-infra/sharing-choices.svg)](/assets/notes/ai-infra/sharing-choices.svg)

图中分支只是选择起点，不是固定推荐。例如已划分的 MIG 实例中也可以在支持条件下使用 MPS。

MPS 是 Multi-Process Service（多进程服务）。Control Daemon（控制守护进程）接收客户端连接并管理 Server。Server 管理客户端共享的 GPU 调度资源。Client 是使用 MPS 的 CUDA 进程，仍有 CUDA Context（上下文），其中包含执行和资源状态。GPU Work Queue（设备工作队列）承载已提交的工作。

| 场景             | 两个客户端各提交短 kernel 时                                                                          |
| ---------------- | ----------------------------------------------------------------------------------------------------- |
| 普通多进程       | 两个 Context 分别提交，设备在 Context 间调度，共用设备时间，不能依靠不同 Context 的 kernel 相互重叠   |
| pre-Volta MPS    | 客户端经 Server 代理提交，复用服务器的 GPU 调度资源。客户端共享服务器侧 GPU 地址空间，隔离较弱        |
| Volta 及后续 MPS | 客户端具有独立 GPU 地址空间，直接向 GPU 提交工作。Server 仍负责建立连接、管理共享的调度资源和故障状态 |

小 kernel 若各自无法占满设备，MPS 可能减少 Context 切换开销并创造重叠机会。两项工作若都已占满带宽或计算资源，共用设备仍会争用。地址空间隔离也没有改变两者共享物理卡的事实。

### 控制协议 v2 与 v3

GPU 执行实现的 pre-Volta/Volta 分界与控制协议是两个维度。下表的 v2 实验采用 Linux、A100 非 MIG 整卡、CUDA Toolkit 12.8.1 和兼容驱动。v3 由 CUDA 13.4 引入，以 NVIDIA Release 615 接口文档为版本参照。使用 v3 前要核对支持目标 GPU 的驱动和配套控制二进制是否识别协议选项。CUDA 12.8.1 实验不使用 v3 命令。

| 能力                | Legacy v2                                                  | v3                                                                                                        |
| ------------------- | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| 控制协议            | 默认协议，命令经标准输入送到控制工具                       | 显式选择协议 3，例如受支持工具的 `-p 3`，用 `module verb` 命令                                            |
| Server 与 Namespace | 按用户启动 Server，用 PID 管理                             | 命名 Server、命名空间及配置文件。Namespace 是客户端分组，可与 cgroup 关联，与 OS PID namespace 是不同概念 |
| 资源配置            | 按架构支持的执行资源比例及设备内存上限                     | 可按 Server/Namespace 配置相应限制，功能及硬件条件按发行版核对                                            |
| Client 管理终止     | `terminate_client <server PID> <client PID>`，需支持该接口 | `client terminate <client PID>`，按目标版本的命令帮助定位                                                 |
| 内存                | Volta+ 的传统设备内存上限                                  | 另有 cgroup 集成的设备内存分区，适用条件见下节                                                            |

[CUDA 13.4 发布说明](https://docs.nvidia.com/cuda/archive/13.4.2/index.html) · [Release 615 MPS v3 接口](https://docs.nvidia.com/deploy/mps/615/mpsv3-interface.html) · [Legacy MPS v2](https://docs.nvidia.com/deploy/mps/latest/mpsv2-interface.html)

## 2. 百分比参数限制的资源与性能范围 {#_2-百分比参数不表示预留同等算力}

legacy MPS 的 active thread percentage 限制可使用的执行资源，并非把每个应用的吞吐、延迟都精确锁定为某个百分比。硬件粒度可能导致取整。显存限制、线程资源限制和带宽隔离也是不同机制。[Legacy MPS v2 接口](https://docs.nvidia.com/deploy/mps/latest/mpsv2-interface.html)

| 方式       | 主要作用                       | 不应自动承诺                           |
| ---------- | ------------------------------ | -------------------------------------- |
| 多 stream  | 表达同一应用工作顺序和并发机会 | 跨租户隔离                             |
| 时间片共享 | 多任务复用设备                 | 显存或吞吐的硬分区                     |
| MPS        | 协作多进程资源复用             | 全部故障互不影响、固定吞吐份额         |
| MIG        | 受支持硬件的资源实例化         | 整卡级故障完全隔离                     |
| vGPU       | 虚拟机等场景的设备虚拟化体系   | 一律只采用时间片；也有 MIG-backed 路径 |

Volta+ 的 Active Thread Percentage（活跃线程比例）是执行资源上限。假设 A、B 分别设为 50%，硬件会把上限向下取到可支持的线程粒度。两个客户端没有预留互斥的一半 SM。若 B 空闲，A 可以使用在其有效上限内原本与 B 争用的资源，不能因此突破自身上限。要允许单个客户端在对方空闲时扩大可用范围，应预先配置更宽的上限，并验证并发时的竞争影响。两个 50% 也不会把显存容量或显存带宽平均分配。

| 方式                                    | 约束单位和设置时机                                                                                                       |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| Uniform Partitioning（统一比例）        | 启动客户端前设置 `CUDA_MPS_ACTIVE_THREAD_PERCENTAGE`，对该进程的上下文应用统一上限，可进一步收紧守护进程或 Server 的上限 |
| Non-uniform Partitioning（非统一比例）  | 启动前启用 `CUDA_MPS_ENABLE_PER_CTX_DEVICE_MULTIPROCESSOR_PARTITIONING`，创建各 Context 前配置比例                       |
| Programmatic Partitioning（程序化限制） | 在支持的 Volta+ MPS 路径通过 `cuCtxCreate_v3()` 指定 SM 数量，按支持粒度向上取整，再用 `cuCtxGetExecAffinity()` 查实际值 |

这些动态限制与新版本显式启用的静态 SM 分区不同。后者需要单独核对 Toolkit、硬件和控制配置。参见 [NVIDIA MPS 资源配置](https://docs.nvidia.com/deploy/mps/when-to-use-mps.html)。

Legacy MPS 的 `CUDA_MPS_PINNED_DEVICE_MEM_LIMIT` 限制支持架构上客户端通过 CUDA API 可分配的设备内存，超限会遇到分配失败。这里的 pinned device memory 与页锁定主机内存不同。CUDA Memory Pool 管理流序分配的缓存和复用，也不构成跨进程容量隔离。MIG 则在支持 GPU 上把显存路径与容量按 GI 硬件分区。

MPS v3 的 cgroup 设备内存分区要求 Linux cgroup v2、CUDA 13.4 或更新版本、支持此能力的驱动和非 MIG GPU。硬上限可使分配失败，软上限涉及内存压力下的回收或驱逐。Release 620 文档还区分 `dmem` 与 `misc` 后端，受内核能力和驱动配置约束，托管内存另有限制。这是配额与压力管理机制，不能据此推导带宽或故障隔离。[MPS v3 Memory Partitioning，Release 620](https://docs.nvidia.com/deploy/mps/620/mpsv3-memory-partitioning.html)

## 3. 按版本管理在途工作与退出顺序 {#_3-故障和退出行为不能靠框架名担保}

停止服务时，应先排空并同步未完成的工作，再按相应版本的管理流程退出。不要从信号处理器直接调用复杂的 CUDA API，这并不能保证异步信号安全。还应保存 server 日志、客户端映射和故障前的时间线。

## 4. 强制中断、故障传播与受控终止 {#_4-sigkill-不能被框架捕获后优雅清理}

Linux 的 SIGKILL 不能被捕获、阻塞或忽略。因此“kill -9 后别的任务没受影响”不能归因为框架在信号处理器里完成了清理。仅观察到其他任务未受影响，还不足以解释机制；进一步判断需要当时的在途工作、server 状态和日志。[Linux signal(7)](https://man7.org/linux/man-pages/man7/signal.7.html)

| 事件                    | 必须区分的条件                    | 不应给出的通用保证       |
| ----------------------- | --------------------------------- | ------------------------ |
| 正常退出                | 是否已排空在途 GPU 工作           | 任意退出顺序都安全       |
| 未同步强制中断          | server 和关联客户端状态           | 只会影响当前 Python 进程 |
| Fatal GPU fault         | 架构、受影响 GPU 及客户端集合     | 全卡必全挂或完全无传播   |
| 受控 client termination | 接口版本、PID namespace、成功返回 | 返回前即可随意杀进程     |

管理终止顺序以目标版本为准。当前 Release 615 文档区分 legacy 的 `terminate_client <server PID> <client PID>` 与 v3 的 `client terminate <client PID>`：确认映射 → 发起管理终止 → 等待成功 → 必要时结束 OS 进程。这里仅列不可直接执行的占位语法，不提供 kill 脚本；管理 PID 必须使用控制端所在 namespace 的对应值。[MPS Client Termination，Release 615](https://docs.nvidia.com/deploy/pdf/CUDA_Multi_Process_Service_Overview.pdf)

正常退出时先停止提交、同步并检查返回值，再释放缓冲区和退出。SIGKILL 跳过应用清理，在途工作与共享 Server 的后果需要按日志和返回码判断。pre-Volta 客户端共享 GPU 地址空间，错误写入或致命故障可能影响其他客户端。Volta+ 的致命 GPU 故障可传播给共享受影响 GPU 集合的客户端。Server 可能处于 FAULT，并拒绝新连接，直至受影响客户端退出并完成恢复。其他 GPU 是否受影响取决于客户端与设备连接关系。Server 自身故障后，先确认在途任务失败范围，重建设备连接并验证正确性，再恢复流量。受控终止需用所选协议并等待成功返回，不能用 OS 信号代替 GPU 侧管理动作。[MPS 故障范围与恢复](https://docs.nvidia.com/deploy/mps/when-to-use-mps.html)

## 5. 在独立实验节点比较三组运行

**以下命令会启动和停止 MPS 守护进程。仅用于已授权、无其他业务的单 GPU 实验节点。** 使用 A100 非 MIG 整卡、Linux、CUDA 12.8.1 的配套驱动与 Legacy v2 控制工具。同一 UID 启动控制端和两个客户端。先用 `nvidia-smi -L`、`nvidia-smi`、`nvcc --version` 和工具帮助核对设备、软件、计算模式和现有 MPS 状态。已有服务占用时停止实验。不要复用其目录或修改生产计算模式。

复用[第 12 章](/articles/ai-infra-performance-profiling.html)的 `layout.cu`，用 `nvcc -std=c++17 -O2 layout.cu -o layout` 编译。将 `repeats` 固定到让两进程可观察重叠的值，三组保持一致。客户端成功标准是同步成功且逐元素校验输出 `PASS`。先在确认未使用 MPS 时分别运行 `./layout row`、`./layout column`（A 组），再并行启动并分别等待两个进程、保存输出和退出码（B 组）。

C 组只在独立环境中执行。以下是 Bash 示例，先把占位符替换为 `nvidia-smi -L` 的实际物理 UUID。守护进程只暴露选中的卡。客户端不再用宿主数字索引过滤由 MPS 重新枚举的设备。

```bash
lab=$(mktemp -d)
mkdir "$lab/pipe" "$lab/log"
export CUDA_MPS_PIPE_DIRECTORY="$lab/pipe"
export CUDA_MPS_LOG_DIRECTORY="$lab/log"
CUDA_VISIBLE_DEVICES='<GPU_UUID>' nvidia-cuda-mps-control -d
```

启动成功后运行下列客户端。在它们仍运行时，从同一实验终端环境的另一个 Shell 查询 `printf 'get_server_list\n' | nvidia-cuda-mps-control`，再将返回的 Server PID 填入 `get_client_list <SERVER_PID>` 进行查询。查询太晚时列表可能已为空，应延长三组的相同工作轮数并重测。

```bash
env -u CUDA_VISIBLE_DEVICES ./layout row >"$lab/a.log" 2>&1 & a=$!
env -u CUDA_VISIBLE_DEVICES ./layout column >"$lab/b.log" 2>&1 & b=$!
a_rc=0; b_rc=0
wait "$a" || a_rc=$?
wait "$b" || b_rc=$?
printf 'client A=%s B=%s\n' "$a_rc" "$b_rc"
```

只有确认两个客户端已退出且该 daemon 确属本次实验，才执行 `printf 'quit\n' | nvidia-cuda-mps-control`，随后保存日志并确认服务已停止。若客户端异常，先查 Server 日志与状态，按维护流程处理，不进行强制终止。使用 MIG 与 MPS 的组合实验时，另外验证驱动与实例 UUID、可见设备和独立 pipe 目录约束。参见 [NVIDIA MPS 操作指南](https://docs.nvidia.com/deploy/mps/latest/quick-start.html)。

记录 GPU、Driver、Toolkit、MPS 协议、资源限制、输入和预热条件。除内存访问负载外，可用[第 7 章](/articles/ai-infra-cuda-graphs.html)的短 kernel 普通路径，以及固定迭代数的长计算负载，分别做 A/B/C 对照。报告各客户端正确性、错误率、总吞吐、P50/P95/P99、显存及可用 SM 活动。微基准可按多批运行统计批次耗时，不能把批均值当作单请求尾延迟。业务实验则用真实请求延迟。对比同一负载的独跑及同跑干扰，比较 MPS 的性能收益。

## 6. 按服务约束选择共享方式

| 方式                          | 适用条件与粒度                           | 算力与显存控制                             | 性能与故障边界                       |
| ----------------------------- | ---------------------------------------- | ------------------------------------------ | ------------------------------------ |
| CUDA Stream                   | 单进程内的工作流，常见于推理流水线       | 用依赖组织并发，无租户算力或容量配额       | 竞争同一执行环境与设备               |
| 时间片共享                    | 调度系统允许多个任务使用同卡             | 轮转分配执行机会，通常没有硬件显存切分     | 上下文切换、尾延迟和设备故障共享     |
| MPS                           | 支持的 Linux CUDA 平台，多进程推理或 HPC | 按版本使用比例、SM 限制或设备内存上限      | 实际吞吐受争用与故障传播范围影响     |
| MIG                           | 支持的 GPU 与配置，按 GI/CI 粒度部署     | GI 硬件分区，CI 切分计算并共享父 GI 显存   | 分区内与整卡风险分别评估             |
| vGPU（Virtual GPU，虚拟 GPU） | 受支持的虚拟化平台、驱动及配置           | 依 Profile，可使用时间片或 MIG-backed 路径 | 性能和故障边界取决于宿主与 vGPU 类型 |

例如服务 A 与 B 同属一个应用且只想重叠预处理和推理，可先试 Stream。若是互信的独立进程且各自的短 kernel 不能占满 GPU，可用 MPS 对照测试。若希望 B 的显存压力与 A 分开，则先按[第 13 章](/articles/ai-infra-mig-isolation.html)选择不同 GI，再评估实例内是否需要 MPS。虚拟机租户则核对 [NVIDIA vGPU 产品文档](https://docs.nvidia.com/vgpu/)及目标平台的支持矩阵。
