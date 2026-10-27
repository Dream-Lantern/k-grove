---
id: ai-infra-mps-sharing
title: 第 15 章 MPS 与其他共享方式：并发不等于硬隔离
description: 多个小 CUDA 进程各自无法充分利用整卡时，MPS（Multi-Process Service）可能提高资源复用率。它与 MIG 的目标不同，不能简单判断“哪个一定更快”。
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
order: 15
---

# 第 15 章 MPS 与其他共享方式：并发不等于硬隔离

多个小 CUDA 进程各自无法充分利用整卡时，MPS（Multi-Process Service）可能提高资源复用率。它与 MIG 的目标不同，不能简单判断“哪个一定更快”。

## 1. 先分清历史实现

传统 pre-Volta 路径和 Volta 起的执行及地址空间机制不同。MPS 有控制守护进程、server 与 client 运行时等角色，具体提交路径和隔离能力需按架构与实现理解。[MPS Architecture](https://docs.nvidia.com/deploy/mps/latest/architecture.html)

[![GPU 共享：需求与机制](/assets/notes/ai-infra/sharing-choices.svg)](/assets/notes/ai-infra/sharing-choices.svg)

图中分支只是选择起点，不是固定推荐。例如已划分的 MIG 实例中也可以在支持条件下使用 MPS。

## 2. 百分比参数不表示预留同等算力

legacy MPS 的 active thread percentage 限制可使用的执行资源，并非把每个应用的吞吐、延迟都精确锁定为某个百分比。硬件粒度可能导致取整。显存限制、线程资源限制和带宽隔离也是不同机制。[Legacy MPS v2 接口](https://docs.nvidia.com/deploy/mps/latest/mpsv2-interface.html)

| 方式       | 主要作用                       | 不应自动承诺                           |
| ---------- | ------------------------------ | -------------------------------------- |
| 多 stream  | 表达同一应用工作顺序和并发机会 | 跨租户隔离                             |
| 时间片共享 | 多任务复用设备                 | 显存或吞吐的硬分区                     |
| MPS        | 协作多进程资源复用             | 全部故障互不影响、固定吞吐份额         |
| MIG        | 受支持硬件的资源实例化         | 整卡级故障完全隔离                     |
| vGPU       | 虚拟机等场景的设备虚拟化体系   | 一律只采用时间片；也有 MIG-backed 路径 |

## 3. 故障和退出行为不能靠框架名担保

停止服务时，应先排空并同步未完成的工作，再按相应版本的管理流程退出。不要从信号处理器直接调用复杂的 CUDA API，这并不能保证异步信号安全。还应保存 server 日志、客户端映射和故障前的时间线。

## 4. SIGKILL 不能被框架捕获后优雅清理

Linux 的 SIGKILL 不能被捕获、阻塞或忽略。因此“kill -9 后别的任务没受影响”不能归因为框架在信号处理器里完成了清理。原实验缺少在途工作、server 状态和日志，应保留为现象，不推断原因。[Linux signal(7)](https://man7.org/linux/man-pages/man7/signal.7.html)

| 事件                    | 必须区分的条件                    | 不应给出的通用保证       |
| ----------------------- | --------------------------------- | ------------------------ |
| 正常退出                | 是否已排空在途 GPU 工作           | 任意退出顺序都安全       |
| 未同步强制中断          | server 和关联客户端状态           | 只会影响当前 Python 进程 |
| Fatal GPU fault         | 架构、受影响 GPU 及客户端集合     | 全卡必全挂或完全无传播   |
| 受控 client termination | 接口版本、PID namespace、成功返回 | 返回前即可随意杀进程     |

管理终止顺序以目标版本为准。当前 Release 615 文档区分 legacy 的 `terminate_client <server PID> <client PID>` 与 v3 的 `client terminate <client PID>`：确认映射 → 发起管理终止 → 等待成功 → 必要时结束 OS 进程。这里仅列不可直接执行的占位语法，不提供 kill 脚本；管理 PID 必须使用控制端所在 namespace 的对应值。[MPS Client Termination，Release 615](https://docs.nvidia.com/deploy/pdf/CUDA_Multi_Process_Service_Overview.pdf)
