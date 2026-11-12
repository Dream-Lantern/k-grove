---
id: kubernetes-ingress
title: 第二十章 Ingress 与 HTTP 入口路由
description: "Ingress 对象声明适用的 HTTP/HTTPS 路由；Ingress Controller 观察并实现这些规则。只创建一个 Ingress 对象，不会自动安装一个能接外部流量的代理。"
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
order: 20
---

# 第二十章 Ingress 与 HTTP 入口路由

> 本章以 Kubernetes 1.28 的 networking.k8s.io/v1 为背景，说明规则、控制器和入口地址的配合。清单使用教学名称，控制器扩展需按实现版本单独核对。

## 1. 规则、控制器与入口地址

Ingress（入口路由）是声明 HTTP/HTTPS 路由的 API 对象，不是实际代理服务器；Ingress Controller（入口控制器）观察并实现这些规则。只创建一个 Ingress 对象，不会自动安装一个能接外部流量的代理。

外部 DNS、负载均衡或节点入口仍需相应的基础设施支持。控制器可以作为 Pod 运行，但入口如何暴露取决于部署方式，不能只根据“它在哪个节点”，就认定外部一定能直接连接该节点的某个端口。

[![Ingress：规则不是控制器本身](/assets/notes/kubernetes/k8s-ingress-boundaries.svg)](/assets/notes/kubernetes/k8s-ingress-boundaries.svg)

图中的 Service 是规则后端引用。某些控制器直接使用端点地址转发，不要求每个业务数据包都先经过 ClusterIP；不要把声明上的依赖画成唯一的实际包路径。

控制关系可理解为 Ingress → ingressClassName 引用 IngressClass（入口类）→ 与该类 spec.controller 对应的 Controller → 配置代理数据平面。业务客户端则经外部 DNS、LoadBalancer 或其他入口访问代理，再被转发到适用后端；Controller 通常不在每个请求的数据路径上。

study-controller 只是教学类名，必须存在实际 IngressClass 和对应运行中的 Controller。未指定 ingressClassName 时，是否采用默认类、是否处理无类对象，取决于默认类设置及实现配置。这里不创建虚构的 Controller 标识，也不假定已安装任何入口实现。[1.28 IngressClass 与控制器](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/ingress.md)

## 2. Host 与 Path 选择哪一个后端

以下完整清单保存为 `catalog-ingress.yaml`，假设 study 中已有 catalog 和 catalog-admin 两个 Service，各暴露 TCP 80 且有可用后端。catalog.example.com 是教学域名。清单未提交，暂不引用 TLS Secret，便于先独立验证 HTTP：

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: catalog
  namespace: study
spec:
  ingressClassName: study-controller
  rules:
    - host: catalog.example.com
      http:
        paths:
          - path: /api
            pathType: Prefix
            backend:
              service:
                name: catalog
                port:
                  number: 80
          - path: /api/admin
            pathType: Prefix
            backend:
              service:
                name: catalog-admin
                port:
                  number: 80
          - path: /api
            pathType: Exact
            backend:
              service:
                name: catalog-admin
                port:
                  number: 80
