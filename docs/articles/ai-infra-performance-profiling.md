---
id: ai-infra-performance-profiling
title: 第 12 章 性能分析：先看时间线，再看 Kernel
description: "GPU 性能分析先把业务延迟拆到 CPU、提交、搬运与设备计算等阶段，再选择适合该层次的工具。本章按系统时间线、选定 kernel 和长期监控的顺序，说明如何从现象缩小到可验证的瓶颈假设。"
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
order: 12
---

# 第 12 章 性能分析：先看时间线，再看 Kernel

GPU 性能分析先把业务延迟拆到 CPU、提交、搬运与设备计算等阶段，再选择适合该层次的工具。本章按系统时间线、选定 kernel 和长期监控的顺序，说明如何从现象缩小到可验证的瓶颈假设。

## 1. 工具分工

| 工具           | 优先回答的问题                 | 典型输出                 |
| -------------- | ------------------------------ | ------------------------ |
| Nsight Systems | CPU/GPU 在等待什么，哪里有空隙 | CUDA、CPU、NVTX 等时间线 |
| Nsight Compute | 选定 kernel 为什么慢           | 指令、访存、占用率等分析 |
| NVML/DCGM      | 长期状态与资源是否异常         | 设备、实体和采样指标     |
| 业务压测       | 用户实际得到了什么             | 延迟分位数、吞吐和错误率 |

[![性能定位：按证据选择工具](/assets/notes/ai-infra/profiling-decision.svg)](/assets/notes/ai-infra/profiling-decision.svg)

沿用前两章的双服务场景。假设服务 A 的 TTFT（Time to First Token，首 Token 延迟）升高且请求吞吐低于目标，服务 B 与它共用节点。先固定模型、输入输出长度、并发和负载模式，记录请求吞吐、错误率及 TTFT 分位数。用 [NVML](/articles/ai-infra-nvml.html)确认进程、节点、GPU UUID 和实例，再用 [DCGM](/articles/ai-infra-dcgm-monitoring.html)核对同一实体的活动和显存趋势。设备活动异常只是线索，不能据此把根因归给某个请求或 kernel。

把诊断分成三段。先无 profiler 测业务基线。随后用 Nsight Systems 找到主要耗时阶段，仅在设备热点已明确时用 Nsight Compute 分析选中的 kernel。最后只修改一个因素，在相同负载下关闭 profiler 再测业务。持续监控的采集配置也应在两组一致，并记录是否暂停了 profiling 字段。

## 2. 先做一份有限窗口的时间线

下面是 Linux 文档示例，`app.py` 为占位应用；实际采集会运行应用、产生报告并带来开销。

```bash
nsys profile --trace=cuda,nvtx --delay=5 --duration=10 --kill=none --stop-on-exit=true \
  --output=trial python app.py
nsys stats trial.nsys-rep
```

