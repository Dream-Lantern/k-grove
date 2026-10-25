---
id: kubernetes-kube-proxy
title: 第十章 kube-proxy 与 Service 转发
description: 工作负载的 Pod 会替换，Pod 地址也可能变化。客户端若把每个实例的地址写死，就需要随时追踪这些变化。Service 通过逻辑入口与后端集合的配合，让客户端不必把某个临时 Pod 当成永久地址。
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
order: 10
---

# 第十章 kube-proxy 与 Service 转发

> 聚焦 Kubernetes 1.28 的 Linux 节点，解释 Service 的节点侧实现。Service 清单编写和对外暴露将在资源章节继续展开；本章不更换代理模式，也不修改防火墙规则。

## 1. 为什么需要一个不跟着 Pod 改变的入口

工作负载的 Pod 会替换，Pod 地址也可能变化。客户端若把每个实例的地址写死，就需要随时追踪这些变化。Service 通过逻辑入口与后端集合的配合，让客户端不必把某个临时 Pod 当成永久地址。

Service 是 API 对象，并不是一台独立的代理机器。以普通 ClusterIP Service 为例，要实现连接转发，还需要端点信息与节点上的服务数据平面配合。

这里先明确例外：Headless Service 使用 `clusterIP: None`，没有普通 Service 虚拟 IP；ExternalName 提供 DNS 别名语义，也不是为它新建一组普通虚拟 IP 转发规则。原笔记“所有 Service 都分配 ClusterIP”的说法因此需要修正。[Kubernetes 1.28 Service](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/service.md)

## 2. Service、端点与 kube-proxy 各做什么

可以按信息流拆成三层：

- Service 描述入口、端口以及适用的后端选择条件。
- 相关控制器根据对象状态维护端点信息；1.28 学习时应同时认识 EndpointSlice，而不是只停留在旧 Endpoints 对象。
- kube-proxy 观察 Service 与端点相关变化，在本节点协调所需的转发机制。

kube-proxy 不负责创建应用副本，也不是由它判断应用所有业务接口是否健康。它消费的后端信息来自集群对象状态，readiness 等状态会影响通常的后端资格。

常见部署会以 DaemonSet 运行 kube-proxy，但并不是“Service 协议要求它必须作为 DaemonSet”。某些网络方案采用不同的服务数据平面实现，集群也可能不使用 kube-proxy。因此，分析具体环境前应先确认实现，不能仅从 Pod 名称推断全部网络结构。

## 3. 控制路径与数据路径要分开

![Service 状态更新、节点规则与业务流量的区别](/assets/notes/kubernetes/k8s-service-control-data.svg)

上半部分是控制路径：API 中的状态变化被观察到后，节点规则随之协调。下半部分是业务路径：客户端连接 Service 地址与端口，由适用的数据平面选取后端，再沿 Pod 网络到达目标端口。

在 iptables 模式下，kube-proxy 主要负责配置规则，业务数据包并不是先交给 kube-proxy 用户态进程逐条处理。它也不会因为服务使用 HTTP，就开始按 `Host` 或 URL 路径做七层路由。

把“不是 HTTP 代理”写成“不支持 HTTP 流量”是错误的：HTTP 可以承载在 TCP 连接上，Service 可以转发这样的连接；只是它不因此具备 HTTP 语义路由能力。

## 4. 1.28 的模式，不能套用今天的列表

Kubernetes v1.28.0 的 kube-proxy 参数说明列出了 Linux 的 `iptables` 和 `ipvs`，以及 Windows 的 `kernelspace`。这是本章的历史范围；不要把后来文档中的 nftables 模式和迁移建议倒写成 1.28 的默认配置。[v1.28.0 kube-proxy 参数源码](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/cmd/kube-proxy/app/server.go)

| 模式     | 本章需要理解的机制                            | 不应得出的结论                     |
| -------- | --------------------------------------------- | ---------------------------------- |
| iptables | kube-proxy 协调内核规则，典型路径包含目标转换 | 每个请求都经过用户态代理进程       |
| IPVS     | 利用内核 IPVS 及配套网络规则实现转发          | 有哈希表就意味着无限扩展、永远更快 |

