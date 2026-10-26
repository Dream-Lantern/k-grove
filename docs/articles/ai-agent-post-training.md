---
id: ai-agent-post-training
title: 第7章 模型后训练：SFT、RL、偏好优化
description: 后训练不是只有一种算法。实践常见：SFT（监督微调）→ 偏好优化/DPO 或 RL（按需要）。
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
order: 7
---

# 第7章 模型后训练：SFT、RL、偏好优化

## 7.1 三个阶段各自改变了什么

1. **Tokenization（词元化）**：把文本变成离散 Token 序列。Tokenizer 是编码规则，不是训练模型理解世界的阶段。
2. **Pretraining（预训练）**：通常通过预测下一个 Token 训练基础表示与知识能力。
3. **Post-training（后训练）**：通过示范数据、偏好或奖励信号提高遵循指令、行为质量和工具使用能力。

后训练不是只有一种算法。实践常见：**SFT（监督微调）→ 偏好优化/DPO 或 RL（按需要）**。

## 7.2 SFT（Supervised Fine-Tuning）

目标是在给定输入 `x` 与高质量目标回答 `y` 后，提升正确目标序列的条件概率。常见训练只计算 Assistant 响应位置的 Loss，用户消息位置使用 Loss Masking。

**注意**：是否 Mask 掉用户 Token 取决于训练任务/数据模板/实现，不可当成所有 SFT 都必须如此。高质量示范可以教会格式、任务流程、工具调用样式，但模型对未覆盖的环境变化仍可能泛化不足。

### LoRA（Low-Rank Adaptation）

