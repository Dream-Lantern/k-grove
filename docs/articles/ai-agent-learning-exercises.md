---
id: ai-agent-learning-exercises
title: 六周系统学习路线与主动复习
description: "按六周组织 Agent 基础、上下文、检索、工具、评估与进阶实践，配合主动回忆题和受控 Agent 综合设计练习。"
date: '2026-10-25'
updated: '2026-11-12'
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
order: 90
---

# 六周系统学习路线与主动复习

> 建议每周投入 4～6 小时。按执行链、设计权衡和实验验证三个层次学习，每周留下可检查的图、代码或记录。

| 周    | 主题                                | 最小学习目标                          | 核心产物                            |
| ----- | ----------------------------------- | ------------------------------------- | ----------------------------------- |
| 第1周 | 第1～2章：Agent、Harness 与 Context | 区分工具反馈循环与执行约束            | 离线轨迹、批准拒绝记录和 Checkpoint |
| 第2周 | 第3章：Memory 与 RAG                | 运行固定语料的 BM25 并核对指标        | 排名、相关标注、Hit／Recall／RR     |
| 第3周 | 第4～5章：工具与 Coding Agent       | 区分 Schema、授权、重复事件及修复反馈 | 测试输出与修复前后 Diff             |
| 第4周 | 第6章：评估与可观测性               | 区分计划、运行、已知结果及配对范围    | 12 单元覆盖表                       |
| 第5周 | 第7～8章：后训练与持续改进          | 定位复制差异并用独立证据检查声明      | 字节审计、三态判断和候选经验        |
| 第6周 | 第9～10章：实时交互与协作           | 解释停止确认、术语返修及版本冲突      | 播放状态记录与两章术语报告          |

## 每周先完成最小闭环，再选进阶

下面的最小任务为基础必做；扩展到 30 份语料、20 条任务、10 条失败轨迹，以及真实模型、GPU 训练或音频接入均属选做。完成固定输入和对应验收即可完成基础周任务，高成本实验不作为必过条件。

### 第1周：先观察工具循环，再检查 Harness

前置：Python 函数、列表与 JSON。练习 A 在固定提交的上游 `chapter1/web-search-agent` 目录执行，先按其 README 安装依赖：

```bash
python -X utf8 main.py --provider offline-demo --output demo.json
```

输入为内置示例问题；检查 `demo.json` 的 `trace` 中思考、行动、观察与答案的顺序，说明观察如何进入后续步骤。它回放预写轨迹，不调用模型或真实搜索。最小产物是该 JSON 和一张工具循环图。

练习 B 回到 **k-grove 根目录**，运行标准库脚本：

```bash
python examples/ai-agent/ch9-11-review/controlled_plan.py
```

输入为固定 DemoLLM 计划；检查 `before_approval=REJECTED`、`after_approval=APPROVED`、`same_execution_on_retry=true`、`missing_metrics=UNKNOWN`。该程序演示批准、幂等和 SLO 约束，不含模型决策循环。再写一份含任务、工作目录、文件和下一步的 Checkpoint。进阶可选上下文压缩或真实工具接入，分别保存新增配置与反馈。

### 第2周：运行最小检索并核对三个指标

