---
id: kubernetes-architecture
title: 第一章：Kubernetes 整体架构——从一次部署理解各组件如何协作
description: "Kubernetes 通过一组持续协作的组件，把 API 对象中描述的期望状态逐步变成运行中的应用。理解组件职责与对象关系，是学习部署、网络和故障排查的起点。"
date: '2026-10-25'
updated: '2026-10-28'
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
order: 1
---

# 第一章：Kubernetes 整体架构——从一次部署理解各组件如何协作

Kubernetes 通过一组持续协作的组件，把 API 对象中描述的期望状态逐步变成运行中的应用。理解组件职责与对象关系，是学习部署、网络和故障排查的起点。

本章以**运行三个 Web 应用副本**为例，沿请求提交、控制器协调、调度和节点执行这条主线解释各组件的配合。

读完后，我们应能区分控制平面与工作节点，解释 Pod、容器和 Deployment 的关系，并沿着一次普通 Deployment 部署的过程，说清 API 对象如何逐步变成运行中的程序。

适用范围：以 Linux 节点上的常见 Kubernetes 架构为主，讲解稳定的基本机制。单节点学习环境和生产高可用集群分别说明。

## 1. 有了容器，为什么还需要 Kubernetes？

假设我们已经把一个 Web 应用打包成容器镜像，并能在一台机器上启动它。现在希望这个应用同时运行三个实例，以便分担访问压力。

只启动三个容器并不难，难的是后续管理：

- 哪台机器还有足够资源，可以接收新实例？
- 一个实例退出后，由谁决定是否重新启动？
- 整台机器故障后，怎样在其他机器启动实例？
- 更新镜像时，怎样逐步替换旧实例？
- 实例的地址变化后，其他服务如何继续访问它？
- 配置文件、访问凭证和业务数据怎样与容器分开管理？

这些问题跨越了单个容器的生命周期。Kubernetes 主要提供容器化工作负载的编排与管理机制：用 API 对象描述需要的状态，由集群中的组件持续协调。

虚拟机、容器和操作系统各有隔离与资源管理机制。Kubernetes 在此基础上提供集群编排；应用启动速度和故障恢复时间仍取决于镜像、初始化、依赖与部署策略。

Kubernetes 帮助组织部署和恢复过程，应用自身仍要处理启动、健康检查、连接排空和数据一致性等问题。

## 2. 先分清四个对象：集群、节点、Pod 和容器

### 2.1 集群与节点

集群（Cluster）是由控制平面、节点及相关组件共同组成的运行环境。节点（Node）通常是一台物理机或虚拟机，也对应 Kubernetes API 中的节点对象。

可以先按职责分成两部分：

- **控制平面（Control Plane）**：保存和管理集群状态，推进控制、调度等工作。
- **工作节点（Worker Node）**：为应用提供实际运行环境，运行 Pod 中的容器。

