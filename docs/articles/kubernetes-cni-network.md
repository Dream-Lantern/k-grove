---
id: kubernetes-cni-network
title: 第九章 CNI 与 Pod 网络
description: "Pod 有一个 IP、Service 有一个地址、应用能通过服务名访问，它们看起来都与网络有关，实际由不同机制共同完成。"
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
order: 9
---

# 第九章 CNI 与 Pod 网络

> 本章以 Kubernetes 1.28 的 Linux 普通 Pod 为背景，沿运行时网络准备、地址管理和通信验证展开。`hostNetwork`、Windows 及特殊实现需单独核对。

## 1. 先把三类网络问题分开

Pod 有一个 IP、Service 有一个地址、应用能通过服务名访问，它们看起来都与网络有关，实际由不同机制共同完成。

| 问题                     | 主要观察范围                         | 不能代替的检查                 |
| ------------------------ | ------------------------------------ | ------------------------------ |
| Pod 怎样获得网络连接？   | 运行时、CNI 集成、网络方案           | 有 IP 不代表跨节点和策略都正确 |
| 一个稳定入口怎样选后端？ | Service、EndpointSlice、服务数据平面 | 后端集合正确不等于应用端口正常 |
| 服务名怎样变成地址？     | Pod DNS 配置、集群 DNS               | 解析成功不代表业务连接成功     |

CNI 的全称是 Container Network Interface，定义网络配置和插件调用约定。它可以用于 Kubernetes 之外的容器场景；选择具体网络方案后，还要确认采用哪种数据路径和地址管理方式。

## 2. CNI 在 Pod 创建过程的什么位置

在常见 containerd CRI 集成中，kubelet 发起运行时请求，运行时的网络集成依据配置调用 CNI 插件，为 Pod 级网络环境配置连接。不要把它简化成“调度器直接给容器分配网卡”。

主要关心四类事情：网络接口如何建立、地址如何分配、路由或转发表如何配置、失败时如何清理。IP 地址管理通常称为 IPAM，它可以通过插件委托等机制完成。CNI 约定调用和结果，不要求所有方案都用同一种 IPAM。

