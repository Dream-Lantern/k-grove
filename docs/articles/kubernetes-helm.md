---
id: kubernetes-helm
title: 第二十七章 Helm、Chart 与发布记录
description: "Chart 是一组模板、默认值和元数据等组成的包。用户结合 Values 渲染 Kubernetes 对象，通过安装或升级形成一次 Release 的管理记录。"
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
order: 27
---

# 第二十七章 Helm、Chart 与发布记录

> 本章介绍 Helm 3 的包结构、模板渲染与 Release 管理，服务于 Kubernetes 1.28 学习。工具和 Chart 需分别固定版本，示例为命令阅读材料。

下文升级、回滚和 Release 存储等版本敏感说明按 **Helm v3.13.3 固定源码**核对。

## 1. Chart 与 Release 分别是什么

Chart 是一组模板、默认值和元数据等组成的包。用户结合 Values 渲染 Kubernetes 对象，通过安装或升级形成一次 Release 的管理记录。一个 Chart 可以形成多个 Release，不能把包名、应用名和发布实例名混为一谈。

Chart 的 `version` 与 `appVersion` 也不是同一个版本号。升级 Chart 可能修改模板、依赖或默认值，即使应用版本没变，也应审核实际渲染差异。

[![Helm：Chart、Values、渲染与 Release](/assets/notes/kubernetes/k8s-helm-release.svg)](/assets/notes/kubernetes/k8s-helm-release.svg)

Helm 使用相应 Kubernetes 权限执行资源操作，不会因为“它是包管理器”绕过 RBAC 或准入。

| 概念                 | 用途                                                            |
| -------------------- | --------------------------------------------------------------- |
| Chart（配置包）      | 可复用的 Kubernetes 模板、默认值与元数据                        |
| Chart Version        | Chart 包的 version，不等于应用版本                              |
| appVersion           | 应用版本元数据，除非模板引用，否则不会自动改变镜像 tag          |
| Values（参数值）     | 模板渲染的输入，可有多层覆盖                                    |
| Release（发布实例）  | 一次由 Helm 管理的安装实例及记录，一个 Chart 可安装多个 Release |
| Revision（修订编号） | Release 历史的编号，区别于 Deployment Revision                  |

Values 变化也可能通过升级形成新 Revision。Helm Release 是管理记录，不是 Kubernetes 自带的一种 Deployment 资源。

## 2. 先理解包内结构

`Chart.yaml` 描述包元数据和依赖；`values.yaml` 提供默认输入；`templates` 保存模板；`charts` 可保存依赖包。模板语法和 Kubernetes 字段校验属于不同层次。

