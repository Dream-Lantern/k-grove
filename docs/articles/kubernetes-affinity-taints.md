---
id: kubernetes-affinity-taints
title: 第二十四章 节点选择、亲和性与污点容忍
description: nodeSelector、节点亲和性描述 Pod 对节点的要求或偏好；污点写在 Node 上，用来排斥未能容忍它的 Pod。两者可以配合，但容忍一个节点污点不等于一定被调度到那个节点。
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

## 1. 先分清“想去哪里”与“允许谁来”

nodeSelector、节点亲和性描述 Pod 对节点的要求或偏好；污点写在 Node 上，用来排斥未能容忍它的 Pod。两者可以配合，但容忍一个节点污点不等于一定被调度到那个节点。

[![调度约束：容忍不等于一定安排到该节点](/assets/notes/kubernetes/k8s-scheduling-constraints.svg)](/assets/notes/kubernetes/k8s-scheduling-constraints.svg)

例如，为专用硬件节点设置污点，可以减少普通 Pod 进入；需要设备的 Pod 仍应声明设备资源和相应的选择条件。仅添加 toleration，并不能保证取得某块硬件。

## 2. 硬条件与软偏好

`nodeSelector` 是简单的节点标签约束。`nodeAffinity` 提供更丰富的匹配方式：

- `requiredDuringSchedulingIgnoredDuringExecution`：调度时必须满足。
- `preferredDuringSchedulingIgnoredDuringExecution`：参与偏好评分，不保证最终一定选择。

`IgnoredDuringExecution` 表示这类约束不会因为节点标签后来变化就自动按该亲和规则驱逐已有 Pod，不是“运行期间永远不受任何其他机制影响”。

新增片段，位于 Pod spec 下：

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: disktype
              operator: In
              values: ["ssd"]
```

同一个 term 里的表达式按 AND 组合，多个 nodeSelectorTerms 则按 OR 组合。`In`、`NotIn`、`Exists`、`DoesNotExist` 的拼写与语义要准确，不能写成 DoesNotExists；Gt/Lt 等运算符也不是所有选择器场景都支持。

## 3. Pod 亲和与反亲和看拓扑域

podAffinity 选择与某组 Pod 靠近的拓扑域；podAntiAffinity 则表达适用的分离要求。先用选择器找参照 Pod，再通过 `topologyKey` 识别节点所在的域。

如果 topologyKey 是 zone，相同区内的另一节点也可能满足亲和，不要求参照 Pod 就在目标节点本机。若需要同节点，通常采用相应 hostname 拓扑键。

还要核对命名空间选择范围和拓扑标签是否齐全。把反亲和一律写成“不能同一个机房”，或把 NotIn 一律等同于 podAntiAffinity，都会丢失选择器和拓扑域的区别。[调度约束说明](https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/)

## 4. 三种污点效果

| 效果             | 主要语义                     | 已运行 Pod                          |
| ---------------- | ---------------------------- | ----------------------------------- |
| NoSchedule       | 阻止不容忍的新调度           | 不因这一效果自动驱逐                |
| PreferNoSchedule | 尽量避开不容忍的 Pod         | 不是强制迁出                        |
| NoExecute        | 对未容忍者施加调度及驱逐语义 | 容忍与 tolerationSeconds 会影响处理 |

一个 Pod 可能需要匹配多个污点。Equal 关注适用的 key/value/effect，Exists 可不比较 value；省略某些字段会扩大匹配范围，不能随意用一个空 toleration 把所有限制都绕开。

`tolerationSeconds` 用于相应 NoExecute 容忍的持续时间，不是任何调度偏好的通用超时。驱逐也不是把原 Pod UID 搬到另一节点；是否产生替代 Pod 还取决于控制器等条件。[污点与容忍](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)

## 5. 拓扑分布是另一个有用补充

TopologySpreadConstraints 可以表达副本在适用拓扑域中的分布目标。它与反亲和用途有交集，但不是完全相同的字段。配置时应先明确故障域、选择哪些 Pod、允许多大偏斜以及无法满足时的处理。

在未了解节点标签与容量前，不要同时添加大量 required 规则。即使集群看起来还有空余 CPU，多种约束组合后也可能找不到任何可行节点。

## 6. 先用事件解释 Pending

```bash
kubectl describe pod POD_NAME -n NAMESPACE
kubectl get nodes --show-labels
kubectl describe node NODE_NAME
```

查询未执行。排查时，应按资源、节点选择、Pod 拓扑关系、污点、卷及其他调度约束逐项对照。事件提供的是定位线索，不能把最先看到的原因认定为唯一原因；放宽条件前，还应确认它原本保障的隔离或可用性要求。

[返回本册目录](/collections/kubernetes/)
