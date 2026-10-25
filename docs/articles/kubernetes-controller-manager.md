---
id: kubernetes-controller-manager
title: 第五章：kube-controller-manager——多个控制循环怎样协作？
description: 第一章说 Kubernetes 会持续比较期望与已观察状态，但“持续比较”不是一个包办所有任务的巨大循环。不同控制器负责不同对象和关系，围绕 API 状态各自推进。
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
order: 5
---

# 第五章：kube-controller-manager——多个控制循环怎样协作？

第一章说 Kubernetes 会持续比较期望与已观察状态，但“持续比较”不是一个包办所有任务的巨大循环。不同控制器负责不同对象和关系，围绕 API 状态各自推进。

这一章重点理解控制器如何获得线索、如何再次协调，以及为什么一个对象的变化能引起其他组件工作。原理不依赖某个版本的内部 goroutine 数量，也不把控制器列表当作所有集群永远固定的配置。

## 1. Controller、API 对象和 Controller Manager 分别是什么？

- API 对象表达配置和状态，例如 Deployment、ReplicaSet。
- Controller 是观察相关状态并推进协调的逻辑，例如 Deployment Controller。
- kube-controller-manager 组织运行多种内置控制循环，但不是集群所有控制器的唯一归宿。

Ingress Controller、外部存储相关控制器或自定义 Operator 等，也可以作为独立组件运行。不能用“所有控制器都是 controller-manager 里的协程”解释整个生态。

