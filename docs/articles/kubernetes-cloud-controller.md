---
id: kubernetes-cloud-controller
title: 第三十三章 Cloud Controller Manager 与云集成
description: "Kubernetes 描述 Node、Service 等期望对象，但实际云主机、路由和负载均衡由云平台管理。Cloud Controller Manager（CCM）把适用的云厂商集成职责与核心控制循环分开。"
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
order: 33
---

# 第三十三章 Cloud Controller Manager 与云集成

> 本章以 Kubernetes 1.28 的架构职责为背景，说明 Cloud Controller Manager 如何协调云侧节点、路由与负载均衡；具体提供者的配置需单独核对。

## 1. 为什么把云接口单独抽出来

Kubernetes 描述 Node、Service 等期望对象，但实际云主机、路由和负载均衡由云平台管理。Cloud Controller Manager（云控制器管理器，CCM）把适用的云厂商集成职责与核心控制循环分开。

CCM 观察相关对象，按云提供者实现和权限调用云接口，再更新相应状态。它不是业务数据包逐次经过的代理，也不等于每种环境都必须安装的通用组件。裸机集群可以采用其他网络与入口实现。

[![云集成：网络与存储分别协调](/assets/notes/kubernetes/k8s-cloud-boundaries.svg)](/assets/notes/kubernetes/k8s-cloud-boundaries.svg)

### 外部 CCM 如何初始化新 Node

本节是假设已有匹配云提供者的 **1.28 外部 CCM 模式**，不是所有环境通用的启动参数。官方部署说明要求结合该模式核对 kubelet、kube-apiserver、kube-controller-manager 的 `--cloud-provider=external` 配置；不要在使用内置云控制循环或无云提供者的环境无条件复制。

| 组件                    | 外部模式中的配置含义                                                           |
| ----------------------- | ------------------------------------------------------------------------------ |
| kubelet                 | 使用 external 路线，注册 Node 时标记需要外部云初始化                           |
| kube-controller-manager | 切换对应云控制循环的责任，避免与外部实现重复管理；迁移期卷设置另核对           |
| kube-apiserver          | 按 1.28 外部模式核对云提供者参数及相关配置，不把它当作实际执行节点初始化的组件 |
| 外部 CCM 自身           | 按厂商文档配置实际云提供者、凭据和控制器；不能将其提供者名也机械改为 external  |

合成案例：新云主机 node-b 上的 kubelet 以 external 模式加入集群。主要职责链如下，配置发生在节点注册之前：

```text
配置 external 模式 → kubelet 注册 Node
  → 带 node.cloudprovider.kubernetes.io/uninitialized:NoSchedule 初始化污点
  → 外部 CCM 的 Node Controller 查询云实例信息
  → 协调 ProviderID、区域/可用区标签、地址等适用云元数据
  → 完成适用的云初始化并解除初始化污点
  → 满足 Ready、其他污点和资源等条件后，可正常调度普通工作负载
```

污点 Key 为 `node.cloudprovider.kubernetes.io/uninitialized`，效果为 NoSchedule，kubelet 实现还设置值 true。没有对应容忍的普通工作负载会受阻；CCM 等引导组件需要适当容忍与部署设计。CCM 不可用或云 API 失败时，新节点可能一直停在这里，但这不是所有 Node 故障的统一原因。

流程按职责概括，不承诺所有元数据字段在同一个 API 写入中完成。v1.28.0 实现将 ProviderID/标签变更与移除污点协调，再更新节点地址；不能把“污点消失”当作所有地址和业务网络都已验证完成。[1.28 外部 CCM 部署说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/administer-cluster/running-cloud-controller.md)、[kubelet 注册状态](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/kubelet/kubelet_node_status.go)、[云 Node Controller](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/cloud-provider/controllers/node/node_controller.go)。

未执行的只读查询模板，用于对比初始化污点、providerID、标签、地址和事件：

```bash
kubectl get node node-b -o yaml
kubectl describe node node-b
```

## 2. 三类常见职责

节点相关控制用于把适用的云侧信息与 Node 状态协调；路由相关控制按网络方案处理所需云路由；服务相关控制可为 LoadBalancer Service 协调云侧负载均衡。

这些能力取决于提供者和部署方式，不能认为每个 CCM 都以同样方式完成全部任务。云接口限额、权限和异步资源创建也会影响协调结果。

| 控制器             | 职责                                        | 适用结果                                          |
| ------------------ | ------------------------------------------- | ------------------------------------------------- |
| Node Controller    | 从云实例信息协调 Node 元数据                | spec.providerID、地址、实例类型、区域与可用区标签 |
| Route Controller   | 按云网络方案协调路由                        | 适用的节点间 Pod 网络路由                         |
| Service Controller | 观察 LoadBalancer Service，调用云提供者接口 | 云负载均衡资源及 Service 的适用外部地址状态       |

