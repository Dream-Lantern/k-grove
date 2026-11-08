---
id: ai-infra-training-inference-finetuning
title: 第 18 章 训练、推理与微调：参数究竟何时更新
description: "训练通过数据和目标函数更新模型参数，推理使用已训练参数处理新输入，微调则在已有模型上继续适配任务。下面先观察一次参数更新的循环，再区分配置、显存与质量评价。"
date: '2026-10-25'
updated: '2026-10-28'
category: gpu-infra
type: explanation
tags:
  - ai-infra
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 18
---

# 第 18 章 训练、推理与微调：参数究竟何时更新

训练通过数据和目标函数更新模型参数，推理使用已训练参数处理新输入，微调则在已有模型上继续适配任务。下面先观察一次参数更新的循环，再区分配置、显存与质量评价。

## 1. 一个训练 step 的核心循环

读取 batch → 前向计算 → 计算损失 → 反向求梯度 → 优化器更新参数。训练通过数据和目标函数学习参数，不要求所有任务都使用人工标签；自监督学习可以由数据自身构造训练目标。

[![训练、验证、测试：数据职责与参数更新](/assets/notes/ai-infra/training-cycle.svg)](/assets/notes/ai-infra/training-cycle.svg)

训练集用于学习参数，验证集用于超参数和模型选择，测试集应作为独立的最终评估，避免反复查看测试结果来调参。数据切分还应防止重复样本、同一用户或时间穿越造成泄漏。[PyTorch 优化参数教程](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial.html)

### 在 CPU 上观察一次权重更新

Model Parameters（模型参数）是优化器可调整的张量。Forward（前向）用当前权重计算预测，Loss（损失）把预测误差变成标量。Backward（反向）通过自动微分计算 Gradient（梯度），即损失对参数的变化率。Optimizer（优化器）根据梯度和状态更新参数，Learning Rate（学习率）控制更新尺度。

以下使用 Python 3 和 PyTorch CPU 环境。令初始权重 `w=1`，输入 `x=2`，目标为 0。平方损失为 4，梯度为 8。SGD（Stochastic Gradient Descent，随机梯度下降）学习率为 0.1 时，`w ← 1 − 0.1 × 8 ≈ 0.2`。保存为 `train_step.py`，先用 `python -c "import torch; print(torch.__version__)"` 记录版本，再执行 `python train_step.py`。

```python
import torch
from torch import nn

model = nn.Linear(1, 1, bias=False, device="cpu")
with torch.no_grad():
    model.weight.fill_(1.0)

optimizer = torch.optim.SGD(model.parameters(), lr=0.1)
x = torch.tensor([[2.0]])
target = torch.tensor([[0.0]])

model.train()
before = model.weight.detach().clone()
optimizer.zero_grad(set_to_none=True)
prediction = model(x)
loss = nn.functional.mse_loss(prediction, target)
loss.backward()

assert torch.equal(model.weight.detach(), before)
torch.testing.assert_close(loss.detach(), torch.tensor(4.0))
torch.testing.assert_close(model.weight.grad, torch.tensor([[8.0]]))
optimizer.step()
torch.testing.assert_close(model.weight.detach(), torch.tensor([[0.2]]))

model.eval()
assert model(x).requires_grad
with torch.no_grad():
    assert not model(x).requires_grad
with torch.inference_mode():
    assert not model(x).requires_grad
print("PASS")
```

