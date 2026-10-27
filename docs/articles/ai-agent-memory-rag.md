---
id: ai-agent-memory-rag
title: 第3章 用户记忆、知识库与 RAG
description: RAG（Retrieval-Augmented Generation，检索增强生成）是让模型在回答前检索有依据的外部信息的流程，不等于存储系统本身；既可以连接知识库，也可以服务于个人记忆。
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
order: 3
---

# 第3章 用户记忆、知识库与 RAG

## 3.1 Context、Memory、Knowledge Base 是三层不同概念

| 概念           | 作用                    | 生命周期               | 典型内容                 |
| -------------- | ----------------------- | ---------------------- | ------------------------ |
| Context        | 本次推理实际看见什么    | 单次模型调用及当前任务 | 指令、对话、检索片段     |
| 用户 Memory    | 跨会话维护个人/任务经验 | 多会话、长期           | 已确认偏好、任务历史     |
| Knowledge Base | 共享领域事实和资料      | 按版本长期维护         | 文档、业务规则、代码规范 |

RAG（Retrieval-Augmented Generation，检索增强生成）是让模型在回答前**检索有依据的外部信息**的流程，不等于存储系统本身；既可以连接知识库，也可以服务于个人记忆。

## 3.2 用户记忆的分类

- **情景记忆（Episodic）**：谁在何时做了什么，依赖事件上下文。
- **语义记忆（Semantic）**：从多条事实抽象的稳定知识或偏好。
- **程序记忆（Procedural）**：执行某类任务的步骤或技能经验。

按保存颗粒度，还可区分：原始轨迹、精炼事实、关联卡片、任务状态。原书比较 Simple Notes、Enhanced Notes、JSON Cards 与 Advanced JSON Cards，强调从简单原子事实向关联结构演进时，表达力上升、维护成本也上升。

示意卡片【实践补充】：

```json
{
  "fact_id": "f-001",
  "subject": "project",
  "predicate": "preferred_report_format",
  "value": "markdown",
  "source": "confirmed_user_preference",
  "observed_at": "2026-10-22",
  "confidence": 0.95,
  "expires_at": null
}
```

**注意**：`confidence=0.95` 只是应用自行定义的元数据，不代表天然经过概率校准。个人信息保存还要有最小化、过期、纠错、删除、权限及审计策略。

## 3.3 记忆的读取与整理

建议设计四条管线：

1. **提取候选**：从交互中识别“长期有用且有权限保存”的信息。
2. **去重/冲突**：与旧记忆比较，处理更正、时效与来源。
3. **检索与注入**：只选择当前任务需要的记忆，避免长期常驻全部细节。
4. **复核与清理**：按时间衰减、显式更正、反馈迭代。

存储内容并非越精简越好，复杂关系可能需要结构化表示；但无论采用何种形式，都不能将模型推测当作已证实的用户事实。

### Mem0、Memobase、LoCoMo

原书把 Mem0 / Memobase 作为记忆系统案例，LoCoMo 用于长对话记忆评估。阅读框架时要拆解：写入时如何抽取、冲突如何解决、如何检索、删除如何实现、评价采用什么任务。**仅看“能记住多少条”不足以评价系统。**

## 3.4 标准 RAG 流程

[本章修订流程图（含失败/未知路径）](/assets/notes/ai-agent/03-rag.svg)

### 分块 Chunking

- 固定长度：实现容易，但可能切断事实上下文。
- 按 Markdown/标题/段落：更有利于保持文档结构。
- 递归分块：按章节→段落→句子逐层细化。
- 父子块：小块负责召回，大块提供上下文，兼顾定位和解释。

分块设计必须与问题类型匹配。例如函数级代码检索更适合符号/文件层级索引，而不是单纯按 500 字符截断。

### Dense / Sparse / Hybrid

| 技术   | 代表              | 擅长                         | 可能的短板                  |
| ------ | ----------------- | ---------------------------- | --------------------------- |
| Dense  | 向量余弦相似度    | 语义近似和同义表达           | 精确编号/专有名词可能漏召回 |
| Sparse | BM25 等           | 代码符号、版本号、精确关键词 | 改写与语义表达较弱          |
| Hybrid | BM25 + Dense      | 兼顾精确和语义               | 融合策略需评测              |
| Rerank | Cross-Encoder/LLM | 对少量候选精排               | 成本和延迟更高              |

典型顺序是召回 TopK → 合并去重 → 重排 TopN → 注入模型；**Rerank 不能修复召回阶段完全漏掉的文档。**

## 3.5 结构化组织与智能体检索

