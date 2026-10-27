---
id: kubernetes-kubeadm-review
title: 第二章：kubeadm 单节点安装实践复盘（Kubernetes 1.28）
description: 第一章解释了各组件的作用，本章则按依赖关系重新组织安装记录：先准备主机和运行时，再建立控制平面，最后配置 Pod 网络和日常管理入口。
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
order: 2
---

# 第二章：kubeadm 单节点安装实践复盘（Kubernetes 1.28）

第一章解释了各组件的作用，本章则按依赖关系重新组织安装记录：先准备主机和运行时，再建立控制平面，最后配置 Pod 网络和日常管理入口。

本章是对原有 Kubernetes 1.28 实践的整理，不是新版本安装推荐，也不是已重新执行并验收的安装教程。**没有在你的电脑或任何远程主机上安装、升级、重启服务或操作集群。** 下列命令和配置均为笔记内容，保留历史背景；不能把它们拼成面向未知主机的一键脚本。

## 1. 先固定复盘范围，而不是先复制命令

原记录使用 `apt` 包管理命令，并指定 `kubeadm/kubelet/kubectl=1.28.0-00`，初始化版本为 `v1.28.0`。可以据此确认记录采用 Debian 系命令风格，但没有足够信息证明具体是哪个 Ubuntu/Debian 发行版，也没有完整记录内核与首次安装时的 containerd 版本。

| 项目       | 原记录能够确认的内容                    | 仍不能直接下结论的部分           |
| ---------- | --------------------------------------- | -------------------------------- |
| Kubernetes | 初始化指定 v1.28.0                      | 当时实际安装结果、后续是否升级   |
| 操作系统   | 使用 apt 与 systemd 相关命令            | 发行版、版本、内核               |
| containerd | 作为容器运行时；后来有 2.2 配置补记     | 初装版本、配置是否来自同一实验   |
| Pod 网络   | 记录了 Calico v3.26.1 与自定义 Pod CIDR | 与实际环境的兼容及成功测试       |
| GPU        | 出现 NVIDIA 工具链配置                  | 是否属于基础实验、硬件与驱动版本 |

不能为了补齐环境表格，就假定使用了“Ubuntu 22.04”或某个 containerd 小版本。缺失的复盘材料应如实标记，不能补写成看似完整的成功案例。

尤其要区分：**“一段 containerd 2.2 的配置能在该版本文档中找到”与“这套配置就是原来 1.28 集群使用的配置”不是一回事。** 前者可以核对文档，后者还需要当时的环境证据。

## 2. 安装顺序为什么不能随便颠倒？

[![Kubernetes 1.28：安装记录的依赖顺序](/assets/notes/kubernetes/k8s-128-install-order.png)](/assets/notes/kubernetes/k8s-128-install-order.png)

图中的箭头表示主要依赖，不表示每个命令都必须严格串行，也不表示某一步通过就保证整个应用可用。

先记住几个工具的分工：

- `kubeadm`：帮助引导集群，不是长期负责运行容器的守护进程。
- `kubelet`：节点上的代理，负责协调本节点 Pod 的运行。
- `kubectl`：调用 Kubernetes API 的客户端；安装客户端不等于集群已经存在。
- `containerd`：提供容器与镜像相关能力；进程启动不等于 CRI 和镜像配置已正确。
- CNI 网络实现：使 Pod 网络具备所需能力，不是 kubeadm 安装完成后自然就有。

安装流程及前置条件以 [Kubernetes release-1.28 的 kubeadm 文档](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/setup/production-environment/tools/kubeadm/create-cluster-kubeadm.md)为历史核对依据，不用当前默认值反推当年的实际环境。

## 3. 主机准备：每一处配置都应该知道在解决什么问题

### 3.1 先看环境，再决定改什么

下面是一组环境清点命令示意，没有在本次整理过程中执行：

```bash
cat /etc/os-release
uname -r
swapon --show
containerd --version
kubeadm version -o short
kubelet --version
kubectl version --client
```

这些输出回答的是不同问题：系统发行版、内核、swap 使用情况、运行时及工具版本，不能用其中一条替代全部检查。

原记录中的 `kubelet version` 已在整理时纠正为 `kubelet --version`。这是命令形式的修订，不是报告它已经在某台机器运行成功。

### 3.2 swap：区分临时关闭与持久配置

原记录采用关闭 swap 的路径。`swapoff -a` 影响当前运行环境；要在重启后继续保持相应状态，还涉及系统的持久配置。不能把一次命令成功理解成重启后仍然满足条件。

原笔记通过 `sed` 改写 `/etc/fstab`。这属于会影响主机启动和挂载行为的修改，应先保留文件原件并确认目标 swap 条目，不适合写成面向所有系统的通用替换指令。本章保留这一操作目的，不提供自动改写未知主机配置的脚本。

