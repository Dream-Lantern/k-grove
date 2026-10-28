---
id: kubernetes-deployment
title: 第十五章 Deployment 发布、扩缩容与回滚
description: "Deployment 通过 ReplicaSet 协调符合模板的 Pod。用户通常修改 Deployment 的期望，而不是逐个修改它创建的 Pod。"
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
order: 15
---

# 第十五章 Deployment 发布、扩缩容与回滚

> 面向 Kubernetes 1.28 的无状态副本管理。命令均为未执行的学习示例，涉及更新、回滚和删除的命令不能当成只读检查。

## 1. Deployment 管理的是一组期望

Deployment 通过 ReplicaSet 协调符合模板的 Pod。用户通常修改 Deployment 的期望，而不是逐个修改它创建的 Pod。Pod 被替换后，新对象会来自相应模板。

修改 `spec.template` 才会触发适用的模板发布过程；只修改 `replicas` 是扩缩容，不因此产生一个新的应用模板版本。Deployment 自己的顶层 metadata 标签变化，也不等于 Pod 模板变化。

[![Deployment 发布：约束过程，不保证零故障](/assets/notes/kubernetes/k8s-deployment-rollout-detail.svg)](/assets/notes/kubernetes/k8s-deployment-rollout-detail.svg)

这个模型适合可互换副本。数据库的复制、主从切换和数据迁移并不会由 Deployment 自动完成，是否适用需要结合应用设计。

## 2. RollingUpdate 与 Recreate

RollingUpdate 逐步调整新旧 ReplicaSet 的副本；Recreate 会先终止旧 Pod，再创建新模板的 Pod。这是策略差异，不是“一个永远零停机，一个永远错误”。

新增教学片段，位于 Deployment spec 下：

```yaml
replicas: 4
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
minReadySeconds: 10
progressDeadlineSeconds: 600
```

这些数字用于解释：期望 4 个副本，允许适用的额外副本预算，并要求更新过程中不主动降低到低于期望的可用数量。实际是否有额外调度容量、应用是否 Ready，仍决定发布能否推进。终止中的 Pod 也可能暂时占用资源，不能只按期望副本加 surge 估计任何时刻的所有进程数。

`maxSurge` 百分比向上取整，`maxUnavailable` 百分比向下取整。两项不能同时为 0。`minReadySeconds` 参与“可用”的判断，避免仅短暂 Ready 就立即算成稳定副本。

发布失败条件不是自动回滚数据库的指令，`progressDeadlineSeconds` 也不等于“超时后平台自动还原所有状态”。参数定义以 [v1.28.0 Deployment API 类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/apps/v1/types.go)为准。

## 3. 更新策略与应用兼容性 {#_3-为什么滚动更新仍会中断}

更新策略可以约束副本调整，但无法修复错误探针、协议不兼容、共享依赖故障或数据库迁移问题。如果新副本过早 Ready，旧副本停止后，客户端仍可能收到错误。

发布前需要确认新旧版本能否同时工作：请求格式、缓存格式、数据库 schema、消息格式是否兼容？只要旧版仍可能接到请求，就不能假设整个系统已经原子切换。

同理，更新中途又修改模板，控制器会继续协调新的目标，不是承诺“先完成上一版再开始下一版”，也不能概括成“立即删除所有刚更新过的 Pod”。

## 4. 观察发布与历史

以下为学习模板，前三条观察发布，后两条会改变目标状态：

```bash
kubectl rollout status deployment/APP -n NAMESPACE
kubectl rollout history deployment/APP -n NAMESPACE
kubectl describe deployment APP -n NAMESPACE

# 变更示例，未执行
kubectl rollout undo deployment/APP -n NAMESPACE --to-revision=2
kubectl scale deployment/APP -n NAMESPACE --replicas=4
```

`--to-revision` 指定目标修订版本。回滚依赖保留的发布历史，`revisionHistoryLimit` 影响旧 ReplicaSet 的保留；历史是 Pod 模板的相关记录，不包括数据库备份、所有 ConfigMap 内容和外部副作用。

如果镜像标签可变，即使模板中保留了旧标签，也不能保证拉取到当时的同一份内容。因此，发布交接时需要固定镜像版本或 digest，并保存配置与兼容性说明。

## 5. 暂停、补丁与声明式源

Deployment 支持 pause / resume，用于暂停模板发布的推进；它不是冻结整个集群，也不表示其他控制器停止工作。准备多项模板变更时，需要同时保证声明源和在线对象最终一致。

JSON Patch 使用操作列表；直接写 `{"spec":{"replicas":3}}` 属于对象式补丁，不能同时宣称它是 `--type=json`。为避免低层补丁格式混乱，简单副本变更可以先理解 scale；正式流程则按团队确定的声明式工具管理。

暂停期间仍需考虑 HPA 或 GitOps 等其他字段管理者。多个工具反复覆盖 replicas，会使手工扩容看起来“自动失效”。

## 6. 删除前先看所有权和数据

典型 Deployment 的 ReplicaSet 与 Pod 会随适用的级联删除处理；Service 通常是独立对象，不因为标签相同就一起删除。孤儿化与后台、前台删除策略也会影响过程。

删除改变资源生命周期，回滚恢复相关模板版本，二者处理不同层次的问题。在确认数据、依赖和恢复路径之前，不应通过“全删重建”处理仅需修改配置的问题。

滚动发布的一般机制还可参阅 [Deployment 文档](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)，其中新功能和参数需要再与 1.28 对照。

[catalog 案例：配置、探针与发布一起推演](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
