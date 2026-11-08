---
id: ai-infra-multi-gpu-nccl
title: 第 22 章 多 GPU 与 NCCL：并行策略和通信契约
description: "区分 DP、TP、PP 等并行维度，联系每卡显存、通信缓冲与 NCCL 集合通信，理解多卡配置和定位方法。"
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
order: 22
---

# 第 22 章 多 GPU 与 NCCL：并行策略和通信契约

## 1. 四种并行维度

| 策略          | 主要切分对象           | 常见成本               |
| ------------- | ---------------------- | ---------------------- |
| 数据并行 DP   | 不同输入，模型通常复制 | 梯度同步、模型副本内存 |
| 张量并行 TP   | 一个算子的张量计算     | 层内频繁通信           |
| 流水线并行 PP | 不同模型阶段           | 调度气泡、激活传递     |
| 专家并行 EP   | 不同专家及其 token     | 分发、负载不均、回收   |

这些维度可以组合，不能把四张 TP 卡当作四个 DP 副本重复计算全局 batch。并行方式还会影响每卡权重、KV 和通信缓冲区的预算，不能只把总显存除以卡数。

[![多 GPU：集合通信的匹配契约](/assets/notes/ai-infra/parallel-collectives.svg)](/assets/notes/ai-infra/parallel-collectives.svg)

### 四卡部署如何分工

| 配置                                     | GPU 0–3 的分工                                           | 通信与显存                                                                        |
| ---------------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------- |
| DP=4（Data Parallelism，数据并行）       | 每卡一份完整模型，分派不同请求；训练时各副本处理不同样本 | 推理各副本独立持有 KV，常规推理无梯度同步；训练通常同步梯度                       |
| TP=4（Tensor Parallelism，张量并行）     | 四卡协同处理同一批，矩阵权重沿轴分片                     | 层内要归约或汇集部分结果；每卡部分权重，KV 可能分片或复制                         |
| PP=4（Pipeline Parallelism，流水线并行） | 四卡依次持有四组层，请求或微批顺序经过各阶段             | 邻接阶段传激活；训练还回传梯度。每卡持有本阶段权重及 KV，阶段失衡与空泡降低利用率 |
| EP=4（Expert Parallelism，专家并行）     | MoE 专家放在不同卡，Router 选择后分发并回收向量          | 每卡持有部分专家，非专家层另选布局；通信与热点取决于路由                          |

例如 GPU 0/1 与 GPU 2/3 各组成一个 TP=2 副本，此时 DP=2，两个请求组各用两张卡。训练 DP 梯度同步应在对应的分片副本之间做，推理在两个副本之间分派请求。7B 模型的权重、KV 和缓冲应按每个 rank 的实际布局核算。EP 的分发算例见[第 21 章](/articles/ai-infra-mixture-of-experts.html)。

## 2. NCCL 集合操作与 Rank 的匹配契约 {#_2-nccl-提供什么}

NCCL 为 GPU 间通信提供集合操作等能力。AllReduce 将归约结果返回给各 rank；AllGather 汇集各 rank 数据；ReduceScatter 将归约结果按 rank 分发。rank 是通信组中的编号，不等于永远固定的物理 GPU 索引。

参与同一集合操作的各 rank 必须遵守匹配的调用与数据契约。某 rank 提前报错或使用不匹配的 count、datatype、操作顺序，其他 rank 可能等待，并不说明网络一定坏了。[NCCL Collective Operations](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/usage/collectives.html)

NCCL（NVIDIA Collective Communications Library，集合通信库）以 Communicator（通信器）定义成员与顺序。World Size 是该组成员数，Rank 是组内从零开始的逻辑编号；Local Rank 通常由启动器赋予节点内进程。子通信组的 rank 可与全局 rank 不同。下表为两节点、一进程一卡的逻辑示意，UUID 用别名代替。

| Node | Process | Global Rank | Local Rank | GPU UUID |
| ---- | ------- | ----------: | ---------: | -------- |
| A    | A0      |           0 |          0 | GPU-A0   |
| A    | A1      |           1 |          1 | GPU-A1   |
| B    | B0      |           2 |          0 | GPU-B0   |
| B    | B1      |           3 |          1 | GPU-B1   |

