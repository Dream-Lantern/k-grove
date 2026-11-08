---
id: ai-infra-mig-isolation
title: 第 13 章 MIG 原理：GI、CI 与隔离的粒度
description: "MIG（Multi-Instance GPU）基于受支持硬件，将 GPU 的相应资源划为可分配实例。理解它时，先看 GI 与 CI 的包含关系，再看 Profile 描述的资源以及通信和故障边界；具体变更操作在下一章展开。"
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
order: 13
---

# 第 13 章 MIG 原理：GI、CI 与隔离的粒度

MIG（Multi-Instance GPU）基于受支持硬件，将 GPU 的相应资源划为可分配实例。理解它时，先看 GI 与 CI 的包含关系，再看 Profile 描述的资源以及通信和故障边界；具体变更操作在下一章展开。

## 1. GI 与 CI 的包含关系

GI（GPU Instance）由一定的计算、内存及相关引擎资源组成。一个 GI 可以进一步划分 CI（Compute Instance）；同一 GI 下的 CI 划分计算资源，但共享父 GI 的相应内存和引擎资源。因此，两个 CI 不能被描述为拥有两份完全独立的 GI 显存。[MIG Concepts](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/concepts.html)

[![MIG：GI 的资源边界与 CI 共享关系](/assets/notes/ai-infra/mig-boundaries.svg)](/assets/notes/ai-infra/mig-boundaries.svg)

图中是逻辑示意，不按某款产品的精确比例绘制。“显存固定八等分、计算固定七等分”有 A100 等特定产品语境，不能推广到所有 MIG GPU。

以 A100 40GB 为教学基线，物理资源模型有 8 份 GPU Memory Slice（显存切片）和 7 份 GPU SM Slice（计算切片）。每个显存切片约 5 GB，关联部分内存带宽。SM（Streaming Multiprocessor，流式多处理器）是执行线程块的硬件单元。GI 按 Profile 获得若干切片，分配到不同 GI 的路径有独立的 L2 Cache（二级缓存）分区、Memory Controller（显存控制器）及相应显存通道。Copy Engine（复制引擎）承担数据搬运，可用数量及其他引擎按 Profile 而异。这个分片模型不推广到其他 GPU。

MIG 全称 Multi-Instance GPU（多实例 GPU）。GI 是 GPU Instance（GPU 实例），CI 是 Compute Instance（计算实例）。CI 在父 GI 内进一步切分 SM，仍使用父 GI 所获的显存与引擎。[MIG 官方 Profile 表](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/supported-mig-profiles.html)

## 2. Profile 描述实例配置与资源关系 {#_2-profile-不只是显存数字}

在 A100 40GB 的历史示例中，`3g.20gb` 描述一个特定 GI 配置；如果进一步分 CI，可能出现 `1c.3g.20gb` 等名称。这里的 20GB 指父 GI 相关容量，而不是每个 CI 又额外生成 20GB。

即使名称相同或相近，也应查询目标设备：型号、容量和驱动不同，可用的 profile、放置位置及媒体引擎能力都可能不同。profile ID 与 instance ID 不是同一概念。[MIG Device Names](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/mig-device-names.html)

| 资源           | A100 40GB 的 `3g.20gb` GI                            | `1c.3g.20gb` CI                                  |
| -------------- | ---------------------------------------------------- | ------------------------------------------------ |
| 计算           | 3 个 SM 切片，官方示例为 42 SM                       | 1 个计算切片，其他 CI 使用各自子集               |
| 显存容量和带宽 | 4/8 显存切片，名义容量 20 GB，相关 L2 和显存路径分区 | 同一 GI 内共享父资源，两个 CI 也只共享这一份容量 |
| 复制等引擎     | 按 GI Profile 分配                                   | 同 GI 内共享相关引擎，可发生争用                 |

