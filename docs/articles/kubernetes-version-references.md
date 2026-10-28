---
id: kubernetes-version-references
title: 附录 A　版本依据与特性门控
description: "本册主要复盘 Linux Kubernetes 1.28，不是面向当前最新版本的安装手册。下表集中列出讨论版本、API、门控、实现前提和证据位置；各章只展开与主题有关的差异。"
date: '2026-10-25'
updated: '2026-10-28'
category: engineering
type: reference
tags:
  - kubernetes
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kubernetes
series: kubernetes-learning
order: 90
---

# 附录 A　版本依据与特性门控

[返回本册目录](/collections/kubernetes/)

本册主要复盘 Linux Kubernetes 1.28，不是面向当前最新版本的安装手册。下表集中列出讨论版本、API、门控、实现前提和证据位置；各章只展开与主题有关的差异。

## 1. 怎样阅读版本证据

`v1.28.0` 等 tag 固定了本册核对的源码版本，不等于真实集群必然运行该补丁版本；需要更严格归档时，还可记录解析后的 commit。`release-1.28` 是历史文档分支，仍可能修订，不等于当年的不可变快照。当前概念文档只用于明确注明的稳定机制，不用于证明后来新增字段在 1.28 可用。

## 2. 章节的版本与前提

| 章节                   | 讨论版本 / API                                         | 关键门控或实现前提                                         | 证据定位                                                                                                                                                                          |
| ---------------------- | ------------------------------------------------------ | ---------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1—5 架构和控制平面     | Kubernetes 1.28；核心 v1 等                            | 高可用、存储和认证取决于实际配置                           | 各章版本源码及概念链接，不将图当成完整同步时序                                                                                                                                    |
| 6 调度                 | v1.28.0 调度框架实现                                   | 插件、调度配置与队列行为按该版本                           | [固定版本 framework 接口](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/scheduler/framework/interface.go)                                                             |
| 7 探针                 | 1.28，core/v1 Pod                                      | 端口、应用探针语义、节点运行时                             | [1.28 Pod 生命周期](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/pods/pod-lifecycle.md)                                   |
| 8 运行时               | containerd 1.7；CRI v1                                 | 实际二进制和配置未复测；参数举例固定 v1.7.0                | 正文的 v1.7.0 pull/export 源码；架构资料使用 release/1.7 分支并明确其可变性                                                                                                       |
| 9—11 网络              | 1.28，networking.k8s.io/v1、discovery.k8s.io/v1        | CNI 策略执行能力、DNS 实现及流量策略                       | 正文的 1.28 文档；EndpointSlice 条件另由 v1.28.0 类型和控制器交叉核对                                                                                                             |
| 12—14 对象和资源       | 1.28，core/v1、apps/v1、policy/v1                      | 默认化、普通 init、RuntimeClass overhead；sidecar 另看下表 | v1.28.0 QoS 源码、1.28 资源与 init 文档                                                                                                                                           |
| 15—18 工作负载         | 1.28，apps/v1、batch/v1                                | 更新预算、PVC 门控及作业幂等分别处理                       | [v1.28.0 apps/v1](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/apps/v1/types.go)                                                        |
| 19—23 服务配置和存储   | 1.28；core/v1、networking.k8s.io/v1、storage.k8s.io/v1 | 控制器、供应器、CSI/NFS 和应用重载能力                     | 各章历史文档；NFS 手册不代表原环境版本已核实                                                                                                                                      |
| 24—25 调度约束与 HPA   | 1.28，autoscaling/v2                                   | 指标 API、request、行为策略和门控                          | [1.28 HPA 算法](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/run-application/horizontal-pod-autoscale.md)；异构 request 聚合实现待补证 |
| 26—30 管理、权限和排障 | 1.28；Helm 3 单独处理                                  | 客户端版本、有效身份、准入配置                             | 各章公开 API 和工具资料；命令没有运行                                                                                                                                             |
| 31 设备插件            | v1.28.0 deviceplugin/v1beta1                           | 厂商驱动、资源单位与设备共享能力                           | v1.28.0 API、资源 helper 与 validation 源码                                                                                                                                       |
| 32 DRA                 | 1.28 早期 resource.k8s.io/v1alpha2；1.32 对照另列      | 两代模型不能混写，驱动和门控需匹配                         | 正文保留 1.28 与 v1.32.0 的分开证据                                                                                                                                               |
| 33 云集成              | 1.28 职责背景                                          | 具体云提供者、CSI、权限和集成实现                          | 概念资料说明职责，不承诺任意厂商的自动化行为                                                                                                                                      |

## 3. v1.28.0 的关键门控

| 特性                      | 阶段  | 上游默认 | 本册使用方式                                |
| ------------------------- | ----- | -------- | ------------------------------------------- |
| SidecarContainers         | Alpha | false    | 普通 init 章节不套用可重启 sidecar 语义     |
| MaxUnavailableStatefulSet | Alpha | false    | 不把该字段写成无条件通用能力                |
| StatefulSetAutoDeletePVC  | Beta  | true     | 分开 whenDeleted 与 whenScaled，默认 Retain |
| DynamicResourceAllocation | Alpha | false    | 1.28 早期 DRA 与后续结构化模型分开          |

以上来自 [v1.28.0 kube_features.go](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)。实际集群可能覆盖上游默认值；对于同一功能，还需确认相关组件的门控配置和 API 可用性。

## 4. 从版本依据到实际环境验证 {#_4-本册没有替代哪些验证}

版本表用于定位文档、源码和门控条件。复现时还需记录实际发行版、内核、containerd、CNI、CoreDNS、存储与设备驱动，再依次验证服务端 schema、调度、运行和故障恢复。各章教学数字为纸面算例，实际性能需要单独测量。
