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

Deployment 中的副本通常可互换；有些应用还需要固定成员名、独立数据目录或受控的成员启动顺序。StatefulSet（有状态副本集）提供序号、稳定命名及卷申领等机制。

例如一组名为 ledger 的副本，可以采用 ledger-0、ledger-1 等逻辑名字。某个实例替换后能沿用相应身份和存储引用，但替代 Pod 的 UID、节点和 IP 仍可能改变。应用不能把稳定名字误当成永不变动的进程或地址。

[![StatefulSet：身份与存储分开管理](/assets/notes/kubernetes/k8s-stateful-identity.svg)](/assets/notes/kubernetes/k8s-stateful-identity.svg)

StatefulSet 不会自动将普通数据库变成多副本数据库。复制协议、选主、仲裁和备份仍需由应用及相应的运维方案实现。

StatefulSet 维护的是成员逻辑身份。PVC（PersistentVolumeClaim，持久卷申领）引用 PV（PersistentVolume，持久卷）。以 study 中的 ledger 为例：

| 成员     | 独立 PVC      | 重建后保持与可能变化的内容                          |
| -------- | ------------- | --------------------------------------------------- |
| ledger-0 | data-ledger-0 | 名称与对应存储引用可沿用，Pod UID、IP、节点可能变化 |
| ledger-1 | data-ledger-1 | 同上，不代表原容器进程一直存活                      |
| ledger-2 | data-ledger-2 | 同上，不表示三成员共享同一数据目录                  |

跨节点重新挂载还受 PV 拓扑、CSI（Container Storage Interface，容器存储接口）驱动、访问模式及后端能力约束，稳定名称不能消除存储限制。

## 2. serviceName 与 volumeClaimTemplates

StatefulSet 的 `serviceName` 与管理网络身份的 Service 相关；常见方式是准备 Headless Service（无头服务，不分配普通 ClusterIP，用于成员发现）。该 Service 需要创建并配置，不能只写一个名字就当作它已存在。

`volumeClaimTemplates` 为各副本产生对应的 PVC。Pod 引用相应卷，不意味着多个副本自动共享同一个数据目录，也不意味着一个节点故障后能不受限制地把卷同时挂到另一节点。

以下保存为 `ledger.yaml`，包含完整 Service 和 StatefulSet。它用固定版本 busybox:1.36.1 演示独立目录与身份，不是数据库，也不实现复制协议。前置条件是 Linux 1.28 隔离集群、专用 study 命名空间、镜像拉取权限，以及管理员已提供真实可用的 `study-storage` StorageClass（存储类）。缺少该存储类或供应器时，PVC 可能 Pending，不能预期直接部署成功。

```yaml
apiVersion: v1
kind: Service
metadata:
  name: ledger-headless
  namespace: study
spec:
  clusterIP: None
  selector:
    app: ledger
  ports:
    - name: http
      port: 8080
      targetPort: http
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: ledger
  namespace: study
spec:
  serviceName: ledger-headless
  replicas: 3
  podManagementPolicy: OrderedReady
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      partition: 0
  persistentVolumeClaimRetentionPolicy:
    whenDeleted: Retain
    whenScaled: Retain
  selector:
    matchLabels:
      app: ledger
  template:
    metadata:
      labels:
        app: ledger
    spec:
      containers:
        - name: app
          image: busybox:1.36.1
          command: ["sh", "-ec"]
          args:
            - |
              mkdir -p /data/www
              hostname > /data/www/index.html
              exec httpd -f -p 8080 -h /data/www
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 2
          volumeMounts:
            - name: data
              mountPath: /data
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

volumeClaimTemplates 中的 data 分别生成 data-ledger-0、data-ledger-1、data-ledger-2，挂载到对应成员的 /data。ReadWriteOnce 表达单节点读写访问模式，并不是通用的“一个 Pod 独占”保证。

集群域假设为 cluster.local 时，成员名为 `ledger-0.ledger-headless.study.svc.cluster.local`：依次是 Pod 名、Service 名、命名空间、服务域标识和集群域。cluster.local 只是常见示例。Service 必须存在，解析还受端点 Ready、CoreDNS 配置和 DNS 缓存影响；稳定名称不保证始终可解析或可达。这里没有设置 publishNotReadyAddresses，因此未就绪成员不应被当作已正常发布的就绪端点。

以下仅是复现步骤，create/apply 会修改实验资源；study 已被其他实验使用时应另选名称并同步修改所有清单和命令：

```bash
kubectl get storageclass study-storage
# 仅当 study 不存在且专供本实验时创建
kubectl create namespace study
kubectl apply -f ledger.yaml
kubectl rollout status statefulset/ledger -n study --timeout=180s
```

预期逐步出现三个成员及独立 PVC，全部运行后 HTTP 探针成功；清理时可删除自己创建的 StatefulSet 与 Service，清单保留策略为 Retain，PVC 将留待核对。本章不提供或执行 PVC/PV 删除命令，后续存储退役需依据备份与后端回收策略单独决定。

```bash
# 仅删除本实验创建的工作负载和服务，保留 PVC
kubectl delete statefulset ledger -n study
kubectl delete service ledger-headless -n study
kubectl get pvc -n study
```

## 3. 顺序管理与更新策略

默认 OrderedReady 管理方式要求按序推进适用的创建、扩缩容过程。Parallel 改变的是 Pod 管理行为，不能因此推导成滚动更新也必然完全并发。

| 三副本从零创建                 | 可能的管理过程                                                                       |
| ------------------------------ | ------------------------------------------------------------------------------------ |
| OrderedReady（默认，有序就绪） | 创建 ledger-0，等其 Running 且 Ready，再创建 ledger-1；等其满足条件，再创建 ledger-2 |
| Parallel（并行管理）           | 创建与扩缩容时不必等待前序成员 Ready 才继续处理其他成员，但仍受容量、存储等条件限制  |

Parallel 不是“RollingUpdate 同时更新全部成员”的开关。Ready 也不等于数据库已经完成日志追赶、复制或选主；如应用要求这些条件，应设计真实的就绪契约与成员管理。

在常见 RollingUpdate 路径里，更新通常从较大序号向较小序号推进，并等待相应就绪条件。`partition` 用来限定哪些序号进入更新范围，是按序号分界，不是按流量百分比划分灰度。

假设默认序号从 0 开始，三个成员初始均为 v1，模板已改为 v2。以下是 spec 下的局部字段，并未应用：

```yaml
updateStrategy:
  type: RollingUpdate
  rollingUpdate:
    partition: 2
