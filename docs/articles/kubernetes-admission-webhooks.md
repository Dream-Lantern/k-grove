---
id: kubernetes-admission-webhooks
title: 第二十九章 准入 Webhook 与安全边界
description: 即使调用者通过认证并获得了相应写权限，提交的对象仍可能不满足集群策略。例如，策略可能要求声明某个标签，或禁止某类主机权限。准入机制在适用的对象写入流程中检查这些条件。
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
order: 29
---

# 第二十九章 准入 Webhook 与安全边界

> 以 Kubernetes 1.28 的 admissionregistration.k8s.io/v1 为主。补充原 Webhook 短条目，未部署 Webhook、修改证书或更改准入策略。

## 1. 为什么有权限创建，还可能被拒绝

即使调用者通过认证并获得了相应写权限，提交的对象仍可能不满足集群策略。例如，策略可能要求声明某个标签，或禁止某类主机权限。准入机制在适用的对象写入流程中检查这些条件。

准入不负责用户登录，也不代替 RBAC。GET 查询不是“触发 Pod 创建注入”的同一种流程，不能把所有 API 请求都概括成 Webhook 拦截。

![写请求中的认证授权、适用准入与保存边界](/assets/notes/kubernetes/k8s-admission-webhook.svg)

## 2. 两类 Webhook 与配置资源

MutatingWebhookConfiguration 配置相应的变更 Webhook，可以在允许的机制中修改请求对象；ValidatingWebhookConfiguration 配置验证 Webhook，按条件接受或拒绝。

没有一个标准资源就叫 `admissionWebhook`。Webhook 服务本身也不是仅创建配置对象就自动可用：需要适用的服务地址、证书信任、实现和网络可达。

变更阶段与验证阶段有顺序关系，但不能假定多个变更 Webhook 会按某个未经保证的固定顺序执行。重新调用、默认化和其他准入组件也会影响结果。实现时应考虑幂等，避免重复注入相同字段。[动态准入机制](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)

## 3. 匹配范围决定影响面

配置涉及 API 组、版本、资源、操作和作用范围，还可按支持的选择条件缩小对象范围。Pod 创建与 Deployment 更新不是同一个资源请求，不能只写“拦截应用发布”就说明准确范围。

特别注意命名空间排除与控制面依赖。一个范围过大的 Webhook 若不可用，可能阻塞修复它自身所需的资源写入，形成操作上的死锁。例外设计也要避免变成任意工作负载绕过策略的入口。

本章不生成一个作用于全部资源、忽略全部命名空间差异的配置模板。实际部署前需要先定义策略目标、范围、可用性与恢复方式。

## 4. timeout、failurePolicy 与 sideEffects

`timeoutSeconds` 限制适用调用等待时间。`failurePolicy` 影响调用错误或超时等失败时如何处理，不能理解为“验证明确拒绝也自动忽略”。

`sideEffects` 描述副作用条件，对 dry-run 等行为很重要。Webhook 既要如实声明，也要实际满足：不能一边宣称无副作用，一边在请求中不可逆地写入外部业务系统。

可用性和安全通常需要权衡。遇到调用错误一律放行，可能削弱策略；一律拒绝，则可能在依赖故障时阻塞写操作。应根据目标资源与风险选择，没有适用于所有场景的建议。

## 5. 证书与访问路径

API Server 必须能访问相应 Webhook 服务，并验证预期身份。服务端名字、证书名称与 CA 信任需要一致；不能把跳过验证当成日常修复。

Webhook 服务账户应只获得必要权限，日志不应打印请求中的真实 Secret。控制器返回的错误信息也需要避免泄露敏感对象内容。

故障时先收集 API 错误、配置范围、服务端点、证书有效性和服务日志。修改 failurePolicy 或删除配置会改变全局策略，必须作为受控变更，而不是随手排障步骤。

## 6. 准入通过之后还要验什么

对象保存不保证镜像能拉取、Pod 能调度、应用能启动，也不证明应用具有业务权限。准入是 API 策略边界之一，与容器安全上下文、网络策略和应用认证分别负责不同问题。

可以在明确授权的测试环境中设计允许、拒绝、超时、证书错误、dry-run 和恢复等用例。本次没有执行这些实验，候选稿不声称 Webhook 高可用方案已通过验收。

[返回本册目录](/collections/kubernetes/)
