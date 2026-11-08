---
id: ai-infra-capacity-troubleshooting
title: 第 24 章 排障与容量验收：从现象走到证据
description: "笔记记录了 torch.cuda.is_available() 为 false、重启后恢复的现象。排查时先保存环境与错误信息，再沿设备发现、CUDA 初始化、容器和框架逐层定位；重启后的恢复现象本身不足以确定根因。"
date: '2026-10-25'
updated: '2026-10-28'
category: gpu-infra
type: troubleshooting
tags:
  - ai-infra
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 24
---

# 第 24 章 排障与容量验收：从现象走到证据

笔记记录了 `torch.cuda.is_available()` 为 false、重启后恢复的现象。排查时先保存环境与错误信息，再沿设备发现、CUDA 初始化、容器和框架逐层定位；重启后的恢复现象本身不足以确定根因。

## 1. 先记录环境、设备与错误现场 {#_1-第一原则-先保存现场}

记录时间、驱动和框架版本、容器 digest、设备 UUID、环境变量、错误码及相关日志。重启、升级驱动或批量杀进程可能破坏现场；在生产系统中，必须先评估影响并确认维护授权，不能将这些操作作为诊断的第一步。

[![GPU 排障：逐层通过、逐层定位](/assets/notes/ai-infra/gpu-troubleshoot.svg)](/assets/notes/ai-infra/gpu-troubleshoot.svg)

## 2. 按失败层次逐步缩小

| 现象                             | 优先证据                           | 不应立即推断             |
| -------------------------------- | ---------------------------------- | ------------------------ |
| 宿主无法发现 GPU                 | 驱动、设备枚举、系统日志           | Python 版本造成          |
| nvidia-smi 可用，CUDA 初始化失败 | 设备权限、库加载、最小 CUDA 错误   | 小版本数字不一致必然冲突 |
| 容器失败而宿主正常               | runtime、设备暴露、容器库与配置    | 必须重装宿主驱动         |
| 加载成功但请求 OOM               | 峰值与阶段、并发、上下文、KV/Graph | 权重文件太大是唯一原因   |
| 多卡挂起                         | 所有 rank 中最先失败的日志         | 最后等待者就是根因       |

以四卡服务器上的 7B 或更大模型为例，先在故障发生的节点、容器和服务身份下记录证据，再与健康副本对照。图概括主检查顺序；容器的设备映射和权限横跨多个层，故障也可同时发生。

| 层                                | 只读证据与现象                                                     | 下一步                                       |
| --------------------------------- | ------------------------------------------------------------------ | -------------------------------------------- |
| PCIe 与硬件                       | `lspci` 缺失 NVIDIA PCIe 功能或枚举变化                            | 对齐槽位、节点和历史日志，确认设备是否掉线   |
| 内核驱动                          | `lsmod`、`/proc/driver/nvidia/version`、内核日志出现加载失败或 Xid | 对照已加载模块、启动时间和设备标识           |
| 节点与权限                        | `ls -l /dev/nvidia*`，服务身份下节点不存在或访问被拒               | 核对 UID/GID、设备 cgroup 和映射             |
| NVML（NVIDIA Management Library） | `nvidia-smi -L`、NVML 初始化错误或 UUID 缺失                       | 核对驱动、管理库和 GPU/MIG 暴露              |
| CUDA Driver / Runtime             | 同环境运行第 3 节探针，保存初始化错误及库版本                      | 检查用户态驱动库、运行时兼容性和实际加载路径 |
| 容器运行时                        | `docker inspect` 或编排配置，宿主与容器 UUID 不一致                | 核对 runtime、设备请求和镜像 digest          |
| PyTorch / 服务框架                | 进程日志与框架探针显示 CPU 构建或算子错误                          | 核对 wheel、后端和目标架构                   |
| 模型加载                          | 启动日志中的权重路径、分片、格式和加载峰值                         | 核对模型 revision、权限及预算                |
| Prefill / Decode                  | 请求 trace、KV 块、峰值显存、队列变化                              | 定位阶段和触发形状                           |
| API 与业务                        | 现有请求日志的状态码、超时、错误率和响应体                         | 区分入口、代理、客户端与引擎的故障           |