经典LoRA写为 `W = W0 + (α/r) B A`：`W0`冻结，`A∈R^(r×d_in)`、`B∈R^(d_out×r)`可训练。对给定LoRA参数，增量**等于**缩放后的BA；“近似”描述对完整更新空间的低秩限制，不是这条参数化等式的不精确。rsLoRA等变体可用`α/√r`缩放，记录rank/alpha时也应记录实现选项与库版本。依据：[LoRA原论文](https://arxiv.org/abs/2106.09685)、[PEFT v0.21.0 LoraConfig](https://huggingface.co/docs/peft/v0.21.0/package_reference/lora)。

- `rank (r)`：适配容量的超参数，不是越大一定越好。
- `alpha`：影响增量缩放，必须连同 rank 等因素一起理解。
- `target_modules`：只加 Attention 与同时加入 MLP 的效果可能不同。
- 全参微调 vs LoRA：取决于数据量、部署目标、显存与遗忘风险。

**对原笔记的修订**：`SFT rank 64–256、RL rank 8–32、学习率约全参 10 倍、LoRA 1%–5% 参数` 是书中归纳的部分实验/实践经验，并非可跨模型、模块、数据规模无条件复制的定律。实施时应先做小规模实验与回归。

## 7.3 RL（Reinforcement Learning）

五个核心要素：**环境、状态/观察、动作、策略、奖励/回报**；价值函数用于估计未来回报，部分算法还使用环境模型。

- **行为/动作**：生成答案、调用工具、编辑代码。
- **策略 Policy**：给定上下文如何分配动作概率。
- **奖励 Reward**：环境或评价机制给出的数值反馈，可来自任务规则、人类反馈、学习到的奖励模型或启发式代理；优化信号不自动等于事实正确性。RLVR才特指用可验证结果构造奖励的路线。
- **回报 Return**：未来奖励的累积，常写为折扣和 `G_t = Σ_(k≥0) γ^k R_(t+k+1)`，不等于单步即时奖励。
- **信用分配（Credit Assignment）**：长链任务成功/失败究竟归因于哪一步。

例如任务完成可给结果奖励、每次工具调用可扣成本；未经授权的动作应由执行器阻断，不能假设一个负奖励就能保证不发生。奖励接口参考 [Gymnasium Env.step](https://gymnasium.farama.org/api/env/)，与第7.6节硬约束配合理解。

探索与利用需要平衡：始终选择最有把握的行为，无法学习新策略；一直随机尝试，也无法稳定完成任务。

## 7.4 SFT 与 RL 如何选择

| 问题                 | SFT                            | RL                               |
| -------------------- | ------------------------------ | -------------------------------- |
| 是否有高质量目标示范 | 很适合                         | 不一定需要示范，但通常需要起点   |
| 能否对结果打分       | 非必要                         | 通常必要                         |
| 主要学习什么         | 输出格式、模仿模式、可示范流程 | 在环境中选择可获高回报的行为策略 |
| 反馈颗粒度           | Token 级目标标签               | 可为结果级/过程级奖励            |
| 相对代价             | 往往较低                       | 环境交互与验证成本可能较高       |
| 风险                 | 示范覆盖不足、复制坏模式       | 奖励投机、策略坍缩、分布漂移     |

原书借用 `mass-covering` 与 `mode-seeking` 解释监督学习和偏好/强化学习的一种倾向。**注意**：这是帮助理解的概念对比，不应被理解为“所有 SFT 必然覆盖所有模式”或“所有 RL 必然坍缩”。

## 7.5 RLHF、RLVR、DPO

- **RLHF**：Reinforcement Learning from Human Feedback；从人类偏好训练奖励模型，再以 RL 等方法优化策略。不是唯一的人类反馈路线。
- **RLVR**：Reinforcement Learning with Verifiable Rewards；使用可程序判定的正确性结果（测试通过、数学答案、格式验证等）做奖励。
- **DPO**：Direct Preference Optimization；利用偏好成对样本直接训练策略，不必显式训练单独的在线奖励模型。
- **PPO/GRPO**：后训练中不同的策略优化技术，具体优劣受训练配置与实现影响。

在工具型 Agent 中，不能把环境工具输出的 Token 当成模型自己应预测的动作目标；训练 Masking 与角色边界尤为重要。

## 7.6 奖励结果、约束过程

只有结果奖励会出现“达到分数但作弊”：例如为通过测试而删除测试、为获得订单成功率而绕过用户授权。

更可靠的设计是两层：

```text
结果验证：业务目标实现了吗？
过程验证：调用顺序、权限、动作、成本符合约束吗？
```

能由程序规则识别的违规行为，应通过不可绕过的约束阻止，而不只是纳入模型的软奖励。对于长期多轮任务，需要定位导致失败的工具调用，不能在结束时笼统地对所有步骤作相同处理。

## 7.7 On-policy蒸馏的研究边界

“在轨/同策略”指学习所用轨迹由当前学生策略生成。以下以明确论文为实例，不把所有OPD/OPSD变体归为同一算法：

| 实例                            | rollout生成者          | 教师可见信息与训练信号                                               | 教师参数关系                                                                 |
| ------------------------------- | ---------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| GKD中的on-policy distillation   | 学生生成自己的输出序列 | 教师对学生轨迹给分布反馈，选择分布间损失；学生并非只模仿固定教师答案 | 使用独立教师；具体冻结/更新策略须跟实验配置记录                              |
| Self-Distilled Reasoner中的OPSD | 学生仅看问题生成轨迹   | 教师还看已验证解法等特权上下文；沿学生轨迹匹配逐token分布            | 同一模型以不同上下文充当师生，梯度只反传学生支路；不能套用“固定独立教师”假设 |

来源：[GKD，arXiv:2306.13649v3](https://arxiv.org/abs/2306.13649v3)、[Self-Distilled Reasoner，arXiv:2601.18734v3，§3.2](https://arxiv.org/html/2601.18734v3)。两者的样本分布、教师输入和训练对象应分开记。

更密集的token监督不保证更便宜：还要计教师推理/logits、rollout长度、训练吞吐、验证成本与留出表现。[Rethinking On-Policy Self-Distillation for Thinking Models，arXiv:2607.05184v1](https://arxiv.org/abs/2607.05184v1)在其长推理任务和模型设置下观察到特权上下文带来的退化；这限制了外推范围，不能推出OPSD普遍无效。本次核对机制与论文范围，没有复现训练或引用它们的数值作为本地收益。

## 7.8 怎样把训练放进系统工程

对于更新频繁的事实：优先 RAG；对固定规则：优先代码校验；对可描述操作流程：考虑 Prompt/Skill；对大量广泛隐式策略或感知能力：才考虑参数训练。训练前先建立安全、可复现的 Eval 集，与训练数据隔离。

## 7.9 先做精确复制审计，再决定是否后训练

与工程最接近的训练例子是当前仓库 `chapter8/exact-copy-sft`：从编辑工具 `old_string` 匹配失败出发，分别检查字符生成、Tokenizer、序列化和工具参数，再用随机字符串做 LoRA 训练。另一个值得看的是 `premature-completion-dpo`，把“没有证据就提前宣告完成”变成偏好样本。

源码节选（上下文依赖见原文件）：[chapter8/exact-copy-sft/evaluate.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/evaluate.py#L20-L23)。

```python
pred = tok.decode(generated[0, ids.shape[-1]:], skip_special_tokens=True).strip(); target = row["target"]
pb, tb = pred.encode("utf-8"), target.encode("utf-8")
first = next((i for i, (a, b) in enumerate(zip(pb, tb)) if a != b), min(len(pb), len(tb)))
out.append({"id": row["id"], "kind": row["kind"], "exact": int(pb == tb), "prediction": pred, "target": target, "first_diff_byte": first})
```

这段评估在比较 UTF-8 字节之前对预测调用 `.strip()`。因此它测量的是“去掉预测首尾空白后的匹配”，并不是未经处理的完整输出 byte-exact。若空格或换行本身就是 `old_string` 的一部分，必须额外记录原始输出，报告 raw exact 与 normalized exact 两个指标。后处理契约允许去掉空白时可以保留，但需在指标名称里说明。

### 推荐实验顺序

1. 固定目标字符串，在模型前后、JSON 编解码前后、工具入口分别计算 UTF-8 长度和 Hash，找到第一个发生变化的边界。
2. 先运行 `python tokenizer_audit.py` 检查 round-trip；这一步也需要对应 Tokenizer 的模型文件，首次可能下载。
3. 确认问题确实在模型生成后，才对照基座与 LoRA。训练、留出和边界集按随机种子、字符组合、长度及包装上下文隔离。
4. 同时检查原始字节一致性、首个分歧位置和真实工具参数是否匹配；只看自然语言相似度会漏掉这一类失败。

![07-training](/assets/notes/ai-agent/07-training.svg)

图内实线框标固定提交可定位步骤，虚线框区分本地修订示例与建议；不代表整链已经实测。[SVG](/assets/notes/ai-agent/07-training.svg) · [可编辑 DOT](/assets/notes/ai-agent/07-training.dot)。

本次未进行 GPU 训练，也未调用计费模型，不能将仓库历史训练结果当作本地复现成绩。笔记中的本地脚本仅展示 Unicode、首尾空白和 JSON round-trip 的区别，用于判断应在哪一层修复错误。

DPO 的偏好对也应关联证据状态：同一句“已完成”，有读回证据时可能正确，缺少证据时则可能错误。如果仅按措辞标注 chosen/rejected，模型可能只是更擅长说“我还没完成”，任务能力却没有改善。

### 源码与实验入口

- [chapter8/exact-copy-sft/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter8.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html) · 统一验证入口（仅保留于本地审阅资料，公开版不提供）

## 检查理解

1. 什么知识应该放在 RAG，而不是要求模型通过 SFT 记住？
2. LoRA 为什么可以降低训练成本？Rank 越大就一定越好吗？
3. 为什么只奖励“任务成功”可能训练出危险的 Agent？
4. RLVR 与 RLHF 的奖励来源有什么区别？
5. 一个 Agent 不会正确输出 JSON，是先尝试 Schema 校验/提示示例，还是立即上 RL？

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
