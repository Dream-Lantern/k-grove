---
id: ai-agent-harness
title: 第1章 AI Agent 基础与 Harness
description: 从上下文、模型决策和工具执行理解 Agent 的工作循环，再认识 Harness 如何管理状态、权限与退出条件。
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
order: 1
---

# 第1章 AI Agent 基础与 Harness

AI Agent 围绕一个目标，反复执行“判断下一步、采取行动、读取反馈”的过程。例如，查找一项配置的使用方法时，它可以先搜索资料，再读取相关文档，最后根据找到的内容组织回答。

理解 Agent，可以先抓住三个组成部分：模型负责决策，上下文提供决策所需的信息，工具负责与外部环境交互。把这些部分组织成可持续运行的程序，就是本章要介绍的 Harness。

## 1.1 Agent 的基本组成 {#_1-1-现代-agent-是什么}

原书用 **Agent = LLM + 上下文 + 工具** 概括 Agent 的基本组成。

| 组成部分            | 作用                   | 包含的内容或例子                                           |
| ------------------- | ---------------------- | ---------------------------------------------------------- |
| LLM（大语言模型）   | 根据当前信息决定下一步 | 回答问题、选择工具、修正计划                               |
| Context（上下文）   | 提供本轮决策所需的信息 | 用户目标、系统指令、任务状态、历史交互、工具结果           |
| Tools（工具）       | 读取或改变外部环境     | 搜索、读取文件、查询数据库、调用 API、执行代码             |
| Harness（工程支架） | 组织运行过程并约束执行 | 驱动循环、维护状态、校验权限、处理错误、记录轨迹、管理退出 |

一次工具调用包含明确的分工：模型提出调用哪个工具、传入哪些参数；Harness 校验请求并执行工具，再把结果交给模型。工具是否执行成功，以实际返回结果和环境状态为依据。

### Agent 与普通 Chatbot / Workflow 的区别

三者可以从“下一步由谁决定”来理解。

| 系统             | 决策与执行路径                                     | 适合的场景                           |
| ---------------- | -------------------------------------------------- | ------------------------------------ |
| 普通 Chatbot     | 主要根据输入生成文本                               | 问答、翻译、解释                     |
| Workflow         | 外层执行顺序由代码预先定义，模型参与其中的局部判断 | 审批、固定流程、确定性操作           |
| Autonomous Agent | 模型根据反馈选择下一步动作                         | 调研、代码修复、需要逐步探索的任务   |
| 混合系统         | 固定流程管理关键状态，模型处理其中的开放问题       | 同时需要灵活决策和执行约束的工程任务 |

选择时可以从任务的复杂度出发：一次模型调用能够完成的任务，保持单次调用即可；步骤固定的任务，适合 Workflow；需要根据中间结果调整动作的任务，再考虑 Agent 循环。

## 1.2 ReAct 循环与轨迹

ReAct（Reasoning + Acting）把推理与行动结合起来。它的基本过程是：**读取上下文 → 判断下一步 → 调用工具 → 观察结果 → 再次判断**。

一轮执行可以拆成五步：

1. **准备上下文。** Harness 将用户目标、当前状态、可用工具和相关历史组织成模型输入。
2. **生成下一步动作。** 模型给出工具调用请求，或生成准备返回的答案。
3. **执行工具。** 对工具调用，Harness 校验参数、权限与执行条件，再调用对应工具。
4. **写入观察结果。** 工具的返回值、错误或状态变化进入上下文，成为下一轮决策的依据。
5. **判断继续或结束。** 根据结果、任务完成条件与剩余预算，继续执行、等待新输入，或结束任务并说明当前结果。

**教学示例：查找配置说明。** 以下是为解释流程而编写的例子，不是实际运行记录。

假设用户要求“查找某个开源项目的配置方法，并附上来源”。第一轮，模型提出搜索请求；Harness 执行搜索，把返回的文档链接与摘要写入上下文。第二轮，模型根据这些结果提出读取文档的请求；Harness 读取内容并返回。资料足够后，模型组织回答，执行侧再按任务要求核对配置说明与出处。

这个例子里，每一轮都会用到上一轮的工具结果。搜索失败、文档无关或信息不足时，后续动作也需要随之调整。

[![Harness：动作分流与退出条件](/assets/notes/ai-agent/01-harness.png)](/assets/notes/ai-agent/01-harness.png)

图中展示教学与建议流程：工具结果回到下一轮，候选答案经过完成条件检查，等待、拒绝和未完成各有出口。具体源码的覆盖范围在第 1.5 节说明。[原始 DOT 语义图源](/assets/notes/ai-agent/01-harness.dot)供对照，不是本版配图的可编辑源文件。

### 最小伪代码

下面的教学伪代码只保留工具调用循环和步数限制，便于对应前面的执行顺序：

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

`messages` 保存模型当前可见的信息；`decision` 是本轮输出；工具执行后，调用请求和返回结果一同追加到 `messages`。达到 `MAX_STEPS` 仍未结束时，循环通过异常退出，避免无限运行。

这里的 `decision.is_final` 演示“返回答案”分支。配图中的完成条件校验、等待与拒绝，以及并行调用、幂等、事务、取消和重试竞态，需要在执行设计中进一步实现。工具输出较大时，也需要控制进入上下文的内容。

## 1.3 Harness 的核心工程能力

基本循环解释了 Agent 如何推进任务。要让任务在失败、断线或多轮交互后仍能继续，还需要管理循环周围的状态和执行条件。

本章把这些职责归纳为六项，方便学习和检查设计：