```

`study-controller` 需要相应 IngressClass 和实现；`catalog` Service 需要在适用命名空间存在。入口路由到 Service 80，不等于后端应用必须也监听 80。

客户端的 Host、DNS 解析与入口地址需要一致。仅用 IP 访问一个按域名分流的入口，可能落入其他规则或默认后端，这不自动证明网络故障。

## 3. 三种 pathType

| 类型                   | 匹配规则               | 例子                                   |
| ---------------------- | ---------------------- | -------------------------------------- |
| Exact                  | 路径精确匹配           | /foo 不等于 /foo/                      |
| Prefix                 | 按路径元素进行前缀匹配 | /foo 可匹配 /foo/bar，但不匹配 /foobar |
| ImplementationSpecific | 由相应实现定义         | 必须查控制器文档                       |

Prefix 按路径元素匹配，规则 `/foo/` 可以匹配 `/foo`，也可匹配 `/foo/bar`，但不能匹配 `/foobar`。存在多个匹配时，要按标准的最长匹配与 Exact 优先等规则理解。[1.28 Ingress 路径定义与例子](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/ingress.md)

在 Host=catalog.example.com 的前提下，本章规则得到以下匹配结果；不按 YAML 中书写的先后顺序简单挑第一项：

| 请求路径         | 匹配结果                                            | 后端             |
| ---------------- | --------------------------------------------------- | ---------------- |
| /api             | Prefix /api 和 Exact /api 均匹配，同长时 Exact 优先 | catalog-admin:80 |
| /api/items       | Prefix /api                                         | catalog:80       |
| /apix            | 不匹配 Prefix /api，且没有其他匹配项                | 按入口默认处理   |
| /api/admin       | 两条 Prefix 均匹配，更长 /api/admin 优先            | catalog-admin:80 |
| /api/admin/users | 更长 Prefix /api/admin                              | catalog-admin:80 |
| /API/items       | 大小写不同，不匹配 /api                             | 按入口默认处理   |

[![Ingress Host/Path：Exact 优先、较长 Prefix 优先及未匹配路径](/assets/notes/kubernetes/k8s-ingress-host-path-match.svg)](/assets/notes/kubernetes/k8s-ingress-host-path-match.svg)

正则表达式不属于所有 Prefix 规则的通用能力。控制器是否支持正则、如何开启、与 pathType 如何组合，都属于实现和版本条件。

Prefix 只判断选择哪条路由。例如 /api/users 匹配 /api，不代表后端收到的路径自动变为 /users。Rewrite（路径重写）需要具体 Controller 的实现与配置，不是标准 Ingress 对任意控制器的统一保证。本文不加入私有重写注解，后端需能处理原路径。

## 4. TLS 与扩展注解

TLS（Transport Layer Security，传输层安全协议）证书需要与入口使用的名字匹配，并由相应配置引用。入口终止 TLS 不表示到后端的每一段连接都会自动继续使用 TLS；这是另一项部署和信任条件。

在具备受信任、域名匹配的测试证书后，才把下面局部字段加入 Ingress spec；它不是独立清单。本次没有创建或读取证书、私钥或 Secret：

```yaml
tls:
  - hosts:
      - catalog.example.com
    secretName: catalog-tls
```

catalog-tls 应是 Ingress 所在 study 命名空间的适用 TLS Secret，包含证书和私钥。Secret 存在不等于证书未过期、证书链受信任或域名匹配；证书签发、续期与信任须独立管理。不要把真实私钥放进公开笔记。

SNI（Server Name Indication，服务器名称指示）位于 TLS 握手，用于选择适用证书；HTTP Host 位于后续 HTTP 请求，用于规则匹配。二者属于不同协议层。通常在入口解密，再通过 HTTP 转发本例 8080 后端；如需入口至后端 HTTPS，还必须另行配置实现支持与信任链。

上传大小、重写、跳转等注解通常是控制器扩展，键名不能随意混用。旧的 class 注解与 `ingressClassName` 也不能仅因名字相似就当作可互换配置。

本文清单采用标准字段；控制器注解属于具体实现，需要单独核对。实施前核对控制器的安装版本、维护状态和兼容要求。

## 5. 按入口路径定位

先核对客户端名称与地址，再看 IngressClass、规则是否被控制器接受、入口服务是否暴露、后端 Service 与端点是否可用。

```bash
kubectl get ingress,ingressclass -A
kubectl describe ingress catalog -n study
kubectl get svc,endpointslice -n study
```

HTTP 404、502、503 可能来自不同组件，需要结合响应特征与控制器日志判断。不能将状态码直接对应为唯一根因，否则可能混淆默认后端、应用路由和上游连接等不同环节的故障。

### 5.1 补齐测试后端与入口前提

需要已安装、与 Kubernetes 1.28 兼容的实际 Controller、对应 IngressClass、可达入口地址及专用 study。先完成[第十九章实验 A](/articles/kubernetes-service-endpointslice.html#_5-1-实验-a-正常后端与访问)，暂不清理其 catalog Deployment/Service；若此前已清理，则重新按该节创建。不要覆盖其他实验或生产对象，整个练习均未在集群执行。

第二个后端保存为 `catalog-admin.yaml`。固定版本 busybox:1.36.1 实际监听 8080，标签 app=catalog-admin，避免与 catalog 的 Service 相互混选：

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog-admin
  namespace: study
spec:
  replicas: 1
  selector:
    matchLabels:
      app: catalog-admin
  template:
    metadata:
      labels:
        app: catalog-admin
    spec:
      containers:
        - name: app
          image: busybox:1.36.1
          command: ["sh", "-ec"]
          args:
            - |
              mkdir -p /www/api/admin
              printf 'catalog-admin api\n' > /www/api/index.html
              printf 'catalog-admin panel\n' > /www/api/admin/index.html
              exec httpd -f -p 8080 -h /www
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /api/admin/
              port: http
---
apiVersion: v1
kind: Service
metadata:
  name: catalog-admin
  namespace: study
spec:
  selector:
    app: catalog-admin
  ports:
    - name: http
      protocol: TCP
      port: 80
      targetPort: http
```

