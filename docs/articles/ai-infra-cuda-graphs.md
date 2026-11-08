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

以三个依赖任务为例，A 将输入加 1，B 将中间值乘 2，C 再减 3。普通路径由 CPU 向同一 Stream 分别提交 A、B、C。图路径用 DAG（Directed Acyclic Graph，有向无环图）表示 A → B → C，可显式添加节点和边，也可通过 [第 6 章的流顺序与事件](/articles/ai-infra-streams-events.html)捕获依赖。

| 阶段     | 普通提交             | 图提交                                   |
| -------- | -------------------- | ---------------------------------------- |
| 首次准备 | 准备输入和缓冲区     | 同样准备数据，再定义 Graph 并实例化      |
| 每轮 CPU | 分别提交 A、B、C     | 调用一次 `cudaGraphLaunch(exec, stream)` |
| 每轮 GPU | 按流顺序运行 A、B、C | 按图依赖重新执行三个 kernel              |
| 消费结果 | 等相应工作完成       | 等相应图执行完成                         |

实例化检查定义、准备可复用的执行状态，存在一次性时间和资源开销。回放使用当前可访问的输入和已配置参数，三个 kernel 仍各自执行。若 B 后有两个独立分支，依赖解除后可被调度，能否重叠还取决于 SM、带宽等资源。

## 2. Graph 与 GraphExec 的区别

`cudaGraph_t` 是工作图描述，`cudaGraphExec_t` 是实例化后的可执行对象。修改原图不会自动同步到已创建的执行实例，但“每次参数变化都必须重新实例化”也不对：符合条件时可以更新节点参数或使用 `cudaGraphExecUpdate()`。

CUDA 12.8.1 还提供事件节点和条件节点等能力。选择节点与更新方法时，按对应 API 确认可更新范围、参数要求和捕获限制。[Graph Management API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__GRAPH.html)

| 更新接口                             | 修改对象                                | 适用场景                                       |
| ------------------------------------ | --------------------------------------- | ---------------------------------------------- |
| `cudaGraphKernelNodeSetParams()`     | 原始 Graph 的 kernel 节点               | 修改定义，供后续实例化或整体更新使用           |
| `cudaGraphExecKernelNodeSetParams()` | 已实例化 GraphExec 中对应的 kernel 节点 | 少数节点参数变动，使用实例化来源图中的节点句柄 |
| `cudaGraphExecUpdate()`              | 用新 Graph 尝试更新既有 GraphExec       | 多处变化且图拓扑、节点匹配及参数满足约束       |

例如 B 使用同一 kernel、Context 和有效的缓冲区，只把乘数从 2 改成 3，可尝试对 B 执行实例节点更新，检查返回后再提交。参数改成指针时还要验证可访问性、分配寿命与 API 约束。若新增第四个节点并改变依赖，整体更新的拓扑契约不再满足，应检查返回及 `cudaGraphExecUpdateResultInfo`，实例化新图并在旧工作完成后清理旧资源。更新只影响后续 launch。多个宿主线程共享图对象时应串行化访问；同一个 GraphExec 的重复执行彼此有序，即使提交到不同流也不会并行运行同一个实例。需要并行尝试时使用不同实例和互不冲突的数据。

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

### 捕获的三种路径

- **单流**。用显式流调用 `cudaStreamBeginCapture()`，提交支持捕获的 kernel 或拷贝，再在发起流上调用 `cudaStreamEndCapture()` 取得 Graph。捕获期间记录节点与依赖，设备执行发生在实例化和 launch 之后。
- **非法同步**。捕获中调用 `cudaStreamSynchronize()` 等待该流会失败，捕获可能失效。捕获范围内还要避免涵盖被捕获流的设备同步或查询，以及受模式约束的潜在不安全 API，例如普通 `cudaMalloc()`。预先准备缓冲区。若中途出错，仍在发起流结束捕获并检查结果，丢弃失败或空图，恢复到非捕获状态后重试或走普通提交。
- **跨流**。发起流 A 捕获并记录 Event E1，流 B 等 E1 后加入同一捕获图。B 提交任务并记录 E2，A 等 E2，把 B 汇回发起流后再结束捕获。未汇回的分支可导致结束失败。

