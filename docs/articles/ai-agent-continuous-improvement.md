---
id: ai-agent-continuous-improvement
title: 第8章 Agent 的持续进化（Continual Improvement）
description: "Agent 的持续改进是一条工程流程：轨迹采集 → 评价 → 跨轨迹归纳 → 候选更新 → 回归验证 → 发布/回滚。系统从任务记录中提取候选经验，经验证后更新合适的载体。"
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
order: 8
---

# 第8章 Agent 的持续进化（Continual Improvement）

## 8.1 从任务经历到可验证的改进 {#_8-1-保存经历不等于-学会}

Agent 的持续改进是一条工程流程：**轨迹采集 → 评价 → 跨轨迹归纳 → 候选更新 → 回归验证 → 发布/回滚**。系统从任务记录中提取候选经验，经验证后更新合适的载体。一次成功可能只是偶然，轨迹也可能含有提示注入，因此需要独立评价；完成任务本身不会自动修改模型参数。

### 三层验证器

| 层级     | 数据依据             | 例子                       |
| -------- | -------------------- | -------------------------- |
| 结果验证 | 数据库/测试/业务环境 | 是否真正创建测试任务       |
| 过程验证 | 工具轨迹、权限与顺序 | 是否在批准前执行了写操作   |
| 质量验证 | Rubric + LLM/人工    | 说明是否完整、策略是否合适 |

正确性越容易形式化，就越应交由确定性程序判断；使用 LLM 评价语言质量时，仍须校准并保留不确定性。

## 8.2 四类更新载体

| 载体              | 适合什么                     | 最大好处               | 主要风险           |
| ----------------- | ---------------------------- | ---------------------- | ------------------ |
| 知识库 / 经验文档 | 经验证事实与经验             | 可溯源、易更新         | 检索不到/过期      |
| Prompt / Skill    | 可语言化规则和操作流程       | 修改快、可限定作用域   | 规则冲突或膨胀     |
| 程序 / Harness    | 确定性校验、状态机、业务逻辑 | 可测试、强约束         | 维护成本           |
| 模型参数          | 隐式习惯、复杂感知与策略     | 泛化、推理时调用成本低 | 训练难、回归成本高 |

**按根因选择更新载体**。例如批准计划的 SLO `≤` 被错误渲染成 `<`，问题在渲染层，应修复 Renderer 并增加单测；流程指导问题则可考虑更新 Prompt 或 Skill。

## 8.3 轨迹转可验证的经验

[经验提取、候选验证与受控发布流程](/assets/notes/ai-agent/08-evolution.svg)

经验文档推荐字段：触发条件、问题表现、根因、可执行对策、反例、不适用范围、参考轨迹、验证版本与日期。

## 8.4 Prompt 自动优化是什么

原书提及 DSPy、OPRO、GEPA 等工具/思路。共同框架是：根据失败案例提出候选提示或结构修改，用开发集筛选，再用独立保留集检验，不能在评估集反复调优后宣称泛化。

更新 Skill 时，应先查找相近 Skill，尽量作最小修订；只有确属全新领域能力时才新增模块，避免大量相近 Skills 相互冲突。

## 8.5 “睡眠学习”与安全边界

后台整理任务可以周期性做经验合并、冲突检测、候选提案，但**不是允许在线运行的 Agent 自行修改生产规则**。

建议：线上采集只写候选区；候选通过来源验证、静态检查、回归评估、权限审核后才提升为正式版本。具有高风险的自动修改必须明确人工批准。记录“谁、何时、基于什么证据、修改了什么、如何回滚”。

## 8.6 最小实验

准备 30 个已解决任务轨迹，划分归纳集和未见过的评测集。比较：不加经验、检索单条相似轨迹、检索跨轨迹归纳经验三组表现。除了成功率，还要报告 Token 消耗、误导率（负迁移）、来源可追溯率。切忌评估题泄漏到经验提取集。

## 8.7 从候选补丁到受控发布的源码链

当前仓库 `chapter9/self-modifying-agent` 值得与 `trajectory-verifier` 配合读：前者生成和验证控制代码候选，后者检查轨迹中的声明、工具结果与证据是否一致。它们把“从失败学习”拆成可检查的程序步骤。

`evolution.validate_candidate()` 先限制源码长度、编译和 AST 预筛，再通过 `candidate_sandbox.py` 调用 Docker。AST denylist 只是快速过滤器，实际执行边界是容器及资源限制。容器不可用或返回格式不符时，检查保持失败，不自动降级成在主进程执行候选。

