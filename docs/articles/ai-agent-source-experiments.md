---
id: ai-agent-source-experiments
title: 源码实验地图：哪些值得先补、怎样验证
description: "按学习优先级组织固定提交中的 22 个源码实验入口，说明阅读重点、建议练习与结果记录方式。"
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
order: 91
---

# 源码实验地图：阅读顺序与验证方法 {#源码实验地图-哪些值得先补、怎样验证}

源码固定于提交 `dbc046eb896ac4e39aa19c7774c8bf49583b89a6`，获取日期为 2026-10-22。下列优先级是依据学习顺序和工程迁移价值制定的个人建议。P0 用于建立最小理解闭环，P1 用于组件对照，P2 则在基础系统和评估成熟后研究。

这里的 **学习 P0** 是优先理解的基础实验，**学习 P1** 是核心机制的进阶对照，**学习 P2** 是深入研究和扩展；它们不是源码缺陷等级或发布阻塞等级。按周安排见 [六周路线](/articles/ai-agent-learning-exercises.html)，本站与上游章号差异见 [章节对照](/articles/ai-agent-chapter-reference.html)。

## 先读这条主线

上下文消融 → 工具执行与反馈 → 混合检索 → 环境和轨迹评估 → 经验候选与门禁。语音和多 Agent 按项目需要选做；后训练先完成错误归因和数据审计。

第一次阅读可依次完成以下六站，先看输入怎样变成可检查的输出，再进入完整索引。上游命令均在对应目录执行，并先按该目录 README 准备依赖：

