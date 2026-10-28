---
id: ai-infra-cuda-graphs
title: 第 7 章 CUDA Graphs：定义、实例化、更新与回放
description: "大量短 kernel 每次由 CPU 单独提交时，主机开销可能占比较高。CUDA Graphs 把工作定义与执行分开，允许重用已实例化的执行图。"
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
order: 7
---

# 第 7 章 CUDA Graphs：定义、实例化、更新与回放

## 1. 通过定义与执行分离复用提交工作 {#_1-它主要减少什么开销}

大量短 kernel 每次由 CPU 单独提交时，主机开销可能占比较高。CUDA Graphs 把工作定义与执行分开，允许重用已实例化的执行图。它不等于 kernel 融合：图内仍可以保留多个 kernel，也不能保证单个长 kernel 本身因此变快。

[![CUDA Graphs：构建、回放与更新](/assets/notes/ai-infra/graph-lifecycle.svg)](/assets/notes/ai-infra/graph-lifecycle.svg)

图定义可通过显式添加节点及依赖建立，也可以在支持的操作范围内进行 stream capture。capture 记录工作及依赖，不是一次正常的“先计算出结果再缓存答案”。不能在捕获期间读取尚未执行的输出。

## 2. Graph 与 GraphExec 的区别

`cudaGraph_t` 是工作图描述，`cudaGraphExec_t` 是实例化后的可执行对象。修改原图不会自动同步到已创建的执行实例，但“每次参数变化都必须重新实例化”也不对：符合条件时可以更新节点参数或使用 `cudaGraphExecUpdate()`。

CUDA 12.8.1 还提供事件节点和条件节点等能力。选择节点与更新方法时，按对应 API 确认可更新范围、参数要求和捕获限制。[Graph Management API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__GRAPH.html)

## 3. 一个可核对的使用框架

以下为伪代码，只表示生命周期，省略错误处理和具体 kernel：

```text
准备长期有效的输入输出缓冲区
开始捕获 stream
提交被支持的拷贝或 kernel 工作
结束捕获，得到 Graph
实例化为 GraphExec
循环：更新输入 → 启动 GraphExec → 按需求等待结果
退出前等待未完成工作 → 销毁 GraphExec、Graph 及相关资源
```

图仍可能访问缓冲区时，不能将其释放。图复用的成本不只有实例化时间，还涉及固定形状、内存池、捕获数量和维护复杂度。应比较“构建 + 多次回放”的总成本，而不是只看最短的一次 launch。

## 4. Graph 回放与普通 launch 的观测覆盖 {#_4-为什么只-hook-culaunchkernel-会漏数据}

执行图回放时，不保证经过应用拦截的普通 kernel launch 入口。因此，“hook 没命中”不能说明 kernel 没执行；也不能通过让图相关函数直接返回成功来绕过调用，这可能破坏输出句柄、依赖和应用正确性。

图节点遍历可以帮助读取定义态的 kernel 参数，但真实运行时间需要 profiler/activity 证据。节点数也取决于模型、形状、后端及版本。

## 5. 回归时联合验证输出、资源与速度 {#_5-回归验证不只检查速度}

回归时，至少要核对无图/有图的输出、不同输入、边界形状、错误返回、内存增长和并发场景。更新不兼容时，应采用重新构建等明确的回退路径。Graph、event 和 stream 都需要管理生命周期。

## 6. 分别计量调用、排队、搬运与计算时间 {#_6-四种时间不要都叫-h2d-延迟}

| 时间对象             | 观察的区间         | 主要边界                         |
| -------------------- | ------------------ | -------------------------------- |
| CPU API 调用时间     | host 进入到返回    | 可能主要是 enqueue，也可能含阻塞 |
| 提交到设备开始的等待 | 提交与实际开始之间 | 受队列、依赖和调度影响           |
| 显式 H2D copy 时间   | 数据搬运活动       | 与 kernel launch 不是同一活动    |
| kernel 执行时间      | 设备活动 start/end | 受并发和 profiler 扰动影响       |

Graph 复用不意味着输入数据无需传输；只有实现确实复用或避免了某次搬运，才能从账本中去掉它。图里有多少节点也不等于回放了多少工作：子图需要相应遍历，条件节点和回放次数还会改变实际活动数量。判断覆盖与耗时应以真实 activity 为证据，而不是由静态节点数乘一个经验值。
