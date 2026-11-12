---
id: ai-agent-post-training
title: 第7章 模型后训练：SFT、RL、偏好优化
description: "介绍 SFT、LoRA、强化学习和偏好优化的基本机制，并结合精确复制与工具使用说明训练信号、硬约束和验证方法。"
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
order: 7
---

# 第7章 模型后训练：SFT、RL、偏好优化

## 7.1 词元化、预训练与后训练 {#_7-1-三个阶段各自改变了什么}

1. **Tokenization（词元化）**：把文本变成离散 Token 序列。Tokenizer 是编码规则，不是训练模型理解世界的阶段。
2. **Pretraining（预训练）**：通常通过预测下一个 Token 训练基础表示与知识能力。
3. **Post-training（后训练）**：通过示范数据、偏好或奖励信号提高遵循指令、行为质量和工具使用能力。

后训练包含多种方法，实践常见路径为：**SFT（监督微调）→ 偏好优化/DPO 或 RL（按需要）**。

第 6 章先判断任务是否成功，这里再问怎样改变导致失败的行为。假设 Agent 经常选错工具、复制错误参数、提前宣布完成，先按原因选择改进方式：

| 问题                       | 优先考虑            | 为什么                       |
| -------------------------- | ------------------- | ---------------------------- |
| 缺少最新接口知识           | 更新知识库或检索    | 提供当前版本事实             |
| 工具参数格式错误           | Schema、参数校验    | 在执行入口确定性地拦截错误   |
| 工具调用流程不清楚         | Prompt、Skill、示范 | 先把正确步骤表达清楚         |
| 多种任务中反复出现策略错误 | SFT、偏好优化或 RL  | 利用跨任务数据改变行为分布   |
| 复杂隐式感知与行为能力不足 | 评估后考虑参数训练  | 某些能力难以仅用显式规则表达 |

**后训练通过修改模型参数改变行为，但不是所有 Agent 问题都需要训练。** 先排除数据、协议和执行器缺陷，再进入下面的训练方法；7.8 节讨论怎样验证训练是否带来系统收益。

## 7.2 SFT（Supervised Fine-Tuning）

目标是在给定输入 `x` 与高质量目标回答 `y` 后，提升正确目标序列的条件概率。常见训练只计算 Assistant 响应位置的 Loss，用户消息位置使用 Loss Masking。

**注意**：是否 Mask 掉用户 Token 取决于训练任务/数据模板/实现，不可当成所有 SFT 都必须如此。高质量示范可以教会格式、任务流程、工具调用样式，但模型对未覆盖的环境变化仍可能泛化不足。

### 一条问答怎样变成训练信号

用“用户：2+2 等于几？助手：4”作教学样本。实际训练先用 **Chat Template（聊天模板）**把角色和消息拼成模型约定的序列，再由 Tokenizer 编码。下面只画出逻辑位置；`<user>` 等是示意标记，`4` 也不保证在所有 Tokenizer 中恰好是一个 Token：

一次训练更新依次做四件事：

1. 准备输入问题与目标回答，明确本例要监督 `4` 及约定的结束标记。
2. 用聊天模板组织角色消息，Tokenizer 编码后生成输入、目标标签和损失掩码。
3. 前向计算每个目标 Token 的概率，再由有效标签位置计算损失。
4. 反向传播得到梯度，由优化器更新可训练参数，进入下一批样本。

```text
输入上下文：  <user> 2+2 等于几？ <assistant>
目标回答：                                   4 <结束>
损失标签：    忽略用户与提示位置              监督回答与约定的结束位置
```

Assistant Token 是属于助手目标回答的 Token。采用 **Teacher Forcing（教师强制）**时，每个预测位置看到的是正确的前缀，而不是模型上一步随机生成的错误前缀。例如目标回答有多个 Token，预测第二个时输入中提供正确的第一个 Token。实现可并行计算各位置，但因果注意力不允许模型偷看当前待预测 Token 及后文。

