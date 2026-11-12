---
id: kubernetes-kubectl
title: 第二十六章 kubectl 日常管理与安全变更
description: "kubectl 通过 kubeconfig 等配置确定 API 地址、身份与上下文。上下文还关联默认命名空间；如果不清楚终端使用的默认值，即使命令正确，也可能作用于错误环境。"
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
order: 26
---

# 第二十六章 kubectl 日常管理与安全变更

> Kubernetes 1.28 使用习惯与命令复盘。分清查询、连接和变更，避免把文档中的例子当成自动操作脚本。

## 1. 先确认自己连着哪里

kubectl 通过 kubeconfig 等配置确定 API 地址、身份与上下文。上下文还关联默认命名空间；如果不清楚终端使用的默认值，即使命令正确，也可能作用于错误环境。

| 配置概念                      | 用途                                                   |
| ----------------------------- | ------------------------------------------------------ |
| Cluster（集群）               | 目标 API Server 地址、CA 等连接设置                    |
| User（用户配置）              | 使用的身份或认证方式，不等同于已证明有效权限           |
| Context（上下文）             | 关联 Cluster、User 与适用默认 Namespace（命名空间）    |
| Current Context（当前上下文） | 未显式指定时默认使用的上下文                           |
| KUBECONFIG                    | 环境变量，可指定参与加载、合并的配置文件，影响最终配置 |

上下文名称叫 study 或 test，并不证明 API 地址一定属于测试环境。命令行 --context、-n 等参数还可能覆盖默认值；对有影响的操作应显式指定已核验的目标上下文和 Namespace。

```bash
kubectl config current-context
kubectl config get-contexts
kubectl cluster-info
kubectl auth can-i get pods -n study
kubectl get namespaces
```

这组只作查询。不要把管理员 kubeconfig 到处复制当作给普通用户开通访问的方法；应为相应身份分配必要权限。kubeconfig 可能包含秘密，未知来源配置也可能有认证插件等行为，不应直接信任。

前两条主要检查本地配置；cluster-info、auth can-i 与 get namespaces 会联系实际集群。未知 kubeconfig 的 exec 认证插件可能执行本地程序，不能为了“先看看”就信任它。本章没有读取、复制或输出实际管理员 kubeconfig，也不执行在线检查。以下 STUDY_CONTEXT 均是需替换并核验的占位名。

kubectl 的 GET 请求由 API 服务端相应的资源处理机制响应，不是每次同步调用某个 Pod 控制器来生成列表。控制器通过自己的循环协调对象状态。

## 2. get、describe、logs 各看一层

| 命令     | 适合看什么           | 需注意                         |
| -------- | -------------------- | ------------------------------ |
| get      | 列表、概要、对象字段 | 列表摘要不能替代完整状态       |
| describe | 关系、状态和事件摘要 | 事件保留有限，不是永久审计     |
| logs     | 容器输出             | 明确 Pod、容器、当前或上次实例 |

```bash
kubectl get pods -n NAMESPACE -o wide
kubectl get deployment APP -n NAMESPACE -o yaml
kubectl describe pod POD_NAME -n NAMESPACE
kubectl logs POD_NAME -n NAMESPACE -c CONTAINER_NAME --tail=100
```

输出 YAML 可能携带环境信息，日志也可能包含用户数据或令牌。分享前脱敏；不要为了方便把全部命名空间的内容上传到外部服务。

## 3. 容器执行与端口转发 {#_3-exec-与-port-forward-不只是查询}

exec 在容器中运行进程，port-forward 建立访问通道。即使命令看起来只是在打开 shell，也可能获得读写业务数据的能力。这类操作需要额外明确授权和最小权限。

