---
id: ai-agent-chapter-reference
title: 本地笔记与当前仓库章号对照
description: "本分册按 Agent 基础、上下文、检索、工具、评估与进阶能力组织学习顺序。下表将本站文章对应到参考仓库的正文和源码目录，便于边读原理边定位实现。"
date: '2026-10-25'
updated: '2026-11-12'
category: ai-agent
type: reference
tags:
  - ai-agent
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-agent
series: agent-engineering
order: 92
---

# 本地笔记与当前仓库章号对照

本站按照自身教学顺序重新组织 AI Agent 章节，因此部分章号与参考仓库不同；这不是缺章或源码错误。下表用于定位原始正文和实验，链接均固定到 `dbc046eb896ac4e39aa19c7774c8bf49583b89a6`。本地 `order` 保持不变。

| 本站章节                                                               | 上游正文                                                                                                           | 上游实验入口                                                                                                                                                                      | 对应主题             |
| ---------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| [第1章：AI Agent 基础与 Harness](/articles/ai-agent-harness.html)      | [第1章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter1.md)   | [chapter1/web-search-agent](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/web-search-agent/README.md)                           | 执行循环与运行时     |
| [第2章：Context 工程](/articles/ai-agent-context-engineering.html)     | [第2章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter2.md)   | [chapter2/context-compression](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter2/context-compression/README.md)                     | 上下文组织与压缩     |
| [第3章：Memory 与 RAG](/articles/ai-agent-memory-rag.html)             | [第3章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter3.md)   | [chapter3/retrieval-pipeline](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter3/retrieval-pipeline/README.md)                       | 记忆、索引与检索     |
| [第4章：工具、MCP 与事件](/articles/ai-agent-tools-events.html)        | [第4章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter4.md)   | [chapter4/execution-tools](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter4/execution-tools/README.md)                             | 工具执行与验证       |
| [第5章：Coding Agent](/articles/ai-agent-coding-agent.html)            | [第5章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter5.md)   | [chapter5/coding-agent](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter5/coding-agent/README.md)                                   | 代码修改与反馈       |
| [第6章：Agent 评估](/articles/ai-agent-evaluation.html)                | [第7章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter7.md)   | [chapter7/user-memory-system-evaluation](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter7/user-memory-system-evaluation/README.md) | 任务、指标与证据     |
| [第7章：模型后训练](/articles/ai-agent-post-training.html)             | [第8章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter8.md)   | [chapter8/exact-copy-sft](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/README.md)                               | 复制审计与 SFT       |
| [第8章：持续进化](/articles/ai-agent-continuous-improvement.html)      | [第9章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter9.md)   | [chapter9/trajectory-verifier](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter9/trajectory-verifier/README.md)                     | 轨迹验证与改进       |
| [第9章：多模态与实时交互](/articles/ai-agent-multimodal-realtime.html) | [第6章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter6.md)   | [chapter6/streaming-speech](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/streaming-speech/README.md)                           | 语音流与打断         |
| [第10章：Multi-Agent 协作](/articles/ai-agent-multi-agent.html)        | [第10章](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter10.md) | [chapter10/book-translation](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/README.md)                         | 角色分工与上下文隔离 |

按周实践见 [六周系统学习路线](/articles/ai-agent-learning-exercises.html)；选择其他源码入口、区分本地与上游证据见 [源码实验地图](/articles/ai-agent-source-experiments.html)。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