**Cross-Entropy Loss（交叉熵损失）**对目标 Token 取负对数概率，并按约定的有效位置归约。假设 `4` 在此样本中是一个目标 Token，模型给它的条件概率为 0.25，该位置损失是 `-ln(0.25) ≈ 1.386`；如果之后概率提高到 0.5，损失就降到 `-ln(0.5) ≈ 0.693`。0.5 是比较损失变化的假设值，不是一次更新必然达到的概率。

**梯度（Gradient）**描述损失对各可训练参数的局部变化率；反向传播计算这些变化率，**优化器（Optimizer）**再按学习率及自身规则调整参数。普通梯度下降可示意为 `θ ← θ - η∇θL`，实际脚本使用的 AdamW 还维护梯度统计并处理权重衰减。全参微调更新选定的基础权重；使用 LoRA 时通常冻结基础权重，更新适配器参数。一次更新依据当前批次降低训练目标，是否改善其他样本还要用留出集检查。

常见 SFT 只在助手目标位置计算损失，是因为任务要学习“给定用户输入后怎样回答”，不一定需要学习“怎样续写用户的问题”。**Loss Masking（损失掩码）**排除的是相应目标位置的直接损失，不是把用户输入删掉；用户上下文仍参与前向计算，也会影响助手位置的梯度。Padding、系统消息、工具观察、结束标记是否计入目标，要按训练实现明确。