| 操作           | 作用             | 主要边界                                     |
| -------------- | ---------------- | -------------------------------------------- |
| get / describe | 查询资源与事件   | 输出可能暴露环境或敏感信息                   |
| logs           | 读取日志         | 可能含 Token、用户或业务数据                 |
| exec           | 在容器内启动进程 | 可改变应用与数据，不属于纯只读查询           |
| port-forward   | 建立访问通道     | 可能连入内部敏感服务，不等同于状态查询       |
| apply / patch  | 创建或修改对象   | 改变在线期望状态                             |
| replace        | 替换完整对象     | 可能覆盖字段；不能把完整对象来源视为天然正确 |
| delete         | 删除资源         | 可能影响业务、依赖对象和持久数据             |

风险由操作、身份、资源和环境共同决定。日志和 YAML 不应未经脱敏直接上传外部服务，查询权限也不是传播全部查询结果的授权。

容器没有 bash 或诊断工具，并不说明应用不健康。临时安装工具会改变现场，必要时应使用经批准的诊断方式。诊断方式应与环境权限和现场保留要求相匹配。

## 4. create、apply、replace、patch

create 主要创建新对象；apply 管理声明式配置并进行适用的创建或更新；replace 用完整对象替换；patch 按选定补丁格式修改部分字段。

apply 并非只是“修改文件里看起来不一样的几行”，还涉及字段管理与冲突。在线 edit 也不会回写版本库。团队应明确声明源、字段管理者和变更审批，不能指望混用命令后各处配置自动保持一致。

### 4.1 两种 Apply 与字段管理

Client-Side Apply（客户端应用，CSA）由客户端结合提交声明、适用的历史 last-applied 配置及在线对象计算更新；Server-Side Apply（服务端应用，SSA）由 API Server 处理声明和字段管理。Field Manager（字段管理者）用于标识管理来源，metadata.managedFields（托管字段记录）用于记录适用的字段管理信息。

独立纸面场景：管理者 A 用 SSA 声明 Deployment 的 spec.replicas=2，持有该字段；管理者 B 通过 SSA 声明同一字段为 3，可能收到字段所有权冲突。应先查谁管理该字段、为何要改、控制器是否持续协调，再决定交接管理权。不能默认用 --force-conflicts 抢占所有冲突；非 Apply 更新和控制器写入的行为也不能与 SSA 冲突检测混为一谈。[1.28 Server-Side Apply](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/server-side-apply.md)

HPA、Helm、GitOps 和人工修改可能共同影响 replicas；字段归属与声明源要事先协调，不能把 SSA 当成所有写入者自动达成一致的机制。

### 4.2 验证分层

| 检查方式       | 主要目的                                           | 不能证明                             |
| -------------- | -------------------------------------------------- | ------------------------------------ |
| YAML 静态检查  | 语法与基本结构                                     | Kubernetes API 字段及业务一定合法    |
| dry-run=client | 客户端生成与适用检查                               | 完整服务端校验，或所有情况下完全离线 |
| dry-run=server | 访问服务端，经过适用校验与准入，但不持久化目标资源 | Pod 调度、挂载和应用可用             |
| kubectl diff   | 比较在线与拟应用对象                               | 差异合理或业务可运行                 |
| kubectl apply  | 实际创建/修改                                      | 变更已通过运行和业务验收             |

新增学习模板，以下不执行。服务端 dry-run 仍会联系集群，diff 也不能在未确认上下文时随意运行：

```bash
kubectl --context=STUDY_CONTEXT -n study apply --dry-run=server -f app.yaml
kubectl --context=STUDY_CONTEXT -n study diff -f app.yaml
# 真正变更，仅作语法说明
kubectl --context=STUDY_CONTEXT -n study apply -f app.yaml
```

app.yaml 需替换为审阅过的测试清单，本节命令不组成自动变更脚本。客户端 dry-run 不是完整的服务端权限、准入与版本校验，也不能保证完全不进行 API 发现等交互。服务端 dry-run 仍受权限和准入策略影响；Webhook 的 sideEffects 声明须允许相应 dry-run，不能把被拒绝的请求当作已经验证通过。[1.28 API dry-run 语义](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/api-concepts.md)