一个模板能成功渲染，只说明模板处理完成，不代表目标集群支持对应 API，也不代表镜像、存储或外部依赖可用。[Helm 3 Chart 结构](https://helm.sh/docs/v3/topics/charts/)

需要明确 Values 各层输入的覆盖关系。多个 `-f` 文件和命令行覆盖会影响最终结果，不能只看编辑过的一个 values.yaml 就认定它是最终生效配置，也要留意命令行值的类型转换。

### 2.1 一个完整最小 Chart

以下文件只写在文章中。读者可在专用临时目录按结构重建，不要覆盖已有 catalog Release。本例无依赖、CRD、Hook 或真实凭据；镜像固定 busybox:1.36.1，实际启动 8080 静态 HTTP 服务，未做集群运行验证。

```text
catalog-chart/
├── Chart.yaml
├── values.yaml
└── templates/
    ├── deployment.yaml
    └── service.yaml
values-dev.yaml
values-override.yaml
```

`catalog-chart/Chart.yaml`：

```yaml
apiVersion: v2
name: catalog-chart
description: Minimal catalog teaching chart
type: application
version: 0.1.0
appVersion: "1.36.1"
```

`catalog-chart/values.yaml`：

```yaml
replicaCount: 2
image:
  repository: busybox
  tag: "1.36.1"
service:
  port: 80
autoscaling:
  enabled: false
```

`catalog-chart/templates/deployment.yaml`：

```text
apiVersion: apps/v1
kind: Deployment
metadata:
  name: {{ .Release.Name | quote }}
  namespace: {{ .Release.Namespace | quote }}
spec:
  {{- if not .Values.autoscaling.enabled }}
  replicas: {{ .Values.replicaCount }}
  {{- end }}
  selector:
    matchLabels:
      app: {{ .Release.Name | quote }}
  template:
    metadata:
      labels:
        app: {{ .Release.Name | quote }}
    spec:
      containers:
        - name: app
          image: {{ printf "%s:%s" .Values.image.repository .Values.image.tag | quote }}
          command: ["sh", "-ec"]
          args:
            - |
              mkdir -p /www
              printf 'catalog chart demo\n' > /www/index.html
              exec httpd -f -p 8080 -h /www
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /
              port: http
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
```

`catalog-chart/templates/service.yaml`：

```text
apiVersion: v1
kind: Service
metadata:
  name: {{ .Release.Name | quote }}
  namespace: {{ .Release.Namespace | quote }}
spec:
  selector:
    app: {{ .Release.Name | quote }}
  ports:
    - name: http
      protocol: TCP
      port: {{ .Values.service.port }}
      targetPort: http
```

这是 Go Template（Go 模板）：.Release 提供发布实例信息，.Values 读取合并输入；printf 组合镜像引用，quote 给字符串加引号，if 控制是否渲染 replicas。以 Release=catalog、Namespace=study 渲染时，两对象均名 catalog，Pod 标签 app=catalog；换 Release 名会同步改变名称和标签，避免固定名称碰撞。Service 的 80 通过命名端口 http 指向实际 8080。

autoscaling.enabled=true 只省略固定 replicas，**不会创建 HPA**。需另行配置第二十五章 HPA 并设计副本字段交接，省略字段的首次迁移也要审核差异，不能承诺切换时副本数完全不波动。

### 2.2 Values 覆盖顺序

在 catalog-chart 同级保存以下两个文件。`values-dev.yaml`：

```yaml
replicaCount: 3
```

`values-override.yaml`：

```yaml
replicaCount: 4
```

```bash
helm template catalog ./catalog-chart -n study \
  -f values-dev.yaml \
  -f values-override.yaml \
  --set replicaCount=5
```

| 输入层                         | replicaCount          |
| ------------------------------ | --------------------- |
| Chart 默认 values.yaml         | 2                     |
| 第一个 -f values-dev.yaml      | 3                     |
| 后一个 -f values-override.yaml | 4                     |
| 显式 --set                     | 5，成为本例最终渲染值 |

后面的 Values 文件覆盖前面的同名标量，显式命令行值再覆盖。--set 有类型推断，镜像 tag 等字符串需使用适当字符串输入方式；不要把敏感值放入 Shell 参数。映射和数组不是统一的“任意深度合并”，本例只展示标量覆盖。[Helm 3 Values 说明](https://helm.sh/docs/v3/chart_template_guide/values_files/)与[v3.13.3 多文件/命令行合并实现](https://raw.githubusercontent.com/helm/helm/v3.13.3/pkg/cli/values/options.go)

## 3. 先做不安装的检查

按第二节重建样例文件并安装兼容 Helm 3 后，运行以下命令审阅渲染结果：

```bash
helm lint ./catalog-chart
helm template catalog ./catalog-chart -n study -f values-dev.yaml
helm show values ./catalog-chart
```

这些命令适合检查包与模板，但不能替代目标集群的实际验收。模板、插件和依赖应来自可信来源，不应随意执行未知插件或把真实 Secret 打印到终端日志。

| 验证层             | 能确认                        | 不能确认                            |
| ------------------ | ----------------------------- | ----------------------------------- |
| helm lint          | Chart 结构与适用规则          | 目标集群一定接受                    |
| helm template      | 模板可渲染                    | 服务端 Schema、调度、镜像或业务正常 |
| 渲染 YAML 静态检查 | 基本语法和字段关系            | 完整服务端合法性                    |
| Server Dry-run     | 授权环境的适用服务端校验/准入 | 真正运行与业务可用                  |
| 运行验收           | 实际对象与业务观察            | 所有外部副作用自动可回滚            |

只有经过授权才连接目标集群做 Server Dry-run，不为通过检查而连接未知集群。使用模板中的 .Capabilities、lookup、私有函数或复杂依赖时，还需按实际 Helm 版本验证，本例不使用这些能力。

Chart 仓库负责包分发，OCI 提供另一种分发方式，索引站点帮助发现资源。使用历史 stable 仓库资料时，需重新核对实际包来源、维护状态与版本。

## 4. 安装、升级与回滚分别改什么

以下命令用于升级和回滚，会改变集群资源：

```bash
helm install catalog ./catalog-chart -n study -f values-dev.yaml
helm upgrade catalog ./catalog-chart -n study -f values-override.yaml
helm rollback catalog REVISION -n study
```

复盘时固定 Chart、依赖、Values、工具版本和镜像引用。不要默认上一次升级的所有输入都会以你期待的方式复用，尤其要审核重置或复用 Values 的选项。

这些变更需要专用、已授权的 study 和没有同名现存资源的实验环境；REVISION 要从实际历史核对，不是可直接执行的文字。不要在已有 HPA、人工对象或其他 Release 管理的 catalog 上照抄安装命令。

### 4.1 Release 历史不是 Deployment 历史

独立纸面路径，假设操作均成功、没有并发或额外失败修订：

| 操作     | 配置                     | Release Revision                 |
| -------- | ------------------------ | -------------------------------- |
| 初次安装 | v1                       | 1                                |
| 升级     | v2                       | 2                                |
| 再升级   | v3                       | 3                                |
| 回滚到 1 | 尝试恢复历史 v1 资源配置 | 新建 4，不是把当前记录编号改回 1 |

v3.13.3 的 rollback 按当前 Revision+1 建立新记录并执行适用资源更新。失败操作也可能留下历史和状态，真实编号以查询为准；Release Revision 与 Deployment 模板 Revision 是两套编号。[v3.13.3 rollback 实现](https://raw.githubusercontent.com/helm/helm/v3.13.3/pkg/action/rollback.go)

以下查询会连接集群，不在本次执行。get values 及 --all 输出可能含敏感值，不可未经脱敏传播：

```bash
helm list -n study
helm history catalog -n study
helm status catalog -n study
helm get values catalog -n study
helm get values catalog -n study --all
```

### 4.2 升级时复用哪些 Values

按 v3.13.3 的 reuseValues 分支，默认逻辑不是无条件复用上次所有计算结果：若未传新的覆盖值，会在适用情况下复制上一 Release 的用户配置；若有新的覆盖值，默认不会自动复制全部旧用户配置。--reuse-values 会以旧 Chart 已合并结果为基础，再合入新覆盖，可能保留旧默认值；--reset-values 则丢弃旧配置，使用新 Chart 默认值加本次覆盖。[v3.13.3 upgrade 实现](https://raw.githubusercontent.com/helm/helm/v3.13.3/pkg/action/upgrade.go)

独立算例：旧 Chart 默认 replicaCount=2、service.port=80；旧 Release 用户覆盖 replicaCount=3。新 Chart 默认 replicaCount=4、service.port=8081。本次新覆盖若存在，仅为 replicaCount=5：

| 升级输入                     | 最终 replicaCount | 最终 service.port    |
| ---------------------------- | ----------------- | -------------------- |
| 默认，无新覆盖               | 3，复用旧用户覆盖 | 8081，新默认         |
| 默认，显式新覆盖 5           | 5                 | 8081                 |
| --reuse-values，无新覆盖     | 3                 | 80，旧合并默认被保留 |
| --reuse-values，显式新覆盖 5 | 5                 | 80                   |
| --reset-values，无新覆盖     | 4，新默认         | 8081                 |
| --reset-values，显式新覆盖 5 | 5                 | 8081                 |

此版本同时设置 reset/reuse 时，reset 分支优先；不要用混合参数掩盖不清晰的继承意图。表格不是对上面的最小 Chart 在线升级，Helm 其他次版本或 Helm 4 需重新核对。上线前检查 Release 当前 Values 与实际渲染，不能只读仓库最新 values.yaml。

按 Release 历史回滚，并不会自动撤销数据库迁移、消息发送和外部云资源操作的所有副作用。钩子也可能运行具有副作用的任务，因此必须了解包的具体实现。

## 5. 卸载与数据保留

卸载主要按 Release 管理关系处理适用资源。CRD、钩子资源、显式保留对象和持久数据可能有单独生命周期，不能保证“卸载后环境完全恢复为安装前”。

正式维护前列出对象与数据，确认回收策略、备份和业务停机条件；卸载结果需同时核对集群对象与外部资源。

| 内容                          | Helm 回滚是否自动恢复                  |
| ----------------------------- | -------------------------------------- |
| 历史 Release 中适用资源配置   | 可以尝试恢复，仍需运行验收             |
| ConfigMap/Secret 外部手工修改 | 不保证，应核对 Helm 管理范围与实际差异 |
| 数据库 Schema 迁移            | 不自动撤销                             |
| Hook 的外部副作用             | 不自动撤销                             |
| 对象存储中的业务数据          | 不自动恢复                             |
| 非 Helm 管理资源              | 不保证                                 |

helm.sh/resource-policy: keep 可要求保留适用资源，保留对象可能脱离正常 Release 生命周期管理，仍需核对版本与实际删除路径。CRD（Custom Resource Definition，自定义资源定义）在 Helm 3 的 crds/ 中有特殊安装边界，不能假设 upgrade/uninstall 自动完整升级或删除它。Hook（钩子）可在安装、升级、回滚等阶段运行任务，其资源不等同于普通 Release 资源；需设计 before-hook-creation、hook-succeeded、hook-failed 等适用清理策略或 Job TTL。[Helm 3 Hook 与资源边界](https://helm.sh/docs/v3/topics/charts_hooks/)

Chart 直接包含的 PVC 与 StatefulSet 等工作负载生成的 PVC 也不能一概而论；卸载是否删申领、PV 是否 Delete 回收、后端数据是否删除需逐层检查。回滚不等于完整业务恢复，卸载不保证回到安装前环境。未知 Chart 不用于回滚或卸载实验，本章不实际执行清理；若读者另行创建实验 Release，应在核对上述边界后按授权流程退役。

仅当确认 catalog 是自己安装的本节已审核最小 Chart、没有混入其他资源或真实数据时，以下才是对应的实验清理语法；它会修改集群：

```bash
helm uninstall catalog -n study
```

## 6. Chart 与 Release 的安全边界

先审查固定版本 Chart 的来源、依赖、模板与 Hook，不随意安装未知 Helm 插件。模板渲染、dry-run、diff 和 Release 历史都可能包含 Secret 或敏感 Values，dry-run 不等于没有敏感输出。

Helm v3.13.3 默认用 Release 所在命名空间的 Secret 保存历史，存储驱动可配置，不能把编码/压缩理解为保密；需检查实际存储后端与最小访问权限。[v3.13.3 Release 存储选择](https://raw.githubusercontent.com/helm/helm/v3.13.3/pkg/action/action.go)

本章只使用无敏感价值的教学参数，没有读取或输出生产 Values、凭据和实际 Release。正式变更应审核渲染后的资源，并核对 Kubernetes RBAC、准入和业务验收；Helm 不绕过这些边界。

关于命令选项和实际语义，参阅 [Helm 3 文档](https://helm.sh/docs/v3/)，并与使用的具体版本帮助对应。Chart 是可审计的交付包，不能替代应用发布与数据恢复设计。

[返回本册目录](/collections/kubernetes/)
