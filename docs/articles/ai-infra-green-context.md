---
id: ai-infra-green-context
title: 第 5 章 Context、Module 与 Green Context 的边界
description: "理解 CUDA Context 与 Green Context 的资源归属、SM 资源划分和生命周期，区分资源配置与实际性能验证。"
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
order: 5
---

# 第 5 章 Context、Module 与 Green Context 的边界

Context 可以理解为 CUDA 资源和状态的管理环境。一个进程可以使用多张设备，也可以管理多个 context；因此需要明确对象归属和生命周期。

## 1. Runtime API 与 Driver API

Runtime API 常见前缀为 `cuda`，负责较多隐式管理；Driver API 常见前缀为 `cu`，提供更明确的 context 和 module 操作。Runtime 通常使用设备的 primary context。混用两套 API 时，应先明确当前线程使用哪个 context，不要每个组件都自行创建、销毁一套互不知情的环境。[Driver 与 Runtime 的差异](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/driver-vs-runtime-api.html)

[![Context：所有权与当前线程](/assets/notes/ai-infra/context-ownership.png)](/assets/notes/ai-infra/context-ownership.png)

`cuCtxSetCurrent()` 设置的是调用它的宿主线程的当前 context，不是一个“整个 GPU 当前只能选中谁”的全局开关。context 所属、宿主线程当前状态、硬件此刻执行哪个任务，是三个不同问题。[Context API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__CTX.html)

## 2. Module、Function、Stream 与分配的对象关系 {#_2-module、function、stream-不是同一种对象}

| 对象       | 表示什么             | 需要记录的归属               |
| ---------- | -------------------- | ---------------------------- |
| Context    | CUDA 执行和资源环境  | 设备及生命周期管理者         |
| Module     | 已加载的设备代码     | 加载时的相关 context         |
| Function   | 可启动的设备函数句柄 | 所属代码及有效生命周期       |
| Stream     | 有顺序约束的工作队列 | 创建环境和使用约束           |
| Allocation | 已分配的内存         | 分配方式、可访问方和释放时机 |

PTX 是中间表示，cubin 是面向相应 GPU 架构的设备二进制。fat binary 可以携带多个目标版本。不能由“文件里有 PTX”推断任何驱动都能 JIT 它；兼容性仍受驱动和 PTX 版本约束。

跨进程通信也不是只能复制回 CPU。CUDA IPC、外部内存、设备间访问等提供特定能力，但需要满足设备、句柄、安全和生命周期条件。初学示例默认各进程管理自己的分配，不依赖隐式共享。

## 3. Green Context 的 SM 资源划分流程 {#_3-green-context-不是更轻但仍随便抢全卡}

以 CUDA 12.8.1 文档为准，Green Context 可以把所支持的 SM 资源集合划分并提供给特定执行环境。逻辑步骤是查询资源 → 划分 SM 资源 → 生成描述符 → 创建 green context，再按 API 契约创建或使用相关 stream。

Green Context 与 MIG 提供不同层次的资源能力。解释其保证时，应分别核对 SM 划分粒度、最小数量、并发进展条件与其他 context 的关系；显存控制器、带宽和故障域的隔离还需按目标架构与 API 限制单独判断。[Green Contexts，CUDA 12.8.1](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__GREEN__CONTEXTS.html)

## 4. 工程上先写清所有权

插件式程序尤其需要明确：谁初始化设备、谁持有 primary context、谁创建 stream，以及谁负责最终同步和销毁。不要让一个插件调用 reset，销毁其他插件仍在使用的环境。排查 invalid context 或失效句柄时，沿“创建线程—当前 context—传递对象—销毁时机”追踪。
