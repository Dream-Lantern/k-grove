---
id: ai-infra-mixture-of-experts
title: 第 21 章 MoE：路由、专家与稀疏激活
description: MoE（Mixture of Experts，混合专家）在不同模型中有不同结构。本章以 Transformer 中常见的稀疏专家 FFN 为例：对每个 token 选择部分专家计算，而不是每次使用全部专家。
date: '2026-10-25'
updated: '2026-10-28'
category: gpu-infra
type: explanation
tags:
  - ai-infra
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 21
---

# 第 21 章 MoE：路由、专家与稀疏激活

MoE（Mixture of Experts，混合专家）在不同模型中有不同结构。本章以 Transformer 中常见的稀疏专家 FFN 为例：对每个 token 选择部分专家计算，而不是每次使用全部专家。

## 1. 专家不是人工指定的语义分类器

专家通常输出隐藏向量，路由器从训练中学习分配；并不保证每个专家对应人能命名的主题，专家 FFN 也不必天然比普通 FFN 简单。

[![MoE：按 Token 路由至部分专家](/assets/notes/ai-infra/moe-routing.svg)](/assets/notes/ai-infra/moe-routing.svg)

图中仅展示两个被选专家和一个未选专家，数字不对应某个产品配置。实际可能存在共享专家、额外路由规则或不同 top-k。

## 2. 用向量例子代替情感分数

新增教学例：某个 token 的隐藏向量为 `h`，路由器选择专家 1 和 3。若该实现将所选权重归一化为 0.7、0.3，可以写成 `y = 0.7 E1(h) + 0.3 E3(h)`。这里 `E1(h)` 和 `E3(h)` 都是向量。

不同实现的归一化、缩放、共享专家和容量策略可能不同，因此该公式只用于说明加权聚合。不能将几个 token 的标量“情感贡献”取平均，就视为 MoE 层的通用输出。

## 3. 总参数与激活参数要分开

总参数影响存储和部署布局；每 token 激活参数影响部分计算量。稀疏激活不代表没有使用的专家权重就从内存中消失，也不能只按激活参数推算所需显存。只有在明确的 offload 或按需加载实现下，权重驻留策略才会不同。

DeepSeek-V3 是一种具体 MoE 设计，包含 MLA、专家划分及负载均衡等特定机制；它的能力和数字不能推广到全部 MoE，更不能自动等同 DeepSeek-R1 的所有蒸馏模型。[DeepSeek-V3 官方仓库](https://github.com/deepseek-ai/DeepSeek-V3)

## 4. 为什么专家越多不一定越快

专家负载分布不均会造成热点，跨设备分发 token 需要通信，较小的专家批次也可能降低计算效率。专家并行通常伴随分发与回收，因此端到端时间应包含网络和等待，不能只统计专家矩阵乘法。

容量限制、token dropping、无丢弃路由及负载均衡策略会改变训练与服务行为，需按具体实现说明。验证时至少看每个专家 token 数、通信时间、长尾和输出质量，不把路由图上的并行箭头当作加速证明。

## 5. 把 MoE 层放回隐藏向量计算

设 token 隐藏向量 `h∈R^d`，路由选择专家集合 `T(h)`，可用 `y=Σ[e∈T(h)] g_e(h) E_e(h)` 表示加权输出，是否归一化由实现确定。每个被选专家的输出需要能参与相同隐藏维度的组合；它不是对所有 token 的情感分数求平均。

在具体 Transformer 中，MoE FFN 输出还会按该模型的 residual、normalization 等结构继续流动，不能把一个通用路由图当成完整层定义。Switch Transformer 的 top-1 也是一类具体设计，不等于所有 MoE 都只选一个专家。[Sparsely-Gated MoE](https://arxiv.org/abs/1701.06538)、[Switch Transformers v3](https://arxiv.org/abs/2101.03961v3)

讨论“更高效”时，至少应说明比较的是同总参数、同激活计算量，还是同质量模型；这些基线回答的问题不同。还应分别记录驻留权重、分发/回收通信和专家负载，避免只关注稀疏激活而忽略内存与长尾成本。
