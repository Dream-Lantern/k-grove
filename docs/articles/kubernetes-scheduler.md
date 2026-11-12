---
id: kubernetes-scheduler
title: 第六章：kube-scheduler——Pod 怎样找到节点，失败后又怎样重试？
description: "Pod 创建后，需要先完成节点选择和绑定，再由节点准备运行环境。排查 Pending 时，先区分尚未绑定与已经绑定这两种状态，才能定位到正确环节。"
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
order: 6
---

# 第六章：kube-scheduler——Pod 怎样找到节点，失败后又怎样重试？

Pod 创建后，需要先完成节点选择和绑定，再由节点准备运行环境。排查 Pending 时，先区分尚未绑定与已经绑定这两种状态，才能定位到正确环节。

Scheduler 主要解决前一个问题：为需要调度的 Pod 选择合适节点并推进绑定。它不是镜像下载器，也不是以“实时 CPU 最低”为唯一依据的负载均衡器。

本章按调度周期、扩展点和重试队列三个层次说明调度器。框架概念以官方说明为依据，源码接口、字段与默认值需固定版本；文中伪代码用于解释流程，尚未作为 Kubernetes 1.28 插件编译运行。

初次阅读可先完成第 1～3 节和[Pending 实验](#pending-lab)，再读[第 10 节排障](#pending-observation)；先掌握“约束 → 选择 → 绑定 → 节点执行”。第 4～9 节的框架扩展点、预留许可、队列与插件属于进阶选读。内部实现以 Kubernetes `v1.28.0` 为历史示例，不把当前文档新增的接口或行为反推为当年的默认配置。

## 1. 先分清四件事：创建、调度、绑定、运行

| 阶段          | 解决的问题                   | 主要观察对象                      |
| ------------- | ---------------------------- | --------------------------------- |
| 创建 Pod 对象 | API 中是否有这份运行规格     | Pod 对象及创建结果                |
| 调度决策      | 哪个节点满足需求，应该选哪个 | 调度约束、请求资源、候选节点      |
| 绑定          | 把选择结果记录到相应对象关系 | Pod 的节点绑定信息                |
| 节点执行      | 怎样准备并运行容器           | kubelet、运行时、镜像、网络和存储 |

因此，看到 Pod Pending 不能立即断定 Scheduler 有故障。已经绑定节点的 Pod 也可能因为镜像或卷等条件尚未满足而等待。

普通调度路径关注尚未绑定节点、需要由相应调度器处理的 Pod。静态 Pod、手工指定节点等特殊路径需要另外说明。[调度器概念](https://kubernetes.io/docs/concepts/scheduling-eviction/kube-scheduler/)

## 2. 选择节点看的是约束，不是随便找一台空闲机器

节点可能受到多类条件影响：

- Pod 请求的 CPU、内存、扩展资源等是否能安排。
- 节点标签、亲和性、污点与容忍等约束是否满足。
- 存储拓扑和相关卷条件是否允许。
- 已有工作负载与拓扑关系是否符合要求。
- 在可行节点之间，配置的评分规则怎样比较。

尤其要分清 `requests` 与实际使用率。调度中的资源核算不应直接解释成每次抓取实时 CPU 指标，再选择最低者。

### 一个新增教学例子

假设 Pod 请求 2 个 CPU，node-a 在相关请求核算下只剩 1 个，node-b 可以安排 3 个。仅看这项条件，node-a 就不能因为“此刻监控显示 CPU 很闲”而被当成满足请求的节点。

node-b 通过这一项检查，也不代表必然最终被选中：它还可能受到污点、亲和性或存储条件影响。这个例子没有来自真实集群的测量结果。

## 3. Filter 筛选可行节点，Score 比较候选节点 {#_3-filter-与-score-先问能不能-再问更适合谁}

过滤阶段检查候选节点是否可行。一个节点不满足某条硬约束，就不能仅凭其他评分很高补回来。

评分阶段则在可行节点中比较。不同插件可以根据各自规则打分，再经过相应归一化、权重和汇总过程形成选择依据。

所以，把“绑定阶段负责挑更合适的节点”作为两阶段定义并不准确。**主要的筛选、评分与选择发生在调度周期；绑定周期负责后续准备及绑定相关工作。**

候选节点的评估比例需要结合调度器版本与配置解释。候选评估策略和配置随版本、集群规模及实现而变化；缺少版本与配置时，不写死“总是检查 50%”或“只检查 5%”。

### 3.1 两个可行节点怎样比较？

假设 Node A、Node B 均通过 Filter。人为设定两个评分项及权重，帮助理解加权汇总：

| 评分项   | Node A | Node B | 权重 |
| -------- | -----: | -----: | ---: |
| 资源分布 |     80 |     60 |    1 |
| 节点偏好 |     30 |     70 |    2 |
| 合计     |    140 |    200 |    — |

Node A 的合计为 `80 × 1 + 30 × 2 = 140`，Node B 为 `60 × 1 + 70 × 2 = 200`。仅按这两个假设评分项，B 更优；如果 A 没有通过 Filter，它根本不会参与这张评分表。

分数、名称和权重都是教学假设，不是默认插件的实际输出。真实结果由启用的插件、归一化规则、权重、配置和版本决定；资源请求核算也不能直接替换成实时利用率。[调度框架评分机制](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/#scoring)

### 3.2 用 nodeSelector 制造并解除 Pending {#pending-lab}

本实验使用隔离测试集群。前提是 `kubectl` 上下文已核对，有创建专用命名空间、管理实验 Pod、读取事件和修改指定测试节点标签的权限。测试节点应允许该 Pod 调度、资源充足、网络正常且能获取镜像。不要对生产节点执行这些操作。

先清点标签，要求实验开始时所有节点都没有 `demo.example.com/eligible` 这个键。这样既保证没有节点匹配 `true`，也让清理时能够明确恢复为“键不存在”，无需覆盖已有值：

```bash
kubectl config current-context
kubectl get nodes -L demo.example.com/eligible
kubectl get nodes -l demo.example.com/eligible -o name
```

最后一条应无节点返回；若返回节点，或命令因权限等原因失败，停止实验，不覆盖、移除已有标签。选择经过授权的测试节点，将下面变量的值替换为真实名称，并记录原对象以便核对；后续标签命令在同一 Bash 终端执行。`k8s-scheduler-demo` 也必须是本次新建的专用空间：

```bash
DEMO_NODE='REPLACE_WITH_TEST_NODE'
kubectl get node "$DEMO_NODE" -o yaml > scheduler-node-before.yaml
kubectl create namespace k8s-scheduler-demo
```

保存以下完整清单为 `pending-demo.yaml`：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: pending-demo
  namespace: k8s-scheduler-demo
spec:
  nodeSelector:
    demo.example.com/eligible: "true"
  containers:
    - name: web
      image: nginx:1.28.0
      resources:
        requests:
          cpu: 100m
          memory: 64Mi
```

这里标签值是字符串 `"true"`。`nodeSelector` 是硬约束；即使有资源空闲的节点，没有标签匹配也不能选它。镜像标签仅用于固定示例版本，实际环境需维护镜像安全。

```bash
kubectl apply -f pending-demo.yaml
kubectl get pod pending-demo -n k8s-scheduler-demo -o wide
kubectl describe pod pending-demo -n k8s-scheduler-demo
kubectl get pod pending-demo -n k8s-scheduler-demo -o jsonpath='{.spec.nodeName}{"\n"}'
kubectl get events -n k8s-scheduler-demo --field-selector involvedObject.kind=Pod,involvedObject.name=pending-demo --sort-by=.metadata.creationTimestamp
```

在调度器正常处理后，预期 Pod 保持 Pending、`spec.nodeName` 为空，并出现与标签约束有关的 `FailedScheduling` 线索。事件可能稍后才出现，文字及列出的其他约束随版本与环境变化，不能要求它逐字等于某条示例错误。

在未被其他操作修改的测试节点上增加标签；**不使用 `--overwrite`**，若提示键已存在，应停止并核对环境变化：

```bash
kubectl label node "$DEMO_NODE" demo.example.com/eligible=true
kubectl wait --for=condition=PodScheduled pod/pending-demo -n k8s-scheduler-demo --timeout=120s
kubectl get pod pending-demo -n k8s-scheduler-demo -o wide
kubectl describe pod pending-demo -n k8s-scheduler-demo
```

节点标签变化会为重新评估提供线索。其他约束满足时，预期调度器再次尝试并完成绑定，`spec.nodeName` 变为选中的节点；不保证立即发生。若等待超时，继续看 Events，确认是否仍有污点、资源或其他约束。绑定成功后仍需 kubelet 拉镜像、配置网络并启动容器，所以不等于 Pod 已 Running 或 Ready。[将 Pod 指派给节点](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)

清理前核对节点标签仍是本实验添加的 `true`，没有他人后续修改。先删除实验 Pod，再移除本次新增的键，最后删除专用空间：

```bash
kubectl delete pod pending-demo -n k8s-scheduler-demo --wait=true
kubectl get node "$DEMO_NODE" -L demo.example.com/eligible
kubectl label node "$DEMO_NODE" demo.example.com/eligible-
kubectl get node "$DEMO_NODE" -L demo.example.com/eligible
kubectl delete namespace k8s-scheduler-demo
```

对照 `scheduler-node-before.yaml` 确认该键恢复为不存在。若加标签步骤没有成功，跳过移除标签命令；不要把整个旧 Node YAML 重新 apply 回去，以免覆盖其他字段。本实验验证标签硬约束与重新调度的可观察结果，不能仅凭这些输出确定内部队列位置。

## 4. 调度周期与绑定周期的边界

[![调度周期与绑定周期](/assets/notes/kubernetes/k8s-scheduler-cycles-detail.svg)](/assets/notes/kubernetes/k8s-scheduler-cycles-detail.svg)

图中归并了部分扩展点，省略失败分支；是框架职责图，不是某个版本的完整函数调用栈。

调度周期可以先理解为：从队列选取 Pod，检查条件，对节点筛选和评分，选择节点，并推进 Reserve、Permit 等相关处理。

绑定周期涉及等待许可、PreBind、Bind、PostBind 等工作。不同 Pod 的绑定过程可以与后续调度尝试交错或并发进行，不能理解为必须等一个 Pod 完成全部过程，才开始处理下一个。

Reserve 和 Permit 仍属于调度周期的框架处理；Permit 返回等待时，绑定周期中的等待逻辑会暂停后续推进。**“Permit 在调度周期”和“等待 Permit 发生在绑定周期”并不矛盾。** [Scheduling Framework](https://kubernetes.io/docs/concepts/scheduling-eviction/scheduling-framework/)

## 5. 逐个认识扩展点，而不是背一串缩写

下面按用途组织。扩展点是否启用、插件接口签名及实现细节必须按目标版本核对。

| 环节                   | 主要作用                       | 容易误解的地方                   |
| ---------------------- | ------------------------------ | -------------------------------- |
| PreEnqueue / QueueSort | 入队前条件与队列排序           | 不等于对节点评分                 |
| PreFilter              | 准备或检查调度相关状态         | 不是为所有节点执行完整启动检查   |
| Filter                 | 判断某节点是否可行             | 失败可能只排除该节点             |
| PostFilter             | 无可行节点时尝试相应补救       | 不是每轮过滤后的通用日志回调     |
| PreScore / Score       | 准备并计算节点分数             | 高分不能覆盖未满足的硬约束       |
| NormalizeScore         | 对相应评分结果做规范化         | 不是可以随意插入的独立任意阶段   |
| Reserve / Unreserve    | 预留相关状态，以及失败后的清理 | 不等于已经在节点分配好了实体设备 |
| Permit                 | 批准、拒绝或有期限地等待       | 不只有简单成功/失败两种结果      |
| PreBind / Bind         | 绑定前准备与提交绑定           | 不是重新选择最高分节点           |
| PostBind               | 绑定后的相应处理               | 不代表容器此时已经 Ready         |

扩展点的结果需要结合其作用域与状态语义解释：节点级过滤、等待许可和整体尝试失败，各自影响不同阶段。

例如，Filter 发现某个节点不符合要求，不代表集群没有其他可用节点；Permit 等待也不是立即失败。框架如何记录状态、回退和重试，需要结合具体阶段理解。

## 6. Reserve、Permit 和失败清理为什么值得单独理解？

### 6.1 Reserve 是逻辑协调，不是万无一失的物理锁

当框架为某次选择保留相应状态后，后续阶段仍然可能失败。如果没有回退，后来的调度可能一直认为某项资源被占用。

因此，Reserve 插件的清理逻辑需要正确处理重复执行、部分完成等情况。Unreserve 的幂等实现负责清理预留状态，外部资源还需独立核对是否完整释放。

例如某插件已为这个 Pod 记录一份调度侧预留，随后另一插件失败，回退必须能清理这份记录；即使自己的 Reserve 尚未完整完成，Unreserve 也要安全处理。否则重试会把残留状态当作真实占用。它不是“节点上的设备已实际交付容器”，框架也不能自动撤销插件发出的任意外部系统操作。

按框架约定，Unreserve 应具备幂等性，并且不能失败；相关 Reserve 失败或后续回退时，还要遵循框架规定的清理顺序。接口约定要求实现者正确处理，而不是框架替插件修复任意外部资源错误。[v1.28.0 Reserve/Unreserve 接口](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/scheduler/framework/interface.go)

### 6.2 Permit 可以等待，但不能无限等

某些调度扩展希望满足额外协同条件后才继续绑定。等待需要超时与拒绝处理，并配合前面预留状态的回退。

| Permit 结果 | 后续处理                                                                                     |
| ----------- | -------------------------------------------------------------------------------------------- |
| 批准        | 全部 Permit 插件批准后，继续绑定周期的后续阶段                                               |
| 拒绝        | 本次尝试不能继续绑定，触发相应 Unreserve 清理并按规则返回队列                                |
| 等待        | 调度周期返回等待状态；绑定周期等待批准，批准后再进入 PreBind，超时或拒绝则回退预留并重新排队 |

因此，“等待 Permit”不表示容器已经在节点上启动，也不表示绑定周期已成功完成。精确调用位置可对照 [Kubernetes v1.28.0 的调度与绑定实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/scheduler/schedule_one.go)；并非每个扩展点失败都能用同一条回退箭头概括。

这里不直接给出一个未经运行的协同调度插件。先把批准、拒绝、等待三种结果画清楚，再学习具体接口，比照抄某个 main 注册片段更稳妥。

### 6.3 Bind 完成，不等于应用启动完成

绑定记录使目标节点的 kubelet 可以继续处理，后续还会涉及镜像、网络、挂载和应用初始化。排查时应在绑定边界切换关注点，而不是把后续错误一律归于 Scheduler。

## 7. 调度队列：为什么失败后不能立即无限重试？

如果一个请求需要的条件暂时不存在，持续立即重试会消耗资源，也可能让其他 Pod 难以得到公平处理。调度器需要组织可尝试对象、待重新评估对象和退避对象。

[![Scheduler：失败之后如何再次尝试](/assets/notes/kubernetes/k8s-scheduler-retry-queues.svg)](/assets/notes/kubernetes/k8s-scheduler-retry-queues.svg)

图示保留常见概念，不表示每次失败都只能沿同一条固定路线进入队列；具体事件处理和队列实现随版本变化。

Pending 是 Kubernetes API 中的 Pod 阶段；Active、Unschedulable、Backoff 是调度器内部组织待处理工作的概念。`kubectl get pods` 的 Pending 一列不能告诉我们它具体在哪个内部队列；已绑定、等待节点准备的 Pod 也可能仍处于 Pending。

### 7.1 Active：可以进入尝试的对象

这里放置当前可以被取出进行调度尝试的 Pod。队列的排序与节点评分不是一回事：先决定取哪个 Pod，再为它评估节点。

### 7.2 Unschedulable：需要条件变化或重新评估

暂时没有可行节点时，相关对象需要等待适当的重新评估机会。节点、Pod、卷等相关变化可能提供线索，但不是任意一个对象变化都必须无差别唤醒全部失败 Pod。

重新评估除了外部事件，还可能由周期性刷新或其他重新入队机制触发，具体取决于版本实现。队列字段名和内部容器类型也不是稳定业务 API。

### 7.3 Backoff：避免高频重复尝试

退避会将部分重试推迟到合适的时间，但这并不表示系统保证“再过几秒一定调度成功”。它只限制尝试节奏；如果资源条件始终不满足，重试仍可能失败。

事件到达、是否仍处于退避期、当前调度尝试和队列移动的时序会影响实际转移。move request 相关竞态可作为队列源码阅读线索，其字段与时序属于内部实现。

例如，标签更新后可能先触发重新入队，若 Pod 仍在退避期，也不一定立即被取出尝试。理解 v1.28 的历史处理方式时，应对照 [v1.28.0 调度队列实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/scheduler/internal/queue/scheduling_queue.go)，不能从当前文档中的新机制推导所有历史版本默认行为。

## 8. 带上限的退避算例 {#_8-修正原笔记中的退避算例}

指数退避需要同时考虑增长规则和等待上限。示例将最大等待设为 10 秒时，计算出的等待时间也应截断到这个上限。

下面使用**人为设定的教学参数**，不宣称它们是任意版本的默认值：

```text
初始等待 b0 = 1 秒
最大等待 bmax = 10 秒
第 k 次连续失败的示意等待：
    wait(k) = min(b0 × 2^(k-1), bmax)，k 从 1 开始

示意序列：1、2、4、8、10、10……秒
```

实际队列还要结合事件、失败计数重置及实现时序，不能把这一公式当作所有内部行为的完整模拟。

下列调度队列设计资料适合了解历史设计，具体行为仍需对照目标版本实现。[调度队列设计资料](https://github.com/kubernetes/community/blob/f03b6d5692bd979f07dd472e7b6836b2dad0fd9b/contributors/devel/sig-scheduling/scheduler_queues.md)

## 9. Scheduler Plugin 与 Scheduler Extender 有什么区别？

框架插件通常以代码集成到调度器进程，依照对应接口参与扩展点处理。给出一个注册函数名，不等于已经提供了可编译、可用且版本兼容的插件。

Scheduler Extender 则是独立接口扩展路径。标准 Extender 使用相应的 HTTP 接口和配置，应与调度框架插件的进程内接口分开理解。

两种机制在扩展能力、版本耦合、故障影响和部署成本上都有差异。决定自定义之前，应先检查已有的调度配置、亲和性和插件能否满足需求。[调度扩展与配置](https://kubernetes.io/docs/reference/scheduling/config/)

<a id="pending-observation"></a>

## 10. Pending 的观察顺序

下面是笔记中的观察命令整理，未在实际集群执行：

```bash
kubectl get pod POD_NAME -n NAMESPACE -o wide
kubectl describe pod POD_NAME -n NAMESPACE
kubectl get pod POD_NAME -n NAMESPACE -o jsonpath='{.spec.nodeName}{"\n"}'
kubectl get events -n NAMESPACE --sort-by=.metadata.creationTimestamp
```

`POD_NAME`、`NAMESPACE` 是需替换的占位符，分别改成实际 Pod 名称和命名空间。`nodeName` 为空通常说明尚未完成节点绑定；非空说明已指定节点，但不能证明容器运行完成。手动在 Pod 中指定 `nodeName` 会绕过 Scheduler 的正常节点选择，不能把这种路径当成一次普通调度成功。

| 信息                 | 能提供的证据                                                 |
| -------------------- | ------------------------------------------------------------ |
| Pod Phase            | 当前生命周期阶段，不能直接映射为某个调度队列                 |
| Pod Events           | 调度或其他阶段的状态变化与失败线索，可能聚合或过期           |
| `spec.nodeName`      | 当前是否指定节点，结合 PodScheduled 条件判断绑定边界         |
| Scheduler 日志与指标 | 对内部调度尝试、失败与队列行为的进一步证据，需结合版本和配置 |

阅读结果时：

1. 先判断 Pod 是否已经绑定节点。
2. 如果未绑定，查看事件提示的是资源、污点、亲和性、卷还是其他条件。
3. 把提示与 Pod 规格、节点和相关存储对象对应，不只看一个状态单词。
4. 如果已经绑定，再沿 kubelet、运行时及应用准备过程继续。
5. 如果怀疑调度器本身异常，结合其领导者工作状态、API 访问及日志，不直接重启整套控制平面。

本章没有给出“调度失败就解除全部污点、删除所有 Pending Pod”的修复办法，因为这会改变隔离、业务与故障证据，而未必解决真正约束。

读完后，应能用一句话说明分工：**控制器决定需要哪些 Pod，Scheduler 为相应 Pod 选择节点，kubelet 再推进本节点上的运行。**

完成节点绑定后，接下来由[第七章 kubelet](/articles/kubernetes-kubelet.html)解释本节点如何准备 Pod、调用运行时并持续上报状态。

[返回本册目录](/collections/kubernetes/)
