---
id: kubernetes-service-endpointslice
title: 第十九章 Service 与 EndpointSlice 资源实践
description: "Service 的 selector 通常选择同命名空间中具有匹配标签的 Pod。它不要求 Pod 一定来自 Deployment，也不通过 Deployment 的名字找到后端。"
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

Service（服务）提供逻辑访问入口，其 selector（选择器）通常选择同命名空间中具有匹配标签的 Pod。它不要求 Pod 一定来自 Deployment，也不通过 Deployment 的名字找到后端。

如果 Service 在 study，Pod 在另一个命名空间，即使标签完全一样，也不会被这个普通 selector 自动纳入。标签匹配采用所列要求的组合，Pod 可以还有额外标签。

[![Service：port与targetPort映射](/assets/notes/kubernetes/k8s-service-ports-detail.png)](/assets/notes/kubernetes/k8s-service-ports-detail.png)

## 2. 一个最小端口例子

以下保存为 `catalog-service.yaml`，包含完整 Deployment 与 Service。使用固定版本 busybox:1.36.1，httpd 实际监听 0.0.0.0:8080，提供静态页面及就绪文件。它不是附录 B 的业务程序，也不声称业务依赖健康；本次未拉取镜像或创建资源。

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog
  namespace: study
spec:
  replicas: 2
  selector:
    matchLabels:
      app: catalog
  template:
    metadata:
      labels:
        app: catalog
    spec:
      containers:
        - name: app
          image: busybox:1.36.1
          command: ["sh", "-ec"]
          args:
            - |
              mkdir -p /www/api
              printf 'catalog root\n' > /www/index.html
              printf 'catalog api\n' > /www/api/index.html
              printf 'catalog items\n' > /www/api/items
              printf 'catalog users\n' > /www/api/users
              printf 'ready\n' > /www/ready
              exec httpd -f -p 8080 -h /www
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /ready
              port: http
            periodSeconds: 2
---
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
      targetPort: http