每进程按可见设备表选择 CUDA Device，CUDA Context 持有该设备的运行状态，CUDA Stream（流）组织 GPU 工作及依赖。跨流消费结果需要事件或相应同步。NCCL 常规集合调用将工作提交到指定流，Host 返回只表示提交阶段推进。用流完成状态判断结果可用，并用 `ncclCommGetAsyncError` 等检查异步通信错误。2.32.3 的线程安全指南要求避免多线程并发操作同一通信器，也应避免多个线程并发操作同设备上的独立通信器。单线程驱动多设备时，相关调用用 `ncclGroupStart/End` 成组提交，避免首个 rank 等待其余尚未提交的 rank。[通信器与异步错误](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2323/user-guide/docs/usage/communicators.html) · [线程安全](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2323/user-guide/docs/usage/threadsafety.html) · [Group Calls](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2323/user-guide/docs/usage/groups.html)

### 三 Rank 的数值推演

| 操作                          | Rank 0 / 1 / 2 输入                                             | 输出                                                                                         | API 的 Count                       |
| ----------------------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ---------------------------------- |
| Sum AllReduce（全归约）       | [1,2] / [3,4] / [5,6]                                           | 每 rank 均为 [9,12]                                                                          | 输入与输出各 2 个元素              |
| AllGather（全收集）           | [1,2] / [3,4] / [5,6]                                           | 每 rank 均为 [1,2,3,4,5,6]，按 rank 排列                                                     | 每 rank 发送 2 个元素，各接收 6 个 |
| Sum ReduceScatter（归约分散） | [1,2,3,4,5,6] / [10,20,30,40,50,60] / [100,200,300,400,500,600] | 先按位置求和得 [111,222,333,444,555,666]，各 rank 依次接收 [111,222] / [333,444] / [555,666] | 每 rank 接收 2 个元素，各提供 6 个 |

Count 以元素计，所有参与者应匹配集合调用的类型、数据类型、计数、适用的归约操作与顺序。归约分散后再全收集能组合出相同数学结果的全归约。Ring 或 Tree 属于实际算法选择，通信量、拓扑及消息尺寸会影响选择，浮点归约顺序也可能改变末位。[集合通信与 API 语义](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2323/user-guide/docs/usage/collectives.html)

## 3. 互连与可达性

同节点卡可能经 PCIe、NVLink/NVSwitch 等路径通信；跨节点还涉及 NIC、网络和可能的 RDMA。拓扑和亲和性会影响性能，但不能由“机箱里有 NVLink”推断每个设备对都直接互连。

MIG、虚拟机和容器还可能限制可用通信路径。

PCIe（Peripheral Component Interconnect Express）将设备接入主机，NVLink 是 NVIDIA GPU 高速互连，NVSwitch 在支持的系统上为 NVLink 提供交换。GPUDirect P2P（Peer-to-Peer）允许可达 GPU 直接访问对端设备内存。跨节点经 GPU → NIC（Network Interface Card，网卡）→ 网络 → NIC → GPU；RDMA（Remote Direct Memory Access，远程直接内存访问）可由网卡直接操作远端注册内存，GPUDirect RDMA 在兼容配置下允许 NIC 访问 GPU 内存。GPU/NIC 跨 PCIe Root Complex 或 NUMA（Non-Uniform Memory Access，非一致性内存访问）节点，可能多走主机互连或受限于可达性。

```bash
nvidia-smi -L
nvidia-smi topo -m
```

