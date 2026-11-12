---
id: kubernetes-troubleshooting
title: 第三十章 应用、网络与存储分层排障
description: "排障从明确现象开始：记录时间范围、影响用户、环境、命名空间、工作负载、相关 Pod UID 与最近变更，再将问题归为提交失败、启动失败、间歇错误、延迟升高或数据不一致。"
date: '2026-10-25'
updated: '2026-10-28'
category: engineering
type: troubleshooting
tags:
  - kubernetes
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kubernetes
series: kubernetes-learning
order: 30
---

# 第三十章 应用、网络与存储分层排障

> 本章串联 API、调度、节点、网络和存储各层证据，提供定位顺序与记录方法。命令为模板，示例场景用于教学推理。

## 1. 先给现象加上边界

排障从明确现象开始：记录时间范围、影响用户、环境、命名空间、工作负载、相关 Pod UID 与最近变更，再将问题归为提交失败、启动失败、间歇错误、延迟升高或数据不一致。

先判断影响一个副本、一台节点、一个命名空间还是全局；集群内外是否都失败。下面所有案例均为 **合成教学推演**，命令是只读查询模板，输出描述是给定证据或预期，不是实际集群结果。POD_NAME 等大写名称需要替换；日志和事件也可能含敏感信息，保存前应脱敏。

[![排障路径：先找停在哪一层](/assets/notes/kubernetes/k8s-troubleshooting-map.svg)](/assets/notes/kubernetes/k8s-troubleshooting-map.svg)

## 2. API 请求失败

先核对当前上下文、API 地址、真实身份，再保留脱敏错误原文和时间。认证、授权、准入和对象冲突需要分别定位。

| 现象                       | 可能原因                                              | 关键证据                                     |
| -------------------------- | ----------------------------------------------------- | -------------------------------------------- |
| 401 Unauthorized           | 令牌过期或认证失败                                    | API 错误、所用凭据的身份与有效性，不打印凭据 |
| 403 Forbidden              | RBAC、其他授权或适用准入拒绝                          | 实际身份、命名空间、授权规则、错误详情       |
| Admission Webhook 明确拒绝 | 对象不满足策略                                        | Webhook 名称、status.message 与被拒字段      |
| Webhook 超时               | 服务、网络或依赖异常                                  | 超时原文、匹配配置、Service 与后端状态       |
| API 对象冲突               | 更新所用 resourceVersion 过旧，或声明式字段所有权冲突 | 操作类型、错误原文、对象版本或 managedFields |

普通更新的版本冲突与 Server-Side Apply（服务端应用）的字段管理冲突不是同一机制。应先读取最新对象、理解并发修改或字段归属，再制定变更；不要一律强制覆盖。403 也不能一律归为 RBAC，更不能靠临时 cluster-admin 授权掩盖原因。不要公开 kubeconfig、Bearer token 或 Secret。

## 3. Pod 没有进入业务运行

按三层收集证据，而不是看到 Pending 就认定调度器故障：

| 层次                   | 先看什么                                                                       | 继续定位                                                                         |
| ---------------------- | ------------------------------------------------------------------------------ | -------------------------------------------------------------------------------- |
| 是否已分配节点         | spec.nodeName、PodScheduled 条件、FailedScheduling 事件                        | CPU/内存 requests、节点亲和性、污点与容忍、PVC 绑定及拓扑约束                    |
| 节点是否完成运行准备   | sandbox、kubelet 和 Container Runtime Interface（CRI，容器运行时接口）相关事件 | Container Network Interface（CNI，容器网络接口）、镜像、卷附加和挂载、运行时错误 |
| 应用是否正常启动与服务 | 容器 state、lastState、restartCount、日志                                      | 退出原因、配置与依赖、startup/liveness/readiness 探针                            |

