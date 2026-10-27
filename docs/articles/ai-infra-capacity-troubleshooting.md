---
id: ai-infra-capacity-troubleshooting
title: 第 24 章 排障与容量验收：从现象走到证据
description: 笔记记录了 torch.cuda.is_available() 为 false、重启后恢复的现象。
date: '2026-10-25'
updated: '2026-10-28'
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

笔记记录了 `torch.cuda.is_available()` 为 false、重启后恢复的现象。

## 1. 第一原则：先保存现场

记录时间、驱动和框架版本、容器 digest、设备 UUID、环境变量、错误码及相关日志。重启、升级驱动或批量杀进程可能破坏现场；在生产系统中，必须先评估影响并确认维护授权，不能将这些操作作为诊断的第一步。

[![GPU 排障：逐层通过、逐层定位](/assets/notes/ai-infra/gpu-troubleshoot.svg)](/assets/notes/ai-infra/gpu-troubleshoot.svg)

## 2. 按失败层次逐步缩小

| 现象                             | 优先证据                           | 不应立即推断             |
| -------------------------------- | ---------------------------------- | ------------------------ |
| 宿主无法发现 GPU                 | 驱动、设备枚举、系统日志           | Python 版本造成          |
| nvidia-smi 可用，CUDA 初始化失败 | 设备权限、库加载、最小 CUDA 错误   | 小版本数字不一致必然冲突 |
| 容器失败而宿主正常               | runtime、设备暴露、容器库与配置    | 必须重装宿主驱动         |
| 加载成功但请求 OOM               | 峰值与阶段、并发、上下文、KV/Graph | 权重文件太大是唯一原因   |
| 多卡挂起                         | 所有 rank 中最先失败的日志         | 最后等待者就是根因       |

## 3. 一个不修改环境的框架信息片段

下面只做信息查询。

```python
import os
import torch
print("torch", torch.__version__)
print("build cuda", torch.version.cuda)
print("visible", os.environ.get("CUDA_VISIBLE_DEVICES", "<unset>"))
print("available", torch.cuda.is_available())
```

`PYTORCH_NVML_BASED_CUDA_CHECK=1` [PyTorch CUDA 环境变量](https://docs.pytorch.org/docs/2.14/cuda_environment_variables.html)

## 4. OOM 要先确认发生阶段

加载时 OOM，先看权重、并行布局和加载峰值；prefill OOM，检查输入长度、chunk 和激活；decode OOM，检查并发、KV 增长与内存池。还应区分 CUDA 分配失败与主机 OOM killer。

释放缓存并不能解决所有问题。仍由张量或图引用的内存，不会因为“清缓存”就安全释放；盲目缩短上下文或降低精度，也可能影响用户功能和质量。

## 5. 最终验收是一组约束

正确性和任务质量 → 代表性负载 → 稳态性能 → 最坏形状与峰值显存 → 并发公平性 → 排空、失败和重启恢复。每项都应注明测试条件、预期、结果和证据，不用“能聊天”代替容量验证。
