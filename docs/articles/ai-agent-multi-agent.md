---
id: ai-agent-multi-agent
title: 第10章 多 Agent 协作
description: "从上下文共享、协作拓扑和任务交接理解多 Agent，结合翻译实验说明角色分工、版本冲突与收益评估。"
date: '2026-10-25'
updated: '2026-10-30'
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

## 10.1 上下文组织与协作拓扑 {#_10-1-先分两个设计维度}

**维度一：上下文是否共享**。

- 共享：角色切换时继承完整轨迹，信息丢失少，但长上下文开销高。
- 隔离：子 Agent 只得到任务目标和必要证据，可减轻上下文并为独立任务并行创造条件，但交接质量成为关键。上下文隔离本身不限制进程或工具能访问哪些文件，权限仍须由执行系统落实。

**维度二：协作拓扑**。

- Peer（对等协作）：Writer↔Reviewer，相互修正，适合少量明确角色。
- Manager/Orchestrator：主 Agent 分解任务并汇总，适合多个独立子任务。
- Decentralized/Handoff：Agent 之间自行移交控制权，适合职责网络和动态路由。

上下文与拓扑是不同的设计维度，不能只用“有几个 Agent”来描述协作架构。

## 10.2 多 Agent 何时值得做

多 Agent 的价值来自**新信息、新能力或有效并行**。当角色隔离或并行带来的收益超过协调成本时，才有必要增加 Agent。

| 情形                                 | 是否适合多 Agent               |
| ------------------------------------ | ------------------------------ |
| 单任务仅需 2～3 次工具调用           | 一般不值得                     |
| 多份互不依赖材料可以并行处理         | 可以考虑                       |
| 需要代码生成与独立执行测试的交叉检查 | 可考虑，因为测试结果是新信息   |
| 仅让三个相似模型读同一段文本互相赞同 | 不一定增益，可能只是成本上升   |
| 需要访问不同机密数据的角色分权       | 适合隔离，但权限必须由系统执行 |

要把 **性能收益、总 Token、总耗时、错误率、协调成本** 放在同一评估框架下。

## 10.3 任务交接的结构化信息 {#_10-3-协作时传递什么}

任务交接（handoff）可使用**结构化契约**，传递目标、约束、进度与可复核证据：

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

## 10.4 IPC 与共享文件系统并发问题

IPC（Inter-Process Communication，进程间通信）专指操作系统进程之间的通信。多 Agent 可能只是同一进程中的不同调用或上下文，角色交接也可以通过函数、消息、文件引用或远程 API 完成，不一定发生 OS 级 IPC。常见的数据交换方式包括：

- 共享文件/存储：读写快且灵活，但面临竞态和覆盖。
- 消息/API：界限清晰，有显式载荷，适合异步；需要投递保障和幂等。

共享工作区中的常见冲突是：两个 Agent 同时修改同一文件，后保存的内容覆盖先保存的内容。可通过 Git worktree/分支隔离、乐观版本检查、细粒度任务划分和合并测试处理。共享数据库任务则需要事务与状态机，不能仅靠提示词要求“别冲突”。

文件交接也要带版本：Worker 读取 `ch2@v1` 后提交修订，应声明预期输入版本或 Hash；如果索引已变成 `ch2@v2`，Manager 应拒绝旧产物覆盖并重新仲裁。不同角色名或不同 Prompt 并不会自动带来工具权限隔离；只读范围、写目录和可用凭据须由运行时分别限制。角色增加后，还要重新测量协调、调用和返修开销，不能从架构图的盒子数量推导性能。

## 10.5 多 Agent 常见失败

1. **成本爆炸**：每个 Agent 重复读全量上下文、反复讨论，未引入新信息。
2. **理解债（Comprehension Debt）**：代码产出很快，团队却跟不上架构演变，不知道做了什么。
3. **认知投降（Cognitive Surrender）**：因为“Agent 总能写”，开发者停止对核心决策的审查。
4. **交接失真**：必要约束在角色转换时遗漏。
5. **循环和责任不清**：多个 Agent 将任务相互推回，没有明确 Owner 与结束条件。

**补充工程建议**：对每个 Agent 设置预算、可调用工具、产物格式、证据标准、完成条件和冲突仲裁方式。

