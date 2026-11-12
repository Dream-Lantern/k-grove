---
id: kubernetes-affinity-taints
title: 第二十四章 节点选择、亲和性与污点容忍
description: "nodeSelector、节点亲和性描述 Pod 对节点的要求或偏好；污点写在 Node 上，用来排斥未能容忍它的 Pod。"
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
order: 24
---

# 第二十四章 节点选择、亲和性与污点容忍

> Kubernetes 1.28 调度配置复盘，承接第六章调度器。未修改节点标签、污点或 Pod 配置。下面的片段为新增教学示意。

## 1. 节点选择与污点容忍的分工 {#_1-先分清-想去哪里-与-允许谁来}

nodeSelector（节点选择器）、Node Affinity（节点亲和性）描述 Pod 对节点的要求或偏好；Taint（污点）写在 Node 上，用来排斥没有匹配 Toleration（容忍）的 Pod。两者可以配合，但容忍一个节点污点不等于一定被调度到那个节点。

[![调度约束：容忍不等于一定安排到该节点](/assets/notes/kubernetes/k8s-scheduling-constraints.svg)](/assets/notes/kubernetes/k8s-scheduling-constraints.svg)

例如，为专用硬件节点设置污点，可以减少普通 Pod 进入；需要设备的 Pod 仍应声明设备资源和相应的选择条件。仅添加 toleration，并不能保证取得某块硬件。

## 2. 硬条件与软偏好

`nodeSelector` 是简单的节点标签约束。`nodeAffinity` 提供更丰富的匹配方式：

- `requiredDuringSchedulingIgnoredDuringExecution`：调度时必须满足。
- `preferredDuringSchedulingIgnoredDuringExecution`：参与偏好评分，不保证最终一定选择。

`IgnoredDuringExecution` 表示这类约束不会因为节点标签后来变化就自动按该亲和规则驱逐已有 Pod，不是“运行期间永远不受任何其他机制影响”。

新增片段，位于 Pod spec 下：

```yaml
nodeSelector:
  gpu: "true"
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: disktype
              operator: In
              values: ["ssd"]
```

同一个 term 里的表达式按 AND 组合，多个 nodeSelectorTerms 则按 OR 组合。常用运算符包括 `In`、`NotIn`、`Exists`、`DoesNotExist`；Gt/Lt 等运算符是否可用，需按具体选择器字段核对。

### 2.1 硬约束的交集

假设节点具有以下标签；表中 zone 简称指 topology.kubernetes.io/zone，gpu 的 true/false 是标签字符串，不是 Pod 已申请到 GPU：

| 节点   | disktype | zone   | gpu   |
| ------ | -------- | ------ | ----- |
| node-a | ssd      | zone-a | false |
| node-b | ssd      | zone-b | true  |
| node-c | hdd      | zone-b | true  |

套用上面 nodeSelector.gpu=true 与 required disktype=ssd：node-a 不满足 gpu，node-c 不满足磁盘类型，只有 node-b 同时通过。这仅是这两项条件的候选结果，资源、污点与存储仍可能阻止调度。

### 2.2 Term 内 AND、Term 间 OR

把 required 部分替换成下面片段，分别定义 Term A、Term B；不是把两个 Term 与上一份 required 清单同时提交：

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: topology.kubernetes.io/zone
              operator: In
              values: ["zone-a"]
            - key: disktype
              operator: In
              values: ["ssd"]
        - matchExpressions:
            - key: topology.kubernetes.io/zone
              operator: In
              values: ["zone-b"]
            - key: gpu
              operator: In
              values: ["true"]
