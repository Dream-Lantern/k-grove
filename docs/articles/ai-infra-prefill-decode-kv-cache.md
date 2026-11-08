---
id: ai-infra-prefill-decode-kv-cache
title: 第 19 章 大模型推理：Prefill、Decode 与 KV Cache
description: "自回归语言模型通常先处理输入，再逐步生成输出，对应 prefill 和 decode 两个阶段。前者建立输入上下文的状态，后者在已有状态上继续生成。"
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
order: 19
---

# 第 19 章 大模型推理：Prefill、Decode 与 KV Cache

自回归语言模型通常先处理输入，再逐步生成输出，对应 prefill 和 decode 两个阶段。前者建立输入上下文的状态，后者在已有状态上继续生成。沿这两阶段观察 KV Cache、调度与计时，可以把首字延迟、生成间隔和显存需求联系起来。

## 1. 从 Prefill 进入逐步 Decode {#_1-一次请求如何推进}

prefill 处理输入 token 并建立相应注意力状态；decode 在已有上下文基础上逐步产生新 token，并追加所需状态。两阶段的瓶颈会随 batch、上下文和模型而变化，不能写成“prefill 永远计算密集、decode 永远带宽密集”。

[![LLM自回归推理：Prefill到Decode](/assets/notes/ai-infra/llm-serving.png)](/assets/notes/ai-infra/llm-serving.png)

continuous batching 允许在迭代调度中加入和移除请求，无需让整个静态 batch 等待最长的请求。它仍然受到队列、公平性和资源约束的影响，并发增加并不意味着吞吐和延迟都会改善。

### 四个输入 Token 如何生成两个输出 Token

Embedding（嵌入）把输入 Token ID 转为向量。每层将隐藏状态投影为 Q（Query，查询）、K（Key，键）和 V（Value，值）。普通缩放点积注意力可写为 `Attention(Q,K,V) = softmax(QKᵀ / √dₖ + M)V`，其中 `dₖ` 为每头的键维度。点积给出 Attention Score（注意力分数），缩放控制其幅度。Causal Mask（因果掩码）`M` 将未来位置置为负无穷，沿键位置做 softmax 后加权求和。

1. Prefill（预填充）处理输入 `p1…p4`。同一层可以并行处理四个位置，但 `p2` 只看 `p1,p2`，而 `p4` 可以看全部输入。将各层四个位置的 K、V 放入 KV Cache（键值缓存），由最后位置的输出 logits 采样 `y1`。
2. Decode（逐步解码）把 `y1` 送回模型。每层用当前 Q 查询过去四个位置和当前的 K、V，缓存增到五个位置，再从输出采样 `y2`。如果已达到长度上限或采到停止符，此时可以结束。`y2` 已输出，只有继续作为下一轮输入时才会计算并缓存它的 K、V。
3. 图示沿单请求展示首 Token 和后续循环，KV 读写细节见上述步骤，多请求调度见第 4 节。缓存写入、采样和第一次 decode 调用的边界由模型和引擎实现决定，预填充与首 Token 事件也应分别观测。

### 两种负载的侧重点

A（8192 输入、128 输出）有更长的 Prefill，普通全注意力中因果配对数量随输入长度近似平方增长。较大的 Token 批能摊销模型权重读取，也可能遇到计算或工作区瓶颈。B（128 输入、4096 输出）有更多串行生成迭代，低批量时反复读取权重，KV 也随迭代增长。每步的注意力需要访问越来越长的历史。增大 Decode 批量可摊销权重读取，却也增加 KV 流量和等待。A 虽然输出短，解码时仍要查询很长的输入。Compute Bound（计算受限）和 Memory Bound（内存受限）需结合模型、批量、上下文、精度和硬件测量。

## 2. KV Cache 复用历史 Key 与 Value {#_2-kv-cache-缓存的不是最后回答}

