---
id: kubernetes-api-server
title: 第三章：kube-apiserver——请求如何变成集群状态？
description: "运行一次 kubectl get pods 和提交一份 Deployment，看起来都只是访问 API Server，后续工作却不一样：前者读取对象，后者改变期望状态，随后还可能触发多个控制循环。"
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
order: 3
---

# 第三章：kube-apiserver——请求如何变成集群状态？

运行一次 `kubectl get pods` 和提交一份 Deployment，看起来都只是访问 API Server，后续工作却不一样：前者读取对象，后者改变期望状态，随后还可能触发多个控制循环。

这一章把三件事分开：**请求能否进入、对象能否保存，以及保存以后谁继续工作。** 原理以 Kubernetes 1.28 已具备的基础 API 机制为学习范围；不把主线文档后来增加的缓存优化或 API 特性写成当年默认行为。

## 1. API Server 的职责与请求类型 {#_1-api-server-管什么-不管什么}

kube-apiserver 提供 Kubernetes HTTP API。用户、控制器、调度器和 kubelet 可以基于各自权限读取或修改 API 对象。

它负责处理连接、请求身份、权限、准入和对象访问等问题，但不是将所有请求同步转发给工作节点的通用网关。应用的普通 HTTP 请求也不需要经过它。

可以用一个对照帮助理解：

| 请求                 | API Server 的主要工作  | 后续是否一定调度 Pod？           |
| -------------------- | ---------------------- | -------------------------------- |
| 查询某命名空间的 Pod | 按权限返回相应对象信息 | 否                               |
| 创建 ConfigMap       | 处理并保存相应配置对象 | 否                               |
| 创建 Deployment      | 处理并保存工作负载期望 | 后续控制器可能创建需要调度的 Pod |
| 更新 Pod 状态        | 处理对应状态子资源请求 | 不等于重新创建或调度这个 Pod     |

因此，“每种资源都有一个同步请求处理控制器”不是准确的理解。[Kubernetes API 概念](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/api-concepts.md)

## 2. 先区分 TLS、认证、授权和准入

[![API 写请求：逐层识别访问边界](/assets/notes/kubernetes/k8s-api-request-boundaries.png)](/assets/notes/kubernetes/k8s-api-request-boundaries.png)

这是普通写请求的高层模型，省略了解码、默认化、具体 REST 处理和其他内部步骤。读取、聚合 API、连接型请求等路径不能机械套用所有框。

### 2.1 TLS：保护连接，不自动授予操作权限

客户端需要按配置校验 API Server 的服务端身份，并保护传输。使用 HTTPS 不能直接推导出“每个客户端都必须持有一张客户端证书”。

客户端证书是认证方式之一。Bearer Token 等机制也可能用于识别调用者；是否启用及怎样校验由集群配置决定。TLS 保护连接，客户端身份由启用的认证机制确认。

不要为绕过证书错误，直接把跳过 TLS 校验当作正常使用方式。证书的可信来源、API 地址和时间等问题应该分别检查。

### 2.2 认证：你是谁？

认证关注调用者身份。例如，一份 kubeconfig 可以指明客户端使用哪种认证材料。

认证得到调用者身份，授权再决定其操作范围。同一个 API Server 对不同身份可以作出不同授权决定；学习 1.28 的认证配置时，应使用该版本实际支持的机制，而非照搬历史 Basic Authentication 配置。

### 2.3 授权：你能对什么做什么？

授权判断调用者能否执行某个动作。动作通常与资源、动词、命名空间及子资源等范围有关；RBAC 是常见的授权机制之一。

“能列出 Pod”与“能创建 Deployment”是两种权限；“能访问某个命名空间”也不等于有权读取其中所有敏感对象。

### 2.4 准入：这次资源操作是否满足集群规则？

对于适用的请求，准入可以修改对象或根据策略拒绝请求。Mutating 与 Validating 的角色不同，Webhook 也不能替代身份认证和 RBAC。