这也不应扩写成“所有 Kubernetes 版本都永远不能使用 swap”。这里复盘的是 1.28 记录采用的配置路线；其他行为需要独立核对版本、特性和 kubelet 设置。[1.28 安装前置条件](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/setup/production-environment/tools/kubeadm/install-kubeadm.md)

### 3.3 内核模块和转发参数

原记录提到 `overlay`、`br_netfilter` 以及 IP 转发和桥接过滤参数。它们分别关联文件系统/运行时及网络数据路径，不应把它们统称为“让 Kubernetes 可以联网的一条万能配置”。

原文的模块列表 heredoc 起止写在同一行。文件内容本应清楚地分行：

```text
# /etc/modules-load.d/k8s.conf 的内容示意
overlay
br_netfilter
```

对应的内核参数片段在原记录中是：

```ini
net.bridge.bridge-nf-call-iptables = 1
net.bridge.bridge-nf-call-ip6tables = 1
net.ipv4.ip_forward = 1
```

文件存在、模块已加载、参数已生效，是三件不同的事。实际需要哪些参数还与所选网络实现有关；上面是历史材料的整理，不是对任意 CNI 的强制要求。[1.28 容器运行时与网络准备](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/setup/production-environment/container-runtimes.md)

## 4. containerd：服务、CRI、cgroup 和镜像要分别检查

### 4.1 为什么“containerd active”还不够？

服务处于运行状态，只能说明当前服务管理器未观察到进程退出。要确认 kubelet 能否访问 CRI、运行时插件是否可用、镜像能否获取，以及 sandbox 能否创建，还需分别检查。

复盘时应依次核对版本、实际加载的配置、CRI 插件、socket 路径及日志，而不是一看到 Pod 创建失败就反复重启 containerd。

### 4.2 cgroup 驱动要与 kubelet 配合

原记录在 runc 相关配置中设置 `SystemdCgroup = true`。它不是一个随意放在 TOML 文件顶层就能生效的全局开关。

下面只对比配置位置，不能混合粘贴为同一个文件：

```toml
# containerd 1.x 文档中的相关配置位置示意
[plugins."io.containerd.grpc.v1.cri".containerd.runtimes.runc.options]
  SystemdCgroup = true
```

```toml
# containerd 2.x 文档中的相关配置位置示意
# 这是后续版本旁注，不代表已验证为原 1.28 环境
[plugins."io.containerd.cri.v1.runtime".containerd.runtimes.runc.options]
  SystemdCgroup = true
```

