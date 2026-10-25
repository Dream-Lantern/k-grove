---
id: ai-infra-inference-engines
title: 第 23 章 推理引擎选型：以负载和证据代替星级排名
description: 原笔记为不同引擎列出了星级、固定毫秒数和数倍性能，但没有说明模型、硬件、版本和压测条件，不宜据此选型。本章保留各引擎的定位，用可验证的流程组织选型依据。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 23
---

# 第 23 章 推理引擎选型：以负载和证据代替星级排名

原笔记为不同引擎列出了星级、固定毫秒数和数倍性能，但没有说明模型、硬件、版本和压测条件，不宜据此选型。本章保留各引擎的定位，用可验证的流程组织选型依据。

## 1. 先确认必须支持的组合

模型架构、权重格式、量化格式、GPU 后端、上下文长度、多模态、并行方式、adapter 和结构化输出，可能分别有限制。“支持 NVIDIA”不等于任何 NVIDIA 卡都支持该引擎的所有优化 kernel。

![从兼容性到质量与负载测试](/assets/notes/ai-infra/engine-selection.svg)

## 2. 各项目看什么，而不是谁永远最快

| 项目               | 值得研究的方向                    | 需要实测或单独核查                |
| ------------------ | --------------------------------- | --------------------------------- |
| vLLM               | 服务调度、分页 KV、模型与后端生态 | 特定模型、量化与硬件组合          |
| SGLang             | 请求调度、前缀复用、结构化生成等  | 当前参数、后端与内存策略          |
| TensorRT-LLM       | NVIDIA 平台的推理实现与优化       | 目标 GPU、构建/运行路径及模型支持 |
| LMDeploy           | LLM/VLM 部署与相应后端            | 当前模型、量化和设备支持矩阵      |
| DeepSpeed-MII      | DeepSpeed 生态中的服务路径        | 不混同整个 DeepSpeed 的全部能力   |
| Ollama / llama.cpp | 本地模型管理与相应运行实现        | 模型格式、CPU/GPU 分配和服务边界  |

以上是阅读方向，不是功能完整性承诺。FP6、NVMe offload、固定长上下文等不能从“属于同一个生态”直接归到某个独立服务项目，更不能据此承诺单卡加载任意模型。

核对具体支持范围时直接查看项目资料：[TensorRT-LLM](https://nvidia.github.io/TensorRT-LLM/)、[LMDeploy](https://lmdeploy.readthedocs.io/en/latest/)、[DeepSpeed-MII](https://github.com/deepspeedai/DeepSpeed-MII)。不要用过时截图中的星级替代当前支持矩阵。

## 3. 用两阶段评估节省时间

第一阶段只验证硬约束：模型能否正确加载、指定精度能否运行、输出质量是否达标、功能协议是否满足需求。只要有一项不满足，就应暂停性能比较。

第二阶段固定负载，在可接受的错误率与质量下比较 TTFT、TPOT、输出 token/s、p95/p99、峰值显存和恢复行为。至少包含短输入短输出、长输入、长输出和混合并发，而不是只测一个 batch。

## 4. 参数优化要保留回退

prefill chunk、并发上限、静态显存比例和 Graph 覆盖范围相互影响。比如给 KV 留出更多空间可能减少工作区余量，增加 Graph 捕获范围也可能增加内存。先记录默认基线，再一次调整一个因素。[SGLang 调优文档](https://docs.sglang.io/docs/advanced_features/hyperparameter_tuning)

每个候选结果都应附上模型 revision、镜像 digest、引擎版本、GPU、驱动、输入分布和计时定义。正文不应保留“首选”“最佳”“90%+ 利用率”等缺少适用条件的宣传语；技术选型需要说明取舍，而不只是给出排名。

## 5. 同一份基准协议再增加 SLO 约束

| 固定项     | 记录内容                                             |
| ---------- | ---------------------------------------------------- |
| 制品与软件 | 模型 revision、量化、引擎 commit/发行版、镜像 digest |
| 硬件与并行 | GPU/SKU/数量、驱动、TP/PP/DP/EP、互连                |
| 负载       | 输入输出长度分布、到达率或并发、流式模式             |
| 过程       | 预热、持续时间、重复次数、计时边界                   |
| 结果       | TTFT/TPOT/ITL/E2E 分位数、吞吐、OOM/失败/超时        |

SLO goodput 可定义为窗口中同时满足质量、错误与指定时延约束的成功请求数除以窗口时长；若按 token/s 计，则另写清纳入条件与计数对象。它与把全部成功输出 token 相加所得的裸吞吐不同，不能把不达延迟要求的工作也算成“可服务容量”。

合成算例：100 秒窗口完成 1000 个请求，其中只有 800 个满足预设 SLO，则请求 goodput 为 8 request/s，不是 10。这只是指标示意，不是任何引擎的实测。对输出不足两 token 的请求，TPOT 处理规则也应提前约定，不能事后挑选样本美化结果。