Legacy 默认流不能发起捕获，捕获涉及 blocking 流时也应避免隐式触发 legacy 同步。Global 模式对潜在不安全调用的限制涉及其他线程，ThreadLocal 将这类限制限于发起线程，Relaxed 放宽此类限制，但仍禁止与捕获直接冲突的操作。除 Relaxed 外，结束捕获须由发起线程调用。[CUDA 12.8.1 Stream Capture](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-c-programming-guide/index.html#stream-capture) · [Stream API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__STREAM.html)

## 4. Graph 回放与普通 launch 的观测覆盖 {#_4-为什么只-hook-culaunchkernel-会漏数据}

执行图回放时，不保证经过应用拦截的普通 kernel launch 入口。因此，“hook 没命中”不能说明 kernel 没执行；也不能通过让图相关函数直接返回成功来绕过调用，这可能破坏输出句柄、依赖和应用正确性。

图节点遍历可以帮助读取定义态的 kernel 参数，但真实运行时间需要 profiler/activity 证据。节点数也取决于模型、形状、后端及版本。

CUPTI（CUDA Profiling Tools Interface，CUDA 性能分析工具接口）可记录 Activity（活动记录）。对支持的逐节点采集模式，kernel 记录可提供 Correlation ID（关联标识）、Graph ID（图标识）和 Graph Node ID（节点标识）。图及节点标识用于识别定义来源，不单独标识某次回放。另计 `cudaGraphLaunch` 的成功提交数，结合设备活动检查执行与时间。字段、时钟和采集粒度见 [第 8 章](/articles/ai-infra-api-wrapper.html)。

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

## 7. 对照实验：同一组三个短 kernel

Linux、兼容 NVIDIA 驱动、CUDA Toolkit 12.8.1 和受支持的 C++ 编译器。保存为 `graph_bench.cu` 后运行 `nvcc -std=c++17 -O2 graph_bench.cu -o graph_bench && ./graph_bench`。示例用相同设备缓冲区、输入、kernel、流和重复次数。构建前先做一次不计时的普通提交并同步，触发首次加载。正式测量前每种模式各预热 100 轮，每组计时 10000 轮。每轮 A 从固定输入重写中间值，因此各轮预期结果相同。

```cpp
#include <cuda_runtime.h>
#include <chrono>
#include <cstdio>
#include <cstdlib>
#include <vector>

void check(cudaError_t status) {
  if (status != cudaSuccess) {
    std::fprintf(stderr, "%s\n", cudaGetErrorString(status));
    std::exit(1);
  }
}

constexpr int n = 1024;
__global__ void a(const int* input, int* work) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  work[i] = input[i] + 1;
}
__global__ void b(int* work) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  work[i] *= 2;
}
__global__ void c(int* work) {
  int i = blockIdx.x * blockDim.x + threadIdx.x;
  work[i] -= 3;
}

int main() {
  using Clock = std::chrono::steady_clock;
  auto ms = [](auto from, auto to) {
    return std::chrono::duration<double, std::milli>(to - from).count();
  };
  constexpr int repeats = 10000;
  constexpr size_t bytes = n * sizeof(int);
  std::vector<int> input(n), output(n);
  for (int i = 0; i < n; ++i) input[i] = i;
  int *d_in, *d_work;
  check(cudaMalloc(&d_in, bytes));
  check(cudaMalloc(&d_work, bytes));
  cudaStream_t stream;
  check(cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking));
  check(cudaMemcpyAsync(d_in, input.data(), bytes, cudaMemcpyHostToDevice, stream));
  auto normal = [&] {
    a<<<4, 256, 0, stream>>>(d_in, d_work);
    check(cudaGetLastError());
    b<<<4, 256, 0, stream>>>(d_work);
    check(cudaGetLastError());
    c<<<4, 256, 0, stream>>>(d_work);
    check(cudaGetLastError());
  };
  normal();
  check(cudaStreamSynchronize(stream));

  cudaGraph_t graph;
  cudaGraphExec_t exec;
  auto begin = Clock::now();
  check(cudaStreamBeginCapture(stream, cudaStreamCaptureModeGlobal));
  normal();
  check(cudaStreamEndCapture(stream, &graph));
  auto built = Clock::now();
  check(cudaGraphInstantiate(&exec, graph, 0));
  auto instantiated = Clock::now();
  std::printf("build=%.3f ms instantiate=%.3f ms\n",
              ms(begin, built), ms(built, instantiated));

  cudaEvent_t start, stop;
  check(cudaEventCreate(&start));
  check(cudaEventCreate(&stop));
  auto run = [&](const char* label, auto submit) {
    for (int i = 0; i < 100; ++i) submit();
    check(cudaStreamSynchronize(stream));
    auto request_begin = Clock::now();
    check(cudaMemcpyAsync(d_in, input.data(), bytes, cudaMemcpyHostToDevice, stream));
    check(cudaStreamSynchronize(stream));
    check(cudaEventRecord(start, stream));
    auto before = Clock::now();
    for (int i = 0; i < repeats; ++i) submit();
    auto submitted = Clock::now();
    check(cudaEventRecord(stop, stream));
    check(cudaStreamSynchronize(stream));
    auto completed = Clock::now();
    float device_ms;
    check(cudaEventElapsedTime(&device_ms, start, stop));
    check(cudaMemcpy(output.data(), d_work, bytes, cudaMemcpyDeviceToHost));
    auto request_end = Clock::now();
    bool ok = true;
    for (int i = 0; i < n; ++i) {
      if (output[i] != 2 * i - 1) ok = false;
    }
    std::printf("%s submit=%.3f ms stream=%.3f ms wall=%.3f ms e2e=%.3f ms %s\n",
                label, ms(before, submitted), device_ms,
                ms(before, completed), ms(request_begin, request_end), ok ? "PASS" : "FAIL");
    return ok;
  };
  const bool normal_ok = run("normal", normal);
  const bool graph_ok = run("graph", [&] { check(cudaGraphLaunch(exec, stream)); });
  check(cudaEventDestroy(stop));
  check(cudaEventDestroy(start));
  check(cudaGraphExecDestroy(exec));
  check(cudaGraphDestroy(graph));
  check(cudaStreamDestroy(stream));
  check(cudaFree(d_work));
  check(cudaFree(d_in));
  return normal_ok && graph_ok ? 0 : 2;
}
```

CPU 时钟分别计量构建、实例化、提交循环及从开始提交到同步完成的整批墙钟时间。后者包含排队和等待，排除了两边同样执行的输入拷贝、回拷及校验。另以 e2e 计量从本批输入 H2D 前到输出 D2H 返回的时间，仍将一次性分配、建图、实例化及结果校验单列。提交时间包含代码中的错误检查和可能的排队背压。CUDA Event 计量流上两标记之间的设备时间跨度，其中可能有提交不及时导致的空档。要得到各 kernel 的设备执行区间，用逐节点设备活动记录。建议交替测试顺序、重复多轮并报告中位数与波动，同时记录 GPU、驱动、Toolkit 和性能分析开销。

简化成本为 `Tgraph = Tbuild + Tinstantiate + N × Treplay`，`Tnormal = N × Tnormal_launch`，两条路径的每轮成本须采用同一计量口径。若实际请求涉及输入准备、更新、搬运、同步和资源管理，应计入相应端到端成本。两组预期均输出 `PASS`，具体耗时与是否获益待设备实测。
