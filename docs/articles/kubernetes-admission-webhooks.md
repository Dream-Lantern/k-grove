---
id: kubernetes-admission-webhooks
title: 第二十九章 准入 Webhook 与安全边界
description: "即使调用者通过认证并获得了相应写权限，提交的对象仍可能不满足集群策略。例如，策略可能要求声明某个标签，或禁止某类主机权限。"
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
order: 29
---

# 第二十九章 准入 Webhook 与安全边界

> 本章以 Kubernetes 1.28 的 admissionregistration.k8s.io/v1 为范围，解释对象写入时的策略检查、Webhook 匹配和故障处理。

## 1. 写权限之后的对象策略检查 {#_1-为什么有权限创建-还可能被拒绝}

一个写请求进来，要先过三道关：Authentication（认证）先认出“你是谁”，Authorization（授权）再判断这个身份能不能做这个动作，Admission Control（准入控制）最后检查这次要写入的对象本身是否符合集群规则。例如，调用者能够创建 Pod，仍可能因为对象使用被禁止的主机权限而遭拒。GET 只读不写对象，因此不进入这套准入流程。

[![准入 Webhook：允许、拒绝与调用异常](/assets/notes/kubernetes/k8s-admission-webhook.svg)](/assets/notes/kubernetes/k8s-admission-webhook.svg)

## 2. 两类 Webhook 与配置资源

Mutating Admission Webhook（变更准入 Webhook）可修改请求对象，例如为 Pod 补充 `managed-by: policy-webhook`。Validating Admission Webhook（验证准入 Webhook）决定是否接受，例如要求 Pod 声明 `team` 标签。于是，变更成功的对象仍可能因缺少 team 被后续验证拒绝。

MutatingWebhookConfiguration 和 ValidatingWebhookConfiguration 只是两份“登记表”：写清楚哪些请求要送给哪个服务、送到哪个地址。真正做判断的是另外部署的 Webhook Server，它要自己实现协议、配好 TLS、能被 API Server 访问到。所以创建配置不会凭空变出一个服务，也不会给这个服务任何管理员权限。

[![AdmissionReview 请求、响应与后续处理](/assets/notes/kubernetes/k8s-admission-review-flow.svg)](/assets/notes/kubernetes/k8s-admission-review-flow.svg)

图是主要职责关系，省略内置准入组件、默认化和其他校验；插件的内部顺序不在这张图里。API Server 调用各 Webhook，而不是 Webhook 直接相互调用。

下面是 **合成的 AdmissionReview 协议示例，未发送**。AdmissionReview 是 API Server 与 Webhook 交换请求、判定的信封。为突出字段，省略请求中的部分服务端上下文；真实请求的身份信息由 API Server 提供。`dryRun: true` 表示本次模拟写入不持久化，仍可调用匹配的 Webhook。

字段说明：`request.uid` 关联同一次准入请求的回复，`operation` 是 API 操作，`object` 是待准入对象；`dryRun: true` 表示本次请求不持久化对象，仍可能进入适用的准入检查。

```json
{
  "apiVersion": "admission.k8s.io/v1",
  "kind": "AdmissionReview",
  "request": {
    "uid": "review-demo-001",
    "operation": "CREATE",
    "kind": { "group": "", "version": "v1", "kind": "Pod" },
    "resource": { "group": "", "version": "v1", "resource": "pods" },
    "namespace": "study",
    "name": "catalog-demo",
    "userInfo": { "username": "demo-user", "groups": ["system:authenticated"] },
    "object": {
      "apiVersion": "v1",
      "kind": "Pod",
      "metadata": { "name": "catalog-demo", "namespace": "study", "labels": {} },
      "spec": { "containers": [{ "name": "app", "image": "busybox:1.36.1", "command": ["sleep", "3600"] }] }
    },
    "dryRun": true
  }
}
```

变更 Webhook 的允许响应如下。`response.uid` 必须复制本次 `request.uid`，它是调用关联标识，不是 Pod UID。`patch` 是 JSON Patch 的 Base64 编码，`patchType` 为 `JSONPatch`：

字段说明：`response.uid` 必须与请求 UID 对应；`allowed` 表示允许，`patchType` 声明补丁格式，`patch` 是 JSON Patch 字节经 Base64 编码后的字符串。

```json
{
  "apiVersion": "admission.k8s.io/v1",
  "kind": "AdmissionReview",
  "response": {
    "uid": "review-demo-001",
    "allowed": true,
    "patchType": "JSONPatch",
    "patch": "W3sib3AiOiJhZGQiLCJwYXRoIjoiL21ldGFkYXRhL2xhYmVscy9tYW5hZ2VkLWJ5IiwidmFsdWUiOiJwb2xpY3ktd2ViaG9vayJ9XQ=="
  }
}
```

解码后的补丁如下；示例请求已经有 `metadata.labels: {}`，因此父路径存在。如果真实对象没有 labels，必须先构造父对象，不能直接照搬该路径。

