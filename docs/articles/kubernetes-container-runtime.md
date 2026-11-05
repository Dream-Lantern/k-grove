---
id: kubernetes-container-runtime
title: 第八章 容器运行时与 containerd 工具边界
description: "启动一个容器，不只是运行一个镜像名字。还涉及获取镜像内容、准备根文件系统、设置隔离和资源约束、创建进程，以及记录退出结果。"
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
order: 8
---

# 第八章 容器运行时与 containerd 工具边界

> 本章以 Kubernetes 1.28 与 containerd 1.7 系列的接口关系为主要背景。containerd 2.x 配置需要按对应版本单独使用，两代配置的区别见安装实践章节。

## 1. kubelet 与运行时的接口分工 {#_1-kubelet-为什么不直接管理所有-linux-细节}

启动一个容器，不只是运行一个镜像名字。还涉及获取镜像内容、准备根文件系统、设置隔离和资源约束、创建进程，以及记录退出结果。把所有实现都写进 kubelet，会使 Kubernetes 与具体运行时紧密耦合。

CRI（Container Runtime Interface，容器运行时接口）让 kubelet 用约定的服务接口请求这些能力。实现可以不同，但接口帮助双方明确各自的职责。containerd 的 CRI 集成和 CRI-O 是两种实现路线；不能把 CRI-O 的内部工具链画成所有运行时都必须采用的固定调用链。

## 2. CRI、OCI、CNI 和 CSI 不在同一层

OCI（Open Container Initiative，开放容器倡议）制定镜像与运行时等规范；CNI（Container Network Interface，容器网络接口）约定容器网络配置与插件调用；CSI（Container Storage Interface，容器存储接口）让编排系统对接卷的创建、挂载等存储能力。它们解决不同问题，CSI 也不是 CRI 内部的存储子接口。

| 名称 | 主要关注点                                      | 不应怎样理解                                 |
| ---- | ----------------------------------------------- | -------------------------------------------- |
| CRI  | kubelet 与运行时之间的容器、sandbox、镜像等接口 | 不是一种镜像格式，也不是容器进程本身         |
| OCI  | 镜像、运行时等相关规范                          | 不等于一个直接供 kubelet 使用的完整 CRI 实现 |
| CNI  | 网络配置与插件调用的约定                        | 不是所有数据包都经过的代理服务               |
| CSI  | 存储能力与插件集成接口                          | 不是 CRI 的另一种名字                        |

[![运行时接口：CRI、OCI、CNI 的分工](/assets/notes/kubernetes/k8s-runtime-interfaces.svg)](/assets/notes/kubernetes/k8s-runtime-interfaces.svg)

