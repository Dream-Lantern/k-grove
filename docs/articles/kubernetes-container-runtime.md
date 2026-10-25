---
id: kubernetes-container-runtime
title: 第八章 容器运行时与 containerd 工具边界
description: 启动一个容器，不只是运行一个镜像名字。还涉及获取镜像内容、准备根文件系统、设置隔离和资源约束、创建进程，以及记录退出结果。把所有实现都写进 kubelet，会使 Kubernetes 与具体运行时紧密耦合。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 8
---

# 第八章 容器运行时与 containerd 工具边界

> 以 Kubernetes 1.28 与 containerd 1.7 系列的接口关系为主要背景。原安装补充材料还混有后来的 containerd 2.x 配置，不能把两代配置直接拼成一份教程；版本冲突已在第二章单独说明。本章不安装、不启动、不清理任何运行时对象。

## 1. kubelet 为什么不直接管理所有 Linux 细节

启动一个容器，不只是运行一个镜像名字。还涉及获取镜像内容、准备根文件系统、设置隔离和资源约束、创建进程，以及记录退出结果。把所有实现都写进 kubelet，会使 Kubernetes 与具体运行时紧密耦合。

容器运行时接口 CRI 让 kubelet 用约定的服务接口请求这些能力。实现可以不同，但接口帮助双方明确各自的职责。containerd 的 CRI 集成和 CRI-O 是两种实现路线；不能把 CRI-O 的内部工具链画成所有运行时都必须采用的固定调用链。

## 2. CRI、OCI、CNI 和 CSI 不在同一层

| 名称 | 主要关注点                                      | 不应怎样理解                                 |
| ---- | ----------------------------------------------- | -------------------------------------------- |
| CRI  | kubelet 与运行时之间的容器、sandbox、镜像等接口 | 不是一种镜像格式，也不是容器进程本身         |
| OCI  | 镜像、运行时等相关规范                          | 不等于一个直接供 kubelet 使用的完整 CRI 实现 |
| CNI  | 网络配置与插件调用的约定                        | 不是所有数据包都经过的代理服务               |
| CSI  | 存储能力与插件集成接口                          | 不是 CRI 的另一种名字                        |

![kubelet、containerd、OCI 与 CNI 的接口分工](/assets/notes/kubernetes/k8s-runtime-interfaces.svg)