## 10.6 结合 Agent 评测平台做拆分

可把评测任务按职责拆开，但下图展示的是翻译角色概览，只用来帮助理解编排关系，不是 Benchmark Worker 的完整执行架构：

[多 Agent 的角色分工与依赖流程](/assets/notes/ai-agent/10-multi-agent.svg)

并非每个盒子都必须是独立 LLM Agent。**Benchmark Worker、校验器和资源调度服务可能应主要由确定性代码实现**。Orchestrator 可保留用户意图分类与解释能力；Planner 可提方案，但持久化写入与状态转换遵守统一业务服务。

对比单 Agent：记录两个版本的任务成功率、方案可执行率、人工返工次数、端到端耗时、Token 总成本、业务规则违反率。只有收益足够明显才继续增加 Agent 数量。

## 10.7 用翻译实验理解管理者上下文隔离

`chapter10/book-translation/agents.py` 的 `run_orchestration()` 是一条值得跟读的实现：Glossary Agent 先生成术语表，章节翻译 Agent 读取必要原文，Proofreading Agent 检查一致性，Manager 依据报告安排修订。Manager 维护任务、进度、文件索引和调用摘要，避免长期持有所有章节全文。

### 两章翻译怎样完成一次交接

下面用两个短章节构造教学案例。原文 `source/ch1.md@src-v1`、`source/ch2.md@src-v1` 都包含 token；约定统一译为“词元”。`@v1` 等是本例的版本标记，不是上游已有的版本协议，文件引用还应保存实际内容 Hash。

| 角色与顺序           | 输入及上下文边界                                                              | 输出产物、状态与验证                                                                               |
| -------------------- | ----------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Manager 制定任务     | 两章引用、目标语言、术语要求、预算；索引记版本和状态                          | 分派 Glossary；维护任务、文件索引与摘要，不把所有译文塞回主上下文                                  |
| Glossary             | 本例两章原文与编辑要求；不需要主会话其他历史                                  | `glossary.json@g-v1`：token→词元；结构和必需条目检查后记 READY                                     |
| Translation 逐章执行 | 每次仅本章原文、g-v1、翻译指南；不继承另一章的完整调用历史                    | `ch1_zh.md@v1`、`ch2_zh.md@v1`；分别记 TRANSLATED，尚不是质量验收通过                              |
| Proofreading         | 两章译文与 g-v1，因为跨章一致性确实需要这些内容                               | `proofreading_report.json@p-v1` 引用 ch1-v1/ch2-v1，标出 ch2 混用“词元”和“标记”，记 NEEDS_REVISION |
| Manager 安排一次返修 | 文件索引、报告摘要和剩余返修预算；给 Translation 传 ch2 原文、g-v1 和明确意见 | 仅 ch2 产生 v2；提交时检查输入版本，过期产物不得覆盖新版本                                         |
| Manager 汇总         | 确认索引已指向 ch2-v2，重新执行术语与结构检查                                 | 本例词面检查通过后记 READY_FOR_HUMAN；如仍有问题且预算用尽，停止并列出待确认项                     |

例如 ch1-v1 为“词元决定序列长度”，ch2-v1 为“先统计词元，再合并标记”。审校报告给出 `chapter=ch2, expected=词元, observed=标记` 及引用版本；Manager 只把相关意见发回第二章，修订为“先统计词元，再合并词元”。这个小例子检验术语，不证明整段译文的语义和文风质量。

上游 `run_orchestration()` 实际逐章调用，审校后至多安排一轮修订，代码不是无限互审。其默认 Proofreading 输入是译文和术语表，不能由此证明它已逐字对照原文验证代码、图片或遗漏；这些还需独立结构比对和人工/语义审查。上表的显式版本校验与修后重新验证是本地教学契约，不能冒充上游已经具备的完整门禁。

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

[![多 Agent：翻译角色分工示例](/assets/notes/ai-agent/10-multi-agent.svg)](/assets/notes/ai-agent/10-multi-agent.svg)

