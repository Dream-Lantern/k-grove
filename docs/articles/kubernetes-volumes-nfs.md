---
id: kubernetes-volumes-nfs
title: 第二十二章 Volume、emptyDir、hostPath 与 NFS
description: "容器镜像提供文件系统基础，运行中的可写层不适合作为跨 Pod 生命周期的数据保留承诺。卷让容器通过某个路径访问适用的数据来源。"
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
order: 22
---

# 第二十二章 Volume、emptyDir、hostPath 与 NFS

> 本章以 Kubernetes 1.28 的 Linux 场景为主，比较临时卷、节点目录与远端文件系统的数据生命周期，并说明 NFS 导出配置和维护命令的含义。

## 1. 卷把路径与数据来源连接起来

容器镜像提供文件系统基础，运行中的可写层不适合作为跨 Pod 生命周期的数据保留承诺。Volume（卷）让容器通过某个路径访问适用的数据来源。

一个 Pod 的 `volumes` 定义来源，各容器的 `volumeMounts` 定义挂载位置，通过 `name` 对应。相同卷在两个容器中可以挂到不同路径；文件能否互读写还受权限与访问方式影响。

[![卷的生命周期：先问数据属于谁](/assets/notes/kubernetes/k8s-volume-lifetimes.svg)](/assets/notes/kubernetes/k8s-volume-lifetimes.svg)

图按数据所属层级逐项比较，箭头不代表数据会自动从 emptyDir 迁移到远端存储。

| 存储方式   | 容器实例重启         | Pod 删除后以新 UID 替代  | 数据归属     |
| ---------- | -------------------- | ------------------------ | ------------ |
| 容器可写层 | 不保证保留旧实例内容 | 不保留旧实例内容         | 容器实例     |
| emptyDir   | 同一 Pod 中通常保留  | 不继承原卷内容           | Pod 生命周期 |
| hostPath   | 节点目录可继续存在   | 取决于实际节点和目录     | 指定 Node    |
| NFS        | 通常不删除远端数据   | 满足挂载条件时可再次访问 | NFS 服务端   |

容器重启与 Pod 替换是不同事件。数据继续存在不等于已备份；能共享访问也不等于应用具有并发写入一致性。[1.28 卷生命周期与类型](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/volumes.md)

## 2. emptyDir：跟随 Pod 的临时共享空间

emptyDir 适合临时文件、缓存及同 Pod 容器共享。普通容器重启不会单独清空它；Pod 生命周期结束后则不能继续依赖其中数据。

以下保存为 `volume-demo.yaml`，是完整 Pod。前置条件为 Linux 1.28 隔离集群、固定版本 busybox:1.36.1 可拉取，以及专用 study 命名空间和 Pod 管理权限；已有其他实验时另选命名空间并同步修改。仅使用无敏感价值的测试文本，不创建主机目录或远端存储。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: volume-demo
  namespace: study
spec:
  restartPolicy: Always
  securityContext:
    runAsUser: 1000
    runAsGroup: 1000
    fsGroup: 1000
  containers:
    - name: writer
      image: busybox:1.36.1
      command: ["sh", "-ec"]
      args:
        - |
          touch /tmp/healthy
          while true; do sleep 5; done
      livenessProbe:
        exec:
          command: ["sh", "-c", "test -f /tmp/healthy"]
        initialDelaySeconds: 2
        periodSeconds: 2
        failureThreshold: 2
      volumeMounts:
        - name: work
          mountPath: /work
    - name: reader
      image: busybox:1.36.1
      command: ["sh", "-c", "while true; do sleep 30; done"]
      volumeMounts:
        - name: work
          mountPath: /input
          readOnly: true
  volumes:
    - name: work
      emptyDir:
        sizeLimit: 1Gi