节点职责还包括检查云实例是否存在；在确认云端已删除实例的适用情况下，可删除对应 Kubernetes Node 对象。有些实现将这部分拆为 Cloud Node Lifecycle Controller，不应把 Node NotReady 直接等同于云主机已删除。[1.28 职责说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/architecture/cloud-controller.md)、[v1.28.0 节点生命周期实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/cloud-provider/controllers/nodelifecycle/node_lifecycle_controller.go)。

### 路由管理与数据平面的分工

| 组件                                             | 职责                                                        |
| ------------------------------------------------ | ----------------------------------------------------------- |
| CCM Route Controller                             | 适用的云侧路由协调                                          |
| CNI（Container Network Interface，容器网络接口） | Pod 网络配置与连接                                          |
| kube-proxy                                       | 按实现设置 Service 流量转发规则；部分网络实现有替代数据平面 |
| 云负载均衡器                                     | 云侧入口流量分发与适用健康检查                              |

某些云网络通过云路由实现跨节点 Pod 通信；覆盖网络等 CNI 方案未必需要相同的云路由机制。是否启用 Route Controller 取决于云提供者与网络方案。CCM 不等于 CNI，也不是每个业务数据包经过的代理。

### LoadBalancer Service 的完整链路

以下为 **合成 Service 示例，未创建**。假定 study 中已有标签 app=catalog、实际监听 8080 的后端，以及支持默认 LoadBalancer 集成的云提供者；不同实现可能需要特定注解或另一类控制器。

```yaml
apiVersion: v1
kind: Service
metadata:
  name: catalog
  namespace: study
spec:
  type: LoadBalancer
  selector:
    app: catalog
  ports:
    - port: 80
      targetPort: 8080
```

1. 用户提交 Service，API Server 接受并保存对象。
2. Service Controller 观察变化；适用的默认云负载均衡实现开始协调。
3. 控制器在创建前添加清理 Finalizer（最终处理标记，防止对象过早彻底删除）。
4. CCM 通过云提供者实现调用云 API，创建或更新对应负载均衡资源。
5. 提供者返回适用状态，控制器更新 `status.loadBalancer`，可能包含外部 IP 或主机名。
6. 云负载均衡器按实现向节点或后端转发；后端选择、健康检查、网络策略和应用响应仍需单独验证。

Service 对象存在不代表云负载均衡器已创建；有外部地址也不证明业务健康。默认共享控制器只处理适用的 LoadBalancer Service，例如设置了 `loadBalancerClass` 时应由对应实现负责，不能假定本例 CCM 一定接管。[v1.28.0 Service Controller](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/cloud-provider/controllers/service/controller.go)

EndpointSlice 的生成与云负载均衡管理是独立职责。对本例带 selector 的 Service，kube-controller-manager 中的 EndpointSlice Controller 跟踪匹配 Pod 并协调端点；CCM Service Controller 管理的是云侧负载均衡与相关状态，不把两者合成一个控制器。[v1.28.0 EndpointSlice Controller](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/controller/endpointslice/endpointslice_controller.go)

故障推演：对象创建成功，但 EXTERNAL-IP 长时间显示 `<pending>`。依次查看以下 **未执行的只读模板**：

```bash
kubectl get svc catalog -n study
kubectl describe svc catalog -n study
kubectl get events -n study --sort-by=.lastTimestamp
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog
```

先按 Service UID 和时间关联事件，检查是否有负责它的控制器、CCM 运行与日志，再核对云 API 身份权限、配额、子网/网络配置、厂商注解及云端创建错误。CCM 的命名空间和 Pod 名取决于安装方式，应确认后再查询日志。不要打印云凭据，也不要把“无外部地址”直接归因于 kube-proxy；若已创建但业务不通，再检查入口、端点与后端健康。

## 3. 云存储与 CSI 的独立集成路径 {#_3-原架构图中的存储要拆出来}

集群依赖的云网络与云存储各有集成路径。CCM 主要承担适用的云控制职责，卷供应与挂载需要结合存储机制分析。

CSI（Container Storage Interface，容器存储接口）把存储操作交给匹配的驱动。CSI Controller 服务与节点插件分别承担控制面和节点侧职责，并由相应控制器、sidecar 与 kubelet 协调，不是 CCM 直接调用 CSI 的固定链路。

以下是采用动态供给云盘的职责示意，省略重试和厂商细节；静态 PV 或不需附加的存储不会完整走同一条链：