Linux 只读观察命令如下。日志权限因环境而异，使用已有权限执行。在现有容器的诊断 shell 中重复设备查询，避免把宿主的成功结果当作容器结果。

```bash
lspci | grep -i nvidia
lsmod | grep '^nvidia'
cat /proc/driver/nvidia/version
ls -l /dev/nvidia*
journalctl -k -b --no-pager | grep -Ei 'NVRM|Xid|oom|out of memory'
nvidia-smi
nvidia-smi -L
nvcc --version
# Docker 示例。CONTAINER 为现有容器名。
docker inspect --format '{{.Image}} {{json .HostConfig.DeviceRequests}}' "$CONTAINER"
```

## 3. 一个不修改环境的框架信息片段

下面只做信息查询。

```python
import os
import torch
print("torch", torch.__version__)
print("build cuda", torch.version.cuda)
print("visible", os.environ.get("CUDA_VISIBLE_DEVICES", "<unset>"))
print("available", torch.cuda.is_available())
```

在 PyTorch 2.14，默认检测路径通过 CUDA Runtime 的 `cudaGetDeviceCount` 获取设备数，该路径会经 `cuInit` 初始化 CUDA Driver。启用 `PYTORCH_NVML_BASED_CUDA_CHECK=1` 时先尝试基于 NVML 的计数，失败时可能回退默认检测。NVML 成功的路径可避免该检查先初始化 CUDA 而影响后续 fork 子进程；NVML 成功只说明较弱的可发现性，CUDA 上下文初始化或算子执行仍可能失败。在诊断进程启动前设置变量，分别记录两个独立进程的结果与错误。未运行框架的 GPU 探针标为 NOT RUN。[PyTorch 2.14 CUDA 语义](https://docs.pytorch.org/docs/2.14/notes/cuda.html) · [环境变量](https://docs.pytorch.org/docs/2.14/cuda_environment_variables.html)

`nvidia-smi` 的 Driver Version 是 NVIDIA 驱动版本，CUDA Version 是驱动报告的 CUDA 支持版本。`nvcc --version` 对应 PATH 选中的 Toolkit 编译器，`torch.version.cuda` 是 PyTorch 构建使用的 CUDA 版本，CPU 构建通常为 `None`。CUDA Runtime 提供应用侧 API，底层通过 CUDA Driver 访问设备。几个版本可以不同，应查兼容表和原始错误，重启后恢复只能证明服务当时恢复。[CUDA 兼容性指南](https://docs.nvidia.com/deploy/cuda-compatibility/index.html)

## 4. 按加载、Prefill 与 Decode 区分 OOM {#_4-oom-要先确认发生阶段}

加载时 OOM，先看权重、并行布局和加载峰值；prefill OOM，检查输入长度、chunk 和激活；decode OOM，检查并发、KV 增长与内存池。还应区分 CUDA 分配失败与主机 OOM killer。

释放缓存并不能解决所有问题。仍由张量或图引用的内存，不会因为“清缓存”就安全释放；盲目缩短上下文或降低精度，也可能影响用户功能和质量。

| 阶段            | 关键证据                                                     | 最小对照                                                           |
| --------------- | ------------------------------------------------------------ | ------------------------------------------------------------------ |
| 加载            | 分片驻留权重、精度、量化元数据、加载临时张量                 | 固定权重 revision，对照实际 TP/PP 及每 rank 加载峰值               |
| Prefill         | 长输入与 batch、激活、kernel 工作区                          | 只改变输入长度或分块预算，记录 TTFT 与瞬时峰值                     |
| Decode          | 活跃请求、输出长度、KV Pool 与块使用率                       | 改并发或输出上限，区分池耗尽、驱逐与设备分配失败                   |
| CUDA Graph 捕获 | 捕获 batch/形状、图池及预热峰值                              | 用隔离配置减小捕获形状，比较常驻与峰值以及 Decode 延迟             |
| Host OOM        | Linux OOM Killer 或容器 cgroup 的 `oom_kill`，并核对进程退出 | 对照主机内存和 cgroup 限额，保存终止记录；单独检查 CUDA Device OOM |

在 PyTorch 2.14 使用以下片段观察已有进程、已初始化设备的分配器统计，放入受控诊断钩子；另起进程无法读取服务进程的统计。返回值以字节计，峰值是自初始化或上次峰值重置以来的记录。

```python
import torch

device = torch.cuda.current_device()
print("allocated", torch.cuda.memory_allocated(device))
print("reserved", torch.cuda.memory_reserved(device))
print("peak allocated", torch.cuda.max_memory_allocated(device))
print(torch.cuda.memory_summary(device=device))
```

Allocated 表示分配器中活跃张量占用，Reserved 包括分配器已保留的内存及可复用空闲块。GPU Used 来自设备视角，可能包含 CUDA Context、NCCL 或其他进程。KV Pool 是引擎预留的空间，可能已计入框架或设备统计。避免把包含关系相加。 `torch.cuda.empty_cache()` 释放分配器未占用的缓存，不能释放活跃张量或仍被引用的图内存，也不属于这个只读检查。[PyTorch 2.14 CUDA 显存管理](https://docs.pytorch.org/docs/2.14/notes/cuda.html#memory-management)

多卡故障先保存所有 rank 的日志、调用序号、通信器规模与成员、Rank→GPU UUID 和 GPU/NIC 拓扑，按时间及序号寻找最早 CUDA 或网络错误。再区分集合操作不匹配、设备失效和框架超时。通信契约与挂起案例见[第 22 章](/articles/ai-infra-multi-gpu-nccl.html)。

## 5. 最终验收是一组约束

正确性和任务质量 → 代表性负载 → 稳态性能 → 最坏形状与峰值显存 → 并发公平性 → 排空、失败和重启恢复。每项都应注明测试条件、预期、结果和证据，不用“能聊天”代替容量验证。

### 容量与恢复验收

沿用[第 23 章](/articles/ai-infra-inference-engines.html)的基准协议，锁定模型 revision、Tokenizer、镜像和引擎版本、GPU 与拓扑、并行布局、精度和输入输出分布。记录预热、测量窗口、重复次数、并发及到达率。

| 负载         | 重点核查                      |
| ------------ | ----------------------------- |
| 短输入短输出 | 基础 TTFT、E2E 与吞吐         |
| 长输入短输出 | TTFT 与 Prefill 峰值          |
| 短输入长输出 | Decode、ITL、TPOT 与 KV       |
| 混合并发     | 稳态吞吐、P99、排队积压和失败 |

各组记录 TTFT/ITL/TPOT/E2E 的 P50/P95/P99、Output Token/s、Request/s、OOM、失败、超时、设备峰值和质量。容量上界取同时满足正确性、质量、时延 SLO、错误率与显存余量，且队列稳定的最大已验证到达率。例如教学门槛可设 P99 TTFT≤500 ms、失败率≤1%、设备峰值后至少余 10% 显存。如果 12 req/s 组虽有 12 req/s 完成速率，但 P99 TTFT 达 650 ms，该组未通过。真实门槛由业务预先确定。

故障恢复顺序为观察 → 保存现场 → 分层定位 → 提出可证伪的假设 → 最小验证 → 授权修复 → 恢复业务 → 复测容量与正确性 → 归档。重启会清除进程状态和部分时间线，驱动升级可能同时改变多层变量，GPU Reset 会影响设备上的任务，因此均应纳入授权和影响评估。恢复后先验证最小功能，再逐级复测混合负载、峰值与 SLO。若只确认恢复，根因标为待证，并记录还需哪些证据。

故障记录至少包含事件时间和时区、GPU UUID、Driver/CUDA、容器 Image Digest、PyTorch/Serving 版本、Model Revision、Error Code、日志位置与最早异常、根因状态、授权与修复动作、恢复验证及遗留问题。以上矩阵和探针均为待执行方案。