普通读取请求并不会每次都经过完整的写入准入流程。架构图中的阶段用于说明边界，并不是所有 HTTP 请求共用的固定调用栈。[访问控制与准入](https://kubernetes.io/docs/concepts/security/controlling-access/)

## 3. API 对象怎样保存，又怎样被观察？

在常见内置资源路径中，API Server 处理通过检查的状态变更，并使用配置好的存储后端保存对象。etcd 是标准控制平面的关键状态存储，但不是所有用户、控制器和节点都直接操作它。

**标准控制平面组件主要经 API Server 访问 Kubernetes API 状态；管理员和备份工具在受控条件下也可能直接访问 etcd。** 这是 API 数据的正常访问路径与管理操作之间的区别。

不能由此开放 etcd 给普通客户端。直接读写其内部数据会绕开 Kubernetes API 的处理边界，并且可能破坏系统状态。

还要区分对象持久存储与应用持久数据：创建一个数据库 Pod，不意味着数据库文件由 API Server 写入 etcd。业务数据的卷、备份和恢复仍由应用及存储方案负责。

## 4. Watch 与组件的独立观察 {#_4-watch-不是-etcd-回调下一个组件}

假设用户创建了 Deployment。相关控制器需要知道新的期望，Scheduler 之后也需要知道是否出现未绑定 Pod。

常见客户端使用 list/watch 等机制建立和持续更新对象视图。Watch 关注的是对象变化，不是 API Server 为每个控制器安排一串可靠的远程函数回调。

[![API 状态：观察与写回走向](/assets/notes/kubernetes/k8s-api-observe-state.svg)](/assets/notes/kubernetes/k8s-api-observe-state.svg)

图中“观察”和“写入”方向分开；各组件独立推进，省略断线、重试和响应。控制器之间的协调依赖对象与状态，并不要求前一个组件同步调用下一个组件。

### 4.1 resourceVersion 用来协调观察，不是业务时间戳

对象或集合的 `resourceVersion` 帮助客户端处理相应版本与变化观察。客户端应按 API 约定使用，不把它转换成墙上时钟，也不把内部存储实现当作可随意做加减的永久业务契约。

### 4.2 Watch 断开后还需要恢复观察

连接可能断开，服务器保存的历史也可能不足。客户端必须能处理重新建立观察、必要的重新列举及重复触发等情况。

因此，“注册了 Watch”并不意味着“永远不会漏掉状态更新、恰好处理一次每个事件”。对控制器而言，恢复后能根据当前状态重新协调，往往比依赖某一次通知更重要。[1.28 API 的观察与版本约定](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/api-concepts.md)

## 5. Deployment 创建后的协调流程 {#_5-创建-deployment-的请求-为什么不能直接等同于创建容器}

沿用第一章的三副本教学例子：

1. 客户端提交 Deployment，API Server 处理并保存对象。
2. Deployment Controller 观察到需要协调的状态，创建或调整 ReplicaSet。
3. ReplicaSet Controller 经 API 协调 Pod 数量。
4. Scheduler 发现需要调度的 Pod，选择节点并推进绑定。
5. 目标节点上的 kubelet 配合运行时等机制推进运行，继续上报状态。

这不是每次 API 请求都必须完整走完的调用链，也不是 ReplicationController 创建 ReplicaSet 的流程。RC 与 ReplicaSet Controller 是不同控制器，后文单独介绍。

成功保存 Deployment 的响应，不能证明镜像已经拉取、Pod 已经就绪或 Service 已经可访问。将“API 操作成功”与“业务目标达成”分开，能避免很多排障误判。[Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

## 6. 读取请求与已观察状态 {#_6-为什么-get-pod-列表-不需要启动一个-pod-控制器}

读取对象的请求由相应 API 处理路径完成，不是让 Pod 控制器临时向所有节点收集进程，再同步返回。

API 状态也是已经观察、更新并保存的状态表示，不能把某个时刻返回的 JSON 理解成每个节点在同一物理时刻的实时快照。列表、单对象读取和 Watch 有各自语义；缓存及存储读取行为还与版本和请求条件有关。

这一章不把后续版本的读取优化反向套给 1.28，也不承诺“每个 GET 都直接触发一次 etcd 全集群读取”。要分析这些实现细节，需要固定版本和具体请求。

## 7. 日常观察：命令回答的是哪一个问题？

下面的命令分别观察客户端上下文、资源种类、对象状态与授权结果：

```bash
kubectl config current-context
kubectl api-resources
kubectl get deployments -n default
kubectl get pods -n default -o wide
kubectl auth can-i list pods -n default
```

- `current-context`：先确认正在查看哪个客户端上下文，不能仅凭窗口名称猜集群。
- `api-resources`：帮助认识服务器可提供的资源种类，不证明当前用户能操作所有资源。
- `get`：查看相应资源状态，不能替代应用健康和访问测试。
- `auth can-i`：检查指定动作的授权判断；不是执行该动作，也不证明后续准入或调度必然成功。

`default` 只是示例命名空间；有权限和作用域限制时，结果可能不同。不公开输出真实 kubeconfig、令牌或敏感对象。

## 8. 从错误阶段判断下一步，而不是一律重启 API Server

| 现象                        | 优先区分的边界                             |
| --------------------------- | ------------------------------------------ |
| 连接或证书错误              | API 地址、网络、服务端证书信任与连接配置   |
| 身份无法被接受              | 认证材料、有效期及认证配置                 |
| 动作被禁止                  | 授权范围、命名空间、资源与子资源           |
| 对象被策略拒绝              | 准入规则、Webhook、对象校验及配额          |
| API 操作成功但 Pod 无法运行 | 控制器、调度、运行时、镜像、网络及存储     |
| API 普遍延迟或失败          | 请求负载、存储后端、控制平面资源与相关日志 |

表格给出的是定位顺序，并不表示故障根因已经确认。不同代理和认证配置还可能改变返回形式，因此不能只凭一个状态码就执行修复脚本。

这一章的关键是：API Server 让组件围绕统一对象协作，但不会把独立控制循环变成一条同步安装流水线。

[返回本册目录](/collections/kubernetes/)