这张 SVG 仅概括“Manager 制定任务→Worker 翻译→审阅统一→合并验收”四步，未单列 Glossary、返修与指标节点；不能据此判断完整执行架构。DOT 才细化术语先行、逐章翻译、限次返修和评价，且不是该 SVG 的直接生成源。固定提交的章节翻译是顺序调用，本例不主张并发加速。[放大查看 SVG](/assets/notes/ai-agent/10-multi-agent.svg)。[原始 DOT 语义图源](/assets/notes/ai-agent/10-multi-agent.dot)供对照，不是本版配图的可编辑源文件。

### 对照图源时，哪些是概览省略

| 关系               | SVG 概览             | DOT / 正文                                                             |
| ------------------ | -------------------- | ---------------------------------------------------------------------- |
| Manager 的持久职责 | 制定任务与最终合并   | 任务、摘要、文件索引贯穿流程；正文交接表补版本与状态                   |
| 术语先于翻译       | 未单独画出           | Manager→Glossary→逐章 Translation                                      |
| 章节完成后审校     | Worker→审阅统一      | Translation→Proofreading，之后可限次返修                               |
| 失败与退出         | 没有展开返修或失败边 | DOT 有返修回边；正文明确预算用尽停止、保留待确认，不以合并动作冒充通过 |
| 评价与公平对照     | 没有细化指标         | DOT 细化命中/混用/覆盖，以及同术语表的单 Agent 基线                    |

现有两份图都保留。完整的教学交接还要结合上表和文件版本契约阅读；概览中的合并是流程阶段，并不保证审校一定成功。

### 推荐消融与公平基线

以同一组章节、同一模型和相同质量要求，对照单 Agent、管理者编排、关闭术语 Agent、关闭审校 Agent。仓库入口支持 `--no-glossary` 与 `--no-proofreading`；先查看 `python demo.py --help` 确认输入和输出路径。再增加“单 Agent 同样获得术语表”的对照，才能区分共享资料与角色隔离的贡献。

`consistency.py` 提供术语漂移/指定译法检查，并剔除代码块后统计。本地实验直接调用这份代码，验证跨章混用译名会被发现；字符串统计仍不是翻译语义质量评判，需要独立核对含义、遗漏和代码保真。指标的覆盖和严格口径见下一节。

研究并行能力时，可继续阅读 `parallel-web-research`，重点是独立浏览器上下文、超时隔离、锁保护的单次结算、级联终止和资源关闭，而不只是 `gather()`。比较加速效果时，串行和并行应访问同一批来源，并记录超时与失败；不能因任务未完成、耗时较短，就将其计为效率提升。

### 上游历史结果：少用 Token，也可能更慢

固定提交的 [README：2026-07-30 正式实跑结果](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/README.md)记录了英文书第 1～2 章、26 个翻译单元的历史实验：原文 242,090 字节、23 个插图引用、14 个围栏代码块。翻译使用 `doubao-seed-1-6-flash-250615`，匿名裁判使用 `doubao-seed-1-6-250615`，均关闭 thinking。下表转述上游记录，本地没有重新调用模型执行：

| 指标                             | 四角色管理者组 | 单 Agent 组 |
| -------------------------------- | -------------: | ----------: |
| 翻译 API 调用数                  |             29 |          26 |
| 翻译总 Token                     |        203,277 |   1,317,808 |
| 主上下文峰值                     |          4,618 |      94,355 |
| 翻译墙钟时间                     |      270.829 s |   254.127 s |
| 编辑部指定译法遵从率（上游口径） |            75% |          0% |
| 确定性字符串术语一致率           |            50% |       87.5% |

翻译总 Token 较少，墙钟时间却更长，说明减少重复上下文并不自动抵消调度与调用开销。表中的 Manager 峰值是管理状态序列化后用 tiktoken 计算的局部峰值，单 Agent 峰值来自调用上下文；它们不是全体 Agent 的 Token 总成本，也不能直接当成相同口径的计费输入。翻译 Token 和时间还应与裁判等其他阶段开销分开记录。

指定译法指标提高，但宽泛字符串一致率反而较低，`embedding` 也没有遵守“嵌入向量”。这些指标与严格遵从率、翻译语义质量不同，详见 §10.8。共享术语信息本身也是变量，不能把全部差异归因于 Agent 数量。