配置格式版本、插件 ID 和运行时处理器都需要与实际二进制对应。不能仅用一次字符串替换，就断言 kubelet 和运行时已经正确配合。[1.28 对应说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/setup/production-environment/container-runtimes.md)、[containerd 2.2 配置说明](https://github.com/containerd/containerd/blob/v2.2.0/docs/cri/config.md)

### 4.3 sandbox 镜像与业务镜像是两类检查

原记录出现了创建 Pod sandbox 时拉取镜像失败的排查过程。sandbox 镜像不是应用自己的镜像；能够获取一个 Web 镜像，不能证明 sandbox 镜像也能成功获取。

同样，原记录里的某个 `pause` 标签不能被写成所有 Kubernetes/运行时组合的固定答案。要核对实际运行时配置、镜像仓库地址和相关版本要求。

### 4.4 镜像源与 containerd namespace

原文后来补记了 `certs.d/<registry>/hosts.toml` 的配置方式。仓库域名、镜像标签与摘要都具有具体含义，不能简单把 `quay.io` 全文替换成另一个域名，就认为获得了等价可信的镜像。

原记录还使用 `ctr -n k8s.io ...` 导入离线镜像。这里的 `k8s.io` 是 containerd 的 namespace，**不是 Kubernetes 的 Namespace 资源**。镜像是否出现在 CRI 可见范围、清单引用的名称是否一致、架构是否匹配，都需要进一步确认。

第三方代理和镜像站只是传输与分发选择，不是官方来源、镜像完整性或长期可用性的保证。历史地址可以保留在私有原文，不应包装成新的默认信任链。

## 5. 引导控制平面：保存好配置，也分清成功的含义

### 5.1 安装包来源属于历史环境的一部分

`1.28.0-00` 与旧仓库地址共同构成当时的记录。今天是否还能获取完全相同的包，取决于实际仓库；不能把旧包名直接拼到另一套新仓库命令里。

因此本章不增加新的软件源，也不提供升级到当前版本的命令。复盘重点是解释 kubeadm、kubelet 和 kubectl 的版本需要相互核对，而不是把其中某个工具更新到“最新”。

### 5.2 初始化参数分别决定什么？

以下是脱敏后的命令结构，仅用于阅读：

```text
kubeadm init
  --kubernetes-version=v1.28.0
  --apiserver-advertise-address=<CONTROL_PLANE_IP>
  --pod-network-cidr=<POD_CIDR>
  --image-repository=<IMAGE_REPOSITORY>
```

这是带占位符的结构示意，不是可以逐行执行的 shell 脚本。参数主要涉及控制平面的通告地址、预期 Pod 网段、组件镜像来源及目标版本。修改它们会影响后续节点访问、网络插件配置和镜像获取，不能只为绕过一条报错临时填写任意值。

初始化还会创建证书、kubeconfig 和相关控制平面配置。应保留必要的恢复材料，但不能把管理凭证上传到博客或发给所有节点。高可用和工作节点加入不是“把全部私钥复制过去”的同义词。

### 5.3 配置 kubectl，不等于创建第二套集群

将管理用 kubeconfig 放到客户端选定的位置，是让客户端知道 API 地址和认证信息。它不是在安装新的 API Server。

默认管理员配置具有较高权限，只适合对应的受控管理场景。后续权限章节会单独说明普通用户和 ServiceAccount，不把“复制 admin.conf”当作所有人的通用授权方法。

## 6. CNI 与单节点调度：为什么控制平面起来了还不能算完成？

原记录在初始化后观察到节点 NotReady、CoreDNS 尚未正常运行，并继续安装 Calico。这个先后顺序很有教学价值，但不能反过来推导“所有 NotReady 都是没装 CNI”或“所有 CoreDNS Pending 都只有一个原因”。

应结合节点条件、Pod 事件、插件日志及运行时错误判断。Pod CIDR 配置是否一致是其中一项检查，不是全部网络验收。

原记录的 Calico 版本保留为 `v3.26.1`。目前没有当年的完整安装输出与兼容性验收记录，不能把这一组合写成已复现成功。也不能同时下载两套不同清单，修改不同文件后却假定应用的是同一配置。

单节点实验如果允许业务 Pod 与控制平面共用节点，需要明确处理调度隔离。解除某个污点会改变允许调度的范围，但“单节点必须删除所有污点”并不成立；专门的容忍配置或其他部署安排也属于需要说明的选择。

本章不会执行原文中的 `kubectl taint nodes --all ...`，也不提供对未知集群一键解除隔离的指令。

## 7. 验收应分层，不要只截一张 Ready

| 层次           | 要确认什么                             | 不能据此证明什么         |
| -------------- | -------------------------------------- | ------------------------ |
| 主机与运行时   | 服务、CRI、cgroup 与基础网络准备       | 业务应用已经正常         |
| API 与控制平面 | 能完成相应 API 访问；组件无关键错误    | 任意用户都有正确权限     |
| 节点           | Node 条件与实际资源状态                | 所有 Pod 都能调度        |
| 系统 Pod       | 网络、DNS 等相应组件的状态             | 所有域名和外部访问均正常 |
| 业务路径       | 应用就绪、DNS、Service、存储等实际测试 | 生产高可用与数据恢复能力 |

原笔记中的观察命令可按下面的方式归类；本次没有运行这些命令：

```bash
kubectl get nodes -o wide
kubectl get pods -A
kubectl get events -A --sort-by=.metadata.creationTimestamp
journalctl -u kubelet --no-pager -n 100
```

日志包含凭证、地址或工作负载信息时，应先脱敏。遇到错误后，先定位它发生的层次，再决定修改哪项配置，不要同时调整所有组件。

## 8. GPU、Helm 与 Minikube 为什么不混进基础安装主线？

NVIDIA Container Toolkit 属于有相应硬件需求时的扩展，涉及驱动、运行时和设备管理；它不是普通 CPU 学习集群的前置条件。原文中的 GPU 配置留待设备专题复盘。

Helm 是管理应用模板和 Release 的工具，不是 kubeadm 引导控制平面的必要步骤。原记录的“下载脚本后直接执行”需要另行说明来源和审查边界，本章没有执行或推荐盲目照抄。

Minikube 是另一条本地学习路径，不必与这套 kubeadm 命令混用。它的驱动、节点数和特性门控要按自身版本核对；不能沿用“永远只支持一个虚拟机节点”的定义。

## 9. 本章结论与待补材料

这份记录已经整理成可阅读的历史实践复盘，但还没有被重新实验验收。已确认的修订包括 heredoc 排版、版本查看命令，以及 containerd 1.x/2.x 配置的分离；未确认的环境信息没有补造。

后续若要把它变成严格可复现教程，需要补齐当时的发行版、运行时版本、实际配置、安装日志和逐项测试结果。**这不影响继续学习后面的组件章节，也不意味着需要现在安装或操作任何环境。**

[返回本册目录](/collections/kubernetes/)
