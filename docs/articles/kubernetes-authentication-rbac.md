---
id: kubernetes-authentication-rbac
title: 第二十八章 身份认证、ServiceAccount 与 RBAC
description: "认证识别调用者；授权判断该身份是否能执行请求；适用的准入随后检查写请求。API 权限不等于网络访问权限，ServiceAccount 也不是应用数据库的万能账号。"
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
order: 28
---

# 第二十八章 身份认证、ServiceAccount 与 RBAC

> Kubernetes 1.28 权限复盘。只整理公开机制与合成清单，未读取管理员凭据、创建令牌或修改授权。

## 1. 认证、授权与工作负载身份 {#_1-谁在调用-与允许做什么}

认证识别调用者；授权判断该身份是否能执行请求；适用的准入随后检查写请求。API 权限不等于网络访问权限，ServiceAccount 也不是应用数据库的万能账号。

下面是主要职责关系，不是 API Server 内部所有校验函数唯一且严格的执行顺序；读请求不走图中的对象写入分支。

[![API 请求中的认证、授权与准入职责](/assets/notes/kubernetes/k8s-api-auth-admission-flow.svg)](/assets/notes/kubernetes/k8s-api-auth-admission-flow.svg)

认证成功不代表有操作权限；授权成功也不保证准入通过。例如，用户有创建 Pod 的 RBAC 权限，但策略禁止 `privileged` 容器，该请求仍可能被拒绝。准入通过不代表保存一定成功，更不代表 Pod 已经调度或运行。控制器的协调发生在后续异步流程中。

普通用户可以通过证书、外部身份系统等方式认证，其身份由认证系统管理；ServiceAccount 则是 Kubernetes 提供的工作负载身份资源。两类身份都可在授权范围内访问 API。[1.28 身份认证](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/access-authn-authz/authentication.md)

ServiceAccount 是命名空间内的工作负载身份资源，其标准身份包含命名空间和账号名。创建它并不会自动授予管理员权限；需要分别考虑 Pod 使用哪个账号、如何提供凭据，以及允许哪些操作。

## 2. TokenRequest、投射令牌与轮换 {#_2-1-28-的令牌不能套用旧-secret-模型}

普通 Pod 默认使用所在命名空间的 default ServiceAccount，但是否自动挂载凭据还受相应配置影响。能挂载令牌不等于已经获得读取所有资源的权限。

1.28 的常见服务账户凭据采用 TokenRequest 与 projected volume 路线，有相应期限与绑定语义；不能继续把“每个 ServiceAccount 自动创建一个长期 token Secret，再挂到 Pod”当成普遍默认。

常见链路可拆成六步：

1. Pod 的 `serviceAccountName` 指定工作负载身份。
2. ServiceAccount 准入机制在适用条件下为 Pod 配置 Projected Volume（投射卷，把多种来源的数据投射为容器内文件）。
3. kubelet 通过 TokenRequest API 请求有期限、适用 audience（令牌预期接收方）和绑定条件的令牌。
4. kubelet 将令牌投射到卷中，容器从文件读取。
5. kubelet 在适用条件下提前请求并更新令牌。
6. 应用重新读取更新后的文件；永久缓存启动时的值会导致轮换后仍使用旧令牌。

令牌获取、文件投射、轮换与 RBAC 授权是不同机制。持有有效令牌只解决身份认证，不自动增加权限。对于无需访问 API 的 Pod，可以使用以下 **Pod spec 局部片段，不能单独提交**：

```yaml
spec:
  serviceAccountName: reader
  automountServiceAccountToken: false
```

ServiceAccount 和 Pod 都能配置 `automountServiceAccountToken`；Pod spec 显式设置时优先。关闭自动挂载不会删除账号，也不会撤销已有 RBAC 规则；它也不禁止显式声明服务账户令牌投射卷。本章不请求或打印真实令牌。[ServiceAccount 准入与投射机制](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/access-authn-authz/service-accounts-admin.md)、[1.28 服务账户配置与令牌轮换](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/configure-pod-container/configure-service-account.md)

## 3. Role、ClusterRole 与绑定

[![RBAC：主体、规则与授权范围](/assets/notes/kubernetes/k8s-rbac-binding.svg)](/assets/notes/kubernetes/k8s-rbac-binding.svg)

Role 描述命名空间级范围的规则；ClusterRole 可描述集群级资源或可复用规则。RoleBinding 在自己的命名空间内授予相应权限，可以引用 Role，也可以引用 ClusterRole；引用后者不自动变成全局授权。

ClusterRoleBinding 授予集群范围的相应权限。主体可以是用户、组或 ServiceAccount，不仅限于服务账户。RBAC 权限是相加的，不能靠再建一个“空角色”抵消已有管理员授权。[1.28 RBAC 机制](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/access-authn-authz/rbac.md)

