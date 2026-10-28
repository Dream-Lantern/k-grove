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

`apiVersion: v1` 是核心组的表达；Deployment 通常使用 `apps/v1`。不要给所有对象都填同一个版本。版本名字中的 alpha、beta、稳定版表示演进阶段，不能把“beta 一般不会弃用”当成兼容承诺。升级前仍要核对被移除的 API 和迁移路径。

API 资源存在集群级与命名空间级范围。Namespace 能组织 Pod、Service 等资源，但 Node、PV、ClusterRole 等不属于某一个 Namespace。名字相同不代表跨范围是同一个对象。

## 2. YAML 的映射、列表与多文档

下面是一份用于阅读结构的 Deployment 示例。镜像名是教学占位，不是可以拉取的实际发布物。

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
          image: registry.example.com/study/catalog:DEMO
          ports:
            - name: http
              containerPort: 8080
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

## 3. 对象标签、模板标签与选择器 {#_3-三处-labels-作用可能不同}

在 Deployment 示例中，`metadata.labels` 是 Deployment 自己的标签；`spec.template.metadata.labels` 是未来 Pod 的标签。两处不会因为键名相同就自动成为一回事。

`spec.selector` 描述控制器选择的 Pod 范围，必须与模板标签相匹配。Pod 可以拥有更多标签，不要求它的全部标签与选择器完全相等。选择器不是对 Deployment 名字的引用，也不等同于 ownerReferences 所表达的控制关系。

Service 的 selector 通常匹配同一命名空间中的 Pod 标签，而不是 Deployment 对象本身。Deployment 与 Service 可以通过共同的 Pod 标签协作，但仍是彼此独立的资源。

## 4. 选择器的逻辑

常见等值筛选如 `app=catalog`，集合筛选如 `tier in (api,worker)`。多个以逗号分隔的要求通常按 AND 组合，不能把逗号当 OR。

`matchLabels` 能表达简单等值关系；支持的资源还可以通过 `matchExpressions` 表达集合等条件。不同字段支持的选择器形式不同，例如 Service selector 不是完整的 LabelSelector 表达式对象，不能把 Deployment 的整段 selector 原样粘进去。

节点选择也有自己的入口：`nodeSelector` 位于 Pod 的 spec 中，用来约束节点标签；它不属于 Deployment 自身的顶层 spec。

新增查询示例，未执行：

```bash
kubectl get pods -n study --show-labels
kubectl get pods -n study -l app=catalog,tier=api
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

这些是查询模板，仍需先确认上下文和权限。客户端 dry-run 不是完整服务端兼容检查，某些发现或校验也可能需要与集群交互；服务端 dry-run 会发送请求，经过适用校验与准入，但不持久化目标资源。两者都不能证明业务上线成功。

关于标签与资源版本，参阅 [标签和选择器](https://kubernetes.io/docs/concepts/overview/working-with-objects/labels/)及 [API 版本机制](https://kubernetes.io/docs/reference/using-api/)；具体 1.28 字段仍以目标版本 schema 为准。后续资源章会沿着这份结构逐层增加配置。

[继续看 catalog 贯穿案例：完整对象与关系](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
