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

| 章节                   | 讨论版本 / API                                                                                                               | 关键条件                                                 | 可复核证据                                                                                                                                                                                                                                                                                                                                                                                |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1—5 架构和控制平面     | Kubernetes 1.28；组件进程不等于 core/v1；etcd 使用独立 v3 API 与 Raft                                                        | kubeadm、认证、存储与高可用按实际配置；etcd 版本独立记录 | 见下方控制平面、kubeadm 与 etcd 固定版本资料                                                                                                                                                                                                                                                                                                                                              |
| 6 调度                 | v1.28.0 Scheduler Framework；组件配置不是 Pod API                                                                            | 插件、调度配置、队列与重试                               | [framework/interface.go](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/scheduler/framework/interface.go)                                                                                                                                                                                                                                                                      |
| 7—8 节点与运行时       | kubelet 1.28；core/v1 Probe；CRI v1；containerd 1.7                                                                          | 探针由应用实现；containerd 2.x 仅作单独差异对照          | [Probe API](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/core/v1/types.go)、[CRI proto](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/cri-api/pkg/apis/runtime/v1/api.proto)；第 8 章固定 containerd v1.7.0 工具源码                                                                                                           |
| 9—11 网络与 DNS        | CNI 规范及插件、kube-proxy 1.28、独立 CoreDNS 实现                                                                           | CNI、CRI、CSI 分别负责网络、运行时和存储；策略依赖实现   | [1.28 网络插件](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/extend-kubernetes/compute-storage-net/network-plugins.md)、[proxier.go](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/proxy/iptables/proxier.go)；CoreDNS 版本需查实际镜像                                                                                         |
| 12—14 对象、Pod 和资源 | core/v1、policy/v1；普通 init 与可重启 sidecar 区分                                                                          | 默认化、QoS、overhead、PDB 的适用驱逐边界                | [core/v1](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/core/v1/types.go)、[policy/v1](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/policy/v1/types.go)                                                                                                                                                                    |
| 15—18 工作负载         | Deployment/StatefulSet/DaemonSet 使用 apps/v1；Job/CronJob 使用 batch/v1                                                     | 更新预算、PVC 策略门控、批任务幂等                       | [apps/v1](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/apps/v1/types.go)、[batch/v1](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/batch/v1/types.go)                                                                                                                                                                      |
| 19—21 服务与配置       | core/v1 Service、ConfigMap/Secret；discovery.k8s.io/v1 EndpointSlice；networking.k8s.io/v1 Ingress                           | 端点条件、控制器实现、配置投射与应用重载分别验收         | [EndpointSlice 类型](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/discovery/v1/types.go)、[端点条件生成](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/endpointslice/utils.go)、[Ingress 类型](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/networking/v1/types.go)                            |
| 22—23 卷和持久存储     | core/v1 Volume/PV/PVC；storage.k8s.io/v1 StorageClass                                                                        | CSI、NFS、供应器及回收策略另核对；NFS 工具版本未实测     | [storage/v1](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/storage/v1/types.go)、[1.28 PV](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/persistent-volumes.md)                                                                                                                                       |
| 24—25 调度约束与 HPA   | core/v1 调度字段；autoscaling/v2 HPA                                                                                         | 指标 API、requests、缺失样本、稳定窗口与速率限制         | [HPA 类型](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/autoscaling/v2/types.go)、[GetResourceUtilizationRatio](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/controller/podautoscaler/metrics/utilization.go)、[ReplicaCalculator](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/controller/podautoscaler/replica_calculator.go) |
| 26—27 客户端与包管理   | kubectl 1.28；Helm v3.13.3 作为源码基线                                                                                      | Helm 工具与 Chart 分别固定版本，不把 Helm 4 套入         | [kubectl apply](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubectl/pkg/cmd/apply/apply.go)、[Helm upgrade](https://github.com/helm/helm/blob/v3.13.3/pkg/action/upgrade.go)                                                                                                                                                                                 |
| 28—30 身份、准入与排障 | core/v1 ServiceAccount、authentication.k8s.io/v1 TokenRequest、rbac.authorization.k8s.io/v1、admissionregistration.k8s.io/v1 | 凭据有效性、有效授权、准入结果和运行状态分层判断         | [RBAC 类型](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/rbac/v1/types.go)、[准入默认值](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/apis/admissionregistration/v1/defaults.go)                                                                                                                                                             |
| 31 Device Plugin       | deviceplugin/v1beta1 是节点 gRPC 协议，非 REST API Group/Version                                                             | 设备驱动、数量整数校验、健康、拓扑与运行时支持           | [api.proto](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1/api.proto)、[Device Manager](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/kubelet/cm/devicemanager/manager.go)                                                                                                                                    |
| 32 DRA                 | 1.28 经典 resource.k8s.io/v1alpha2；1.32 结构化 resource.k8s.io/v1beta1                                                      | 资源 API、节点 RPC、类型注释和 Feature Gate 分别判断     | [1.28 类型](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/resource/v1alpha2/types.go)、[1.32 类型](https://github.com/kubernetes/kubernetes/blob/v1.32.0/staging/src/k8s.io/api/resource/v1beta1/types.go)、[1.32 门控](https://github.com/kubernetes/kubernetes/blob/v1.32.0/pkg/features/versioned_kube_features.go)                                     |
| 33 云基础设施          | 1.28 外部 CCM；CSI、CNI、Device Plugin、DRA 各自集成                                                                         | 云节点/路由/负载均衡不等于存储或容器网络；厂商实现另核对 | [Cloud Node Controller](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/cloud-provider/controllers/node/node_controller.go)、[Service Controller](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/cloud-provider/controllers/service/controller.go)                                                                                     |

### 补充源码入口与已完成核对

- 控制平面：[kube-apiserver 路由安装](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/apiserver/pkg/endpoints/installer.go)、[kubeadm 常量与依赖版本](https://github.com/kubernetes/kubernetes/blob/v1.28.0/cmd/kubeadm/app/constants/constants.go)、[Deployment 协调](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/controller/deployment/deployment_controller.go)。组件配置、REST 资源、CRI 和 etcd 协议不是同一个 API 分类。
- etcd 独立核对 [v3.5.9 API 定义与读取一致性选项](https://github.com/etcd-io/etcd/blob/v3.5.9/api/etcdserverpb/rpc.proto)，不把 Kubernetes tag 当作所有外部依赖的版本证明。
- 第 25 章已补齐异构 CPU request 聚合：对纳入样本求 `sum(usage)/sum(request)`，不是平均各 Pod 百分比；函数还存在整数截断。该源码结论已核对，真实 HPA 运行效果仍未测试，不能继续标记为“算法待补证”。
- 第 32 章同时保留 1.32 类型注释 Alpha 与整体门控 Beta、默认关闭的差异；1.28 节点端已包含批量 v1alpha3 RPC 及旧单数调用兼容，不能用资源 API 的 v1alpha2 推断节点协议。

## 3. v1.28.0 的关键门控

| 特性                      | 阶段  | 上游默认 | 本册使用方式                                |
| ------------------------- | ----- | -------- | ------------------------------------------- |
| SidecarContainers         | Alpha | false    | 普通 init 章节不套用可重启 sidecar 语义     |
| MaxUnavailableStatefulSet | Alpha | false    | 不把该字段写成无条件通用能力                |
| StatefulSetAutoDeletePVC  | Beta  | true     | 分开 whenDeleted 与 whenScaled，默认 Retain |
| DynamicResourceAllocation | Alpha | false    | 1.28 早期 DRA 与后续结构化模型分开          |

以上来自 [v1.28.0 kube_features.go](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)。实际集群可能覆盖上游默认值；对于同一功能，还需确认相关组件的门控配置和 API 可用性。

### StatefulSetAutoDeletePVC 的资料冲突

本轮重新读取两份资料，冲突仍存在：固定 `v1.28.0` 的 `pkg/features/kube_features.go` 将 StatefulSetAutoDeletePVC 设为 Beta、默认 **true**；[release-1.28 Feature Gates 文档表格](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/command-line-tools-reference/feature-gates.md)仍列 Beta、默认 **false**。

证明 **v1.28.0 上游源码编译默认配置**时，固定 tag 中的注册值更直接；不能用可修订历史表格覆盖该实现，也不能声称两份资料一致。真实集群还应检查发行版、厂商补丁与组件启动时的门控覆盖。门控默认开启也不代表 PVC 默认删除：未指定保留策略时 whenDeleted/whenScaled 仍是 Retain。

门控默认值、实际组件启用状态、API 是否服务、驱动及功能链是否完整，是四个检查层次。例如 DRA 仅开启门控而未开放 API 或安装驱动，并不能完成设备分配。

## 4. 从版本依据到实际环境验证 {#_4-本册没有替代哪些验证}

版本表用于定位文档、源码和门控条件。复现时还需记录实际发行版、内核、containerd、CNI、CoreDNS、存储与设备驱动，再依次验证服务端 schema、调度、运行和故障恢复。各章教学数字为纸面算例，实际性能需要单独测量。

### 证据类型与验证状态

| 证据类型          | 适合证明的内容               | 不能单独证明             |
| ----------------- | ---------------------------- | ------------------------ |
| 固定版本 API 定义 | 字段、类型、版本及声明的约束 | 所有运行时校验均已通过   |
| 固定版本源码      | 实现、默认值及条件分支       | 实际发行版没有补丁或覆盖 |
| 版本化官方文档    | 对应版本的预期用法           | 历史文档分支永不修订     |
| 教学推演          | 解释机制、数量和失败分支     | 真实集群已获得同样结果   |
| 环境实测          | 指定版本与配置下的实际行为   | 其他环境同样成立         |

本册已做文档、源码与离线示例核对；站点构建、链接和浏览器验收属于文档交付证据，不等同于 Kubernetes 集群实验。实际复现仍需记录 Context、命名空间、权限、二进制版本、门控、驱动和数据恢复条件。
