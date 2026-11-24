---
id: kubernetes-kube-proxy
title: 第十章 kube-proxy 与 Service 转发
description: "工作负载的 Pod 会替换，Pod 地址也可能变化。客户端若把每个实例的地址写死，就需要随时追踪这些变化。Service 通过逻辑入口与后端集合的配合，让客户端不必把某个临时 Pod 当成永久地址。"
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
order: 10
---

# 第十章 kube-proxy 与 Service 转发

> 聚焦 Kubernetes 1.28 的 Linux 节点，解释 Service 的节点侧实现。Service 清单编写和对外暴露将在资源章节继续展开；本章不更换代理模式，也不修改防火墙规则。

## 1. 为什么需要一个不跟着 Pod 改变的入口

工作负载的 Pod 会替换，Pod 地址也可能变化。Service 给这一组 Pod 一个固定的名字和固定地址，客户端只认这一个地址；后面 Pod 被替换掉，Service 把新请求转给换上的新 Pod。

Service 是 API 对象，并不是一台独立的代理机器。以普通 ClusterIP Service 为例，要真的把连接转发出去，还需要两样东西：一份“当前哪些 Pod 可用”的端点信息，以及节点上真正改写数据包的那层机制，也就是服务数据平面（例如内核里的 iptables 规则）。

这里先明确例外：Headless Service 使用 `clusterIP: None`，没有普通 Service 虚拟 IP；ExternalName 提供 DNS 别名语义，也不是为它新建一组普通虚拟 IP 转发规则。这些类型需要按各自的地址与转发语义理解。[Kubernetes 1.28 Service](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/service.md)

## 2. Service、端点与 kube-proxy 各做什么

可以按信息流拆成三层：

- Service 是你写的配置，只声明两件事：入口监听哪个端口，以及用哪些标签挑后端 Pod。
- EndpointSlice 是一张实时更新的名单，由控制器按对象状态维护：把符合条件、已经就绪的 Pod 地址和端口写进去。1.28 学习时应认识它，而不只停留在旧 Endpoints 对象。
- kube-proxy 是每个节点上的执行者：它盯着 Service 和名单的变化，把本机内核里的转发规则改成一致。

kube-proxy 不负责创建应用副本，也不去探测应用好不好用。它读的是集群里已经算好的后端名单；一个 Pod 能不能进这份名单，取决于 readiness 这类由 kubelet 上报的状态，而不是 kube-proxy 自己判断。

常见部署会以 DaemonSet 运行 kube-proxy，但并不是“Service 协议要求它必须作为 DaemonSet”。某些网络方案采用不同的服务数据平面实现，集群也可能不使用 kube-proxy。因此，分析具体环境前应先确认实现，不能仅从 Pod 名称推断全部网络结构。

## 3. 控制路径与数据路径要分开

[![Service：规则更新与业务流量是两条路径](/assets/notes/kubernetes/k8s-service-control-data.svg)](/assets/notes/kubernetes/k8s-service-control-data.svg)

上半部分是控制路径：Service 或端点一有变化，kube-proxy 收到通知，去改本节点的转发规则。下半部分是业务路径：客户端连接 Service 地址与端口时，由内核里已经写好的规则直接挑一个后端，数据包沿 Pod 网络到达目标端口，这一段没有 kube-proxy 参与。

在 iptables 模式下，kube-proxy 主要负责配置规则，业务数据包并不是先交给 kube-proxy 用户态进程逐条处理。它也不会因为服务使用 HTTP，就开始按 `Host` 或 URL 路径做七层路由。

HTTP 可以承载在 TCP 连接上，Service 能转发这样的连接；按 `Host` 或 URL 路径路由则属于七层能力，需要相应入口实现。

## 4. 1.28 的模式，不能套用今天的列表

Kubernetes v1.28.0 的 kube-proxy 参数说明列出了 Linux 的 `iptables` 和 `ipvs`，以及 Windows 的 `kernelspace`。这是本章的历史范围；后来文档中的 nftables 模式和迁移建议，不是 1.28 的默认配置。[v1.28.0 kube-proxy 参数源码](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/cmd/kube-proxy/app/server.go)