```

| 分区阈值    | ledger-0（序号 0） | ledger-1（序号 1） | ledger-2（序号 2） |
| ----------- | ------------------ | ------------------ | ------------------ |
| partition=2 | v1                 | v1                 | v2                 |
| 再降至 1    | v1                 | v2                 | v2                 |
| 再降至 0    | v2                 | v2                 | v2                 |

表格为每阶段完成后的目标状态，不是同时替换。序号大于或等于 partition 才进入新版本范围；低于阈值的成员即使重建，也按相应旧修订恢复。阈值大于或等于本例副本数 3 时，没有现有成员进入新版本范围。每一步仍需满足就绪和更新策略条件。

[![StatefulSet 三成员：partition 从 2 降到 1 再降到 0](/assets/notes/kubernetes/k8s-stateful-partition.svg)](/assets/notes/kubernetes/k8s-stateful-partition.svg)

OnDelete 保留已有 Pod，之后在受控删除与重建时采用新的模板；字段值使用 `OnDelete`。

不能照搬 Deployment 的 `maxSurge`。1.28 中 StatefulSet 的 `maxUnavailable` 也有 Alpha 特性门控条件，不应写成无条件通用字段，更不能沿用 Deployment 的 25% 默认值。[1.28 StatefulSet 的更新与门控说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/statefulset.md)

## 4. 滚动失败后的模板回退与实例恢复 {#_4-滚动失败后-回退为何可能仍然卡住}

假如高序号的新 Pod 因配置错误始终不 Ready，更新可能停在那里。恢复旧模板后，控制器也不总会立即自动替换那个错误实例；历史版本存在需要针对已失败实例人工处理的情况。

以 partition=0、默认 OrderedReady 为例：v1 三成员健康 → 模板改 v2 → ledger-2 先重建 → 错误配置使其一直不 Ready → ledger-1、ledger-0 尚未更新。即使模板恢复 v1，1.28 文档所述的强制回退问题仍可能使更新等待错误实例 Ready，不能照搬 Deployment 的回滚预期。

该版本文档给出的处理包括恢复正确模板后，受控删除已经尝试错误配置的 Pod，使其重建；这必须先确认旧进程已退出、成员与存储状态安全，以及数据兼容性和恢复流程，不能直接转成强制删除脚本。[1.28 StatefulSet 强制回退说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/statefulset.md)

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

仅作纸面推演：三副本缩为两副本后，ledger-0、ledger-1 及 data-ledger-0、data-ledger-1 保留；ledger-2 被缩容，在上述 whenScaled=Delete 条件下，控制器为 data-ledger-2 设置适用的所有者关系，由垃圾回收执行相应删除流程。whenDeleted=Retain 不能覆盖缩容轴；普通 Pod 故障替换也不是缩容。前面完整实验特意使用 Retain/Retain，不能与这里的删除策略片段混用。

PVC 删除后，PV 与后端数据是否删除还取决于回收策略、驱动和保护机制。应按 Pod → PVC → PV → 后端逐层推演，而不是把 Delete 直接翻译成任何存储上立即擦除数据。[1.28 PVC 保留策略](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/statefulset.md) · [v1.28.0 门控默认值](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)

“StatefulSet 删除后 PVC 一定永远保留”和“删除 Pod 会自动清空 PVC”都不是通用结论。应用退役时，应逐项列出 StatefulSet、Service、PVC、PV 和后端数据的目标状态，并验证备份。

## 6. 查询时先看成员关系

```bash
kubectl get sts ledger -n study -o wide
kubectl get pods -n study -l app=ledger -o wide
kubectl get pvc -n study
kubectl describe sts ledger -n study
kubectl get sts ledger -n study -o jsonpath='{.status.currentRevision}{" "}{.status.updateRevision}{" "}{.status.replicas}{" "}{.status.readyReplicas}{"\n"}'
kubectl get statefulset APP -n NAMESPACE -o yaml
kubectl get pods,pvc -n NAMESPACE
kubectl describe pod POD_NAME -n NAMESPACE
```

关注当前模板、更新修订、成员序号、就绪、PVC 绑定和应用复制状态；Kubernetes 资源正常只覆盖其中一部分。

currentRevision、updateRevision 分别用于观察当前与目标更新修订，配合各 Pod 的 controller-revision-hash 标签判断版本；分区发布时两者可以不同。status.replicas 是观察到的成员数，readyReplicas 是其中 Ready 数，不能代替应用一致性检查。PVC 为 Bound 也不代表应用数据已正确恢复。

下一章的[DaemonSet](/articles/kubernetes-daemonset.html)关注节点覆盖，和 StatefulSet 的稳定成员身份解决不同问题。

[返回本册目录](/collections/kubernetes/)
