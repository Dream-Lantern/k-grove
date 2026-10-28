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

## 1. Chart 与 Release 分别是什么

Chart 是一组模板、默认值和元数据等组成的包。用户结合 Values 渲染 Kubernetes 对象，通过安装或升级形成一次 Release 的管理记录。一个 Chart 可以形成多个 Release，不能把包名、应用名和发布实例名混为一谈。

Chart 的 `version` 与 `appVersion` 也不是同一个版本号。升级 Chart 可能修改模板、依赖或默认值，即使应用版本没变，也应审核实际渲染差异。

[![Helm：Chart、Values、渲染与 Release](/assets/notes/kubernetes/k8s-helm-release.svg)](/assets/notes/kubernetes/k8s-helm-release.svg)

Helm 使用相应 Kubernetes 权限执行资源操作，不会因为“它是包管理器”绕过 RBAC 或准入。

## 2. 先理解包内结构

`Chart.yaml` 描述包元数据和依赖；`values.yaml` 提供默认输入；`templates` 保存模板；`charts` 可保存依赖包。模板语法和 Kubernetes 字段校验属于不同层次。

一个模板能成功渲染，只说明模板处理完成，不代表目标集群支持对应 API，也不代表镜像、存储或外部依赖可用。[Helm 3 Chart 结构](https://helm.sh/docs/v3/topics/charts/)

需要明确 Values 各层输入的覆盖关系。多个 `-f` 文件和命令行覆盖会影响最终结果，不能只看编辑过的一个 values.yaml 就认定它是最终生效配置，也要留意命令行值的类型转换。

## 3. 先做不安装的检查

新增教学命令，未执行。路径与 Release 名均为占位，输出可能包含配置秘密：

```bash
helm lint ./chart
helm template study ./chart -f values-study.yaml
helm show values ./chart
```

这些命令适合检查包与模板，但不能替代目标集群的实际验收。模板、插件和依赖应来自可信来源，不应随意执行未知插件或把真实 Secret 打印到终端日志。

Chart 仓库负责包分发，OCI 提供另一种分发方式，索引站点帮助发现资源。使用历史 stable 仓库资料时，需重新核对实际包来源、维护状态与版本。

## 4. 安装、升级与回滚分别改什么

以下只是语法示例，会改变集群，当前未执行：

```bash
helm install RELEASE ./chart -n NAMESPACE -f values-study.yaml
helm upgrade RELEASE ./chart -n NAMESPACE -f values-study.yaml
helm history RELEASE -n NAMESPACE
helm rollback RELEASE REVISION -n NAMESPACE
```

复盘时固定 Chart、依赖、Values、工具版本和镜像引用。不要默认上一次升级的所有输入都会以你期待的方式复用，尤其要审核重置或复用 Values 的选项。

按 Release 历史回滚，并不会自动撤销数据库迁移、消息发送和外部云资源操作的所有副作用。钩子也可能运行具有副作用的任务，因此必须了解包的具体实现。

## 5. 卸载与数据保留

卸载主要按 Release 管理关系处理适用资源。CRD、钩子资源、显式保留对象和持久数据可能有单独生命周期，不能保证“卸载后环境完全恢复为安装前”。

正式维护前列出对象与数据，确认回收策略、备份和业务停机条件；卸载结果需同时核对集群对象与外部资源。

关于命令选项和实际语义，参阅 [Helm 3 文档](https://helm.sh/docs/v3/)，并与使用的具体版本帮助对应。Chart 是可审计的交付包，不能替代应用发布与数据恢复设计。

[返回本册目录](/collections/kubernetes/)