```

| 节点   | Term A：zone-a AND ssd | Term B：zone-b AND gpu=true | A OR B | 若再叠加 nodeSelector.gpu=true |
| ------ | ---------------------- | --------------------------- | ------ | ------------------------------ |
| node-a | 满足                   | 不满足                      | 满足   | 不满足                         |
| node-b | 不满足                 | 满足                        | 满足   | 满足                           |
| node-c | 不满足                 | 满足                        | 满足   | 满足                           |

多个 required Term 之间虽为 OR，但 nodeSelector 与整个 required nodeAffinity 仍是 AND。不能把软偏好用作绕过这层交集的补丁。

下面位于 affinity.nodeAffinity 下，是独立的软偏好片段，可与相应硬条件共同配置：

```yaml
preferredDuringSchedulingIgnoredDuringExecution:
  - weight: 80
    preference:
      matchExpressions:
        - key: disktype
          operator: In
          values: ["ssd"]
```

weight=80 是评分权重，不是 80% 的调度概率。只对通过硬约束的候选节点产生偏好，最终还会综合其他 Scheduler（调度器）插件的评分，不能保证匹配节点必定被选中。[1.28 节点选择与亲和规则](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/scheduling-eviction/assign-pod-node.md)

## 3. Pod 亲和与反亲和看拓扑域

Pod Affinity（Pod 亲和性，字段 podAffinity）选择与某组 Pod 靠近的拓扑域；Pod Anti-Affinity（Pod 反亲和性，字段 podAntiAffinity）则表达适用的分离要求。先用选择器找参照 Pod，再通过 `topologyKey` 识别节点所在的域。

如果 topologyKey 是 zone，相同区内的另一节点也可能满足亲和，不要求参照 Pod 就在目标节点本机。若需要同节点，通常采用相应 hostname 拓扑键。

还要核对命名空间选择范围和拓扑标签是否齐全。把反亲和一律写成“不能同一个机房”，或把 NotIn 一律等同于 podAntiAffinity，都会丢失选择器和拓扑域的区别。[1.28 Pod 亲和与反亲和](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/scheduling-eviction/assign-pod-node.md)

以下是独立场景，不叠加上一节节点表：zone-a 包含 node-a、node-b，zone-b 包含 node-c；study 中 app=ledger 的数据库参照 Pod 已运行在 node-a，各节点均具有正确 zone 与 hostname 标签。

| 关系（只考虑本项）                               | node-a         | node-b         | node-c |
| ------------------------------------------------ | -------------- | -------------- | ------ |
| required Pod Affinity，topologyKey=zone          | 满足           | 满足，同区即可 | 不满足 |
| required Pod Affinity，topologyKey=hostname      | 满足，同节点域 | 不满足         | 不满足 |
| required Pod Anti-Affinity，topologyKey=hostname | 不满足         | 满足           | 满足   |

第一行可由 Pod spec 下的片段表达；namespaces 显式限定参照范围，省略 namespaces/namespaceSelector 时通常针对当前 Pod 所在命名空间，而不是全群集：

```yaml
affinity:
  podAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app: ledger
        namespaces: ["study"]
        topologyKey: topology.kubernetes.io/zone
```

若改为同节点关系，topologyKey 使用 kubernetes.io/hostname。若要反亲和，可采用下面独立片段：

```yaml
affinity:
  podAntiAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      - labelSelector:
          matchLabels:
            app: ledger
        namespaces: ["study"]
        topologyKey: kubernetes.io/hostname
