---
id: kubernetes-dra
title: 第三十二章 DRA：版本边界与设备分配
description: Dynamic Resource Allocation 尝试通过资源申领与驱动协作来表达更复杂的设备需求。安装一个插件，并不会让所有硬件自动具备相同的分区和共享能力。
date: '2026-10-25'
updated: '2026-10-25'
category: engineering
type: explanation
tags:
  - kubernetes
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kubernetes
series: kubernetes-learning
order: 32
---

# 第三十二章 DRA：版本边界与设备分配

> 本册主线是 Kubernetes 1.28。原 DRA 笔记混有后续版本的对象和推断，本章按历史模型与后续对照拆开，不提供跨版本混用清单，也未启用 DRA 或安装驱动。

## 1. 先确定讨论的是哪一代模型

Dynamic Resource Allocation 尝试通过资源申领与驱动协作来表达更复杂的设备需求。安装一个插件，并不会让所有硬件自动具备相同的分区和共享能力。

1.28 的官方说明将 DRA 标为 Alpha，要求显式启用相关能力并具备资源驱动等条件。“默认开启即可使用”遗漏了默认状态、API 和实现前提。

![DRA 历史模型、后续对象与驱动条件的阅读边界](/assets/notes/kubernetes/k8s-dra-version-boundary.svg)

## 2. 1.28：ResourceClass 与早期协调模型

1.28 文档中的 `resource.k8s.io/v1alpha2` 包含 ResourceClass、ResourceClaim、ResourceClaimTemplate 和 PodSchedulingContext 等对象。

ResourceClass 描述相应资源驱动及公共参数关联；ResourceClaim 表达具体资源需求；Template 用于形成申领；PodSchedulingContext 参与适用的调度与分配协调。参数对象和分配由相应驱动等机制处理，不能照搬后来由结构化设备信息参与选择的完整流程。

直接引用已有 Claim 与引用 Template 的生命周期也不同：前者可由使用者管理并用于适用共享场景，后者可为对应 Pod 形成申领。是否能共享实际硬件仍取决于驱动和资源模型。

以上历史范围以 [Kubernetes 1.28 DRA 文档](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/scheduling-eviction/dynamic-resource-allocation.md)为依据。这里不提供未经实测的完整示例，以免读者误以为普通 1.28 集群已经具备相关支持。

## 3. 后续对照：DeviceClass 与 ResourceSlice

后来的结构化模型使用 DeviceClass、ResourceSlice 等表达设备类别、资源池和设备信息，并让申领与相应选择机制协作。它们不能填进前一节的 1.28 旧清单。

可以在 [v1.32.0 resource/v1beta1 类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.32.0/staging/src/k8s.io/api/resource/v1beta1/types.go)中核对这一组对象定义。该源码用于版本对照，不等于声明所有后续 DRA 能力在 1.32 都稳定、默认启用或完全兼容。

阅读一篇 DRA 实践时，至少记录 Kubernetes 次版本、API 版本、特性门控、驱动和客户端版本。只写“支持 DRA”不足以判断清单是否可用，也不能把当前文档的状态反推成历史状态。

## 4. 分配决定与节点准备

资源分配结果、Pod 选择节点和节点侧设备准备是相关但不同的环节。后续节点服务中的 `NodePrepareResources` 与 `NodeUnprepareResources` 名字要准确；原文的 UnNodePrepareResources 不应继续作为接口名。

节点准备可以为运行时提供适用的设备配置信息。CDI 标识也不能一律解释为 UUID：其命名与设备配置格式有专门约定，需要与对应运行时和驱动版本核对。

“申领已经分配”不保证节点准备和应用访问必然成功。驱动、节点状态和外部依赖还可能失败，需要重试、清理与故障恢复设计；图中不再承诺一定避开所有硬件准备冲突。

## 5. 共享、分区与性能不能靠抽象名字推断

DRA 的申领和共享语义，不自动等同于 GPU 任意比例切分。设备是否支持分区、何时准备、隔离程度及共享限制，都需要硬件和驱动实现。

原笔记“DRA 调度效率比 Device Plugin 低得多”的结论缺少集群规模、版本、设备、请求模式与测量口径，本稿将其保留为待验证问题，不写成公开事实。“1.32 存在一致性问题”的笼统说法同样需要具体问题链接、复现与修复版本，不能扩大为整代实现的定论。

比较应针对相同的业务约束：设备选择能力、准备和清理、可观测性、失败处理、调度延迟与运维成本。先满足功能和隔离需求，再用同口径实验评估开销。

## 6. 这一章怎样用于 1.28 复盘

复盘普通 1.28 环境时，先理解并确认经典设备插件路径；涉及早期 DRA 的历史实验，则按第二节的版本资料复核。后续模型保留为拓展阅读，不将其写成历史教程中已部署成功的内容。

未来若要升级实践，应另开固定环境的验证记录，检查 API 迁移、驱动兼容和资源生命周期。本次仅整理文字与图源，没有升级或启用特性，也没有为未验证的硬件场景编造实验。

[返回本册目录](/collections/kubernetes/)
