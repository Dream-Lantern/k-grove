---
id: kubernetes-api-server
title: 第三章：kube-apiserver——请求如何变成集群状态？
description: "运行一次 kubectl get pods 和提交一份 Deployment，看起来都只是访问 API Server，后续工作却不一样：前者读取对象，后者改变期望状态，随后还可能触发多个控制循环。"
date: '2026-10-25'
updated: '2026-11-04'
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

它负责处理连接、请求身份、权限、准入和对象访问等问题，但顺序是先建好连接，再认身份、查权限、跑准入，最后才读写对象；它不是将所有请求同步转发给工作节点的通用网关。应用的普通 HTTP 请求也不需要经过它。

可以用一个对照帮助理解：

| 请求                 | API Server 的主要工作  | 后续是否一定调度 Pod？           |
| -------------------- | ---------------------- | -------------------------------- |
| 查询某命名空间的 Pod | 按权限返回相应对象信息 | 否                               |
| 创建 ConfigMap       | 处理并保存相应配置对象 | 否                               |
| 创建 Deployment      | 处理并保存工作负载期望 | 后续控制器可能创建需要调度的 Pod |
| 更新 Pod 状态        | 处理对应状态子资源请求 | 只更新状态，不重建或重新调度     |

因此，“每种资源都有一个同步请求处理控制器”不是准确的理解。[Kubernetes API 概念](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/api-concepts.md)

## 2. 先区分 TLS、认证、授权和准入

[![API 写请求：逐层识别访问边界](/assets/notes/kubernetes/k8s-api-request-boundaries.png)](/assets/notes/kubernetes/k8s-api-request-boundaries.png)

这是普通写请求的高层模型，省略了解码、默认化、具体 REST 处理和其他内部步骤。读取、聚合 API、连接型请求等路径不能机械套用所有框。

### 2.1 TLS：保护连接，不自动授予操作权限

客户端需要按配置校验 API Server 的服务端身份，并保护传输。使用 HTTPS 不能直接推导出“每个客户端都必须持有一张客户端证书”。

客户端证书是认证方式之一。Bearer Token 等机制也可能用于识别调用者；是否启用及怎样校验由集群配置决定。TLS 保护连接，客户端身份由启用的认证机制确认。

为绕过证书错误而跳过 TLS 校验，会把中间人攻击一并放进来。证书的可信来源、API 地址和时间等问题应该分别检查。

### 2.2 认证：你是谁？

认证关注调用者身份。例如，一份 kubeconfig 可以指明客户端使用哪种认证材料。

认证得到调用者身份，授权再决定其操作范围。同一个 API Server 对不同身份可以作出不同授权决定；学习 1.28 的认证配置时，应使用该版本实际支持的机制，而非照搬历史 Basic Authentication 配置。

### 2.3 授权：你能对什么做什么？

授权判断调用者能否执行某个动作。动作通常与资源、动词、命名空间及子资源等范围有关；RBAC 是常见的授权机制之一。

“能列出 Pod”与“能创建 Deployment”是两种权限；“能访问某个命名空间”只覆盖部分资源，敏感对象仍要单独授权。

### 2.4 准入：这次资源操作是否满足集群规则？

对于适用的请求，准入可以修改对象或根据策略拒绝请求。其中 Mutating 负责改：往对象里补默认值、加标签；Validating 只做判断：接受还是拒绝，不改内容。Webhook 与身份认证、RBAC 也是三套彼此独立的机制，其中一个通过不代表另外两个也通过。

