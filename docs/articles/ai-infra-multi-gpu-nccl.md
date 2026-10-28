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

## 2. NCCL 集合操作与 Rank 的匹配契约 {#_2-nccl-提供什么}

NCCL 为 GPU 间通信提供集合操作等能力。AllReduce 将归约结果返回给各 rank；AllGather 汇集各 rank 数据；ReduceScatter 将归约结果按 rank 分发。rank 是通信组中的编号，不等于永远固定的物理 GPU 索引。

参与同一集合操作的各 rank 必须遵守匹配的调用与数据契约。某 rank 提前报错或使用不匹配的 count、datatype、操作顺序，其他 rank 可能等待，并不说明网络一定坏了。[NCCL Collective Operations](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/usage/collectives.html)

## 3. 互连与可达性

同节点卡可能经 PCIe、NVLink/NVSwitch 等路径通信；跨节点还涉及 NIC、网络和可能的 RDMA。拓扑和亲和性会影响性能，但不能由“机箱里有 NVLink”推断每个设备对都直接互连。

MIG、虚拟机和容器还可能限制可用通信路径。

## 4. 从最先失败的 Rank 排查多卡挂起 {#_4-如何排查多卡挂起}

应先保留所有 rank 的日志，找到最先出错或未进入集合调用的进程，再核对 world size、rank 映射、调用顺序、网络接口和设备可见性。只检查最后仍在等待的进程，会将根因错判为“通信库卡住”。

`NCCL_DEBUG=INFO` 等诊断变量可以增加日志，但也会影响日志量与运行开销，应按目标版本验证，并在定位后恢复。关闭某种传输路径的临时 workaround，不应成为面向所有生产环境的推荐配置。[NCCL 环境变量](https://docs.nvidia.com/deeplearning/nccl/user-guide/docs/env.html)

## 5. MIG 场景的通信库支持范围 {#_5-回链-mig-支持状态-而非只验证链路可达}

第 13 章列出了当前官方文档仍不支持 NCCL with MIG 的边界。