这是逻辑分工，不是“必须一台控制机器加一台工作机器”的硬性布局。学习环境可以只有一台机器，同时承担控制与工作职责；生产集群则需要结合可用性、容量和故障域设计部署拓扑。参见 [Kubernetes 节点说明](https://kubernetes.io/docs/concepts/architecture/nodes/)。

### 2.2 Pod 与容器

容器是运行应用的进程；Pod 则是 Kubernetes 调度和管理容器时使用的基本单元。一个 Pod 可以包含一个容器，也可以包含多个需要紧密协作的容器。

同一 Pod 的容器共同调度到同一节点，通常共享网络命名空间，因此能通过 `localhost` 通信；文件共享则需要挂载相应的共享卷。**它们不会因为处于同一 Pod，就自动共享一份进程内存或完全相同的容器根文件系统。**

同一 Pod 中的多个容器构成一个共同调度的运行单元，应用副本则通常通过多个 Pod 表达。需要三个可分别管理的 Web 实例时，通常创建三个 Pod，而不是把三个 Web 容器塞进同一个 Pod。参见 [Pod 的组织方式](https://kubernetes.io/docs/concepts/workloads/pods/)。

### 2.3 Deployment 与副本管理 {#_2-3-deployment-为什么还要再包一层}

Pod 负责表达一次运行实例，但它本身不是“永远保持三个实例”的完整管理方案。

对于常见的无状态 Web 应用，可以用 Deployment 描述 Pod 模板、副本数量和更新策略。Deployment 管理 ReplicaSet，ReplicaSet 再协调 Pod 的数量。

因此，先记住这层关系：

```text
Deployment：管理 Pod 模板的发布和更新
    └── ReplicaSet：协调一组匹配 Pod 的副本数量
            └── Pod：包含实际运行的容器
```

这里表达的是管理关系，不是进程调用栈。Deployment、ReplicaSet 和 Pod 都是 API 对象，不是三种依次嵌套运行的容器。更新时还可能同时存在新旧 ReplicaSet，并非一个 Deployment 永远只对应一个 ReplicaSet。[Deployment 官方说明](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

## 3. 架构总览：控制平面负责协调，节点负责运行

[![k8s-logical-architecture](/assets/notes/kubernetes/k8s-logical-architecture.svg)](/assets/notes/kubernetes/k8s-logical-architecture.svg)

图 1：此图只表示逻辑分组，不表示调用顺序、固定节点数或高可用副本配置。

读图时注意：

1. 左侧是控制平面的主要组件，不表示这些组件必须只运行一份，或全部部署在同一台机器。
2. 右侧是一台示意工作节点；两个 Pod、每个 Pod 两个容器只是帮助看清层级，并非推荐或固定数量。
3. `cloud-controller-manager` 是与云平台集成有关的可选组件；部分网络方案也会替代 `kube-proxy` 的 Service 数据平面实现。
4. CNI 是网络集成接口与相关实现体系，不意味着每个集群都存在一个同名的独立常驻进程。CoreDNS 和存储驱动等补充能力在后文介绍。

先把图当作“职责地图”，不必一次掌握所有内部接口。[官方组件概览](https://kubernetes.io/docs/concepts/overview/components/)

## 4. 控制平面的组件职责 {#_4-控制平面-谁接收请求-谁决定下一步}

### 4.1 kube-apiserver：处理 API 请求 {#_4-1-kube-apiserver-api-入口-不是万能任务转发器}

`kubectl`、客户端程序和集群组件通过 Kubernetes API 读取或修改对象，kube-apiserver 提供这一入口。

例如，提交 Deployment 时，需要经过相应的身份认证、授权、准入与对象处理，成功的状态变更才会进入持久存储流程。普通用户通过`kubectl`命令无法直接修改 etcd，也不是通过 `kubectl` 登录到某台工作节点执行启动容器的脚本。

API Server 并不会在收到每个请求后，同步调用某个控制器，并等到所有容器启动完成才回复。请求处理与后续状态协调是两件事，具体权限流程会在安全章节展开。[Kubernetes API](https://kubernetes.io/docs/concepts/overview/kubernetes-api/)

### 4.2 etcd：保存 API 状态 {#_4-2-etcd-保存集群状态-不是应用文件仓库}

etcd 是持久的分布式键值存储，用于保存 Kubernetes 的 API 数据。Deployment、Pod 等对象的状态需要有可靠的保存位置，这样控制平面才能在重启或故障恢复后继续协调。

把“集群状态”与“业务数据”分开，是理解架构的重要一步。应用镜像和数据库的数据文件，不会因为应用部署到了 Kubernetes，就自动存进 etcd。

在标准控制平面中，其他组件主要经 API Server 访问 API 状态。[组件职责](https://kubernetes.io/docs/concepts/overview/components/)

### 4.3 kube-controller-manager：运行持续协调的控制器

控制器（Controller）不断观察相关对象，比较期望与已观察状态，再采取相应行动。

例如，ReplicaSet 期望维持三个匹配的 Pod，观察到少了一个时，就会推进创建替代 Pod。不同控制器分别负责副本、节点状态等不同问题；kube-controller-manager 组织运行其中多种内置控制器。

控制器不是在运行 `kubectl get` 时才开始工作，也通常不会亲自到节点上启动容器。它往往通过修改 API 对象，触发其他组件继续推进。[控制器模式](https://kubernetes.io/docs/concepts/architecture/controller/)

### 4.4 kube-scheduler：为尚未绑定的 Pod 选择节点

Scheduler 关注需要调度、尚未绑定到节点的 Pod，根据资源需求、节点条件和调度约束等选择合适位置，并推进绑定。

它回答的是“这个 Pod 放在哪个节点”，不是“在节点上如何拉镜像和启动进程”。如果没有节点满足条件，Pod 可能暂时无法调度；调度器不能凭空创造 CPU、内存或device。[Kubernetes 调度器](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/)

### 4.5 cloud-controller-manager：对接云平台

这个组件把部分云平台相关控制逻辑与 Kubernetes 的核心控制逻辑分离，例如与节点或云负载均衡器有关的集成。

本地学习集群不一定需要它。也不能因为创建了某个 API 对象，就假定任何环境都会自动提供对应的云资源；这取决于部署方式和实际集成能力。[云控制器](https://kubernetes.io/docs/concepts/architecture/cloud-controller/)

## 5. 工作节点：谁把 Pod 变成运行中的容器？

### 5.1 kubelet：负责本节点上的 Pod

kubelet 是节点上的主要代理。对于普通调度到本节点的 Pod，它根据相应规格协调运行，执行健康检查，并向控制平面报告节点和 Pod 的状态。

它既不是整个集群的调度器，也不直接代替容器运行时完成所有底层操作。单独讨论静态 Pod 时，还有与常规调度不同的管理路径，后续 kubelet 章节再展开。[kubelet 说明](https://kubernetes.io/docs/reference/command-line-tools-reference/kubelet/)

### 5.2 容器运行时：处理镜像和容器运行

容器运行时提供镜像与容器运行相关能力。常见实现包括 containerd 和 CRI-O。

kubelet 通过容器运行时接口（Container Runtime Interface，CRI）与兼容运行时交互。先用下面的职责链理解即可：

```text
kubelet：根据本节点 Pod 的需要发起操作
    → CRI：约定交互接口
        → 兼容运行时：处理容器与镜像相关工作
```

CRI 是接口，不是必须单独安装的容器引擎。具体搭建方式需要核对版本与运行时配置。[CRI 官方说明](https://kubernetes.io/docs/concepts/containers/cri/)

### 5.3 CNI：把 Pod 接入网络

在 Linux 常见部署中，运行时的网络集成通过容器网络接口（Container Network Interface，CNI）等机制，配合网络插件完成地址、接口与路由相关配置。

不同方案可以使用覆盖网络、原生路由或云网络集成。这里先记住它主要关联“Pod 如何接入并使用网络”，具体路径在网络章节展开。[Kubernetes 网络模型](https://kubernetes.io/docs/concepts/services-networking/)

### 5.4 kube-proxy：Service 转发的一种实现

kube-proxy 观察 Service、EndpointSlice 等对象，维护节点上的相关转发规则。应用访问 Service 时，数据平面按照这些规则把流量送往后端。

它不等同于集群 DNS，也不负责为每个 Pod 分配网络。部分网络方案提供自己的 Service 转发实现，因此不能把 kube-proxy 当作所有集群都不可替代的固定进程。[Service 网络机制](https://kubernetes.io/docs/concepts/services-networking/service/)

### 5.5 CoreDNS 与存储驱动：主图之外还需要认识的能力

CoreDNS 常用于集群内的 DNS 服务发现。例如，应用通过 Service 的域名寻找服务，而不必手工记录每个 Pod 的 IP。DNS 查询和后续业务流量转发是两个过程，不应都归到 kube-proxy。[CoreDNS 使用说明](https://kubernetes.io/docs/tasks/administer-cluster/dns-custom-nameservers/)

存储方面，卷及存储驱动帮助 Pod 使用文件系统与后端存储。卷不一定持久；临时卷、持久卷及回收策略需要分别理解，更不能把“挂载了卷”直接等同于“已经备份”。[卷的用途与生命周期](https://kubernetes.io/docs/concepts/storage/volumes/)

## 6. Kubernetes 怎样理解“我要三个副本”？

Kubernetes 的工作方式通常称为声明式管理：你描述期望结果，由相应组件持续协调，而不是在请求里指定所有节点和每一步操作步骤。

许多对象包含三类重要信息：

| 部分       | 回答的问题         | 示例                        |
| ---------- | ------------------ | --------------------------- |
| `metadata` | 这个对象是谁？     | 名称、命名空间、标签        |
| `spec`     | 希望它是什么样？   | Deployment 希望维持的副本数 |
| `status`   | 系统观察到了什么？ | 已就绪副本数、相关状态条件  |

以 Deployment 为例，下面仅展示一个字段片段，**不是完整可提交清单**：

```yaml
spec:
  replicas: 3
```

它表达的是期望副本数量为 3。如果已观察到的可用实例不足，相关组件会继续尝试推进；容量不足、镜像不可用或权限错误等问题也可能让目标迟迟无法达到。

不是所有对象都拥有完全相同的 `spec/status` 结构，也不应把期望副本数直接当作当前就绪实例数。[对象、spec 与 status](https://kubernetes.io/docs/concepts/overview/working-with-objects/)

[![控制循环：不断协调期望与已观察状态](/assets/notes/kubernetes/k8s-reconcile-loop.svg)](/assets/notes/kubernetes/k8s-reconcile-loop.svg)

图 2：用副本协调说明控制循环。图中的观察和变更经 API 等机制完成；这是简化反馈模型，不表示所有控制器都使用相同的检查周期。

“自动恢复”不意味着恢复必然成功或瞬间完成。它表示系统具备发现差异、推进修正的机制，而不是对任何故障作出零中断保证。

## 7. 一次 Deployment 部署，实际上经历了什么？

继续使用新增教学例子：创建一个名为 `web-demo` 的 Deployment，希望运行三个 Web Pod。

[![从 Deployment 到 Pod 运行](/assets/notes/kubernetes/k8s-deployment-journey.svg)](/assets/notes/kubernetes/k8s-deployment-journey.svg)

图 3：按主要状态变化整理的教学流程。箭头表示后续工作依赖哪些对象或状态变化，不代表组件之间存在固定的同步调用链；各组件会独立观察、重试与协调。

### 第一步：客户端提交 Deployment

`kubectl` 或其他客户端向 API Server 提交 Deployment 对象。API Server 处理请求并持久保存相应 API 状态；成功响应只说明这一请求被处理，不表示三个应用实例已经全部可用。

### 第二步：Deployment Controller 协调 ReplicaSet

Deployment Controller 观察到期望的 Pod 模板和副本设置，创建或调整相关 ReplicaSet。它通过 API 推进这一变化，而不是直接给 kubelet 下发“启动三个容器”的同步调用。

### 第三步：ReplicaSet Controller 协调 Pod 数量

ReplicaSet Controller 根据选择器、受管理 Pod 及副本目标协调 Pod 的创建或删除。此时，API 中可以已经存在 Pod 对象，但 Pod 还没有节点位置或运行中的容器。

**“Pod 对象已经创建”和“应用已经启动”是两个阶段。** 这也是排查 Pending 时首先要建立的认识。[Deployment 与 ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

### 第四步：Scheduler 选择节点并推进绑定

Scheduler 为需要调度的 Pod 寻找可行节点，再完成相应绑定。三个副本不必然自动分散在三台不同机器；想获得特定的分布效果，需要结合容量和调度约束设计。

本章先不展开过滤、评分和绑定扩展点，只保留“选择位置”和“执行运行”之间的职责区别。[调度概念](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/)

### 第五步：目标节点上的 kubelet 协调运行

kubelet 观察到分配给本节点的 Pod，配合运行时、网络与存储相关机制推进准备和容器启动。

这一步失败时，原因可能是镜像、运行时、网络、挂载或应用自身，而不一定是“调度器选错节点”。

### 第六步：状态回报与就绪判断

kubelet 持续报告运行状态。容器处于运行状态，不自动表示应用已经能提供服务；应用可能尚未完成初始化，就绪检查也可能尚未通过。

如果另外配置了匹配的 Service，控制器与数据平面还会根据相关端点状态协调访问路径。**创建 Deployment 不会自动创建一个对应的 Service。** [Service 与后端](https://kubernetes.io/docs/concepts/services-networking/service/)

## 8. 管理请求与业务流量，是两条不同的路径

管理路径关心的是对象的查询、创建和修改。例如：

```text
kubectl / API 客户端 → kube-apiserver → 相应 API 状态处理
```

业务路径关心的是应用请求如何到达运行中的后端。例如，一个已经配置好的入口方案，逻辑上可能涉及：

```text
用户请求 → 外部入口 / Ingress Controller → 应用后端 Pod
                     由 Service 等对象提供后端选择依据
```

这是逻辑关系，不保证每个数据包都物理经过一个独立的“Service 进程”。具体转发由所选网络、入口控制器和数据平面实现决定。

普通业务请求通常不需要先经过 API Server，也不会把请求数据写进 etcd。反过来，应用如果主动调用 Kubernetes API，则确实会使用管理 API；不要把两类请求混为一谈。

本章到这里先建立路径区别，Service、DNS 和 Ingress 的访问实验留到对应资源章节。[网络与入口概览](https://kubernetes.io/docs/concepts/services-networking/)

## 9. 出现故障时，怎样用架构关系判断影响范围？

### 9.1 应用容器退出

容器退出后，节点上的 kubelet 会结合相应的重启策略处理。若是 Pod 被删除或需要替换，Deployment/ReplicaSet 等控制机制再协调实例数量。重启容器与创建替代 Pod 不是同一个动作。

### 9.2 工作节点故障

失联节点上的进程不能理解成被 Kubernetes 直接“搬运”到另一台机器。对于受相应控制器管理的工作负载，在故障被处理、旧对象状态及删除条件允许、并且其他节点具备资源和依赖的情况下，系统可以协调创建替代 Pod。

新 Pod 的身份、地址和运行位置可能变化；存储能否重新挂载、应用如何恢复业务状态，还要另行设计。因此副本机制不能替代数据备份。[Pod 生命周期](https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/)

### 9.3 控制平面不可用

已有容器可能暂时继续运行，但新的 API 操作、调度和控制循环会受影响，不能进一步推导成“应用完全不受影响”。

图中画出两个控制节点，并不等于已经具备高可用。尤其是只有两个 etcd 投票成员时，失去一个就无法维持多数。kubeadm 的高可用拓扑需要分别考虑控制平面入口、etcd 多数派和故障域，而不是只数控制节点的图标。[kubeadm 高可用拓扑](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/ha-topology/)

### 9.4 网络或存储组件异常

应用进程正在运行，并不代表网络可达；节点 Ready，也不能证明每条业务路径都通畅。Pod 网络、Service 转发、DNS、入口和存储各有对应的检查位置。排障时，应先判断故障位于哪条路径，再查找相应组件的证据。

## 10. 后续资源章节放在这张地图的什么位置？

后续章节按用途展开资源与机制，可用下面的索引定位：

| 你要解决的问题                     | 后续重点资源或机制                                 |
| ---------------------------------- | -------------------------------------------------- |
| 管理长期运行的应用与更新           | Pod、Deployment、ReplicaSet                        |
| 管理稳定身份、节点任务或完成型任务 | StatefulSet、DaemonSet、Job、CronJob               |
| 组织应用并找到后端                 | Namespace、Label、Selector、Service、EndpointSlice |
| 从外部访问应用                     | Ingress / Gateway 相关资源及实现                   |
| 管理配置、凭证和文件数据           | ConfigMap、Secret、Volume、PV、PVC、StorageClass   |
| 决定位置、资源额度和副本规模       | 调度约束、requests/limits、HPA                     |
| 限制 API 操作权限                  | ServiceAccount、Role、ClusterRole 及绑定           |

这是一份阅读索引，不是互斥的 API 分类表。一个功能通常需要多个对象和组件配合，例如 Secret 只是敏感配置管理的一部分，base64 表示不是加密；StatefulSet 也不会自动实现数据库主从复制。[Secret 的安全边界](https://kubernetes.io/docs/concepts/configuration/secret/)

安装实践章节单独说明 Linux、Kubernetes、containerd 和网络插件的版本组合，以及安装、验证与恢复步骤。这里的架构示例用于理解职责与流程。

## 11. 本章要点 {#_11-读完后-试着回答这五个问题}

1. API Server 保存期望状态，后续控制器、调度器和节点组件继续推进运行。
2. Scheduler 选择节点，kubelet 在目标节点协调容器运行。
3. 同一 Pod 的容器共同调度并协作；多个 Pod 通常表达可分别管理的应用副本。
4. Pod 替换后地址可能变化，应用应通过合适的服务发现与访问机制定位后端。
5. 节点故障影响其运行实例；控制平面故障主要影响 API、调度和协调，业务影响仍需结合依赖判断。

后续组件、资源和排障章节均可放回“对象提交 → 控制器协调 → 节点选择 → 节点执行 → 状态回报”这条主线理解。

## 参考资料

以文中就近链接为主，以下提供继续阅读入口。架构事实按官方资料复核；示意流程不是源码级时序证明。

- [Kubernetes：组件概览](https://kubernetes.io/docs/concepts/overview/components/)
- [Kubernetes：API 对象](https://kubernetes.io/docs/concepts/overview/working-with-objects/)
- [Kubernetes：控制器](https://kubernetes.io/docs/concepts/architecture/controller/)
- [Kubernetes：Pod](https://kubernetes.io/docs/concepts/workloads/pods/)
- [Kubernetes：Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
- [Kubernetes：CRI](https://kubernetes.io/docs/concepts/containers/cri/)
- [Kubernetes：网络模型](https://kubernetes.io/docs/concepts/services-networking/)
- [Kubernetes：kubeadm 高可用拓扑](https://kubernetes.io/docs/setup/production-environment/tools/kubeadm/ha-topology/)

[返回本册目录](/collections/kubernetes/)
