---
id: kubernetes-persistent-volumes
title: 第二十三章 PV、PVC 与 StorageClass
description: "理解 Pod、PVC、PV 与 StorageClass 的引用关系，区分绑定、挂载、访问模式、动态供应和数据回收。"
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
order: 23
---

# 第二十三章 PV、PVC 与 StorageClass

> Kubernetes 1.28 存储原理与字段复盘。示例只说明引用关系；没有供应存储、挂载卷或删除数据。回收策略涉及真实数据时，必须先验证备份和恢复。

## 1. 三个对象解决三个问题

Pod 需要存储，但不适合把某台服务器的所有实现细节都写进应用模板。

PV（PersistentVolume，持久卷）、PVC（PersistentVolumeClaim，持久卷申领）和 StorageClass（存储类）分开表达后端、需求与供应策略：

| 对象         | 作用                                 | 范围       |
| ------------ | ------------------------------------ | ---------- |
| PV           | 表示集群可用的持久卷及后端信息       | 集群级     |
| PVC          | 提出容量、模式等存储需求并绑定卷     | 命名空间级 |
| StorageClass | 描述动态供应等相关策略与 provisioner | 集群级     |

[![存储路径：Pod → PVC → PV → 后端](/assets/notes/kubernetes/k8s-storage-binding-detail.svg)](/assets/notes/kubernetes/k8s-storage-binding-detail.svg)

PV 不是磁盘分区本身，StorageClass 也不会凭空提供磁盘。动态供应依赖可用的驱动或 provisioner，以及所需的后端权限。存储驱动与 CRI 运行时处于不同层次，不能把原示意图中的 CRI 当作通用存储供应接口。

典型动态供应关系可理解为 PVC → 引用 StorageClass → Provisioner（供应器）/CSI 驱动准备后端 → 创建 PV 并形成 PVC Bound → Pod 挂载 → 应用访问。CSI（Container Storage Interface，容器存储接口）不同于 CRI（Container Runtime Interface，容器运行时接口）。这是职责关系，具体顺序受绑定模式与驱动实现影响，不能画成所有存储都完全相同的固定调用链。

## 2. 静态匹配与动态供应

静态供应由管理员预先提供 PV，再根据 PVC 的要求匹配。动态供应则按适用的 StorageClass 与 provisioner 为申领创建相应资源。

匹配需要考虑容量、class、accessModes、volumeMode、选择器和绑定约束等条件，并非“同一个 class 名就必定绑定”。卷需要满足 PVC 的容量需求，但访问模式匹配并不要求两侧列表的文本完全相同。

假设两个静态 PV 均为 Available、Filesystem，且其他条件满足。PVC 请求 10Gi、RWO、class=fast：

| PV   | 容量 | accessModes | StorageClass | 此次容量判断      |
| ---- | ---- | ----------- | ------------ | ----------------- |
| pv-a | 20Gi | RWO         | fast         | 满足 20Gi ≥ 10Gi  |
| pv-b | 5Gi  | RWO         | fast         | 不满足 5Gi < 10Gi |

这只筛掉容量不足的 pv-b，不证明 pv-a 必定完成绑定；还需匹配 volumeMode、class、所需 accessModes、PVC selector、PV 状态和其他绑定条件，并使卷拓扑与 Pod 调度兼容。容量更大的 PV 不因被 10Gi 申领就自动切出剩余容量给另一申领。

storageClassName 省略与显式 `storageClassName: ""` 不等价：省略可能受默认 StorageClass 的准入或后续默认化处理影响，空字符串表示不请求某个存储类，不能当成选择默认类。PVC 的 spec.volumeName 可指向预期 PV，但仍需满足容量、class、访问模式等适用校验，也不免除挂载时的拓扑限制；不能用它绕过所有绑定规则。[1.28 PV/PVC 绑定与预绑定](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/persistent-volumes.md)

`WaitForFirstConsumer` 会让供应或绑定与使用该 PVC 的 Pod 调度协同，因此 PVC Pending 不一定立即表示故障；要先看 class 的绑定模式和事件。

### 2.1 两个可用区的绑定推演

假设 zone-a 有 Node A、zone-b 有 Node B，后端卷只能在其所在可用区使用。Pod 的硬节点亲和性要求 zone-b。对比两种假设 StorageClass 的 volumeBindingMode，而不是实际修改现有类：

| 模式                 | 可能过程                                      | 对此 Pod 的影响                                         |
| -------------------- | --------------------------------------------- | ------------------------------------------------------- |
| Immediate            | PVC 创建后先绑定/供应；若选到 zone-a 卷       | Pod 要求 zone-b，与卷区域冲突，可能无法调度             |
| WaitForFirstConsumer | 等待消费 Pod，再与 Scheduler 和供应器协调拓扑 | 在驱动、容量等条件允许时选择 zone-b 存储并调度至 Node B |

