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
3. 通过 CRI（Container Runtime Interface，容器运行时接口）请求运行时准备 Pod Sandbox，即 Pod 级运行环境。
4. 对适用的普通 Linux Pod，运行时的 CNI（Container Network Interface，容器网络接口）集成配置网络；卷与配置准备仍由相应机制负责。
5. 按镜像拉取策略等条件准备业务镜像，创建并启动应用容器。
6. 在运行过程中执行适用的健康探针，观察容器退出、重启和运行状态。
7. 根据配置处理终止等工作，并向 API Server 更新 Pod 状态；上报可以与准备、重试交错进行。

Pod sandbox 是运行时管理 Pod 级运行环境的抽象，不能直接等同于业务容器。普通 Linux Pod 的网络准备往往涉及运行时的 CNI 集成；存储插件的接入又是另一条机制，不能把所有准备工作都归给 CRI。

例如，`web-demo` 中一个 Pod 已绑定到 Node A，kubelet 仍可能因卷未就绪、Sandbox 网络配置失败或业务镜像拉取失败而无法启动应用。这些阶段有各自的前提和重试，不能将上述编号当作跨实现一致的精确时序，更不能因 Pod 已有节点位置就跳过准备阶段的证据。

[![Pod 绑定后的节点侧协调](/assets/notes/kubernetes/k8s-node-pod-workflow.svg)](/assets/notes/kubernetes/k8s-node-pod-workflow.svg)

