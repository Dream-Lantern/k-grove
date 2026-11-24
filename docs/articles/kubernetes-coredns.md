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

应用通常希望连接一个服务名，而不是记住某个 Pod 地址。DNS（Domain Name System，域名系统）负责把名称解析为相应记录，应用再利用结果建立连接。本轮沿用 `study` 命名空间的 `catalog` 服务。

这两件事必须分开：

1. 查询：服务名应解析成什么？
2. 连接：到解析结果对应的端口，业务能否成功？

[![DNS 解析成功之后，应用才建立业务连接](/assets/notes/kubernetes/k8s-dns-two-paths.svg)](/assets/notes/kubernetes/k8s-dns-two-paths.svg)

以普通 ClusterIP Service 为例，应用通过 DNS 查询得到 Service 地址后，再发起业务连接，由服务数据平面处理。CoreDNS 只负责解析，不代理 HTTP 请求。解析超时与业务连接超时表现相似，处理路径不同：前者查 DNS，后者查 Service、端点与后端。

## 2. CoreDNS 与 kube-dns 这个名字

CoreDNS 是常见的集群 DNS 实现。很多环境中，对 Pod 暴露的 DNS Service 仍叫 `kube-dns`，而后端运行的是 CoreDNS。Service 名称与服务实现不是一回事。

kubelet 参与配置 Pod 的 DNS 环境，应用使用的解析器再按配置进行查询。典型部署经过集群 DNS 服务入口；使用 NodeLocal DNS 或其他方案时，路径会不同。