| 观察词            | 所属层级                | 含义与限制                                                     |
| ----------------- | ----------------------- | -------------------------------------------------------------- |
| Pending           | Pod phase               | 接受对象后仍在准备；已分配 Node 也可能因镜像、卷等原因 Pending |
| FailedScheduling  | Event reason            | 调度失败事件，需查看具体约束与消息                             |
| ContainerCreating | 常见容器 Waiting reason | 运行准备中，结合事件分辨 sandbox、卷或其他步骤                 |
| ImagePullBackOff  | 容器 Waiting reason     | 拉取失败后退避；不等于镜像一定不存在                           |
| CrashLoopBackOff  | 容器 Waiting reason     | 反复退出后重启退避，不是 Pod phase                             |
| OOMKilled         | 容器 Terminated reason  | 查看 state 或 lastState 的终止原因，再结合内存限制、节点与监控 |

[v1.28.0 Pod phase 定义](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/core/v1/types.go)也明确将调度等待和镜像下载等准备时间包含在 Pending 中。

kubectl 的 STATUS 列是摘要，不能替代 API 字段。readiness 决定是否就绪；liveness 失败可导致容器重启；配置 startup 后，启动检查成功前其余两类探针暂不执行，不能混称为同一检查。

```bash
kubectl get pod POD_NAME -n study -o wide
kubectl describe pod POD_NAME -n study
kubectl get pod POD_NAME -n study -o jsonpath='{.spec.nodeName}{"\n"}{.status.phase}{"\n"}{.status.containerStatuses}{"\n"}'
kubectl logs POD_NAME -n study -c app --timestamps --tail=100
kubectl logs POD_NAME -n study -c app --previous --timestamps --tail=100
```

`--previous` 读取该容器上次终止实例的可用日志；没有上次实例或日志已轮转时可能失败。事件保留有限，不是永久历史；用 Pod UID、时间和控制器关系关联，缺失时记录证据缺项，不把无事件当作无故障。[1.28 Pod 排障](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/debug/debug-application/debug-pods.md)提供常见入口；其 Pending 简述需要结合这里的实际 phase、nodeName 和事件细分。

## 4. 运行中但不能服务

案例一：study/catalog 的 Pod Ready，从指定集群内客户端访问 Pod IP 和 Service 成功，但外部通过 Ingress 访问失败。给定 Service 端口为 80、targetPort 为 8080，Ingress 主机为 `catalog.example.com`。这些证据先缩小到入口路径；不能证明 Ingress Controller 到后端的路径也健康，因为客户端来源、节点与网络策略可能不同，部分控制器还直接访问端点。

```bash
kubectl get service catalog -n study -o yaml
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog -o yaml
kubectl get pods -n study -l app=catalog -o wide
kubectl get ingress catalog -n study -o yaml
kubectl describe ingress catalog -n study
kubectl get ingressclass
```

先核对 Service selector、实际端点及 Ready 条件、80 → 8080 映射，再核对 Ingress 的 `ingressClassName`、对应 IngressClass 的 controller、实际控制器是否处理该资源。根据环境确定控制器所在命名空间和 Pod，再查询其事件与脱敏日志，不假定控制器统一叫 ingress-nginx。

| 获取的证据                   | 支持的方向                       | 下一步                                       |
| ---------------------------- | -------------------------------- | -------------------------------------------- |
| 外部域名未解析或指向错误入口 | DNS 或入口地址配置               | 对照 Ingress status、实际负载均衡地址与 DNS  |
| DNS 正确，TCP 连接失败       | 入口监听、负载均衡或访问路径     | 检查入口端口、健康检查与来源限制             |
| TCP 通而 TLS 失败            | 证书、主机名、SNI 或信任链       | 按同一域名核对证书，不跳过校验               |
| HTTP 404                     | Host/path 或控制器路由可能不匹配 | 核对路由和控制器日志；404 本身不唯一确定原因 |
| HTTP 502/503 或后端超时      | 控制器到端点路径、后端选择或应用 | 对照控制器日志、端点端口与策略               |

在已获准访问的客户端可使用如下 **请求模板**；第二条只绕过 DNS，保留 Host 和 TLS 的服务器名称，不能用 IP URL 替代。INGRESS_IP 需替换为实际入口 IP，本章不发送请求。