先按 UUID 对齐设备。若 GPU 0/1 显示 NVLink 路径，而 GPU 0/2 显示跨 NUMA 的 SYS 路径，应分别测量；同样核对 NIC 和 CPU 亲和性，拓扑矩阵只表明路径类别。小消息常受启动时延影响，大消息更受链路带宽、协议和争用影响。[NVIDIA SMI 拓扑文档](https://docs.nvidia.com/deploy/nvidia-smi/index.html) · [GPUDirect RDMA](https://docs.nvidia.com/cuda/gpudirect-rdma/)

## 4. 从最先失败的 Rank 排查多卡挂起 {#_4-如何排查多卡挂起}

应先保留所有 rank 的日志，找到最先出错或未进入集合调用的进程，再核对 world size、rank 映射、调用顺序、网络接口和设备可见性。只检查最后仍在等待的进程，会将根因错判为“通信库卡住”。

`NCCL_DEBUG=INFO` 等诊断变量可以增加日志，但也会影响日志量与运行开销，应按目标版本验证，并在定位后恢复。关闭某种传输路径的临时 workaround，不应成为面向所有生产环境的推荐配置。[NCCL 环境变量](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/env.html)

例如第 17 次 AllReduce 中 Rank 0–2 已进入，Rank 3 的上一项 CUDA kernel 报错后未进入。前三个 rank 因缺少参与者而等待；异步 CUDA 错误可能到后续 API 才显现。按节点时间和调用序号合并所有 rank 日志，先核对 Rank 3 的首条异常，再比对 communicator、World Size、Rank→UUID、操作序列、Count 和 Datatype。契约无异常时，核对 Xid、链路或 NIC 错误、节点连通性和所选传输。对照 NCCL 2.32.3，短时使用 `NCCL_DEBUG=INFO`、`NCCL_DEBUG_SUBSYS=INIT,COLL,NET`。应用需区分框架超时与 NCCL 异步错误，失败后按应用策略协调中止受影响通信器并回收，避免单个 rank 在旧通信器上继续。[NCCL 2.32.3 环境变量](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2323/user-guide/docs/env.html)

## 5. MIG 场景的通信库支持范围 {#_5-回链-mig-支持状态-而非只验证链路可达}

NCCL 2.31 之前缺少 MIG communicator 支持。自 2.31 起支持多个不同 MIG 实例组成通信器，2.31.2 与 2.32.3 归档均标为实验性。每个 rank 要选不同的 MIG Device，CUDA Driver 所提供的 CUDA 能力至少为 13.0，设置 `NCCL_MNNVL_ENABLE=0`，MIG 路径不使用 NVLink SHARP（NVLS）。Toolkit 版本不能替代驱动能力判断。2.31 文档记录的验证范围为最多 8 GPU、每 GPU 7 个 MIG 实例和典型 nccl-tests 集合操作。具体 GPU、实例及节点拓扑要按实际路径验证，尤其是多节点和大规模部署。通信器能工作与某一 MIG P2P 路径可用属于两项验证。[第 13 章 MIG 通信支持矩阵](/articles/ai-infra-mig-isolation.html) · [NCCL 2.31.2](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2312/user-guide/docs/usage/communicators.html#using-mig-instances) · [NCCL 2.32.3](https://docs.nvidia.com/deeplearning/nccl/archives/nccl_2323/user-guide/docs/usage/communicators.html#using-mig-instances)

## 6. 最小通信验收方案

在授权的 Linux 四卡隔离节点执行，先记录 GPU 型号与 UUID、驱动、CUDA、NCCL 2.32.3、NIC/互连、环境变量和工具 commit。使用 nccl-tests 2.17.9（commit `2535da805b34e96d1dc08be66289be1a6d57f5ad`），按 README 指定 CUDA_HOME 和 NCCL_HOME 编译，固定二进制与动态链接库；先验证全卡 GPU，MIG 另按上节条件单独对照。以下未执行。

```bash
./build/all_reduce_perf -b 8 -e 64M -f 2 -g 2 -c 1
./build/all_reduce_perf -b 8 -e 64M -f 2 -g 4 -c 1
./build/all_gather_perf -b 32 -e 64M -f 2 -g 4 -c 1
./build/reduce_scatter_perf -b 32 -e 64M -f 2 -g 4 -c 1
```

单进程以 `-g` 指定 GPU 数，按实际输出确认设备映射。逐消息尺寸记录时间、algbw、busbw 和错误计数，正确性要求校验错误数为零、退出成功且没有超时。若失败，先区分映射或契约错误、设备错误、传输初始化及慢链路。带宽阈值由相同拓扑基线设定。[NVIDIA nccl-tests](https://github.com/NVIDIA/nccl-tests/blob/2535da805b34e96d1dc08be66289be1a6d57f5ad/README.md)
