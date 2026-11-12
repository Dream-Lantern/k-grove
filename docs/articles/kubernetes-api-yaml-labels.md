---
id: kubernetes-api-yaml-labels
title: 第十二章 API 对象、YAML 与标签选择
description: "介绍 Kubernetes API 对象、YAML 映射与列表、模板标签和选择器，结合 Deployment 清单理解字段层级与校验。"
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
order: 12
---

# 第十二章 API 对象、YAML 与标签选择

> 面向 Kubernetes 1.28 的资源阅读基础。以下清单均为新增教学示例，未提交到集群。API 版本、对象结构和标签关系理解清楚后，再读具体工作负载。

## 1. 清单中的对象身份与期望状态 {#_1-一份清单在描述什么}

Kubernetes 把集群中的管理对象通过 API 暴露出来。Pod、Service、Deployment 是不同的资源类型；每个对象有名字、所属范围及相应字段。清单常用 YAML 编写，提交后由服务端按 API 定义处理。

`apiVersion` 决定采用哪个 API 组和版本，`kind` 指出对象种类，`metadata` 描述身份和标签，`spec` 通常描述期望。`status` 是组件报告的观察结果，编写创建清单时通常不复制已有对象的 status、UID 和 resourceVersion。

Schema（模式定义）规定对象允许的字段、类型和相关约束，例如 `replicas` 是整数、`containers` 是列表。并非所有资源都有完全相同的 `spec/status` 结构；YAML 也只是常见清单格式，API 还支持 JSON 等表示。看懂缩进后，仍需按对应 API Schema 判断字段是否放对位置。[Kubernetes 1.28 API 对象](https://github.com/kubernetes/website/blob/release-1.28/content/en/docs/concepts/overview/working-with-objects/_index.md)

`apiVersion: v1` 是核心组的表达；Deployment 通常使用 `apps/v1`。不要给所有对象都填同一个版本。版本名字中的 alpha、beta、稳定版表示演进阶段，不能把“beta 一般不会弃用”当成兼容承诺。升级前仍要核对被移除的 API 和迁移路径。

API 资源存在集群级与命名空间级范围。Namespace 能组织 Pod、Service 等资源，但 Node、PV、ClusterRole 等不属于某一个 Namespace。名字相同不代表跨范围是同一个对象。

## 2. YAML 的映射、列表与多文档

下面的 Deployment 同时用于第十、十一章的 `catalog` 实验，保存为 `deployment.yaml`。它用固定标签 `busybox:1.36.1` 启动 TCP 8080 上的简单 HTTP 服务，镜像仍需由实验节点实际获取。原笔记中的 `registry.example.com/study/catalog:DEMO` 是教学占位，不能当成真实可拉取的发布物。

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog
  namespace: study
  labels:
    team: platform
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
          command: ["sh", "-c"]
          args:
            - |
              mkdir -p /www
              echo catalog > /www/index.html
              exec httpd -f -p 8080 -h /www
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 2
```

`metadata`、`spec` 等字段是映射；`containers`、`ports` 是列表，列表项用 `-` 表示。是否使用 `-` 由字段的数据类型决定，与“下一行有没有缩进”无关。YAML 语法正确，只是第一步，内容还需符合 Kubernetes 对该资源的字段定义。

`---` 分隔 YAML 文档，不表示进入一个嵌套对象。一个文件可以包含多个资源文档。嵌套关系由缩进表达，应使用空格保持一致，避免 Tab。

`|` 表示保留换行的块标量，内容仍是一段字符串。比如 ConfigMap 中的一份应用配置：

```yaml
data:
  app.conf: |
    listen=8080
    log_level=info
```

块内的 `#` 是字符串中的字符，是否是应用配置注释由应用格式决定。字段是数字、布尔值还是字符串也要核对；ConfigMap `data` 的值应为字符串，不能仅靠“YAML 能解析”判断对象有效。

### 2.1 第十～十二章共用实验资源 {#catalog-lab}

仅在隔离学习集群使用。前提是上下文正确，有创建命名空间及其中 Deployment、Service、Pod、读取端点和使用 exec 的权限，节点可调度、资源足够、镜像可获取，Pod 网络正常。示例访问命令使用 IPv4 和集群域 `cluster.local`，自定义集群域需同步调整；不要求实际 ClusterIP 等于第十章的教学 IP。

`study` 必须是本实验新建的专用空间。若已存在且含其他工作，换用新的空间并同步修改清单、命令和 DNS 名称，避免覆盖或清理他人资源。将以下两份资源保存为 `catalog-access.yaml`：

```yaml
apiVersion: v1
kind: Service
metadata:
  name: catalog
  namespace: study
spec:
  selector:
    app: catalog
  ports:
    - name: http
      port: 80
      targetPort: 8080
      protocol: TCP
---
apiVersion: v1
kind: Pod
metadata:
  name: dns-debug
  namespace: study
spec:
  containers:
    - name: tools
      image: busybox:1.36.1
      command: ["sleep", "3600"]
  restartPolicy: Never
```

```bash
kubectl config current-context
kubectl create namespace study
kubectl apply -f deployment.yaml -f catalog-access.yaml
kubectl rollout status deployment/catalog -n study --timeout=120s
kubectl wait --for=condition=Ready pod/dns-debug -n study --timeout=120s
kubectl get deployment,service,pods -n study
```

条件满足时，预期两份应用副本最终 Ready，`dns-debug` 可执行 `nslookup` 和 `wget`。超时应查 Events、镜像、调度及容器状态，不能假定准备完成。诊断容器只休眠一小时，结束后需要在专用空间重新准备诊断环境，不能把工具退出误判为 DNS 故障。

接着完成[第十章三条访问路径](/articles/kubernetes-kube-proxy.html#catalog-access-test)及[第十一章 DNS 对照](/articles/kubernetes-coredns.html#catalog-dns-test)。三章共用同一套资源，不重复创建；全部实验结束后删除专用空间及其资源：

```bash
kubectl delete namespace study
```

上述命令及预期均为文档示例，本次没有提交到 API Server，也没有验证镜像、DNS 或网络运行结果。

## 3. 对象标签、模板标签与选择器 {#_3-三处-labels-作用可能不同}

在 Deployment 示例中，`metadata.labels` 是 Deployment 自己的标签；`spec.template.metadata.labels` 是未来 Pod 的标签。两处不会因为键名相同就自动成为一回事。

`spec.selector` 描述控制器选择的 Pod 范围，必须与模板标签相匹配。Pod 可以拥有更多标签，不要求它的全部标签与选择器完全相等。选择器不是对 Deployment 名字的引用，也不等同于 ownerReferences 所表达的控制关系。

Service 的 selector 通常匹配同一命名空间中的 Pod 标签，而不是 Deployment 对象本身。Deployment 与 Service 可以通过共同的 Pod 标签协作，但仍是彼此独立的资源。

[![Deployment 自身标签、选择器与 Pod 模板](/assets/notes/kubernetes/k8s-deployment-label-relations.svg)](/assets/notes/kubernetes/k8s-deployment-label-relations.svg)

本例 Deployment 自身是 `team=platform`，Pod 模板是 `app=catalog`，两者无需相等。`spec.selector.matchLabels` 必须由模板标签满足；`spec.template.spec.containers` 才是新 Pod 中的容器规格。Service 也用 Pod 的 `app=catalog` 选择后端，不能把 Deployment 名称或自身标签当作隐式关联。

### 3.1 不匹配的模板与不可变选择器

下面只是错误的 Deployment `spec` 片段，不是可执行资源：

```yaml
selector:
  matchLabels:
    app: catalog
template:
  metadata:
    labels:
      app: order
```

模板不满足选择器，不能通过 `apps/v1` Deployment 的相应校验。即使模板原来正确，**`apps/v1` Deployment 的 `spec.selector` 创建后也不可变**；修改 YAML 不意味着可以更新任意字段。不要用直接删除生产 Deployment 来绕过这一限制，应在创建前设计清楚选择范围和迁移安排。[Deployment 选择器约束](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/#label-selector-updates)、[v1.28.0 Deployment 更新校验](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/registry/apps/deployment/strategy.go)

多个 ReplicaSet 或 Deployment 的选择范围意外重叠，还可能导致归属和副本协调问题。标签匹配不等于可以接管已有控制器管理的 Pod；归属与收养的区别见[第五章](/articles/kubernetes-controller-manager.html)。

## 4. 选择器的逻辑

常见等值筛选如 `app=catalog`，集合筛选如 `tier in (api,worker)`。多个以逗号分隔的要求通常按 AND 组合，不能把逗号当 OR。

`matchLabels` 能表达简单等值关系；支持的资源还可以通过 `matchExpressions` 表达集合等条件。不同字段支持的选择器形式不同，例如 Service selector 不是完整的 LabelSelector 表达式对象，不能把 Deployment 的整段 selector 原样粘进去。

节点选择也有自己的入口：`nodeSelector` 位于 Pod 的 spec 中，用来约束节点标签；它不属于 Deployment 自身的顶层 spec。

以三个虚构 Pod 演算，以下不是上节实验的实际输出：

| Pod | app     | tier   | env  |
| --- | ------- | ------ | ---- |
| A   | catalog | api    | prod |
| B   | catalog | worker | prod |
| C   | order   | api    | dev  |

| 选择器                 | 匹配结果 | 原因                        |
| ---------------------- | -------- | --------------------------- |
| `app=catalog`          | A、B     | app 等值匹配                |
| `app=catalog,tier=api` | A        | 两个要求同时成立            |
| `tier in (api,worker)` | A、B、C  | in 要求该标签值属于给定集合 |
| `app=catalog,env=dev`  | 无       | 没有 Pod 同时满足两个条件   |

同一个 LabelSelector（标签选择器）中的多个 `matchLabels`、`matchExpressions` 要求按 AND 组合；`in` 的集合内可以包含多个允许值。Service 的 `spec.selector` 则是键值映射，不接受这套 `matchExpressions` 结构。[标签选择器语义](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/)

下面的只读查询示例，结果取决于实际 Pod 标签；共用实验只设置了 `app=catalog`，没有设置 `tier/env`，不能期待它自动产生虚构 A、B、C 的筛选结果：

```bash
kubectl get pods -n study --show-labels
kubectl get pods -n study -l app=catalog
kubectl get pods -n study -l app=catalog,tier=api
kubectl get pods -n study -l 'tier in (api,worker)'
kubectl get pods -n study -l app=catalog,env=dev
kubectl get nodes --show-labels
```

`kubectl label` 会修改服务端对象，不是“重开终端就失效”的临时设置；它以后是否被覆盖，取决于控制器和配置管理方式。`kubectl edit` 同样是修改在线对象，也不会自动更新你的 Git 配置。最终应让团队采用的声明式源与在线状态保持一致。

## 5. 从帮助到校验

目标环境的 API 和资源文档可用于确认字段类型、位置与说明：

```bash
kubectl api-resources
kubectl explain deployment.spec.template
kubectl explain pod.spec.containers
```

这些是查询模板，仍需先确认上下文和权限。客户端 dry-run 进行本地处理，某些发现或校验也可能需要与集群交互；服务端 dry-run 会发送请求，经过适用校验与准入，但不持久化目标资源。

对保存好的 `deployment.yaml`，可在有权限的测试 API Server 上请求服务端 Dry-run（试运行）：

```bash
kubectl apply --dry-run=server -f deployment.yaml
```

它仍向 API Server 发送请求，需要与正常操作相应的权限；目标命名空间也需已存在。适用准入会参与处理，Webhook 的副作用声明及服务端配置可能使 Dry-run 被拒绝，不能把失败一律解释为 YAML 缩进错误。

| 层次                    | 主要检查                                                  | 不能证明什么                                                     |
| ----------------------- | --------------------------------------------------------- | ---------------------------------------------------------------- |
| YAML 语法               | 缩进、映射、列表和标量的解析及基本类型                    | Kubernetes 字段、字段关系和准入一定合法                          |
| API Schema 与服务端校验 | 资源字段、约束和适用准入；服务端 Dry-run 不持久化目标资源 | 调度、拉镜像和运行一定成功；也不保证之后正式提交仍有相同环境条件 |
| 实际运行                | 观察控制器、Pod、镜像、网络及应用结果                     | 不能只凭一次 Dry-run 或 Ready 就宣称完整业务验收                 |

例如，前面的 `app=catalog` / `app=order` 片段可以通过 YAML 解析，仍违反 Deployment 字段关系约束。相反，合法对象即便服务端 Dry-run 成功，也可能因镜像不可获取而无法运行。[Kubernetes 1.28 Dry-run 保证与权限](https://github.com/kubernetes/website/blob/release-1.28/content/en/docs/reference/using-api/api-concepts.md#dry-run)

关于标签与资源版本，参阅 [标签和选择器](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/)及 [API 版本机制](https://kubernetes.io/docs/reference/using-api/)；具体 1.28 字段仍以目标版本 schema 为准。后续资源章会沿着这份结构逐层增加配置。

[继续看 catalog 贯穿案例：完整对象与关系](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