```bash
curl --connect-timeout 3 --max-time 10 -v https://catalog.example.com/
curl --connect-timeout 3 --max-time 10 -v --resolve catalog.example.com:443:INGRESS_IP https://catalog.example.com/
```

比较同一来源、同一协议和业务路径，才能解释差异。ICMP ping 不验证 HTTP 路由或 TLS。若表现为仅跨节点失败，再沿节点路由/封装、MTU 与策略调查，不能仅凭超时就宣布 DNS 或 CNI 故障。[1.28 Service 排障](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/debug/debug-application/debug-service.md)

## 5. 存储与数据异常

案例二：catalog 使用 `catalog-data` PVC；PVC 已 Bound，但新 Pod 尚不能启动，事件报告 FailedAttachVolume 或 FailedMount。Bound 只说明 PVC 与 PV 已绑定，不保证节点附加、挂载和应用文件访问成功。

```bash
kubectl get pvc catalog-data -n study -o wide
kubectl describe pvc catalog-data -n study
kubectl get pod POD_NAME -n study -o yaml
kubectl describe pod POD_NAME -n study
kubectl get pv PV_NAME -o yaml
kubectl get storageclass STORAGE_CLASS_NAME -o yaml
kubectl get volumeattachment
```

从 PVC 的 `spec.volumeName` 得到 PV_NAME，再读取该 PV 和实际 StorageClass；查询集群资源需要对应权限，失败时由有权限人员协助。将 Pod 的 nodeName、PV 拓扑/节点亲和性、访问模式、VolumeAttachment 状态和 CSI（Container Storage Interface，容器存储接口）事件放在同一时间线上。

| 给定证据                                 | 待验证假设                 | 后续只读证据                                         |
| ---------------------------------------- | -------------------------- | ---------------------------------------------------- |
| FailedAttachVolume，提示已在另一节点使用 | 附加限制或旧节点使用未解除 | 访问模式、旧 Pod/节点、VolumeAttachment 和 CSI 记录  |
| FailedMount，提示挂载失败                | 节点挂载、驱动或存储端问题 | 事件原文、驱动与节点日志、存储端状态                 |
| 挂载已成功，应用报 Permission denied     | 文件权限或进程身份问题     | 应用日志、runAsUser/runAsGroup/fsGroup、存储权限记录 |

进一步核对 Pod 的 volumeMounts 是否将该 PVC 挂在预期 `/data`，是否误配只读或 subPath，应用配置是否实际使用 `/data`；再结合应用和存储记录验证预期文件的读写。本章不写入卷。PVC Bound、挂载成功、应用能够读写是三个不同的验收层次，不随意修改 PV 回收策略。

最后一行是另一条分支，不应把它冒充前面“尚未挂载”的同一结论。先确定停在哪一步，再由责任人选择处理方法；不删除 PVC/PV、不格式化卷，也不以改成 root 或全目录可写作为默认修复。

Pod 能写临时目录不证明持久卷可写。发现数据异常时保护现场，防止旧实例与替代实例同时写入；etcd 对象备份也不能代替业务卷或数据库的一致性备份。恢复方案需结合存储与应用记录另行验证。

## 6. 一次只验证一个假设

案例三：旧版本 v1 正常，发布 v2 后新 Pod readiness 失败，旧 Pod 继续服务。假定使用滚动更新，`maxUnavailable: 0`、`maxSurge: 1`，且旧副本仍健康；这才支持“新副本不就绪时旧副本仍保留”的推演，不把它推广到所有发布策略。

[![Readiness 失败：从假设到证据和验收](/assets/notes/kubernetes/k8s-readiness-troubleshooting.svg)](/assets/notes/kubernetes/k8s-readiness-troubleshooting.svg)

先观察 Deployment，再按 ownerReferences 与模板版本区分 ReplicaSet 和 Pod；标签查询只是候选集合，不代替归属核对。