| 顺序与目录                                  | 阅读重点与最小入口                                                                                                  | 运行前提与预期观察                                               | 后续深入                                                   |
| ------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------- | ---------------------------------------------------------- |
| 1：`chapter1/web-search-agent`              | 工具循环；`python main.py --provider offline-demo --output demo.json`                                               | 安装项目依赖；无需 Key，观察预写 `trace` 中行动、观察与答案      | 上下文消融或真实工具反馈                                   |
| 2：`chapter2/context-compression`           | 六种压缩策略；`python experiment.py --list-strategies`                                                              | 先安装依赖；列出策略，随后只读比较保留／丢弃哪些信息             | 固定快照与尾部事实负例；真实模型实验另配服务               |
| 3：`chapter3/retrieval-pipeline`            | 召回、融合、重排；按[第3章 BM25 步骤](/articles/ai-agent-memory-rag.html#最小-bm25-实验-先验证输入、输出与指标)执行 | BM25 依赖与语料；观察候选 ID、排名和指标，不加载 Dense 模型      | 同数据加入 Dense／RRF／Rerank                              |
| 4：`chapter4/execution-tools`               | 执行和验证；`python cli.py list` 后阅读文件工具测试                                                                 | 项目依赖；先查看工具目录，再在临时工作区测试允许／拒绝路径       | `python cli.py demo`；执行类工具按 README 准备 Bash 等环境 |
| 5：`chapter7/user-memory-system-evaluation` | 读 `retrieval_metrics()`、`RunRecord`、完整性检查；依赖就绪后 `python experiment.py --help`                         | 先理解输入配置与结果字段；不从历史报告推定本地已运行             | 配对矩阵、成本覆盖；实际后端实验另配模型和数据             |
| 6：`chapter10/book-translation`             | 文件交接与上下文隔离；`python demo.py --dry-run`                                                                    | SDK、tiktoken 与编码缓存；观察角色、计划和上下文预算，无模型调用 | 同资料单 Agent 基线、术语／审校消融与质量证据              |

### 先确定实验属于哪个仓库

| 来源／运行方式         | 执行位置与条件                                                          |
| ---------------------- | ----------------------------------------------------------------------- |
| 固定提交的上游实验     | 在 ai-agent-book 的对应目录运行；本文 `chapterN/…` 指上游路径           |
| 本地独立教学脚本       | 从 k-grove 根目录运行 `examples/ai-agent/…`；标准库示例通常无需模型服务 |
| Markdown 内嵌代码      | 按正文给出的环境、目录和输入操作；片段不一定能脱离上下文独立运行        |
| 真实模型 API 实验      | 额外固定模型、端点、配置及费用口径；离线轨迹不属于此类                  |
| GPU 训练／本地模型实验 | 单独准备权重、驱动、依赖与数据；按对应 README 记录硬件和模型 revision   |

下表列出公开仓库中的 22 个实验入口。实验代码及完整运行说明请从 [ai-agent-book 固定提交](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6) 获取，并遵守上游许可证。实验优先级是个人学习建议，不表示这些实验已在本站环境运行。

## 22 个重点实验

| 本地章 | 优先级 | 仓库目录                                                                                                                                                                                | 学习重点                             | 建议练习                                                   | 验证与边界                                                          |
| ------ | ------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------ | ---------------------------------------------------------- | ------------------------------------------------------------------- |
| 1      | P0     | [chapter1/context](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/context/README.md)                                                   | 把历史、调用意图与工具结果分开消融   | 固定单任务和预算，对照五种消息配置；逐轮保存真实请求       | 任务正确性、重复工具调用、协议错误；不要预设去掉 reasoning 必然退化 |
| 1      | P0     | [chapter1/web-search-agent](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter1/web-search-agent/README.md)                                 | 先看懂工具闭环                       | 先跑 offline-demo，再按需换真实提供商                      | 离线轨迹为预写数据，不是模型能力测试                                |
| 2      | P0     | [chapter2/context-compression](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter2/context-compression/README.md)                           | 比较六种压缩策略与失败回退           | 固定搜索快照，并把必需事实放到输入尾部做负例               | 事实保留、引用、溢出、摘要与主模型总用量                            |
| 2      | P1     | [chapter2/kv-cache](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter2/kv-cache/README.md)                                                 | 用请求证据解释缓存                   | 对照稳定前缀、动态 system、打乱工具等布局                  | cached_tokens 与逐轮 TTFT；前缀相同不自动证明命中                   |
| 2      | P1     | [chapter2/prompt-injection](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter2/prompt-injection/README.md)                                 | 学习分层防御的消融方法               | 同一攻击矩阵比较不同防御配置，只在测试环境运行             | 攻击成功率与正常任务误拒率同时统计                                  |
| 3      | P0     | [chapter3/retrieval-pipeline](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter3/retrieval-pipeline/README.md)                             | 把混合检索拆到召回、融合、重排       | 先 BM25，再加 Dense/RRF/Rerank；保存各阶段候选             | Hit/Recall/MRR 和时延；正确文档未召回时重排无从修复                 |
| 3      | P1     | [chapter3/user-memory](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter3/user-memory/README.md)                                           | 把记忆格式映射为读写成本             | 比较同一组事实的表示、关联与检索；不使用私人数据做公开样本 | 冲突处理、过期事实、召回与最终答案分开看                            |
| 4      | P0     | [chapter4/execution-tools](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter4/execution-tools/README.md)                                   | 明确执行与验证的边界                 | 从路径、写入/编辑、幂等测试读起；只用临时工作区            | 失败时是否写入、重复业务键、结果验证，不连接外部写入工具            |
| 4      | P1     | [chapter4/active-tool-discovery](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter4/active-tool-discovery/README.md)                       | 解释渐进工具加载                     | 固定任务与工具全集，对比全量注入和按需发现                 | 发现召回率、选错工具、Schema token 与新增轮次                       |
| 5      | P0     | [chapter5/coding-agent](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter5/coding-agent/README.md)                                         | 把错误反馈接回主循环                 | 追踪 BaseTool、EditTool、SystemState，再做小仓库修复       | 改动行为、回归、工具计数；静态风险扫描不是运行沙盒                  |
| 5      | P1     | [chapter5/permission-embedded-data-objects](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter5/permission-embedded-data-objects/README.md) | 把权限和数据访问一起设计             | 阅读授权数据对象及测试，对照仅靠提示词的方案               | 权限是否由服务端强制；不要在笔记里假造集成结果                      |
| 6      | P0     | [chapter7/user-memory-system-evaluation](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter7/user-memory-system-evaluation/README.md)       | 学习完整评估记录与矩阵验收           | 从 retrieval_metrics/RunRecord 到 completion_assessment    | 缺失单元、API 错误、未计价用量必须显式保留                          |
| 6      | P1     | [chapter7/agent-cost-analysis](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter7/agent-cost-analysis/README.md)                           | 按完整链路分析成本                   | 对照缓存布局与压缩；计入检索、摘要、重试与主模型           | 总成本、原生币种、成功任务成本；不直接合并不同币种                  |
| 7      | P1     | [chapter8/exact-copy-sft](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/README.md)                                     | 定位逐字复制失败发生在哪层           | 先 Unicode/JSON/Tokenizer 审计，再考虑 LoRA                | raw byte exact 与后处理 exact 分开；训练需 GPU，未运行              |
| 7      | P2     | [chapter8/premature-completion-dpo](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/premature-completion-dpo/README.md)                 | 把提前宣告完成变成证据约束的偏好样本 | 阅读数据生成与评分条件，先检查接口与验证器                 | 区分措辞变化与真实完成；训练和保留集隔离                            |
| 8      | P0     | [chapter9/trajectory-verifier](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter9/trajectory-verifier/README.md)                           | 让声明与真实工具结果对照             | 先启发式检查，再审视 LLM Judge 的校准                      | 确定性结果冲突可检查；词面匹配不等于语义证明                        |
| 8      | P1     | [chapter9/self-modifying-agent](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter9/self-modifying-agent/README.md)                         | 理解候选代码门禁和回滚               | 只读诊断、候选、静态检查、Docker 边界与 manifest           | 源码可读不等于已运行；本次未启动候选执行或发布                      |
| 8      | P1     | [chapter9/harness-safety-gate](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter9/harness-safety-gate/README.md)                           | 比较代码护栏与提示词修补             | 读稳定 dispatcher 与门禁候选，查看边界/保留案例            | 正常任务保留率与违规阻断率，不只看攻击被拒绝                        |
| 9      | P0     | [chapter6/streaming-speech](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/streaming-speech/README.md)                                 | 理解全双工打断状态                   | 先用合成块测试停止、队列清空和重规划，再接真实音频         | 状态机通过不代表首音频/打断延迟达标                                 |
| 9      | P1     | [chapter6/async-agent](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter6/async-agent/README.md)                                           | 检查取消是否真的生效                 | 阅读真实任务执行与取消测试，追踪子进程生命周期             | 进程退出、进度冻结、晚到事件，不只看取消消息                        |
| 10     | P0     | [chapter10/book-translation](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/README.md)                               | 把共享契约与上下文隔离结合           | 对照单 Agent、编排、无术语 Agent、无审校 Agent             | 指定术语遵从、语义质量、Manager 峰值与全体总用量                    |
| 10     | P1     | [chapter10/parallel-web-research](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/parallel-web-research/README.md)                     | 理解并行后的唯一结算和清理           | 同来源串并行对照，观察锁、终止广播与 context 关闭          | 耗时、缺失任务、重复命中、资源泄漏同时核对                          |

## 实验记录的证据状态 {#三种证据状态}

| 状态         | 记录含义与可追溯入口                                                                                                                   |
| ------------ | -------------------------------------------------------------------------------------------------------------------------------------- |
| 上游历史实验 | 固定提交中的历史运行；例如翻译 `real_20260730T061500Z_v4/evidence.json`，原始模型和指标见[第10章](/articles/ai-agent-multi-agent.html) |
| 当前本地检查 | 在 k-grove 实际执行的脚本和测试；下文给出复制审计的完整记录，不与上游历史数值合并                                                      |
| 静态源码核查 | 查看固定提交文件、参数与分支；本轮核对了完整索引的 22 个 README 及十章映射，不代表执行全部实验                                         |
| 待复现       | 当前未运行的付费模型对照、完整 RAG 模型链、GPU 训练、真实音频／浏览器 campaign 和 Docker 候选门禁，分别按实验登记                      |

仓库 README 中的历史数值、validation 文件和“已验收”标记均属于上游记录，不能将这些数值视为本地复现结果。引用历史结果前，还需核对相应 manifest、输入、硬件、模型和运行条件。

例如以下记录指向已经存在的上游翻译回执；`run_id` 沿用原目录名，不是本站新跑的翻译任务：

```yaml
experiment: chapter10/book-translation
source_commit: dbc046eb896ac4e39aa19c7774c8bf49583b89a6
evidence_origin: upstream
execution_type: historical_real_api
run_id: real_20260730T061500Z_v4
evidence_ref: validation/real_20260730T061500Z_v4/evidence.json
```

[原始 evidence.json](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter10/book-translation/validation/real_20260730T061500Z_v4/evidence.json)同时保留 Token、时间、匿名质量评价和结构检查。引用时应保留少用 Token 却更慢、术语一致率降低等负结果。此前“8 组／11 组”的笼统汇总不再作为证据，具体结论以各自回执与执行类型为准。

## 本地检查的记录要求 {#本地检查的唯一说明}

每次检查应记录代码版本、依赖、命令、输入、结果分组与唯一 run_id。保留历史结果，当前运行单独标识；汇总时同时列出检查范围、通过项、失败项和未运行项，避免用一个总数代替证据。

## 在线实验的记录模板

```yaml
source_commit: dbc046eb896ac4e39aa19c7774c8bf49583b89a6
entrypoint: "chapterN/project/script.py"
model_and_revision: "实际使用值，不沿用 README 默认值"
dataset_snapshot_and_hash: "..."
environment: {python: "...", dependencies: "...", hardware: "..."}
controlled_variables: []
changed_variable: "仅一项或预先定义的因子矩阵"
repeats_and_seeds: []
success_definition: "环境验证器及统计口径"
metrics: {quality: null, latency: null, tokens: null, cost: null}
api_errors_and_missing_cells: []
evidence_paths: []
conclusion_and_limits: "..."
```

### 一份实际完成的本地记录

2026-11-12 在 k-grove 根目录用 Python 3.12.10 执行标准库审计，退出码 0：

```bash
python -X utf8 examples/ai-agent/ch6-8-review/copy_audit.py
```

代码基线为本地提交 `d2a1fdd533cbeab576e26de404b22376bced0ab7`，该脚本 SHA-256 为 `58114e2f8b967aac6e9d69366bc1a950339d234f22fe6062bffa00dba1dc15a6`。本次记录 ID 为 `local_copy_audit_20261112`；完整输入、原始输出、Python 版本与实际命令保存在本仓库 `examples/ai-agent/ch6-8-review/validation/copy-audit-20261112.json`，可取得源码后复核。

| 固定输入                              | 实际输出                                                            | 结果解释                                      |
| ------------------------------------- | ------------------------------------------------------------------- | --------------------------------------------- |
| prediction=`" abc\n"`，target=`"abc"` | 字节数 5／3；`raw_exact=false`、`normalized_exact=true`，首差字节 0 | 匹配来自预测 `.strip()`，不能写成原样复制成功 |
| 预组合 `é` 与组合重音表示             | raw／normalized 均 false，`nfc_diagnostic_equal=true`               | Unicode 等价诊断不等于字节相等                |
| 中文经 JSON 转义再解码                | JSON 序列化文本不同，解码后的 `raw_exact=true`                      | 分别审计序列化表示与解析后的字符串            |

这份记录只来自本地标准库脚本，没有加载 Tokenizer 或训练模型。复跑时保存为新的记录，记录代码 Hash、命令与输出，避免覆盖历史回执。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