源码节选（上下文依赖见原文件）：[chapter9/self-modifying-agent/evolution.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter9/self-modifying-agent/evolution.py#L276-L278)。

```python
accepted = candidate.get("changed", False) and bool(checks) and all(checks.values())
failed = [name for name, passed in checks.items() if not passed]
contract = diagnosis.get("change_contract", {})
```

`release_manifest()` 还会保存稳定版本与候选版本的 Hash、来源轨迹、预期修复、潜在回归和回滚版本。这里的 `release_to_canary` 只表示决定进入影子/灰度候选阶段，并不意味着已替换生产代码；正式部署仍由外层发布系统执行。

[![Agent 持续进化：门禁、审批与发布](/assets/notes/ai-agent/08-evolution.svg)](/assets/notes/ai-agent/08-evolution.svg)

图中从轨迹提取候选更新，经过验证、审批与灰度再进入正式版本，并保留拒绝和回滚路径。[放大查看 SVG](/assets/notes/ai-agent/08-evolution.svg)。[原始 DOT 语义图源](/assets/notes/ai-agent/08-evolution.dot)供对照，不是本版配图的可编辑源文件。

### 推荐三个反例

| 候选                       | 要验证什么                       | 应如何解释                           |
| -------------------------- | -------------------------------- | ------------------------------------ |
| 改善不可重试错误的重试策略 | 新失败减少，旧临时错误恢复不退化 | 新旧任务都通过才有资格进入后续门禁   |
| 只针对训练轨迹硬编码       | 留出集、边界集与旧任务回归       | 训练案例通过不构成泛化证据           |
| 尝试导入模块或写外部文件   | 静态预筛、执行沙盒和资源边界     | 被过滤或隔离，不把“能执行”当“可发布” |

`trajectory-verifier/consistency_checker.py` 是启发式检查器：在实际结果和声明结果均存在并进入比较时，能发现两者不同；缺少实际返回时并不等价于忠实报告，词面相似也不等于语义蕴含。它适合产生待复核信号，业务是否成功仍应查询环境真值。增加 LLM Judge 时，要做独立校准，不能因为裁判输出了分数就认为证据链已完整。

### 源码与实验入口

- [chapter9/self-modifying-agent/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter9/self-modifying-agent/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter9.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

## 8.8 验证器的覆盖范围与证据来源

固定提交中的`consistency_checker.py`是英文/数字词项的启发式演示，**不是通用自然语言事实验证器**。审阅反例揭示三个不同缺口：

| 输入/机制                     | 原快照行为                                  | 正确解释与修订选择                                      |
| ----------------------------- | ------------------------------------------- | ------------------------------------------------------- |
| 空轨迹、纯中文无证据声明      | 无有效词项时可满分且无违规                  | 规则未发现问题不代表证据充分；无可评估输入应为UNKNOWN   |
| 未获证实的claim复述成最终结论 | claim grounding可为0而conclusion support为1 | 原实现把全部claim再加入结论证据；禁止以自身复述自我支持 |
| 有声明的工具结果但无实际返回  | 不进入结果对照，完整性维度可为1             | 区分尚未调用/待返回/日志缺失/合法null，不把缺证判忠实   |

配套教学示例 `experiments/revised_contracts.py` 与原快照分开，采用范围更窄的**结构化证据契约**：由可信适配器传入`evidence_id/source/call_id/step_id/key/value/present/complete`，声明显式给出待核对字段及来源ID。最终结论也独立指向先前外部观察，不能仅引用一个未经证明的claim。未来观察、身份冲突、未采集完成、不可结构化的自然语言都保持UNKNOWN；相反的已知值为FAIL。合法null通过`present=true, value=null`表达。

```json
{
  "claim": {"step_id": 2, "key": "task.status", "expected": "done", "evidence_ids": ["obs-1"]},
  "trusted_observation": {"evidence_id": "obs-1", "source": "tool", "call_id": "call-1", "step_id": 1, "key": "task.status", "value": "done", "present": true, "complete": true}
}
```

适配器的可信性不能由模型自行填`source=tool`来获得。这个教学示例只比对结构化事实及时间/身份关系；不会验证中文语义、否定句推理、真实权限或业务数据库。中文/英文/混合语言在没有结构化证据时一律UNKNOWN，有确定性字段证据时才对字段作比较。报告可评估数量、覆盖率、UNKNOWN数量和每项原因，不用一个平均分掩盖未覆盖内容。

该契约的回归案例包括：空输入、三种语言无证据、合法证据、状态/数值冲突、缺实际结果、合法null、错误调用ID、未来证据与自我循环。通过这些测试只表明该合成契约成立；完整业务仍需环境验证器。实际业务接入时，应另行保存运行环境、不可变输入与验证证据。

## 本章要点 {#检查理解}

1. 轨迹存储只是起点，经验需要提取、验证并作用于后续任务，才能形成改进闭环。
2. 确定性规则和实现缺陷适合用代码及测试修复；可语言化操作流程可更新 Skill。
3. 独立 Eval 检查泛化与回归，回滚机制在新版本退化时恢复稳定状态。
4. 缺少来源或验证的经验保留在候选区，取得证据并通过审核后再发布。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