结构方面也有负结果：两组虽然保留代码块和图片数量，却都改动了代码 payload、增加了标题；管理者组改动了图片目标，单 Agent 组的图片目标序列则保持不变。数量相同不能证明结构保真。上游“完整执行与溯源门通过”只说明实验完成，不表示所有质量假设成立；这也不是本地复现证据。相关原始记录见 [v4 evidence.json](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/validation/real_20260730T061500Z_v4/evidence.json)。

### 分级复现：先不调用模型

在获取的上游工作副本中固定到 `dbc046eb896ac4e39aa19c7774c8bf49583b89a6`。从其根目录创建并激活 Python 3.12 独立环境，安装这个项目的依赖；以下是待执行的准备命令，不是本地已运行回执：

```bash
python -m venv .venv-translation
# 激活后再执行下列命令；Windows PowerShell 使用 ./.venv-translation/Scripts/Activate.ps1
# macOS/Linux 使用 source .venv-translation/bin/activate
cd chapter10/book-translation
python -m pip install -r requirements.txt
python -m pip install pytest
```

这会安装 OpenAI SDK、tiktoken、python-dotenv 和测试工具，不需要 GPU。tiktoken 首次初始化可能需要下载编码数据，严格离线使用前应准备缓存。下列各步都在 `chapter10/book-translation` 目录执行：

| 层级        | 命令                                                                                                                             | Key / 费用                                      | 输出与可验证结论                                                                          |
| ----------- | -------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------- | ----------------------------------------------------------------------------------------- |
| 1：预演     | `python demo.py --dry-run`                                                                                                       | 无需 Key，无模型 API 费用；依赖和编码缓存须就绪 | 终端协作图、计划与 Token 预算估算；不生成真实译文，不证明质量或实际 usage                 |
| 2：回归     | `python -m pytest tests`                                                                                                         | 调用被测试替身替换，无需 Key、无 API 费         | pytest 结果与临时产物；验证空值/非法术语表和报告处理，未证明翻译质量                      |
| 3：真实调用 | `python demo.py --out-dir output/full`                                                                                           | 需可用提供方 Key、模型配置，实际计费            | full 下 orchestration/single_agent 的术语表、章节文件及启用时的审校报告，终端用量与对比表 |
| 4：消融     | `python demo.py --no-glossary --out-dir output/no-glossary`；`python demo.py --no-proofreading --out-dir output/no-proofreading` | 同上，分别产生真实调用费用                      | 独立目录避免覆盖；同章节、模型、预算与质量检查下比较关闭组件的影响                        |

真实调用前应自行配置合适的模型与服务端点，确认价格、配额和材料授权；本练习不要求初学者完成付费步骤。`--no-glossary` 仅关闭抽取角色，源码仍补入编辑部指定术语；`--no-proofreading` 同时关闭审校及其 Manager 修订闭环，不能解释成只减少一次读取。`--skip-single` 会跳过单 Agent 对照，因而无法用该次输出完成两组比较。

另有本仓库的纯标准库练习，目录在项目根目录下，不需要安装上游 SDK：

```bash
python examples/ai-agent/ch9-11-review/translation_contracts.py
python -m unittest discover -s examples/ai-agent/ch9-11-review -p "test_translation*.py" -v
```

它以两章固定短句验证词面命中、混用、一次有限修订和版本冲突，不调用真实 Agent，也不替代完整 Markdown/语义保真评估。上游回归测试、这份教学实验和真实翻译是三个不同层次。

### 源码与实验入口

- [chapter10/book-translation/agents.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/agents.py)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter10.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

## 10.8 指定译法命中、混用与严格遵从

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

## 本章要点 {#检查理解}

1. 上下文是否共享与协作拓扑是两个设计维度，管理者模式也可以使用隔离的子 Agent 上下文。
2. 互不依赖、产物可汇合的任务适合并行；协作收益需连同总成本和错误率评价。
3. 共享工作区可通过分支、worktree、版本检查和任务边界控制覆盖冲突。
4. Planner 可提出方案，业务校验和权限约束由确定性服务落实。
5. Reviewer 的贡献需在同任务、同模型和公平资料条件下对照，并统计质量、返工和全体用量。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