模式选择受版本、内核能力、服务数量、规则变化频率、兼容语义和运维条件影响。原笔记中关于 IPVS 性能的绝对结论缺乏环境和测量条件，本稿不保留为普遍结论；也没有据此替你修改模式。

当前官方 [虚拟 IP 与 Service 代理说明](https://kubernetes.io/docs/reference/networking/virtual-ips/)可补充机制背景，但其中新增模式、弃用时间和调优参数必须与具体版本另行核对。本章不提供未经复测的性能数字。

## 5. 用一次连接理解端口转换

新增教学示例：一个 Service 对外提供 TCP 80，后端应用监听 TCP 8080。客户端连接的是 Service 的 80 端口，最终到达某个后端的 8080 端口。

```text
客户端 → Service 地址:80 → 服务数据平面 → 后端 Pod 地址:8080
```

这里的 Service 地址不是节点地址，也不表示应用必须监听 80。`port` 和 `targetPort` 分别描述两个位置，名字相似不代表含义相同。

本例刻意不用原文中的 `10.96.123.456`：它不是合法 IPv4 地址，最后一段超过了 255。示意地址若写错，会让读者误把无效数据当成可执行配置；图中改为角色名称，实际地址从环境观察。

连接转发还要考虑回程、连接跟踪、会话保持与流量策略。负载均衡不意味着一个 HTTP 长连接里的每个请求都会平均分配到不同 Pod，也不保证多个后端获得完全相同的请求数。

## 6. 后端变化，不意味着旧连接瞬间消失

Pod 创建、就绪或终止后，相关端点状态与节点规则需要经过多个协调过程更新，不能将其描述为“实时同步，永不访问异常后端”。

排查时至少区分：

1. API 中端点是否已更新。
2. 节点的数据平面是否已经反映相关状态。
3. 客户端是否复用了已有连接或缓存。
4. 服务策略是否限制只使用本地端点。
5. 应用是否仍在监听并处理已有请求。

readiness、`publishNotReadyAddresses`、终止端点及相应流量策略，会影响“哪些端点被认为适合使用”。在普通控制器维护的 EndpointSlice 中，先读 `conditions.ready`、`serving`、`terminating`：一个 `ready: false, serving: true, terminating: true` 的端点正在退出，但应用仍可能就绪。是否接收具体流量，还由数据平面、连接状态与策略决定。字段规则和缺省值在第十九章展开，不能只数 Pod 就判断后端可用。

## 7. 按失败层级检查

以下命令是未执行的查询模板；查看输出不等于获准修改网络。

```bash
kubectl get service SERVICE_NAME -n NAMESPACE -o yaml
kubectl get pods -n NAMESPACE --show-labels
kubectl get endpointslice -n NAMESPACE -l kubernetes.io/service-name=SERVICE_NAME -o yaml
```

如果没有端点，先核对命名空间、选择器、标签、应用就绪与目标端口信息，不要直接清空规则。

如果端点看似正确，再比较同一客户端访问 Pod 地址、Service 地址和服务名的区别。三种路径失败的位置不一样：只有服务名失败时更需要看 DNS；Pod 地址也失败时还要看应用和 Pod 网络；只有 Service 地址失败时才更集中检查服务数据平面及策略。对比结果是线索，不是没有例外的判定公式。

NodePort 是否可达还受节点地址选择、流量策略、防火墙和底层网络影响。“任意节点加端口一定通”和“生产环境不能使用 NodePort，因为一定低效”都过于绝对。对外访问设计将在 Service 与 Ingress 资源章中按条件展开。

## 8. 本章小结

Service 提供逻辑入口，端点描述后端，kube-proxy 的常见作用是把这些信息落实到节点服务数据平面。规则更新与业务流量不是同一条调用链；下一章补上名称发现，解释 CoreDNS 为什么可以解析服务名，却不代替应用转发业务请求。

[返回本册目录](/collections/kubernetes/) · [下一章：CoreDNS 与服务发现](/articles/kubernetes-coredns.html)
