---
id: ai-agent-evaluation
title: 第6章 Agent 的评估与可观测性
description: "从结果、过程、效率和安全四个层次理解 Agent 评估，说明任务设计、验证器、指标口径与完整性检查。"
date: '2026-10-25'
updated: '2026-10-28'
category: ai-agent
type: explanation
tags:
  - ai-agent
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-agent
series: agent-engineering
order: 6
---

# 第6章 Agent 的评估与可观测性

## 6.1 评估的目标

Agent 评估通过可复现任务和独立证据，判断**模型、提示词、工具或架构变更对产品的影响**。一个完整的评估流程包含四个彼此相连的要素：

1. 可复现的环境：工具、数据、权限和初始状态可控。
2. 代表性任务：真实需求、边缘情况、失败场景、防止评估数据污染。
3. 独立验证器：优先从环境真值判断成功，无法形式化时再用 Rubric/LLM Judge。
4. 反馈闭环：轨迹诊断 → 提出改进 → 受控实验 → 回归发布。

对比实验要控制变量；消融实验固定其余条件，仅关闭某一组件，以衡量它的贡献。

## 6.2 评估分为结果、过程、效率、安全四层

| 层级        | 指标示例                                   | 主要回答               |
| ----------- | ------------------------------------------ | ---------------------- |
| 结果正确性  | 任务成功率、真实环境状态、一致性           | 事情最终做成了吗？     |
| 过程正确性  | 工具调用正确率、步骤合法率、路径冗余       | 是否按允许的方式完成？ |
| 效率与成本  | 总 Token、LLM 延迟、工具调用费、端到端耗时 | 代价是否合理？         |
| 安全/稳定性 | 越权率、注入成功率、回归率、重试可靠性     | 会不会伤害系统或退化？ |

“API 请求成功率”不等于“Agent 任务完成率”；即使 Agent 的全部调用都返回 200 OK，也可能没有完成业务目标。

## 6.3 Pass@k、Pass^k、Best@k

对固定的一道任务，假设单次成功的概率为 `p`，每次尝试**独立同分布**（简化假设）：

- `Pass@1 = p`：单次成功率。
- `Pass@k = 1-(1-p)^k`：k 次尝试中至少一次成功的概率；体现通过多次尝试能否找到解。
- `Pass^k = p^k`：k 次尝试都成功的概率；体现连续稳定性。
- `Best@k`：必须说明是用真值做oracle最优选择，还是由实际selector挑一个；后者的选择错误与费用要计入系统结果。

例：`p=0.6, k=5`：`Pass@5 ≈ 98.976%`，`Pass^5 = 7.776%`。

**注意**：现实执行之间可能因相同样本、共享环境、随机种子和工具状态而相关，上述公式不是无需前提的通式。正式报告应说明抽样方法、k、独立性假设及重复次数；某些 Benchmark 的 `pass@k` 是特殊的有限样本无偏估计，不可随意混用。

### 先逐题计算，再按声明权重汇总

不同任务有不同`p_i`。在每题内部重复独立的前提下，等权宏平均为：

```text
macro Pass@k = mean_i[1 - (1-p_i)^k]
macro Pass^k = mean_i[p_i^k]
```

两题的成功概率分别为1和0，平均单次成功率为0.5，但按题平均的Pass@5与Pass^5都为0.5。把平均概率0.5直接代入非线性公式，却会得到96.875%和3.125%，不代表该数据集。抽样权重不等时改用预先声明的权重。