Immediate 不必然选错区域；上述是揭示提前绑定风险的可能路径。WaitForFirstConsumer 也不创造后端容量，需要 StorageClass、Provisioner/CSI 与拓扑支持，不能保证所有约束一定有解。NFS、云盘、局部磁盘的拓扑限制可能不同，不能一律套用区域云盘模型。

[![Immediate 与 WaitForFirstConsumer：存储拓扑和调度协作](/assets/notes/kubernetes/k8s-storage-wait-consumer.svg)](/assets/notes/kubernetes/k8s-storage-wait-consumer.svg)

本例的节点约束可以用 Pod spec 下的局部字段表达，未应用；topology.kubernetes.io/zone 需要节点真实具有相应标签：

```yaml
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
        - matchExpressions:
            - key: topology.kubernetes.io/zone
              operator: In
              values: ["zone-b"]
```

WFFC（WaitForFirstConsumer，等待首个消费者）期间 PVC Pending 可能是预期状态。直接用 spec.nodeName 绕过 Scheduler 可能使这种协作无法正常完成，不能作为 Pending 的通用修复。这里是卷绑定与调度协调，不是应用数据跨区复制。[1.28 StorageClass 绑定模式](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/storage-classes.md)

## 3. PVC 字段与 Pod 引用方式 {#_3-先纠正字段-再理解模式}

下面是完整 PVC 与 Pod，可保存为 `catalog-storage.yaml` 进行结构核对。假设管理员已提供真实可用的 study-storage；名称本身不代表任何集群都有它。运行需专用 Linux 1.28 测试集群、全新 study 测试 PVC、足够后端容量、供应器与节点插件、存储权限及可拉取的固定版本 busybox:1.36.1。不要把清单指向已有业务数据，本次不创建、删除或扩容实际 PVC/PV。

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: catalog-data
  namespace: study
spec:
  accessModes:
    - ReadWriteOnce
  volumeMode: Filesystem
  storageClassName: study-storage
  resources:
    requests:
      storage: 10Gi
---
apiVersion: v1
kind: Pod
metadata:
  name: catalog-storage
  namespace: study
  labels:
    app: catalog-storage
spec:
  restartPolicy: Never
  containers:
    - name: app
      image: busybox:1.36.1
      command: ["sh", "-ec"]
      args:
        - |
          printf 'catalog storage demo\n' > /data/study-message.txt
          sleep 3600
      volumeMounts:
        - name: data
          mountPath: /data
  volumes:
    - name: data
      persistentVolumeClaim:
        claimName: catalog-data