```

writer 的 /work 与 reader 的 /input 对应同一个卷。`sizeLimit` 也不是为 Pod 自动预留一整块磁盘；节点实际容量、临时存储与驱逐条件仍需要考虑。内存型 emptyDir 还有内存核算等条件，不能只看它“速度可能更快”。

这里不是共享两个镜像的所有文件系统。卷内文件仍受 UID/GID（用户/组标识）与权限影响；本例统一身份并设置 fsGroup，让卷目录可供 writer 写入，reader 通过只读挂载读取。

### 2.1 写入、读取与仅重启容器

以下 create/apply、exec 写入和 delete 都会改变专用测试资源。先创建并记录状态，再写入文件：

```bash
# 仅当 study 不存在且专供本实验时创建
kubectl create namespace study
kubectl apply -f volume-demo.yaml
kubectl wait pod/volume-demo -n study --for=condition=Ready --timeout=120s
kubectl get pod volume-demo -n study -o jsonpath='{.metadata.uid}{"\n"}{.status.containerStatuses}{"\n"}'
kubectl exec volume-demo -n study -c writer -- sh -c 'printf "hello-from-writer\n" > /work/message.txt'
kubectl exec volume-demo -n study -c reader -- cat /input/message.txt
```

预期 reader 读到 hello-from-writer。接着仅在此测试 Pod 中移除 writer 的存活标记，让 liveness 达到失败阈值后由 kubelet 重启 writer；这不是删除重建整个 Pod：

```bash
kubectl exec volume-demo -n study -c writer -- rm /tmp/healthy
kubectl describe pod volume-demo -n study
kubectl get pod volume-demo -n study -o jsonpath='{.metadata.uid}{"\n"}{.status.containerStatuses}{"\n"}'
# 等待 writer 重启并重新运行后，再读取
kubectl exec volume-demo -n study -c reader -- cat /input/message.txt
```

连续观察直到 writer 的 restartCount 增加、重新处于 Running，且 Pod UID 仍与此前相同；reader 未被主动重启。标记位于 writer 的 /tmp，与共享卷不同，writer 启动时只重建标记，不覆盖 message.txt，因此同一 Pod 的 emptyDir 内测试文本应保留。探针检查、终止宽限和重启退避使等待时间不固定，不能承诺几秒内完成。

如出现 Pod UID 改变、节点故障或 Pod 驱逐，已不是同一实验前提。最后只清理测试 Pod；删除后的新 Pod 即使同名，也不会继承原 emptyDir，不能用它代替持久化：

```bash
kubectl delete -f volume-demo.yaml
```

### 2.2 磁盘与内存型 emptyDir

以下是 Pod spec 下的局部示意，未应用，不与前面的 1Gi 磁盘型卷混淆：

```yaml
volumes:
  - name: cache
    emptyDir:
      medium: Memory
      sizeLimit: 256Mi
```

tmpfs（Temporary File System，临时文件系统）把文件放入内存。Memory emptyDir 写入的文件会计入适用写入容器的内存使用，可能与应用堆内存共同触及 limit，导致 OOM（Out of Memory，内存不足）等处理。sizeLimit 不是预留 256Mi，也不保证容器一定能写满该值。

| 类型          | 主要资源来源                         | 需关注                                             |
| ------------- | ------------------------------------ | -------------------------------------------------- |
| 默认 emptyDir | 节点适用临时存储，底层介质依节点配置 | 可用空间、ephemeral-storage 核算及节点压力驱逐     |
| medium=Memory | 内存 tmpfs                           | 写入容器内存用量、内存 limit、节点压力和卷容量上限 |

Memory 不代表没有资源代价，也不据此宣称任何负载性能最好。两者都随 Pod 生命周期结束，资源核算细节见上述 1.28 卷文档。

## 3. hostPath：节点目录不等于可迁移持久卷

hostPath 映射特定节点的路径。Pod 换到另一个节点，不会自动把原目录的数据带走；同一个绝对路径在不同节点也可能指向完全不同的数据。

Directory、DirectoryOrCreate、File、FileOrCreate 等 type 用于适用的类型检查或创建条件。FileOrCreate 不会替你创建缺失的父目录；空 type 不表示路径已经被完整安全验证。

DirectoryOrCreate 可在缺失时创建目录，按 kubelet 对应的所有者/组及目录权限处理；FileOrCreate 可创建空文件，但父目录必须先存在。创建成功仍不代表容器身份可读写，节点安全策略和文件权限也会影响结果。

hostPath 可能暴露节点文件、Unix Socket 或敏感设备；readOnly 也不能消除读取敏感信息的风险。本章不把主机根目录、运行时 Socket、kubelet 敏感目录或 privileged 配合 hostPath 作为默认实验，更不在节点上写入或删除文件。[1.28 hostPath 类型与限制](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/volumes.md)

| 场景                | 选择方向                                  |
| ------------------- | ----------------------------------------- |
| 同 Pod 临时共享文件 | emptyDir                                  |
| 节点日志采集        | 按实际路径与最小权限评估 hostPath         |
| Pod 换节点仍需数据  | 不能仅依赖 hostPath，核对实际持久后端能力 |
| 业务持久化          | 评估 PV/PVC 与存储后端、备份和恢复        |

## 4. NFS：数据在远端，风险也有远端部分

NFS（Network File System，网络文件系统）的数据在远端。Pod 卸载或删除后，远端数据通常仍由服务器端管理；是否保留、可恢复和安全，不取决于 Pod 对象是否存在。

客户端节点需要具备适用的挂载支持，服务端需要导出目录、网络可达和正确权限。不能只在一台节点测试成功，就宣称整个集群都可用。

典型访问关系为 Pod 中的挂载路径 → Node 上的 NFS 客户端与内核挂载 → 网络 → NFS Server 的导出目录。kubelet 根据卷配置协调挂载，不会自动创建远端 NFS 服务。服务端需允许对应客户端，节点需具备挂载工具和协议支持，读写还受身份映射、文件权限与挂载选项约束。

[![NFS：远端导出、节点客户端挂载与容器路径](/assets/notes/kubernetes/k8s-nfs-mount-path.svg)](/assets/notes/kubernetes/k8s-nfs-mount-path.svg)

以下是 Pod spec 下的只读结构片段。192.0.2.10 是文档示例地址，/exports/study 也是假设路径，不能据此实际连接；容器、镜像等必需字段仍省略。本章不部署 NFS 服务端、不改 exports 或执行挂载维护：

```yaml
volumes:
  - name: remote
    nfs:
      server: 192.0.2.10
      path: /exports/study
      readOnly: true
