---
id: ai-infra-prefill-decode-kv-cache
title: 第 19 章 大模型推理：Prefill、Decode 与 KV Cache
description: 为什么长提示词影响首字延迟，而生成很长的回答会持续占用显存？自回归语言模型通常可以分为 prefill 和 decode 两个阶段，这有助于把服务指标与资源需求联系起来。
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
order: 19
---

# 第 19 章 大模型推理：Prefill、Decode 与 KV Cache

为什么长提示词影响首字延迟，而生成很长的回答会持续占用显存？自回归语言模型通常可以分为 prefill 和 decode 两个阶段，这有助于把服务指标与资源需求联系起来。

## 1. 一次请求如何推进

prefill 处理输入 token 并建立相应注意力状态；decode 在已有上下文基础上逐步产生新 token，并追加所需状态。两阶段的瓶颈会随 batch、上下文和模型而变化，不能写成“prefill 永远计算密集、decode 永远带宽密集”。

![请求调度、Prefill 与循环 Decode](/assets/notes/ai-infra/llm-serving.svg)

continuous batching 允许在迭代调度中加入和移除请求，无需让整个静态 batch 等待最长的请求。它仍然受到队列、公平性和资源约束的影响，并发增加并不意味着吞吐和延迟都会改善。

## 2. KV Cache 缓存的不是最后回答

注意力计算可以复用历史 token 的 key/value。KV cache 的大小与层数、KV head 数、head dimension、已缓存 token 数和数据类型有关。PagedAttention 将逻辑 token 与非连续物理块关联，改善相应内存管理，并不是增加 GPU 的实际显存容量。[vLLM Paged Attention](https://docs.vllm.ai/en/latest/design/paged_attention/)

对普通全注意力 decoder，在未分片、未压缩、未考虑特殊层结构的简化模型中：

```text
KV 字节数 ≈ 2 × 层数 × KV heads × head_dim × 已缓存 token 数 × 每元素字节数
```

前面的 2 表示 K 与 V。使用 GQA/MQA 时应填 KV heads，而不是 query heads；MLA、滑动窗口、量化、分片和前缀共享需要另建模型，不能盲套该公式。

## 3. TTFT、TPOT 和吞吐不是一个数字

TTFT 是请求到首个输出 token 的时间，通常包含排队和 prefill；TPOT 描述后续输出 token 的时间间隔，需注明计算和聚合定义。吞吐应区分输入 token、输出 token、请求数以及稳定时间窗口。

同一配置可能提高吞吐，却让 p99 变差。报告必须注明输入/输出长度分布、并发或到达率、流式/非流式、是否包含 tokenization，以及是否排除了失败和超时请求。不能将“某模型 85ms”视为引擎的通用延迟。

## 4. 四项常见优化解决不同问题

前缀复用减少重复上下文工作；chunked prefill 限制长提示一次占用的调度工作量；CUDA Graphs 降低适合路径的提交开销；speculative decoding 用候选生成和验证改变解码过程。是否有效需核对后端支持、模型和输出质量，不能只看功能名称。

优化前先明确目标是降低 TTFT、稳定 TPOT 还是提高容量，然后保持质量与错误率约束。如果没有这些目标，调大并发或显存比例通常只会把一个瓶颈移到另一个位置。

## 5. 用一个教学配置算清 KV 的量纲

假设普通全注意力 decoder 有 32 层、8 个 KV heads、每 head 128 维，K/V 每元素 2 字节；8 个请求各实际缓存 4096 token，且无共享前缀、无分片或压缩。这是人为配置，不对应某个已测模型。

```text
总缓存 tokens = Σ T_i = 8 × 4096 = 32768
KV 字节 ≈ 2 × 32 × 8 × 128 × 32768 × 2
        = 4,294,967,296 bytes = 4 GiB
```

这里先得到全模型的逻辑 KV 数据量，不是每 GPU 实际占用。TP/PP 布局、某些实现的 KV 复制、分页尾块、预留池和元数据还要分别算；请求继续生成时 `T_i` 会增长，不能只用初始 prompt 长度规划峰值。GQA 填的是 KV heads，不能误填 query heads；MLA 等结构也不能硬套本例。

## 6. 统一计时定义再做统计

令请求发送时刻为 `t0`，第一个输出 token 到达为 `t1`，第 `j` 个 token 到达为 `tj`，共输出 `N` 个 token。新增示意定义如下，实际 benchmark 还需说明网络、tokenization 和流式分包边界。

| 指标        | 本册示意定义           | 统计注意                                       |
| ----------- | ---------------------- | ---------------------------------------------- |
| TTFT        | `t1 - t0`              | 可能含排队和 prefill；标明客户端还是服务端计时 |
| 单间隔 ITL  | `tj - t(j-1)`，j≥2     | 看分布，可能被网络分包聚合影响                 |
| 单请求 TPOT | `(tN - t1)/(N-1)`，N>1 | N=1 时无定义；不是所有 token 间隔的 p99        |
| E2E         | `tN - t0`              | 最终完成事件的定义需固定                       |

按请求平均 TPOT、按 token 汇总 ITL，以及先计算每个请求的 p99 再取平均，属于不同的统计方式。一次响应 chunk 还可能包含多个 token，因此不能将 chunk 到达间隔直接视为逐 token ITL。
