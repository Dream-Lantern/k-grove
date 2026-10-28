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

容器镜像提供文件系统基础，运行中的可写层不适合作为跨 Pod 生命周期的数据保留承诺。卷让容器通过某个路径访问适用的数据来源。

一个 Pod 的 `volumes` 定义来源，各容器的 `volumeMounts` 定义挂载位置，通过 `name` 对应。相同卷在两个容器中可以挂到不同路径；文件能否互读写还受权限与访问方式影响。

[![卷的生命周期：先问数据属于谁](/assets/notes/kubernetes/k8s-volume-lifetimes.svg)](/assets/notes/kubernetes/k8s-volume-lifetimes.svg)

图按数据所属层级逐项比较，箭头不代表数据会自动从 emptyDir 迁移到远端存储。

## 2. emptyDir：跟随 Pod 的临时共享空间

emptyDir 适合临时文件、缓存及同 Pod 容器共享。普通容器重启不会单独清空它；Pod 生命周期结束后则不能继续依赖其中数据。

新增教学片段，省略 containers 的其他必需字段：

```yaml
containers:
  - name: writer
    volumeMounts:
      - name: work
        mountPath: /work
  - name: reader
    volumeMounts:
      - name: work
        mountPath: /input
volumes:
  - name: work
    emptyDir:
      sizeLimit: 1Gi
```

writer 的 /work 与 reader 的 /input 对应同一个卷。`sizeLimit` 也不是为 Pod 自动预留一整块磁盘；节点实际容量、临时存储与驱逐条件仍需要考虑。内存型 emptyDir 还有内存核算等条件，不能只看它“速度可能更快”。

## 3. hostPath：节点目录不等于可迁移持久卷

hostPath 映射特定节点的路径。Pod 换到另一个节点，不会自动把原目录的数据带走；同一个绝对路径在不同节点也可能指向完全不同的数据。

Directory、DirectoryOrCreate、File、FileOrCreate 等 type 用于适用的类型检查或创建条件。FileOrCreate 不会替你创建缺失的父目录；空 type 不表示路径已经被完整安全验证。

hostPath 可能暴露节点文件、socket 或敏感设备。挂载 kubelet、运行时等路径时，尤其需要审查权限，不能仅因示例能够启动，就直接用于普通业务 Pod。[卷类型与限制](https://kubernetes.io/docs/concepts/storage/volumes/)

## 4. NFS：数据在远端，风险也有远端部分

NFS 的名称是 Network File System。Pod 卸载或删除后，远端数据通常仍由服务器端管理；是否保留、可恢复和安全，不取决于 Pod 对象是否存在。

客户端节点需要具备适用的挂载支持，服务端需要导出目录、网络可达和正确权限。不能只在一台节点测试成功，就宣称整个集群都可用。

`no_root_squash` 用于关闭 root squashing。它关闭 root squashing，使客户端 UID/GID 0 不再按该机制映射为匿名身份，但不会绕过所有其他权限检查。它会改变安全边界，不宜作为通用默认；应分别核对客户端范围、身份映射、目录权限和读写需求。[exports(5) 的身份映射选项](https://man7.org/linux/man-pages/man5/exports.5.html)

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

[返回本册目录](/collections/kubernetes/)
