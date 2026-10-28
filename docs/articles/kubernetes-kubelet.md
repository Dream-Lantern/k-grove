---
id: kubernetes-kubelet
title: 第七章 kubelet：节点协作与健康检查
description: "调度器为 Pod 选择节点，并不意味着镜像已经下载、卷已经挂载、容器已经启动。调度解决的是“放在哪里”，节点侧还要解决“在这里如何运行”。"
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
order: 7
---

# 第七章 kubelet：节点协作与健康检查

> 本章以 Linux 上的 Kubernetes 1.28 为学习背景。沿调度与绑定之后的节点侧流程，说明 kubelet 如何协调运行、检查健康并回报状态；命令和配置为阅读示例。

## 1. 绑定之后的节点侧协调 {#_1-已经选好节点-为什么-pod-还没运行}

调度器为 Pod 选择节点，并不意味着镜像已经下载、卷已经挂载、容器已经启动。调度解决的是“放在哪里”，节点侧还要解决“在这里如何运行”。

kubelet 是节点上的代理，持续处理分配给本节点的 Pod。它读取期望配置，结合已观察到的容器与主机状态，调用相应的运行时和卷机制，使实际状态逐步接近期望，并向 API Server 报告状态。控制平面据此继续协调，用户也能通过 API 查看进展。

可以用三个问题分清它和前面组件的边界：

- “需要几个副本？”由相应的工作负载控制器协调，不由 kubelet 维护整个集群的副本数。
- “这一个 Pod 放在哪台节点？”通常由调度器决定，不由 kubelet 在全局挑选。
- “分配到这里的 Pod 为什么还没有启动？”这时才进入 kubelet、运行时、卷与网络的节点侧范围。

[![kubelet：把本节点的期望转成运行状态](/assets/notes/kubernetes/k8s-kubelet-boundaries.svg)](/assets/notes/kubernetes/k8s-kubelet-boundaries.svg)

图中的箭头表示主要请求或调用方向，不是说 API Server 同步调用 kubelet 并等待应用启动完毕。kubelet 会持续观察和协调，网络短暂中断也不能简单等同于“节点上的所有容器立即停止”。

节点注册、Pod 管理、健康检查和状态上报都属于节点侧的持续协调，分析故障时要看它们之间的状态如何传递。

## 2. 从 Pod 配置到容器运行，中间有哪些事情

以下是帮助理解的逻辑拆分，不是承诺所有实现都严格依次执行的源码调用链：

1. 观察本节点需要管理的 Pod，读取镜像、资源、卷、探针等配置。
2. 检查相关条件，准备卷和所需配置；条件不满足时记录事件或等待重试。
3. 通过容器运行时接口 CRI 处理 Pod sandbox、镜像及容器生命周期。
4. 在运行过程中执行适用的健康检查，观察退出情况和资源状态。
5. 根据配置处理容器重启、Pod 终止等工作，并回报状态。

Pod sandbox 是运行时管理 Pod 级运行环境的抽象，不能直接等同于业务容器。普通 Linux Pod 的网络准备往往涉及运行时的 CNI 集成；存储插件的接入又是另一条机制，不能把所有准备工作都归给 CRI。

这里还有一个边界：静态 Pod 可由 kubelet 根据节点本地配置管理，不走普通 Pod 的调度流程。kubeadm 管理的控制平面经常会涉及静态 Pod。不要因此推导成“所有 Kubernetes Pod 都必须先由调度器分配”。

## 3. 看状态时，先分清三个层级

应用能否接收请求，需要结合节点、Pod、容器与就绪条件分层判断：

| 观察对象 | 典型字段或显示                   | 它能说明什么                                     |
| -------- | -------------------------------- | ------------------------------------------------ |
| Node     | `Ready` 等条件                   | 节点在所观察维度上的状态，不是每个应用的验收结果 |
| Pod      | `status.phase`                   | Pod 生命周期的粗粒度概况                         |
| 容器     | `Waiting / Running / Terminated` | 该容器当前处于哪个运行阶段                       |
| Pod 条件 | `Ready`、`ContainersReady` 等    | 就绪判断及其他条件；不是 Pod phase 的取值        |

`kubectl get` 展示的 `STATUS` 是面向人的摘要，不能把里面出现的所有文字都当成 API 的 `phase`。例如 `CrashLoopBackOff` 不是 Pod phase，`Terminating` 也不是。

一个容器进程可以已经启动，但应用仍在加载数据，readiness 尚未通过；一个 Node 可以是 Ready，但某个 Pod 因镜像获取失败无法运行。把这些状态混为一谈，就容易在错误层级寻找原因。

关于 Pod phase、容器状态和原 Pod 不会迁移为同一个对象的定义，参见 [Kubernetes 1.28 Pod 生命周期](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/pods/pod-lifecycle.md)。后面的资源章节会单独展开生命周期字段。

## 4. startup、liveness 与 readiness 的职责 {#_4-三类探针分别在问什么}

探针用于检查容器内的应用，不能完整证明业务正确。应用需要为探针接口定义合适的语义；如果接口始终返回成功，检查结果就无法反映真实状态。