检查真实类的 spec.controller，并从该实现的安装记录确定 Controller 命名空间、Pod 和版本，不能凭教学类名猜部署名。下列 CONTROLLER_NAMESPACE、CONTROLLER_POD 需替换，不是已知存在的资源：

```bash
kubectl get ingressclass study-controller -o yaml
kubectl get pods -n CONTROLLER_NAMESPACE -o wide
kubectl describe pod CONTROLLER_POD -n CONTROLLER_NAMESPACE
kubectl apply -f catalog-admin.yaml
kubectl rollout status deployment/catalog-admin -n study --timeout=180s
kubectl get svc catalog catalog-admin -n study
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog-admin -o yaml
kubectl apply -f catalog-ingress.yaml
kubectl get ingress catalog -n study -o wide
kubectl describe ingress catalog -n study
```

两组 Service 应有各自合格端点；Controller 必须接受规则且入口实际可达后，再测外部请求。Ingress 的 ADDRESS 是否填写及格式也依实现，不能只用空或非空字段判断入口一定可用。

### 5.2 HTTP 与 HTTPS 分别验证

下面 INGRESS_ADDRESS 是占位符，需要实际可访问的入口地址，可能由 LB、NodePort 或其他方式提供，不能任意换成某个 Node IP。使用 NodePort 时还需加入实际端口。curl -i 同时显示响应头，便于区分入口响应与应用响应：

```bash
curl -i -H 'Host: catalog.example.com' http://INGRESS_ADDRESS/api
curl -i -H 'Host: catalog.example.com' http://INGRESS_ADDRESS/api/items
curl -i -H 'Host: catalog.example.com' http://INGRESS_ADDRESS/api/admin/
curl -i -H 'Host: catalog.example.com' http://INGRESS_ADDRESS/apix
```

预期 /api 选择 catalog-admin，/api/items 返回 catalog items，/api/admin/ 返回 catalog-admin panel；/apix 按默认后端或未匹配策略处理，不预设所有实现的固定响应码。本例静态 httpd 访问目录 /api 时可能返回重定向到 /api/；这是后端应用行为，跟随后路径改变又会重新匹配 Ingress，不能把最终页面当作原请求 Exact 优先的证明。应结合响应头与 Controller 的路由日志检查，避免误以为 Prefix 自动 Rewrite。

HTTPS 必须先满足第四节的 TLS Secret、证书域名、信任链与入口监听条件。若这些条件未提供，完整 HTTPS 验证尚未成立。具备条件后可用 --resolve 指定入口 IP，同时保留 URL 域名供 SNI、HTTP Host 与证书校验使用；INGRESS_IP 需要替换为实际入口 IP：

```bash
curl -i --resolve catalog.example.com:443:INGRESS_IP https://catalog.example.com/api/items
# 使用专用测试 CA 时，需替换为已信任的测试 CA 文件
curl -i --cacert TEST_CA_PEM --resolve catalog.example.com:443:INGRESS_IP https://catalog.example.com/api/items
```

不默认使用 -k 绕过校验。仅在 HTTPS 请求上手工改 Host 头，并不能替代正确的 SNI 与证书匹配验证。

### 5.3 故障分层与清理

| 现象                          | 优先检查                                          |
| ----------------------------- | ------------------------------------------------- |
| 域名解析失败                  | 外部 DNS，先区分入口 IP 与域名                    |
| 入口地址不可达                | LB、NodePort、入口监听、防火墙与网络              |
| 404                           | Host/Path、默认后端、应用路由及响应来源           |
| 502/503                       | Controller 配置、后端就绪、连接与代理实现         |
| TLS 证书错误                  | SNI、域名、证书期限、链与 Secret 引用             |
| Service 可达而 Ingress 不可用 | IngressClass、Controller 接受状态、规则和入口路径 |

这些只是取证方向，不是状态码与根因的一一对应。必要时读取目标 Controller 日志，结合 Service 与 EndpointSlice 判断，不把重启 Controller 当作默认处理。

以下 delete 仅用于自己创建的本章资源；借用的第十九章后端和客户端应按该章清理，Controller、IngressClass 和外部提供的 TLS Secret 不在本章清理范围：

```bash
kubectl delete -f catalog-ingress.yaml
kubectl delete -f catalog-admin.yaml
```

Ingress 负责适用的入口路由。用户登录、业务权限、应用限流和网络访问约束仍需要相应机制，不能因为外面有一个入口代理就省略。

入口和后端关系清楚后，下一章学习 [ConfigMap 与 Secret](/articles/kubernetes-configmap-secret.html)如何把配置交付给应用。

[返回本册目录](/collections/kubernetes/)