普通读取请求并不会每次都经过完整的写入准入流程。架构图中的阶段用于说明边界，并不是所有 HTTP 请求共用的固定调用栈。[访问控制与准入](https://kubernetes.io/docs/concepts/security/controlling-access/)

### 2.5 把边界放进一次 Deployment 创建请求

假设 `kubectl` 首次创建第一章的 `web-demo`。可以按以下问题理解这次普通内置资源写请求：

1. **连接谁？** 客户端建立 TLS 连接并校验 API Server 的证书和身份，随后使用配置的认证材料访问 API。
2. **调用者是谁？** 认证机制识别用户或 ServiceAccount。认证成功不意味着拥有管理员权限。
3. **允许这个动作吗？** 授权机制判断该身份能否在目标命名空间创建 `deployments`。读取 Pod 与这项权限是两回事。
4. **这次操作符合策略吗？** 对适用的写请求，准入插件或 Webhook 可以补充策略字段、检查配额或拒绝不符合规则的对象；有创建权限仍可能被准入拒绝。
5. **对象能否合法保存？** API Server 还会进行解码、版本转换、默认化、字段校验及存储处理。这些工作不能全部归入准入；默认化、修改准入和验证等处理在实现中有各自位置，并非先完整准入再一次性校验。通过检查后，对象才进入持久化路径。
6. **客户端得到什么？** 创建成功响应包含对象信息，表示 API 操作成功；不会等待 Web 容器启动。`kubectl apply` 对已存在对象还可能发起 PATCH，不能一概称为创建请求。
7. **后续谁工作？** 控制器独立观察保存的对象并继续协调。它们可能在客户端收到响应前就已开始观察变化；响应与后续协调没有固定的先后等待关系。

这是帮助理解边界的教学模型，不能当作每种 API 请求的精确源码时序。读取请求不走全部写入阶段，失败请求也不会继续保存。具体实现需固定资源、动词和版本核对。[Kubernetes API 访问控制](https://kubernetes.io/docs/concepts/security/controlling-access/)、[准入控制器](https://kubernetes.io/docs/reference/access-authn-authz/admission-controllers/)

## 3. API 对象怎样保存，又怎样被观察？

在常见内置资源路径中，API Server 处理通过检查的状态变更，并使用配置好的存储后端保存对象。etcd 是标准控制平面的关键状态存储，但不是所有用户、控制器和节点都直接操作它。

**标准控制平面组件主要经 API Server 访问 Kubernetes API 状态；管理员和备份工具在受控条件下也可能直接访问 etcd。** 这是 API 数据的正常访问路径与管理操作之间的区别。

不能由此开放 etcd 给普通客户端。直接读写其内部数据会绕开 Kubernetes API 的处理边界，并且可能破坏系统状态。

还要区分对象持久存储与应用持久数据：创建一个数据库 Pod，不意味着数据库文件由 API Server 写入 etcd。业务数据的卷、备份和恢复仍由应用及存储方案负责。

## 4. Watch 与组件的独立观察 {#_4-watch-不是-etcd-回调下一个组件}

假设用户创建了 Deployment。相关控制器需要知道新的期望，Scheduler 之后也需要知道是否出现未绑定 Pod。

List 是一次性问全量：把某类对象当前有哪些、以及这个列表的版本一起取回来。Watch 则是订阅：告诉 API Server“从这个版本往后，一有变化就推给我”，省掉反复全量查询的开销。常见控制器客户端先 List 建立本地缓存，再通过 Watch 更新缓存、将相关对象加入工作队列。控制循环随后读取当前视图并协调；通知与实际协调并非一对一同步执行。

Watch 关注的是对象变化，不是 API Server 为每个控制器安排一串可靠的远程函数回调，也不是 etcd 直接回调控制器。缓存可能暂时落后，协调逻辑需要允许重试并在重复执行时保持正确。

[![API 状态：观察与写回走向](/assets/notes/kubernetes/k8s-api-observe-state.svg)](/assets/notes/kubernetes/k8s-api-observe-state.svg)

图中“观察”和“写入”方向分开；各组件独立推进，省略断线、重试和响应。控制器之间通过对象与状态衔接，前一个组件不必同步调用下一个。

### 4.1 resourceVersion 用来协调观察，不是业务时间戳

对象的 `metadata.resourceVersion` 表示该对象的资源版本；List 返回的列表也有自己的 `metadata.resourceVersion`，可用作随后观察该集合变化的起点。客户端应把它当作不透明字符串，按 API 约定原样传回；算时间差、推断业务间隔或加减计数都没有意义。具体读取一致性和 Watch 起点取决于请求参数与 API 版本。

### 4.2 Watch 断开后还需要恢复观察

连接可能因超时、代理重置、网络故障或服务端重启而断开；服务器保留的变更历史也有边界。恢复观察需要区分两种情况：

- **普通断线，版本仍可用**：客户端可携带最后处理的 `resourceVersion` 重建 Watch，继续接收后续变化。不是每次断线都必须先全量 List；实际策略由 API 语义和客户端实现决定。
- **版本过旧，历史不可用**：API Server 会以 HTTP `410 Gone` 或 Watch 流中的相应错误事件告知版本过期。客户端应丢弃失效的缓存视图，重新 List 获取集合与新版本，再从新版本恢复 Watch；不能继续依赖旧状态假装观察未中断。

因此，注册 Watch 只建立通知通道，漏事件与重复处理仍要由客户端处理。对控制器而言，恢复后能根据当前状态重新协调，往往比依赖某一次通知更重要。[1.28 API 的观察与版本约定](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/api-concepts.md)

例如，断线期间某个 Pod 被删除，随后控制器重新 List 得到的只是当前集合，不一定能重放此前所有中间事件。它仍应根据“当前副本不足”推进创建替代 Pod，而不是永远等待那一次删除通知。List/Watch 帮助恢复状态视图，控制循环负责让当前状态接近期望。

### 4.3 动手观察 ConfigMap 的变化

前提：已安装与集群版本兼容的 `kubectl`，上下文正确，具备创建命名空间及其中 ConfigMap 的增删改查、List/Watch 权限。使用两个 Bash 终端，均连接同一集群。`k8s-api-demo` 必须是本实验新建的专用空间；若同名空间已存在，请换名并同步修改命令。

终端 A 创建对象，读取其数据和版本，再开启 Watch：

```bash
# 创建命令中指定的实验命名空间；它是后续资源的作用范围
kubectl create namespace k8s-api-demo
# 创建命令中指定的资源；--dry-run 时仅生成或校验请求，需区分是否实际落库
# -n k8s-api-demo 限定命名空间
kubectl create configmap watch-demo -n k8s-api-demo --from-literal=message=hello
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n k8s-api-demo 限定命名空间
# -o yaml 输出完整对象字段，便于核对 spec 与 status
kubectl get configmap watch-demo -n k8s-api-demo -o yaml
# 查询事件记录；--field-selector 按对象字段过滤，--sort-by 按指定字段排序，便于梳理时间线
# -n k8s-api-demo 限定命名空间
# -o yaml 输出完整对象字段，便于核对 spec 与 status
kubectl get configmap watch-demo -n k8s-api-demo --watch --output-watch-events -o yaml
```

普通 `get` 返回当前可读到的对象；最后一条命令先输出当前对象再持续观察。因使用了 `--output-watch-events`，输出包装为事件对象，`type` 表示事件类型，ConfigMap 位于 `object` 字段。初始输出只是当前状态，不代表刚刚又创建了一次对象。

保持终端 A 运行，在终端 B 修改数据并重新读取：

```bash
# 局部修改指定资源；--type=json 按 JSON Patch 操作列表修改，--type=merge 按对象合并
# -n k8s-api-demo 限定命名空间
kubectl patch configmap watch-demo -n k8s-api-demo --type=merge -p '{"data":{"message":"updated"}}'
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n k8s-api-demo 限定命名空间
# -o yaml 输出完整对象字段，便于核对 spec 与 status
kubectl get configmap watch-demo -n k8s-api-demo -o yaml
```

预期终端 A 观察到 `MODIFIED`，其中 `object.data.message` 变为 `updated`，`object.metadata.resourceVersion` 与修改前不同；终端 B 的普通读取也能看到新值和版本。版本的具体数字不固定，不能要求它恰好增加 1。本实验说明 API 对象的变化可被观察，不证明任何应用已重新读取配置，也不验证 410 恢复逻辑。

最后在终端 B 删除 ConfigMap，预期终端 A 可看到 `DELETED`；按 `Ctrl+C` 停止观察，再删除专用空间：

```bash
# 删除命令中明确指定的实验资源；-f 表示按该清单标识删除，不能当作只读检查
# -n k8s-api-demo 限定命名空间
kubectl delete configmap watch-demo -n k8s-api-demo
# 删除命令中明确指定的实验资源；-f 表示按该清单标识删除，不能当作只读检查
kubectl delete namespace k8s-api-demo
```

若观察已中断，“没有看到通知”只说明通道断了；重新读取对象确认当前状态，再检查客户端连接与错误。客户端库的完整重连与缓存恢复逻辑不由这个交互式命令实验代替。[kubectl get 的观察选项](https://kubernetes.io/docs/reference/kubectl/generated/kubectl_get/)

## 5. Deployment 创建后的协调流程 {#_5-创建-deployment-的请求-为什么不能直接等同于创建容器}

第一章已经解释了[Deployment → ReplicaSet → Pod 的协调过程](/articles/kubernetes-architecture.html#_7-一次-deployment-部署-实际上经历了什么)。本章只需把它接回观察机制：Deployment Controller 看到新的 Deployment，写出一个 ReplicaSet；ReplicaSet Controller 看到副本不够，写出 Pod；Scheduler 看到这些 Pod 还没有节点，挑好节点写回绑定结果；目标节点上的 kubelet 看到 Pod 分给了自己，才把它变成运行中的容器。四者都是通过 API 观察各自关心的对象，再按职责写回，它们依赖持续更新的状态视图协作，不需要 API Server 同步串行调用。

成功保存 Deployment 的响应，不能证明镜像已经拉取、Pod 已经就绪或 Service 已经可访问。将“API 操作成功”与“业务目标达成”分开，能避免很多排障误判。[Deployment](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)

## 6. 读取请求与已观察状态 {#_6-为什么-get-pod-列表-不需要启动一个-pod-控制器}

读取对象的请求由相应 API 处理路径完成，不是让 Pod 控制器临时向所有节点收集进程，再同步返回。

API 状态也是已经观察、更新并保存的状态表示，不能把某个时刻返回的 JSON 理解成每个节点在同一物理时刻的实时快照。列表、单对象读取和 Watch 有各自语义；缓存及存储读取行为还与版本和请求条件有关。

这一章不把后续版本的读取优化反向套给 1.28，也不承诺“每个 GET 都直接触发一次 etcd 全集群读取”。要分析这些实现细节，需要固定版本和具体请求。

## 7. 日常观察：命令回答的是哪一个问题？

下面的命令分别观察客户端上下文、资源种类、对象状态与授权结果：

```bash
# 查看当前 kubectl 上下文，确认后续命令将连接哪个集群；此命令不切换上下文
kubectl config current-context
# 查询当前 API Server 提供的资源类型、简称和作用域，确认目标版本实际支持哪些资源
kubectl api-resources
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n default 限定命名空间
kubectl get deployments -n default
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n default 限定命名空间
# -o wide 展示节点、IP 等扩展列
kubectl get pods -n default -o wide
# 检查当前或 --as 指定身份是否获准执行后面的动词与资源操作；结果是授权判断，不实际执行该操作
# -n default 限定命名空间
kubectl auth can-i list pods -n default
```

- `current-context`：先确认正在查看哪个客户端上下文；窗口名称不足以判断集群。
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
