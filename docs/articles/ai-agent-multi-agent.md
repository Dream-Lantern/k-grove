---
id: ai-agent-multi-agent
title: 第10章 多 Agent 协作
description: 上下文与拓扑是不同的设计维度，不能只用“有几个 Agent”来描述协作架构。
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
order: 10
---

# 第10章 多 Agent 协作

> 源码增补基于 `dbc046eb896a`（2026-10-22 获取）；本地编号保持不变。`【源码补充】`为本次读码归纳，代码节选依赖原文件上下文。

**本地阅读编号**：第10章；**当前仓库对应**：第10章。旧版分节号不再作为当前源码定位依据；完整映射仅见[章号对照](/articles/ai-agent-chapter-reference.html)。**原笔记已有**：上下文共享、IPC、Peer/Manager/Decentralized、A2A、并发冲突、Loop 失败模式。

## 10.1 先分两个设计维度【书】

**维度一：上下文是否共享**。

- 共享：角色切换时继承完整轨迹，信息丢失少，但长上下文开销高。
- 隔离：子 Agent 只得到任务目标和必要证据，便于并行和权限隔离，但交接质量成为关键。

**维度二：协作拓扑**。

- Peer（对等协作）：Writer↔Reviewer，相互修正，适合少量明确角色。
- Manager/Orchestrator：主 Agent 分解任务并汇总，适合多个独立子任务。
- Decentralized/Handoff：Agent 之间自行移交控制权，适合职责网络和动态路由。

上下文与拓扑是不同的设计维度，不能只用“有几个 Agent”来描述协作架构。

## 10.2 多 Agent 何时值得做【书+整理】

**一个实际检验问题**：多 Agent 是否引入单 Agent 无法廉价获得的**新信息、新能力或有效并行**？

| 情形                                 | 是否适合多 Agent               |
| ------------------------------------ | ------------------------------ |
| 单任务仅需 2～3 次工具调用           | 一般不值得                     |
| 多份互不依赖材料可以并行处理         | 可以考虑                       |
| 需要代码生成与独立执行测试的交叉检查 | 可考虑，因为测试结果是新信息   |
| 仅让三个相似模型读同一段文本互相赞同 | 不一定增益，可能只是成本上升   |
| 需要访问不同机密数据的角色分权       | 适合隔离，但权限必须由系统执行 |

要把 **性能收益、总 Token、总耗时、错误率、协调成本** 放在同一评估框架下。

## 10.3 协作时传递什么【书】

最稳妥的 handoff 不是把全部对话复制过去，而是提供**结构化合同**：

```yaml
handoff:
  task_id: "..."
  role: "Analyzer"
  objective: "判断本次性能测试是否满足批准的 SLO"
  input_refs: ["execution_snapshot", "metric_summary"]
  fixed_constraints: ["使用冻结阈值和统计口径"]
  expected_output: ["PASS/FAIL/UNKNOWN", "evidence", "reason"]
  permission_scope: ["read-only"]
  timeout_seconds: 60
```

子 Agent 给出的结论必须引用可复核的证据，不能用上一 Agent 的口头声明替代实际的数据查询与权限校验。

## 10.4 IPC 与共享文件系统并发问题【书】

IPC（Inter-Process Communication）可类比两种方式：

- 共享文件/存储：读写快且灵活，但面临竞态和覆盖。
- 消息/API：界限清晰，有显式载荷，适合异步；需要投递保障和幂等。

共享工作区中的常见冲突是：两个 Agent 同时修改同一文件，后保存的内容覆盖先保存的内容。可通过 Git worktree/分支隔离、乐观版本检查、细粒度任务划分和合并测试处理。共享数据库任务则需要事务与状态机，不能仅靠提示词要求“别冲突”。

## 10.5 多 Agent 常见失败【书】

1. **成本爆炸**：每个 Agent 重复读全量上下文、反复讨论，未引入新信息。
2. **理解债（Comprehension Debt）**：代码产出很快，团队却跟不上架构演变，不知道做了什么。
3. **认知投降（Cognitive Surrender）**：因为“Agent 总能写”，开发者停止对核心决策的审查。
4. **交接失真**：必要约束在角色转换时遗漏。
5. **循环和责任不清**：多个 Agent 将任务相互推回，没有明确 Owner 与结束条件。

**补充工程建议**：对每个 Agent 设置预算、可调用工具、产物格式、证据标准、完成条件和冲突仲裁方式。

## 10.6 结合 Agent 评测平台做拆分【实践补充】

示例：

[本章修订流程图（含失败/未知路径）](/assets/notes/ai-agent/10-multi-agent.svg)

并非每个盒子都必须是独立 LLM Agent。**Benchmark Worker、校验器和资源调度服务可能应主要由确定性代码实现**。Orchestrator 可保留用户意图分类与解释能力；Planner 可提方案，但持久化写入与状态转换遵守统一业务服务。

对比单 Agent：记录两个版本的任务成功率、方案可执行率、人工返工次数、端到端耗时、Token 总成本、业务规则违反率。只有收益足够明显才继续增加 Agent 数量。

