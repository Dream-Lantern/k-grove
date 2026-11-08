---
id: ai-infra-mixture-of-experts
title: 第 21 章 MoE：路由、专家与稀疏激活
description: "MoE（Mixture of Experts，混合专家）在不同模型中有不同结构。本章以 Transformer 中常见的稀疏专家 FFN 为例：对每个 token 选择部分专家计算，而不是每次使用全部专家。"
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

## 1. 路由器选择专家并处理隐藏向量 {#_1-专家不是人工指定的语义分类器}

专家通常输出隐藏向量，路由器从训练中学习分配；并不保证每个专家对应人能命名的主题，专家 FFN 也不必天然比普通 FFN 简单。

[![MoE：按 Token 路由至部分专家](/assets/notes/ai-infra/moe-routing.svg)](/assets/notes/ai-infra/moe-routing.svg)

图中仅展示两个被选专家和一个未选专家，数字不对应某个产品配置。实际可能存在共享专家、额外路由规则或不同 top-k。

## 2. 被选专家的向量加权示例 {#_2-用向量例子代替情感分数}

教学例：某个 token 的隐藏向量为 `h`，路由器选择专家 1 和 3。若该实现将所选权重归一化为 0.7、0.3，可以写成 `y = 0.7 E1(h) + 0.3 E3(h)`。这里 `E1(h)` 和 `E3(h)` 都是向量。

不同实现的归一化、缩放、共享专家和容量策略可能不同，因此该公式只用于说明加权聚合。不能将几个 token 的标量“情感贡献”取平均，就视为 MoE 层的通用输出。

若隐藏维度为 d、路由专家数为 E，可用一个 E×d 的矩阵计算 `score = Wr × h`，得到 E 个分数。选出 Top-K 索引、计算选中项的门控权重，再把向量发给对应专家（dispatch）。专家批量执行 FFN；输出按原 token 归位并加权相加（combine），随后流入 Transformer 的后续计算。Softmax、Top-K、选中项归一化的顺序依模型而定，也有用 sigmoid 打分的设计。

若 `E1(h) = [2, -1]`、`E3(h) = [0, 3]`，按图示权重聚合得 `y = [1.4, 0.2]`。共享专家若存在，则按模型规定的方式参与聚合。

## 3. 总参数与激活参数要分开

总参数影响存储和部署布局；每 token 激活参数影响部分计算量。稀疏激活不代表没有使用的专家权重就从内存中消失，也不能只按激活参数推算所需显存。只有在明确的 offload 或按需加载实现下，权重驻留策略才会不同。