注意力计算可以复用历史 token 的 key/value。KV cache 的大小与层数、KV head 数、head dimension、已缓存 token 数和数据类型有关。PagedAttention 将逻辑 token 与非连续物理块关联，改善相应内存管理，并不是增加 GPU 的实际显存容量。[vLLM Paged Attention](https://docs.vllm.ai/en/latest/design/paged_attention/)

对普通全注意力 decoder，在未分片、未压缩、未考虑特殊层结构的简化模型中：

```text
KV 字节数 ≈ 2 × 层数 × KV heads × head_dim × 已缓存 token 数 × 每元素字节数
```

前面的 2 表示 K 与 V。使用 GQA/MQA 时应填 KV heads，而不是 query heads；MLA、滑动窗口、量化、分片和前缀共享需要另建模型，不能盲套该公式。

式中层数只计写缓存的注意力层，KV heads 是每层实际存储的 K/V 头数，head_dim 是每头元素数，缓存 Token 是本轮累计位置数，元素宽度以字节计。GQA（Grouped-Query Attention，分组查询注意力）由多个查询头共享一组 KV，MQA（Multi-Query Attention，多查询注意力）通常共享单组 KV。MLA（Multi-head Latent Attention，多头潜在注意力）可存压缩的潜在状态，须依据具体后端布局估算。滑窗或局部层按实际保留位置计算，量化还需计尺度等元数据。TP（张量并行）可能拆分或复制 KV 头，PP（流水线并行）按层放置。要按 GPU 分别建账。

### 分页与共享

PagedAttention 将每个请求的 Logical Block（逻辑块）通过 Block Table（块表）映射到设备上的 Physical Block（物理块）。引擎从 Free Block Pool（空闲块池）按需领块，末块未满时追加；跨边界时增加映射。假设 Block Size 为 16 Token，A 有 17 Token，需要 2 块，尾部闲置 15 槽；B 有 31 Token，也需要 2 块，尾部闲置 1 槽。每个请求不再需要一整段连续显存，仍会有尾块开销。

Prefix Sharing（前缀共享）可让匹配前缀引用同一物理块。Reference Count（引用计数）防止一方退出时提前回收共享块，释放后还可能保留为可淘汰前缀。若实现允许共享可写尾块，分支继续写前应采用 Copy-on-Write（写时复制），以保留另一分支的内容。只共享完整块的实现可让尾块保持私有。块表、哈希和引用计数都有开销，池的预留容量与活跃 KV 字节数分开记录。[vLLM v0.10.2 PagedAttention](https://docs.vllm.ai/en/v0.10.2/design/paged_attention.html) · [PagedAttention 原论文](https://arxiv.org/abs/2309.06180)

## 3. 分别定义首字、生成间隔与吞吐 {#_3-ttft、tpot-和吞吐不是一个数字}

TTFT 是请求到首个输出 token 的时间，通常包含排队和 prefill；TPOT 描述后续输出 token 的时间间隔，需注明计算和聚合定义。吞吐应区分输入 token、输出 token、请求数以及稳定时间窗口。

同一配置可能提高吞吐，却让 p99 变差。报告必须注明输入/输出长度分布、并发或到达率、流式/非流式、是否包含 tokenization，以及是否排除了失败和超时请求。不能将“某模型 85ms”视为引擎的通用延迟。

## 4. 四项常见优化解决不同问题

前缀复用减少重复上下文工作；chunked prefill 限制长提示一次占用的调度工作量；CUDA Graphs 降低适合路径的提交开销；speculative decoding 用候选生成和验证改变解码过程。是否有效需核对后端支持、模型和输出质量，不能只看功能名称。

优化前先明确目标是降低 TTFT、稳定 TPOT 还是提高容量，然后保持质量与错误率约束。如果没有这些目标，调大并发或显存比例通常只会把一个瓶颈移到另一个位置。

### 连续批处理与分块预填充

Continuous Batching（连续批处理）在每轮重新组织 Waiting Queue（等待队列）和 Running Batch（运行批次）。以 A=512 输入/128 输出、B=4096/64、C=128/512 为例，假设每轮 Token Budget 为 1024，KV 块可用，优先保留已有 Decode，再调度部分 Prefill（Chunked Prefill，分块预填充）。以下是教学策略，非任何引擎的固定顺序。

| 迭代 | 运行与等待变化                                                     |    Token 预算用量 |
| ---- | ------------------------------------------------------------------ | ----------------: |
| 1    | A 完成 Prefill 并出首 Token，B 完成第一块，C 等待                  |         512 + 512 |
| 2    | A 解码一步，C 加入并完成 Prefill，B 继续分块                       |     1 + 128 + 895 |
| 3–4  | A、C 各解码一步，B 每轮继续预填充                                  | 每轮 1 + 1 + 1022 |
| 5    | B 处理最后 645 个输入位置并出首 Token                              |       1 + 1 + 645 |
| 后续 | B、A、C 各达到停止条件后退出，释放自己的 KV 块引用，等待请求可补入 |    随活跃请求变化 |

每轮还需要为新输入位置分配块或使用尾块，预算有余但 KV 池不足时也可能无法接纳请求。拆分 B 可减少单轮阻塞，但小块带来更多调度或 kernel 开销，过小的预算也会拖长 B 的 TTFT。静态批处理通常等整批完成再补入新请求。连续批处理的收益取决于负载、优先级、显存和调度公平性。

### PD 分离

PD Disaggregation（Prefill-Decode Disaggregation，预填充与解码分离）把两类工作调度到独立实例。路由器安排 Prefill 生成上下文状态，再让 Decode 实例通过传输层接收并导入 KV 与必要的请求状态，继续生成。可按长短请求比例分别配置两类资源池，也能减少长 Prefill 对 Decode 节奏的干扰。代价包括 KV 传输、接收缓存、跨实例等待、两端负载失衡及故障处理。若请求短或网络慢，交接可能超过节省的排队时间。Attention 的数学定义保持一致。

以 vLLM v0.10.2 为例，分块 Prefill 使用 `--enable-chunked-prefill` 和 `--max-num-batched-tokens`，前缀缓存用 `--enable-prefix-caching` 或 `--no-enable-prefix-caching` 做对照。PD 由独立实例配合 KV connector，`--kv-transfer-config` 配置角色及传输。可用 connector、硬件和版本要求按对应部署文档确认。[vLLM v0.10.2 引擎参数](https://docs.vllm.ai/en/v0.10.2/configuration/engine_args.html)、[vLLM v0.10.2 PD 部署](https://docs.vllm.ai/en/v0.10.2/features/disagg_prefill.html)

## 5. 用一个教学配置算清 KV 的量纲

假设普通全注意力 decoder 有 32 层、8 个 KV heads、每 head 128 维，K/V 每元素 2 字节；8 个请求各实际缓存 4096 token，且无共享前缀、无分片或压缩。这是人为配置，不对应某个已测模型。

```text
总缓存 tokens = Σ T_i = 8 × 4096 = 32768
KV 字节 ≈ 2 × 32 × 8 × 128 × 32768 × 2
        = 4,294,967,296 bytes = 4 GiB
```

这里先得到全模型的逻辑 KV 数据量，不是每 GPU 实际占用。TP/PP 布局、某些实现的 KV 复制、分页尾块、预留池和元数据还要分别算；请求继续生成时 `T_i` 会增长，不能只用初始 prompt 长度规划峰值。GQA 填的是 KV heads，不能误填 query heads；MLA 等结构也不能硬套本例。

按本例参数，每 Token 为 131072 bytes（128 KiB），每请求 4096 Token 为 512 MiB，8 个请求合计 4 GiB。若每请求再实际缓存 128 Token，新增 `8 × 128 × 128 KiB = 128 MiB`。这是逻辑数据量。池可能预先保留整块空间，新的 Token 有时只填已有尾块。

## 6. 统一计时定义再做统计

令请求发送时刻为 `t0`，第一个输出 token 到达为 `t1`，第 `j` 个 token 到达为 `tj`，共输出 `N` 个 token。新增示意定义如下，实际 benchmark 还需说明网络、tokenization 和流式分包边界。

| 指标        | 本册示意定义           | 统计注意                                       |
| ----------- | ---------------------- | ---------------------------------------------- |
| TTFT        | `t1 - t0`              | 可能含排队和 prefill；标明客户端还是服务端计时 |
| 单间隔 ITL  | `tj - t(j-1)`，j≥2     | 看分布，可能被网络分包聚合影响                 |
| 单请求 TPOT | `(tN - t1)/(N-1)`，N>1 | N=1 时无定义；不是所有 token 间隔的 p99        |
| E2E         | `tN - t0`              | 最终完成事件的定义需固定                       |

按请求平均 TPOT、按 token 汇总 ITL，以及先计算每个请求的 p99 再取平均，属于不同的统计方式。一次响应 chunk 还可能包含多个 token，因此不能将 chunk 到达间隔直接视为逐 token ITL。

以客户端发送为 `t0=0 ms`，四个 Token 分别在 500、550、620、680 ms 到达。TTFT（Time to First Token，首 Token 延迟）是 500 ms。三个 ITL（Inter-Token Latency，Token 间隔）分别为 50、70、60 ms。TPOT（Time per Output Token，每输出 Token 平均耗时）为 60 ms，E2E（End-to-End Latency，端到端延迟）按最后 Token 完成定义为 680 ms。服务端 TTFT 应标明从接收请求、入队还是执行起算，并明确结束事件，不能直接与客户端含网络的时间比较。ITL P99 对逐间隔样本求分位数，TPOT P99 对请求级均值求分位数。Output Token/s 与 Request/s 分别用测量窗口内的输出 Token 数与完成请求数除以窗口秒数。超时、失败、截断和无输出应单列分母及计入规则。AIPerf 文档用 ITL 表示请求级平均间隔，采用该工具时要与本文的逐间隔口径对齐。[NIM Benchmarking 2.0.0 指标](https://docs.nvidia.com/nim/benchmarking/llm/2.0.0/metrics)

## 7. 验证容量、调度和前缀复用

固定模型 revision、Tokenizer、推理后端与版本、GPU、精度和测量窗口。每组先预热，记录输入输出实际长度、到达率、并发、批处理配置及请求终止原因。本表是待执行方案。

| 对照                    | 重点记录                                                                            |
| ----------------------- | ----------------------------------------------------------------------------------- |
| 短/长输入与短/长输出    | 理论 KV、实际活跃块、KV Pool、TTFT 与 TPOT                                          |
| 并发与批预算单因素变化  | ITL P99、排队时间、吞吐、池耗尽、拒绝与 OOM                                         |
| Prefix Cache 关闭与开启 | 固定请求顺序，对照未见前缀、热前缀，分别测 0%、50%、100% 前缀重复的负载             |
| 相同到达率下的冷/暖缓存 | 记录实际命中 Token 和块、重算、缓存初始化方式与性能分布。重复相同 Prompt 的结果单列 |

预热 kernel 和预热前缀缓存应区分。容量分析先从理论 KV 起算，再与引擎报告的池大小、块占用及设备峰值核对。[第 20 章](/articles/ai-infra-quantization-memory.html)把 KV Pool 放回完整显存账本。