```bash
kubectl get deployment catalog -n study -o yaml
kubectl get replicasets -n study -l app=catalog -o wide
kubectl get pods -n study -l app=catalog -o wide
kubectl get replicaset NEW_RS_NAME -n study -o yaml
kubectl describe pod NEW_POD_NAME -n study
kubectl get pod NEW_POD_NAME -n study -o jsonpath='{.spec.containers}{"\n"}{.status.containerStatuses}{"\n"}'
kubectl logs NEW_POD_NAME -n study -c app --timestamps --tail=100
kubectl logs NEW_POD_NAME -n study -c app --previous --timestamps --tail=100
```

对比新旧 ReplicaSet 模板中的镜像、启动参数、配置引用及探针；不要直接打印所引用的 Secret 内容。Ready=false 不必然意味着进程退出，探针配置错误与应用本身不可用应分别验证。

给定教学证据：新 Pod 已分配节点且容器 Running；事件出现 `Readiness probe failed`；readiness 使用 HTTP `/ready` 的 9090 端口，而应用启动配置和日志显示监听 `0.0.0.0:8080`，并提供 `/ready`；旧模板使用 8080。`containerPort: 8080` 只是声明，单凭这个字段不能证明进程真的监听，应与启动参数、应用日志和获准的连接验证相互印证。

| 步骤与假设             | 所需证据 / 给定结果                                                           | 判断与下一步                                                       |
| ---------------------- | ----------------------------------------------------------------------------- | ------------------------------------------------------------------ |
| 初始假设：CPU 不足     | requests、limits、节点条件及既有 CPU/限流监控；本例监控正常，无支持限流的证据 | 目前不支持；已调度也不能单独证明运行时 CPU 永远足够                |
| 下一假设：探针端口错误 | 对比新旧模板、事件、应用启动配置和日志；9090 与 8080 不一致                   | 支持端口不匹配，继续确认路径、协议和实际监听                       |
| 验证修复假设           | 在授权测试环境单独修正探针端口，保持路径、镜像和资源等其余条件                | 观察探针是否成功及新版本业务；本章未实施，不能写成根因已被实测确认 |

不要同时升级 CNI、重启 DNS、增加资源和改变探针。若修正端口后仍失败，就保留结果，继续检查路径、协议、监听地址或依赖；不能把图中的常见原因当作必然根因。

责任人在受控流程中保存修复前配置，单独修改探针；需要恢复时先核实可用历史模板和配置兼容性，再选择恢复方案，不假定固定 revision 永远有效。本文不执行修复或回滚。

验收既要看新 ReplicaSet 的 Pod Ready、Deployment updated/available 与滚动完成，也要看 EndpointSlice 是否纳入期望新端点，并从原先失败的业务路径验证 **确实命中新版本**。旧 Pod 仍成功可能掩盖新版本故障，只有总体请求成功还不够。观察窗口需覆盖原故障触发条件，并记录业务与数据一致性结果。

## 7. 排障记录的最小模板

```text
现象与时间：
影响范围：
环境与近期变更：
已收集证据（脱敏）：
假设及排除依据：
获批的变更与恢复步骤：
验证结果及观察窗口：
仍未确认的条件：
```

| 只读命令模板                                                        | 获取的证据                                       |
| ------------------------------------------------------------------- | ------------------------------------------------ |
| `kubectl config current-context`                                    | 当前上下文；仍需核对是否为目标环境               |
| `kubectl auth can-i get pods -n study`                              | 当前身份对指定请求的授权判定                     |
| `kubectl get deployment,replicaset,pod -n study -o wide`            | 发布、归属候选与节点概况                         |
| `kubectl get events -n study --sort-by=.metadata.creationTimestamp` | 有限保留的事件；按 UID、时间关联，非永久审计记录 |
| `kubectl get service,endpointslice,ingress -n study`                | 服务、端点与入口概况                             |
| `kubectl describe node NODE_NAME`                                   | 节点条件、分配与事件；需要集群级读取权限         |
| `kubectl get pvc -n study`                                          | 卷声明状态；不是挂载成功证明                     |

只读查询和日志访问也需要权限，结果保存前应脱敏。exec、port-forward、临时特权容器或节点诊断可能扩大访问能力，不作为默认动作；确有需要时明确目标、范围和授权。恢复或变更应另走受控流程。

[返回本册目录](/collections/kubernetes/)