DeepSeek-V3 是一种具体 MoE 设计，包含 MLA、专家划分及负载均衡等特定机制；它的能力和数字不能推广到全部 MoE，更不能自动等同 DeepSeek-R1 的所有蒸馏模型。[DeepSeek-V3 官方仓库](https://github.com/deepseek-ai/DeepSeek-V3)

若有 8 个路由专家，每个 100M 参数，Top-2 对应 800M 路由专家总参数和每 token 200M 激活专家参数。这个小计之外还有共享模块、Router 和 Attention；驻留与传输按部署布局计算，时延还受批量和通信影响。

## 4. 专家负载、通信与端到端成本 {#_4-为什么专家越多不一定越快}

专家负载分布不均会造成热点，跨设备分发 token 需要通信，较小的专家批次也可能降低计算效率。专家并行通常伴随分发与回收，因此端到端时间应包含网络和等待，不能只统计专家矩阵乘法。

容量限制、token dropping、无丢弃路由及负载均衡策略会改变训练与服务行为，需按具体实现说明。验证时至少看每个专家 token 数、通信时间、长尾和输出质量，不把路由图上的并行箭头当作加速证明。

### 八个 Token 的专家负载

8 个 token 各选 2 个专家，共 16 次分配。令所有 token 选择 E1，第二个选择按下表分配。

| 专家 | Token | 分配数 |
| ---- | ----- | -----: |
| E1   | 1–8   |      8 |
| E2   | 1–5   |      5 |
| E3   | 6–7   |      2 |
| E4   | 8     |      1 |

平均每专家 4 次，热点 E1 为均值的两倍。在每专家同批最多接收 5 次、且超额分配直接丢弃的教学策略中，E1 有 3 次分配被舍弃；本例这些 token 仍有第二个专家。Dropless 实现保留所有分配，需要为不均匀批次预留资源或拆分执行。同步汇合时热点所在设备可能决定何时能继续。

### 两张 GPU 上的 Expert Parallelism

GPU 0 持有 E1/E2、初始 token 1–4，GPU 1 持有 E3/E4、初始 token 5–8。Router 选择后，按专家所有者打包；dispatch 阶段 GPU 1 将 token 5–8 的 E1 分配及 token 5 的 E2 分配送到 GPU 0，其余均在本地。GPU 按专家组成大小为 8、5、2、1 的局部批次，各算各的 FFN。Combine 阶段 GPU 0 回传 5 项专家输出，原 rank 恢复 token 顺序并聚合。本例若每项传一个 d 维向量、每元素 b 字节，分发和回传各为 5db 字节的跨卡载荷。索引、对齐、填充、同 rank 去重和协议开销另按实现计算。

All-to-All 描述各 rank 按目标交换不等量数据的模式，本例只在一个方向有远端分发。实现可以用 All-to-All 类集合通信或专用通信 kernel，通信与专家计算有时能分块重叠。EP 将专家分布到不同 rank；TP 拆分单个张量或算子；DP 处理不同请求子批。在部分引擎中 Attention 采用 DP、MoE 层在这些 rank 间用 EP。节点内 NVLink/PCIe 与节点间链路的带宽、时延和争用决定跨设备的代价。

在 vLLM v0.10.2 的 EP 部署中，用 `--enable-expert-parallel` 启用，EP 组大小按 `TP × DP` 组织；该版本部署指南的示例取 TP=1。文档给出的 DeepEP 示例使用 `VLLM_ALL2ALL_BACKEND=deepep_high_throughput` 做高吞吐路径，`deepep_low_latency` 做低延迟路径。使用前核对 DeepEP 构建、GPU、节点拓扑和部署方式。Prefill 通常能合出较大的 expert batch，矩阵乘法和链路启动开销较易摊薄；Decode 常是较小的 expert batch，dispatch/combine 和热点等待可能显著影响 ITL。具体收益取决于 batch、路由分布及互联。[vLLM v0.10.2 专家并行部署](https://docs.vllm.ai/en/v0.10.2/serving/expert_parallel_deployment.html)

### 训练均衡与推理均衡

训练时可通过辅助损失鼓励专家使用均衡，也可像 DeepSeek-V3 一样根据专家负载调整 Top-K 选择偏置。训练实现还可能通过 capacity 控制每步批量，并规定超额分配是否丢弃。推理时可以静态放置专家；支持冗余专家的系统也能复制热点专家，在副本间分配 token，或者根据负载重排专家位置。额外副本消耗显存，重排涉及权重传输、协调及路由映射更新。DeepSeek EPLB 是按统计负载规划冗余专家及放置的工程例子，部署是否能在线更新映射要看服务框架。[DeepSeek EPLB](https://github.com/deepseek-ai/EPLB)

### DeepSeek-V3 实例

以初代 DeepSeek-V3 基础结构为例，官方技术报告 v2 给出总参数 671B、每 token 激活 37B。每个 MoE 层有 256 个路由专家和 1 个共享专家，每个 token 选 8 个路由专家；前三层用稠密 FFN。MLA（Multi-head Latent Attention）属于注意力，专家选择发生在 MoE FFN。报告的主负载均衡机制使用基于负载的选择偏置，同时还有序列级辅助项。其报告中的分布式部署利用 EP 与拓扑感知通信；工程部署需为驻留权重、缓冲和节点间通信留出预算，具体 rank 和后端由部署方案决定。上文的 vLLM 参数是引擎配置。[DeepSeek-V3 技术报告 v2](https://arxiv.org/abs/2412.19437v2)、[DeepSeek-V3 官方配置](https://huggingface.co/deepseek-ai/DeepSeek-V3-Base/blob/main/config.json)

## 5. 把 MoE 层放回隐藏向量计算

设 token 隐藏向量 `h∈R^d`，路由选择专家集合 `T(h)`，可用 `y=Σ[e∈T(h)] g_e(h) E_e(h)` 表示加权输出，是否归一化由实现确定。每个被选专家的输出需要能参与相同隐藏维度的组合；它不是对所有 token 的情感分数求平均。

在具体 Transformer 中，MoE FFN 输出还会按该模型的 residual、normalization 等结构继续流动，不能把一个通用路由图当成完整层定义。Switch Transformer 的 top-1 也是一类具体设计，不等于所有 MoE 都只选一个专家。[Sparsely-Gated MoE](https://arxiv.org/abs/1701.06538)、[Switch Transformers v3](https://arxiv.org/abs/2101.03961v3)

讨论“更高效”时，至少应说明比较的是同总参数、同激活计算量，还是同质量模型；这些基线回答的问题不同。还应分别记录驻留权重、分发/回收通信和专家负载，避免只关注稀疏激活而忽略内存与长尾成本。

## 6. 用时间账本定位长尾

简化的无重叠账本为 `T_MoE ≈ T_route + T_dispatch + T_expert + T_combine + T_other`。假设两张 GPU 的一个教学步骤先花 0.10 ms 路由、0.40 ms 分发，之后 GPU 0 的热点专家批花 0.90 ms、GPU 1 花 0.40 ms。GPU 1 先结束并等 0.50 ms，关键路径上的专家阶段仍只计 0.90 ms。回传与汇合花 0.30 ms，其他开销花 0.20 ms，总计 1.90 ms。存在计算通信重叠时，应从 trace 看实际关键路径。小 batch 的专家算子效率和热点 rank 的等待都可能成为瓶颈。

## 7. 验证专家并行与尾延迟

固定模型与路由规则、精度、软硬件版本、生成参数和请求分布。单卡可部署时，以单卡为基线对照 EP=2，分别改变输入长度、batch、专家负载分布和支持的通信后端。区分 Prefill 与 Decode，记录总参数和每 token 激活参数、各 rank 驻留权重与峰值显存、每专家 token 数、分发/回传时间、专家计算及等待、TTFT/ITL/TPOT、输出吞吐和质量、失败率。使用同一批输入比较不同部署，分别报告热点和均匀负载，并标明拓扑。这些是实验设计，时间账本为教学数据。