- **RAPTOR**：按层次聚合并摘要，便于从细节到主题层级检索。
- **图增强RAG / GraphRAG**：广义方法用实体、关系或图结构组织检索；不同项目并非同一实现。若特指 Microsoft GraphRAG，还应区分实体周围的 local search 与依靠社区报告的 global search。后者用于“全库主要主题是什么”一类跨全数据集汇总；“某实体关联了哪些对象”更接近局部检索问题。社区发现、报告生成与更新均有成本。依据：[Microsoft GraphRAG Global Search](https://microsoft.github.io/graphrag/query/global_search/)（2026-10-22核查，项目特定机制，不泛化到全部图RAG）。
- **文件系统范式 / OpenViking**：利用目录层次、文件引用、按需查看实现渐进式知识发现；适合 Agent 具有 read/grep/list 等工具的场景。
- **Agentic RAG**：模型判断“需不需要检索、换不换关键词、证据够不够”，可能多轮搜索，但引入更高成本与失败风险。
- **Contextual Retrieval**：在索引时为原本脱离章节语境的块附加相关背景，有助于减少语义断裂。这与“把用户记忆摘要放到每次查询前”是不同的处理环节，不应混为一谈。

## 3.6 RAG 的评价指标与诊断

检索指标的唯一主定义见 [第6章：单查询RR与跨查询MRR](/articles/ai-agent-evaluation.html#retrieval-metrics)。本章使用同一口径：前5名为 `[X,A,Y]`、相关集合为 `{A,B}` 时，Hit@5=1、Recall@5=0.5、RR@5=0.5。只有这一题时MRR也为0.5；不要把单查询的首次相关排名或RR直接称为MRR。

排障时，先确认正确文档是否进入候选池，再检查融合与重排是否改善了它的位置，最后独立验证回答正确性、证据支持与引用准确性。端到端还应记录任务完成率、p95时延、检索/重排用量、过期信息和权限违规情况。检索得分高，并不能替代生成阶段的验证。

## 3.7 工程实验

以 Agent 开发文档问答为任务，做三个版本：BM25-only、Dense-only、Hybrid+Rerank。固定问题集，包含精确符号、同义词、跨文件关系和不存在的答案；比较 Recall@5、引用准确率与 p95 延迟。再引入“未找到可信依据则明确未知”的策略。

## 3.8 用混合检索源码补齐“融合”这一步

优先读 `retrieval-pipeline/fusion.py`。RRF（Reciprocal Rank Fusion，倒数排名融合）不直接相加 BM25 分数和余弦相似度，而按每路排名贡献 `w / (k + rank)`。这避免了量纲不同的问题；`k=60` 是示例默认值，不是针对你的语料验证过的最优值。

源码节选（上下文依赖见原文件）：[chapter3/retrieval-pipeline/fusion.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter3/retrieval-pipeline/fusion.py#L83-L91)。

```python
weights = weights or {}
fused: Dict[str, float] = {}

for source, ranked in ranked_lists.items():
    weight = weights.get(source, 1.0)
    for rank, (doc_id, _score) in enumerate(ranked, start=1):
        fused[doc_id] = fused.get(doc_id, 0.0) + weight * (1.0 / (k + rank))

return sorted(fused.items(), key=lambda kv: kv[1], reverse=True)
```

输入需保证同一路列表中的每个文档只出现一次。这段实现逐项累加得分，因此上游若在同一路重复返回同一文档，就会重复加分。另一个实现 `weighted_score_fusion()` 会先对每路做 min-max 归一化；只有一个候选或所有分数相等时，归一化结果设为 1。理解这些退化情形，比仅记住融合公式更有帮助。

### 推荐实验：型号、同义改写与漏召回

仓库自带相邻产品型号与自然语言查询。先在 `chapter3/retrieval-pipeline` 运行 `python evaluate.py --no-dense --no-rerank --output bm25.json` 建立稀疏基线；再分别启用 Dense、RRF、Rerank，并使用相同的语料、问题、chunk 参数和评测 k。

每条查询保留两路候选 ID、融合后排名、重排后排名与相关标注。再故意让正确文档不进入候选池，验证“重排不能补回漏召回”。首次加载 Dense/Rerank 仍可能下载模型；无 API Key 不等于无需联网或无需模型资源。单进程 CLI 和微服务路径的默认模型可能不同，应以实际参数为准。

[![RAG：混合检索示例](/assets/notes/ai-agent/03-rag.svg)](/assets/notes/ai-agent/03-rag.svg)

配图用于概念与学习流程说明，适用版本和实现边界以正文为准，不代表整链已实测。[放大查看 SVG](/assets/notes/ai-agent/03-rag.svg)。[原始 DOT 语义图源](/assets/notes/ai-agent/03-rag.dot)供对照，不是本版配图的可编辑源文件。

若要继续研究记忆，下一步看 `chapter3/user-memory` 的记忆表示，再用当前仓库第7章的评估器比较相同问题。表示复杂度上升是否有收益，需要通过召回与最终答案分开验证。

### 源码与实验入口

- [chapter3/retrieval-pipeline/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter3/retrieval-pipeline/README.md)
- [chapter3/user-memory/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter3/user-memory/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter3.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html) · 统一验证入口（仅保留于本地审阅资料，公开版不提供）

## 检查理解

1. 为什么记忆和知识库都可使用 RAG，却不是同一层概念？
2. Dense 检索对代码错误码 `E1042` 可能不如 BM25 的原因是什么？
3. 为什么需要区分召回质量和最终回答质量？
4. Contextual Retrieval 是在索引时还是在每次对话中自动“把记忆加到 Query”？
5. 如何确认一个“长期记忆”是用户确认的事实而非模型推断？

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
