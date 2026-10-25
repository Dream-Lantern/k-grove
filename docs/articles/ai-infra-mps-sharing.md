---
id: ai-infra-mps-sharing
title: 第 15 章 MPS 与其他共享方式：并发不等于硬隔离
description: 多个小 CUDA 进程各自无法充分利用整卡时，MPS（Multi-Process Service）可能提高资源复用率。它与 MIG 的目标不同，不能简单判断“哪个一定更快”。
date: '2026-10-25'
updated: '2026-10-25'
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

原笔记“把所有进程 context 融成一个”描述过于笼统。传统 pre-Volta 路径和 Volta 起的执行及地址空间机制不同。MPS 有控制守护进程、server 与 client 运行时等角色，具体提交路径和隔离能力需按架构与实现理解。[MPS Architecture](https://docs.nvidia.com/deploy/mps/latest/architecture.html)

![GPU 共享方案的选择维度](/assets/notes/ai-infra/sharing-choices.svg)

图中分支只是选择起点，不是固定推荐。例如已划分的 MIG 实例中也可以在支持条件下使用 MPS；“组合能力”不等于约束全部消失。

## 2. 百分比参数不表示预留同等算力

legacy MPS 的 active thread percentage 限制可使用的执行资源，并非把每个应用的吞吐、延迟都精确锁定为某个百分比。硬件粒度可能导致取整，不能把某块 A40 的观测公式泛化到所有卡。显存限制、线程资源限制和带宽隔离也是不同机制。[Legacy MPS v2 接口](https://docs.nvidia.com/deploy/mps/latest/mpsv2-interface.html)

| 方式       | 主要作用                       | 不应自动承诺                           |
| ---------- | ------------------------------ | -------------------------------------- |
| 多 stream  | 表达同一应用工作顺序和并发机会 | 跨租户隔离                             |
| 时间片共享 | 多任务复用设备                 | 显存或吞吐的硬分区                     |
| MPS        | 协作多进程资源复用             | 全部故障互不影响、固定吞吐份额         |
| MIG        | 受支持硬件的资源实例化         | 整卡级故障完全隔离                     |
| vGPU       | 虚拟机等场景的设备虚拟化体系   | 一律只采用时间片；也有 MIG-backed 路径 |

## 3. 故障和退出行为不能靠框架名担保

原文某次实验发现 PyTorch/TensorFlow 进程被终止后其他进程没受影响，不能据此推断框架自动完成全部 MPS 安全退出。强制终止、未完成 GPU 工作、fatal fault 以及共享设备集合都可能改变影响范围。

停止服务时，应先排空并同步未完成的工作，再按相应版本的管理流程退出。不要从信号处理器直接调用复杂的 CUDA API，这并不能保证异步信号安全。还应保存 server 日志、客户端映射和故障前的时间线。

## 4. 新能力要单独标注

2026-10-22 核对的官方主线文档已区分 legacy v2 和可选 MPS v3，并列出 namespace、配置和 memory partitioning 等主题。不能继续写“MPS 在所有版本都没有这些能力”，也不能把 v3 接口加入旧 CUDA 环境直接使用。是否可用须核对驱动、GPU、接口版本和迁移说明。[MPS 官方入口](https://docs.nvidia.com/deploy/mps/latest/index.html)

本册保留 legacy 的概念复盘，不提供未经本机验证的启停配置。验证共享收益时，至少对比独占基线、任务组合、尾延迟和故障影响，不能只看总利用率上升。

## 5. SIGKILL 不能被框架捕获后优雅清理

Linux 的 SIGKILL 不能被捕获、阻塞或忽略。因此“kill -9 后别的任务没受影响”不能归因为框架在信号处理器里完成了清理。原实验缺少在途工作、server 状态和日志，应保留为现象，不推断原因。[Linux signal(7)](https://man7.org/linux/man-pages/man7/signal.7.html)

| 事件                    | 必须区分的条件                    | 不应给出的通用保证       |
| ----------------------- | --------------------------------- | ------------------------ |
| 正常退出                | 是否已排空在途 GPU 工作           | 任意退出顺序都安全       |
| 未同步强制中断          | server 和关联客户端状态           | 只会影响当前 Python 进程 |
| Fatal GPU fault         | 架构、受影响 GPU 及客户端集合     | 全卡必全挂或完全无传播   |
| 受控 client termination | 接口版本、PID namespace、成功返回 | 返回前即可随意杀进程     |

管理终止顺序以目标版本为准。当前 Release 615 文档区分 legacy 的 `terminate_client <server PID> <client PID>` 与 v3 的 `client terminate <client PID>`：确认映射 → 发起管理终止 → 等待成功 → 必要时结束 OS 进程。这里仅列不可直接执行的占位语法，不提供 kill 脚本；管理 PID 必须使用控制端所在 namespace 的对应值。[MPS Client Termination，Release 615](https://docs.nvidia.com/deploy/pdf/CUDA_Multi_Process_Service_Overview.pdf)

代际差异也要写具体：pre-Volta 路径不能视为每个客户端都有独立 GPU 地址空间；Volta MPS 的客户端各有自己的 GPU 地址空间，并可直接提交设备工作，server 仍协调相关共享资源。Volta 的有限故障包含也不是“只影响出错进程”：致命 GPU 错误可能影响与故障设备有关的客户端集合，须按所用设备关系检查。

## 6. 动态百分比与静态分区分别验收

legacy active-thread 百分比不是专属 SM 编号集合的证据；当前文档还列出了有条件的静态分区模式，也不能因此说所有 static 能力都只属于 v3。接口代际与资源模式是两个维度，应各自核对。[Legacy MPS v2 interface](https://docs.nvidia.com/deploy/mps/latest/mpsv2-interface.html)

优化时，不应预设“少 block、多线程一定适合 MPS”。调整 block/grid 前后，都要校验是否完整覆盖数据，再比较独占和共运行时的吞吐、尾延迟与相互干扰，不能只看某个属性 API 返回的 SM 数。