插件配置可以有链式组合。前面的插件建立连接，后面的插件对结果继续调整，具体能力取决于配置和实现。CNI 规范版本也不同；本章采用 [CNI spec 1.0.0](https://raw.githubusercontent.com/containernetworking/cni/spec-v1.0.0/SPEC.md)核对基本的 ADD、DEL、CHECK 与结果传递，不把后来规范的新操作反推成所有 1.28 环境必然支持的能力。

网络准备失败时，业务容器可能尚未进入可运行阶段。与“Pod 没启动”相比，事件中的错误往往更有助于定位故障边界。但出现 CNI 错误，并不一定是插件二进制损坏，也可能涉及地址池耗尽、外部依赖、配置不一致或主机网络问题。

## 3. CNI 接口与网络实现方式 {#_3-为什么-cni-不等于-overlay}

Overlay 常用额外封装，把逻辑的 Pod 网络承载在底层节点网络上。它是一类网络实现路线，不是 CNI 接口的同义词。

另一些方案可以采用原生路由，或与云网络地址和网卡能力集成；同一个网络项目也可能支持多种模式。因此，仅写“使用某某 CNI”还不足以说明实际数据路径，还需记录模式、地址管理、路由、MTU 和策略等条件。

[![Pod 网络：两节点布局与跨节点路径](/assets/notes/kubernetes/k8s-cni-two-nodes.png)](/assets/notes/kubernetes/k8s-cni-two-nodes.png)

图中用双节点布局区分创建期配置与运行期通信：

1. 跨节点网络可采用封装、原生路由或云网络集成，具体路径由所选方案决定。
2. 节点、Pod 和 Service 地址分别规划，图中以角色表示。
3. CNI ADD 在网络准备阶段配置连接，后续业务数据包沿已建立的数据路径传输。

图中省略的 veth、网桥、隧道或云网卡，不代表它们永远不存在；只是不能在一张通用图里把其中一种结构写成规范要求。

## 4. 地址段、IPAM 与可达性

“控制器分配节点 Pod CIDR，再由插件分配 Pod IP”是一种配置路线；其他网络方案可以采用不同的地址管理机制。

一些配置会使用 Node 的 PodCIDR，其他方案可能通过自身 IPAM 或云侧分配机制管理地址。分析环境时应核对实际网络方案，而不是只看初始化命令里出现过一个 `--pod-network-cidr` 就认定所有地址都由它控制。

地址规划至少要区分节点网络、Pod 网络和 Service 地址范围。它们承担的角色不同，冲突可能导致路由歧义；但不能把任意三个看起来不同的网段就直接判定为可用，还要考虑所在网络、VPN、云路由以及其他实际地址。

拿到 Pod IP 只说明地址分配相关步骤有了结果。跨节点通信还需要合适的底层连通、转发路径和回程；策略也可能有意阻断访问。对于采用封装的网络，MTU 不合适可能导致小请求正常、大报文异常。这里列的是定位方向，不是对你的环境已确认的根因。

## 5. 按通信范围组织网络测试 {#_5-同-pod、同节点与跨节点-不是一条测试}

普通 Pod 内共享网络环境的容器通常可以通过 localhost 通信；两个不同 Pod 则不能把对方当成自己的 localhost。

同节点 Pod 之间的连接，不一定经过与跨节点相同的路径。因此“本机 Pod 能互通”只能缩小范围，不能证明跨节点网络正常。反过来，“ping 不通”也不能单独证明 TCP 业务端口不可用：ICMP 可能被限制，应用也可能根本不依赖 ICMP。

新增教学推理例子：假设 Pod A 可以访问同节点的 Pod B，却无法访问另一节点的 Pod C。下一步应对比目的端口、策略、源和目标节点及路由条件，而不是立即更换 CNI。若只有某个目标应用失败，还要回到应用监听与后端状态。

这只是通过对照缩小问题范围的教学例子，并非你的实验结果。

## 6. NetworkPolicy 是另一层契约

NetworkPolicy 用 API 描述适用的网络访问约束，但需要具备相应能力的网络实现执行。创建对象成功，不等于策略已经被所有数据路径执行。

没有适用隔离策略与存在允许规则不是同一种状态。分析策略时还要分别看 ingress 和 egress、源和目标选择器及协议端口。不能用“集群有 CNI”推导出“已经按默认拒绝保护”，也不能把网络策略当成 HTTP 路径级授权。基础边界参见 [Kubernetes 1.28 NetworkPolicy](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/network-policies.md)；权限章节会继续区分 API 权限与网络访问权限。

### 6.1 按什么顺序判断一次连接

对支持策略的普通 Pod 网络，先分别判断源的 egress 与目标的 ingress。某方向没有策略选中并隔离时，该方向默认允许；隔离后，适用策略的允许规则取并集，不按创建先后覆盖。源出口和目标入口都需要允许，请求才可能通过这层限制。DNS、应用监听和其他网络条件仍需正常。

### 6.2 一个列表项的差别就是 AND 与 OR

以下为新增片段，位于策略 spec 的 ingress 中，仅用于比较来源集合，未部署。标签 team=frontend 是 Namespace 标签，role=client 是 Pod 标签：

```yaml
ingress:
  - from:
      - namespaceSelector:
          matchLabels:
            team: frontend
        podSelector:
          matchLabels:
            role: client
```

同一个 peer 中两个选择器同时成立：只允许 team=frontend 命名空间里的 role=client Pod。若改成两个 peer：

```yaml
ingress:
  - from:
      - namespaceSelector:
          matchLabels:
            team: frontend
      - podSelector:
          matchLabels:
            role: client
```

现在是两组来源的并集：team=frontend 命名空间中的全部 Pod，或者策略所在命名空间里的 role=client Pod。第二个 podSelector 单独出现时，不是选择所有命名空间。两个例子没有限制 ports，表示这条规则没有另加端口筛选，不应误读为只开放某个业务端口。

## 7. 不改变现场的观察方式

下面只是授权环境中的命令模板，未执行；名称、命名空间和上下文需要先确认。`kube-system` 只是常见系统组件所在位置，并不是所有网络方案的固定部署目录。

```bash
kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl describe pod POD_NAME -n NAMESPACE
kubectl get networkpolicy -n NAMESPACE
```

相比直接重装，先按以下问题整理一份简短的观察记录更有助于定位：

- 源、目标分别是什么 Pod、节点、地址族和端口？
- 失败发生在创建 sandbox、获得 IP，还是业务连接阶段？
- 同节点和跨节点、Pod 地址和 Service 地址是否表现不同？
- 是否只有某类流量、某个大小范围或某个命名空间失败？
- 最近是否改过插件配置、节点网络或访问策略？

本章不提供清空 iptables、删除 CNI 目录、批量删除网卡的“万能修复”。这些操作会改变现场，也可能破坏已有工作负载。插件、节点与内核参数的修复必须建立在具体证据上。

## 8. 本章小结

CNI 定义如何配置网络连接，实际网络方案决定具体的数据路径与地址管理。建立了 Pod 网络以后，应用仍需要稳定的访问入口；下一章解释 Service 如何与 kube-proxy 配合，以及为什么规则更新路径与业务流量路径必须分开画。

[返回本册目录](/collections/kubernetes/) · [下一章：kube-proxy 与 Service 转发](/articles/kubernetes-kube-proxy.html)
