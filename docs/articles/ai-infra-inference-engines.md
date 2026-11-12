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

可以从以下项目了解推理服务的实现。FP6、NVMe offload、固定长上下文等不能从“属于同一个生态”直接归到某个独立服务项目。

核对具体支持范围时直接查看项目资料：[TensorRT-LLM](https://nvidia.github.io/TensorRT-LLM/)、[LMDeploy](https://lmdeploy.readthedocs.io/en/latest/)、[DeepSpeed-MII](https://github.com/deepspeedai/DeepSpeed-MII)。不要用过时截图中的星级替代当前支持矩阵。

### 版本化候选范围

以下版本用于定位证据。升级、换镜像、换后端或换模型后要重新填兼容矩阵。

| 候选          | 定位与版本证据                                                                                              | 组合核查重点                                                                                       |
| ------------- | ----------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| vLLM          | 在线批处理和离线推理，架构示例固定 [v0.10.2](https://docs.vllm.ai/en/v0.10.2/design/arch_overview.html)     | 目标后端、分页 KV、前缀缓存、推测解码、多模态、LoRA、结构化输出及 OpenAI 风格 API 按模型与版本验证 |
| SGLang        | 服务调度与前缀复用，源码示例固定 [v0.5.2](https://github.com/sgl-project/sglang/tree/v0.5.2)                | RadixCache、推测解码、并行、多模态和约束生成需要核对后端及模型配置                                 |
| TensorRT-LLM  | NVIDIA GPU 推理与服务，参考 [v1.2.1](https://github.com/NVIDIA/TensorRT-LLM/releases/tag/v1.2.1)            | 按执行后端核对权重转换、FP8/低位 kernel、KV 策略、并行和服务端入口                                 |
| LMDeploy      | LLM/VLM 部署，参考 [v0.18.0](https://github.com/InternLM/lmdeploy/releases/tag/v0.18.0)                     | TurboMind 与 PyTorch 后端的模型、精度、调度、会话能力分别验证                                      |
| DeepSpeed-MII | DeepSpeed-FastGen 服务路径，参考 [v0.3.3](https://github.com/deepspeedai/DeepSpeed-MII/releases/tag/v0.3.3) | 按 MII 的版本与接口验证动态批处理、模型、并行和服务协议，单独审查依赖及维护状态                    |
| Ollama        | 本地模型分发与运行，参考 [v0.40.15](https://github.com/ollama/ollama/releases/tag/v0.40.15)                 | 验证制品、CPU/GPU 分配、原生与兼容 API、并发及服务资源上限                                         |
| llama.cpp     | GGUF 推理运行时与 HTTP server，参考 [v0.9.0](https://github.com/ggml-org/llama.cpp/releases/tag/v0.9.0)     | 按构建验证 CPU/CUDA/Metal 等后端、GPU offload、slot、上下文和协议覆盖                              |

在部署记录中，为每个候选分别填写权重格式、连续批处理、KV 管理、Prefix Cache、Speculative Decoding（推测解码）、TP/PP/DP/EP、多模态、LoRA、结构化输出、流式与 API 协议。每格附模型与后端组合以及 PASS、FAIL 或 NOT TESTED。单机多卡 offload 与集群 EP 分列。

### 请求如何在引擎内推进

HTTP 层解析请求、应用 Chat Template 并分词后，把输入与生成约束交给引擎队列。Scheduler（调度器）在每轮按 token 预算和 KV 余量，从 Waiting Queue（等待队列）接纳请求，更新 Running Batch（运行批次）。Prefill 消化输入，Decode 为已有请求推进输出，模型执行后进行 Sampling（采样），前端按流式或一次性返回。缓存是运行中的资源，分配通常发生在执行前，结束、取消或抢占时按实现释放请求引用。客户端超时应验证是否传成引擎取消，及后台请求、KV 和队列指标何时回落。

vLLM v0.10.2 的 V1 调度器按已计算 token 与目标 token 的差额推进并调用 KV 管理器分配块，可在预算内混合不同阶段；共享前缀可复用匹配的块。SGLang v0.5.2 的 Scheduler 调度新请求和运行批次，RadixCache 用 token 前缀组织树，查找匹配前缀并对活跃引用保护，空闲缓存可淘汰。两个实现的缓存匹配、抢占、取消和回收都应按目标版本观察。CUDA Graph 可在支持的形状重放 GPU 工作、减少 Host 提交开销，也要核对捕获开销、显存和回退路径。[vLLM V1 调度源码](https://github.com/vllm-project/vllm/blob/v0.10.2/vllm/v1/core/sched/scheduler.py) · [SGLang 调度源码](https://github.com/sgl-project/sglang/blob/v0.5.2/python/sglang/srt/managers/scheduler.py) · [SGLang RadixCache](https://github.com/sgl-project/sglang/blob/v0.5.2/python/sglang/srt/mem_cache/radix_cache.py)

## 3. 逐级验收兼容性、质量与容量

先验证能否加载，再判断功能与质量，最后测容量。以第 22 章的四 GPU 服务器部署 7B 或更大模型为例，逐项记录下表结果。任何前置门槛失败的配置应另列。

| 门槛         | 硬约束                                                                                                         | 验收证据                                                                 |
| ------------ | -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| 兼容性       | 架构、模型 revision、Tokenizer、BF16/FP8/INT4 权重及 KV 格式、GPU/Compute Capability/卡数、TP/PP/DP/EP、上下文 | 固定镜像和制品，在目标硬件加载，记录实际 dtype、后端与并行布局           |
| 正确性与质量 | 多模态、LoRA、Structured Output、Streaming、API、输出质量                                                      | 对照协议、取消、边界形状和黄金用例，校验 JSON Schema、任务指标和错误响应 |
| 性能与容量   | 业务到达率、SLO、错误预算和显存余量                                                                            | 固定协议做稳态及峰值测试，用置信范围或重复结果说明波动                   |

## 4. 参数优化要保留回退

prefill chunk、并发上限、静态显存比例和 Graph 覆盖范围相互影响。比如给 KV 留出更多空间可能减少工作区余量，增加 Graph 捕获范围也可能增加内存。先记录默认基线，再一次调整一个因素。[SGLang 调优文档](https://docs.sglang.io/docs/advanced_features/hyperparameter_tuning)

每个候选结果都应附上模型 revision、镜像 digest、引擎版本、GPU、驱动、输入分布和计时定义。正文不应保留“首选”“最佳”“90%+ 利用率”等缺少适用条件的宣传语；技术选型需要说明取舍，而不只是给出排名。

先用同一 GPU 数量和预算跑默认基线，再分别调整 Chunked Prefill、Prefix Cache、KV Pool、Static Memory Fraction、CUDA Graph、Max Running Requests、TP/PP 或量化。用实际 token 预算、图覆盖、池字节与并行布局比较等效条件；同名参数或相同数值也可能有不同语义。每轮调优后重新核查正确性、质量、Goodput、设备资源成本及回退条件。第 19、20 章列出了相应 vLLM 与 SGLang 参数。

## 5. 同一份基准协议再增加 SLO 约束

| 固定项     | 记录内容                                             |
| ---------- | ---------------------------------------------------- |
| 制品与软件 | 模型 revision、量化、引擎 commit/发行版、镜像 digest |
| 硬件与并行 | GPU/SKU/数量、驱动、TP/PP/DP/EP、互连                |
| 负载       | 输入输出长度分布、到达率或并发、流式模式             |
| 过程       | 预热、持续时间、重复次数、计时边界                   |
| 结果       | TTFT/TPOT/ITL/E2E 分位数、吞吐、OOM/失败/超时        |

### 固定并发与固定到达率

Fixed Concurrency（固定并发）常采用 Closed-loop Load（闭环负载），完成一个请求再补一个。忽略思考时间时，20 个在途请求若平均耗时 1 秒，约产生 20 req/s；耗时 2 秒时约为 10 req/s。Fixed Request Rate（固定请求到达率）可用 Open-loop Load（开环负载），按独立时间表发请求。若持续发送 20 req/s，而只能完成 15 req/s，且没有拒绝，队列每秒约积压 5 个请求，尾延迟会继续变化。容量测试应确认稳态、报告积压或拒绝，并记录实际发出与计划发送之间的差距。

### 可复现的测量记录

保存模型、Tokenizer、权重量化、Chat Template、Thinking 模式、采样参数与请求数据的 revision 或摘要。记录 Engine Version/Commit、镜像 digest、Driver、CUDA Runtime、通信与注意力后端。记录 GPU 型号、数量、显存、互连、节点、共享负载和并行布局。将相同请求内容、顺序、输入/输出长度分布、并发或到达序列、流式模式与冷/热前缀状态交给每组。预热与测量窗口分开，按相同次数重复，保留逐请求时间戳、状态和输出。

TTFT（Time to First Token，首 Token 延迟）从客户端发出到首 Token。ITL（Inter-Token Latency，Token 间隔）按逐间隔采样；TPOT（Time per Output Token，每输出 Token 平均耗时）按请求计，不足两 Token 单列。E2E（End-to-End Latency，端到端延迟）需声明最后 Token 或完成事件。各指标记录 P50/P95/P99，并记录 Output Token/s、Request/s、GPU 峰值显存与利用率、质量得分、失败率与超时率。流式 chunk 可能包含多个 Token；无法获取逐 Token 时间时另标 chunk 口径。失败、超时、拒绝、截断以及窗口末尾未完成请求均保留状态与分母规则。

SLO（Service Level Objective，服务等级目标）和 Goodput（满足条件的有效吞吐）需先定义。例如 100 秒内成功完成 1000 个请求，800 个同时满足质量、TTFT 和 TPOT 门槛，则完成吞吐为 10 req/s，Goodput 为 8 req/s。失败和超时不能成为合格请求。测试前确定窗口、完成口径、超时和截断规则，报告全部送入请求数，避免事后排除不利样本。

### 一次版本化压测的入口

以下用 vLLM v0.10.2 的客户端测试一个已经授权、独立部署的 OpenAI Completions 端点。先用真实短请求确认协议和模型名。设置 `BASE_URL`、`MODEL`、`TOKENIZER_DIR` 为该实例 URL、服务模型名与固定版本的本地 Tokenizer。随机负载用于性能对照，质量另跑同一固定用例集。

```bash
vllm bench serve --backend openai --base-url "$BASE_URL" \
  --endpoint /v1/completions --model "$MODEL" --tokenizer "$TOKENIZER_DIR" \
  --dataset-name random --random-input-len 512 --random-output-len 128 \
  --num-prompts 1000 --request-rate 10 --seed 42 \
  --percentile-metrics ttft,tpot,itl,e2el --metric-percentiles 50,95,99
```

先预热并保存缓存状态，再重复运行三次，核对实际发出速率、输出长度、完成与超时计数、分位数和设备峰值。若响应不兼容、发生拒绝或队列持续增长，保留日志及错误样本，按矩阵判定。跨引擎对照需核对相同请求内容和到达序列，不能只比较各自客户端默认结果。[vLLM v0.10.2 benchmark 参数](https://docs.vllm.ai/en/v0.10.2/cli/bench/serve.html)

### 选型报告模板

| 项目            | 填写项                                                |
| --------------- | ----------------------------------------------------- |
| 引擎及模型      | Version / Commit / Digest，Model Revision / Tokenizer |
| 资源            | GPU 型号、数量、显存、拓扑与并行布局                  |
| 兼容性 / 正确性 | PASS / FAIL / NOT TESTED，附日志                      |
| 质量            | 数据集、分数和门槛                                    |
| 时延            | TTFT / TPOT P95、P99，单位 ms，附 ITL/E2E             |
| 速率            | req/s、output token/s、SLO Goodput req/s              |
| 资源峰值        | 每设备 MiB/GiB，附统计来源                            |
| 失败与恢复      | 失败/超时数量及比例、恢复用例和证据                   |
| 最终结论        | 适用负载、限制、资源成本与回退触发条件                |

当前表为模板，所有运行结果为 NOT TESTED。并行与通信机制见[第 22 章](/articles/ai-infra-multi-gpu-nccl.html)，容量和恢复验收见[第 24 章](/articles/ai-infra-capacity-troubleshooting.html)。
