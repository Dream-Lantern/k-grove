---
id: demo-container-model
title: "镜像与容器：阅读概念图"
description: "用新绘制的简单图示验证图片、代码块和容器分册。"
date: "2026-10-14"
updated: "2026-10-17"
category: engineering
collection: docker
type: explanation
tags: [Docker, 容器, 镜像]
series: container-foundations
order: 10
featured: true
draft: true
source:
  kind: demo
---

# 镜像与容器：阅读概念图

## 区分名称

Docker 镜像用于组织应用运行所需的文件；容器是运行实例。这里仅以概念示意验证页面，不提供安装步骤。

![本地新绘制的镜像到容器关系图](../assets/articles/demo-container-model/model.svg)

## 示意代码

下面是说明阅读顺序的伪代码，不是可执行部署命令。

```text
准备镜像 → 声明运行配置 → 观察容器状态
```

[进入下一篇工作负载条目](./demo-kubernetes-workload.html)。
