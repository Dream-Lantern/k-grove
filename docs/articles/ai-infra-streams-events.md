---
id: ai-infra-streams-events
title: 第 6 章 Stream 与 Event：顺序、依赖和真正的重叠
description: 异步不等于并行。CPU 提交函数较快返回，只能说明主机没有等待 GPU 完成全部工作；不同任务能否同时执行，还取决于依赖、硬件与资源。
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
order: 6
---

# 第 6 章 Stream 与 Event：顺序、依赖和真正的重叠

异步不等于并行。CPU 提交函数较快返回，只能说明主机没有等待 GPU 完成全部工作；不同任务能否同时执行，还取决于依赖、硬件与资源。

## 1. 先建立顺序保证

普通使用中，同一 stream 的工作按照提交顺序推进。先拷入输入再计算，再拷回输出，能够表达依赖关系。不能把这三个依赖同一数据的阶段写成“放到一个 stream 里就会自动重叠”。

不同 stream 的独立工作可能并发，但没有“创建两个 stream 就保证加速”的契约。legacy default stream 还可能与其他 blocking stream 产生隐式同步；per-thread default stream 及 non-blocking stream 有不同语义。[Stream API，12.8.1](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__STREAM.html)

![显式事件连接两个 stream](/assets/notes/ai-infra/stream-dependencies.svg)

图中 B 的消费阶段必须等待 A 的生产事件。没有这条依赖边，即使某次碰巧运行正确，也可能存在数据竞争。

## 2. 用事件表达跨 stream 的依赖

下面是教学片段，不是完整可编译程序；假定 stream 和 event 已创建、对象生命周期覆盖所有异步工作，所有调用均须检查错误。

```cpp
// s_producer 上的工作必须先完成，消费者才能读它的输出。
produce<<<grid, block, 0, s_producer>>>(buffer);
cudaEventRecord(ready, s_producer);
cudaStreamWaitEvent(s_consumer, ready, 0);
consume<<<grid, block, 0, s_consumer>>>(buffer);
```

`cudaStreamWaitEvent` 为设备工作建立顺序，不等于要求 CPU 阻塞等待。CPU 要读取结果时，再在相应 stream/event 上等待完成。避免在每个操作后调用 `cudaDeviceSynchronize()`，否则很容易把原本可流水化的工作全部串行化。

## 3. 什么情况下搬运与计算可能重叠

通常需要硬件支持、相互独立的数据分块、合适的 stream 布局和主机内存条件。页锁定内存有利于异步主机搬运，但函数名带 `Async` 并不保证所有参数组合都对主机完全非阻塞；应检查具体拷贝类型和同步语义。[异步执行说明](https://docs.nvidia.com/cuda/cuda-programming-guide/02-basics/asynchronous-execution.html)

实验时，先画出三个分块的数据依赖，再检查时间线中是否出现预期的重叠。如果没有，应排查隐式同步、pageable memory、资源占满和输入依赖，而不是直接增加到几十个 stream。

## 4. 计时需要明确测量对象

CPU 在提交前后读时钟，通常测到的是提交开销，而不是 GPU 执行时长。CUDA event 可以测量受其顺序约束的 GPU 时间区间；跨 stream、跨设备或存在并发时，要认真设计依赖，不能把任意两个 event 相减当作某个 kernel 的独占成本。

最终至少应同时记录端到端时间和 GPU 时间线。服务响应慢的原因可能在队列、CPU 分词或网络阶段，但也不能仅凭一个 kernel 耗时很短，就排除 GPU 性能问题。