```

Node Affinity 直接匹配 Node 标签；Pod Affinity/Anti-Affinity 通过参照 Pod 和节点拓扑判断。严格反亲和会缩小候选范围；硬反亲和可用的 topologyKey 还受 LimitPodHardAntiAffinityTopology 等准入配置影响，不能随意把 hostname 换成任意区域键就承诺可用。

## 4. 三种污点效果

| 效果             | 主要语义                     | 已运行 Pod                          |
| ---------------- | ---------------------------- | ----------------------------------- |
| NoSchedule       | 阻止不容忍的新调度           | 不因这一效果自动驱逐                |
| PreferNoSchedule | 尽量避开不容忍的 Pod         | 不是强制迁出                        |
| NoExecute        | 对未容忍者施加调度及驱逐语义 | 容忍与 tolerationSeconds 会影响处理 |

一个 Pod 可能需要匹配多个污点。Equal 关注适用的 key/value/effect，Exists 可不比较 value；省略某些字段会扩大匹配范围，不能随意用一个空 toleration 把所有限制都绕开。

纸面假设 Node A 有 dedicated=storage:NoSchedule：

| Pod | 容忍配置                                               | 仅此污点检查                |
| --- | ------------------------------------------------------ | --------------------------- |
| A   | 没有匹配容忍                                           | 不能通过新的调度检查        |
| B   | key=dedicated、Equal、value=storage、effect=NoSchedule | 可通过，但不保证选择 Node A |
| C   | key 不匹配                                             | 仍不能通过                  |

Pod B 的 spec 局部字段如下，未应用：

```yaml
tolerations:
  - key: dedicated
    operator: Equal
    value: storage
    effect: NoSchedule
```

`tolerationSeconds` 用于相应 NoExecute 容忍的持续时间，不是任何调度偏好的通用超时。驱逐也不是把原 Pod UID 搬到另一节点；是否产生替代 Pod 还取决于控制器等条件。[1.28 污点与容忍](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/scheduling-eviction/taint-and-toleration.md)

另一独立时间线：Pod 已在 Node A 运行，T0 后节点出现 dedicated=storage:NoExecute，并持续存在。不要与前面的 NoSchedule 效果混淆：

| 容忍情况                     | T0 之后的适用行为                                                          |
| ---------------------------- | -------------------------------------------------------------------------- |
| 无匹配容忍                   | 进入适用驱逐处理，不保证瞬时完成                                           |
| 匹配，未设 tolerationSeconds | 不因这个污点的容忍时间到期而驱逐，但仍可能受其他机制影响                   |
| 匹配，tolerationSeconds=60   | 可容忍约 60 秒；仍有该污点时随后进入适用驱逐处理，不保证第 60 秒已完成终止 |

最后一行的 Pod spec 片段如下。仅说明规则，不修改真实节点污点或执行驱逐：

```yaml
tolerations:
  - key: dedicated
    operator: Equal
    value: storage
    effect: NoExecute
    tolerationSeconds: 60
```

## 5. 拓扑分布是另一个有用补充

TopologySpreadConstraints（拓扑分布约束）可以表达副本在适用拓扑域中的分布目标。它与反亲和用途有交集，但不是完全相同的字段。配置时应先明确故障域、选择哪些 Pod、允许多大偏斜以及无法满足时的处理。

### 5.1 三个 Zone 的 maxSkew 推演

再使用独立场景：study 中 app=catalog 的已有匹配 Pod 在 zone-a、zone-b、zone-c 分别为 2、2、1。三个 Zone 都具备合格节点和 topology.kubernetes.io/zone 标签，其他硬条件不影响本例；不叠加前面的 gpu、节点亲和或 ledger 参照规则。

以下是完整结构示例，未创建；若要运行，需隔离集群、相应标签与既有 Pod 分布，且能够拉取 busybox:1.36.1。本章不修改节点标签或调度器配置，也不人为构造真实集群中的分布：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: catalog-spread
  namespace: study
  labels:
    app: catalog
spec:
  topologySpreadConstraints:
    - maxSkew: 1
      topologyKey: topology.kubernetes.io/zone
      whenUnsatisfiable: DoNotSchedule
      labelSelector:
        matchLabels:
          app: catalog
  containers:
    - name: app
      image: busybox:1.36.1
      command: ["sleep", "3600"]
```

topologyKey 划分拓扑域，labelSelector 选择同命名空间中参与统计的 Pod；新 Pod 自身也带 app=catalog，所以在候选域计数中加 1。DoNotSchedule 是硬约束；ScheduleAnyway 则倾向改善分布，不能当作同一项硬拒绝。

对于本例，调度过滤使用已有合格域的全局最小匹配数 1，比较“候选域已有数 + 新 Pod 的匹配贡献 − 全局最小值”与 maxSkew：