```text
PVC 引用 StorageClass → 到达适用供给时机（可能等待首个消费者）
  → external-provisioner 调用 CSI Controller 创建云盘
  → 形成 PV 并完成 PVC/PV 绑定
  → 需要附加时，经相关控制器与 CSI Controller 完成节点附加
  → kubelet 调用 CSI Node Plugin 完成适用的暂存与发布挂载
  → 容器访问预期挂载路径 → 应用读写与数据一致性另行验收
```

云盘创建不是 CCM 的统一职责。驱动使用的云凭据、资源权限和回收策略应独立核对。PV/PVC 正常、挂载成功、应用能读写是不同验收层次；备份、一致性与数据保留也需要独立设计。

同理，外部 DNS 的记录管理不总由 CCM 自动处理。入口 DNS、负载均衡、Service 后端和证书属于多个边界，某个对象已创建不代表整条路径已经完成。

职责链与本册[持久卷章节](/articles/kubernetes-persistent-volumes.html)衔接；可对照 [1.28 PV 文档](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/persistent-volumes.md)及 [1.28 CSI 介绍](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/storage/volumes.md)理解供给与挂载边界。

## 4. 权限、费用与清理

云 API 权限应限定在必需的资源和操作范围内，并考虑凭据轮换。配置错误的控制循环可能反复调用接口或遗留资源；实施前也应检查 API 限流、配额和费用。

删除 Kubernetes 对象后，云资源是否自动删除，要看提供者、注解、最终处理与保留策略。不能根据 kubectl 列表里已经没有对象就断言云端已无资源或费用。

### LoadBalancer 的清理 Finalizer

标准清理标记是 `service.kubernetes.io/load-balancer-cleanup`。在本例对应的云 Service Controller 路径中，先完成负载均衡清理，再移除该标记，Service 才可彻底删除。它保护清理流程，不保证云 API 永不失败。[v1.28.0 Finalizer 常量](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/cloud-provider/service/helpers/helper.go)与前述 Service Controller 实现。

下面仅是 **已批准退役时的删除命令示例，会删除 Service 并触发适用的云入口清理，本章未执行**，不用于探测故障：

```bash
kubectl delete svc catalog -n study
```

若删除后长期 Terminating，先只读检查 deletionTimestamp、finalizers、事件、CCM 状态和云端资源标识，再检查云 API 可达性、权限、限流、依赖资源和删除错误。控制器会重试，Kubernetes 对象删除与云资源清理可能存在时间差；先确认云侧实际状态，不直接移除 Finalizer 掩盖失败，也不提供强制清理脚本。

网络入口和持久数据尤其需要区分：清理负载均衡与回收云盘是不同风险。清理前应列出准确资源标识与恢复路径，分别确认入口退役和数据保留要求。

最小权限同时涉及访问 Kubernetes API 的 RBAC 与云 API 身份；凭据轮换要核对控制器是否正确重载。云 API 配额、速率限制和重试会影响完成时间。云负载均衡器、公网 IP、云盘可能持续计费，不能只以 Kubernetes 对象消失判断费用停止；外部 DNS 通常由独立组件管理。

| 现象                    | 优先检查                                          |
| ----------------------- | ------------------------------------------------- |
| Node 云初始化未完成     | CCM、初始化污点、云 API 与实例识别                |
| Node 缺少区域标签       | Node Controller、云元数据、更新权限               |
| Pod 跨节点网络异常      | CNI、适用 Route Controller、云路由与策略          |
| LoadBalancer 无外部地址 | 负责该 Service 的控制器、云权限、配额、子网与事件 |
| Service 删除卡住        | Finalizer、CCM 重试与云资源清理结果               |
| PVC 创建失败            | CSI、StorageClass、云存储权限和配额               |

## 5. 回到整个学习路线

对象声明期望，控制器与节点组件持续推进，外部系统承担各自实际能力。云集成也遵循这个分工，诊断时应分别观察 API 状态、云端资源和实际数据路径。

阅读具体教程时，先确认版本、实现与依赖，再看命令。是否运行成功、业务是否正确、数据能否恢复、权限是否合适，都需要分别验证，不能仅凭一张绿色状态截图完成验收。

这三章从设备发现、复杂申领到外部云协作，最终都要回到具体责任边界：

| 组件          | 主要职责                                 |
| ------------- | ---------------------------------------- |
| Device Plugin | 设备发现、扩展资源上报与容器设备访问配置 |
| DRA           | 对应版本的资源申领、设备选择与分配协调   |
| CSI           | 存储供给、适用附加与节点挂载             |
| CNI           | Pod 网络配置与连接                       |
| CCM           | 适用云节点、云路由与云负载均衡管理       |

本章所有云案例都是教学推演，未启动 CCM、调用云 API、创建计费资源或执行删除。

[返回本册目录](/collections/kubernetes/)
