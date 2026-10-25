---
id: kubernetes-configmap-secret
title: 第二十一章 ConfigMap 与 Secret 配置交付
description: ConfigMap 保存非敏感配置；Secret 为敏感数据提供专门的 API 类型和使用方式。应用镜像、配置对象和 Pod 是不同资源，它们的版本与生命周期也要分别管理。
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
order: 21
---

# 第二十一章 ConfigMap 与 Secret 配置交付

> Kubernetes 1.28 背景。关注配置怎样进入容器、什么时候更新和怎样控制泄露风险。没有创建、读取或输出真实 Secret。

## 1. 把配置与镜像分开

ConfigMap 保存非敏感配置；Secret 为敏感数据提供专门的 API 类型和使用方式。应用镜像、配置对象和 Pod 是不同资源，它们的版本与生命周期也要分别管理。

Secret 中常见的 Base64 是编码，不是加密。它可以直接解码，不应被贴到公开仓库、问题截图或构建日志里。安全还依赖 RBAC、存储加密、传输保护、节点权限及应用如何使用凭据。[1.28 Secret 安全边界](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/secret.md)

`immutable: true` 限制对象数据后续修改，不是磁盘加密或防读取开关。对象更新受限后，配置发布流程也需要采用替代对象等方式管理。

## 2. 环境变量、文件与挂载关系

ConfigMap 和 Secret 都可通过适用的环境变量或卷投射方式提供给容器。配置一般需要在 Pod 所在命名空间可引用，不能靠同名跨命名空间自动找到。

新增教学示例：非敏感应用配置与普通目录投射，镜像为占位；未执行。

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: catalog-config
  namespace: study
data:
  app.conf: |
    listen=8080
    log_level=info
---
apiVersion: v1
kind: Pod
metadata:
  name: catalog-demo
  namespace: study
spec:
  containers:
    - name: app
      image: registry.example.com/study/catalog:DEMO
      volumeMounts:
        - name: config
          mountPath: /etc/study-config
          readOnly: true
  volumes:
    - name: config
      configMap:
        name: catalog-config
```

`volumes` 定义数据来源，`volumeMounts` 定义容器中的挂载位置，通过卷名关联。Deployment 的对应位置在 `spec.template.spec` 内，Pod 则直接在 `spec`；Service 没有这样的容器模板，不能套用这段挂载配置。

## 3. items、subPath 与原目录

`items` 可选择配置键并映射成卷内相对文件路径；`mountPath` 是容器内路径；`subPath` 选择卷内子路径。三者指向不同层级。

把卷挂到已有目录上，会遮蔽该挂载位置原本可见的内容，不等于物理删除镜像中的文件。subPath 可以只挂一个文件，但会改变更新语义。

通过 subPath 投射 ConfigMap 或 Secret 时，不能期待与普通卷投射相同的自动更新效果。如果应用尝试通过软链接等方式处理更新，还需验证其打开文件的方式和实际更新行为，不能把某种路径技巧当作通用的热更新保证。

## 4. 配置更新至少有两个阶段

![配置对象变更、消费方式与应用采用新配置](/assets/notes/kubernetes/k8s-config-delivery.svg)

| 消费方式     | 已运行容器中的典型更新语义 | 还需处理                 |
| ------------ | -------------------------- | ------------------------ |
| 环境变量     | 不随对象修改自动刷新       | 受控替换容器或 Pod       |
| 普通卷投射   | 可能在协调与缓存传播后更新 | 应用是否重新读取或重载   |
| subPath 挂载 | 不提供相同的自动更新效果   | 采用合适的发布或替换方式 |

“文件已变化”与“应用正在使用新配置”需要分别验收。如果应用只在启动时读取一次配置，即使文件已更新，也不会自动采用新内容。不可变对象则需要另一套变更流程。[ConfigMap 消费与更新说明](https://kubernetes.io/docs/concepts/configuration/configmap/)

常见做法包括配置版本化、Pod 模板校验和触发发布，或采用经过审核的重载机制；选哪一种要看应用能力。这里没有安装重载插件，也没有把删除 Pod 当成默认步骤。

## 5. 镜像凭据与服务账户

`imagePullSecrets` 引用适用的仓库凭据，用于镜像获取，不等于把该秘密作为业务环境变量。Pod 可以显式引用，ServiceAccount 等配置也可能影响注入，不能概括成“只对一个 Pod 有效”。

避免把密码放在命令行示例中。生产凭据的创建、轮换和撤销应有独立流程，也要避免在 `get -o yaml`、模板渲染和差异报告中泄露。

本章不展示实际密码。验证时，应检查对象是否存在、引用关系是否正确、挂载或环境配置是否符合预期，以及应用采用了哪个配置版本，不必通过打印真实值来证明“读到了”。

[catalog 案例：配置文件与应用重载约定](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
