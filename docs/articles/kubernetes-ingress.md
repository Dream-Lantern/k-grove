---
id: kubernetes-ingress
title: 第二十章 Ingress 与 HTTP 入口路由
description: Ingress 对象声明适用的 HTTP/HTTPS 路由；Ingress Controller 观察并实现这些规则。只创建一个 Ingress 对象，不会自动安装一个能接外部流量的代理。
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
order: 20
---

# 第二十章 Ingress 与 HTTP 入口路由

> 以 Kubernetes 1.28 的 networking.k8s.io/v1 为背景。区分标准规则与控制器扩展，不安装任何 Ingress Controller，不复制原笔记里的真实域名或发布元数据。

## 1. 规则、控制器与入口地址

Ingress 对象声明适用的 HTTP/HTTPS 路由；Ingress Controller 观察并实现这些规则。只创建一个 Ingress 对象，不会自动安装一个能接外部流量的代理。

外部 DNS、负载均衡或节点入口仍需相应的基础设施支持。控制器可以作为 Pod 运行，但入口如何暴露取决于部署方式，不能只根据“它在哪个节点”，就认定外部一定能直接连接该节点的某个端口。

![外部入口、Ingress Controller、Service 后端与应用的职责](/assets/notes/kubernetes/k8s-ingress-boundaries.svg)

图中的 Service 是规则后端引用。某些控制器直接使用端点地址转发，不要求每个业务数据包都先经过 ClusterIP；不要把声明上的依赖画成唯一的实际包路径。

## 2. Host 与 Path 选择哪一个后端

新增教学清单，所有名字与域名均为示例，未提交：

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
```

`study-controller` 需要相应 IngressClass 和实现；`catalog` Service 需要在适用命名空间存在。入口路由到 Service 80，不等于后端应用必须也监听 80。

客户端的 Host、DNS 解析与入口地址需要一致。仅用 IP 访问一个按域名分流的入口，可能落入其他规则或默认后端，这不自动证明网络故障。

## 3. 三种 pathType

| 类型                   | 匹配规则               | 例子                                   |
| ---------------------- | ---------------------- | -------------------------------------- |
| Exact                  | 路径精确匹配           | /foo 不等于 /foo/                      |
| Prefix                 | 按路径元素进行前缀匹配 | /foo 可匹配 /foo/bar，但不匹配 /foobar |
| ImplementationSpecific | 由相应实现定义         | 必须查控制器文档                       |

Prefix 不是任意字符串前缀，末尾斜杠也不能按原笔记中的说法机械区分：规则 `/foo/` 可以匹配 `/foo`。存在多个匹配时，要按标准的最长匹配与 Exact 优先等规则理解。[1.28 Ingress 路径定义与例子](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/ingress.md)

正则表达式不属于所有 Prefix 规则的通用能力。控制器是否支持正则、如何开启、与 pathType 如何组合，都属于实现和版本条件。

## 4. TLS 与扩展注解

TLS 证书需要与入口使用的名字匹配，并由相应配置引用。入口终止 TLS 不表示到后端的每一段连接都会自动继续使用 TLS；这是另一项部署和信任条件。

上传大小、重写、跳转等注解通常是控制器扩展，键名不能随意混用。旧的 class 注解与 `ingressClassName` 也不能仅因名字相似就当作可互换配置。

本章保留标准清单，不把某个控制器的全部注解当成 Kubernetes 通用字段。控制器的安装版本、维护状态和兼容要求需要在真正实施前另行核对，本文没有选型或部署承诺。

## 5. 按入口路径定位

先核对客户端名称与地址，再看 IngressClass、规则是否被控制器接受、入口服务是否暴露、后端 Service 与端点是否可用。

```bash
kubectl get ingress,ingressclass -A
kubectl describe ingress catalog -n study
kubectl get svc,endpointslice -n study
```

命令未执行。HTTP 404、502、503 可能来自不同组件，需要结合响应特征与控制器日志判断。不能将状态码直接对应为唯一根因，否则可能混淆默认后端、应用路由和上游连接等不同环节的故障。

Ingress 负责适用的入口路由。用户登录、业务权限、应用限流和网络访问约束仍需要相应机制，不能因为外面有一个入口代理就省略。

[返回本册目录](/collections/kubernetes/)