补丁说明：`op: add` 在 JSON Pointer 的 `path` 处写入 `value`；这里依赖对象已有 `metadata.labels`，并不等同于任意缺失父路径都能自动创建。

```json
[{ "op": "add", "path": "/metadata/labels/managed-by", "value": "policy-webhook" }]
```

对应的对象局部结果：

```yaml
metadata:
  labels:
    managed-by: policy-webhook
```

相同标签和值已存在时，应返回 `allowed: true` 并省略 patch，避免无意义的重复修改；若已有不同值，策略必须明确选择保留、拒绝或改写。本例选择改写为期望值，再次处理同一结果不产生补丁。这就是幂等：重复处理不会不断增加或改变结果。

验证 Webhook 接收到变更后的对象，但它还要求 team 标签。下例为 **另一次验证调用的拒绝响应**，那次验证请求沿用上面的 Pod 内容并包含已补充的标签，`request.uid` 改为 `review-demo-002`，其余示例字段不变。响应 UID 对应该次验证请求，不复用前一个变更调用的 UID：

拒绝说明：`allowed: false` 拒绝该请求，`status` 补充原因；回复 UID 对应另一次请求，不能与前面的允许回复混配。

```json
{
  "apiVersion": "admission.k8s.io/v1",
  "kind": "AdmissionReview",
  "response": {
    "uid": "review-demo-002",
    "allowed": false,
    "status": { "code": 403, "reason": "Forbidden", "message": "missing team label" }
  }
}
```

`allowed: true` 只允许继续，后续准入或 API 处理仍可能失败；`allowed: false` 是明确拒绝。即使所有 Webhook 允许，也不证明对象已经保存、Pod 已调度或应用已运行。这里 dry-run 更不会持久化。

变更 Webhook 的 `reinvocationPolicy` 默认 `Never`：同一个对象在一次准入评估里，这个 Webhook 只被调用一次。改成 `IfNeeded` 后，如果排在你后面的 Webhook 又改了对象，API Server 可能回头再调用你一次，让你看到最新内容；具体调几次不固定，先后顺序也没有保证。所以先把逻辑做成幂等（重复执行结果不变），再考虑打开它。[1.28 动态准入协议与重入机制](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/reference/access-authn-authz/extensible-admission-controllers.md)

## 3. 匹配范围决定影响面

教学规则只匹配带 `admission-lab=enabled` 标签的测试 Namespace 中的 Pod CREATE。下面是 **webhooks 数组中一个条目的局部字段**，省略 name、clientConfig 等必要内容，不是可直接提交的完整配置；`reinvocationPolicy` 只用于变更 Webhook。

```yaml
rules:
  - operations: ["CREATE"]
    # 空字符串代表核心 API 组；不是匹配所有 API 组的通配符。
    apiGroups: [""]
    apiVersions: ["v1"]
    resources: ["pods"]
    scope: Namespaced
namespaceSelector:
  matchLabels:
    admission-lab: enabled
admissionReviewVersions: ["v1"]
# Fail 表示 Webhook 调用失败按拒绝处理；这是调用失败策略，不是业务拒绝回复。
failurePolicy: Fail
# 本次调用/探测的超时秒数，具体对象见所在配置段。
timeoutSeconds: 10
# None 声明 Webhook 无副作用，以便 API Server 按其规则处理 dry-run。
sideEffects: None
# IfNeeded 允许按准入流程需要再次调用 Mutating Webhook，处理逻辑应适应重复执行。
reinvocationPolicy: IfNeeded
```

`operations` 匹配操作，`apiGroups` 中空字符串代表核心 API 组，`apiVersions` 匹配资源版本，`resources` 匹配资源种类，`scope` 限制为命名空间资源。`admissionReviewVersions` 声明服务支持的协议版本，与被检查的 Pod API 版本不是同一字段。

| API 请求                                    | 是否进入该 Webhook   |
| ------------------------------------------- | -------------------- |
| 带指定 Namespace 标签的 study 中 CREATE Pod | 匹配                 |
| 不带该标签的普通 Namespace 中 CREATE Pod    | 不匹配               |
| UPDATE Deployment                           | 不匹配资源与操作     |
| GET Pod                                     | 不属于该准入调用范围 |

`namespaceSelector` 依据 Namespace 标签，因此还要控制谁能修改这些标签。`objectSelector` 依据对象标签进一步筛选；本例未设置，不能额外假定 Pod 必须有某个选择标签。用户若能改对象标签，基于它的自选加入不能作为防恶意绕过的唯一强制边界。

Deployment UPDATE 与控制器随后发起的 Pod CREATE 是不同 API 请求；后者可能独立匹配本规则。不能将规则概括成拦截整个应用发布过程。范围还应避开控制面修复依赖，防止 Webhook 故障阻塞修复自身的写请求；例外也应有明确权限边界。

## 4. timeout、failurePolicy 与 sideEffects

