---
id: ai-infra-quantization-memory
title: 第 20 章 量化与显存预算：低位宽不等于等比例加速
description: 
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
order: 20
---

# 第 20 章 量化与显存预算：低位宽不等于等比例加速

## 1. 量化如何表示数值

一种常见的仿射整数表示为 `q = clamp(round(x/s)+z)`，还原近似值为 `x̂ = s(q-z)`。scale `s`、zero point `z`、量化范围及分组粒度影响误差和元数据开销。对称与非对称量化属于这种模型中的不同选择，不能代表所有低精度格式。

FP16 与 BF16 都是 16bit 浮点，但指数和尾数字段不同：BF16 范围更接近 FP32、精度较低；FP16 范围更窄。低位整数与 FP8 等浮点也不是同一种编码。不能由“位数一样”判断相同精度或相同 kernel 支持。

## 2. PTQ、QAT 与 W4A16

PTQ 在训练后做量化，可能使用校准数据；QAT 在训练中考虑量化误差。W4A16 表示相应权重/激活精度组合，不等于模型中所有张量都以同样方式存放或计算。硬件支持、反量化开销和矩阵形状决定是否真的加速。[Transformers 量化概览](https://huggingface.co/docs/transformers/main/en/quantization/overview)

## 3. 先列显存账本

![模型服务的显存预算组成](/assets/notes/ai-infra/memory-budget.svg)

```text
总显存需求 ≈ 权重 + KV cache + 激活值/工作区
           + CUDA Graph 相关缓冲/内存池 + 通信与框架开销 + 安全余量
```

这些项可能因负载与实现而复用或重叠，因此不能将不同工具报告的 reserved、allocated、缓存池和已用显存重复相加。框架 reserved 所包含的空间，也不一定全部由活跃张量占用。

教学算例：7×10^9 个参数按 16bit 存储，权重约 14×10^9 字节，即约 13.04 GiB；理想 4bit 数据约 3.5×10^9 字节，即约 3.26 GiB。后者还没有包含 scale、其他精度张量与任何运行时内存，不能据此保证“4GB 卡一定可运行”。

## 4. 修正 SGLang 原估算

当前文档将 `mem-fraction-static` 关联到权重和 KV 池的预算比例，并要求为激活和 Graph 等保留空间。原式 `chunked_prefill_size × 1.5 + cuda_graph_max_bs × 2` 没有自洽的字节单位和模型条件，不能用于估算 GB，应删除。[SGLang 参数调优](https://docs.sglang.io/docs/advanced_features/hyperparameter_tuning)

应固定模型、精度、上下文、并发和 Graph 配置，读取启动预算，再测试最坏的 prefill/decode 负载并预留余量。每次增加配额后，都要重新检查 OOM、p99 和质量。

## 5. 正确的 INT8 数值例子

![INT8 的量化、存储和还原](/assets/notes/ai-infra/int8-affine-example.svg)

新增算例设 `x=3.14`、`scale=0.1`、`zero_point=0`，选择对称有效范围 [-127,127]，使用本例明确的就近舍入：`q=clip(round(31.4),-127,127)=31`。存储为 int8 的位串是 `00011111`；还原约为 3.1，`还原值−原值≈−0.04`。这不是把 FP32 的指数或尾数截成整数，也不使用错误的 `01001000`（十进制 72）。

有符号 int8 存储类型可表示 [-128,127]；本例为对称方案选择 [-127,127]，两者不能混为一谈。超过量化范围会发生 clip；数值到半整数时采用哪种舍入规则也需按后端声明。[TensorRT 量化类型与方案](https://docs.nvidia.com/deeplearning/tensorrt/latest/inference-library/work-with-quantized-types.html)

## 6. 权重、激活与 KV 的量化是三项配置

| 对象     | 需要说明的粒度              | 额外问题                                   |
| -------- | --------------------------- | ------------------------------------------ |
| 权重 W   | per-tensor/channel/group 等 | scale/zero-point 元数据，模型格式与 kernel |
| 激活 A   | 输入及层内中间张量的表示    | 范围估计、校准、异常值与动态尺度           |
| KV cache | 注意力缓存的低精度表示      | 长上下文误差、可用后端和缓存格式           |

激活不是“不断更新的输入 token”；token ID 与层内中间张量是不同对象。LoRA/adapter 属于参数适配方法，不会自动压缩基础权重；W4A16 也不表示 KV 使用了 4bit。

表示范围和分辨率可以不同：FP32 为 1/8/23 位符号/指数/显式尾数字段，FP16 为 1/5/10，BF16 为 1/8/7。这里是格式字段说明，不是把所有数都当作 normal finite value；零、subnormal、Inf/NaN 另有编码。一个 π 的舍入例子只反映表示误差，不直接证明模型质量下降多少。
