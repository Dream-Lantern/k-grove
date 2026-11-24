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
# 查看当前 kubectl 上下文，确认后续命令将连接哪个集群；此命令不切换上下文
kubectl config current-context
# 列出 kubeconfig 中的上下文及当前选中项，便于核对集群和身份
kubectl config get-contexts
# 查询当前集群控制平面及服务入口信息，用于确认 API 连接
kubectl cluster-info
# 检查当前或 --as 指定身份是否获准执行后面的动词与资源操作；结果是授权判断，不实际执行该操作
# -n study 限定命名空间
kubectl auth can-i get pods -n study
# 查询命令中指定的资源及对象名；只读返回当前状态
kubectl get namespaces
```

这组只作查询。给普通用户开通访问要靠为其身份分配必要权限；复制管理员 kubeconfig 会把管理员权限一并交出去。kubeconfig 可能包含秘密，未知来源的配置还可能触发认证插件等行为，使用前要确认来源。

前两条主要检查本地配置；cluster-info、auth can-i 与 get namespaces 会联系实际集群。未知 kubeconfig 的 exec 认证插件可能执行本地程序，不能为了“先看看”就信任它。本章没有读取、复制或输出实际管理员 kubeconfig，也不执行在线检查。以下 STUDY_CONTEXT 均是需替换并核验的占位名。

kubectl get 这类请求是直接问到 API Server：它从存储里取出对象返回给你，不会临时去叫某个 Pod 控制器现算一份列表。控制器只在后台自己的循环里改对象状态，不负责应答查询。

## 2. get、describe、logs 各看一层

| 命令     | 适合看什么           | 需注意                         |
| -------- | -------------------- | ------------------------------ |
| get      | 列表、概要、对象字段 | 列表摘要不能替代完整状态       |
| describe | 关系、状态和事件摘要 | 事件保留有限，不是永久审计     |
| logs     | 容器输出             | 明确 Pod、容器、当前或上次实例 |

```bash
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n NAMESPACE 限定命名空间
# -o wide 展示节点、IP 等扩展列
kubectl get pods -n NAMESPACE -o wide
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n NAMESPACE 限定命名空间
# -o yaml 输出完整对象字段，便于核对 spec 与 status
kubectl get deployment APP -n NAMESPACE -o yaml
# 查看指定资源的状态详情及相关事件，用于核对调度、启动或控制器失败原因
# -n NAMESPACE 限定命名空间
kubectl describe pod POD_NAME -n NAMESPACE
# 读取指定 Pod 或工作负载的容器日志；-c 选择容器
# --tail=100 仅取末尾相应行数
# -n NAMESPACE 限定命名空间
kubectl logs POD_NAME -n NAMESPACE -c CONTAINER_NAME --tail=100
```

输出 YAML 可能携带环境信息，日志也可能包含用户数据或令牌。分享前脱敏；把全部命名空间的内容上传到外部服务，泄露面会远超需要排查的范围。

## 3. 容器执行与端口转发 {#_3-exec-与-port-forward-不只是查询}

exec 是在容器里启动一个进程；port-forward 是在你本机和某个 Pod 之间临时开一条隧道，本机端口的流量被原样转到 Pod 的端口，相当于绕过 Service 直接连进去。即使命令看起来只是在打开 shell，也可能获得读写业务数据的能力。这类操作需要额外明确授权和最小权限。

| 操作           | 作用             | 主要边界                                     |
| -------------- | ---------------- | -------------------------------------------- |
| get / describe | 查询资源与事件   | 输出可能暴露环境或敏感信息                   |
| logs           | 读取日志         | 可能含 Token、用户或业务数据                 |
| exec           | 在容器内启动进程 | 可改变应用与数据，不属于纯只读查询           |
| port-forward   | 建立访问通道     | 可能连入内部敏感服务，不等同于状态查询       |
| apply / patch  | 创建或修改对象   | 改变在线期望状态                             |
| replace        | 替换完整对象     | 可能覆盖字段；不能把完整对象来源视为天然正确 |
| delete         | 删除资源         | 可能影响业务、依赖对象和持久数据             |

风险由操作、身份、资源和环境共同决定。日志和 YAML 上传外部服务前要先脱敏；查询权限只覆盖查询动作，不覆盖结果的对外传播。

容器没有 bash 或诊断工具，并不说明应用不健康。临时安装工具会改变现场，必要时应使用经批准的诊断方式。诊断方式应与环境权限和现场保留要求相匹配。

## 4. create、apply、replace、patch

create 只建新对象，对象已存在就会报错；apply 拿文件去对齐集群，没有就建、有差异就改；replace 用一整份对象把现有的覆盖掉；patch 只动你指定的那几个字段，其余不碰。

apply 并非只是“修改文件里看起来不一样的几行”，还涉及字段管理与冲突。在线 edit 也不会回写版本库。团队应明确声明源、字段管理者和变更审批，不能指望混用命令后各处配置自动保持一致。

### 4.1 两种 Apply 与字段管理

Client-Side Apply（客户端应用，CSA）由客户端来算：kubectl 读三样东西——这次提交的声明、上次 apply 留下的 last-applied 记录、集群里当前的对象——比对之后才决定发什么改动。Server-Side Apply（服务端应用，SSA）则由 API Server 接住整份声明，自己判断哪些字段归谁管、哪些需要改。Field Manager（字段管理者）用于标识管理来源，metadata.managedFields（托管字段记录）用于记录适用的字段管理信息。

独立纸面场景：管理者 A 用 SSA 声明 Deployment 的 spec.replicas=2，持有该字段；管理者 B 通过 SSA 声明同一字段为 3，可能收到字段所有权冲突。应先查谁管理该字段、为何要改、控制器是否持续协调，再决定交接管理权。`--force-conflicts` 只应用在确认可以接管的字段上；非 Apply 更新和控制器写入的行为与 SSA 冲突检测是两套机制。[1.28 Server-Side Apply](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/server-side-apply.md)

HPA、Helm、GitOps 和人工修改可能共同影响 replicas；字段归属与声明源要事先协调，不能把 SSA 当成所有写入者自动达成一致的机制。

### 4.2 验证分层

| 检查方式       | 主要目的                                           | 不能证明                             |
| -------------- | -------------------------------------------------- | ------------------------------------ |
| YAML 静态检查  | 语法与基本结构                                     | Kubernetes API 字段及业务一定合法    |
| dry-run=client | 客户端生成与适用检查                               | 完整服务端校验，或所有情况下完全离线 |
| dry-run=server | 访问服务端，经过适用校验与准入，但不持久化目标资源 | Pod 调度、挂载和应用可用             |
| kubectl diff   | 比较在线与拟应用对象                               | 差异合理或业务可运行                 |
| kubectl apply  | 实际创建/修改                                      | 变更已通过运行和业务验收             |

新增学习模板，以下不执行。服务端 dry-run 仍会联系集群；运行 diff 前要先确认上下文：

```bash
# 根据 -f 指定的 YAML 清单创建或更新资源；清单中的 namespace 与当前上下文都需要对应本实验
# -n study 限定命名空间；--context 显式选择 kubeconfig 上下文
# --dry-run=server 请求服务端校验与默认化，但不持久化资源
kubectl --context=STUDY_CONTEXT -n study apply --dry-run=server -f app.yaml
# 比较 -f 指定清单与集群现有对象的差异；只展示变更，不应用清单
# -n study 限定命名空间；--context 显式选择 kubeconfig 上下文
kubectl --context=STUDY_CONTEXT -n study diff -f app.yaml
# 真正变更，仅作语法说明
# 根据 -f 指定的 YAML 清单创建或更新资源；清单中的 namespace 与当前上下文都需要对应本实验
# -n study 限定命名空间；--context 显式选择 kubeconfig 上下文
kubectl --context=STUDY_CONTEXT -n study apply -f app.yaml
```

app.yaml 需替换为审阅过的测试清单，本节命令不组成自动变更脚本。客户端 dry-run 不经过服务端的权限、准入与版本校验，仍可能进行 API 发现等交互。服务端 dry-run 仍受权限和准入策略影响；Webhook 的 sideEffects 声明须允许相应 dry-run；请求被拒绝时，不能算验证通过。[1.28 API dry-run 语义](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/using-api/api-concepts.md)

kubectl diff 的退出码 0 表示无差异，1 表示存在差异，大于 1 表示命令或 diff 过程失败。自动化要把退出码 1 当作“有差异”而非失败，并单独处理大于 1 的失败。diff 可能展示 Secret 等敏感字段，传播前要遮蔽；命令成功只说明文件与集群状态一致，业务可用性仍需另测。[v1.28.0 diff 命令定义](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/kubectl/pkg/cmd/diff/diff.go)

## 5. 标签和补丁要与声明源协调

`kubectl label` 修改在线标签后，不会因为关闭终端自动丢失；后续控制器或自动化可能覆盖它。标签命令使用 `label` 子命令，筛选值需要与实际标签一致。

JSON Patch 使用 `[{"op": ...}]` 一类操作数组；Merge Patch 使用对象结构。使用 `--type=json` 却传一段合并补丁不是正确组合。不了解字段语义时，不以“服务端接收了”为变更正确性的唯一证明。

假设 Deployment 已有 spec.replicas 字段，要改为 3。JSON Patch 是有序操作数组，replace 要求目标路径存在：

补丁说明：这是 JSON Patch 操作数组；`replace` 把 `/spec/replicas` 的已有值改为 `3`，后续通过 `--type=json` 提交，不是独立的 kubectl 命令。

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

补丁说明：这是 Merge Patch 对象；只合并 `spec.replicas: 3`，未列出的对象字段不会像整体替换那样全部丢弃。

```json
{
  "spec": {
    "replicas": 3
  }
}
```

下面两条是彼此独立的等目标示例，都会修改在线资源；本次不执行，读者也不必依次运行。catalog 若由 HPA 管理，直接改副本数会与 HPA 的协调冲突：

```bash
# 局部修改指定资源；--type=json 按 JSON Patch 操作列表修改，--type=merge 按对象合并
# 补丁把 spec.replicas 设为 3，即期望副本数；不是直接创建指定数量的新 Pod
# -n study 限定命名空间；--context 显式选择 kubeconfig 上下文
kubectl --context=STUDY_CONTEXT -n study patch deployment catalog --type=json -p '[{"op":"replace","path":"/spec/replicas","value":3}]'
# 局部修改指定资源；--type=json 按 JSON Patch 操作列表修改，--type=merge 按对象合并
# 补丁把 spec.replicas 设为 3，即期望副本数；不是直接创建指定数量的新 Pod
# -n study 限定命名空间；--context 显式选择 kubeconfig 上下文
kubectl --context=STUDY_CONTEXT -n study patch deployment catalog --type=merge -p '{"spec":{"replicas":3}}'
```

Merge Patch 对数组通常整体替换；Strategic Merge Patch（战略合并补丁）在适用内建类型上按字段 Schema 定义处理列表，例如容器列表可按 name 合并。不能把这套规则当作任意 CRD 或所有数组的共同语义。

## 6. 删除前先形成一份清单

确认对象种类、名字、命名空间、UID、拥有关系与后端数据；说明要级联删除还是孤儿化。删除工作负载不保证关联 Service 或所有存储一并消失，反过来也可能按策略触发数据回收。

`--cascade=orphan` 是显式孤儿化的一种表达，不能继续把旧的 `--cascade=false` 当作当前学习的通用写法。强制删除可能留下仍运行的进程，不作为普通卡顿的第一步。

以 catalog 为例：Deployment 通常拥有 ReplicaSet，ReplicaSet 拥有 Pod，适用级联删除依 OwnerReferences（所有者引用）处理；Service、ConfigMap 不因名称相同就被拥有或一并删除。Orphan（孤儿化）保留适用依赖对象，但会改变后续管理关系。PVC/PV、StatefulSet 的 PVC 保留策略和后端回收还需独立检查。强制删除 Pod 不保证原容器进程已停止，删除对象也不会恢复业务数据。

删除前逐项确认对象种类、Namespace、UID、OwnerReferences、关联资源、持久数据、回收策略、备份恢复条件，以及预期影响和业务验证方法。用强制删除全部资源的一键命令替代这些判断，会跳过上述确认。

一次安全的变更按这个顺序做：先把当前声明和状态存下来，再确认这次会影响到哪些对象和业务，准备好回滚路径，然后一次只改一项，改完立刻看对象状态和业务结果。回滚能恢复哪些外部状态，需要事先写清。

[![kubectl：本地检查、在线验证、变更授权及运行验收](/assets/notes/kubernetes/k8s-kubectl-change-validation.svg)](/assets/notes/kubernetes/k8s-kubectl-change-validation.svg)

图中的变更授权按所在团队流程执行，本章只是教学流程，不是本次修订需要连接集群的请求。后续认证、授权和准入章节会继续解释服务端权限边界；下一章先学习 [Helm 的 Chart、Values 与 Release](/articles/kubernetes-helm.html)。

[返回本册目录](/collections/kubernetes/)