| 模式     | 本章需要理解的机制                            | 常见误解                           |
| -------- | --------------------------------------------- | ---------------------------------- |
| iptables | kube-proxy 协调内核规则，典型路径包含目标转换 | 每个请求都经过用户态代理进程       |
| IPVS     | 利用内核 IPVS 及配套网络规则实现转发          | 有哈希表就意味着无限扩展、永远更快 |

模式选择受版本、内核能力、服务数量、规则变化频率、兼容语义和运维条件影响。IPVS 的性能表现需结合上述条件测量，不能仅由数据结构推导实际收益。

当前官方 [虚拟 IP 与 Service 代理说明](https://kubernetes.io/docs/reference/networking/virtual-ips/)可补充机制背景，但其中新增模式、弃用时间和调优参数必须与具体版本另行核对。本章不提供未经复测的性能数字。

## 5. 用一次连接理解端口转换

以 `catalog` 为例，Service 提供 TCP 80，后端应用监听 TCP 8080。客户端连接 Service 的 80 端口，最终到达某个后端的 8080 端口。这里“提供入口”不表示一定能从集群外访问。

```text
客户端 → Service 地址:80 → 服务数据平面 → 后端 Pod 地址:8080
```

这里的 Service 地址不是节点地址，也不表示应用必须监听 80。`port` 是 Service 自己对外开的端口，`targetPort` 是流量最终打进 Pod 容器的端口。名字相似，作用在两段不同的连接上。

### 5.1 一条 TCP 连接怎样到达 Pod？

以下地址均为合法的**人为教学地址**，不是实际集群值，实验也不需要分配这些固定 IP：

| 对象            | 示例地址           |
| --------------- | ------------------ |
| Service catalog | `10.96.10.20:80`   |
| Pod A           | `10.244.1.10:8080` |
| Pod B           | `10.244.2.10:8080` |
| 客户端 Pod      | `10.244.3.10`      |

VIP（Virtual IP，虚拟 IP）表示这个逻辑 Service 入口。NAT（Network Address Translation，网络地址转换）改变数据包的地址或端口；其中 DNAT（Destination Network Address Translation，目的网络地址转换）改变目的位置。Conntrack（Connection Tracking，连接跟踪）维护连接状态及适用的转换关联。

以 Kubernetes 1.28 Linux iptables 模式、普通 TCP ClusterIP 流量为例，假设这次选择 Pod A，省略额外的源地址转换：

1. 客户端从临时端口（例如 `49152`）向 `10.96.10.20:80` 建立 TCP 连接。
2. 数据包进入适用的节点内核处理路径，匹配 kube-proxy **预先配置**的 Service 规则；不是临时调用 kube-proxy 处理 HTTP。
3. 规则依据可用端点、会话保持及流量策略等选择后端。本例选 A，通过 DNAT 把目标从 `10.96.10.20:80` 改为 `10.244.1.10:8080`。
4. 包沿 Pod 网络到达 A。此后这条连接的流量使用相应 Conntrack/NAT 状态，不是每个 HTTP 请求重新轮询后端。
5. A 返回数据，回程经过相应路由与连接跟踪处理；反向转换让客户端仍看到来自 Service `10.96.10.20:80` 的响应，维持连接两端预期的地址关系。

[![Service TCP 连接的 DNAT 与返回路径](/assets/notes/kubernetes/k8s-service-connection-nat.svg)](/assets/notes/kubernetes/k8s-service-connection-nat.svg)

这是一次连接的简化关系，不是所有 CNI 和节点布局的完整内核路径。实际还可能涉及 SNAT（Source Network Address Translation，源网络地址转换）、不同的路由和连接跟踪条件。B 是另一候选后端，不表示该连接的下一个 HTTP 请求就会转到 B。[v1.28.0 iptables 转发规则实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/proxy/iptables/proxier.go)

连接转发还要考虑回程、连接跟踪、会话保持与流量策略。负载均衡不意味着一个 HTTP 长连接里的每个请求都会平均分配到不同 Pod，也不保证多个后端获得完全相同的请求数。

## 6. 后端更新、端点传播与已有连接 {#_6-后端变化-不意味着旧连接瞬间消失}

Pod 创建、就绪或终止后，相关端点状态与节点规则需要经过多个协调过程更新，不能将其描述为“实时同步，永不访问异常后端”。

排查时至少区分：

1. API 中端点是否已更新。
2. 节点的数据平面是否已经反映相关状态。
3. 客户端是否复用了已有连接或缓存。
4. 服务策略是否限制只使用本地端点。
5. 应用是否仍在监听并处理已有请求。

readiness、`publishNotReadyAddresses`、终止端点及相应流量策略，会影响“哪些端点被认为适合使用”。在普通控制器维护的 EndpointSlice 中，先读 `conditions.ready`、`serving`、`terminating`：一个 `ready: false, serving: true, terminating: true` 的端点正在退出，但应用仍可能就绪。是否接收具体流量，还由数据平面、连接状态与策略决定。字段规则和缺省值在第十九章展开，不能只数 Pod 就判断后端可用。

例如最初 A、B 都 Ready，`catalog` 有两个适用后端；随后 B 开始终止：

1. Pod B 出现删除时间等终止信息。Pod 的 Ready 条件与“是否正在终止”分别表达不同状态，不能简单认为删除请求使所有流量立刻消失。
2. EndpointSlice 控制器更新 B 的条件。常见未设置 `publishNotReadyAddresses` 的场景，终止端点的 `ready` 为 false；`terminating` 表达退出中，`serving` 则可表达终止期间的就绪能力。
3. 节点端点观察与规则同步随后推进。API 中的 EndpointSlice 已更新，只能证明对象层有了变化，不能证明所有节点都已完成规则更新。
4. 节点反映变化后，常规新连接的后端选择会随之调整；已有 TCP 连接仍可能保留到 B 的连接跟踪关系，只要应用和网络仍允许，就可能继续处理请求，也可能因终止、超时或其他原因中断。

| 观察项                    | 回答的问题                                                                     |
| ------------------------- | ------------------------------------------------------------------------------ |
| Pod Ready                 | kubelet 报告的 Pod 就绪条件如何？                                              |
| EndpointSlice `ready`     | 对常规端点消费者，这个端点是否可作为就绪后端？终止与发布未就绪地址存在额外语义 |
| `serving` / `terminating` | 端点是否仍具备服务能力、是否进入终止过程？                                     |
| 节点数据平面              | 对象变化是否已经落实到该节点的转发机制？                                       |
| 客户端连接                | 客户端新建连接，还是继续复用已有连接？                                         |

所以“不再 Ready”不是立即拆除所有旧连接的命令，端点更新也不是节点同步完成的证明。本地流量策略、终止端点处理等还可能改变后端使用方式，本章不承诺无损切换；更完整的条件规则见[第十九章 Service 与 EndpointSlice](/articles/kubernetes-service-endpointslice.html)。[v1.28 EndpointSlice 条件](https://github.com/kubernetes/website/blob/release-1.28/content/en/docs/concepts/services-networking/endpoint-slices.md#conditions)

## 7. 按失败层级检查

以下命令是查询模板；查看输出只覆盖读取，修改网络仍需单独授权。

```bash
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n NAMESPACE 限定命名空间
# -o yaml 输出完整对象字段，便于核对 spec 与 status
kubectl get service SERVICE_NAME -n NAMESPACE -o yaml
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n NAMESPACE 限定命名空间
# --show-labels 显示全部标签，-L 则把指定标签展示为列（按本命令所用选项）
kubectl get pods -n NAMESPACE --show-labels
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n NAMESPACE 限定命名空间
# -l kubernetes.io/service-name=SERVICE_NAME 按标签选择对象，不是按名称匹配
# -o yaml 输出完整对象字段，便于核对 spec 与 status
kubectl get endpointslice -n NAMESPACE -l kubernetes.io/service-name=SERVICE_NAME -o yaml
```

如果没有端点，先核对命名空间、选择器、标签、应用就绪与目标端口信息，直接清空规则会丢掉其他服务的转发。

如果端点看似正确，再比较同一客户端访问 Pod 地址、Service 地址和服务名的区别。三种路径失败的位置不一样：只有服务名失败时更需要看 DNS；Pod 地址也失败时还要看应用和 Pod 网络；只有 Service 地址失败时才更集中检查服务数据平面及策略。对比结果是线索，不是没有例外的判定公式。

NodePort 是否可达还受节点地址选择、流量策略、防火墙和底层网络影响。“任意节点加端口一定通”和“生产环境不能使用 NodePort，因为一定低效”都过于绝对。对外访问设计将在 Service 与 Ingress 资源章中按条件展开。

### 7.1 对照 Pod IP、Service IP 与服务名 {#catalog-access-test}

先按[第十二章共用实验清单](/articles/kubernetes-api-yaml-labels.html#catalog-lab)准备 `study/catalog` Deployment、Service 和 `dns-debug` Pod。前提是两个应用副本已 Ready、Service selector 匹配 `app=catalog`，客户端到后端 TCP 8080、Service TCP 80 及 DNS 路径未被策略阻断。使用 IPv4 测试地址，命令在同一个 Bash 终端执行。

```bash
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n study 限定命名空间
kubectl get svc catalog -n study
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n study 限定命名空间
# -l app=catalog 按标签选择对象，不是按名称匹配
# -o wide 展示节点、IP 等扩展列
kubectl get pods -n study -l app=catalog -o wide
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n study 限定命名空间
# -l kubernetes.io/service-name=catalog 按标签选择对象，不是按名称匹配
# -o yaml 输出完整对象字段，便于核对 spec 与 status
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
# 用 kubectl 查询对象字段并保存到 POD_IP；-o jsonpath 只提取表达式指定的值，供后续请求使用
POD_IP=$(kubectl get pods -n study -l app=catalog -o jsonpath='{.items[0].status.podIP}')
# 用 kubectl 查询对象字段并保存到 SERVICE_IP；-o jsonpath 只提取表达式指定的值，供后续请求使用
SERVICE_IP=$(kubectl get svc catalog -n study -o jsonpath='{.spec.clusterIP}')
# 在指定 Pod 的容器中执行 -- 后面的命令；-c 选择容器，-- 之后的参数传给容器内程序
# wget -qO- 将 HTTP 响应写到标准输出，-T 5 设置超时秒数；URL 用于对比 Pod、Service 或 DNS 路径
# -n study 限定命名空间
kubectl exec dns-debug -n study -- wget -qO- -T 5 "http://$POD_IP:8080"
# 在指定 Pod 的容器中执行 -- 后面的命令；-c 选择容器，-- 之后的参数传给容器内程序
# wget -qO- 将 HTTP 响应写到标准输出，-T 5 设置超时秒数；URL 用于对比 Pod、Service 或 DNS 路径
# -n study 限定命名空间
kubectl exec dns-debug -n study -- wget -qO- -T 5 "http://$SERVICE_IP:80"
# 在指定 Pod 的容器中执行 -- 后面的命令；-c 选择容器，-- 之后的参数传给容器内程序
# wget -qO- 将 HTTP 响应写到标准输出，-T 5 设置超时秒数；URL 用于对比 Pod、Service 或 DNS 路径
# -n study 限定命名空间
kubectl exec dns-debug -n study -- wget -qO- -T 5 http://catalog.study.svc.cluster.local:80
```

先确认列表非空、所选 Pod 已就绪且两个变量均为实际地址；第 5.1 节的教学 IP 只用于说明，代入会得到错误结果。条件满足时三次都预期返回 `catalog`，但证明范围不同：

| 路径            | 额外依赖与边界                                            |
| --------------- | --------------------------------------------------------- |
| Pod IP:8080     | 应用监听、Pod 网络及适用策略；不经过本例 Service VIP 选择 |
| ClusterIP:80    | 再增加 Service 端口、端点与服务数据平面的处理             |
| Service 名称:80 | 再增加源 Pod 的 DNS 配置、解析器与实际 DNS 查询路径       |

这是对照实验，不能从某一行失败唯一确定根因；直接测试一个 Pod 也只覆盖该 Pod。若需隔离 DNS 问题，继续[第十一章实验](/articles/kubernetes-coredns.html#catalog-dns-test)。只做本章时，结束后用 `kubectl delete namespace study` 清理专用空间；继续后续实验则暂不清理。整个实验不修改任何 iptables、IPVS 或 nftables 规则。

## 8. 本章小结

Service 提供逻辑入口，端点描述后端，kube-proxy 的常见作用是把这些信息落实到节点服务数据平面。规则更新与业务流量不是同一条调用链；下一章补上名称发现，解释 CoreDNS 为什么可以解析服务名，却不代替应用转发业务请求。

[返回本册目录](/collections/kubernetes/) · [下一章：CoreDNS 与服务发现](/articles/kubernetes-coredns.html)
