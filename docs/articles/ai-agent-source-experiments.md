---
id: ai-agent-source-experiments
title: 源码实验地图：哪些值得先补、怎样验证
description: 源码固定于提交 dbc046eb896ac4e39aa19c7774c8bf49583b89a6，获取日期为 2026-10-22。下列优先级依据现有笔记缺口和工程迁移价值安排，并非仓库实验的官方评级。P0 用于建立最小理解闭环，P1 用于组件对照，P2 则在
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
order: 91
---

# 源码实验地图：哪些值得先补、怎样验证

源码固定于提交 `dbc046eb896ac4e39aa19c7774c8bf49583b89a6`，获取日期为 2026-10-22。下列优先级依据现有笔记缺口和工程迁移价值安排，并非仓库实验的官方评级。P0 用于建立最小理解闭环，P1 用于组件对照，P2 则在基础系统和评估成熟后研究。

## 先读这条主线

上下文消融 → 工具执行与反馈 → 混合检索 → 环境和轨迹评估 → 经验候选与门禁。语音和多 Agent 按项目需要选做；后训练先完成错误归因和数据审计。

下表列出公开仓库中的 22 个实验入口。实验代码及完整运行说明请从 [ai-agent-book 固定提交](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6) 获取，并遵守上游许可证。实验优先级是个人学习建议，不表示这些实验已在本站环境运行。

## 22 个重点实验

| 本地章 | 优先级 | 仓库目录                                                                                                                                                                                | 值得补什么                           | 建议练习                                                   | 验证与边界                                                          |
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

## 三种证据状态

| 状态           | 本次含义                                                                                       |
| -------------- | ---------------------------------------------------------------------------------------------- |
| 源码阅读       | 已查看指定提交的关键实现；不代表服务已启动或模型已调用                                         |
| 当前确定性检查 | 原有8组、审阅11组为上游观察；修订组另行记录；范围见实验README与对应run_id                      |
| 待复现         | 在线模型对照、完整 RAG 模型链、GPU 训练、真实音频/浏览器 campaign、Docker 候选代码门禁均未运行 |

仓库 README 中的历史数值、validation 文件和“已验收”标记均属于上游记录，不能将这些数值视为本地复现结果。引用历史结果前，还需核对相应 manifest、输入、硬件、模型和运行条件。

## 本地检查的唯一说明

运行方式、依赖、结果分组和历史保存规则统一在实验README（仅保留于本地审阅资料，公开版不提供）。原有8组结果仍保留为历史；当前运行以latest指针（仅保留于本地审阅资料，公开版不提供）指向的run_id清单为准，不能只看一个“通过”数字。

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

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