可以用 NVTX 自定义标记对齐业务阶段：用请求处理、prefill、decode、数据加载等业务阶段对齐时间线。先预热并关注稳定区间，避免把首次 JIT 或模型加载误当作每次请求成本。[Nsight Systems User Guide](https://docs.nvidia.com/nsight-systems/UserGuide/index.html)

以 Linux 的 Nsight Systems CLI 手册为准，`--delay=5` 从启动后推迟 5 秒开始采集，`--duration=10` 限制采集时长为 10 秒。示例显式设置 `--stop-on-exit=true`，目标先正常退出时采集随之结束。限时结束时，手册记录的 Linux 默认行为可能向目标进程组发送 SIGTERM。下面显式用 `--kill=none`，避免采集结束时由该选项终止目标。请用能自行退出的实验程序运行，记录 `nsys --version`，先用 `nsys profile --help` 核对本机版本。不要直接用它启动生产服务并假定服务会在采集后照常运行。对长驻服务优先用隔离副本、按工具版本核对受支持的附加或会话控制方式，并安排停止和清理。用 NVTX（NVIDIA Tools Extension，NVIDIA 工具扩展）标出预热后的稳定阶段，可在支持版本中用 `--capture-range=nvtx` 和指定 NVTX 范围选择窗口，另核对范围结束策略。

| 请求阶段      | 假设耗时 |
| ------------- | -------: |
| CPU 输入准备  |   3.0 ms |
| CUDA API 提交 |   0.3 ms |
| GPU 等待依赖  |   1.5 ms |
| GPU Kernel    |   2.0 ms |
| 结果处理      |   1.2 ms |
| 合计          |   8.0 ms |

这是各阶段完全串行的教学时间线。真实请求可能在 CPU、GPU 和拷贝引擎间重叠，应按实际关键路径计时。API Duration 是主机区间，队列等待是尚未执行设备工作的时间，Kernel Duration 才是设备活动区间。主机同步耗时可能覆盖多个上游依赖。若 A 符合表中情形，即使把 kernel 从 2.0 ms 减半，请求仍需 7.0 ms。优先验证输入准备或依赖为何变慢。

## 3. 再缩小到一个 Kernel

```bash
ncu --set basic --launch-count 1 --output=kernel-trial python app.py
```

该命令只展示最小采集思路，不保证首个 kernel 就是目标，实际使用时应按名称和启动范围筛选。Nsight Compute 可能通过 replay 收集多组计数器，因此测得的时间不等于无采集条件下的业务延迟。metric 名称也会随硬件和版本变化，应查询支持列表后再选择。[Nsight Compute Profiling Guide](https://docs.nvidia.com/nsight-compute/ProfilingGuide/index.html)

从 Systems 的 CUDA GPU 时间线选目标，记录进程、设备、Context、Stream、kernel 名称、启动配置及该名称第几次出现。用相同输入复现，先核查本机 `ncu --version` 和 `ncu --help`，再按以下方式缩小范围。

| 选项                               | 作用                                                                          |
| ---------------------------------- | ----------------------------------------------------------------------------- |
| `--kernel-name`                    | 按指定名称基准匹配，可使用 `regex:`                                           |
| `--kernel-id`                      | 可用 Context、Stream、名称和调用序号的组合进一步定位，具体语法以 CLI 帮助为准 |
| `--launch-skip` / `--launch-count` | 跳过匹配过滤条件的启动，再限制采集次数                                        |
| `--list-sets` / `--query-metrics`  | 分别查询采集集合和本机可用指标。部分指标还要选芯片及查询模式                  |

例如本章实验预热 20 次后，可用 `ncu --kernel-name-base function --kernel-name copy_layout --launch-skip 20 --launch-count 1 --set basic -o layout-row ./layout row`。报告生成后仍需核对选中的名称、网格和 launch 序号。多进程要确认是否需 `--target-processes all` 并限定目标，避免误采其他进程。多 GPU 时固定可见设备和目标 GPU，进程内序号可能重排。计数器采集依赖硬件支持与驱动权限，遇到权限错误应检查管理员配置并参照[第 11 章](/articles/ai-infra-dcgm-monitoring.html)协调其他采集器。[Nsight Compute CLI](https://docs.nvidia.com/nsight-compute/NsightComputeCli/index.html)

## 4. 用 Occupancy 与 Roofline 分析瓶颈假设 {#_4-occupancy-和-roofline-怎么用}

较高的 Occupancy 可能有助于隐藏延迟，但它本身不是优化目标。如果增加常驻 warp 导致寄存器溢出，运行反而可能更慢。判断时需要综合考虑共享内存、寄存器和 block 数的约束。

Roofline 用算术强度 `I = 运算次数 / 数据字节数` 连接计算峰值与带宽峰值，可建立 `性能上界 ≈ min(计算峰值, 带宽 × I)`。这里必须注明数据来自哪一层、使用哪种精度。它是帮助提出瓶颈假设的模型，不是精确预测器。

Arithmetic Intensity（算术强度）用 `I = FLOPs / Bytes` 表示，Roofline 上界为 `Pmax ≈ min(Pcompute, BW × I)`。Compute Throughput（计算吞吐）用选定精度的运算率衡量，Memory Throughput（内存吞吐）用穿过所选边界的字节率衡量。使用 DRAM 字节应配 DRAM 带宽，使用 L2 字节应配 L2 带宽。峰值只给出上界，指令依赖、同步或 launch 等也可能先限制性能。

Theoretical Occupancy（理论占用率）由启动配置和寄存器、共享内存及 SM 的常驻上限推导。Achieved Occupancy（实际占用率）来自执行期间的活跃 warp 采样。两者的差距可来自负载不均衡或尾部，数值高也可能出现就绪 warp 少或内存等待。SM Active 反映有活跃 warp 的空间与时间比例，和峰值算力效率采用不同分母。

假设时间线指向 A 的某个低算术强度 kernel。若 Compute 报告显示大量全局访问事务、低有效字节比例和访存等待，可先提出访存不合并的假设。核对线程索引、实际 DRAM/L2 流量和就绪 warp，再用只改访问布局的对照验证。若调整后事务减少但无采集延迟没有改善，就回到业务关键路径或排查其他限制。

## 5. 一次可复查的优化实验

固定版本和输入 → 正确性基线 → 无采集端到端基线 → 定位热点 → 只改一个因素 → 同样负载复测。报告同时列出均值和尾延迟、重复次数、预热、并发及是否启用 profiler。改动收益按上述条件下的复测结果报告，说明改善幅度及其适用范围。

### 对照实验：改变 warp 内的地址步长

固定为一张 GPU、一个进程、一条默认流，复制 2048 × 2048 个整数。两组只切换线程到元素的映射：行向连续与列向跨步。每组均读写同样的数据，执行同一 kernel，网格与块大小固定。下面的测试不启用 profiler 时用 CUDA Event 计量整批并除以轮数，排除初始化、回拷与校验。

```cpp
#include <cuda_runtime.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <vector>

constexpr int side = 2048;
constexpr int count = side * side;

void check(cudaError_t status) {
  if (status != cudaSuccess) {
    std::fprintf(stderr, "%s\n", cudaGetErrorString(status));
    std::exit(1);
  }
}

__global__ void copy_layout(const int* input, int* output, bool column) {
  int t = blockIdx.x * blockDim.x + threadIdx.x;
  int i = column ? (t % side) * side + t / side : t;
  output[i] = input[i];
}

int main(int argc, char** argv) {
  if (argc != 2 || (std::strcmp(argv[1], "row") && std::strcmp(argv[1], "column"))) {
    std::fprintf(stderr, "usage: %s row|column\n", argv[0]);
    return 1;
  }
  bool column = std::strcmp(argv[1], "column") == 0;
  constexpr size_t bytes = count * sizeof(int);
  constexpr int repeats = 100;
  std::vector<int> input(count), output(count);
  for (int i = 0; i < count; ++i) input[i] = i;
  int *src, *dst;
  check(cudaMalloc(&src, bytes));
  check(cudaMalloc(&dst, bytes));
  check(cudaMemcpy(src, input.data(), bytes, cudaMemcpyHostToDevice));
  cudaEvent_t start, stop;
  check(cudaEventCreate(&start));
  check(cudaEventCreate(&stop));
  auto launch = [&] {
    copy_layout<<<count / 256, 256>>>(src, dst, column);
    check(cudaGetLastError());
  };
  for (int i = 0; i < 20; ++i) launch();
  check(cudaDeviceSynchronize());
  check(cudaEventRecord(start));
  for (int i = 0; i < repeats; ++i) launch();
  check(cudaEventRecord(stop));
  check(cudaEventSynchronize(stop));
  float elapsed;
  check(cudaEventElapsedTime(&elapsed, start, stop));
  check(cudaMemcpy(output.data(), dst, bytes, cudaMemcpyDeviceToHost));
  bool ok = input == output;
  std::printf("%s %.6f ms/launch %s\n", argv[1], elapsed / repeats, ok ? "PASS" : "FAIL");
  check(cudaEventDestroy(stop));
  check(cudaEventDestroy(start));
  check(cudaFree(dst));
  check(cudaFree(src));
  return ok ? 0 : 2;
}
```

保存为 `layout.cu`，在 Linux、兼容驱动、CUDA Toolkit 12.8.1 和受支持宿主编译器下构建。Nsight 与 Toolkit 分别记录版本。先不启动 profiler 运行两组，再按第 3 节过滤分别采样，最后退出 profiler、交替顺序重复两组。两种模式都应输出 `PASS`，时间和瓶颈待实测。不要把带 Replay 的程序计时并入无采集结果。

```bash
nvidia-smi
nvcc --version
nsys --version
ncu --version
nvcc -std=c++17 -O2 layout.cu -o layout
./layout column
./layout row
```

| 记录项           | 填写内容                                                          |
| ---------------- | ----------------------------------------------------------------- |
| 版本与设备       | GPU 型号、计算能力、驱动、Toolkit、Nsight Systems 与 Compute 版本 |
| 条件             | 输入、并发、预热 20 轮、计时 100 轮、重复实验批数、后台工作负载   |
| 无采集基线与复测 | 两组输出一致性、每批平均耗时、重复批次的中位数和波动              |
| 有采集诊断       | 目标 kernel、Replay 与缓存配置、访问事务、有效字节与实际流量      |
| 业务复测         | 同负载的吞吐、TTFT 分位数和错误率；微基准收益需回到服务中验证     |

## 6. Trace、GPU Metrics 和 Replay 分开标注

`nsys --trace=cuda,nvtx` 提供相应 API/活动与标记时间线，不代表默认已经取得所有 SM occupancy、DRAM 带宽和硬件指标。若额外启用 GPU metrics，核对硬件支持、采样配置和权限，并在报告中列为另一项采集配置。

`ncu` 的 kernel 选择、replay 与缓存控制则可能改变观测条件。不要把多 pass 得到的计数器直接视为该服务某次无干扰请求的完整现场。对“多个 GPU kernel 同时重叠”的问题，应保留 Systems 时间线作为背景，再选择需深入的 kernel；不同工具报告的百分比也不能在不核对分母时相互验证。

## 7. 从现象缩小排查范围

| 现象                   | 待验证假设               | 工具与证据                                     | 下一步                                    |
| ---------------------- | ------------------------ | ---------------------------------------------- | ----------------------------------------- |
| 许多短 kernel 间有空隙 | CPU Launch 提交受限      | Systems 的 API 密度、GPU 间隙                  | 核对提交线程与批次后，再对照 Graph 等路径 |
| H2D/D2H 占比高         | 频繁拷贝或未重叠         | Systems 的复制区间和传输量                     | 核对缓冲区驻留、拷贝依赖及页锁定条件      |
| 少数 kernel 持续很长   | 计算流水线接近上限       | Compute 的运算吞吐与指令结构                   | 对照精度和对应计算峰值                    |
| 内存操作密集           | DRAM 带宽或低效事务限制  | Compute 的 DRAM 字节率、实际事务与 Roofline    | 对照访问布局或数据复用                    |
| 常驻 warp 少           | 寄存器或共享内存限制     | Compute 的 Occupancy 限制项、spill 和就绪 warp | 只改块大小等一个因素并复测                |
| GPU 空闲               | 请求不足或批次准备延迟   | 业务队列、Systems 的设备空隙                   | 对齐到达率、调度和提交时刻                |
| CPU 预处理长           | 分词、线程或锁限制       | CPU 栈、NVTX 预处理区间                        | 复现并对比并发及输入长度                  |
| 同步调用长             | 正在等跨流事件或上游工作 | Systems 的同步调用、Event 和 Stream 时间线     | 追踪依赖生产者并验证能否缩小等待范围      |
| 队列增长、TTFT 变慢    | 排队或调度限制           | 请求日志、NVTX、DCGM 同实体时序                | 固定负载，单独验证批处理策略              |