CoreDNS 需要了解相关 Kubernetes 对象，才能形成集群内服务记录。它的 kubernetes 插件文档说明了 API 观察与服务记录处理的关系；具体插件选项依版本而定，这里用于说明组件职责，历史环境的默认值仍需查阅对应版本。[CoreDNS kubernetes 插件](https://coredns.io/plugins/kubernetes/)

把状态来源与查询方向拆开，可理解为：

```text
状态来源：API Server → kubernetes 插件的对象观察 / 本地状态 → 集群服务记录
查询路径：客户端 Pod → 实际 DNS 入口 → CoreDNS → 查询结果返回客户端
需要转发的查询：CoreDNS → forward 插件 → 配置的上游 DNS → 返回结果
```

状态箭头表示插件通过 Kubernetes API 观察 Service、端点等对象；API Server 不会反过来调用 DNS，普通客户端也不直接查询 etcd。配置 cache 插件后，部分结果来自缓存，客户端解析器自身也会缓存，因此对象变更不会立刻反映到每次查询。

DNS 入口可能是名为 `kube-dns` 的 Service，也可能是 NodeLocal DNS 提供的本地入口；入口是 Pod 发查询时最先对接的对象，CoreDNS 是真正应答查询的进程，本地缓存是两者之间可能存在的加速层，三者不是同一个东西。本章不给出固定的镜像与 Corefile，插件参数以目标版本为准。

## 3. 服务名里每一段代表什么

下面是教学名称，不对应固定的真实集群：服务叫 `catalog`，位于 `study` 命名空间，集群域用 `cluster.local` 举例。

```text
catalog.study.svc.cluster.local
catalog       Service 名
study         Namespace
svc           Service DNS 层级
cluster.local 示例集群域，真实值不一定相同
```

在常见搜索域配置下，同命名空间的客户端可以直接查询 `catalog`；其他命名空间需要带上 `study` 等限定信息。短名称如何扩展取决于源 Pod 的解析配置。

`cluster.local` 只是常见约定，集群域可以自定义。复制他人文档中的完整名称前，先确认真实集群域与源 Pod 的搜索列表。

FQDN（Fully Qualified Domain Name，完全限定域名）明确名称的完整层级；显式包含末尾根点号可避免搜索域扩展。常见记录类型分别回答不同问题：

| 记录                             | 含义与本例关系                                                                                                                  |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| A Record（IPv4 地址记录）        | 将名称指向 IPv4 地址，例如普通 Service 的 IPv4 ClusterIP                                                                        |
| AAAA Record（IPv6 地址记录）     | 将名称指向 IPv6 地址；IPv4 单栈实验不要求同时得到 AAAA                                                                          |
| CNAME Record（规范名称别名记录） | 将一个名称指向另一个名称，ExternalName Service 采用此类语义                                                                     |
| SRV Record（服务定位记录）       | 提供目标名称和端口等信息；Kubernetes 为 Service 的命名端口提供相应发现记录，如本例 `_http._tcp.catalog.study.svc.cluster.local` |

## 4. 普通、Headless 与 ExternalName 的差异

| Service 情形   | 需要理解的 DNS 结果                  | 客户端随后面对什么                       |
| -------------- | ------------------------------------ | ---------------------------------------- |
| 普通 ClusterIP | A / AAAA 记录对应 Service 的集群地址 | Service 数据平面负责适用的后端转发       |
| Headless       | 典型的有选择器场景返回后端地址集合   | 客户端需要理解多个地址与实例变化         |
| ExternalName   | CNAME 别名记录                       | 继续解析别名目标，不是本集群新建代理后端 |

普通与 Headless Service 的记录差异参见 [Kubernetes 1.28 DNS 约定](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/dns-pod-service.md)。端点是否就绪、是否发布未就绪地址，以及是否存在手工管理端点等条件会影响具体结果。

Headless Service 仍然有 Service 对象，只是不分配 ClusterIP；返回多个地址也不等于客户端会均匀使用——解析器会缓存结果，应用也可能只取第一个地址。使用 ExternalName 时，应用协议中的主机名（HTTP Host、TLS 证书名称）不会随 DNS 别名自动改写。

### 4.1 没有 Ready 后端，一定不能解析吗？

不一定。DNS 只回答“这个名字对应哪个地址”，“那个地址后面有没有能接请求的后端”是另一回事：

| 场景                          | 典型行为与边界                                     |
| ----------------------------- | -------------------------------------------------- |
| 普通 ClusterIP，有 Ready 后端 | Service 名称通常解析为 ClusterIP，仍需验证端口连接 |
| 普通 ClusterIP，无 Ready 后端 | 名称通常仍能解析为 ClusterIP，但业务连接可能失败   |
| Headless，有可发布后端        | 返回相应后端地址，客户端自行使用解析结果           |
| Headless，无可发布后端        | 可能没有可用地址记录，也不会返回 ClusterIP         |

例如 `catalog` 的 Pod 全部未就绪时，Service 对象与 ClusterIP 仍然存在，DNS 照常返回 ClusterIP，但节点上没有可转发的后端。Headless 记录直接依赖可发布端点，`publishNotReadyAddresses` 会改变未就绪地址的发布条件。CoreDNS 版本、对象同步与插件配置同样影响结果，例如插件文档中的 `ignore empty_service` 选项会改变空 Service 的回答，是否启用要看实际配置。零个 Ready 后端通常仍返回记录，不会变成 NXDOMAIN。[CoreDNS kubernetes 插件的服务处理选项](https://coredns.io/plugins/kubernetes/)

## 5. resolv.conf、搜索域与 ndots

在典型 Linux Pod 中，`/etc/resolv.conf` 记录三样东西：nameserver（查询发给哪台 DNS 服务器）、搜索域（短名称补哪些后缀）和解析器选项。它有助于回答三个问题：

- 请求先发到哪个 DNS 入口？
- 短名称会尝试追加哪些搜索后缀？
- 一个带点号的名称，解析器会如何决定先尝试绝对查询还是搜索扩展？

`ndots` 与名称中的点号数量有关，决定解析器何时先尝试绝对名称，不是查询次数上限。解析器实现、应用库、缓存和具体配置都会影响查询行为。外部名称的搜索域扩展会产生额外查询，是否构成瓶颈要看实际流量。

新增合成的 Linux Pod 配置示意，地址只是文档示例，不对应真实集群：

```text
nameserver 192.0.2.53
search study.svc.cluster.local svc.cluster.local cluster.local
options ndots:5
```

nameserver 指向解析入口；search 提供短名称的候选后缀；ndots:5 影响解析器优先尝试绝对名称还是搜索扩展。`catalog` 可按搜索域展开；显式以末尾点号结束的 `catalog.study.svc.cluster.local.` 表达绝对名称。不同语言运行库的查询顺序、缓存和超时行为不同，实际请求次数要按客户端实现计算。

按常见 Linux 解析器的搜索语义，前序候选失败时会继续尝试后续候选。下表是推演出的候选扩展，实际序列取决于客户端实现：

| 输入名称                           | 与上述 `ndots:5` 配置的关系        | 候选示例                                                                                     |
| ---------------------------------- | ---------------------------------- | -------------------------------------------------------------------------------------------- |
| `catalog`                          | 0 个点，通常先尝试搜索域           | `catalog.study.svc.cluster.local`，随后可能继续其他后缀                                      |
| `catalog.study`                    | 1 个点，仍可能先扩展搜索域         | 先有 `catalog.study.study.svc.cluster.local`，之后可能尝试 `catalog.study.svc.cluster.local` |
| `catalog.study.svc.cluster.local`  | 4 个点，小于 5，可能仍先走搜索列表 | 可能先查询追加 `.study.svc.cluster.local` 的候选，再尝试原名称的绝对形式                     |
| `catalog.study.svc.cluster.local.` | 末尾根点号明确绝对名称             | 不再追加搜索域；仍可能涉及 A/AAAA、重试和缓存等差异                                          |

`ndots:5` 不限制查询次数；名称即便写全，也可能先走搜索扩展。`192.0.2.53` 是文档示例地址，排查时应读取源 Pod 的实际配置。[Linux resolv.conf 的 search / ndots 语义](https://man7.org/linux/man-pages/man5/resolv.conf.5.html)

`dnsPolicy` 决定配置来源。在本章 Linux 范围，`hostNetwork: true` 且需要集群 DNS 时，应显式使用 `dnsPolicy: ClusterFirstWithHostNet`；只写 ClusterFirst 会退回 Default 的行为。Default 继承节点解析配置，不会自动指向集群 DNS。普通 Pod 常用 ClusterFirst，也不保证外部域名或业务网络必然可达。[1.28 Pod DNS 策略](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/dns-pod-service.md)

排查时读取源 Pod 的实际配置，确认 DNS 入口和搜索域，再分析请求路径。

## 6. Corefile 中几个常见职责

Corefile 是 CoreDNS 配置。先认识各插件的职责，再对照实际配置：

- `kubernetes` 处理配置范围内的 Kubernetes 服务发现记录。
- `forward` 可以把适用查询转发到配置的上游解析器。
- `cache` 缓存 DNS 结果，减少重复查询，但缓存也意味着变化不总是立即被客户端观察到。

这些插件共同组织名称解析，实际 Corefile 要结合插件版本与环境配置核对。上游可能是企业 DNS；DNS 出口也可能受网络策略和防火墙约束。外部域名失败只说明转发链路有问题，集群内服务发现可能正常。

转发与缓存的行为和可配置项见 [forward 文档](https://coredns.io/plugins/forward/)与 [cache 文档](https://coredns.io/plugins/cache/)，修改前按目标版本核对。

## 7. 排障先区分返回码与连接阶段

[![DNS 排查：先按失败类型划分边界](/assets/notes/kubernetes/k8s-dns-triage.svg)](/assets/notes/kubernetes/k8s-dns-triage.svg)

常见现象可以这样组织证据：

| 现象                 | 优先核对                                     | 不能立即下的结论               |
| -------------------- | -------------------------------------------- | ------------------------------ |
| NXDOMAIN             | 名称、命名空间、对象是否存在、查询范围       | 一定是网络不通                 |
| SERVFAIL             | DNS 处理失败、对象同步、插件与上游等         | 一定要删除 CoreDNS Pod         |
| 查询超时             | DNS 入口、端点、协议与网络策略、服务处理情况 | 一定是服务名拼错               |
| 已得到地址但连接失败 | 业务端口、后端就绪、Service、Pod 网络与应用  | DNS 解析成功就证明全链路没问题 |

这张表是定位起点，不涵盖所有根因。排查时先记录错误发生在哪个源 Pod：节点终端查询成功，说明不了 Pod 内的解析路径正常。

例如：拼错命名空间后查询一个不存在的完整名称，可能得到 NXDOMAIN，这不是“网络完全不通”；对象同步或上游处理异常可能出现 SERVFAIL，应查处理链和日志；超时可能是源 Pod 到 DNS 入口被策略阻断，也可能是服务处理迟缓；已经得到 ClusterIP 却无法连接时，则要对照端口、端点、就绪与数据平面。以上是教学线索，重启 CoreDNS 前还要有对应的日志和查询证据。

CoreDNS Pod 处于 Running 只说明容器在运行；`kube-dns` Service 存在同样不代表源 Pod 的查询路径可用。节点终端与业务 Pod 的 nameserver、搜索域和网络策略可能不同。

以下是授权环境中常见的查询模板。`kube-dns` 与标签要以实际部署为准；权限不足不等于 DNS 服务故障。

```bash
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n kube-system 限定命名空间
kubectl get service kube-dns -n kube-system
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n kube-system 限定命名空间
# -l kubernetes.io/service-name=kube-dns 按标签选择对象，不是按名称匹配
kubectl get endpointslice -n kube-system -l kubernetes.io/service-name=kube-dns
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n kube-system 限定命名空间
kubectl get pods -n kube-system
```

若要进一步检查 Pod 内的解析配置或发起 DNS 查询，需要已有合适的诊断环境、工具和权限。诊断工具是否存在与 DNS 是否正常是两个检查项：缺少 nslookup 等命令时，应选择已有诊断环境继续验证。

### 7.1 用 catalog 对照 DNS 与业务连接 {#catalog-dns-test}

复用[第十二章共用清单](/articles/kubernetes-api-yaml-labels.html#catalog-lab)的 `study/catalog` 和 `dns-debug`，不重复部署。诊断镜像为 `busybox:1.36.1`，包含本例使用的 nslookup、wget 和 cat；需有 exec 权限、诊断容器仍在运行，后端已 Ready。集群域假定为 `cluster.local`，不同配置必须调整名称。以下命令均未在本次修订中执行。

```bash
# 在指定 Pod 的容器中执行 -- 后面的命令；-c 选择容器，-- 之后的参数传给容器内程序
# cat 读取容器内指定文件，用于核对挂载或启动时配置
# -n study 限定命名空间
kubectl exec dns-debug -n study -- cat /etc/resolv.conf
# 在指定 Pod 的容器中执行 -- 后面的命令；-c 选择容器，-- 之后的参数传给容器内程序
# nslookup 查询后面的名称，用于检查容器内 DNS 解析
# -n study 限定命名空间
kubectl exec dns-debug -n study -- nslookup catalog.study.svc.cluster.local
# 用 kubectl 查询对象字段并保存到 SERVICE_IP；-o jsonpath 只提取表达式指定的值，供后续请求使用
SERVICE_IP=$(kubectl get svc catalog -n study -o jsonpath='{.spec.clusterIP}')
# 在指定 Pod 的容器中执行 -- 后面的命令；-c 选择容器，-- 之后的参数传给容器内程序
# wget -qO- 将 HTTP 响应写到标准输出，-T 5 设置超时秒数；URL 用于对比 Pod、Service 或 DNS 路径
# -n study 限定命名空间
kubectl exec dns-debug -n study -- wget -qO- -T 5 "http://$SERVICE_IP:80"
# 在指定 Pod 的容器中执行 -- 后面的命令；-c 选择容器，-- 之后的参数传给容器内程序
# wget -qO- 将 HTTP 响应写到标准输出，-T 5 设置超时秒数；URL 用于对比 Pod、Service 或 DNS 路径
# -n study 限定命名空间
kubectl exec dns-debug -n study -- wget -qO- -T 5 http://catalog.study.svc.cluster.local:80
```

先核对实际 nameserver/search，再看查询结果；本例 IPv4 环境预期得到 Service 的 A 记录，地址应与实际 ClusterIP 对应。两个 HTTP 请求在条件满足时预期返回 `catalog`。DNS 工具的输出格式、查询类型和错误文字随版本变化，本章不给出固定模拟输出；一次查询成功也不等于业务验收通过。

| DNS 查询 | Service IP 连接 | 优先分析方向                                          |
| -------- | --------------- | ----------------------------------------------------- |
| 失败     | 成功            | 源 Pod DNS 配置与查询路径；还需区分名称、返回码和超时 |
| 成功     | 失败            | Service、端点、策略、Pod 网络和应用连接               |
| 失败     | 失败            | 可能有公共网络故障或多个问题，分别收集证据            |
| 成功     | 成功            | 此次基础解析与连接正常，不覆盖其他端口、后端或客户端  |

HTTP 访问与显式查询使用的缓存和调用时机可能不同，这张表是定位线索，不是根因判定。实验结束后执行 `kubectl delete namespace study` 清理全部专用资源；若还要继续第十二章的在线验证，完成后再清理。

## 8. 本章小结

名称解析把名字换成地址，服务转发把地址换成后端，Pod 网络把包真正送到——三层依次依赖，但不是同一件事。控制平面与常见节点组件至此串成一条线索：状态经 API 协调，kubelet 借助运行时运行容器，网络机制支持连接，服务与 DNS 帮客户端找到并访问后端。后续把这些原理落到资源清单、日常管理、权限与排查。

[返回本册目录](/collections/kubernetes/)
