---
id: kubernetes-controller-manager
title: 第五章：kube-controller-manager——多个控制循环怎样协作？
description: "控制器围绕 API 状态持续协调，分别推进发布、副本、节点和端点等工作。本章沿对象关系说明观察、重试与故障定位。"
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
order: 5
---

# 第五章：kube-controller-manager——多个控制循环怎样协作？

第一章说 Kubernetes 会持续比较期望与已观察状态，但“持续比较”不是一个包办所有任务的巨大循环。不同控制器负责不同对象和关系，围绕 API 状态各自推进。

这一章重点理解控制器如何获得线索、如何再次协调，以及为什么一个对象的变化能引起其他组件工作。原理不依赖某个版本的内部 goroutine 数量，也不把控制器列表当作所有集群永远固定的配置。

## 1. API 对象、控制器与管理进程的分工 {#_1-controller、api-对象和-controller-manager-分别是什么}

- API 对象表达配置和状态，例如 Deployment、ReplicaSet。
- Controller 是观察相关状态并推进协调的逻辑，例如 Deployment Controller。
- kube-controller-manager 组织运行多种内置控制循环，但不是集群所有控制器的唯一归宿。

Ingress Controller、外部存储相关控制器或自定义 Operator 等，也可以作为独立组件运行。不能用“所有控制器都是 controller-manager 里的协程”解释整个生态。