kubectl diff 的退出码 0 表示无差异，1 表示存在差异，大于 1 表示命令或 diff 过程失败。自动化不能把“有差异”简单当成真正错误，也不能忽略大于 1 的失败。diff 可能展示 Secret 等敏感字段，不应原样传播；成功也不证明运行时和业务可用。[v1.28.0 diff 命令定义](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/kubectl/pkg/cmd/diff/diff.go)

## 5. 标签和补丁要与声明源协调

`kubectl label` 修改在线标签后，不会因为关闭终端自动丢失；后续控制器或自动化可能覆盖它。标签命令使用 `label` 子命令，筛选值需要与实际标签一致。

JSON Patch 使用 `[{"op": ...}]` 一类操作数组；Merge Patch 使用对象结构。使用 `--type=json` 却传一段合并补丁不是正确组合。不了解字段语义时，不以“服务端接收了”为变更正确性的唯一证明。

假设 Deployment 已有 spec.replicas 字段，要改为 3。JSON Patch 是有序操作数组，replace 要求目标路径存在：

```json
[
  {
    "op": "replace",
    "path": "/spec/replicas",
    "value": 3
  }
]
```

Merge Patch 则描述要合并的对象结构：

```json
{
  "spec": {
    "replicas": 3
  }
}
```

下面两条为独立的等目标示例，均会修改在线资源，本次不执行，也不要求读者依次运行。catalog 若由 HPA 管理，不应拿它做未经协调的副本变更：

```bash
kubectl --context=STUDY_CONTEXT -n study patch deployment catalog --type=json -p '[{"op":"replace","path":"/spec/replicas","value":3}]'
kubectl --context=STUDY_CONTEXT -n study patch deployment catalog --type=merge -p '{"spec":{"replicas":3}}'
```

Merge Patch 对数组通常整体替换；Strategic Merge Patch（战略合并补丁）在适用内建类型上按字段 Schema 定义处理列表，例如容器列表可按 name 合并。不能把这套规则当作任意 CRD 或所有数组的共同语义。

## 6. 删除前先形成一份清单

确认对象种类、名字、命名空间、UID、拥有关系与后端数据；说明要级联删除还是孤儿化。删除工作负载不保证关联 Service 或所有存储一并消失，反过来也可能按策略触发数据回收。

`--cascade=orphan` 是显式孤儿化的一种表达，不能继续把旧的 `--cascade=false` 当作当前学习的通用写法。强制删除可能留下仍运行的进程，不作为普通卡顿的第一步。

以 catalog 为例：Deployment 通常拥有 ReplicaSet，ReplicaSet 拥有 Pod，适用级联删除依 OwnerReferences（所有者引用）处理；Service、ConfigMap 不因名称相同就被拥有或一并删除。Orphan（孤儿化）保留适用依赖对象，但会改变后续管理关系。PVC/PV、StatefulSet 的 PVC 保留策略和后端回收还需独立检查。强制删除 Pod 不保证原容器进程已停止，删除对象也不会恢复业务数据。

删除前逐项确认对象种类、Namespace、UID、OwnerReferences、关联资源、持久数据、回收策略、备份恢复条件，以及预期影响和业务验证方法。不要用强制删除全部资源的一键命令替代这些判断。

一次安全变更应包括：保存当前声明和状态、确认影响范围、准备可用的恢复路径、每次只执行一项变更，并观察对象与业务结果。回滚能恢复哪些外部状态，需要事先写清。

[![kubectl：本地检查、在线验证、变更授权及运行验收](/assets/notes/kubernetes/k8s-kubectl-change-validation.svg)](/assets/notes/kubernetes/k8s-kubectl-change-validation.svg)

图中的变更授权按所在团队流程执行，本章只是教学流程，不是本次修订需要连接集群的请求。后续认证、授权和准入章节会继续解释服务端权限边界；下一章先学习 [Helm 的 Chart、Values 与 Release](/articles/kubernetes-helm.html)。

[返回本册目录](/collections/kubernetes/)