这张图以 containerd 的常见 Linux 集成为例。containerd 的 CRI 插件接收 kubelet 请求，借助运行时内部机制管理镜像、容器与 Pod 网络；这部分关系可参照 [containerd 1.7 分支的 CRI 架构说明](https://raw.githubusercontent.com/containerd/containerd/release/1.7/docs/cri/architecture.md)。

图没有承诺所有运行时都使用相同的 shim、OCI 实现和网络时序。runc 是常见的 OCI 运行时实现，但不能把“用了 runc”当作“已经给 kubelet 提供 CRI”。

### 2.1 containerd 1.7 的典型 Linux 实现

[![containerd 1.7：CRI 接口、执行链路与网络配置](/assets/notes/kubernetes/k8s-containerd-execution.svg)](/assets/notes/kubernetes/k8s-containerd-execution.svg)

以常见 runc v2 运行时为例，可沿以下职责关系理解一次容器操作：

1. kubelet 通过 CRI 的 RuntimeService、ImageService 请求 Sandbox、容器生命周期和镜像能力，不自行实现所有 Linux 细节。
2. containerd 内的 CRI 插件接收请求，调用 containerd 的镜像、内容、元数据、快照和任务管理能力；网络准备时可通过 CNI 集成配置 Pod 网络。
3. 执行侧由 `containerd-shim-runc-v2` 等 shim（垫片进程）承接任务请求，组织容器 I/O、退出等待和事件等生命周期工作。它让容器执行侧不必与 containerd 主守护进程同生共死，但不代表任意故障下容器都不受影响。
4. shim 使用 runc 这类 OCI Runtime（OCI 运行时实现）按运行配置创建、启动或管理 Linux 容器进程。runc 不是必须一直驻留的完整 CRI 服务，shim 也不是容器内的业务进程。

containerd 与 shim 使用其任务服务通信机制，常见为 ttrpc；OCI 定义执行配置和运行时行为等规范，不能把这段内部通信简单标为“OCI 协议”。网络分支中的 CNI 调用发生在配置阶段，业务包之后走已建立的数据路径；存储接入另有 kubelet/CSI 等机制。

图示是 containerd 1.7 的典型实现关系，省略返回、事件和重试，不保证每条箭头都是严格同步调用，也不要求 CRI-O 具有相同结构。[containerd v1.7.0 CRI 架构](https://github.com/containerd/containerd/blob/v1.7.0/docs/cri/architecture.md)、[v1.7.0 Runtime v2 与 shim 接口](https://github.com/containerd/containerd/blob/v1.7.0/runtime/v2/README.md)

## 3. Pod sandbox 与业务容器

Pod 是 Kubernetes 的资源抽象，运行时需要相应的 Pod 级运行环境。在典型 Linux 实现里，sandbox 与共享命名空间等基础条件相关，业务容器则运行应用进程。

这能解释两类不同的失败：

- `FailedCreatePodSandBox` 一类事件提示 sandbox 准备阶段出现问题，可能涉及网络或运行时，不应直接归因于应用代码。
- 镜像拉取或应用进程启动失败，要沿对应的镜像、权限、入口命令及依赖继续查，不能因为“有 sandbox”就认为应用应该正常。

同一普通 Pod 内的容器共享网络环境，因此能通过 localhost 互相访问，也可能因监听同一地址和端口而冲突。它们不是共享所有文件系统内容；要共享应用文件仍需相应的卷等机制。普通容器通常共享主机内核，也不是给每个容器安装了一套独立内核。

## 4. 镜像、容器记录和 Task 分别是什么

初学时最容易把“存在一条记录”理解成“已经有进程在运行”。

[![containerd：镜像、容器记录与任务不是同一个对象](/assets/notes/kubernetes/k8s-containerd-objects.png)](/assets/notes/kubernetes/k8s-containerd-objects.png)

可以按三个层级观察：

1. 镜像引用与内容：名字指向镜像清单或索引，内容层需要完整且与目标平台匹配。
2. 容器记录：保存运行配置、镜像关联和快照等元数据。创建记录并不自动等于进程正在运行。
3. Task：对应执行侧的运行实体。看进程是否在运行，需要结合任务状态，而非只看容器列表。

这也解释了原命令笔记中为何同时出现 `containers` 和 `tasks`：两者并不是重复命令。直接从低层删除 Kubernetes 管理的对象，可能使运行时与 kubelet 对状态的理解不再一致。

以 `web-demo` 中的 `web` 容器为例：节点可能已经有 `nginx:1.28.0` 的 Image（镜像引用和内容），但这个 Pod 还没有对应的 Container（容器配置与元数据记录）；之后记录已创建，Task（执行任务）也可能尚未启动或已经退出。Sandbox 与业务容器还会形成不同的运行时对象，不能把一条 Sandbox 记录当成 Web 进程已经运行。

因此要把 Pod UID、Sandbox ID、容器名称/ID、所在节点和时间对应起来，结合 Task 状态判断执行情况；不是简单比较三个工具的列表行数或假定 ID 格式完全相同。

## 5. Kubernetes 与 containerd 的 namespace {#_5-两种-namespace-不要互相替代}

Kubernetes Namespace 是 API 资源组织与权限等机制的一部分。containerd namespace 则用于 containerd API 中的元数据隔离。二者不是一对一映射。

在常见 containerd CRI 场景里，Kubernetes 相关对象位于 `k8s.io` 这个 containerd namespace 下。因此在默认 namespace 看不到对象，不等于镜像或容器不存在；把 `ctr -n` 后面的值换成 Pod 所在的 Kubernetes 命名空间，也不是通用解法。

例如 Kubernetes `default` 命名空间中的一个 Pod，其运行时元数据仍可在 containerd 的 `k8s.io` 下；第一章 `k8s-arch-demo` 中的 Pod 也通常使用同一个 containerd namespace。

| 类型                 | 示例                       | 作用                                                                |
| -------------------- | -------------------------- | ------------------------------------------------------------------- |
| Kubernetes Namespace | `default`、`k8s-arch-demo` | API 资源组织与命名空间作用域的权限等边界，不自动提供完整网络隔离    |
| containerd Namespace | `k8s.io`                   | containerd API 元数据的管理隔离，不是 Kubernetes 命名空间的一一映射 |

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

`kubectl` 通过正确的集群上下文访问 API；`crictl` 和 `ctr` 则应在 **Pod 所在节点** 检查本机运行时。先核对 kubelet 的 CRI 端点并为 crictl 配置 `runtime-endpoint`、`image-endpoint`，也为 ctr 选择同一个 containerd 实例的地址。常见 socket 路径不代表所有安装的实际路径，权限不足时应使用已授权的节点管理方式。

```bash
# Kubernetes API 视角
kubectl get pods -A -o wide

# CRI 视角；前提是已配置正确的运行时端点
crictl pods
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

### 6.1 案例：Pod 创建成功，但 Web 容器没有正常运行

先在 API 视角查看 `web-demo` 的实际 Pod：`kubectl describe pod POD_NAME -n k8s-arch-demo`。`POD_NAME` 必须替换为实际名称；这些命令和下表均是教学排查方案，未在本次修订中运行。

| 要确认的阶段                 | 证据与下一步                                                                                                                                     |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| 是否已指定节点               | 查 `spec.nodeName`、PodScheduled 和 Events；尚未绑定时先检查调度约束                                                                             |
| kubelet 是否开始处理         | 在目标节点关联 Pod UID 的 kubelet 日志及 API Events；没有事件也可能是事件过期，不能直接推断从未观察到                                            |
| Sandbox 是否准备成功         | 用 `crictl pods`、`crictl inspectp SANDBOX_ID` 对应 Pod 元数据，结合 `FailedCreatePodSandBox` 和 kubelet/运行时日志检查网络或其他准备条件        |
| 镜像是否可用                 | `crictl images` 与拉取事件；`ErrImagePull`、`ImagePullBackOff` 指向引用、平台、仓库、凭据和策略等检查方向                                        |
| 业务容器是否创建             | `crictl ps -a`、`crictl inspect CONTAINER_ID`；`CreateContainerError` 等线索要回到具体运行配置、挂载和运行时错误                                 |
| 执行任务是否存在、运行或退出 | containerd 原生 `containers list`、`tasks list` 和任务/退出事件；`RunContainerError` 等可提供启动阶段线索，Task 已清理时不能仅凭当前列表还原历史 |
| 是否是应用运行后退出         | `CrashLoopBackOff` 要关联上一次退出、日志、探针和资源证据，见第七章；它不是所有运行时准备失败的统一名称                                          |

`SANDBOX_ID`、`CONTAINER_ID` 分别从实际 CRI 输出取得；不能拿 Pod 名称直接代替。原生 Task ID 与 Container ID 的对应关系也要按该运行时核对。错误原因文字会随版本、实现和失败阶段变化，表格是观察方向，不是症状到根因的一一映射。先形成 API → kubelet → CRI → containerd 的证据链，再决定是否需要受控维护。

## 7. 镜像平台、离线归档与仓库连接 {#_7-原镜像命令中-需要纠正的几个概念}

先分清镜像引用与内容结构：

| 术语                       | 含义                                                                                         |
| -------------------------- | -------------------------------------------------------------------------------------------- |
| Image Tag（镜像标签）      | 名称中的可变指针，例如 `nginx:1.28.0`；相同标签不保证内容永远不变                            |
| Image Digest（镜像摘要）   | 对某个内容对象计算的摘要，常用于固定所引用的清单或索引                                       |
| Image Manifest（镜像清单） | 描述镜像配置与内容层引用；运行时还要核对目标平台                                             |
| Image Index（镜像索引）    | 引用多个清单，常用于按平台选择，如 `linux/amd64` 与 `linux/arm64`                            |
| 内容层与离线归档           | 层是构成文件系统的内容；归档是携带清单、配置、层等的交接文件，不等于所有平台所需内容必然齐全 |

结构定义可对照 [OCI Image Specification v1.0.2](https://github.com/opencontainers/image-spec/tree/v1.0.2)。不要仅凭文件后缀、标签或体积判断平台与完整性。

### 7.1 所有平台，不是所有版本

`--all-platforms` 处理的是一个镜像引用相关的多个平台内容，例如不同 CPU 架构；它不是下载某仓库全部标签，也不是下载该软件所有版本。它更不是所有 push 失败的通用修复开关。[containerd v1.7.0 镜像拉取参数](https://raw.githubusercontent.com/containerd/containerd/v1.7.0/cmd/ctr/commands/images/pull.go)

这里引用 v1.7.0 源码核对参数含义，其他版本的完整参数列表仍需查阅对应帮助。实际离线流程应固定工具版本和目标平台，再核对所需内容是否齐全。

### 7.2 导入成功，不等于可以运行

一个归档中有哪些清单和内容层，决定了它能支持哪些平台；目标主机还需要满足内核、运行时和应用要求。“镜像只能在与导出机器完全相同的平台导入”过于绝对；反过来，“导入没报错就能跨架构运行”也不成立。

离线交接至少记录镜像完整引用、digest、目标操作系统与架构、归档校验值和工具版本。文件名应与实际内容一致，不能把示例中的不同版本号混用。多平台归档要求见 [containerd v1.7.0 export 实现](https://raw.githubusercontent.com/containerd/containerd/v1.7.0/cmd/ctr/commands/images/export.go)，此处不提供未经实际版本验证的批量导入脚本。

在目标节点可先做只读检查，端点和权限前提同第 6 节：

```bash
ctr version
ctr -n k8s.io images list
ctr -n k8s.io images check
crictl images
```

`images list` 的 `REF`、`TYPE`、`DIGEST`、`PLATFORMS` 帮助核对镜像引用、清单类型、目标摘要与平台；`images check` 检查当前默认平台相关内容及所选 snapshotter 的解包状态，不是全部平台运行验收，也不承诺每种不完整状态都会通过非零退出码报告。还要与 CRI 可见引用、Pod 使用的镜像名及拉取策略对应。[containerd v1.7.0 镜像查询与检查实现](https://github.com/containerd/containerd/blob/v1.7.0/cmd/ctr/commands/images/images.go)

### 7.3 TLS 错误，不应默认跳过校验

仓库连接失败可能来自证书链、域名、代理、认证或网络。跳过证书校验和使用明文 HTTP 都会改变安全条件，不能放进通用的“正常拉取”步骤。

本章示例不带真实仓库、用户名或密码，也不建议把密码直接写入命令行。实际环境应采用受控的凭据配置，区分运行时仓库配置与某个 CLI 的连接参数，不能假定两者总是自动共享。

## 8. 哪些操作留到独立维护流程

task 终止、容器删除、镜像删除、挂载与卸载会改变运行现场，应放入独立维护流程，在完成状态观察后按需要执行。Linux 常见卸载文件系统命令是 `umount`，不是 `unmount`；但即使命令拼写正确，也不代表可以卸载运行时正在使用的路径。

尤其不应通过“删除 Kubernetes 管理的容器”来常规修复资源配置。kubelet 可能再次创建对象，原故障未得到解决，证据反而丢失。应先在 Kubernetes 层核对期望与事件，再决定是否需要受控的节点维护。

## 9. 本章小结

CRI 定义 kubelet 的接口，运行时负责具体实现；OCI、CNI、CSI 分别处理不同层面的约定。工具输出必须放回它所属的 API、namespace 和对象类型解释。下一章沿网络这条分支，专门说明 Pod 怎样获得网络连接，以及“拿到 IP”为什么还不是网络验收完成。

[返回本册目录](/collections/kubernetes/) · [下一章：CNI 与 Pod 网络](/articles/kubernetes-cni-network.html)