即使多个内置控制器处在同一个进程，也不表示它们共用一条严格的业务执行链。理解职责和对象关系，比背诵进程内实现细节更重要。[控制器模式](https://kubernetes.io/docs/concepts/architecture/controller/)

## 2. 一次协调大致做什么？

![控制器的观察、排队与协调反馈](/assets/notes/kubernetes/k8s-controller-reconcile.svg)

这是教学模型，不是对任意控制器源码的逐行复现。队列、缓存和重试的具体实现应按目标版本阅读。

可以用下面的伪代码理解一次协调：

```text
收到需要关注的对象线索
读取相关对象的当前视图
如果对象已不存在，处理相应清理或直接结束
比较期望、已观察状态和依赖条件
如有必要，经 API 请求创建、修改或删除对象
记录状态；失败或尚未满足时，等待后续协调机会
```

这里的线索并不是一条只能消费一次的业务消息。控制器可能多次观察到相同对象，也可能在中间变化已经发生后，直接根据最新视图重新决定下一步。

因此，“收到一次事件，就恰好执行一次完整业务流程”的理解并不适用。

## 3. 为什么重复协调不应该反复创造相同资源？

假设某次请求已经创建了目标对象，但客户端在收到成功响应前断线。如果下一次协调不检查现有状态，而是无条件再创建一份，就可能不断制造多余资源或冲突。

控制器通常需要根据当前对象和约束作决定，使重复协调能够正确收敛。这是设计上的要求，不能只凭函数名叫 `Reconcile` 就断言实现天然幂等。

在教学例子中，可以这样区分：

- 错误思路：每收到一个 Deployment 事件，就创建三个新 Pod。
- 合理方向：依据该工作负载的模板、归属和现有状态，决定是否需要创建或调整相关对象。

对外部云资源或存储的操作还要考虑不确定结果、重试与资源标识，不是 API 内部副本数计算可以自动解决的。

## 4. Deployment、ReplicaSet 与 RC，不能混成一个名字

![Deployment 与副本控制的职责层次](/assets/notes/kubernetes/k8s-controller-ownership.svg)

### 4.1 Deployment Controller

它管理发布相关的期望，例如 Pod 模板及相应 ReplicaSet 的调整。滚动更新时，新旧 ReplicaSet 可能同时存在。

### 4.2 ReplicaSet Controller

它围绕 ReplicaSet 的选择范围、归属及目标副本数量协调 Pod。这里要数的是符合相关管理条件的 Pod，不是只数已经 Ready 的容器。

如果目标是三个 Pod，三个 Pod 对象都存在但其中一个尚未就绪，不能据此简单推导 ReplicaSet 一定再创建第四个。副本计数、就绪和 Deployment 的可用性判断属于相关但不同的问题。

### 4.3 ReplicationController（RC）

RC 是另一类历史工作负载资源及对应控制逻辑，不是“创建 ReplicaSet 的上一级控制器”。新的常见应用教程通常以 Deployment 与 ReplicaSet 关系展开，但研究旧笔记时仍要分清名称。

原文关于 RC、ReplicaSet、滚动更新的混合描述，在本章按职责重新拆开，原文保留于私有记录。[Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)、[ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/)、[ReplicationController](https://kubernetes.io/docs/concepts/workloads/controllers/replicationcontroller/)

## 5. 标签、选择器和归属关系为什么需要一起看？

标签不是纯展示字段。控制器可以基于选择器定位相关对象，其他组件也可能使用标签选择后端。

但“标签匹配”不等于可以忽略对象的 ownerReferences 和控制关系，任意接管其他控制器的对象。修改标签、模板或选择器前，需要检查资源自己的约束及已有归属。

例如，给一个 Pod 换标签，可能同时影响副本管理和 Service 选择；它并不保证 Pod 会以你想象的方式自动转交给另一个 Deployment。

排查重复 Pod 时，应一起查看对象的管理链、选择范围、事件和新旧 ReplicaSet，不要先删除看似“多出来”的实例。

## 6. 节点控制：不是运行 get nodes 才开始工作

`kubectl get nodes` 读取节点对象，不会临时启动一次 Node Controller，再等待 kubelet现场汇报。

节点相关机制持续关注节点健康等状态，故障处理还会涉及超时、污点、Pod 生命周期和其他协调逻辑。不能写成“Node Controller 一收到网络断开，就把所有进程立即迁移到另一台机器”。

对于工作负载重建，最终还要有相应控制器、可调度资源以及网络/存储等依赖。节点层认为出现了问题，不等于业务已经恢复。[节点管理](https://kubernetes.io/docs/concepts/architecture/nodes/)

## 7. ResourceQuota：控制器统计不等于所有限制都由它同步执行

ResourceQuota 表达某个命名空间的资源配额约束。相关状态统计和请求准入共同参与工作，不能理解为“只有 ResourceQuota Controller 后台检查，所有创建请求都会先成功，之后再清理超出的对象”。

也不能把它当作主机资源硬隔离的完整替代：对象配额、Pod 的 requests/limits、节点容量和实际资源使用属于不同层次。

新手排查创建失败时，应区分：配额拒绝、字段校验失败和调度资源不足，并查看 API 返回的具体信息。[ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)

## 8. Namespace 删除：为什么会停在 Terminating？

命名空间删除通常需要协调其中对象的清理。Finalizer 等机制可能要求先完成某项外部清理，或由相应控制器移除完成标志。

因此，删除请求被接受，并不代表所有对象与外部资源都已同步消失。命名空间长期处于删除状态，可能与剩余对象、相关 API 或清理控制器无法推进有关，需要根据证据定位。

不要把删除 finalizers 当作万能修复。强行跳过清理约束，可能留下外部存储、云资源或其他无法正确回收的对象。本章不提供强制清理未知命名空间的脚本。[Finalizer](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/)

## 9. Service 与端点协调：不要再把一切都称为 Endpoint Controller

使用选择器的常见 Service 场景中，端点相关控制逻辑根据 Service 和 Pod 等状态维护后端信息。现代学习主线需要认识 EndpointSlice，而不是只画一个同名 Endpoints。

无选择器、ExternalName 和 Headless 等情形又有不同规则，不能用“创建 Service 必然生成一个同名 Endpoints”解释全部资源。

还有一层需要分开：控制器协调端点对象，kube-proxy 或替代实现根据这些信息组织数据平面；控制器不是逐个转发应用请求的网络代理。[EndpointSlice](https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/)

## 10. 控制器失败，怎样逐层观察？

假设 Deployment 的期望副本数没有达成，优先沿着对象关系查：

```text
Deployment 是否存在？模板、状态、条件是否符合预期？
    ↓
是否存在相关 ReplicaSet？新旧版本和副本目标是什么？
    ↓
Pod 对象是否已创建？有没有配额或准入拒绝事件？
    ↓
Pod 是否已绑定节点？如果没有，再看调度条件
    ↓
如果已绑定，继续看 kubelet、镜像、运行时、网络和存储
```

这个顺序能避免两个常见错误：把运行时拉镜像失败归因于 Deployment Controller，或在 Pod 尚未创建时直接排查应用进程。

控制器本身还依赖正确的 API 访问、相应的领导者工作状态，以及可用的依赖组件。进程存在或日志未立即报错，都不足以证明所有控制循环能够完成业务目标。

本章保留的是一套阅读与定位模型，不是声称已经在你的集群验证过的诊断结果。

[返回本册目录](/collections/kubernetes/)