containers:
  - name: reader
    volumeMounts:
      - name: remote
        mountPath: /input
        readOnly: true
```

`no_root_squash` 关闭 root squashing（root 身份压缩映射），使客户端 UID/GID 0 不再按该机制映射为匿名身份，但不会绕过所有其他权限检查。它会改变安全边界，不宜作为通用默认；应分别核对客户端范围、身份映射、目录权限和读写需求。[exports(5) 的身份映射选项](https://man7.org/linux/man-pages/man5/exports.5.html)

| 现象                | 优先检查                                   |
| ------------------- | ------------------------------------------ |
| 挂载超时            | 服务端状态、网络路径与适用 NFS 服务        |
| Permission denied   | exports 客户端范围、UID/GID 映射、目录权限 |
| 部分节点失败        | 各节点客户端支持、网络及访问规则           |
| 挂载成功但不能写    | 容器身份、文件权限、只读挂载与服务端配置   |
| 网络中断后 I/O 卡住 | 挂载语义、服务端恢复与应用 I/O 行为        |
| 文件内容异常        | 并发访问、共享写入协议与应用一致性         |

这些是取证线索，不是症状与根因的一一对应；不要用默认关闭 root squash 或强制卸载替代定位。

## 5. exportfs 与卸载操作的含义 {#_5-命令纠错与保留的前提}

常见卸载命令是 `umount`；`exportfs` 则管理导出状态。重新导出和清空导出表是不同操作，各选项含义如下：

| 选项 | 含义，不是执行建议                                 |
| ---- | -------------------------------------------------- |
| -r   | 重新导出，使导出状态与 exports 等配置同步          |
| -f   | 清空内核导出表或适用缓存，不等同于重新读取 exports |
| -a   | 针对全部适用目录执行相应导出或取消导出动作         |
| -v   | 输出详细信息                                       |

历史环境的发行版和 nfs-utils 版本仍未确定，实际维护前需核对目标系统随附手册。

这里不提供可直接复制的服务端改配命令，因为原记录缺少发行版、服务端版本和维护窗口。Linux 上的命令语义可对照 [nfs-utils 的 exportfs 手册](https://man7.org/linux/man-pages/man8/exportfs.8.html)；实施时仍以目标系统随附文档为准。

挂载卡住时，应分别检查服务端故障、网络、挂载选项和进程状态。强制卸载或重启服务可能影响其他 Pod 和数据写入，不应作为排查的第一步。

## 6. 持久化与备份之间还差一步

远端共享卷可被多个 Pod 使用，不自动保证应用写入互斥、数据库一致性或历史恢复。一个错误程序也可能把共享数据一起删坏。

因此，卷能否挂载、文件能否读写、应用一致性、备份和恢复测试需要分别验收。下一章将通过 PV/PVC/StorageClass 解释如何解耦存储需求与具体后端，但这些抽象同样不能代替备份。

继续阅读[第二十三章 PV、PVC 与 StorageClass](/articles/kubernetes-persistent-volumes.html)。

[返回本册目录](/collections/kubernetes/)
