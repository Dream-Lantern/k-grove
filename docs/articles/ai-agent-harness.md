---
id: ai-agent-harness
title: 第1章 AI Agent 基础与 Harness
description: 原书的核心公式是：Agent = LLM + 上下文 + 工具。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 1
---

# 第1章 AI Agent 基础与 Harness

> 源码增补基于 `dbc046eb896a`（2026-10-22 获取）；本地编号保持不变。`【源码补充】`为本次读码归纳，代码节选依赖原文件上下文。

**本地阅读编号**：第1章；**当前仓库对应**：第1章。旧版分节号不再作为当前源码定位依据；完整映射仅见[章号对照](/articles/ai-agent-chapter-reference.html)。**与原笔记的关系**：这是原笔记缺失的基础章节，建议优先补习。

## 1.1 现代 Agent 是什么？【书+整理】

原书的核心公式是：**Agent = LLM + 上下文 + 工具**。

- **LLM 是决策内核**：理解用户目标、选择动作、制定或修正计划。推理能力不等于对真实环境天然有正确认识。
- **Context 是可用信息**：系统指令、工具定义、当前任务、对话/工具历史、状态、检索内容等。这决定模型“知道什么”。
- **Tools 是行动渠道**：搜索、数据库读取、代码执行、外部 API、GUI 操作等。这决定模型“能够做什么”。
- **Harness（工程支架）** 是运行时组织和约束：循环驱动、状态和上下文管理、执行权限、审计、超时重试、人机确认、观测与恢复。它并不是把工具名字放入提示词那么简单。

### Agent 与普通 Chatbot / Workflow 的区别

| 系统             | 决策与执行路径                                 | 最适合                     |
| ---------------- | ---------------------------------------------- | -------------------------- |
| 普通 Chatbot     | 主要生成文本，通常没有行动闭环                 | 问答、翻译、解释           |
| Workflow         | 外层执行路径由代码定义，模型用于局部判断       | 审批、固定流程、确定性操作 |
| Autonomous Agent | 模型可以选择下一步工具，视反馈调整             | 调研、代码修复、复杂探索   |
| 混合系统         | 高风险状态转移由工作流固定，开放步骤由模型决定 | 企业级生产 Agent           |

**实践判断**：若一个 LLM 调用就能解决，不要先搭 Agent；若流程固定，优先 Workflow；仅在动作路径确实不可预先枚举时放开自主循环。

## 1.2 ReAct 循环与轨迹【书】

ReAct（Reasoning + Acting）可概括为“判断下一步 → 调用工具 → 观察反馈 → 再判断”。

[本章修订流程图（含失败/未知路径）](/assets/notes/ai-agent/01-harness.svg)

**重要分工**：模型只产生调用请求，不等于已经执行；真正的副作用发生在 Harness 的工具适配器中。

即使是最小循环，也需要最大迭代次数、调用预算、工具错误策略、取消信号和最终结束条件，不能只有一个无限 `while True`。

### 最小伪代码【实践补充】

```python
for step in range(MAX_STEPS):
    decision = llm(messages, tools=tool_catalog)
    if decision.is_final:
        return decision.answer
    request = validate_tool_call(decision.tool_call)
    authorize(request, user_context)
    result = dispatch_with_timeout(request)
    messages.extend([decision, result])
raise StepBudgetExceeded()
```

真实工程还需处理并行调用、幂等键、事务、工具输出截断以及取消与重试竞态。

## 1.3 Harness 的核心工程能力【书+整理】

可以记住六个支撑点：**可见（上下文）、可用（工具）、可控（权限与护栏）、可继续（状态恢复）、可诊断（轨迹）、可验证（评估）**。这是便于记忆的归纳，并非原书逐字列出的“六功能”枚举。

常见失败与对应措施：

| 失败               | 典型原因             | 工程手段                         |
| ------------------ | -------------------- | -------------------------------- |
| 死循环调用同一工具 | 无有效反馈或结束判断 | 步数上限、无进展检测、失败分类   |
| 工具误操作         | 模型把文本当授权     | 服务端鉴权、确认、幂等、防重放   |
| 中途断线丢任务     | 状态仅存在内存       | 持久化状态、Checkpoint、恢复策略 |
| 任务做完却答错     | 没验证实际环境       | 环境读回/测试/独立校验           |
| 上下文越来越乱     | 历史不断累加         | 状态摘要、检索、分层压缩         |