| 探针      | 核心问题                         | 达到失败条件后的主要作用                           |
| --------- | -------------------------------- | -------------------------------------------------- |
| startup   | 这次启动是否已经完成？           | 启动失败处理；容器终止后是否重启取决于适用策略     |
| liveness  | 应用是否陷入需要终止处理的状态？ | 触发容器终止，再按适用的重启策略处理               |
| readiness | 当前是否适合承接服务流量？       | 影响就绪和服务后端资格，不直接因这一失败而重启容器 |

[![三类探针：失败后采取的动作不同](/assets/notes/kubernetes/k8s-probe-effects.svg)](/assets/notes/kubernetes/k8s-probe-effects.svg)

配置了 startup probe 时，在它成功之前，其他两类探针不会开始工作。这样能给慢启动应用留出启动检查阶段，而不是单纯把所有检查的间隔都调得很长。

readiness 失败也不等于“删除了 Service”。在常见的选择器 Service 路径里，就绪信息会影响端点状态和通常的后端选择；传播不是瞬时完成，`publishNotReadyAddresses`、终止端点和流量策略等条件还需要单独理解。已有连接是否继续，也不能仅凭一次探针失败下结论。

### 4.1 检查手段不是探针用途

HTTP、TCP、exec 和 gRPC 是检查手段；startup、liveness、readiness 是用途，两者是不同维度。

- HTTP 检查指定路径的响应，不能证明所有业务接口都正确。
- TCP 连接成功主要说明端口可连接，不代表应用完成了业务初始化。
- exec 根据命令退出情况判断，但频繁创建检查进程也有代价。
- Kubernetes 1.28 已有 gRPC 探针处理字段，服务需要实现相应的健康检查协议，不是随便指定一个 gRPC 端口就能工作。

上述字段与 liveness/startup 的 `successThreshold` 必须为 1 的约束，可在 [v1.28.0 API 校验源码](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/core/validation/validation.go)中核对。

### 4.2 新增教学示例：慢启动应用

下面只是放在容器配置中的片段，省略镜像和其他 Pod 字段，不是可直接提交的完整清单。路径必须由应用实现；数字用于解释，不是通用推荐值。

```yaml
startupProbe:
  httpGet:
    path: /health/startup
    port: 8080
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 24
readinessProbe:
  httpGet:
    path: /health/ready
    port: 8080
  periodSeconds: 5
  timeoutSeconds: 2
  failureThreshold: 3
livenessProbe:
  httpGet:
    path: /health/live
    port: 8080
  periodSeconds: 10
  timeoutSeconds: 2
  failureThreshold: 3
```

这段配置把“启动完成”“能否接流量”“是否需要重启处理”分开。`periodSeconds` 是检查间隔配置，`timeoutSeconds` 是单次检查超时，`failureThreshold` 是连续失败阈值。

不要把 `24 × 5` 写成严格的墙钟时间承诺：调度、请求耗时和运行环境都会影响观察到的时刻。也不要直接把所有依赖服务放入 liveness：如果下游短暂故障让所有副本同时被重启，可能反而扩大故障。哪些依赖应该影响 readiness，要结合降级能力和服务契约决定。

## 5. 容器重启与 Pod 替换 {#_5-容器重启-不是-pod-被重新调度}

在同一 Pod 内重启应用容器，和工作负载控制器创建一个新 Pod，是两件事。

对普通应用容器，`restartPolicy` 可以是 `Always`、`OnFailure` 或 `Never`。策略描述适用容器退出后的重启行为；它不是“把原 Pod 移到另一台机器”的配置。节点故障、驱逐或原 Pod 被删除后，通常由上层控制器按需要创建新的 Pod，新对象拥有新的 UID。

因此排查重启时，应先问：是同一个 Pod 的容器 `restartCount` 增加，还是出现了一个新 Pod？前者更需要看容器退出原因、探针和节点侧事件；后者还要看工作负载控制器与调度条件。

终止同样需要时间。应用应正确处理停止信号、停止接收新请求，并完成必要的收尾；探针、端点传播和现有连接的变化也不是绝对同步的。本章不以强制删除、重启服务等操作代替定位。

## 6. 阅读运行证据的顺序

以下命令模板用于依次查看对象、事件和日志。使用时先确认集群上下文并替换占位符；输出含业务信息时，分享前需要脱敏。

```bash
kubectl get nodes
kubectl describe node NODE_NAME
kubectl get pod POD_NAME -n NAMESPACE -o wide
kubectl describe pod POD_NAME -n NAMESPACE
kubectl logs POD_NAME -n NAMESPACE -c CONTAINER_NAME --previous
```

`--previous` 用于查看同一 Pod 中该容器上一个实例的可用日志，不保证节点丢失或日志轮转之后仍可读取。没有历史实例时，报错也不是新的应用故障。

推荐的阅读顺序是：是否绑定节点 → 卡在哪个准备阶段 → 容器是否退出 → 退出原因和探针事件 → 是否存在节点或运行时异常。不要看到 `Pending` 就一律归因于调度器，或看到重启就一律加大内存。

## 7. 本章小结

kubelet 负责本节点的持续协调，不代替调度器或工作负载控制器。状态需要按节点、Pod、容器和条件分层理解；探针要按启动、存活、就绪分工。下一章进入它调用的运行时，解释为什么 `ctr` 看到的对象和 `kubectl` 看到的资源不能直接画等号。

[返回本册目录](/collections/kubernetes/) · [下一章：容器运行时与 containerd 工具边界](/articles/kubernetes-container-runtime.html)