这张图以 containerd 的常见 Linux 集成为例。containerd 的 CRI 插件接收 kubelet 请求，借助运行时内部机制管理镜像、容器与 Pod 网络；这部分关系可参照 [containerd 1.7 分支的 CRI 架构说明](https://raw.githubusercontent.com/containerd/containerd/release/1.7/docs/cri/architecture.md)。

图没有承诺所有运行时都使用相同的 shim、OCI 实现和网络时序。runc 是常见的 OCI 运行时实现，但不能把“用了 runc”当作“已经给 kubelet 提供 CRI”。

## 3. Pod sandbox 与业务容器

Pod 是 Kubernetes 的资源抽象，运行时需要相应的 Pod 级运行环境。在典型 Linux 实现里，sandbox 与共享命名空间等基础条件相关，业务容器则运行应用进程。

这能解释两类不同的失败：

- `FailedCreatePodSandBox` 一类事件提示 sandbox 准备阶段出现问题，可能涉及网络或运行时，不应直接归因于应用代码。
- 镜像拉取或应用进程启动失败，要沿对应的镜像、权限、入口命令及依赖继续查，不能因为“有 sandbox”就认为应用应该正常。

同一普通 Pod 内的容器共享网络环境，因此能通过 localhost 互相访问，也可能因监听同一地址和端口而冲突。它们不是共享所有文件系统内容；要共享应用文件仍需相应的卷等机制。普通容器通常共享主机内核，也不是给每个容器安装了一套独立内核。

## 4. 镜像、容器记录和 Task 分别是什么

初学时最容易把“存在一条记录”理解成“已经有进程在运行”。

![containerd 的镜像、容器元数据和 Task 对象关系](/assets/notes/kubernetes/k8s-containerd-objects.svg)

可以按三个层级观察：

1. 镜像引用与内容：名字指向镜像清单或索引，内容层需要完整且与目标平台匹配。
2. 容器记录：保存运行配置、镜像关联和快照等元数据。创建记录并不自动等于进程正在运行。
3. Task：对应执行侧的运行实体。看进程是否在运行，需要结合任务状态，而非只看容器列表。

这也解释了原命令笔记中为何同时出现 `containers` 和 `tasks`：两者并不是重复命令。直接从低层删除 Kubernetes 管理的对象，可能使运行时与 kubelet 对状态的理解不再一致。

## 5. 两种 namespace，不要互相替代

Kubernetes Namespace 是 API 资源组织与权限等机制的一部分。containerd namespace 则用于 containerd API 中的元数据隔离。二者不是一对一映射。

在常见 containerd CRI 场景里，Kubernetes 相关对象位于 `k8s.io` 这个 containerd namespace 下。因此在默认 namespace 看不到对象，不等于镜像或容器不存在；把 `ctr -n` 后面的值换成 Pod 所在的 Kubernetes 命名空间，也不是通用解法。

另一个重要限制是：containerd namespace 本身不是安全边界。官方说明还区分了按 namespace 分开的元数据与可共享的内容寻址数据，不能用各 namespace 列表中的镜像大小简单相加来估计磁盘实际占用。[containerd 1.7 namespace 说明](https://raw.githubusercontent.com/containerd/containerd/release/1.7/docs/namespaces.md)

## 6. 选工具前，先选观察层级

| 工具                | 观察或操作的主要层级      | 本章建议的理解                                     |
| ------------------- | ------------------------- | -------------------------------------------------- |
| kubectl             | Kubernetes API 对象       | 看 Pod、事件、控制器与期望状态                     |
| crictl              | CRI 接口                  | 看 kubelet 使用的 CRI 运行时视角                   |
| ctr                 | containerd 原生接口       | 低层排查工具，不能当作 Kubernetes 管理器           |
| nerdctl             | containerd 的较高层客户端 | 不是所有机器都安装；命令体验相近不等于对象语义相同 |
| BuildKit / buildctl | 镜像构建                  | 构建与运行是不同任务，不是 kubelet 必备命令        |

以下为新增的只读查询模板，未在本机执行。需要已有工具、正确端点和相应权限；不要为跑这些命令临时放宽运行时 socket 权限。

```bash
# CRI 视角；前提是已配置正确的运行时端点
crictl ps -a
crictl images

# containerd 视角；先观察 namespace，再检查常见的 k8s.io
ctr namespaces list
ctr -n k8s.io images list
ctr -n k8s.io containers list
ctr -n k8s.io tasks list
```

`crictl ps -a` 和 `images` 的历史用法可对照 [cri-tools v1.28.0 文档](https://github.com/kubernetes-sigs/cri-tools/blob/v1.28.0/docs/crictl.md)；`ctr` 子命令应再与实际安装版本的帮助核对，本章未做二进制兼容测试。

不能仅凭“ctr 看到了镜像”，就认定“该 Pod 一定能使用它”。还需核对端点、namespace、镜像引用与平台、CRI 视角，以及拉取策略等条件。

## 7. 原镜像命令中，需要纠正的几个概念

### 7.1 所有平台，不是所有版本

`--all-platforms` 处理的是一个镜像引用相关的多个平台内容，例如不同 CPU 架构；它不是下载某仓库全部标签，也不是下载该软件所有版本。它更不是所有 push 失败的通用修复开关。[containerd v1.7.0 镜像拉取参数](https://raw.githubusercontent.com/containerd/containerd/v1.7.0/cmd/ctr/commands/images/pull.go)

这里引用当前源码仅核对参数的概念含义，不把当前完整参数列表当成 1.7 的兼容承诺。实际离线流程应固定工具版本和目标平台，再核对所需内容是否齐全。

### 7.2 导入成功，不等于可以运行

一个归档中有哪些清单和内容层，决定了它能支持哪些平台；目标主机还需要满足内核、运行时和应用要求。“镜像只能在与导出机器完全相同的平台导入”过于绝对；反过来，“导入没报错就能跨架构运行”也不成立。

离线交接至少记录镜像完整引用、digest、目标操作系统与架构、归档校验值和工具版本。文件名应与实际内容一致，不能把示例中的不同版本号混用。多平台归档要求见 [containerd v1.7.0 export 实现](https://raw.githubusercontent.com/containerd/containerd/v1.7.0/cmd/ctr/commands/images/export.go)，此处不提供未经实际版本验证的批量导入脚本。

### 7.3 TLS 错误，不应默认跳过校验

仓库连接失败可能来自证书链、域名、代理、认证或网络。跳过证书校验和使用明文 HTTP 都会改变安全条件，不能放进通用的“正常拉取”步骤。

本章示例不带真实仓库、用户名或密码，也不建议把密码直接写入命令行。实际环境应采用受控的凭据配置，区分运行时仓库配置与某个 CLI 的连接参数，不能假定两者总是自动共享。

## 8. 哪些操作留到独立维护流程

原笔记还涉及 task 终止、容器删除、镜像删除、挂载与卸载。这些都有改变现场的风险，不作为本章排查的第一步。Linux 常见卸载文件系统命令是 `umount`，不是 `unmount`；但即使命令拼写正确，也不代表可以卸载运行时正在使用的路径。

尤其不应通过“删除 Kubernetes 管理的容器”来常规修复资源配置。kubelet 可能再次创建对象，原故障未得到解决，证据反而丢失。应先在 Kubernetes 层核对期望与事件，再决定是否需要受控的节点维护。

## 9. 本章小结

CRI 定义 kubelet 的接口，运行时负责具体实现；OCI、CNI、CSI 分别处理不同层面的约定。工具输出必须放回它所属的 API、namespace 和对象类型解释。下一章沿网络这条分支，专门说明 Pod 怎样获得网络连接，以及“拿到 IP”为什么还不是网络验收完成。

[返回本册目录](/collections/kubernetes/) · [下一章：CNI 与 Pod 网络](/articles/kubernetes-cni-network.html)