## 1.4 工程思考：评测任务的 Agent 应该如何设计？【实践补充】

一个性能评测任务可分成：**理解测试意图 → 生成方案 → 用户批准 → 冻结配置 → 执行 Benchmark → 分析证据 → 报告**。

LLM 适合处理歧义、提出策略建议和解释结果；SLO 边界比较、执行配置校验、权限、任务状态变更和资产冻结，则应由确定性服务负责。尤其要避免数据库尚未成功写入，Agent 就声称“创建成功”。

## 1.5 从源码看懂一次 Agent 循环【源码补充】

入门时，值得补做 `chapter1/context` 的上下文消融，并阅读 `web-search-agent` 的离线轨迹。前者改变模型本轮实际可见的消息，后者通过预写轨迹展示控制流。离线演示有助于理解代码，但不包含真实模型决策，不能用于证明搜索能力或任务成功率。

`ContextMode` 提供 `FULL / NO_HISTORY / NO_REASONING / NO_TOOL_CALLS / NO_TOOL_RESULTS` 五种配置。读 `_prepare_messages_for_api()` 时，重点看 `NO_HISTORY`：它只保留系统消息和最后一个用户任务，而不是“保留最近一轮”。每轮重新收到同一个任务却看不到过去结果，才是这一消融的具体含义。删除调用记录还可能破坏工具协议，不能把协议错误直接解释成推理能力下降。

源码节选（上下文依赖见原文件）：[chapter1/context/agent.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/context/agent.py#L678-L692)。

```python
messages = self.conversation_history
if self.context_mode != ContextMode.NO_HISTORY:
    return messages

# System prompt(s) are always kept as the static prefix.
windowed = [m for m in messages if m.get("role") == "system"]

# Anchor on the latest user task. Nothing after it is retained: those
# messages are precisely the previous-round history being ablated.
user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
if not user_indices:
    return windowed
last_user_idx = user_indices[-1]
windowed.append(messages[last_user_idx])
return windowed
```

### 如何做一个有解释力的对照

先在原仓库 `chapter1/web-search-agent` 运行 `python main.py --provider offline-demo --output demo.json`，对照 `trace` 与 `answer` 标出调用、观察和结束。再配置提供商，在 `context` 中对同一任务运行五种配置，保存每轮真实请求与工具返回；固定工具、输入文件、模型版本、预算和随机性配置。

记录任务正确性、工具调用次数、重复动作、异常类型和最终答案引用的证据。每种配置应重复多次；若移除 reasoning 字段仍成功，只能说明当前任务/模型/接口下没有观察到退化。隐藏推理不是所有 API 都可见的公共状态，不能用是否返回 reasoning 文本判断模型是否进行了推理。

![01-harness](/assets/notes/ai-agent/01-harness.svg)

图内实线框标固定提交可定位步骤，虚线框区分本地修订示例与建议；不代表整链已经实测。[SVG](/assets/notes/ai-agent/01-harness.svg) · [可编辑 DOT](/assets/notes/ai-agent/01-harness.dot)。

**读码顺序**：`ContextMode` → `_prepare_messages_for_api()` → `execute_task()` → 工具结果消息。后续应优先为 Harness 补充预算、错误分支和终止验证，而不是继续堆叠提示词。

### 源码与实验入口

- [chapter1/context/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/context/README.md)
- [chapter1/web-search-agent/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/web-search-agent/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter1.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html) · 统一验证入口（仅保留于本地审阅资料，公开版不提供）

## 检查理解

1. 为什么“模型会使用工具”不意味着可以忽略 Harness？
2. 怎样解释“模型产生 Tool Call”和“系统执行 Tool Call”的边界？
3. 哪些业务步骤必须由 Workflow 保证，不能完全交给 LLM？
4. 如果一个 Agent 连续四次调用相同搜索工具却没有新结果，系统应该怎样处理？

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。`【书】`、`【整理】`、`【实践补充】`、`【源码补充】`用于区分观点来源与个人归纳，不代表原书逐字转录。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