Profile ID 标识规格，Instance ID 标识创建出来的对象，Placement（放置位置）描述它占据的切片起点和跨度。物理 GPU UUID 用于关联卡，MIG UUID 用于关联当前实例，重建后重新发现。比如官方 A100 40GB 示例中 `3g.20gb` 可在起点 0 或 4 占连续 4 个放置槽。若两个候选区间都被其他实例占到一部分，即使全卡累计仍有 4 个空槽，也没有满足该 Profile 的位置。先比较 `-lgipp` 所列位置和 `-lgi` 的实际布局，再规划创建顺序。官方 3-2-1-1 示例还记录了需要先列出 `3g.20gb` 的 API 已知问题。[官方布局示例](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/getting-started-with-mig.html#instance-geometry)

## 3. 资源隔离与共享故障域 {#_3-隔离-需要说明隔离什么}

MIG 能提供比普通进程共享更明确的硬件资源边界，但共享的物理卡、驱动、主机和外部电源并不会消失。驱动或整卡级故障仍应单独纳入风险模型；不能承诺“任何进程崩溃绝不会影响其他实例”。

硬件分区不意味着性能会随切片数线性变化。不同工作负载受显存、SM、复制引擎或互连影响的程度不同，需要在相应 profile 下测量，不能仅按显存大小折算所有吞吐。

假设推理服务 A、B 分属两个 GI，A 的模型权重与 KV Cache 受 A 的实例容量约束，B 不会与 A 争用同一 GI 的显存切片。若两者改为同一 GI 的两个 CI，计算资源仍各有归属，显存容量、带宽、L2 与相关引擎则可互相影响。进程的 CUDA 虚拟地址空间按 Context 和访问契约管理，共享容量不授权另一个进程访问指针。整卡复位、驱动、主机、外部互连、供电和散热仍是共同影响因素。硬件分区也不会让计算、带宽和业务吞吐按同一个比例缩放。

## 4. 版本差异

[支持的 GPU](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/supported-gpus.html)

R570 与 CUDA 12 的枚举路径允许单个进程从多个 GI 枚举设备，但每个 GI 最多选择一个 CI，最多枚举 64 个 MIG 实例，还要核对进程文件描述符上限。R570 之前的文档限制单个 CUDA 进程枚举一个 MIG Device。旧 R450/R460 形式使用 `MIG-<GPU-UUID>/<GI-ID>/<CI-ID>`（其中 GPU UUID 自带 `GPU-` 前缀），自 R470 起可使用独立 `MIG-<UUID>`。用 `CUDA_VISIBLE_DEVICES` 指定实际实例，容器还受设备注入范围限制。进程内 `cuda:0` 是可见集合的序号，记录映射时使用 UUID 和父 GI/CI。[MIG Device Names](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/mig-device-names.html)

## 5. 分层查阅 P2P、IPC、RDMA 与 NCCL 支持 {#_5-mig-通信支持矩阵必须拆层}

| 机制                                                             | GPU、拓扑与版本                        | 支持与限制                                                                                                                           |
| ---------------------------------------------------------------- | -------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ |
| P2P（Peer-to-Peer，对等访问）                                    | MIG 部署指南以 R570 为边界             | 仅同一物理 GPU 上的 MIG 实例间属于该支持范围。不同物理 GPU 的 MIG P2P、MIG 与非 MIG GPU 的 P2P 不支持。不能据此推导 NVLink P2P 可用  |
| CUDA IPC（Inter-Process Communication，进程间通信）              | 按 MIG 部署指南及目标 CUDA/驱动组合    | 同 GI 的 CI 间有支持说明，跨 GI 不支持                                                                                               |
| GPUDirect RDMA（Remote Direct Memory Access，远程直接内存访问）  | 受支持的 GI、网卡、驱动与拓扑          | 部署指南列出 GI 支持，仍须验证具体 RDMA 路径及设备配置                                                                               |
| NCCL（NVIDIA Collective Communications Library，集合通信库）旧版 | 2.31 之前                              | 无此 MIG communicator 支持，R580 版 MIG 指南的“不支持”用于这一历史边界                                                               |
| NCCL MIG communicator                                            | 自 2.31 起，核对 2.31.2 与 2.32.3 归档 | **实验性**。要求 CUDA Driver 版本至少 13.0，每个 rank 选择不同的 MIG Device，设置 `NCCL_MNNVL_ENABLE=0`，不使用 NVLink SHARP（NVLS） |

CUDA Driver 13.0 是驱动所提供的 CUDA 能力要求，应按目标 NVIDIA 驱动及平台的兼容表核对，不能用已安装 Toolkit 版本替代。例如 CUDA 13.0 GA 发布说明列出的 Linux 基线是 580.65.06，实际部署仍须满足 GPU 与驱动的要求。[CUDA 13.0 GA 驱动表](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/index.html)NCCL 文档未给出所有 MIG 架构和拓扑的覆盖承诺。2.31 记录的验证范围是最多 8 张 GPU、每张 7 个 MIG 实例，运行典型 `nccl-tests` 集合通信。文档未将这项结果确认为任意多节点网络的支持范围。跨物理 GPU 的集合通信即使通过其他传输完成，也不能证明跨物理 GPU 的 MIG P2P 可用。逐项记录 GPU、驱动、CUDA、NCCL、实例 UUID、rank、实际传输及节点拓扑，先小规模验证正确性，再验证吞吐和故障处理。

归档手册按版本固定。NVIDIA 的发布页分别记录了 [2.31.2-1（2026-08-11）](https://github.com/NVIDIA/nccl/releases/tag/v2.31.2-1) 和 [2.32.3-1（2026-09-17）](https://github.com/NVIDIA/nccl/releases/tag/v2.32.3-1)。

[MIG Deployment Considerations](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/deployment-considerations.html) · [R580 历史指南](https://docs.nvidia.com/datacenter/tesla/pdf/MIG_User_Guide.pdf) · [NCCL 2.31.2 归档](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2312/user-guide/docs/usage/communicators.html#using-mig-instances) · [NCCL 2.32.3 归档](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2323/user-guide/docs/usage/communicators.html#using-mig-instances)

## 6. 两个推理服务的隔离实验

在获准使用的实验节点上，先确认 A、B 绑定不同 GI 且模型能装入各自显存。固定 A100 40GB、GI/CI Profile、驱动、框架、批处理和采样方式。分别测 A 单跑、B 单跑及 A/B 同跑，依次改变一个服务的输入长度、并发或计算/内存负载。对同一服务比较吞吐、P50/P95/P99、显存、可用的 GPU/SM 活动指标和错误率。不同 GI 的活动按实体读取，避免把整卡数据当作单个服务数据。若同跑仍出现尾延迟上升，检查主机、外部 I/O、功耗和应用队列。这里是验证设计，未在设备上运行。布局与安全操作见[第 14 章](/articles/ai-infra-mig-operations.html)。