前置：第 1 周、集合与排名。采用方案 A，复用 [第3章最小 BM25 实验](/articles/ai-agent-memory-rag.html#最小-bm25-实验-先验证输入、输出与指标)的完整准备命令；使用 `rank-bm25==0.2.2`、`jieba==0.42.1`，不加载向量或重排模型。该步骤从 k-grove 根目录准备环境，再切到固定上游 `chapter3/retrieval-pipeline`；`$corpus`、`$queries` 指向本仓库已有的四文档语料和查询文件。

```powershell
python evaluate.py --no-dense --no-rerank --device cpu --top-k 5 --eval-k 5 --corpus "$corpus" --queries "$queries" --output bm25.json
```

得到 `bm25.json` 后，在同一目录用以下 Python 代码读取实际排名并逐题计算；可保存为自己的 `inspect_bm25.py` 后运行 `python inspect_bm25.py`：

```python
import json

with open("bm25.json", encoding="utf-8") as stream:
    report = json.load(stream)
for row in report["per_query"]:
    ranked = [item["doc_id"] for item in row["methods"]["sparse"]["top"]][:5]
    gold = set(row["expected"])
    positions = [rank for rank, doc in enumerate(ranked, 1) if doc in gold]
    print({
        "query": row["query"],
        "ranking": [{"rank": rank, "doc_id": doc, "relevant": doc in gold}
                    for rank, doc in enumerate(ranked, 1)],
        "relevant_ids": sorted(gold),
        "Hit@5": int(bool(positions)),
        "Recall@5": len(set(ranked) & gold) / len(gold) if gold else None,
        "RR@5": 1 / positions[0] if positions else 0,
    })
```

最小验收是查询、候选 ID／名次、相关标注及三个指标可以互相复算。若得到 `[B,A]`、相关集为 `{A,B}`，则 Hit@5、Recall@5、RR@5 都为 1；结果不同就按实际候选定位分词或输入差异。不要直接把上游未截断的单题 `mrr` 字段改名为 RR@5。进阶再扩充语料或加入 Dense／Rerank。

### 第3周：区分校验、授权与执行反馈

前置：第 1 周、路径和异常。从 k-grove 根目录运行；先按第 4 章安装 pytest／jsonschema：

```bash
python -m pytest examples/ai-agent/ch4-tools -q
python examples/ai-agent/ch4-tools/event_demo.py
```

第一项应有九个参数／对象授权测试通过；第二项检查恢复和重复投递后 `followups=1`。再按 [第5章平均值修复](/articles/ai-agent-coding-agent.html#_5-6-小型项目练习)创建临时副本，保留测试，记录 `2 passed, 1 failed → 3 passed` 和 Diff。进阶才接 MCP、Lint 或执行沙盒，各自记录独立结果。

### 第4周：解释覆盖率和配对范围

前置：第 2～3 周、比例与配对概念。在 k-grove 根目录执行标准库脚本：

```bash
python examples/ai-agent/ch6-8-review/evaluation_demo.py
```

输入为 12 个合成计划单元。核对计划 12、执行 10、可判定 9，复算 `10/12`、`9/12`、`9/10` 及配对覆盖 `4/6`；保留缺运行和缺证据的原因。进阶再组织 20 条任务、重复运行并分析区间。

### 第5周：从字节差异与证据形成候选经验

前置：第 4 周、字符串与 UTF-8。在 k-grove 根目录执行：

```bash
python -X utf8 examples/ai-agent/ch6-8-review/copy_audit.py
python examples/ai-agent/ch6-8-review/structured_evidence_demo.py
```

核对首尾空白案例的 raw／normalized 差异，以及四种证据输入依次产生 `PASS、FAIL、UNKNOWN、UNKNOWN`。归纳一条含来源、适用条件、反例和回归方法的候选经验。进阶再收集 10 条轨迹并按任务族留出；Tokenizer 往返需要对应文件和依赖，LoRA 训练另需 CUDA 与训练环境。

### 第6周：验证实时状态与协作交接

前置：前五周与状态机。在 k-grove 根目录执行：

```bash
python examples/ai-agent/ch9-11-review/audio_state.py
python -X utf8 examples/ai-agent/ch9-11-review/translation_contracts.py
```

检查无 ACK 时停止确认仍为 UNKNOWN、重复／旧代次不改变新回复；核对两章术语返修前后指标、输入 Hash 和新版本。再列出单 Agent 与 Manager 方案的公平控制变量。真实音频设备或付费翻译消融是选做，不能把离线状态输出当成它们的性能结果。

## 每章学习记录模板

```md
## 本章一句话

## 我已经能解释的三个概念

## 易混淆的两个问题

## 一个运行示例 / 时序图

## 一个反例：为什么看起来合理的方案可能失败？

## 本周实验结果（输入、版本、指标、失败样本）

## 下一次要复习的内容
```

## 主动回忆题（建议合上笔记后回答）

<!-- 分组列表沿用全局题号，供下方自检表引用。 -->
<!-- markdownlint-disable MD029 -->

### Agent 基础与 Context（1～5）

1. 为什么 `LLM + tools` 还缺 Harness？
2. ReAct Loop 怎样检测无进展和如何退出？
3. 如何按关键性、可重读性、时效与执行器约束，选择工具结果和批准约束的保真/摘要策略？
4. Prompt Injection 的最终防线应在哪里？
5. Skills 的渐进式加载与检索工具有什么区别？

### Memory 与 RAG（6～8）

6. Memory 的“保存事实”和 Agent 的“学习策略”如何区分？
7. 什么情况下 BM25 比 Dense 更有效？
8. 为什么 Rerank 不能弥补 Recall 漏召回？

### 工具和 Coding Agent（9～11）

9. 执行工具如何设计幂等性？
10. 异步事件乱序怎样处理？
11. Coding Agent 如何验证实际修改产生了预期效果？

### 评估与后训练（12～15）

12. Pass@k 与 Pass^k 对产品可靠性的含义分别是什么？
13. 两个 Agent 版本在同一批任务上测试，为何使用配对评估？
14. LoRA 的 rank 与 target_modules 为什么需一起调参？
15. 如何防止 RL “奖励投机”？

### 持续进化与实时交互（16～18）

16. 什么时候经验更适合沉淀为代码而不是提示词？
17. 语音 Agent 的流式时延应该如何量化？
18. Computer Use 为什么必须按操作风险做审批？

### 多 Agent 协作（19～20）

19. Multi-Agent 哪些模式引入了额外有效信息？
20. 如何测算分工带来的收益是否超过协调和 Token 成本？

<!-- markdownlint-enable MD029 -->

### 回答后如何自检

保留上面 20 道题。答完后用下表核对机制、前提和易混点，再回到对应章节查漏；检查点不是要求背诵的标准长答案。

| 题号 | 对应章节                                                                                                              | 答案至少应包含                                                                                    |
| ---- | --------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------- |
| 1    | [第1章：Harness](/articles/ai-agent-harness.html)                                                                     | 模型提议动作，运行时管理工具、状态、预算、权限与退出；有工具不等于有可靠执行闭环                  |
| 2    | [第1章：执行循环](/articles/ai-agent-harness.html)                                                                    | 工具/状态反馈、重复或无进展检测、有限预算；成功、失败、取消各有退出条件                           |
| 3    | [第2章：上下文压缩](/articles/ai-agent-context-engineering.html)                                                      | 关键性、能否重读、时效与信任边界；批准约束须可恢复且由执行器强制，不依赖摘要措辞                  |
| 4    | [第2章：注入与信任](/articles/ai-agent-context-engineering.html)和[第4章：护栏](/articles/ai-agent-tools-events.html) | 外部内容是数据；权限、工具白名单和参数校验由程序执行，Prompt 不能成为唯一防线                     |
| 5    | [第2章：Skills](/articles/ai-agent-context-engineering.html)和[第4章：工具发现](/articles/ai-agent-tools-events.html) | Skill 按需加载流程指导，工具发现按任务找能力/Schema；二者不自动执行或授予权限                     |
| 6    | [第3章：记忆](/articles/ai-agent-memory-rag.html)和[第8章：持续改进](/articles/ai-agent-continuous-improvement.html)  | 写入可检索事实不等于参数更新；策略经验需归纳、验证、选载体并回归                                  |
| 7    | [第3章：Sparse/Dense](/articles/ai-agent-memory-rag.html)                                                             | 精确术语、型号等词面匹配可利于 BM25；同义语义可能利于 Dense，不能无条件排序优劣                   |
| 8    | [第3章：检索评价](/articles/ai-agent-memory-rag.html)                                                                 | Reranker 只能重排已召回候选；正确片段未进入候选集时需修召回链                                     |
| 9    | [第4章：工具契约](/articles/ai-agent-tools-events.html)                                                               | 稳定业务键、参数指纹、持久状态与原子去重；同键不同请求应冲突，不是模型记住不重试                  |
| 10   | [第4章：事件契约](/articles/ai-agent-tools-events.html#event-contract)                                                | event_id 管重投递，generation/version 管时效；旧结果、冲突身份和取消后晚到消息需检查              |
| 11   | [第5章：Coding Agent](/articles/ai-agent-coding-agent.html)                                                           | 实际 diff、目标测试与旧行为回归；工具返回成功不等于代码行为正确，静态扫描不等于沙盒               |
| 12   | [第6章：Pass 指标](/articles/ai-agent-evaluation.html)                                                                | 至少一次成功与全部成功；单题 IID 前提、逐题后汇总，实际选择器和副作用另计                         |
| 13   | [第6章：配对评估](/articles/ai-agent-evaluation.html)                                                                 | 同任务结果对应、不一致配对、缺一侧不能硬配；同题重复不是独立新任务                                |
| 14   | [第7章：LoRA](/articles/ai-agent-post-training.html)                                                                  | rank 控制低秩容量，target_modules 决定覆盖矩阵；alpha/缩放实现、训练成本与留出结果一起判断        |
| 15   | [第7章：奖励和约束](/articles/ai-agent-post-training.html)                                                            | 独立结果/过程验证、不可绕过的执行护栏、防删测试等投机；负奖励不是权限控制                         |
| 16   | [第8章：更新载体](/articles/ai-agent-continuous-improvement.html)                                                     | 按根因选载体；确定性状态机/协议错误修代码和测试，流程遗漏才考虑 Prompt/Skill                      |
| 17   | [第9章：实时语音](/articles/ai-agent-multimodal-realtime.html)                                                        | 说话结束、端点、ASR/LLM/TTS、实际播放的起止点；流式可重叠，取消接纳不等于停止 ACK                 |
| 18   | [第9章：Computer Use](/articles/ai-agent-multimodal-realtime.html)                                                    | 读与写的影响不同；确认目标、授权和覆盖/发送风险，动作后重新观察并读回                             |
| 19   | [第10章：协作模式](/articles/ai-agent-multi-agent.html)                                                               | 独立来源、专用工具、执行测试或有效并行可带来新信息；相似模型互相赞同不构成证明                    |
| 20   | [第10章：公平对照](/articles/ai-agent-multi-agent.html)                                                               | 同输入、模型、共享资料、质量标准；统计全体 Token、墙钟、返工与负结果，不拿 Manager 峰值代替总成本 |

若答出了名词却没有说明一次具体输入怎样变成反馈，补一个小例子；若漏掉权限、版本或证据前提，用对应反例重新检查答案。

## 综合练习：从零设计一个受控 Agent

需求：用户通过自然语言创建一次模型性能测试，系统生成建议方案，经用户批准后执行，并报告准确的 SLO 判定。

### 固定输入：先设计，不发起真实压测

采用以下合成任务，DemoLLM 和 Synthetic Dataset 均为教学名称，不对应实际部署。测量时长按每个并发点 30 秒理解，不含预热和准备；并发集合仅为 1、2、4，不是无限边界搜索：

```json
{
  "model": "DemoLLM",
  "goal": "MAX_THROUGHPUT",
  "dataset": "Synthetic Dataset",
  "input_tokens": 128,
  "output_tokens": 128,
  "concurrency": [1, 2, 4],
  "measurement_seconds_per_point": 30,
  "approval_required": true,
  "slo": {"p95_ttft_ms_lte": 300, "error_rate_lte": 0.01}
}
```

SLO（Service Level Objective，服务等级目标）阈值也是本练习的合成约定，须随正式计划一起获批。真实工具需冻结 Tokenizer 与数据生成方式，明确固定的是目标输出长度还是实测长度，以及错误、超时、完成吞吐与测量窗口口径；不能仅凭两项 128 就认定各 Endpoint 负载等价。

### 沿同一任务说明职责和状态

1. **Agent 提议**：解释需求并生成候选 Plan。模型可以提出并发点和阈值，但候选状态必须是 CANDIDATE，不能把用户说“帮我设计”解释为已批准执行。
2. **程序校验并冻结**：确定性服务检查模型/数据集白名单、参数范围、预算和 SLO，产生不可变版本与 Hash。用户批准的是该正式 Plan 的具体内容；之后修改并发、时长或阈值需要重新批准。
3. **执行审批与权限**：执行器检查批准记录绑定的 Plan Hash、执行身份与工具权限。重复请求用同一幂等键与参数指纹复用原 execution_id；同键不同 Plan 必须冲突，不创建第二次负载。
4. **分开记录状态**：Plan 的 APPROVED 不等于任务已运行；Worker 的 RUNNING/COMPLETED/FAILED/CANCELLED 由实际回执更新。COMPLETED 仅说明执行过程结束，不自动意味着 SLO 通过。
5. **按证据评价**：逐并发点读取吞吐、p95 TTFT、错误率与运行覆盖。缺度量、单位或结果时记 UNKNOWN，不补零；超出冻结阈值的已知证据为 FAIL。只有完整可比、满足 SLO 的点才参加最大吞吐选择。
6. **限定结论**：在三个点里选出的只是“本次固定网格内、满足 SLO 的最佳已测点”，不是全局最大值或边界已经收敛。若部分点 UNKNOWN，可报告局部观察，但不能宣布完整比较完成。

最小验收保留：原请求、候选和正式 Plan 差异、版本 Hash、批准引用、权限检查、幂等记录、逐点执行回执、指标及其覆盖、SLO 判定原因。没有正式批准时，预期证据是执行器拒绝，而不是一份漂亮的压测报告。

本仓库的 `examples/ai-agent/ch9-11-review/controlled_plan.py` 提供纯内存教学状态与 SLO 检查。测试中的批准、执行和指标均为构造输入，不连接 Endpoint，也不会制造真实负载；不能把其模拟 RUNNING 状态当成实际运行回执。

将上述职责连成最小教学状态路径：

```text
CANDIDATE → APPROVED → QUEUED → RUNNING → COMPLETED → 结果验证
                                                     ├─ 指标齐全且满足阈值：PASS
                                                     ├─ 已知指标违反阈值：FAIL
                                                     └─ 缺关键指标：UNKNOWN
```

这里的 QUEUED 表示已持久登记待执行，RUNNING／COMPLETED 应由真实 Worker 回执更新。当前脚本只演示 `CANDIDATE → APPROVED`，以及 `simulate_start()` 返回带 `simulated=true` 的 RUNNING 夹具；没有持久队列和完成回执。`assess_slo()` 是对传入指标单独评价。

两个反例必须留在交付物中：未批准就调用 `simulate_start()`，应得到 `PermissionError` 并记为 REJECTED；假设真实任务已 COMPLETED，但提供给 `assess_slo()` 的结果缺关键指标，应为 UNKNOWN。后者的 COMPLETED 是状态推演，不是脚本实际执行过压测；实际示例中的 `assess_slo({})` 只验证缺指标分支。

**必须输出的设计成果**：

1. Agent vs Workflow 边界图：模型做什么，程序强制什么。
2. 工具清单：权限、参数、错误和幂等方案。
3. 状态与上下文：任务持久化、摘要、引用、压缩策略。
4. 必要检索：有哪些知识文档值得做 RAG 或 Skill。
5. 验证器：执行成功 ≠ SLO 通过 ≠ 边界已收敛，分别怎样判断。
6. Eval 数据集：合法请求、歧义请求、越权请求、部分失败、重试与提示注入。
7. 多 Agent 比较：一个 Agent + 工具 vs Orchestrator/Planner/Analyzer，控制变量记录质量和成本。
8. 经验进化：从失败追踪形成候选修复，通过回归后发布。

**交付检验**：如果模型“宣称任务成功”而环境没有对应任务，评估必须失败；如果指标证据缺失，SLO 不能凭文字推测为 PASS；如果没有确认授权，执行器不能放行不可逆动作。

## 源码版实践路线

| 周  | 对应源码                                                    | 阅读顺序                                 |
| --- | ----------------------------------------------------------- | ---------------------------------------- |
| 1   | `chapter1/web-search-agent`、`chapter2/context-compression` | 先跟读工具反馈轨迹，再比较上下文保留方式 |
| 2   | `chapter3/retrieval-pipeline/evaluate.py`、`fusion.py`      | 从 BM25 排名与指标进入融合逻辑           |
| 3   | `chapter4/execution-tools`、`chapter5/coding-agent`         | 从执行契约进入编辑错误反馈               |
| 4   | `chapter7/user-memory-system-evaluation`                    | 从单题记录进入完整性与配对矩阵           |
| 5   | `chapter8/exact-copy-sft`、`chapter9/trajectory-verifier`   | 从复制审计进入训练与证据检查             |
| 6   | `chapter6/streaming-speech`、`chapter10/book-translation`   | 从实时状态进入协作交接与对照             |

### 每周一个可以打开的基础入口

操作命令与验收集中在前面的六周说明；本节源码表只用于进入上游阅读。执行前先用 [章节对照](/articles/ai-agent-chapter-reference.html) 确认本站章号与上游目录，再用 [实验地图](/articles/ai-agent-source-experiments.html) 查看来源、依赖与证据状态。上游命令在上游目录执行，本地脚本从 k-grove 根目录执行。

语音、翻译与批准控制示例的统一测试入口（k-grove 根目录）：

```bash
python -m unittest discover -s examples/ai-agent/ch9-11-review -p "test_*.py" -v
```

本地脚本位于 `docs/` 外，供取得仓库源码后运行；它们不会随静态页面变成在线工具。每次保留命令、输入版本、实际输出和未测范围，不把教学模拟结果写成真实压测或语音性能。

先从 [实验地图](/articles/ai-agent-source-experiments.html) 中选择无需外部服务的确定性检查，再逐步开展需要模型或服务的实验。运行前固定代码版本、依赖与输入；结果分别标记为本地观察、上游参考或待复现。

练习中的20条任务不保证达到统计显著性所需的样本量；应按第6章预先定义任务、变体、重复、效应量和未知数据的处理方式。检查输出分别列出上游实现的观察与本地教学契约的结果，使复现现象和验证修复各有对应证据。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
