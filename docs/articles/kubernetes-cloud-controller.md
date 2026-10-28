---
id: kubernetes-cloud-controller
title: 第三十三章 Cloud Controller Manager 与云集成
description: "Kubernetes 描述 Node、Service 等期望对象，但实际云主机、路由和负载均衡由云平台管理。Cloud Controller Manager（CCM）把适用的云厂商集成职责与核心控制循环分开。"
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
order: 33
---

# 第三十三章 Cloud Controller Manager 与云集成

> 本章以 Kubernetes 1.28 的架构职责为背景，说明 Cloud Controller Manager 如何协调云侧节点、路由与负载均衡；具体提供者的配置需单独核对。

## 1. 为什么把云接口单独抽出来

Kubernetes 描述 Node、Service 等期望对象，但实际云主机、路由和负载均衡由云平台管理。Cloud Controller Manager（CCM）把适用的云厂商集成职责与核心控制循环分开。

CCM 观察相关对象，按云提供者实现和权限调用云接口，再更新相应状态。它不是业务数据包逐次经过的代理，也不等于每种环境都必须安装的通用组件。裸机集群可以采用其他网络与入口实现。

[![云集成：网络与存储分别协调](/assets/notes/kubernetes/k8s-cloud-boundaries.svg)](/assets/notes/kubernetes/k8s-cloud-boundaries.svg)

## 2. 三类常见职责

节点相关控制用于把适用的云侧信息与 Node 状态协调；路由相关控制按网络方案处理所需云路由；服务相关控制可为 LoadBalancer Service 协调云侧负载均衡。

这些能力取决于提供者和部署方式，不能认为每个 CCM 都以同样方式完成全部任务。云接口限额、权限和异步资源创建也会影响协调结果。

例如，Service 的外部地址一直未分配时，应查看服务事件、提供者配置和云侧资源状态，而不是立即重装 kube-proxy。即使外部负载均衡已存在，也不能据此判断后端探测与应用连接正常。

职责框架参见 [Cloud Controller Manager](https://kubernetes.io/docs/concepts/architecture/cloud-controller/)，历史实践还需查对应 1.28 提供者的文档。本章没有验证某个云插件版本。

## 3. 云存储与 CSI 的独立集成路径 {#_3-原架构图中的存储要拆出来}

集群依赖的云网络与云存储各有集成路径。CCM 主要承担适用的云控制职责，卷供应与挂载需要结合存储机制分析。

现代适用的存储集成还涉及 CSI 驱动及相关控制器、节点插件，与 PVC/PV/StorageClass 配合。驱动使用的云凭据、资源权限和数据回收策略，需要独立核对。

同理，外部 DNS 的记录管理不总由 CCM 自动处理。入口 DNS、负载均衡、Service 后端和证书属于多个边界，某个对象已创建不代表整条路径已经完成。

## 4. 权限、费用与清理

云 API 权限应限定在必需的资源和操作范围内，并考虑凭据轮换。配置错误的控制循环可能反复调用接口或遗留资源；实施前也应检查 API 限流、配额和费用。

删除 Kubernetes 对象后，云资源是否自动删除，要看提供者、注解、最终处理与保留策略。不能根据 kubectl 列表里已经没有对象就断言云端已无资源或费用。

网络入口和持久数据尤其需要区分：清理负载均衡与回收云盘是不同风险。清理前应列出准确资源标识与恢复路径，分别确认入口退役和数据保留要求。

## 5. 回到整个学习路线

对象声明期望，控制器与节点组件持续推进，外部系统承担各自实际能力。云集成也遵循这个分工，诊断时应分别观察 API 状态、云端资源和实际数据路径。

阅读具体教程时，先确认版本、实现与依赖，再看命令。是否运行成功、业务是否正确、数据能否恢复、权限是否合适，都需要分别验证，不能仅凭一张绿色状态截图完成验收。

[返回本册目录](/collections/kubernetes/)
