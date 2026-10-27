---
id: kubernetes-service-endpointslice
title: 第十九章 Service 与 EndpointSlice 资源实践
description: Service 的 selector 通常选择同命名空间中具有匹配标签的 Pod。它不要求 Pod 一定来自 Deployment，也不通过 Deployment 的名字找到后端。
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
order: 19
---

# 第十九章 Service 与 EndpointSlice 资源实践

> 第十章介绍节点转发机制，本章专注资源字段与选择关系。Kubernetes 1.28 背景；清单和查询均未提交或执行。

## 1. 先准备被选择的后端

Service 的 selector 通常选择同命名空间中具有匹配标签的 Pod。它不要求 Pod 一定来自 Deployment，也不通过 Deployment 的名字找到后端。

如果 Service 在 study，Pod 在另一个命名空间，即使标签完全一样，也不会被这个普通 selector 自动纳入。标签匹配采用所列要求的组合，Pod 可以还有额外标签。

[![Service：port与targetPort映射](/assets/notes/kubernetes/k8s-service-ports-detail.png)](/assets/notes/kubernetes/k8s-service-ports-detail.png)

## 2. 一个最小端口例子

新增教学清单：假设后端 Pod 具有 `app: catalog` 标签，应用实际监听 TCP 8080。未创建这些对象。

```yaml
apiVersion: v1
kind: Service
metadata:
  name: catalog
  namespace: study
spec:
  type: ClusterIP
  selector:
    app: catalog
  ports:
    - name: http
      protocol: TCP
      port: 80
      targetPort: 8080
```

客户端访问 Service 的 80，目标是后端的 8080。Pod 的 `containerPort` 只是相应端口声明，不负责让应用真正监听。应用只监听 127.0.0.1 时，另一个 Pod 访问其 Pod IP 可能仍失败。

targetPort 也可引用命名端口，但名字必须与所选后端的实际端口定义对应。多端口 Service 要给端口恰当命名，并逐项核对协议和目标。

## 3. EndpointSlice 让后端信息独立变化

Service 描述逻辑入口，端点资源描述地址、端口与条件。普通有 selector 的路径通常由相关控制器维护端点；没有 selector 时，需要按使用场景管理端点，不能假定平台会自动发现外部地址。

EndpointSlice 并非 Pod 对象的完整副本。一个 Service 可以对应多个 Slice，因此不能按“对象名必须等于 Service 名”查找全部后端，而应使用 `kubernetes.io/service-name` 标签等关联信息。

传统 Endpoints 对象仍有历史用途；1.28 学习不应只依赖其同名关系。读取 Slice 时，进一步查看每个 endpoint 的 conditions：

| 字段        | 本章普通 Pod 后端的解释              | 缺省时怎样读                                        |
| ----------- | ------------------------------------ | --------------------------------------------------- |
| terminating | Pod 已有删除时间戳，处于终止过程     | 1.28 类型约定按未终止解释                           |
| serving     | 对应 Pod 的 Ready 状态，包括终止期间 | 1.28 类型约定缺省时参考 ready，不直接套用新版本文字 |
| ready       | 默认要求 serving 且没有 terminating  | 未知状态通常按可就绪解释，不能当作实际健康证明      |

对标准控制器生成的普通 Pod 端点，可用下式理解：

```text
serving     = Pod Ready
terminating = Pod deletionTimestamp 存在
ready       = Service publishNotReadyAddresses
              OR (serving AND NOT terminating)
```

例如 `ready: false, serving: true, terminating: true` 表示端点正在退出，但 Pod 仍就绪。启用 publishNotReadyAddresses 会使这里的 ready 为 true，即使应用本身未就绪；因此不能只凭 ready 判断应用健康，也不应将该选项当成普通故障修复开关。

公式依据 [v1.28.0 EndpointSlice 控制器实现](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/endpointslice/utils.go)，缺省字段依据 [v1.28.0 EndpointConditions 类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/discovery/v1/types.go)。手工管理端点还需确认管理者怎样设置这些条件；数据平面、流量策略与已有连接继续决定具体流量走向。

## 4. 类型表示入口意图，不保证底层已准备

| 情形         | 入口特点                         | 还需要核对                             |
| ------------ | -------------------------------- | -------------------------------------- |
| ClusterIP    | 集群逻辑地址                     | 数据平面与路由，不能当作外部安全边界   |
| NodePort     | 在适用节点地址与分配端口提供入口 | 地址选择、流量策略、防火墙与底层网络   |
| LoadBalancer | 请求适用的外部负载均衡集成       | 云或其他实现、权限、地址分配和后端健康 |
| ExternalName | DNS 别名语义                     | 别名目标、协议主机名与证书             |
| Headless     | 不分配普通 ClusterIP             | 端点发现与客户端如何使用返回地址       |

Headless 是 `clusterIP: None` 等条件形成的行为，不是一个叫 Headless 的 `type` 值。LoadBalancer 也不等于“平台自动替你购买并配置所有外网资源”。

`externalTrafficPolicy`、`internalTrafficPolicy` 等字段会改变适用流量的端点选择与源地址行为。尤其 Local 条件下，无本地合格端点的节点不能按“任意节点都会转到远端”理解。

## 5. 不可达时按关系逐层核对

```bash
kubectl get svc catalog -n study -o yaml
kubectl get pods -n study -l app=catalog -o wide
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
```

先确认标签与命名空间，再看就绪、端口与端点条件。随后比较服务名、Service IP 和 Pod IP 的访问证据，必要时才进入节点规则层。

服务没有端点时，为 Service 重建地址通常无法修复错误的 Pod 标签。即使端点存在，应用不监听的问题也不能靠 DNS 记录解决。排查时，应明确每条证据对应的层次。

## 6. 删除和变更的影响

Service 与工作负载通常独立存在，删除 Deployment 不自动删除相关 Service。重新创建 Service 可能改变地址或分配端口，客户端缓存也可能继续使用旧值。

因此，不能把删除重建视为无害刷新。变更前应记录地址、端口、流量策略和外部依赖，变更后则验证真实客户端的访问路径，不能只确认 YAML 已保存。

[catalog 案例：标签、命名端口与后端](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
