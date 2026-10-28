---
id: kubernetes-coredns
title: 第十一章 CoreDNS 与服务发现
description: "应用通常希望连接“订单服务”，而不是记住某个 Pod 地址。DNS 负责把名称解析为相应记录，应用再利用结果建立连接。"
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
order: 11
---

# 第十一章 CoreDNS 与服务发现

> 本章围绕 Kubernetes 1.28 的服务发现语义，说明名称解析、服务转发与 Pod 网络的关系。实际 CoreDNS 镜像、插件版本与 Corefile 尚未复测，配置需按目标环境核对。

## 1. 一个服务名，涉及两件不同的事

应用通常希望连接“订单服务”，而不是记住某个 Pod 地址。DNS 负责把名称解析为相应记录，应用再利用结果建立连接。

这两件事必须分开：

1. 查询：服务名应解析成什么？
2. 连接：到解析结果对应的端口，业务能否成功？

[![DNS 解析成功之后，应用才建立业务连接](/assets/notes/kubernetes/k8s-dns-two-paths.svg)](/assets/notes/kubernetes/k8s-dns-two-paths.svg)

以普通 ClusterIP Service 为例，应用通过 DNS 查询得到 Service 地址后，再发起业务连接，由服务数据平面处理。CoreDNS 并不因此成为 HTTP 请求的业务代理。解析超时与业务连接超时虽然表面相似，却不能都用“重启 DNS”来处理。

## 2. CoreDNS 与 kube-dns 这个名字

CoreDNS 是常见的集群 DNS 实现。很多环境中，对 Pod 暴露的 DNS Service 仍叫 `kube-dns`，而后端运行的是 CoreDNS。Service 名称与服务实现不是一回事。

kubelet 参与配置 Pod 的 DNS 环境，应用使用的解析器再按配置进行查询。典型部署会经过集群 DNS 服务入口，但使用 NodeLocal DNS 或其他配置时路径可能不同。不要把一张默认部署图写成所有环境的唯一拓扑。

