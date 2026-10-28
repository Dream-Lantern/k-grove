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

> Kubernetes 1.28 使用习惯与命令复盘。以下命令未执行；分清查询、连接和变更，避免把文档中的例子当成自动操作脚本。

## 1. 先确认自己连着哪里

kubectl 通过 kubeconfig 等配置确定 API 地址、身份与上下文。上下文还关联默认命名空间；如果不清楚终端使用的默认值，即使命令正确，也可能作用于错误环境。

```bash
kubectl config current-context
kubectl config get-contexts
kubectl get namespaces
```

这组只作查询。不要把管理员 kubeconfig 到处复制当作给普通用户开通访问的方法；应为相应身份分配必要权限。kubeconfig 可能包含秘密，未知来源配置也可能有认证插件等行为，不应直接信任。

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

容器没有 bash 或诊断工具，并不说明应用不健康。临时安装工具会改变现场，必要时应使用经批准的诊断方式。诊断方式应与环境权限和现场保留要求相匹配。

## 4. create、apply、replace、patch

create 主要创建新对象；apply 管理声明式配置并进行适用的创建或更新；replace 用完整对象替换；patch 按选定补丁格式修改部分字段。

apply 并非只是“修改文件里看起来不一样的几行”，还涉及字段管理与冲突。在线 edit 也不会回写版本库。团队应明确声明源、字段管理者和变更审批，不能指望混用命令后各处配置自动保持一致。

新增学习模板，以下不执行。服务端 dry-run 仍会联系集群，diff 也不能在未确认上下文时随意运行：

```bash
kubectl apply --dry-run=server -f app.yaml
kubectl diff -f app.yaml
# 真正变更，仅作语法说明
kubectl apply -f app.yaml
```

客户端 dry-run 不是完整的服务端权限、准入与版本校验，也不能一概保证所有场景完全不进行 API 发现等交互。服务端 dry-run 处理请求但不持久化目标资源，仍不证明运行时和业务可用。[dry-run 与声明式管理](https://kubernetes.io/docs/reference/using-api/api-concepts/)

## 5. 标签和补丁要与声明源协调

`kubectl label` 修改在线标签后，不会因为关闭终端自动丢失；后续控制器或自动化可能覆盖它。标签命令使用 `label` 子命令，筛选值需要与实际标签一致。

JSON Patch 使用 `[{"op": ...}]` 一类操作数组；Merge Patch 使用对象结构。使用 `--type=json` 却传一段合并补丁不是正确组合。不了解字段语义时，不以“服务端接收了”为变更正确性的唯一证明。

## 6. 删除前先形成一份清单

确认对象种类、名字、命名空间、UID、拥有关系与后端数据；说明要级联删除还是孤儿化。删除工作负载不保证关联 Service 或所有存储一并消失，反过来也可能按策略触发数据回收。

`--cascade=orphan` 是显式孤儿化的一种表达，不能继续把旧的 `--cascade=false` 当作当前学习的通用写法。强制删除可能留下仍运行的进程，不作为普通卡顿的第一步。

一次安全变更应包括：保存当前声明和状态、确认影响范围、准备可用的恢复路径、每次只执行一项变更，并观察对象与业务结果。回滚能恢复哪些外部状态，需要事先写清。

[返回本册目录](/collections/kubernetes/)
