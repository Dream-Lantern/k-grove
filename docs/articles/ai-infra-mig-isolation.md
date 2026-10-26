---
id: ai-infra-mig-isolation
title: 第 13 章 MIG 原理：GI、CI 与隔离的粒度
description: 把一张卡切成几个可分配的设备，和给几个进程设置百分比配额，是两种不同思路。MIG（Multi-Instance GPU）基于受支持硬件划分相应资源，本章先说明切分边界，再讨论操作。
date: '2026-10-25'
updated: '2026-10-25'
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

把一张卡切成几个可分配的设备，和给几个进程设置百分比配额，是两种不同思路。MIG（Multi-Instance GPU）基于受支持硬件划分相应资源，本章先说明切分边界，再讨论操作。

## 1. GI 与 CI 的包含关系

GI（GPU Instance）由一定的计算、内存及相关引擎资源组成。一个 GI 可以进一步划分 CI（Compute Instance）；同一 GI 下的 CI 划分计算资源，但共享父 GI 的相应内存和引擎资源。因此，两个 CI 不能被描述为拥有两份完全独立的 GI 显存。[MIG Concepts](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/concepts.html)

![MIG 资源包含与共享边界](/assets/notes/ai-infra/mig-boundaries.svg)

图中是逻辑示意，不按某款产品的精确比例绘制。“显存固定八等分、计算固定七等分”有 A100 等特定产品语境，不能推广到所有 MIG GPU。

## 2. Profile 不只是显存数字

在 A100 40GB 的历史示例中，`3g.20gb` 描述一个特定 GI 配置；如果进一步分 CI，可能出现 `1c.3g.20gb` 等名称。这里的 20GB 指父 GI 相关容量，而不是每个 CI 又额外生成 20GB。

即使名称相同或相近，也应查询目标设备：型号、容量和驱动不同，可用的 profile、放置位置及媒体引擎能力都可能不同。profile ID 与 instance ID 不是同一概念。[MIG Device Names](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/mig-device-names.html)

## 3. “隔离”需要说明隔离什么

MIG 能提供比普通进程共享更明确的硬件资源边界，但共享的物理卡、驱动、主机和外部电源并不会消失。驱动或整卡级故障仍应单独纳入风险模型；不能承诺“任何进程崩溃绝不会影响其他实例”。

硬件分区不意味着性能会随切片数线性变化。不同工作负载受显存、SM、复制引擎或互连影响的程度不同，需要在相应 profile 下测量，不能仅按显存大小折算所有吞吐。

## 4. 版本差异

[支持的 GPU](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/supported-gpus.html)

## 5. MIG 通信支持矩阵必须拆层

| 组合或层次                         | 官方文档所列边界              | 本册处理                                 |
| ---------------------------------- | ----------------------------- | ---------------------------------------- |
| R570，同物理 GPU 的 MIG 实例间 P2P | 给出同卡支持范围              | 仍核对具体实例与驱动条件                 |
| 不同物理 GPU 的 MIG P2P            | 该说明仍列为不支持            | 不按普通 NVLink 拓扑推定可用             |
| 跨 GI / CI 的 CUDA IPC             | 文档列跨 GI 不支持、CI 间支持 | 不把 P2P 结论当 IPC 结论，仍检查实例关系 |
| GPUDirect RDMA                     | GI 使用有支持说明             | 不据此推导 NCCL 支持                     |
| NCCL with MIG                      | 当前说明明确列为不支持        | 不推荐为受支持的多卡训练部署             |

[MIG Deployment Considerations](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/latest/deployment-considerations.html)