| 新 Pod 候选 Zone | 放入后分布 a/b/c | 本次候选域过滤值 | 仅此项结果 |
| ---------------- | ---------------- | ---------------- | ---------- |
| zone-c           | 2/2/2            | 1 + 1 − 1 = 1    | 满足 ≤ 1   |
| zone-a           | 3/2/1            | 2 + 1 − 1 = 2    | 不满足     |
| zone-b           | 2/3/1            | 2 + 1 − 1 = 2    | 不满足     |

这是有资格前提的三域算例，不是独立于其他条件的节点选择算法。maxSkew 的一般定义涉及候选域和全局最小值，不能在所有情况下只拿最终分布的最大数减最小数替代计算。[v1.28.0 TopologySpreadConstraint API 定义](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/core/v1/types.go)

[![TopologySpread：2/2/1 分布下，新 Pod 放到不同 Zone 的约束判断](/assets/notes/kubernetes/k8s-topology-spread-skew.svg)](/assets/notes/kubernetes/k8s-topology-spread-skew.svg)

### 5.2 合格域与版本边界

真实计数还受节点资格、标签、污点和调度配置影响。v1.28.0 中以下高级能力为默认开启的 Beta，管理员仍可覆盖门控：

| 字段                                 | 特性门控                               | 关键边界                                                                         |
| ------------------------------------ | -------------------------------------- | -------------------------------------------------------------------------------- |
| minDomains                           | MinDomainsInPodTopologySpread          | 只用于 DoNotSchedule；合格域数小于指定值时，全局最小数按 0 处理；未设时按 1 理解 |
| nodeAffinityPolicy、nodeTaintsPolicy | NodeInclusionPolicyInPodTopologySpread | 影响分布计数的节点纳入策略；缺省分别按 Honor、Ignore 处理                        |
| matchLabelKeys                       | MatchLabelKeysInPodTopologySpread      | 允许从新 Pod 标签选取相应键作为匹配条件，使用前核实版本与标签契约                |

nodeTaintsPolicy=Ignore 只是计数时的策略，不表示 Pod 可以穿过未容忍的 NoSchedule 污点。多个拓扑分布约束也需同时满足。本章基本例不设置这些高级字段。[1.28 拓扑分布说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/scheduling-eviction/topology-spread-constraints.md)与[v1.28.0 门控默认值](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)

配置 required 规则前，应对照节点标签、容量与已有约束计算候选范围。CPU 尚有余量时，其他硬条件的交集仍可能为空。

## 6. 先用事件解释 Pending

```bash
kubectl describe pod POD_NAME -n NAMESPACE
kubectl get nodes --show-labels
kubectl describe node NODE_NAME
kubectl get pod POD_NAME -n NAMESPACE -o yaml
```

排查时，应按资源、节点选择、Pod 拓扑关系、污点、卷及其他调度约束逐项对照。事件提供的是定位线索，不能把最先看到的原因认定为唯一原因；放宽条件前，还应确认它原本保障的隔离或可用性要求。

先看 Pending Pod 是否已有 spec.nodeName：未分配节点时，重点读 FailedScheduling 事件；已经绑定而仍 Pending 时，还要检查镜像、网络、卷挂载等节点启动过程，不将所有 Pending 都归因于 Affinity。然后依次核对节点标签 → nodeSelector/required NodeAffinity → Pod 亲和/反亲和参照与 Namespace → Taint/Toleration → 拓扑分布 → CPU/内存 requests → PVC 和存储拓扑。

单条事件不一定覆盖所有阻塞，多个硬约束的交集可能为空；不应直接删除所有污点或清空所有 Affinity 来“修好”调度。保留原来的隔离、存储与可用性目标，再按证据调整。下一章学习 [HPA](/articles/kubernetes-hpa.html)如何按指标改变期望副本数，它也不能取消上述调度约束。

[返回本册目录](/collections/kubernetes/)
