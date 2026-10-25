---
id: kubernetes-authentication-rbac
title: 第二十八章 身份认证、ServiceAccount 与 RBAC
description: 认证识别调用者；授权判断该身份是否能执行请求；适用的准入随后检查写请求。API 权限不等于网络访问权限，ServiceAccount 也不是应用数据库的万能账号。
date: '2026-10-25'
updated: '2026-10-25'
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

## 1. 谁在调用，与允许做什么

认证识别调用者；授权判断该身份是否能执行请求；适用的准入随后检查写请求。API 权限不等于网络访问权限，ServiceAccount 也不是应用数据库的万能账号。

普通用户可以通过证书、外部身份系统等方式认证。Kubernetes 没有要求给每个人创建一个普通 User API 对象，也不是“浏览器用户不能用 API，只有服务账户能调用”。

ServiceAccount 是命名空间内的工作负载身份资源，其标准身份包含命名空间和账号名。创建它并不会自动授予管理员权限；需要分别考虑 Pod 使用哪个账号、如何提供凭据，以及允许哪些操作。

## 2. 1.28 的令牌不能套用旧 Secret 模型

普通 Pod 默认使用所在命名空间的 default ServiceAccount，但是否自动挂载凭据还受相应配置影响。能挂载令牌不等于已经获得读取所有资源的权限。

1.28 的常见服务账户凭据采用 TokenRequest 与 projected volume 路线，有相应期限与绑定语义；不能继续把“每个 ServiceAccount 自动创建一个长期 token Secret，再挂到 Pod”当成普遍默认。

应用应能处理令牌轮换，不应永久缓存启动时读到的令牌。对于无需访问 API 的工作负载，还应考虑关闭相应的自动挂载。[1.28 服务账户配置](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/configure-pod-container/configure-service-account.md)

## 3. Role、ClusterRole 与绑定

![RBAC 主体、规则与绑定范围](/assets/notes/kubernetes/k8s-rbac-binding.svg)

Role 描述命名空间级范围的规则；ClusterRole 可描述集群级资源或可复用规则。RoleBinding 在自己的命名空间内授予相应权限，可以引用 Role，也可以引用 ClusterRole；引用后者不自动变成全局授权。

ClusterRoleBinding 授予集群范围的相应权限。主体可以是用户、组或 ServiceAccount，不仅限于服务账户。RBAC 权限是相加的，不能靠再建一个“空角色”抵消已有管理员授权。[RBAC 机制](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

## 4. 新增最小读权限示例

新增教学示例：以下绑定为 study 中的 reader 授予该命名空间内 Pod 对象的 get、list、watch 权限，可以读取完整对象，包括 spec、status 和直接写入对象的普通环境变量值；它不是“仅元数据可见”的字段级隔离。规则不授予 Pod 写权限，也不包含 pods/log、pods/exec 子资源。Secret 引用不会因此自动展开为 Secret 内容。实际有效权限还需合并其他绑定判断。[资源读取权限的范围](https://kubernetes.io/docs/reference/access-authn-authz/authorization/)

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

## 5. 权限验收与危险的间接能力

```bash
kubectl auth can-i get pods -n study
kubectl auth can-i get pods --subresource=log -n study
```

查询模板未执行，检查的是当前身份的适用请求，不是所有人的权限。使用 `--as` 模拟身份本身需要相应权限，不能随意依赖它绕过认证。

判断是否满足最小权限，还要检查间接访问路径。能够创建 Pod、修改工作负载或挂载敏感资源的身份，可能获得超出单条 API 读权限的实际能力。不能只检查某个 Role 中是否包含 secrets，就认定敏感数据是安全的。

账号撤销、令牌轮换、管理员配置分发和审计应形成完整流程。对于 401、403 等错误先区分认证与授权，结合真实服务端信息判断，不能用“给 cluster-admin 试试”代替定位。

[返回本册目录](/collections/kubernetes/)