聊天模板机制见 [Transformers v4.51.3 文档](https://huggingface.co/docs/transformers/v4.51.3/chat_templating)。本章第 7.9 节的固定源码 `train_sft.py` 在 `encode()` 中给提示标签填 `-100`，保留目标及 EOS 标签，再按长度截断；这是该实现的选择，并不意味着所有 SFT 都采用同一种掩码或截断规则。

### LoRA（Low-Rank Adaptation）

LoRA（低秩适配）在冻结的基础权重旁学习一个受限制的增量。先看二维例子，令 `r=1, alpha=1`：

```text
A = [1  2]       B = [3]       BA = [3  6]
                     [4]            [4  8]
```

`BA` 的两行成比例，秩至多为 1，不能表示任意二维矩阵更新。这个小例子只用来理解增量的结构；两个适配器在这里合计仍有 4 个参数，并不省参数。对大矩阵，若 `r` 远小于输入、输出维度，才会把 `d_out × d_in` 个可训练元素换成 `r(d_in+d_out)` 个。基础权重保留已有映射，A、B 学习任务所需增量；前向同时使用两部分，反向只更新被设为可训练的参数。

经典LoRA写为 `W = W0 + (α/r) B A`：`W0`冻结，`A∈R^(r×d_in)`、`B∈R^(d_out×r)`可训练。对给定LoRA参数，增量**等于**缩放后的BA；“近似”描述对完整更新空间的低秩限制，不是这条参数化等式的不精确。rsLoRA等变体可用`α/√r`缩放，记录rank/alpha时也应记录实现选项与库版本。依据：[LoRA原论文](https://arxiv.org/abs/2106.09685)、[PEFT v0.21.0 LoraConfig](https://huggingface.co/docs/peft/v0.21.0/package_reference/lora)。

- `rank (r)`：适配容量的超参数，不是越大一定越好。
- `alpha`：影响增量缩放，必须连同 rank 等因素一起理解。
- `target_modules`：只加 Attention 与同时加入 MLP 的效果可能不同。
- 全参微调 vs LoRA：取决于数据量、部署目标、显存与遗忘风险。

**参数经验的适用范围**：书中归纳了 `SFT rank 64–256、RL rank 8–32、学习率约全参 10 倍、LoRA 1%–5% 参数` 等部分实验/实践经验。选择参数时需结合模型、目标模块与数据规模，通过小规模实验和回归确认适用性。

### 单个矩阵的 LoRA 参数手算

取一个 `4096 × 4096` 权重矩阵，令 `r=8`：

| 对象      | 形状          | 参数数       |
| --------- | ------------- | ------------ |
| 原矩阵 W0 | `4096 × 4096` | `16,777,216` |
| A         | `8 × 4096`    | `32,768`     |
| B         | `4096 × 8`    | `32,768`     |
| A、B 合计 | 两个低秩矩阵  | `65,536`     |

因此适配器的可训练参数量相对该原矩阵是 `65,536 / 16,777,216 = 1/256 = 0.390625%`。若 `alpha=16`，经典缩放系数 `alpha/r=2`，前向计算使用 `W0x + 2B(Ax)`；缩放改变增量幅度，不增加 A、B 的元素数。rsLoRA 的缩放口径见上文，不应套用这个系数。

这里只统计一个矩阵、无额外可训练偏置等参数的情况。全模型还取决于选择多少层与模块；训练显存还包含基础权重、激活、梯度、优化器状态等，不能把 0.390625% 当作整个模型的训练显存比例。

## 7.3 RL（Reinforcement Learning）

五个核心要素：**环境、状态/观察、动作、策略、奖励/回报**；价值函数用于估计未来回报，部分算法还使用环境模型。

- **行为/动作**：生成答案、调用工具、编辑代码。
- **策略 Policy**：给定上下文如何分配动作概率。
- **奖励 Reward**：环境或评价机制给出的数值反馈，可来自任务规则、人类反馈、学习到的奖励模型或启发式代理；优化信号不自动等于事实正确性。RLVR才特指用可验证结果构造奖励的路线。
- **回报 Return**：未来奖励的累积，常写为折扣和 `G_t = Σ_(k≥0) γ^k R_(t+k+1)`，不等于单步即时奖励。
- **信用分配（Credit Assignment）**：长链任务成功/失败究竟归因于哪一步。

回报式中，`t` 是当前步骤，`k` 表示向后第几个奖励，`R_(t+k+1)` 是对应的即时奖励，`γ∈[0,1]` 是折扣因子；越小越偏向近期奖励。有限任务可在终止处截断求和，持续任务还需保证回报定义有界。

例如任务完成可给结果奖励、每次工具调用可扣成本；未经授权的动作应由执行器阻断，不能假设一个负奖励就能保证不发生。奖励接口参考 [Gymnasium Env.step](https://gymnasium.farama.org/api/env/)，与第7.6节硬约束配合理解。

探索与利用需要平衡：始终选择最有把握的行为，无法学习新策略；一直随机尝试，也无法稳定完成任务。

### Coding Agent 的一次轨迹与一次训练更新

复用 [第 5 章平均值修复](/articles/ai-agent-coding-agent.html#_5-6-小型项目练习)，任务要求空列表抛出 `ValueError`。下面两条是用于比较训练信号的教学轨迹：

- **轨迹 A**：读取失败测试 → 定位 `ZeroDivisionError` → 修改 `average.py` 的空输入处理 → 保留测试 → 验证成功。
- **轨迹 B**：读取失败测试 → 删除空输入测试 → 剩余测试表面通过，原需求仍未实现。

先沿轨迹 A 对应基本概念：

| 环节                   | 本例内容                                                     | 对应概念                                     |
| ---------------------- | ------------------------------------------------------------ | -------------------------------------------- |
| 读到失败用例与相关代码 | 当前测试说明空输入处理错误；真实环境状态还包括仓库与测试文件 | 观察 observation，是 Agent 可见的状态信息    |
| 提议并执行代码编辑     | 策略选择编辑函数，而非删除测试                               | 动作 action，由策略决定                      |
| 再次运行测试           | 工具返回退出码、失败详情与输出                               | 环境反馈，形成下一步观察                     |
| 通过独立检查           | 测试与过程约束均通过，任务才记成功                           | 可验证奖励；本例可约定合规成功为 1，否则为 0 |
| 汇集多次执行记录       | 保存观察、动作、反馈、奖励和后续观察                         | 轨迹 trajectory，用于后续训练或分析          |

普通 Agent 在推理时也会“看报错→改代码→再测试”，但如果没有计算训练目标并由优化器更新模型参数，这仍是执行循环。RL 训练会利用多条轨迹中的奖励或优势估计优化策略参数，让较有利的动作在类似上下文中更可能被选择。具体梯度估计、是否另训价值函数以及采样方式随算法而变。

同一对轨迹可以产生不同训练信号：

| 方法                                                                       | 使用什么数据或反馈                                              | 参数更新的学习目标                       |
| -------------------------------------------------------------------------- | --------------------------------------------------------------- | ---------------------------------------- |
| SFT                                                                        | 筛选后的高质量轨迹 A                                            | 提高正确工具调用与修复序列的条件概率     |
| RLVR（Reinforcement Learning with Verifiable Rewards，可验证奖励强化学习） | 独立验证器检查实现、冻结测试和过程约束；本例约定 A 为 1、B 为 0 | 提高能获得有效奖励的行为概率             |
| DPO（Direct Preference Optimization，直接偏好优化）                        | 同一输入下 A 为优选、B 为劣选的配对                             | 相对参考策略，提高 A 相对 B 的序列概率比 |

DPO 的相对概率目标见[原论文 v3](https://arxiv.org/abs/2305.18290v3)，它不要求先在线执行一套 RL 交互循环。三者都需要防止评测泄漏；若奖励器只看当前目录 pytest 退出码，B 就可能钻过漏洞，因此测试完整性和权限等过程约束也必须检查。普通修复循环只调整本次动作；只有计算训练目标、梯度并更新参数，才是在训练模型。

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

`mass-covering` 可理解为给数据中多个有效模式保留概率：例如两种都正确的修复路径都出现在示范里，学习时不希望漏掉其中一种。`mode-seeking` 则强调把概率集中到较受偏好或奖励的模式。它们与分布间损失方向、采样分布及优化约束有关，不是“SFT 等于前者、RL 等于后者”的算法定义；集中到一条可靠路径也不等于已经发生有害坍缩。

## 7.5 RLHF、RLVR、DPO

- **RLHF**：Reinforcement Learning from Human Feedback；从人类偏好训练奖励模型，再以 RL 等方法优化策略。不是唯一的人类反馈路线。
- **RLVR**：Reinforcement Learning with Verifiable Rewards；使用可程序判定的正确性结果（测试通过、数学答案、格式验证等）做奖励。
- **DPO**：Direct Preference Optimization；利用偏好成对样本直接训练策略，不必显式训练单独的在线奖励模型。
- **PPO（Proximal Policy Optimization，近端策略优化）**：约束策略更新幅度的一类方法；常见 PPO-Clip 用概率比裁剪限制目标中的激励。
- **GRPO（Group Relative Policy Optimization，组相对策略优化）**：利用同一问题的一组采样结果的相对奖励构造优势；原始设计不需要单独的价值模型。它与 PPO 的具体优劣仍受训练配置与实现影响。

算法背景可对照 [PPO 原论文 v2](https://arxiv.org/abs/1707.06347v2)与引入 GRPO 的 [DeepSeekMath v3，§4](https://arxiv.org/html/2402.03300v3#S4)。组内奖励若无法区分候选，或验证器本身有漏洞，增加优化步骤也不会自动产生可靠的学习信号。

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

本节作为进阶阅读：先理解师生反馈链，再比较论文中的训练条件。教师是提供监督的模型，学生是接受更新的模型；普通离线蒸馏可先固定教师生成的数据，再训练学生。下面的同策略方法则先让学生走自己的生成路径。

```text
学生生成自己的序列（rollout）
    → 教师沿学生实际前缀给出下一 Token 的分布反馈
    → 学生计算分布间损失
    → 反向传播并更新学生参数，再生成下一批序列
```

**蒸馏（Distillation）**用教师的输出或概率分布监督学生。**OPD（On-Policy Distillation，同策略蒸馏）**让学生先生成序列，再沿学生实际经过的前缀接受教师反馈，减少“训练只见教师前缀、推理却要面对自己错误”的分布差异。**OPSD（On-Policy Self-Distillation，同策略自蒸馏）**进一步使用同一模型或相关参数版本承担师生角色，具体反馈来源仍需看论文。

**GKD（Generalized Knowledge Distillation，广义知识蒸馏）**是下表中的一种具体方法，不是 OPD 的同义缩写。教师分布是对“下一个 Token 的概率”提供软监督，不是已经证明整段回答正确；rollout 指策略生成并展开一条序列或交互轨迹。

“在轨/同策略”指学习所用轨迹由当前学生策略生成。以下以明确论文为实例，不把所有OPD/OPSD变体归为同一算法：

| 实例                            | rollout生成者          | 教师可见信息与训练信号                                               | 教师参数关系                                                                 |
| ------------------------------- | ---------------------- | -------------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| GKD中的on-policy distillation   | 学生生成自己的输出序列 | 教师对学生轨迹给分布反馈，选择分布间损失；学生并非只模仿固定教师答案 | 使用独立教师；具体冻结/更新策略须跟实验配置记录                              |
| Self-Distilled Reasoner中的OPSD | 学生仅看问题生成轨迹   | 教师还看已验证解法等特权上下文；沿学生轨迹匹配逐token分布            | 同一模型以不同上下文充当师生，梯度只反传学生支路；不能套用“固定独立教师”假设 |

来源：[GKD，arXiv:2306.13649v3](https://arxiv.org/abs/2306.13649v3)、[Self-Distilled Reasoner，arXiv:2601.18734v3，§3.2](https://arxiv.org/html/2601.18734v3)。两者的样本分布、教师输入和训练对象应分开记。

更密集的token监督不保证更便宜：还要计教师推理/logits、rollout长度、训练吞吐、验证成本与留出表现。[Rethinking On-Policy Self-Distillation for Thinking Models，arXiv:2607.05184v1](https://arxiv.org/abs/2607.05184v1)在其长推理任务和模型设置下观察到特权上下文带来的退化；这限制了外推范围，不能推出OPSD普遍无效。这里介绍论文中的机制与适用范围，训练尚未本地复现，论文结果应与本地收益分开记录。

## 7.8 怎样把训练放进系统工程

按 7.1 节的根因表选择载体后，训练前先建立安全、可复现且与训练数据隔离的 Eval 集。精确复制的收益需要依次跨过三个层次：

| 层次       | 检查什么                                            | 能说明什么                                         |
| ---------- | --------------------------------------------------- | -------------------------------------------------- |
| 训练目标   | 训练 Loss 是否下降                                  | 对训练标签的拟合是否改善                           |
| 留出表现   | 同条件基座／适配器的 raw 与 normalized exact        | 未用于训练的数据上是否改善，以及改善是否依赖后处理 |
| Agent 任务 | 实际传入编辑工具的 `old_string`、编辑结果和独立测试 | 复制改善是否传递到了工具调用与任务结果             |

第三层可继续用 `average.py`：在独立副本中记录模型生成的编辑参数，比较 `old_string` 与文件目标片段的 UTF-8 字节，确认只匹配预定位置；执行编辑后读回文件，再运行不变的三个测试并审阅 Diff。基座与适配器须使用相同初态、工具、预算和验证规则，分别记录参数匹配、编辑成功与任务通过。Loss 降低不能跳过后两层验证。

## 7.9 先做精确复制审计，再决定是否后训练

与工程最接近的训练例子是当前仓库 `chapter8/exact-copy-sft`：从编辑工具 `old_string` 匹配失败出发，分别检查字符生成、Tokenizer、序列化和工具参数，再用随机字符串做 LoRA 训练。另一个值得看的是 `premature-completion-dpo`，把“没有证据就提前宣告完成”变成偏好样本。

先问：**精确复制失败来自哪个阶段？** 安装模型前，沿链路找第一次变化的位置：

```text
原始字符串 → JSON / Chat Template → Tokenizer → 模型生成 → 输出后处理 → 工具参数
```

JSON 编码可能把换行表示为转义文本，解码后应恢复原字符；聊天模板会加入角色和控制标记；Tokenizer 编解码需核对是否改变字符；模型可能漏字或补空白；后处理可能删除空白；工具入口还可能再次解析或转换。每个边界分别保留字符串、字节或 Token ID，不能只看最后一次匹配失败。

例如同一输出可以得到两种指标：

```python
prediction = " abc\n"
target = "abc"
raw_exact = prediction.encode("utf-8") == target.encode("utf-8")
normalized_exact = prediction.strip().encode("utf-8") == target.encode("utf-8")
# raw_exact=False，normalized_exact=True
```

差异来自后处理，不能据此说模型原样复制成功。下面先核对固定源码采用哪种口径，再按三个层级定位问题。

源码节选（上下文依赖见原文件）：[chapter8/exact-copy-sft/evaluate.py](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/evaluate.py#L20-L23)。

```python
pred = tok.decode(generated[0, ids.shape[-1]:], skip_special_tokens=True).strip(); target = row["target"]
pb, tb = pred.encode("utf-8"), target.encode("utf-8")
first = next((i for i, (a, b) in enumerate(zip(pb, tb)) if a != b), min(len(pb), len(tb)))
out.append({"id": row["id"], "kind": row["kind"], "exact": int(pb == tb), "prediction": pred, "target": target, "first_diff_byte": first})
```

这段评估在比较 UTF-8 字节之前对预测调用 `.strip()`。因此它测量的是“去掉预测首尾空白后的匹配”，并不是未经处理的完整输出 byte-exact。若空格或换行本身就是 `old_string` 的一部分，必须额外记录原始输出，报告 raw exact 与 normalized exact 两个指标。后处理契约允许去掉空白时可以保留，但需在指标名称里说明。

<a id="推荐实验顺序"></a>

### 分三级做精确复制实验

三个层级回答不同的问题。第一层检查数据链路，第二层检查真实 Tokenizer，第三层才比较模型生成能力；前两层失败时，应先定位原因，避免把链路损坏归因于模型。

| 层级           | 输入与运行入口                                                               | 观察字段与下一步                                                                           |
| -------------- | ---------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| 字符串／字节   | 本地合成字符串，运行下文 `copy_audit.py`                                     | 对照 `raw_exact`、`normalized_exact`、首个差异及 JSON 往返；先解释链路变化，再进第二层     |
| Tokenizer 往返 | 上游生成的 eval／boundary 的 `source`，运行 `tokenizer_audit.py`             | 查看 `probe_count`、`roundtrip_rate`、`failures`；往返失败先定位编码规则，通过后才比较生成 |
| 基座／LoRA     | 同一数据、模型与生成配置，依次运行 `evaluate.py`、`train_sft.py`、适配器评估 | 对齐训练回执与四份评估文件，比较留出和边界表现；再按 7.8 节进入真实工具验证                |

#### 第一层：本地字符串与字节审计，无需 GPU

在本项目仓库根目录，使用 Python 3.11～3.13 运行独立教学示例，仅依赖标准库。字节审计会输出组合重音等 Unicode 字符，使用 `-X utf8` 避免 Windows 默认 GBK 输出无法编码这些字符：

```bash
python -X utf8 examples/ai-agent/ch6-8-review/copy_audit.py
python -m unittest discover -s examples/ai-agent/ch6-8-review -p "test_*.py" -v
```

脚本分别记录原始预测、目标、UTF-8 长度和 SHA-256，比较 `raw_exact` 与仅对预测执行 `.strip()` 后的 `normalized_exact`，并定位原始字节首个分歧。这里的 normalized 只指该项后处理，不隐含 Unicode 归一化。

| 输入差异（教学数据）          | 应怎样解释                                                      |
| ----------------------------- | --------------------------------------------------------------- |
| 预测 `" abc\n"`，目标 `"abc"` | raw 不匹配，strip 后匹配；指标变化来自后处理                    |
| 预测 `"abc"`，目标 `" abc "`  | 两种口径均不匹配；目标不做 strip                                |
| `é` 与 `e` 加组合重音         | 可能显示相同，UTF-8 字节不同；NFC 诊断不能擅自改变复制契约      |
| 中文经过 JSON 转义再解码      | JSON 文本字节可以变化；解码后的字符串应保持一致，要分别审计两层 |
| 内部 CRLF 与 LF               | strip 不会消除内部换行差异                                      |

NFC（Unicode Normalization Form C，规范组合形式）可将某些等价字符表示转换为统一形式，例如组合重音与预组合字符；它用于解释差异，不表示原始字节相等。把同一字符串在模型输出、JSON 解码、工具入口分别记录，找到 Hash 第一次改变的边界；日志本身也要避免泄漏真实敏感内容。这一步不加载模型，不能证明 Tokenizer 或模型复制能力。

#### 第二层：真实 Tokenizer 的 round-trip

在单独的上游实验工作副本中固定到 `dbc046eb896ac4e39aa19c7774c8bf49583b89a6`，使用兼容 Python 环境。下列命令从该副本根目录开始：

```bash
python -m pip install -e ".[torch]"
cd chapter8/exact-copy-sft
python generate_data.py
python -c "from pathlib import Path; Path('validation').mkdir(exist_ok=True)"
python tokenizer_audit.py
```

`generate_data.py` 是标准库脚本，固定生成 `data/train.jsonl`、`eval.jsonl`、`boundary.jsonl`，数量分别为 1024、256、256，种子分别为 719、1729、2718。不同种子不等于所有难度因素已经隔离：固定源码仍使用相同字符生成规则和长度公式；若要验证未见长度或包装的泛化，需要另建明确隔离的测试，并记录改动。

`tokenizer_audit.py` 没有 `--model` 参数，固定审计 Qwen3-8B、Qwen2.5-0.5B-Instruct、Mistral-7B-v0.1 三个 Tokenizer，读取 eval 与 boundary 的 `source` 字段，进行 encode/decode 往返比较。需要相应 Tokenizer 文件、依赖及模型仓库访问权限；这项审计不加载模型权重，也不要求 GPU。这里的 `.[torch]` 是上游提供的依赖组，包含 Transformers 与 PyTorch，会有较大安装开销，并非只安装 Tokenizer 的最小依赖。

检查 `validation/tokenizer_audit.json` 的 `probe_count`、各模型的 `roundtrip_rate` 与失败样本，并记录实际依赖和 Tokenizer 版本。它检查的是 source 字符串能否往返，不是模型回答是否正确，也不覆盖所有 Chat Template 和工具 JSON 路径。本文未执行这一层，不提供虚构的通过率。

#### 第三层：基座与 LoRA 对照

需要适配的 CUDA GPU、驱动与训练栈，以及足够的权重、激活和优化器显存。固定训练脚本采用 bf16，并在没有 CUDA 时退出；显存需求不能仅靠模型名称或 LoRA 参数比例确定。在独立实验副本根目录安装训练依赖，再使用第二层生成并审核过的数据：

```bash
python -m pip install -e ".[train]"
cd chapter8/exact-copy-sft
python evaluate.py --model Qwen/Qwen3-8B --label base --split eval
python evaluate.py --model Qwen/Qwen3-8B --label base --split boundary
python train_sft.py --model Qwen/Qwen3-8B
python evaluate.py --model Qwen/Qwen3-8B --adapter output/adapter --label adapted --split eval
python evaluate.py --model Qwen/Qwen3-8B --adapter output/adapter --label adapted --split boundary
```

命令参数与输入输出来自固定提交的 [生成脚本](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/generate_data.py)、[Tokenizer 审计](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/tokenizer_audit.py)、[训练脚本](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/train_sft.py)、[评估脚本](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/evaluate.py)及 [依赖声明](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/pyproject.toml)。这些依赖范围不是完整锁定环境；复现时还要保存实际解析版本、模型与 Tokenizer revision、数据 Hash、硬件和种子。

检查训练生成的 `output/adapter`、`validation/latest.json` 指向的训练回执，以及四份 `validation/eval_{label}_{split}.json`。在同一任务上对齐基座与适配器的结果，分别报告留出与边界集，不能根据训练损失下降就宣布工具调用更可靠。上游 `byte_exact` 仍是前述 strip 后口径，文件没有保存 strip 前预测；要报告 raw exact，需在独立实验副本中额外保存原始 decode 输出后再重新评估，不能从既有结果倒推出原始指标。

本层未在此运行，没有新增模型准确率或训练收益结论；上游历史回执也不能替代当前硬件与协议下的实测。真实工具集成还需在相同数据边界下核对参数与执行结果。

[![训练改进：条件对照与独立评估](/assets/notes/ai-agent/07-training.png)](/assets/notes/ai-agent/07-training.png)

图中将训练候选、受控对照与独立评估分开，体现训练信号与实际任务收益的验证关系。[放大查看 PNG](/assets/notes/ai-agent/07-training.png)。[原始 DOT 语义图源](/assets/notes/ai-agent/07-training.dot)供对照，不是本版配图的可编辑源文件。

配套本地脚本用于展示 Unicode、首尾空白和 JSON round-trip 的区别，帮助定位错误所在层次；GPU 训练和计费模型调用尚未执行。上游历史训练结果属于参考材料。

DPO 的偏好对也应关联证据状态：同一句“已完成”，有读回证据时可能正确，缺少证据时则可能错误。如果仅按措辞标注 chosen/rejected，模型可能只是更擅长说“我还没完成”，任务能力却没有改善。

### 源码与实验入口

- [chapter8/exact-copy-sft/README.md](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/chapter8/exact-copy-sft/README.md)
- [当前仓库正文](https://github.com/bojieli/ai-agent-book/blob/dbc046eb896ac4e39aa19c7774c8bf49583b89a6/book/chapter8.md)
- [实验优先级与复现记录](/articles/ai-agent-source-experiments.html)

## 本章要点 {#检查理解}

1. 更新频繁的事实适合通过 RAG 提供，固定规则由代码校验，可描述流程可先用 Prompt 或 Skill 表达。
2. LoRA 冻结基础权重、训练低秩增量以减少可训练参数；rank 需结合容量、成本和留出表现选择。
3. 结果奖励可能被投机利用，授权与不可违反的业务规则需要执行器强制约束。
4. RLHF 使用人类反馈学习奖励信号，RLVR 使用可验证结果构造奖励。
5. 格式问题应先检查提示示例、Schema 和工具参数边界，再依据可复现评估判断是否需要训练。

## 学习资料与代码出处

本篇为个人学习整理，参考李博杰《深入理解 AI Agent：设计原理与工程实践》及 [ai-agent-book](https://github.com/bojieli/ai-agent-book/tree/dbc046eb896ac4e39aa19c7774c8bf49583b89a6)。代码节选保留正文中的固定提交链接，引用代码沿用上游 [Apache-2.0 许可证](/licenses/ai-agent-book-APACHE-2.0.txt)，不适用本站 CC0 声明。