```

客户端访问 Service 的 80，目标是后端的 8080。Pod 的 `containerPort` 只是相应端口声明，不负责让应用真正监听。应用只监听 127.0.0.1 时，另一个 Pod 访问其 Pod IP 可能仍失败。

数字 targetPort=8080 直接指定目标端口；本例 targetPort=http 则解析所选 Pod 中名字为 http、协议匹配的容器端口。Service 的 ports[].name 和容器的 ports[].name 是两个不同字段，前者并不因为名字相同就自动完成映射，是 targetPort 的引用建立了关联。多端口 Service 应逐项核对名称、协议与目标。

新旧 Pod 可以都把端口命名为 http，却分别监听 8080、8081；标准控制器需要把解析出的不同目标端口放进不同 EndpointSlice 的端口组，因为一个 Slice 的 ports 适用于其中所有端点。命名端口允许这种迁移，但应用也必须实际在各自端口监听。[1.28 EndpointSlice 端口分组](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/endpoint-slices.md)

## 3. EndpointSlice 让后端信息独立变化

Service 描述逻辑入口，EndpointSlice（端点切片）描述后端地址、端口与条件。普通有 selector 的路径通常由 EndpointSlice Controller（端点切片控制器）维护；用户不需要逐个手工创建每个 Pod 的端点。

典型控制关系是 Deployment → ReplicaSet → Pod 的标签与就绪状态，再由 EndpointSlice Controller 结合另一项输入 Service selector，维护 EndpointSlice → 供 kube-proxy 或其他 Service 数据平面消费。这是状态协调路径，不是每个业务数据包都要经过 Controller。

EndpointSlice 并非 Pod 对象的完整副本。一个 Service 可以对应多个 Slice，因此不能按“对象名必须等于 Service 名”查找全部后端，而应使用 `kubernetes.io/service-name` 标签等关联信息。

同时查看 `endpointslice.kubernetes.io/managed-by`，区分标准控制器和其他管理者；标准控制器通常使用 endpointslice-controller.k8s.io。不要只取第一个 Slice 就认定已看到全部后端。

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

下表限定标准控制器管理的普通 Pod 后端，且 publishNotReadyAddresses=false：

| Pod 情况           | serving | terminating | ready |
| ------------------ | ------- | ----------- | ----- |
| 正常 Ready         | true    | false       | true  |
| 未就绪             | false   | false       | false |
| 正在终止但仍 Ready | true    | true        | false |
| 正在终止且不 Ready | false   | true        | false |

如果 Service spec 设置以下字段，ready 可被置为 true，即使 serving=false；该字段用于特定发现需求，不能代替修复探针或应用：

```yaml
publishNotReadyAddresses: true
```

[![Pod 状态到 EndpointSlice 条件，再传播到数据平面](/assets/notes/kubernetes/k8s-endpointslice-condition-flow.svg)](/assets/notes/kubernetes/k8s-endpointslice-condition-flow.svg)

EndpointSlice 改变不代表所有节点转发规则立即同步，已有连接与新连接可能表现不同。终止中 serving=true 也不是完成业务排空的证明；具体是否选择终止端点，还取决于数据平面及流量策略。

公式依据 [v1.28.0 EndpointSlice 控制器实现](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/endpointslice/utils.go)，缺省字段依据 [v1.28.0 EndpointConditions 类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/discovery/v1/types.go)。手工管理端点还需确认管理者怎样设置这些条件；数据平面、流量策略与已有连接继续决定具体流量走向。

没有 selector 的 Service 也是合法资源，但标准控制器不会按 Pod 标签自动生成后端，需用户或其他控制器管理 EndpointSlice，正确设置 Service 关联标签、端口与管理者。不能把 Service ClusterIP 直接用作它自己的后端地址。对于非 Pod 后端，API Server 不允许把任意外部端点当作 Pod 代理，`kubectl port-forward service/...` 也不能据此成为通用调试路径。[1.28 无选择器 Service 的限制](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/service.md)

## 4. Service 类型与基础设施条件 {#_4-类型表示入口意图-不保证底层已准备}

| 情形         | 入口特点                         | 还需要核对                             |
| ------------ | -------------------------------- | -------------------------------------- |
| ClusterIP    | 集群逻辑地址                     | 数据平面与路由，不能当作外部安全边界   |
| NodePort     | 在适用节点地址与分配端口提供入口 | 地址选择、流量策略、防火墙与底层网络   |
| LoadBalancer | 请求适用的外部负载均衡集成       | 云或其他实现、权限、地址分配和后端健康 |
| ExternalName | DNS 别名语义                     | 别名目标、协议主机名与证书             |
| Headless     | 不分配普通 ClusterIP             | 端点发现与客户端如何使用返回地址       |

Headless 是 `clusterIP: None` 等条件形成的行为，不是一个叫 Headless 的 `type` 值。LoadBalancer 也不等于“平台自动替你购买并配置所有外网资源”。

ExternalName 返回适用的 DNS CNAME（规范名称别名），不为目标创建普通 Service VIP（虚拟 IP）代理后端。ClusterIP 也不是通用安全边界，不能替代网络策略与应用认证。

`externalTrafficPolicy`、`internalTrafficPolicy` 等字段会改变适用流量的端点选择与源地址行为。尤其 Local 条件下，无本地合格端点的节点不能按“任意节点都会转到远端”理解。

例如 NodePort/LoadBalancer Service 设置 externalTrafficPolicy=Local：节点 A 有合格本地后端，节点 B 没有，则 A 可以按本地路径处理外部请求，B 不应被假设自动转发给 A，可能丢弃适用流量；实际外部负载均衡还需将请求发往健康入口。终止端点等细节依实现与策略判断，不把所有状态简化成相同结果。本章完整实验使用 ClusterIP，不直接应用这项外部策略。

## 5. 不可达时按关系逐层核对

```bash
kubectl get svc catalog -n study -o yaml
kubectl get pods -n study -l app=catalog -o wide
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
```

先确认标签与命名空间，再看就绪、端口与端点条件。随后比较服务名、Service IP 和 Pod IP 的访问证据，必要时才进入节点规则层。

标签与命名空间决定后端选择，就绪条件影响端点状态，应用监听决定目标端口能否响应。将访问证据对应到这些层次，再处理相应配置。

### 5.1 实验 A：正常后端与访问

需要能拉取 busybox:1.36.1 的 Linux 1.28 隔离集群、正常 CNI/集群 DNS/Service 数据平面及相应创建权限。使用全新专用 study；若已有前章 catalog 或其他资源，另选名称并同步修改全部 YAML 和命令，避免覆盖。以下均为未执行步骤，create/apply/run/delete 会修改实验资源：

```bash
kubectl create namespace study
kubectl apply -f catalog-service.yaml
kubectl rollout status deployment/catalog -n study --timeout=180s
kubectl get pods -n study -l app=catalog -o wide
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
kubectl run catalog-client -n study --image=busybox:1.36.1 --restart=Never --command -- sleep 3600
kubectl wait pod/catalog-client -n study --for=condition=Ready --timeout=120s
kubectl exec catalog-client -n study -- wget -qO- -T 5 http://catalog/
CATALOG_SERVICE_IP=$(kubectl get svc catalog -n study -o jsonpath='{.spec.clusterIP}')
kubectl exec catalog-client -n study -- wget -qO- -T 5 "http://$CATALOG_SERVICE_IP/"
```

预期两个 Pod Ready，Slice 中有相应地址、TCP 8080 和 ready=true。DNS 与 Service IP 两条查询均预期返回 catalog root。Slice 数量和名称不是固定值；如果失败，分别检查客户端运行、DNS、网络策略、数据平面和应用监听，不能只因 Service 对象存在就宣布成功。

### 5.2 实验 B：Selector 不匹配

仅在上述专用实验中修改 Service selector，不改真实生产标签。merge 补丁会改变资源：

```bash
kubectl patch service catalog -n study --type=merge -p '{"spec":{"selector":{"app":"catalog-missing"}}}'
kubectl get svc catalog -n study -o yaml
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
kubectl exec catalog-client -n study -- wget -qO- -T 5 http://catalog/
# 恢复选择器
kubectl patch service catalog -n study --type=merge -p '{"spec":{"selector":{"app":"catalog"}}}'
```

待控制器同步后，没有匹配后端，可能保留空 Slice，不能要求所有 Slice 对象消失。请求预期失败或超时，具体表现依数据平面，不预设固定错误码。恢复后再次检查两个就绪端点与访问；不要在变更尚未传播时把旧结果当新状态。

### 5.3 实验 C：只让一个后端未 Ready

先确认实验 A 已恢复，选择其中一个 catalog Pod 的实际名称替换 POD_NAME。以下只移除这个实验容器的就绪文件，业务页面仍在，readiness 失败不会触发 liveness 重启：

```bash
kubectl exec POD_NAME -n study -c app -- rm /www/ready
kubectl get pods -n study -l app=catalog -o wide
kubectl describe pod POD_NAME -n study
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
kubectl exec catalog-client -n study -- wget -qO- -T 5 http://catalog/
# 恢复本实验的就绪文件
kubectl exec POD_NAME -n study -c app -- sh -c 'printf "ready\n" > /www/ready'
```

预期探针累计失败后一个 Pod Ready=False，其端点 serving=false、terminating=false、ready=false；另一个仍就绪。普通新 Service 请求在状态传播后应使用合格后端，但已有连接和传播期间不保证无损。只把一个端点变得未就绪，并不表示整个 Service 都不可用。恢复文件后等待探针和 Slice 同步，再重复访问检查。

若 Pod 已被替换，先按新对象重新核对状态，不向旧名称盲目执行恢复。清理只针对自己创建的资源，不删除整个命名空间：

```bash
kubectl delete pod catalog-client -n study
kubectl delete -f catalog-service.yaml
```

## 6. 删除和变更的影响

Service 与工作负载通常独立存在，删除 Deployment 不自动删除相关 Service。重新创建 Service 可能改变地址或分配端口，客户端缓存也可能继续使用旧值。

变更前记录地址、端口、流量策略和外部依赖，变更后验证真实客户端的访问路径；删除重建也需评估地址变化与缓存影响。

Service 后端关系明确后，下一章通过 [Ingress](/articles/kubernetes-ingress.html)把 HTTP Host/Path 路由到适用的 Service。

[catalog 案例：标签、命名端口与后端](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