- **上下文管理：** 保留目标、约束、关键状态和工具反馈，使下一轮能够接着当前进度判断。
- **工具接入：** 提供明确的调用接口，处理返回值、超时和异常。
- **权限控制：** 由执行侧检查调用者身份与操作权限，对需要确认的动作保留批准步骤。
- **状态恢复：** 持久化任务进度和必要状态，在中断后按恢复策略继续。
- **轨迹记录：** 保存模型决策、工具调用与返回结果，便于定位问题。
- **结果验证：** 通过工具读回、测试或独立校验，判断任务是否达到目标。

这些能力对应着具体的运行问题：

| 运行问题                       | 典型原因               | 对应措施                         |
| ------------------------------ | ---------------------- | -------------------------------- |
| 反复调用同一工具，没有进展     | 缺少有效反馈或结束判断 | 步数上限、无进展检测、失败分类   |
| 执行了未获准的操作             | 执行侧没有落实授权检查 | 服务端鉴权、确认、幂等、防重放   |
| 中途断线后丢失任务             | 状态只保存在进程内存中 | 持久化状态、Checkpoint、恢复策略 |
| 输出看似完成，实际结果不正确   | 缺少环境读回或验证     | 测试、工具读回、独立校验         |
| 历史越来越长，关键信息难以定位 | 所有中间内容持续累加   | 状态摘要、检索、分层压缩         |

例如，同一搜索请求连续重复且没有新增信息，可以触发无进展检测。此时系统应根据剩余预算选择调整方案、请求补充信息，或以“未完成”结束，并保留失败原因。

## 1.4 教学案例：性能评测任务的组织 {#_1-4-工程思考-评测任务的-agent-应该如何设计}

下面用一个简化的性能评测任务说明 Agent 与固定流程的配合，不涉及具体平台的内部实现或实测成果。

任务可以按以下顺序组织：

**理解测试意图 → 生成方案 → 用户批准 → 冻结配置 → 执行 Benchmark → 分析证据 → 输出报告。**

在前半段，LLM 帮助理解用户描述、提出方案并解释选择。执行前，由固定流程完成配置校验、权限检查和用户确认，将批准后的配置保存下来。执行阶段调用评测工具，记录真实状态与结果；分析阶段再把这些结果交给模型，用于解释现象和组织报告。

这里的职责分界很重要：SLO 边界比较、配置校验、权限、任务状态变更和资产冻结由确定性服务处理。任务创建成功，应以数据库或工具返回的状态为依据；LLM 根据这些已确认的信息向用户说明进度。

## 1.5 从源码看懂一次 Agent 循环

理解前面的概念后，可以继续阅读原书配套仓库中的实现。本节引用固定提交 `dbc046eb896ac4e39aa19c7774c8bf49583b89a6`；教学图与伪代码用于说明执行设计，不表示该提交已经完整实现图中所有分支。本章也没有给出这些设计的实机验证结果。

建议分两条线阅读：

| 阅读入口                    | 观察内容                                           |
| --------------------------- | -------------------------------------------------- |
| `chapter1/web-search-agent` | 一次调用如何形成轨迹，工具返回后如何进入下一步     |
| `chapter1/context`          | 提供给模型的消息发生变化后，模型能看到哪些任务信息 |

`web-search-agent` 的离线模式使用预写轨迹，适合对照调用、观察和结束的顺序。真实搜索能力与任务成功率需要另用实际模型、工具和任务验证。

### 上下文选择与源码节选

`ContextMode` 提供 `FULL / NO_HISTORY / NO_REASONING / NO_TOOL_CALLS / NO_TOOL_RESULTS` 五种配置，用来改变本轮发送给模型的消息。可以先看 `_prepare_messages_for_api()` 中的 `NO_HISTORY` 分支：它保留系统消息和最后一个用户任务，去掉该任务之后累积的交互记录。

这样，模型下一轮仍能看到任务目标，但看不到之前的工具结果。这个具体变化，有助于理解上下文如何连接多轮执行。

::: details 可选阅读：NO_HISTORY 源码节选

节选来自 [chapter1/context/agent.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/context/agent.py#L678-L692)，其上下文和依赖见原文件。

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

:::

### 上下文消融的对照方法 {#如何做一个有解释力的对照}

消融实验通过移除某类输入，观察它对任务的影响。可以先在原仓库 `chapter1/web-search-agent` 运行 `python main.py --provider offline-demo --output demo.json`，对照 `trace` 与 `answer` 标出调用、观察和结束；再配置提供商，在 `context` 中对同一任务运行五种配置。

比较时固定工具、输入文件、模型版本、预算和随机性配置，每种配置重复多次，保存每轮请求与工具返回。观察任务正确性、工具调用次数、重复动作、异常类型，以及最终答案引用的证据。

实验结果要结合实际输入解释。删除调用记录可能造成工具协议错误，这类错误应单独记录。移除 reasoning 字段后任务仍然成功，只能说明当前任务、模型与接口下没有观察到退化。reasoning 字段的可见性取决于接口，不能据此判断模型是否进行了内部推理。

完整的读码顺序可以串成：`ContextMode` → `_prepare_messages_for_api()` → `execute_task()` → 工具结果消息。做工程练习时，再依次补上预算管理、错误分支和结束验证。

### 源码与实验入口

- [chapter1/context/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/context/README.md)
- [chapter1/web-search-agent/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/web-search-agent/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter1.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

## 本章要点 {#检查理解}

- Agent 通过模型、上下文和工具形成连续的决策与行动过程；Harness 负责组织这个过程。
- 模型输出工具调用请求后，由执行侧校验并执行，实际结果再进入下一轮上下文。
- 任务状态、授权和结果验证需要明确的执行机制；复杂工程任务适合把固定流程与模型决策结合起来。
- 运行过程应有预算、无进展检测和退出条件；等待、拒绝与未完成应分别说明。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