`zero_grad()` 清理之前积累的梯度，`backward()` 写入梯度，`step()` 才在这个循环中更新参数。预期断言全部通过并输出 `PASS`。[PyTorch 优化参数教程](https://docs.pytorch.org/tutorials/beginner/basics/optimization_tutorial.html)

## 2. 三类参数与三个计数

模型权重是学习得到的参数；学习率、batch size 等是训练配置；输入中的 token 是分词器产生的单位，不等于固定数量汉字或单词。

若没有额外并行维度，常用 `有效全局 batch = 每设备微批 × 数据并行副本数 × 梯度累积步数`。张量并行设备不能再次当作数据并行副本重复乘进去。一次 optimizer step 可能包含多个 micro-step。

算例中，`2000 × 2000 × 25000` 的结果为 `100,000,000,000` 个 token，即 1000 亿 token。这个估算还假定每个序列都达到 2000 token；有 padding、打包或变长输入时应统计有效 token。

### 梯度累积与 Token 口径

Micro-batch（微批）是一次前向和反向所处理的本地样本。DP（Data Parallelism，数据并行）由多个模型副本分别处理不同样本。Gradient Accumulation（梯度累积）在一次 Optimizer Step（优化器更新步）前积累多个 Micro-step 的梯度。等长、等权样本时，`Global Batch = Micro Batch × DP Replicas × Accumulation Steps`，例如 `2 × 4 × 8 = 64`。TP（Tensor Parallelism，张量并行）拆分同一副本的计算，不再乘一次设备数。

等大小微批以 mean loss 计算时，将各微批 loss 除以累积次数，再各自 backward。开始累积前清零，全部完成后只 step 一次。若有效样本或 Token 数不同，应累计损失和并除以更新窗口的有效总数，分布式实现还须考虑梯度归约的平均因子。直接平均各微批 mean loss 会让小微批权重偏高。尾窗不足固定累积次数时也要按实际分母处理。

`2000 × 2000 × 25000` 分别表示每次更新的全局序列数、每序列处理的 Token 数和优化器更新步数。Processed Tokens（处理 Token）要声明是否包含 Padding（填充）位置；Effective Tokens（有效 Token）可以按 loss mask 统计参与监督的目标；Unique Tokens 在此指去重后语料位置数，需声明去重单位。Epoch（轮次）指按数据加载规则遍历一次训练集合，重复轮次会增加处理量。假设两个序列分别为 1500 与 1000 Token，填充到 2000 后执行 4000 个位置，若只有填充被屏蔽，最多计 2500 个有效位置，实际目标还受移位和掩码规则影响。Packing（序列打包）可把短序列放进同一上下文以减少填充，仍需正确处理样本边界。

## 3. 推理的参数使用与运行内存 {#_3-推理不更新参数-但仍需要额外内存}

推理使用已训练的参数处理新输入，通常不计算训练梯度，但仍需要激活值、工作区、KV cache 等资源。框架中的 evaluation mode 与关闭梯度是两个不同设置：前者影响 dropout 等模块行为，后者控制梯度记录。具体代码应按所用框架的 API 配合设置。

| 设置                     | 影响                                                                             |
| ------------------------ | -------------------------------------------------------------------------------- |
| `model.train()`          | 启用 Dropout 等模块的训练行为，梯度模式独立                                      |
| `model.eval()`           | 切换评估行为，例如关闭 Dropout 和使用 BatchNorm 运行统计，Autograd 仍可记录      |
| `torch.no_grad()`        | 在作用域内关闭常规梯度记录，不切换模型的训练标志                                 |
| `torch.inference_mode()` | 进一步禁用视图跟踪、版本计数等开销，创建的推理张量参与后续自动微分计算有额外限制 |

推理通常用 `eval()` 配合无梯度模式。上面的 CPU 程序单独验证了 `eval()` 后仍可有梯度记录。[PyTorch inference_mode](https://docs.pytorch.org/docs/stable/generated/torch.autograd.grad_mode.inference_mode.html)

### 用 1B 参数估算显存

| 场景 | 组成与主要变量                                                                                                           |
| ---- | ------------------------------------------------------------------------------------------------------------------------ |
| 训练 | 权重、梯度、优化器状态、反向所需激活、临时工作区与通信缓冲区。激活随 Batch、Sequence Length、精度与重计算策略变化        |
| 推理 | 权重、临时激活、KV Cache、工作区、CUDA Graph 相关缓存及 Serving Runtime 预留。缓存取决于模型结构、并发、上下文和缓存精度 |

BF16（BFloat16）每参数 2 字节，1B 权重约 2 GB 十进制，即约 1907 MiB。若训练梯度也用 BF16，则另约 2 GB。若某实现保留两份 FP32 Adam 状态，则另约 8 GB；若保留 FP32 主权重还会增加约 4 GB。这些只是分项假设，状态、分片、精度和峰值以框架实测为准。

回到 [第 16 章](/articles/ai-infra-kubernetes-hami.html)的 3000 MiB 推理 Pod。假设该模型有 16 层、每层 8 个 KV heads、head 维度 64、BF16 Cache，每 Token 需要 `2 × 16 × 8 × 64 × 2 = 32768` 字节（K 和 V 各一份）。8 条序列各缓存 4096 Token 时约 1024 MiB，权重和缓存合计约 2931 MiB，只剩约 69 MiB 给激活、工作区、运行时及分配器开销。这个假设不足以保证加载或运行成功，更无法证明 50 的算力配置满足 SLO。先按实际模型和缓存配置重新预算，再验证峰值与服务性能。

## 4. 全参数微调与低秩适配 {#_4-微调、lora、qlora-分别改了什么}

Full Fine-tuning（全参数微调）通常更新已有模型的全部可训练权重。Partial Fine-tuning（部分参数微调）只更新选定的基础模型权重，例如末几层。LoRA 冻结基础权重，在相应线性层中训练低秩增量，可写成 `W' = W + ΔW`，其中 `ΔW = BA`；它减少可训练参数和相关优化器开销，不自动减少基础模型加载所需的全部显存。

QLoRA 通常将量化后的基础模型与低秩适配器训练结合。它不是“在 INT4 基础权重上像普通 FP32 一样直接更新所有参数”，基础模型、计算精度、适配器和优化器各有自己的表示。[PEFT LoRA 说明](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)

LoRA（Low-Rank Adaptation，低秩适配）属于 PEFT（Parameter-Efficient Fine-Tuning，参数高效微调）。Adapter（适配器）以少量新参数改变基础层的输出，Rank（秩）限制增量矩阵的表达维度。对输入维度 4096、输出维度 4096 的线性层，`W` 为 `4096 × 4096`。令 `A` 为 `8 × 4096`，`B` 为 `4096 × 8`，则 `BA` 与 `W` 同形。原层有 16,777,216 个权重，LoRA 有 `8 × (4096 + 4096) = 65536` 个可训练参数，约为 0.39%。该比例只计这一个层和这两个矩阵。基础权重、激活及其他层仍占显存，实际实现也可能给增量乘缩放系数。

QLoRA（Quantized Low-Rank Adaptation，量化低秩适配）将冻结的基础权重以低位宽存储，例如原论文的 4-bit NF4（4-bit NormalFloat）。Quantization（量化）用有限编码及尺度等元数据近似表示权重。计算时按算子把所需权重反量化到计算精度，例如 BF16。梯度经基础模型传到可训练 LoRA 参数，优化器状态仍需预算，激活和工作区也仍存在。[LoRA 原论文](https://arxiv.org/abs/2106.09685) · [QLoRA 原论文](https://arxiv.org/abs/2305.14314) · [PEFT LoRA](https://huggingface.co/docs/peft/main/en/conceptual_guides/lora)

## 5. 评价要匹配任务

分类中 `Precision = TP/(TP+FP)`、`Recall = TP/(TP+FN)`，F1 是二者调和平均；分母为零时需要明确定义处理方式。类别不平衡时只看 Accuracy 容易误导，多分类还要注明 macro/micro/weighted 口径。

生成模型还需要从任务质量、格式遵循、事实性、安全等方面评估，并结合人工评估，不能用一个分类 F1 衡量所有任务的质量。微调后应保存基础模型 revision、数据版本、训练配置与 adapter，并使用未参与训练的样本评估。

## 6. 训练、验证与测试图只标真正的数据职责

图中只有训练路径对应基于训练目标的参数更新；验证用于模型/超参数选择，独立测试用于最终评估。线上反馈若要回到训练，需经过授权、清洗、标注与重新切分，不能直接把预测箭头接回优化器。

任务指标和服务指标另列：分类的 precision/recall/F1 描述预测质量；TTFT、ITL、吞吐和错误率描述服务行为。它们应同时满足，但不能用高吞吐替代质量合格，也不拿分类准确率证明系统低延迟。

### 数据泄漏与联合评估

例如同一用户的重复工单落入训练和测试，模型可能记住措辞，测试得分高估陌生用户上的表现。先去重并按用户分组切分。对按时间预测的任务，Future Leakage（未来信息泄漏）可能来自使用预测时尚未产生的标签或对全量数据拟合统计量。按时间切分，并仅用训练期间可得数据拟合转换。验证集用于选择模型，测试集留作最终评估，避免反复根据测试集改配置。

| 评价维度       | 微调前后采用同一口径比较                                                                                                                   |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| 训练与分类质量 | Loss 是优化目标。Accuracy 统计正确率，Precision 衡量预测为正的结果中有多少为真，Recall 衡量真阳性被找到的比例，F1 综合二者                 |
| 生成质量       | 固定独立任务集、解码配置和评分标准，比较任务完成、事实性及格式遵循                                                                         |
| 服务性能       | 同并发与输入输出长度下记录 TTFT（首 Token 延迟）、ITL（Token 间隔）、Throughput（吞吐）和 Error Rate（错误率），与 SLO（服务等级目标）对照 |

表格是评估模板。训练完成、质量改善与服务达标分别验收。推理的预填充、解码和 KV Cache 详见[第 19 章](/articles/ai-infra-prefill-decode-kv-cache.html)。
