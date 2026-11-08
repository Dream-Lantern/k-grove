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

### 默认流语义取决于编译配置

Legacy Default Stream（传统默认流）与同一 Context 中的 blocking streams 有隐式同步，使用 `cudaStreamNonBlocking` 创建的流除外。Per-Thread Default Stream（每线程默认流）由宿主线程分别持有，行为类似普通流。如果显式与传统默认流混用，两者仍可能同步。CUDA 12.8.1 的 nvcc 可用 `--default-stream legacy` 或 `--default-stream per-thread` 选择，未指定时采用 legacy。跨编译单元或组件使用时应核对构建选项。下面的实验显式使用两条 non-blocking streams。[CUDA 12.8.1 默认流同步行为](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/stream-sync-behavior.html)

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

创建 Event 后，`cudaEventRecord(ready, producer)` 把生产流此前的工作关联到这次记录。随后调用 `cudaStreamWaitEvent(consumer, ready, 0)`，让消费流后续工作依赖这次记录。若在首次记录之前调用 wait，该 Event 还没有捕获工作，不能建立预期依赖。Event 作为依赖点可用 `cudaEventCreate()` 创建，也可用 `cudaEventCreateWithFlags(..., cudaEventDisableTiming)` 省去计时。此处生产者和消费者在同一设备执行环境中使用可共同访问的缓冲区。

| 主机等待 API               | 等待范围                         | 用途                                         |
| -------------------------- | -------------------------------- | -------------------------------------------- |
| `cudaDeviceSynchronize()`  | 当前设备执行环境中先前提交的工作 | 等待范围较宽，方便建立单程序正确性基线       |
| `cudaStreamSynchronize(s)` | 指定流的既有工作及其依赖         | 回读该流输出或清理相关资源                   |
| `cudaEventSynchronize(e)`  | 指定事件最近一次记录所捕获的工作 | 等待某个阶段完成，让同一流后续工作有机会继续 |

这些调用阻塞调用方直到满足等待条件，可能报告较早的异步错误。跨流依赖优先用流等待事件表达，主机只在需要结果或回收资源时等待。[CUDA 12.8.1 Event API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__EVENT.html)

## 3. 什么情况下搬运与计算可能重叠

通常需要硬件支持、相互独立的数据分块、合适的 stream 布局和主机内存条件。页锁定内存有利于异步主机搬运，但函数名带 `Async` 并不保证所有参数组合都对主机完全非阻塞；应检查具体拷贝类型和同步语义。[异步执行说明](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#asynchronous-concurrent-execution)

实验时，先画出三个分块的数据依赖，再检查时间线中是否出现预期的重叠。如果没有，应排查隐式同步、pageable memory、资源占满和输入依赖，而不是直接增加到几十个 stream。

拷贝引擎（Copy Engine）可在支持的路径上独立于计算流水线搬运数据。可查询 `asyncEngineCount` 了解设备能力，并用页锁定缓冲区安排 H2D、Kernel 和 D2H。要观察重叠，可把不同分块放入可独立推进的流，分别管理缓冲区的生命周期，再用时间线确认。单个分块的计算仍需等输入可用，主机也要等 D2H 完成再读取输出。DMA 未结束时，提前覆盖输入或释放任一缓冲区都会破坏正确性。[CUDA 12.8.1 异步拷贝语义](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/api-sync-behavior.html)

## 4. 计时需要明确测量对象

CPU 在提交前后读时钟，通常测到的是提交开销，而不是 GPU 执行时长。CUDA event 可以测量受其顺序约束的 GPU 时间区间；跨 stream、跨设备或存在并发时，要认真设计依赖，不能把任意两个 event 相减当作某个 kernel 的独占成本。

最终至少应同时记录端到端时间和 GPU 时间线。服务响应慢的原因可能在队列、CPU 分词或网络阶段，但也不能仅凭一个 kernel 耗时很短，就排除 GPU 性能问题。

## 5. 实践：两条流传递一个整数

生产流先拷入整数 7，再加 1。消费流等待 Event，将中间值乘 2 后拷回主机，预期得到 16。此例验证依赖顺序。相互依赖的两次计算应当先后执行。

```cpp
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>

#define CHECK(expr) do {                                         \
  const cudaError_t status = (expr);                             \
  if (status != cudaSuccess) {                                  \
    std::fprintf(stderr, "%s: %s\n", #expr,                     \
                 cudaGetErrorString(status));                  \
    std::exit(1);                                               \
  }                                                            \
} while (0)

__global__ void produce(int* value) { *value += 1; }
__global__ void consume(int* value) { *value *= 2; }

int main() {
  int* input = nullptr;
  int* output = nullptr;
  int* device = nullptr;
  cudaStream_t producer, consumer;
  cudaEvent_t ready;

  CHECK(cudaMallocHost(reinterpret_cast<void**>(&input), sizeof(int)));
  CHECK(cudaMallocHost(reinterpret_cast<void**>(&output), sizeof(int)));
  CHECK(cudaMalloc(&device, sizeof(int)));
  CHECK(cudaStreamCreateWithFlags(&producer, cudaStreamNonBlocking));
  CHECK(cudaStreamCreateWithFlags(&consumer, cudaStreamNonBlocking));
  CHECK(cudaEventCreateWithFlags(&ready, cudaEventDisableTiming));

  *input = 7;
  CHECK(cudaMemcpyAsync(device, input, sizeof(int),
                        cudaMemcpyHostToDevice, producer));
  produce<<<1, 1, 0, producer>>>(device);
  CHECK(cudaGetLastError());
  CHECK(cudaEventRecord(ready, producer));
  CHECK(cudaStreamWaitEvent(consumer, ready, 0));
  consume<<<1, 1, 0, consumer>>>(device);
  CHECK(cudaGetLastError());
  CHECK(cudaMemcpyAsync(output, device, sizeof(int),
                        cudaMemcpyDeviceToHost, consumer));

  CHECK(cudaStreamSynchronize(consumer));
  const bool ok = *output == 16;
  CHECK(cudaEventDestroy(ready));
  CHECK(cudaStreamDestroy(consumer));
  CHECK(cudaStreamDestroy(producer));
  CHECK(cudaFree(device));
  CHECK(cudaFreeHost(output));
  CHECK(cudaFreeHost(input));

  std::puts(ok ? "PASS" : "FAIL");
  return ok ? 0 : 2;
}
```

消费流同步成功意味着回拷及其所依赖的生产流工作已经完成。本例在记录事件后没有再向生产流提交工作，因此正常路径可以释放全部缓冲区。错误路径的 `CHECK` 结束这个教学进程。服务程序还需要记录错误，并按已创建的对象和在途工作安排清理。

将代码保存为 `stream_event.cu`。在 Linux、兼容 NVIDIA 驱动和 CUDA Toolkit 12.8.1 环境中运行：

```bash
nvcc stream_event.cu -o stream_event
./stream_event
compute-sanitizer --tool memcheck --error-exitcode 1 ./stream_event
```

预期输出 `PASS`。去掉 wait 会让消费操作与生产操作争用同一设备地址，即使偶然读到 16，也不能据此认定正确。若省略最后一次同步，主机可能在回拷完成前读取输出。该示例已静态核查，GPU 执行与 memcheck 待验证。

## 6. 从异步依赖进入 CUDA Graphs

Stream 和 Event 确定哪些操作必须排序、哪些可以独立调度。把这些关系明确后，可以在[第 7 章](/articles/ai-infra-cuda-graphs.html)学习如何捕获或显式构造图，实例化为 GraphExec 并重复提交。每次执行所引用的对象仍需保持有效。
