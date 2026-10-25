---
id: ai-infra-capacity-troubleshooting
title: 第 24 章 排障与容量验收：从现象走到证据
description: 原笔记记录了 torch.cuda.is_available() 为 false、重启后恢复的现象。这个观察有价值，但不能据此确认根因，也不能写成“CUDA 12.4 和 12.1 冲突，重启即可解决”。
date: '2026-10-25'
updated: '2026-10-25'
category: gpu-infra
type: troubleshooting
tags:
  - ai-infra
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: ai-infra
series: ai-infrastructure
order: 24
---

# 第 24 章 排障与容量验收：从现象走到证据

原笔记记录了 `torch.cuda.is_available()` 为 false、重启后恢复的现象。这个观察有价值，但不能据此确认根因，也不能写成“CUDA 12.4 和 12.1 冲突，重启即可解决”。

## 1. 第一原则：先保存现场

应记录时间、驱动和框架版本、容器 digest、设备 UUID、环境变量、错误码及相关日志。重启、升级驱动或批量杀进程可能破坏现场；在生产系统中，必须先评估影响并确认维护授权，不能将这些操作作为诊断的第一步。

![GPU 问题分层定位](/assets/notes/ai-infra/gpu-troubleshoot.svg)

## 2. 按失败层次逐步缩小

| 现象                             | 优先证据                           | 不应立即推断             |
| -------------------------------- | ---------------------------------- | ------------------------ |
| 宿主无法发现 GPU                 | 驱动、设备枚举、系统日志           | Python 版本造成          |
| nvidia-smi 可用，CUDA 初始化失败 | 设备权限、库加载、最小 CUDA 错误   | 小版本数字不一致必然冲突 |
| 容器失败而宿主正常               | runtime、设备暴露、容器库与配置    | 必须重装宿主驱动         |
| 加载成功但请求 OOM               | 峰值与阶段、并发、上下文、KV/Graph | 权重文件太大是唯一原因   |
| 多卡挂起                         | 所有 rank 中最先失败的日志         | 最后等待者就是根因       |

## 3. 一个不修改环境的框架信息片段

下面只做信息查询，但导入框架和 CUDA 可用性探测仍可能初始化相关运行环境；这里没有执行。

```python
import os
import torch
print("torch", torch.__version__)
print("build cuda", torch.version.cuda)
print("visible", os.environ.get("CUDA_VISIBLE_DEVICES", "<unset>"))
print("available", torch.cuda.is_available())
```

`PYTORCH_NVML_BASED_CUDA_CHECK=1` 影响相应可用性检查路径，不是通用的 GPU 修复开关，也不证明后续 CUDA 初始化和 kernel 会成功。环境变量的时机与作用按框架版本检查。[PyTorch CUDA 环境变量](https://docs.pytorch.org/docs/2.14/cuda_environment_variables.html)

## 4. OOM 要先确认发生阶段

加载时 OOM，先看权重、并行布局和加载峰值；prefill OOM，检查输入长度、chunk 和激活；decode OOM，检查并发、KV 增长与内存池。还应区分 CUDA 分配失败与主机 OOM killer，后者需要系统内存证据。

释放缓存并不能解决所有问题。仍由张量或图引用的内存，不会因为“清缓存”就安全释放；盲目缩短上下文或降低精度，也可能影响用户功能和质量，需要明确其中的取舍。

## 5. 最终验收是一组约束

正确性和任务质量 → 代表性负载 → 稳态性能 → 最坏形状与峰值显存 → 并发公平性 → 排空、失败和重启恢复。每项都应注明测试条件、预期、结果和证据，不用“能聊天”代替容量验证。

本册提供的是机制说明、教学代码和测试设计，没有在本机 GPU、Kubernetes 或服务端执行验证。涉及特定硬件、MIG/MPS、Graph 覆盖或引擎优化的实际结果，仍需在准备好的受控环境中复现。

## 6. 历史故障卡：Error 205 与 MPS 只是线索

原截图时间为 2024-08-01，能辨认的环境包括 RTX 4080、驱动 550.78、`nvidia-smi` CUDA Version 12.4，Python 中打印的是 `torch.version.cuda = 12.1`，不是 PyTorch 包版本。截图同时出现 `nvidia-cuda-mps-server`、`E. Process` 计算模式，以及初始化报错 `Error 205: mapping of buffer object failed`。

这些现场证据应一并保留，不能只关注两个版本数字。原记录提到重启后恢复，但缺少重启前后的 MPS 状态、库解析和最小计算对照，因此结论仍是“恢复观察，根因未验证”。原始截图保留在私有原资料与快照中，正文不复制其中的账户和主机标识。

后续若复现，应在不破坏现场的前提下分别核对驱动、计算模式、MPS 控制端/客户端、权限和 CUDA 错误；只有明确是哪项条件改变并能复验，才将候选解释升级为根因。这里不安排杀进程、切换计算模式或重启。
