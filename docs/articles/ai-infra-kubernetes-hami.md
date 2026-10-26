---
id: ai-infra-kubernetes-hami
title: 第 16 章 Kubernetes GPU 资源与 HAMi 调度链
description: Kubernetes 把 Pod 放到某个节点，不等于它天然理解每张 GPU 的剩余显存、拓扑和百分比配额。GPU 能力来自设备插件、调度扩展及运行时等组件的配合。
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
order: 16
---

# 第 16 章 Kubernetes GPU 资源与 HAMi 调度链

Kubernetes 把 Pod 放到某个节点，不等于它天然理解每张 GPU 的剩余显存、拓扑和百分比配额。GPU 能力来自设备插件、调度扩展及运行时等组件的配合。

## 1. 普通设备插件负责什么

设备插件向 kubelet 注册并上报设备健康状态，kubelet 据此发布扩展资源；容器准备阶段再进行设备分配和相应运行配置。`nvidia.com/gpu: 1` 在普通整卡模式中是设备资源请求，不能直接解释为“1% GPU”。NVIDIA 插件还提供 MIG、time-slicing、MPS 等有各自条件的共享模式。[NVIDIA Kubernetes Device Plugin](https://github.com/NVIDIA/k8s-device-plugin)

## 2. HAMi 把调度与容器内控制分开

![HAMi 主要协作链](/assets/notes/ai-infra/hami-scheduling.svg)

图示为典型架构，不锁定某个 commit 的函数顺序。Webhook 修改有关 Pod 配置；调度组件结合节点/设备状态选择位置；kubelet 与设备插件准备设备及注入配置；容器内控制层落实对应策略。Pod 已绑定节点，不意味着镜像、设备配置和业务启动都成功。

## 3. 一个明确标版本的资源片段

以下依据 HAMi v2.10.0 文档，仅为容器资源字段片段，不是完整可部署 Pod；本次没有安装 HAMi，也没有提交资源。

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
    nvidia.com/gpumem: 3000
    nvidia.com/gpucores: 50
```

在默认 `memoryFactor: 1` 下，`gpumem: 3000` 表示每个申请设备的 3000 MiB 配额，使用普通整数，不附 `Mi`/`Gi`。字段和单位取决于版本及配置，不能直接套到普通 NVIDIA 插件。[HAMi 显存分配](https://project-hami.io/docs/userguide/nvidia-device/specify-device-memory-usage)

`gpucores` 也不能解释为“独占一半 SM”，而是代表限制的算力。[HAMi core usage](https://project-hami.io/docs/userguide/nvidia-device/specify-device-core-usage)

## 4. Binpack、Spread 与拓扑

binpack 倾向于集中资源，便于保留空卡；spread 倾向于分散资源，可以减少部分争抢，但也可能增加碎片。多卡任务还需考虑 NUMA、PCIe 和 NVLink 连接。

## 5. 按阶段排查 Pending 和启动失败

先检查 admission 是否生效，再看调度事件和资源余量；绑定后则转向设备插件、runtime、注入库及应用错误。不要把 admission 成功、绑定成功、分配成功、资源限制有效当作同一个验收结果。对 Kubernetes 1.28 的复盘，保持设备插件/调度扩展语境，不把新版本 DRA 能力写成当年的默认行为。

## 6. 调度控制面与节点执行面分开读

![HAMi 控制与节点执行双平面](/assets/notes/ai-infra/hami-control-node.svg)

| 阶段                | 应检查的证据                   | 成功后仍未证明         |
| ------------------- | ------------------------------ | ---------------------- |
| Admission           | 返回变更与最终 Pod 配置        | 一定有可用 GPU         |
| 节点/设备选择与绑定 | 调度事件、分配元数据与节点     | Allocate 必定成功      |
| Allocate            | 设备、库和环境等分配结果       | 应用 CUDA 初始化成功   |
| 容器执行            | 真实库路径、限制效果和业务输出 | 已达到硬隔离或性能 SLO |

`/etc/ld.so.preload` 文件与 `LD_PRELOAD` 环境变量是不同注入入口。