| 场景 | 绑定关系                         | 授权范围                                               |
| ---- | -------------------------------- | ------------------------------------------------------ |
| A    | RoleBinding → Role               | 绑定所在命名空间内适用的资源；Role 必须在同一命名空间  |
| B    | RoleBinding → ClusterRole        | 绑定所在命名空间内适用的命名空间资源                   |
| C    | ClusterRoleBinding → ClusterRole | 按规则授予集群范围的适用权限，包含适用的各命名空间资源 |
| D    | 同一主体适用多个 Binding         | 各允许规则叠加，没有空角色抵消或显式 deny              |

Role 用于命名空间资源；ClusterRole 可描述命名空间资源和集群级资源。即使 ClusterRole 包含 Node 规则，用 `study` 中的 RoleBinding 引用它，也不会得到 Node 访问权或跨命名空间授权。

## 4. 新增最小读权限示例

新增教学示例：以下绑定为 study 中的 reader 授予该命名空间内 Pod 对象的 get、list、watch 权限，可以读取完整对象，包括 spec、status 和直接写入对象的普通环境变量值；它不是“仅元数据可见”的字段级隔离。规则不授予 Pod 写权限，也不包含 pods/log、pods/exec 子资源。Secret 引用不会因此自动展开为 Secret 内容。实际有效权限还需合并其他绑定判断。[1.28 RBAC 资源与子资源](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/access-authn-authz/rbac.md)

清单未执行，不是所有应用的通用权限：

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: reader
  namespace: study
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-reader
  namespace: study
rules:
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: pod-reader
  namespace: study
subjects:
  - kind: ServiceAccount
    name: reader
    namespace: study
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: pod-reader
```

Pod 模板使用 `serviceAccountName: reader` 引用账号。`pods/log`、`pods/exec` 等子资源与普通 pods 不同，不能因为允许 get pods 就假定允许查看日志或进入容器。

| 资源             | 典型 RBAC 动词     | 含义                              |
| ---------------- | ------------------ | --------------------------------- |
| pods             | get / list / watch | 读取完整 Pod 对象、列出或观察变化 |
| pods/log         | get                | 读取 Pod 日志                     |
| pods/exec        | create             | 典型 POST 容器执行请求            |
| pods/portforward | create             | 典型 POST 端口转发请求            |

后两项按 1.28 常见 kubectl POST 请求说明（[exec 源码](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubectl/pkg/cmd/exec/exec.go)、[port-forward 源码](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubectl/pkg/cmd/portforward/portforward.go)）；使用其他连接方法的客户端可能需要相应的 `get` 权限，不能推成所有客户端永远只需 create。子资源独立授权，因此 `get pods` 不等于 `get pods/log`，也不等于 `create pods/exec`。

## 5. 权限验收与危险的间接能力

```bash
kubectl auth can-i get pods -n study
kubectl auth can-i get pods --subresource=log -n study
```

查询模板未执行，检查的是当前身份的适用请求，不是所有人的权限。使用 `--as` 模拟身份本身需要相应权限，不能随意依赖它绕过认证。

如获准模拟服务账户，可以另外检查：

```bash
kubectl auth can-i get pods -n study --as=system:serviceaccount:study:reader
kubectl auth can-i get pods --subresource=log -n study --as=system:serviceaccount:study:reader
```

执行者需要对应的 `impersonate` 权限；模拟不是绕过认证或授权。仅指定用户名的模拟也不应被当作已完整复现真实令牌携带的所有组授权，应核对实际身份、组和全部适用规则。1.28 kubectl 支持上述 `--subresource` 用法。[命令源码](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubectl/pkg/cmd/auth/cani.go)

以下为 **reader 仅适用本例授权、没有其他允许规则时的教学预期**，不是实测结果：

| 操作          | 预期 |
| ------------- | ---- |
| get Pod       | 允许 |
| list Pod      | 允许 |
| watch Pod     | 允许 |
| delete Pod    | 拒绝 |
| get Pod Logs  | 拒绝 |
| exec 进入 Pod | 拒绝 |
| get Secret    | 拒绝 |

判断是否满足最小权限，还要检查间接访问路径。能够创建 Pod、修改工作负载或挂载敏感资源的身份，可能获得超出单条 API 读权限的实际能力。不能只检查某个 Role 中是否包含 secrets，就认定敏感数据是安全的。

账号撤销、令牌轮换、管理员配置分发和审计应形成完整流程。对于 401、403 等错误先区分认证与授权，结合真实服务端信息判断，不能用“给 cluster-admin 试试”代替定位。

| 现象                          | 主要检查方向                                              |
| ----------------------------- | --------------------------------------------------------- |
| 401 Unauthorized              | 凭据、令牌有效期和认证身份                                |
| 403 Forbidden                 | 实际身份、RBAC 或其他授权机制，以及错误中指出的准入策略   |
| ServiceAccount 存在但访问失败 | 是否真的使用该账号的令牌、audience 是否适用、绑定是否正确 |
| 仅某命名空间失败              | RoleBinding 所在命名空间及主体范围                        |
| Pod 可读取但日志失败          | pods/log 子资源规则                                       |

[返回本册目录](/collections/kubernetes/)