CoreDNS 需要了解相关 Kubernetes 对象，才能形成集群内服务记录。它的 kubernetes 插件文档说明了 API 观察与服务记录处理的关系；具体插件选项依版本而定，这里用于说明组件职责，历史环境的默认值仍需查阅对应版本。[CoreDNS kubernetes 插件](https://coredns.io/plugins/kubernetes/)

## 3. 服务名里每一段代表什么

下面是新增教学例子，不对应你的真实集群：服务叫 `catalog`，位于 `shop` 命名空间，集群域暂用 `cluster.local` 举例。

```text
catalog.shop.svc.cluster.local
│       │    │   └─ 示例集群域，真实值不一定相同
│       │    └───── Service 记录所在层级
│       └────────── 命名空间
└────────────────── Service 名
```

在常见搜索域配置下，同命名空间的客户端可以查询 `catalog`；其他命名空间的客户端需要带上 `shop` 等足够限定信息。短名称怎样扩展，还取决于源 Pod 的解析配置，不是 DNS 服务器凭空猜到你想访问哪个命名空间。

`cluster.local` 是常见例子，不是规范要求你只能使用这个集群域。复制别人文档中的完整名称前，应确认实际集群域与源 Pod 的搜索列表。

## 4. 普通、Headless 与 ExternalName 的差异

| Service 情形   | 需要理解的 DNS 结果                  | 客户端随后面对什么                       |
| -------------- | ------------------------------------ | ---------------------------------------- |
| 普通 ClusterIP | A / AAAA 记录对应 Service 的集群地址 | Service 数据平面负责适用的后端转发       |
| Headless       | 典型的有选择器场景返回后端地址集合   | 客户端需要理解多个地址与实例变化         |
| ExternalName   | CNAME 别名记录                       | 继续解析别名目标，不是本集群新建代理后端 |

普通与 Headless Service 的记录差异参见 [Kubernetes 1.28 DNS 约定](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/dns-pod-service.md)。端点是否就绪、是否发布未就绪地址，以及是否存在手工管理端点等条件会影响具体结果。

Headless 并不意味着没有 Service，也不保证每次连接都能自动均匀分散。客户端解析器可能缓存结果，应用也可能只选择一个地址。使用 ExternalName 时，还需留意应用协议中的主机名，例如 HTTP Host 或 TLS 证书名称，它们不会因使用 DNS 别名而自动改写。

## 5. resolv.conf、搜索域与 ndots

在典型 Linux Pod 中，`/etc/resolv.conf` 描述 nameserver、搜索域和解析器选项。它有助于回答三个问题：

- 请求先发到哪个 DNS 入口？
- 短名称会尝试追加哪些搜索后缀？
- 一个带点号的名称，解析器会如何决定先尝试绝对查询还是搜索扩展？

`ndots` 与名称中的点号数量有关，不是“最多向 DNS 请求几次”。解析器实现、应用库、缓存和具体配置都会影响查询行为。对于一个外部名称，搜索域扩展可能产生额外查询；但没有流量证据时，不应直接断言它造成了你的性能瓶颈。

新增合成的 Linux Pod 配置示意，地址只是文档示例，不对应真实集群：

```text
nameserver 192.0.2.53
search study.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

nameserver 指向解析入口；search 提供短名称的候选后缀；ndots:5 影响解析器优先尝试绝对名称还是搜索扩展。`catalog` 可按搜索域展开；显式以末尾点号结束的 `catalog.study.svc.cluster.local.` 表达绝对名称。不同语言运行库的查询顺序、缓存和超时行为并不完全一致，不能据此计算所有客户端固定的请求次数。

`dnsPolicy` 决定配置来源。在本章 Linux 范围，`hostNetwork: true` 且需要集群 DNS 时，应显式使用 `dnsPolicy: ClusterFirstWithHostNet`；只写 ClusterFirst 会退回 Default 的行为。Default 通常继承节点解析配置，不是“默认就使用集群 DNS”的意思。普通 Pod 常用 ClusterFirst，也不保证外部域名或业务网络必然可达。[1.28 Pod DNS 策略](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/dns-pod-service.md)

排查时读取源 Pod 的实际配置，确认 DNS 入口和搜索域，再分析请求路径。

## 6. Corefile 中几个常见职责

Corefile 是 CoreDNS 配置。初学时先认识职责，比一次复制一整段配置更重要：

- `kubernetes` 处理配置范围内的 Kubernetes 服务发现记录。
- `forward` 可以把适用查询转发到配置的上游解析器。
- `cache` 缓存 DNS 结果，减少重复查询，但缓存也意味着变化不总是立即被客户端观察到。

这些插件共同组织名称解析，实际 Corefile 需要结合插件版本与环境配置验证。上游可能是企业 DNS，而不是公共互联网 DNS；DNS 出口也可能受网络策略和防火墙约束。不能把“外部域名失败”直接理解为“集群内服务发现全部失败”。

关于转发与缓存的行为和可配置项，后续修改前应核对相应版本的 [forward 文档](https://coredns.io/plugins/forward/)与 [cache 文档](https://coredns.io/plugins/cache/)，本章不建议随意增大缓存时间或放开所有出口。

## 7. 排障先区分返回码与连接阶段

[![DNS 排查：先按失败类型划分边界](/assets/notes/kubernetes/k8s-dns-triage.svg)](/assets/notes/kubernetes/k8s-dns-triage.svg)

常见现象可以这样组织证据：

| 现象                 | 优先核对                                     | 不能立即下的结论               |
| -------------------- | -------------------------------------------- | ------------------------------ |
| NXDOMAIN             | 名称、命名空间、对象是否存在、查询范围       | 一定是网络不通                 |
| SERVFAIL             | DNS 处理失败、对象同步、插件与上游等         | 一定要删除 CoreDNS Pod         |
| 查询超时             | DNS 入口、端点、协议与网络策略、服务处理情况 | 一定是服务名拼错               |
| 已得到地址但连接失败 | 业务端口、后端就绪、Service、Pod 网络与应用  | DNS 解析成功就证明全链路没问题 |

这些只是定位起点，并未涵盖所有根因。应记录错误发生在哪个源 Pod；即使在节点终端查询成功，也不能据此证明 Pod 内的解析路径正常。

以下是授权环境中常见的查询模板，本次未执行。`kube-dns` 与标签要以实际部署为准；权限不足也不能被当成 DNS 服务故障。

```bash
kubectl get service kube-dns -n kube-system
kubectl get endpointslice -n kube-system -l kubernetes.io/service-name=kube-dns
kubectl get pods -n kube-system
```

若要进一步检查 Pod 内的解析配置或发起 DNS 查询，需要已有合适的诊断环境、工具和权限。诊断工具是否存在与 DNS 是否正常是两个检查项：缺少 nslookup 等命令时，应选择已有诊断环境继续验证。

## 8. 本章小结

名称解析、服务转发、Pod 网络是相互依赖但不同的层级。到这里，控制平面与常见节点组件已经形成一条完整的理解线索：状态经 API 协调，kubelet 借助运行时运行容器，网络机制支持连接，服务与 DNS 帮助客户端找到并访问后端。后续将把这些原理落实到资源清单、日常管理、权限与排查。

[返回本册目录](/collections/kubernetes/)