```

`accessModes` 声明所需访问模式，`volumeMode: Filesystem` 指定文件系统卷模式；Pod 通过 `persistentVolumeClaim.claimName` 引用 PVC。字段名及枚举值需按 API 的大小写填写。

容器的 data 挂载引用 Pod 中同名卷，再由 claimName 指向 study 的 catalog-data；PVC 必须在同命名空间。本例 Pod 标签为 app=catalog-storage，避免被前面 app=catalog 的 Service 或 PDB 误选；本章应使用专用测试命名空间，不与其他实验混用。本例只写无敏感价值的测试文件，不证明任意后端权限都已满足。清单没有定义 StorageClass 或 PV，不会自行安装供应器。

实验者只有在明确授权的测试环境创建上述对象后，才使用以下只读观察。预期先看到 PVC 的绑定或等待消费者事件，再检查 Pod 的挂载和测试文件；单 Pod 限时运行一小时，退出不会自动删除 PVC：

```bash
kubectl get storageclass study-storage -o yaml
kubectl get pvc catalog-data -n study
kubectl describe pvc catalog-data -n study
kubectl get pod catalog-storage -n study -o wide
kubectl describe pod catalog-storage -n study
kubectl exec catalog-storage -n study -c app -- cat /data/study-message.txt
```

若创建了本章专用 Pod，可在完成观察后仅删除它；保留 PVC/PV，先核对绑定、后端和保留策略，再由原授权管理者决定存储退役，本章不提供 PVC/PV 删除命令：

```bash
# 仅清理自己创建的测试 Pod，保留持久卷申领
kubectl delete pod catalog-storage -n study
```

## 4. RWO、RWX、ROX 与 RWOP

RWO（ReadWriteOnce）通常指单节点读写挂载，同节点多个 Pod 的使用情况仍需结合后端与实现；RWX（ReadWriteMany）表示多节点读写，ROX（ReadOnlyMany）表示多节点只读。

RWOP（ReadWriteOncePod）限制单 Pod 读写使用，在 1.28 属于 Beta，且有 CSI 与相关组件条件。不能只改一个字符串就假设任意 NFS 或旧驱动支持它。

| 模式                   | 典型含义           | 不能据此推出                              |
| ---------------------- | ------------------ | ----------------------------------------- |
| RWO：ReadWriteOnce     | 单节点读写挂载     | 只能由一个 Pod 使用；同节点可能有多个 Pod |
| RWX：ReadWriteMany     | 多节点读写挂载     | 自动保证多写事务一致性                    |
| ROX：ReadOnlyMany      | 多节点只读访问模式 | 单凭模式声明就替代实际只读挂载和文件权限  |
| RWOP：ReadWriteOncePod | 单 Pod 使用约束    | 任意旧驱动或任意 NFS 配置都支持           |

v1.28.0 的 ReadWriteOncePod 门控为默认开启的 Beta，管理员可能覆盖。RWOP 只支持适用 CSI 卷，驱动需支持对应访问语义；官方 Beta 说明要求相应 CSI sidecar 至少为 csi-provisioner v3.0.0、csi-attacher v3.3.0、csi-resizer v1.3.0，仍需按实际组件和驱动核对，不能当成安装了 Kubernetes 就自动满足。[1.27 RWOP Beta 官方说明](https://kubernetes.io/blog/2023/04/20/read-write-once-pod-access-mode-beta/)与[v1.28.0 门控](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)

访问模式描述可用的挂载能力及匹配条件，不代替文件系统权限、应用锁和一致性协议。RWX 也不等于多个数据库进程能安全共写同一数据目录。

上述模式与生命周期定义参见 [1.28 PV/PVC 文档](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/persistent-volumes.md)。

## 5. Bound、挂载成功、应用可写分开验收

PVC Bound 表示绑定关系形成。之后仍可能卡在卷附加、节点挂载、权限、文件系统或应用路径上。

| 阶段                                    | 已证明什么                                                         | 仍可能失败                                   |
| --------------------------------------- | ------------------------------------------------------------------ | -------------------------------------------- |
| PVC Bound                               | PVC 与 PV 形成绑定                                                 | 节点不兼容、驱动或后端故障                   |
| Volume Attach（卷附加）/Mount（卷挂载） | 满足适用后端的附加、节点挂载条件；并非每种后端都有独立 Attach 步骤 | 节点插件、挂载选项、文件系统与权限           |
| 应用实际访问                            | 指定容器身份可在指定路径读写                                       | 应用并发一致性、业务数据完整性与恢复仍需另验 |

```bash
kubectl get pvc -n NAMESPACE
kubectl get pvc -n study
kubectl describe pvc catalog-data -n study
kubectl get pv
kubectl describe pvc CLAIM_NAME -n NAMESPACE
kubectl get pv PV_NAME -o yaml
kubectl describe pod POD_NAME -n NAMESPACE
```

先看事件，再区分 Pending、Attach、Mount 与 Permission denied 等不同阶段。不要因为“PV 看起来正常”就直接删除 PVC 重试。

PVC Pending 可能在等待供应或消费者；Bound 但挂载失败应看 Pod Events、CSI 驱动/节点插件和后端状态；已挂载却 Permission denied 则继续检查容器 UID/GID、目录权限和文件系统。不要通过删除申领来掩盖不同阶段的问题。

## 6. 回收策略决定数据风险

PV 使用 `persistentVolumeReclaimPolicy`；StorageClass 的相关字段是 `reclaimPolicy`。Retain 让后续回收需要人工管理，Delete 则可能由适用实现删除 PV 和后端存储。不能把 Delete 写成所有场景无条件的默认值。

Released 不等于安全可供另一个 PVC 自动重用。Recycle 是历史机制，不作为新实践建议。动态 provisioner 的 `archiveOnDelete` 等参数是实现特定行为，不能当作所有 StorageClass 的标准备份开关。

假设 catalog-data 已绑定 pv-001，下面只作风险推演，不执行任何存储删除：

| 操作                   | 可能结果与边界                                                                                                |
| ---------------------- | ------------------------------------------------------------------------------------------------------------- |
| 删除普通消费 Pod       | 不因此删除 PVC；数据是否继续可用还需后端与后续挂载条件                                                        |
| 删除 PVC，PV 为 Retain | 待适用保护条件解除后，PV 通常进入 Released，后端留待人工回收；不是已备份或可直接安全复用                      |
| 删除 PVC，PV 为 Delete | 可能触发 PV 与后端存储删除，时机受保护机制、驱动和状态影响                                                    |
| 删除 StatefulSet       | 还需独立核对其 PVC Retention Policy，不能只看 PV 的回收策略                                                   |
| 删除 PV 对象           | 可能受 in-use protection/finalizer 阻止或延迟；后端处理依对象状态、驱动与回收实现，不能当作安全解绑或擦除工具 |

PVC 使用中的删除保护不等于取消删除请求，后续条件满足仍可能继续回收。StorageClass 的策略影响新供应 PV，实际排查应读取已绑定 PV 的 persistentVolumeReclaimPolicy。Retain 也可能保留误删或损坏后的数据，快照、备份和应用一致性恢复必须单独验证。

删除 PVC 前，至少应核对绑定的 PV、回收策略、驱动参数、后端对象与可用备份；扩容则还需确认 class、驱动、卷类型和文件系统是否支持。持久卷、快照与备份各有边界，仍须验证恢复后的应用数据是否一致。

理解绑定与存储拓扑后，继续在[第二十四章](/articles/kubernetes-affinity-taints.html)分析节点选择与调度约束的交集。

[返回本册目录](/collections/kubernetes/)