HumanEval式有限样本估计：每题采样`n≥k`次，其中`c`次成功，`pass@k_hat = 1 - C(n-c,k)/C(n,k)`；`n-c<k`时取1，再跨题汇总。这依赖相应采样设置；有状态Agent仍需每次环境复位并检查相关性。依据：[HumanEval论文§2.1与附录A](https://arxiv.org/html/2107.03374v2)。

## 6.4 评估数据集和验证器

- **任务代表性**：覆盖常见、边界、长链、失败恢复、注入攻击。
- **初始环境一致**：每条测试用例执行前能复位数据库/沙盒/网页状态。
- **防污染**：Eval 用例与训练样本隔离，动态参数避免硬编码答案。
- **环境真值优先**：创建任务后读数据库、测订单后查真实订单，而不是让模型口头自评。
- **LLM-as-a-Judge**：给出 Rubric、参考答案或证据、评分等级，进行人工校准；尽量不让同一个模型既当唯一选手又当唯一裁判。

## 6.5 统计显著性与置信区间

成功率 `p̂ = successes/n`，独立伯努利近似下 `SE ≈ sqrt(p̂(1-p̂)/n)`。若 `n=100, p̂=0.7`，`SE ≈ 4.58%`，粗略 95% 区间可估计为 `70% ± 9.2 个百分点`。

**注意**：这只是便于解释的正态近似；样本量小、成功率接近 0/1 时可使用 Wilson 区间或二项精确方法。对**相同任务**比较 A/B 两个模型，建议配对统计（例如 McNemar 检验或配对 Bootstrap），而不是把两批结果当独立样本。

另一个随机来源是同一任务重复运行时的生成随机性。应分别说明“任务样本抽样误差”和“重复执行随机波动”，不能用一个误差条笼统表示。

## 6.6 LLM 性能指标与 Agent 端到端指标

| 指标             | 定义                                                    | 注意                                               |
| ---------------- | ------------------------------------------------------- | -------------------------------------------------- |
| TTFT             | Time to First Token，首 Token 延迟                      | 通常只用于流式输出，包含不同服务侧与客户端延迟口径 |
| TPOT             | Time Per Output Token，输出 Token 平均间隔/耗时相关指标 | 不等于所有系统的 ITL 指标定义；要核对具体采集口径  |
| ITL              | Inter-Token Latency，Token 间延迟                       | 可以看每相邻 Token 间分布，需注明是否包含首 Token  |
| E2E latency      | 从请求到最后结果的总延迟                                | Agent 端到端还包含检索、工具、重试及队列           |
| RPS              | Request Throughput，每秒成功/完成请求等定义             | 必须说明是发起速率还是完成速率                     |
| Token throughput | 每秒输入/输出/总 Token                                  | 需声明哪种吞吐，避免混用                           |

Agent 任务的完整时间可以粗分：模型推理、工具执行、网络、排队、框架处理。优化模型 TTFT 不一定改善最终 Agent 任务成功率或总耗时。

### 性能压测示例

比较两个推理 Endpoint 时，要冻结模型/Tokenizer、Dataset/采样、并发、输出约束、预热、重复次数和 SLO 统计口径；否则看到的速度差异可能来自测试工作负载变化，而非部署优化。

对于 SLO 边界测试，故意探索到失败点是正常的；不能按 Grid 的“所有点都 PASS”规则判断边界搜索是否完成。要独立报告：执行状态、搜索结果、证据是否完整、已验证通过/失败两侧。

## 6.7 可观测性：Trace—Span—Evidence

一次任务对应 Trace；模型调用、工具、检索和数据库操作各自形成 Span。每个 Span 建议包含：`trace_id/span_id`、时间、工具/模型版本、输入规模、输出规模、错误、重试、成本、证据引用。注意对 Prompt 和外部结果脱敏。

Trace 负责“发生了什么”，Eval 负责“是否达到目标”，二者联动才能构成改进循环。

## 6.8 从评估到决策

```text
线上观察异常
→ 按任务标签分组定位失败
→ 提出单因素改进假设
→ 同样的评估集、配对实验、重复运行
→ 质量/延迟/成本/安全综合决策
→ 小范围发布并监控
→ 回归集沉淀新的失败案例
```

评估报告应说明**测试条件、相对收益、不确定性和新增风险**，为版本选择提供依据。

<a id="retrieval-metrics"></a>

## 6.9 检索指标的主定义与源码口径

当前仓库的评估源码位于 `chapter7`。`user-memory-system-evaluation/experiment.py` 的 `retrieval_metrics()` 固定看前5个块，并分别返回单查询Hit@5、Recall@5和RR@5；第三个返回值不是跨查询MRR。这段代码能把容易混用的指标拆开。

源码节选（上下文依赖见原文件）：[chapter7/user-memory-system-evaluation/experiment.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter7/user-memory-system-evaluation/experiment.py#L824-L833)。

```python
def retrieval_metrics(retrieved: Sequence[Chunk], relevant_ids: Sequence[str]) -> Tuple[float, float, float]:
    relevant = set(relevant_ids)
    ids = [chunk.chunk_id for chunk in retrieved[:5]]
    hits = [idx for idx, chunk_id in enumerate(ids, 1) if chunk_id in relevant]
    return (
        1.0 if hits else 0.0,
        len(set(ids) & relevant) / len(relevant) if relevant else 0.0,
        1.0 / min(hits) if hits else 0.0,
    )

```

先固定查询集合、相关标注、候选去重和截断k。下面是唯一主定义，其他章节只保留场景例子：

| 指标             | 单查询q的计算                                              | 聚合层级                               |
| ---------------- | ---------------------------------------------------------- | -------------------------------------- |
| 首次相关排名 r_q | 前k个结果中第一条相关结果的1起始位置                       | 未命中时不伪造排名                     |
| Hit@k(q)         | 至少命中一个相关ID取1，否则0                               | 可按查询平均成命中率                   |
| Recall@k(q)      | `cardinality(topk ∩ relevant_q) / cardinality(relevant_q)` | 分母是该查询全部相关文档数；先逐题算   |
| RR@k(q)          | 若`r_q≤k`，取`1/r_q`；未命中取0                            | 一条查询的标量                         |
| MRR@k            | 查询集合上RR@k的平均                                       | 需同时报告有效查询数、排除/UNKNOWN策略 |

空相关集合的查询应按任务单列，不能无条件算成功或漏召回。本地修订示例将其标为UNKNOWN并从MRR分母排除，同时报告覆盖率；这只是明确的约定，不是所有基准的统一规则。[TorchMetrics官方文档](https://lightning.ai/docs/torchmetrics/stable/retrieval/mrr.html)也将query分组、聚合与空标注策略分开。

例如相关集合为 `{A, B}`，返回 `[X, A, Y]`：Hit@5 为 1，Recall@5 为 1/2，RR@5 为 1/2；如果前5名重复出现 A，召回不应因重复而增加。空相关标注在该实现中 Recall 取 0，这是一种实现约定；真实报告中应单列“无答案”任务，避免与漏召回混为一组。

**Hit 与 Recall 的区别**：包含证据的查询比例属于 query-level Hit/Success 指标；集合 Recall 的分母是该查询的全部相关文档数。只有每题恰好一个相关文档等特定设置下，两者才可能数值相同。

### 推荐实验：同一问题上的组件矩阵

先用小规模矩阵比较记忆卡片、RAG、卡片+RAG，再固定主模型，分别调整 Embedding 或 Reranker。每次都记录配置、任务 ID、实际检索片段、最终回答、评判结果、API 错误和原生币种成本。不能同时切换所有模型后，再将收益归因于 Rerank。

[![评估完整性、用量覆盖与结果汇总](/assets/notes/ai-agent/06-eval.png)](/assets/notes/ai-agent/06-eval.png)

图中先检查运行单元与计价覆盖，再汇总质量和成本；缺失项需要单列，已有结果的比较范围随之限定。[放大查看 PNG](/assets/notes/ai-agent/06-eval.png)。[原始 DOT 语义图源](/assets/notes/ai-agent/06-eval.dot)供对照，不是本版配图的可编辑源文件。

读码重点：`RunRecord` 保存一次运行，`completion_assessment()` 检查预期单元是否齐全，`pricing_coverage()` 检查是否有未计价用量，`aggregate()` 才做汇总。存在 API 错误、缺失任务或未计价用量时，必须显式报告；零费用和未知费用不是一回事。

Pass@k 与 Pass^k 的概率式仍保留前文的独立同分布前提。连续多次可靠运行的评价，不能用“多次里至少一次成功”替代。

### 源码与实验入口

- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter7.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

## 6.10 完整性、覆盖与UNKNOWN

记录单元以`task × variant × repeat`标识；A/B对每个任务与重复分别从同一初始状态启动。先逐查询计算，再按任务/变体汇总。缺运行、证据缺失、未计价用量不是0；它们应分别计数并限定哪些结论可判定。可报告已有组件指标，但不能把不完整campaign写成完整的质量/成本优劣比较。

声明检查器也要报语言覆盖、可评估声明数、证据覆盖和UNKNOWN数量，而非只有总分。空轨迹或没有术语覆盖时没有可靠的满分解释；第8章讲证据门禁，第10章讲术语指标。课程中的20条任务只是练习规模，不保证统计显著性或充分功效。

## 本章要点 {#检查理解}

1. Pass@k 衡量多次尝试至少成功一次，Pass^k 衡量连续成功，后者更能反映重复执行的稳定性。
2. HTTP 状态描述请求处理，任务完成需要业务环境中的证据，例如创建后的任务记录与字段读回。
3. 相同任务的 A/B 结果有关联，配对分析利用这一对应关系评价差异。
4. 检索、生成、成本和安全分别评价，并报告缺运行、缺证据与未计价用量。
5. 吞吐比较需固定工作负载、模型、采样与统计口径；不同 Dataset 的差异可能来自输入输出长度变化。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
