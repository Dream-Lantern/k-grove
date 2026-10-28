---
id: kubernetes-statefulset
title: 第十六章 StatefulSet：身份、顺序与数据
description: "Deployment 中的副本通常可互换；有些应用还需要固定成员名、独立数据目录或受控的成员启动顺序。StatefulSet 提供序号、稳定命名及卷申领等机制。"
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
order: 16
---

# 第十六章 StatefulSet：身份、顺序与数据

> Kubernetes 1.28 复盘。示例只帮助理解资源关系，没有部署数据库，也没有操作 PVC。涉及有状态实例时，顺序和数据安全要一起考虑。

## 1. 哪些应用需要稳定身份

Deployment 中的副本通常可互换；有些应用还需要固定成员名、独立数据目录或受控的成员启动顺序。StatefulSet 提供序号、稳定命名及卷申领等机制。

例如一组名为 ledger 的副本，可以采用 ledger-0、ledger-1 等逻辑名字。某个实例替换后能沿用相应身份和存储引用，但替代 Pod 的 UID、节点和 IP 仍可能改变。应用不能把稳定名字误当成永不变动的进程或地址。

[![StatefulSet：身份与存储分开管理](/assets/notes/kubernetes/k8s-stateful-identity.svg)](/assets/notes/kubernetes/k8s-stateful-identity.svg)

StatefulSet 不会自动将普通数据库变成多副本数据库。复制协议、选主、仲裁和备份仍需由应用及相应的运维方案实现。

## 2. serviceName 与 volumeClaimTemplates

StatefulSet 的 `serviceName` 与管理网络身份的 Service 相关；常见方式是准备适用的 Headless Service。该 Service 需要创建并配置，不能只写一个名字就当作它已存在。

`volumeClaimTemplates` 为各副本产生对应的 PVC。Pod 引用相应卷，不意味着多个副本自动共享同一个数据目录，也不意味着一个节点故障后能不受限制地把卷同时挂到另一节点。

新增字段关系片段，位于 StatefulSet spec 下，镜像、容器与 Service 等内容省略：

```yaml
serviceName: ledger-headless
replicas: 3
selector:
  matchLabels:
    app: ledger
updateStrategy:
  type: RollingUpdate
  rollingUpdate:
    partition: 0
volumeClaimTemplates:
  - metadata:
      name: data
    spec:
      accessModes: ["ReadWriteOnce"]
      storageClassName: study-storage
      resources:
        requests:
          storage: 10Gi
```

这不是完整部署清单。`study-storage` 需要真实可用的存储供应能力，Pod 模板还需要匹配标签和对应 volumeMounts。

## 3. 顺序管理与更新策略

默认 OrderedReady 管理方式要求按序推进适用的创建、扩缩容过程。Parallel 改变的是 Pod 管理行为，不能因此推导成滚动更新也必然完全并发。

在常见 RollingUpdate 路径里，更新通常从较大序号向较小序号推进，并等待相应就绪条件。`partition` 用来限定哪些序号进入更新范围，是按序号分界，不是按流量百分比划分灰度。

OnDelete 保留已有 Pod，之后在受控删除与重建时采用新的模板；字段值使用 `OnDelete`。

不能照搬 Deployment 的 `maxSurge`。1.28 中 StatefulSet 的 `maxUnavailable` 也有 Alpha 特性门控条件，不应写成无条件通用字段，更不能沿用 Deployment 的 25% 默认值。[1.28 StatefulSet 的更新与门控说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/statefulset.md)

## 4. 滚动失败后的模板回退与实例恢复 {#_4-滚动失败后-回退为何可能仍然卡住}

假如高序号的新 Pod 因配置错误始终不 Ready，更新可能停在那里。恢复旧模板后，控制器也不总会立即自动替换那个错误实例；历史版本存在需要针对已失败实例人工处理的情况。

处理这类问题前，必须确认旧模板、数据兼容性、成员状态与恢复流程，不能笼统地建议所有 StatefulSet 都“强删全部 Pod”。强制删除时，旧进程可能仍在其他位置运行，重复身份对有状态应用尤其危险。

应先收集实例状态、事件、修订信息与存储挂载结果，再按应用的成员恢复流程处理。具体恢复步骤需结合应用与目标版本，在隔离环境中通过故障实验验证。

## 5. 删除资源与删除数据分开决定

v1.28.0 的 StatefulSetAutoDeletePVC 为 Beta，上游默认开启；管理员仍可能覆盖门控。`persistentVolumeClaimRetentionPolicy` 有两个独立策略轴，默认均为 Retain：whenDeleted 控制删除 StatefulSet 时由模板创建的 PVC，whenScaled 控制缩容所对应的 PVC。

新增字段片段，位于 StatefulSet spec，不是通用推荐：

```yaml
persistentVolumeClaimRetentionPolicy:
  whenDeleted: Retain
  whenScaled: Delete
```

该例表示删除整个 StatefulSet 时保留相应 PVC，但缩容时删除缩掉副本对应的 PVC。普通故障 Pod 的替换不等于缩容，不应因此删除其原有 PVC。

PVC 删除后，PV 与后端数据是否删除还取决于回收策略、驱动和保护机制。应按 Pod → PVC → PV → 后端逐层推演，而不是把 Delete 直接翻译成任何存储上立即擦除数据。[1.28 PVC 保留策略](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/statefulset.md) · [v1.28.0 门控默认值](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)

“StatefulSet 删除后 PVC 一定永远保留”和“删除 Pod 会自动清空 PVC”都不是通用结论。应用退役时，应逐项列出 StatefulSet、Service、PVC、PV 和后端数据的目标状态，并验证备份。

## 6. 查询时先看成员关系

```bash
kubectl get statefulset APP -n NAMESPACE -o yaml
kubectl get pods,pvc -n NAMESPACE
kubectl describe pod POD_NAME -n NAMESPACE
```

命令未执行。关注当前模板、更新修订、成员序号、就绪、PVC 绑定和应用复制状态；Kubernetes 资源正常只覆盖其中一部分。

[返回本册目录](/collections/kubernetes/)