图中分开表示配置准备、运行时操作与持续反馈。Sandbox 不等于业务容器，网络准备也不等于启动后的逐包转发。[v1.28 kubelet 的 Pod 同步实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/kubelet/kubelet.go)、[containerd v1.7.0 CRI 架构](https://github.com/containerd/containerd/blob/v1.7.0/docs/cri/architecture.md)

### 2.1 普通 Pod 与静态 Pod

普通 Pod 通常通过 Kubernetes API 创建，再由相应调度路径确定节点。静态 Pod（Static Pod）则由 kubelet 根据节点本地配置直接管理，不经过普通 Scheduler 选择节点的流程；kubeadm 管理的控制平面常采用静态 Pod。

kubelet 可以为静态 Pod 在 API 中创建 Mirror Pod（镜像 Pod），方便通过 `kubectl` 观察。它是节点本地工作负载的 API 表示，不意味着原静态 Pod 已被 Deployment 接管；删除 Mirror Pod 也不等于删除本地静态 Pod。[Kubernetes 静态 Pod](https://kubernetes.io/docs/tasks/configure-pod-container/static-pod/)

## 3. 看状态时，先分清三个层级

应用能否接收请求，需要结合节点、Pod、容器与就绪条件分层判断：

| 观察对象 | 典型字段或显示                   | 它能说明什么                                     |
| -------- | -------------------------------- | ------------------------------------------------ |
| Node     | `Ready` 等条件                   | 节点在所观察维度上的状态，不是每个应用的验收结果 |
| Pod      | `status.phase`                   | Pod 生命周期的粗粒度概况                         |
| 容器     | `Waiting / Running / Terminated` | 该容器当前处于哪个运行阶段                       |
| Pod 条件 | `Ready`、`ContainersReady` 等    | 就绪判断及其他条件；不是 Pod phase 的取值        |

`kubectl get` 展示的 `STATUS` 是面向人的摘要，不能把里面出现的所有文字都当成 API 的 `phase`。例如 `CrashLoopBackOff` 不是 Pod phase，`Terminating` 也不是。

Pod Phase（阶段）是粗粒度生命周期概况；Pod Conditions（条件）是 `Ready`、`PodScheduled` 等分别报告的条件。Container State（容器状态）描述单个容器，`restartCount` 则记录对应容器的重启次数，是累计线索而非重启原因。Pod 的 `Running` 阶段和容器的 `Running` 状态属于不同字段，`Ready` 始终不是 Phase。

| 观察组合                                | 能说明什么                                                 | 不能说明什么                                |
| --------------------------------------- | ---------------------------------------------------------- | ------------------------------------------- |
| Pod Pending，`spec.nodeName` 为空       | 通常尚未完成节点绑定，应查看 PodScheduled 和调度事件       | 不能直接断言 Scheduler 进程故障             |
| Pod Pending，已有 `nodeName`            | 已指定节点，可能仍在准备镜像、卷或 Sandbox                 | 容器已启动或网络已经验收                    |
| Pod Running，Ready=False                | Pod 已进入运行阶段，但尚未满足整体就绪条件                 | 不能保证业务可承接流量                      |
| 某容器 Waiting，Reason=CrashLoopBackOff | 该容器在反复失败后的重启退避中；Pod Phase 可能仍是 Running | 不能把它当成独立 Phase 或只凭它判断根因     |
| Pod Ready=True                          | 满足容器就绪及所配置的就绪门控等条件                       | 所有下游依赖、Service、DNS 和业务链路均正常 |

`Terminating` 通常与删除过程有关，要看 `metadata.deletionTimestamp` 等信息；`kubectl` 的 STATUS 摘要不会替代上述 API 字段。

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
- Kubernetes 1.28 支持内置 gRPC 探针（1.27 起稳定），服务需要实现 gRPC Health Checking Protocol（gRPC 健康检查协议）；端口必须是数字，不支持命名端口，也不能把需要 TLS/认证的普通 gRPC 接口直接当成这类探针端点。

上述字段与 liveness/startup 的 `successThreshold` 必须为 1 的约束，可在 [v1.28.0 API 校验源码](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/core/validation/validation.go)中核对。

HTTP、TCP、exec 以及内置 gRPC 都可用于相应探针目的，但各自有参数和协议要求。readiness 可配置连续成功次数，liveness/startup 的 `successThreshold` 必须为 1；检查方式不能替代对“启动、存活、就绪”语义的设计。[1.28 探针配置说明](https://github.com/kubernetes/website/blob/release-1.28/content/en/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes.md)

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

### 4.3 慢启动服务的时间线

假设一个 Web 服务启动时需要加载模型，下列时间和检查结果全部是人为设定的教学条件，不是实际运行记录或 kubelet 的精确执行保证：

| 假设时刻 | 应用情况与探针行为                                                                                                        |
| -------- | ------------------------------------------------------------------------------------------------------------------------- |
| 0 秒     | 容器启动，Startup Probe 进入检查阶段；Liveness、Readiness 尚未执行                                                        |
| 20 秒    | 仍在加载模型，Startup 尚未成功；只要未达到启动失败阈值，就继续等待                                                        |
| 40 秒    | Startup 首次成功，启动门控解除，后续按配置执行 Liveness 与 Readiness；不要求它们恰在第 40 秒同时检查                      |
| 50 秒    | 业务暂时无法接单，Readiness 连续失败达到阈值后使就绪条件转为失败；假设存活接口仍正常，不直接触发重启                      |
| 70 秒    | 业务恢复，Readiness 按成功阈值重新通过后恢复就绪；相应端点传播还需要时间                                                  |
| 更晚时刻 | 应用发生无法自行恢复的死锁，Liveness 持续失败达到阈值后，kubelet 终止该容器，再按适用重启策略处理；新实例重新经历启动检查 |

`failureThreshold × periodSeconds` 可帮助估算检查窗口，不能当作精确的终止或恢复倒计时。就绪变化还要考虑探针超时、阈值、检查时机及状态传播；即使所有探针成功，也不能证明业务全链路正确。

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

### 6.1 案例：Pod Running，但重启次数持续增加

以下是排查推演，未在本次修订中执行。假设第一章 `web-demo` 的某个 Pod 出现此现象，具备读取 Pod、Events 和容器日志的权限。先从列表选择实际 Pod，将 `POD_NAME` 替换为名称；容器名 `web` 与第一章一致：

```bash
kubectl get pods -n k8s-arch-demo -l app=web-demo
kubectl get pod POD_NAME -n k8s-arch-demo -o wide
kubectl describe pod POD_NAME -n k8s-arch-demo
kubectl get events -n k8s-arch-demo --field-selector involvedObject.kind=Pod,involvedObject.name=POD_NAME --sort-by=.metadata.creationTimestamp
kubectl get pod POD_NAME -n k8s-arch-demo -o jsonpath='{.metadata.uid}{"\n"}{range .status.containerStatuses[*]}{.name}{" restart="}{.restartCount}{" id="}{.containerID}{"\nstate="}{.state}{"\nlastState="}{.lastState}{"\n"}{end}'
kubectl logs POD_NAME -n k8s-arch-demo -c web --previous
```

先读当前 State，再看 Last State 中的 `terminated.reason`、`exitCode` 与时间，并和探针事件、上一个实例的日志对应。事件会聚合或过期，当前实例可能恰好在两次查询之间变化，不能把一次输出当作完整历史。

| 线索                     | 优先观察方向，不是已确认根因                                                      |
| ------------------------ | --------------------------------------------------------------------------------- |
| `OOMKilled`              | 容器内存限制、实际内存使用和节点压力、退出证据；不能只凭退出码 137 就认定同一原因 |
| `Liveness probe failed`  | 应用响应、探针路径、超时与连续失败阈值，以及是否达到终止条件                      |
| 非零退出码               | 上个实例日志、启动命令、应用配置和依赖；退出码需要结合程序解释                    |
| `ImagePullBackOff`       | 镜像引用、仓库连通、凭据和拉取策略；这是拉取退避，不等于应用启动后崩溃            |
| `FailedCreatePodSandBox` | CRI、网络插件及节点条件；可能尚未启动业务容器，不仅是应用错误                     |

比较不同观察时刻的 Pod UID、Container ID 和 `restartCount`：UID 不变而容器实例 ID 变化、计数增加，支持“同一 Pod 内重启”的判断；控制器新建的替代 Pod 有新的 UID，计数不能跨 Pod 直接累计。重启计数是节点报告的状态，kubelet 状态丢失等情况也会影响记录，必要时还需节点日志佐证。

## 7. 本章小结

kubelet 负责本节点的持续协调，不代替调度器或工作负载控制器。状态需要按节点、Pod、容器和条件分层理解；探针要按启动、存活、就绪分工。下一章进入它调用的运行时，解释为什么 `ctr` 看到的对象和 `kubectl` 看到的资源不能直接画等号。

[返回本册目录](/collections/kubernetes/) · [下一章：容器运行时与 containerd 工具边界](/articles/kubernetes-container-runtime.html)