## 10.7 用翻译实验理解管理者上下文隔离【源码补充】

`chapter10/book-translation/agents.py` 的 `run_orchestration()` 是一条值得跟读的实现：Glossary Agent 先生成术语表，章节翻译 Agent 读取必要原文，Proofreading Agent 检查一致性，Manager 依据报告安排修订。Manager 维护任务、进度、文件索引和调用摘要，避免长期持有所有章节全文。

源码节选（上下文依赖见原文件）：[chapter10/book-translation/agents.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/agents.py#L481-L489)。

```python
manager_context = {
    "task": f"把一本{source_lang}技术小书翻译成流畅{target_lang}，保证术语全书一致。",
    "guide": translation_guide(target_lang),
    "plan": list(ORCHESTRATION_PLAN),
    "call_log": [],       # 各 Agent 调用记录（只记摘要，不记正文）
    "file_index": {},     # 文件索引：只存路径
    "progress": {},       # 进度状态
}
manager_peak = 0  # Manager 上下文（其状态序列化后的）token 峰值
```

Manager 上下文峰值小，只能说明管理者局部上下文更轻；所有子 Agent 的 token 加起来仍可能更高。应同时查看 `TokenTracker`、总调用次数、返修次数和质量指标。代码中的术语表是共享契约，也是实验中的额外信息：不能把“有指定术语表”和“没有术语表”的差异全归因于 Agent 数量。

![10-multi-agent](/assets/notes/ai-agent/10-multi-agent.svg)

图内实线框标固定提交可定位步骤，虚线框区分本地修订示例与建议；不代表整链已经实测。[SVG](/assets/notes/ai-agent/10-multi-agent.svg) · [可编辑 DOT](/assets/notes/ai-agent/10-multi-agent.dot)。

### 推荐消融与公平基线

以同一组章节、同一模型和相同质量要求，对照单 Agent、管理者编排、关闭术语 Agent、关闭审校 Agent。仓库入口支持 `--no-glossary` 与 `--no-proofreading`；先查看 `python demo.py --help` 确认输入和输出路径。再增加“单 Agent 同样获得术语表”的对照，才能区分共享资料与角色隔离的贡献。

`consistency.py` 提供术语漂移/指定译法检查，并剔除代码块后统计。本地实验直接调用这份代码，验证跨章混用译名会被发现；字符串统计仍不是翻译语义质量评判，需要独立核对含义、遗漏和代码保真。指标的覆盖和严格口径见下一节。

研究并行能力时，可继续阅读 `parallel-web-research`，重点是独立浏览器上下文、超时隔离、锁保护的单次结算、级联终止和资源关闭，而不只是 `gather()`。比较加速效果时，串行和并行应访问同一批来源，并记录超时与失败；不能因任务未完成、耗时较短，就将其计为效率提升。

### 源码与实验入口

- [chapter10/book-translation/agents.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/agents.py)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter10.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html) · 统一验证入口（仅保留于本地审阅资料，公开版不提供）

## 10.8 指定译法命中、混用与严格遵从【审阅修订】

上游`check_adherence()`只要一章出现指定译法就计命中；同章“词元和标记”可得到1.0，而`analyze()`的一致性为0。无跟踪概念时二者也可返回1.0，因此不能把这个满分解释为完全遵从或质量提高。

本地词面示例对同一跟踪概念分开报告：

| 量                 | 分母/含义                                                   |
| ------------------ | ----------------------------------------------------------- |
| 指定译法章节命中率 | 有该概念的章节中，至少出现指定译法的章节比例                |
| 混用率             | 有该概念的章节中，同时出现指定和默认译法的比例              |
| 严格章节遵从率     | 有该概念的章节中，出现指定译法且未出现默认译法的比例        |
| 覆盖               | 被跟踪概念覆盖的章节数/总章节数；无覆盖时各率为null/UNKNOWN |

这不是按原文概念出现次数对齐的准确率。普通词同形误命中、复杂Markdown代码块和真实翻译含义需另做验证；不能通过删除所有术语获得理想成绩。测试保留同章混用、跨章混用、零概念和代码排除，严格率与上游命中率同时呈现。

图10明确展示依赖顺序，不表示该翻译代码已经并发调度章节Worker。共享术语表不等于共享完整历史；若另做并行实验，需独立上下文、不同输出文件和汇聚校验。协作消息与版本冲突沿用 [第4章公共事件契约](/articles/ai-agent-tools-events.html#event-contract)。

## 检查理解

1. “上下文共享”和“管理者模式”是什么关系？
2. 哪些子任务值得并行，哪些不值得？
3. 怎样避免两个 Coding Agent 覆盖彼此文件？
4. 为什么业务校验服务不能完全由 Planner Agent 代替？
5. 如何验证新增 Reviewer Agent 真正提升质量而不只是增加成本？

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。`【书】`、`【整理】`、`【实践补充】`、`【源码补充】`用于区分观点来源与个人归纳，不代表原书逐字转录。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