`failurePolicy` 处理适用的 Webhook **调用错误**，不覆盖策略明确拒绝。

| Webhook 结果                                    | failurePolicy=Fail | failurePolicy=Ignore |
| ----------------------------------------------- | ------------------ | -------------------- |
| 正常返回 allowed=true                           | 继续后续处理       | 继续后续处理         |
| 正常返回 allowed=false                          | 拒绝               | 拒绝                 |
| 调用超时                                        | 拒绝               | 忽略该调用错误，继续 |
| 网络连接失败                                    | 拒绝               | 忽略该调用错误，继续 |
| 无法解码或 UID 不匹配等无效响应，被归为调用错误 | 拒绝               | 忽略该调用错误，继续 |

Ignore 不保证整个 API 请求成功；其他准入、校验或持久化仍可能失败。表中最后一行专指调用响应校验错误，不能扩大为忽略所有补丁应用错误或所有 API 错误。[v1.28.0 响应校验](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/apiserver/pkg/admission/plugin/webhook/request/admissionreview.go)、[验证 Webhook 调度与错误分支](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/apiserver/pkg/admission/plugin/webhook/validating/dispatcher.go)。

| 字段               | Kubernetes 1.28 的值与约束                    |
| ------------------ | --------------------------------------------- |
| failurePolicy      | Ignore 或 Fail，默认 Fail                     |
| timeoutSeconds     | 1～30 秒，默认 10 秒；限制单次调用等待        |
| sideEffects        | v1 必填，无默认；可声明 None 或 NoneOnDryRun  |
| reinvocationPolicy | 仅变更 Webhook；Never 或 IfNeeded，默认 Never |

以上核对了 [v1.28.0 API 类型](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/admissionregistration/v1/types.go)与[默认值实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/apis/admissionregistration/v1/defaults.go)。

场景 A：纯验证不写外部系统，可声明 `sideEffects: None`。场景 B：正常请求会写外部系统，但实现能够识别 `request.dryRun` 并在 dry-run 时抑制写入，可声明 `NoneOnDryRun`。Dry-run 仍会调用 Webhook；它要求参与者正确处理模拟请求。

不能声明 None 却实际产生外部副作用。即使普通请求已产生副作用，后续验证仍可能拒绝或保存失败，所以外部操作还需要补偿、恢复或协调机制。Fail 与 Ignore 的差别在于故障时你更怕哪一种：选 Fail，Webhook 一旦超时，相关写入就被拒绝，策略不会失效，代价是 Webhook 自身故障会挡住操作；选 Ignore，Webhook 不可用时请求照常放行，可用性保住了，代价是这段时间策略检查形同虚设。

## 5. 证书与访问路径

API Server 是调用方。`clientConfig.service` 指定的 Service、服务证书名称和 `caBundle` 的信任链必须对应。例如 `policy-webhook` 位于 study 时，服务证书应对 `policy-webhook.study.svc` 有效；`caBundle` 提供验证服务证书所需的 PEM CA 数据（API JSON 中为 Base64）。省略它意味着使用 API Server 的系统信任根，不意味着跳过验证。

普通 Pod 能访问 Service，不足以证明控制面上的 API Server 访问路径正常。要结合控制面网络、Service 端点和服务监听判断；跳过 TLS 验证只是绕过检查，不是修复。Webhook 服务账号仅应有实现所需权限，日志与拒绝信息应避免泄露 Secret 或完整敏感请求。

| 现象                   | 优先检查                                                      |
| ---------------------- | ------------------------------------------------------------- |
| Webhook Service 不可达 | Service、EndpointSlice、后端 Pod、控制面访问路径              |
| x509 证书错误          | 有效期、服务 DNS 名、证书链与 caBundle                        |
| Webhook 超时           | 处理耗时、网络和依赖服务                                      |
| 部分 Namespace 被拒绝  | namespaceSelector、匹配规则、Namespace 标签权限与具体拒绝信息 |
| Dry-run 失败           | sideEffects 声明、协议与服务实现                              |
| Webhook 明确拒绝       | AdmissionReview status 与策略条件，而非先改 failurePolicy     |

修改 failurePolicy 或删除 WebhookConfiguration 可能影响集群全局策略，属于受控变更。本章不执行此类修改，也不提供批量删除配置的排障脚本。

## 6. 准入通过之后还要验什么

对象保存不保证镜像可拉取、Pod 可调度或应用可启动，也不证明应用有数据库等业务权限。这几件事各有各的负责人：准入回答“这个对象允不允许写进集群”，容器安全上下文回答“容器以什么身份、带哪些权限运行”，网络策略回答“哪些 Pod 之间能互相连接”，业务认证回答“应用拿什么账号登录数据库”。任何一层通过，都不能替其他层背书。

在另行授权的测试环境中，还应记录允许、明确拒绝、调用超时、证书错误、dry-run、重新调用与故障恢复的结果。

[返回本册目录](/collections/kubernetes/)