即使多个内置控制器处在同一个进程，也不表示它们共用一条严格的业务执行链。理解职责和对象关系，比背诵进程内实现细节更重要。[控制器模式](https://kubernetes.io/docs/concepts/architecture/controller/)

## 2. 一次协调的基本步骤 {#_2-一次协调大致做什么}

[![控制器：线索、当前视图与再次协调](/assets/notes/kubernetes/k8s-controller-reconcile.png)](/assets/notes/kubernetes/k8s-controller-reconcile.png)

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

### 2.1 Informer、WorkQueue 与 Reconcile 怎样配合？

典型的 Kubernetes 控制器会把“观察变化”与“执行协调”分开：

- **Informer / Cache**：Informer 通过 List/Watch 获取对象并更新本地缓存；Lister 等读取方式可以复用缓存，减少反复向 API Server 查询。缓存可能短暂落后于 API Server，控制器必须考虑观察延迟和更新冲突。
- **WorkQueue（工作队列）**：事件处理逻辑通常把待处理对象的 Key（标识，例如 `namespace/name`）放入队列，而不是把每次事件的完整对象当作必须依次重放的业务消息。队列组织工作项、合并重复线索，并可配合限速与失败重试；它不是保存所有历史事件的消息账本。
- **Reconcile（协调）**：工作线程取出 Key，读取相关资源的当前视图，比较期望与已观察状态，决定是否创建、更新或删除对象。一次处理可能无事可做，也可能部分成功后失败；实现者需要检查已有结果、处理重复执行和重试，不能靠函数名自动获得幂等性。

[![典型控制器：观察、排队、协调与写回](/assets/notes/kubernetes/k8s-controller-informer-workqueue.svg)](/assets/notes/kubernetes/k8s-controller-informer-workqueue.svg)

读图时把两个方向分开：API Server 的变化流更新缓存，Reconcile 的 API 请求修改对象。API 操作又会产生后续观察；处理失败可以限速重新入队，但不要求一个事件对应一次完整事务。

这是常见实现模式，不代表所有内置控制器都采用完全一致的缓存、接口或重试策略。具体源码可读 [Kubernetes v1.28.0 的 sample-controller](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/sample-controller/controller.go)：其中事件入队、工作项处理和状态同步展示了职责分离；不要把主分支后来更新的实现当作全部版本的行为。

## 3. 根据当前状态实现重复协调 {#_3-为什么重复协调不应该反复创造相同资源}

假设某次请求已经创建了目标对象，但客户端在收到成功响应前断线。如果下一次协调不检查现有状态，而是无条件再创建一份，就可能不断制造多余资源或冲突。

控制器通常需要根据当前对象和约束作决定，使重复协调能够正确收敛。这是设计上的要求，不能只凭函数名叫 `Reconcile` 就断言实现天然幂等。

在教学例子中，可以这样区分：

- 错误思路：每收到一个 Deployment 事件，就创建三个新 Pod。
- 合理方向：依据该工作负载的模板、归属和现有状态，决定是否需要创建或调整相关对象。

对外部云资源或存储的操作还要考虑不确定结果、重试与资源标识，不是 API 内部副本数计算可以自动解决的。

## 4. Deployment、ReplicaSet 与 RC 的管理职责 {#_4-deployment、replicaset-与-rc-不能混成一个名字}

[![工作负载管理：Deployment → ReplicaSet → Pod](/assets/notes/kubernetes/k8s-controller-ownership.png)](/assets/notes/kubernetes/k8s-controller-ownership.png)

### 4.1 Deployment Controller

它管理发布相关的期望，例如 Pod 模板及相应 ReplicaSet 的调整。滚动更新时，新旧 ReplicaSet 可能同时存在。

### 4.2 ReplicaSet Controller

它围绕 ReplicaSet 的选择范围、归属及目标副本数量协调 Pod。这里要数的是符合相关管理条件的 Pod，不是只数已经 Ready 的容器。

如果目标是三个 Pod，三个 Pod 对象都存在但其中一个尚未就绪，不能据此简单推导 ReplicaSet 一定再创建第四个。副本计数、就绪和 Deployment 的可用性判断属于相关但不同的问题。

### 4.3 ReplicationController（RC）

RC 是另一类历史工作负载资源及对应控制逻辑，不是“创建 ReplicaSet 的上一级控制器”。新的常见应用教程通常以 Deployment 与 ReplicaSet 关系展开，但研究旧笔记时仍要分清名称。

Deployment 负责发布，ReplicaSet 协调副本，RC 则是另一类历史资源；阅读时需按各自职责区分。[Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)、[ReplicaSet](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/)、[ReplicationController](https://kubernetes.io/docs/concepts/workloads/controllers/replicationcontroller/)

### 4.4 沿用 web-demo，区分副本数量与就绪状态

以下是推演与观察命令，未在本次修订中执行。可复用[第一章实验](/articles/kubernetes-architecture.html#web-demo-lab)的 `web-demo`，只完成创建三个副本的场景，暂不扩容和清理；需要相同上下文、命名空间及读取这些资源的权限：

```bash
kubectl get deployment,rs,pods -n k8s-arch-demo
kubectl describe deployment web-demo -n k8s-arch-demo
kubectl get deployment web-demo -n k8s-arch-demo -o yaml
kubectl get rs -n k8s-arch-demo -l app=web-demo -o yaml
kubectl get pods -n k8s-arch-demo -l app=web-demo -o yaml
```

| 字段                       | 所属对象与含义                                                                                                              |
| -------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `spec.replicas`            | Deployment 的发布副本目标；ReplicaSet 也有自己的副本目标，滚动更新时可能存在多个 ReplicaSet                                 |
| `status.replicas`          | Deployment 统计其目标 Pod 的总副本数；ReplicaSet 统计符合其计数条件的受管理 Pod。两者作用范围不同，也可能暂时落后于实际变化 |
| `status.readyReplicas`     | Deployment、ReplicaSet 分别报告其范围内 Ready 的副本数，不能把字段缺失当作已就绪                                            |
| `status.availableReplicas` | 对应范围内达到可用条件的副本数；与 `minReadySeconds` 等设置有关，不等同于“业务所有路径已通过测试”                           |
| `spec.selector`            | Deployment 或 ReplicaSet 的标签选择条件；定位匹配对象，不能单独证明控制器归属                                               |
| `metadata.ownerReferences` | Pod 或 ReplicaSet 等对象的所有者引用；控制器归属要看 `controller: true` 的引用及其 UID，不能只比较名称                      |

在稳定版本、目标为三个副本的假设下，可以这样推演：

1. **只有两个计入副本数的 Pod**：ReplicaSet Controller 观察到差额后尝试通过 API 补足；成功创建仍需调度和启动。缓存延迟、创建失败等可能使下一轮继续处理，不能每次重复通知就无条件再建一个。
2. **已有三个符合计数条件的 Pod，其中一个未 Ready**：副本目标已满足，不能仅因 `readyReplicas` 为 2 就断言会创建第四个。未就绪要结合探针、应用和节点状态定位；更新策略等其他机制可能影响实际对象数量。
3. **删除其中一个 Pod**：控制器通过后续观察重新评估数量，推进替代 Pod 的创建；它不会把删除通知当作“把原 Pod 原样复活”的指令。观察时可能仍看到终止中的旧对象与新对象并存。
4. **另一个匹配标签的 Pod 已由其他控制器管理**：它不能仅因标签匹配就被本 ReplicaSet 随意接管或计为自己的受管理副本，仍需检查控制器所有权。

例如设置了正数 `minReadySeconds` 时，新 Pod 刚 Ready 不一定立刻被计为 available。这里的数量均是教学条件，不是实际命令输出。[Deployment 状态](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#deployment-status)、[ReplicaSet 的工作原理](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/#how-a-replicaset-works)

## 5. 标签、选择器和归属关系为什么需要一起看？

标签不是纯展示字段。控制器可以基于选择器定位相关对象，其他组件也可能使用标签选择后端。

但“标签匹配”不等于可以忽略对象的 ownerReferences 和控制关系，任意接管其他控制器的对象。修改标签、模板或选择器前，需要检查资源自己的约束及已有归属。

例如，给一个 Pod 换标签，可能同时影响副本管理和 Service 选择；它并不保证 Pod 会以你想象的方式自动转交给另一个 Deployment。

排查重复 Pod 时，应一起查看对象的管理链、选择范围、事件和新旧 ReplicaSet，不要先删除看似“多出来”的实例。

以目标 ReplicaSet 的选择器匹配 `app=web-demo` 为例，先比较以下三种情况：

| Pod 标签与控制器引用                                     | 对目标 ReplicaSet 的意义                                                                                             |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------- |
| 标签匹配，`controller: true` 引用指向目标 ReplicaSet UID | 属于该控制器管理范围，还需结合删除状态、阶段等判断是否计入副本数                                                     |
| 标签匹配，但控制器引用指向另一个控制器 UID               | 不因标签匹配就接管；修改标签也不能绕开现有控制器归属                                                                 |
| 标签匹配，没有 Controller OwnerReference                 | 满足收养条件时可能被目标 ReplicaSet 收养，例如对象和 ReplicaSet 均未进入删除等状态；不能绝对地说只管理自己创建的 Pod |

“没有 Controller OwnerReference”不等于 `ownerReferences` 数组一定为空。标签选择器决定哪些对象匹配，控制器引用识别谁管理对象，所有者引用还为垃圾回收提供依赖关系；删除所有者后是否级联清理，还与删除传播策略和 Finalizer 等有关。不要为了验证收养而在共享集群里删除或伪造控制器引用。[ReplicaSet 的收养行为](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/#non-template-pod-acquisitions)、[所有者与依赖对象](https://kubernetes.io/docs/concepts/overview/working-with-objects/owners-dependents/)

## 6. 节点状态观察与故障协调 {#_6-节点控制-不是运行-get-nodes-才开始工作}

`kubectl get nodes` 读取节点对象，不会临时启动一次 Node Controller，再等待 kubelet 现场汇报。

节点相关机制持续关注节点健康等状态，故障处理还会涉及超时、污点、Pod 生命周期和其他协调逻辑。不能写成“Node Controller 一收到网络断开，就把所有进程立即迁移到另一台机器”。

对于工作负载重建，最终还要有相应控制器、可调度资源以及网络/存储等依赖。节点层认为出现了问题，不等于业务已经恢复。[节点管理](https://kubernetes.io/docs/concepts/architecture/nodes/)

## 7. ResourceQuota：控制器统计不等于所有限制都由它同步执行

ResourceQuota 表达某个命名空间的资源配额约束。相关状态统计和请求准入共同参与工作，不能理解为“只有 ResourceQuota Controller 后台检查，所有创建请求都会先成功，之后再清理超出的对象”。

也不能把它当作主机资源硬隔离的完整替代：对象配额、Pod 的 requests/limits、节点容量和实际资源使用属于不同层次。

新手排查创建失败时，应区分：配额拒绝、字段校验失败和调度资源不足，并查看 API 返回的具体信息。[ResourceQuota](https://kubernetes.io/docs/concepts/policy/resource-quotas/)

例如，某命名空间有生效的 `pods: "2"` 配额，已经有两个计入配额的 Pod，再请求创建第三个。在对应 ResourceQuota 准入插件和配额规则生效时，请求会在 API 写入路径被拒绝；第三个 Pod 可能根本没有创建出来，因而不会进入 Scheduler 排队。ResourceQuota Controller 的使用量协调不能替代这次同步准入检查。

如果第三个 Pod 本来应由 ReplicaSet 创建，应查 ReplicaSet 的创建失败事件及命名空间配额，而不是只盯着 Pod Pending：

```bash
kubectl get resourcequota -n k8s-arch-demo
kubectl describe resourcequota -n k8s-arch-demo
kubectl describe rs -n k8s-arch-demo -l app=web-demo
```

这些只读命令沿用上节实验空间，不会为它新增配额。以下三类约束各有分工：

| 机制                  | 主要负责什么                                       | 常见观察边界                                               |
| --------------------- | -------------------------------------------------- | ---------------------------------------------------------- |
| ResourceQuota         | 限制命名空间内的对象数量或资源请求总额等           | API 创建或更新可能被拒绝，查看配额与返回错误               |
| Pod `requests/limits` | 声明容器的资源需求与限制；运行时按相应机制执行限制 | requests 参与配额与调度核算，limits 不等于预先获得节点资源 |
| Scheduler             | 按资源请求及其他约束为已存在的待调度 Pod 选择节点  | 无可行节点时，Pod 可以存在但尚未绑定                       |

## 8. Namespace 删除：为什么会停在 Terminating？

命名空间删除通常需要协调其中对象的清理。Finalizer 等机制可能要求先完成某项外部清理，或由相应控制器移除完成标志。

因此，删除请求被接受，并不代表所有对象与外部资源都已同步消失。命名空间长期处于删除状态，可能与剩余对象、相关 API 或清理控制器无法推进有关，需要根据证据定位。

不要把删除 finalizers 当作万能修复。强行跳过清理约束，可能留下外部存储、云资源或其他无法正确回收的对象。本章不提供强制清理未知命名空间的脚本。[Finalizer](https://kubernetes.io/docs/concepts/overview/working-with-objects/finalizers/)

## 9. Service、EndpointSlice 与数据平面的配合 {#_9-service-与端点协调-不要再把一切都称为-endpoint-controller}

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

沿用 `k8s-arch-demo/web-demo`，可按下面的证据逐层缩小范围。`POD_NAME` 要替换为实际 Pod 名称；前提是有读取目标对象、事件和相应日志的权限，命令均为观察示例：

| 阶段与现象                         | 优先观察的证据                                                                                                                                       |
| ---------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------- |
| Deployment 不存在                  | `kubectl config current-context` 与 `kubectl get deployment web-demo -n k8s-arch-demo`；核对集群、命名空间、提交结果，以及认证、授权、校验或准入错误 |
| Deployment 存在，ReplicaSet 未生成 | Deployment 的 Conditions、Events、暂停设置和模板；再查控制器的 API 权限、领导者与日志，不把暂停或请求失败直接认定为进程故障                          |
| ReplicaSet 存在，Pod 数量不足      | `kubectl describe rs -n k8s-arch-demo -l app=web-demo`；查实际目标数量、所有权和 `FailedCreate` 等事件，区分配额、准入与其他创建错误                 |
| Pod 存在但未绑定                   | `kubectl describe pod POD_NAME -n k8s-arch-demo`；查 `PodScheduled`、`spec.nodeName`、`FailedScheduling` 和资源、标签、污点、卷约束                  |
| Pod 已绑定但未正常运行             | `kubectl get pod POD_NAME -n k8s-arch-demo -o yaml`；查容器状态和事件，再关联节点 kubelet、运行时、镜像、CNI、挂载和应用日志                         |

需要日志时，根据实际部署方式定位 kube-controller-manager 或节点服务；不要在没有证据时通过重启整个控制平面代替排查。

控制器本身还依赖正确的 API 访问、相应的领导者工作状态，以及可用的依赖组件。进程存在或日志未立即报错，都不足以证明所有控制循环能够完成业务目标。

这套定位顺序适合组织排查过程，实际根因需由目标集群的事件、日志与状态共同确认。

控制器创建出 Pod 对象后，还需要决定放在哪个节点；接着阅读[第六章 Scheduler](/articles/kubernetes-scheduler.html)。

[返回本册目录](/collections/kubernetes/)
