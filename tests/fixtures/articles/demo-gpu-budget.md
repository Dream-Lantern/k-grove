---
id: demo-gpu-budget
title: "GPU 资源实验：先写观察清单"
description: "围绕显存配额和执行上下文记录待验证问题。"
date: "2026-10-15"
updated: "2026-10-18"
category: gpu-infra
type: reference
tags: [GPU, 显存配额, GPU Context]
draft: true
source:
  kind: demo
---

# GPU 资源实验：先写观察清单

## 观察对象

为后续 GPU 虚拟化研究准备清单：设备型号、驱动版本、显存配额、任务生命周期，以及观察工具。

## 暂未验证

GPU Context、GreenCTX 与 Checkpoint / Restore 只作为未来研究关键词。本页不描述任何内部实现，也不声称完成资源隔离实验。
