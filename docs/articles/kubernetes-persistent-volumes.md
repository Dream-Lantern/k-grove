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

| 对象         | 作用                                 | 范围       |
| ------------ | ------------------------------------ | ---------- |
| PV           | 表示集群可用的持久卷及后端信息       | 集群级     |
| PVC          | 提出容量、模式等存储需求并绑定卷     | 命名空间级 |
| StorageClass | 描述动态供应等相关策略与 provisioner | 集群级     |

[![存储路径：Pod → PVC → PV → 后端](/assets/notes/kubernetes/k8s-storage-binding-detail.svg)](/assets/notes/kubernetes/k8s-storage-binding-detail.svg)

PV 不是磁盘分区本身，StorageClass 也不会凭空提供磁盘。动态供应依赖可用的驱动或 provisioner，以及所需的后端权限。存储驱动与 CRI 运行时处于不同层次，不能把原示意图中的 CRI 当作通用存储供应接口。

## 2. 静态匹配与动态供应

静态供应由管理员预先提供 PV，再根据 PVC 的要求匹配。动态供应则按适用的 StorageClass 与 provisioner 为申领创建相应资源。

匹配需要考虑容量、class、accessModes、volumeMode、选择器和绑定约束等条件，并非“同一个 class 名就必定绑定”。卷需要满足 PVC 的容量需求，但访问模式匹配并不要求两侧列表的文本完全相同。

`WaitForFirstConsumer` 会让供应或绑定与使用该 PVC 的 Pod 调度协同，因此 PVC Pending 不一定立即表示故障；要先看 class 的绑定模式和事件。

## 3. PVC 字段与 Pod 引用方式 {#_3-先纠正字段-再理解模式}

新增教学例子：假设 study-storage 是已经准备好的 StorageClass，未创建：

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
```

`accessModes` 声明所需访问模式，`volumeMode: Filesystem` 指定文件系统卷模式；Pod 通过 `persistentVolumeClaim.claimName` 引用 PVC。字段名及枚举值需按 API 的大小写填写。

```yaml
volumes:
  - name: data
    persistentVolumeClaim:
      claimName: catalog-data
```

这段是 Pod spec 内的片段，容器仍需配套 volumeMounts。PVC 必须在 Pod 可引用的同命名空间中。

## 4. RWO、RWX、ROX 与 RWOP

RWO（ReadWriteOnce）通常指单节点读写挂载，同节点多个 Pod 的使用情况仍需结合后端与实现；RWX（ReadWriteMany）表示多节点读写，ROX（ReadOnlyMany）表示多节点只读。

RWOP（ReadWriteOncePod）限制单 Pod 读写使用，在 1.28 属于 Beta，且有 CSI 与相关组件条件。不能只改一个字符串就假设任意 NFS 或旧驱动支持它。

访问模式描述可用的挂载能力及匹配条件，不代替文件系统权限、应用锁和一致性协议。RWX 也不等于多个数据库进程能安全共写同一数据目录。

上述模式与生命周期定义参见 [1.28 PV/PVC 文档](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/persistent-volumes.md)。

## 5. Bound、挂载成功、应用可写分开验收

PVC Bound 表示绑定关系形成。之后仍可能卡在卷附加、节点挂载、权限、文件系统或应用路径上。

```bash
kubectl get pvc -n NAMESPACE
kubectl describe pvc CLAIM_NAME -n NAMESPACE
kubectl get pv PV_NAME -o yaml
kubectl describe pod POD_NAME -n NAMESPACE
```

这些查询未执行。先看事件，再区分 Pending、Attach、Mount 与 Permission denied 等不同阶段。不要因为“PV 看起来正常”就直接删除 PVC 重试。

## 6. 回收策略决定数据风险

PV 使用 `persistentVolumeReclaimPolicy`；StorageClass 的相关字段是 `reclaimPolicy`。Retain 让后续回收需要人工管理，Delete 则可能由适用实现删除 PV 和后端存储。不能把 Delete 写成所有场景无条件的默认值。

Released 不等于安全可供另一个 PVC 自动重用。Recycle 是历史机制，不作为新实践建议。动态 provisioner 的 `archiveOnDelete` 等参数是实现特定行为，不能当作所有 StorageClass 的标准备份开关。

删除 PVC 前，至少应核对绑定的 PV、回收策略、驱动参数、后端对象与可用备份；扩容则还需确认 class、驱动、卷类型和文件系统是否支持。持久卷、快照与备份各有边界，仍须验证恢复后的应用数据是否一致。

[返回本册目录](/collections/kubernetes/)
