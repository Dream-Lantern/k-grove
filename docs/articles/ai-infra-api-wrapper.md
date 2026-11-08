---
id: ai-infra-api-wrapper
title: 第 8 章 API Wrapper：覆盖范围与异步观测
description: "介绍 CUDA 调用拦截的常见入口，区分链接包装、动态符号解析与驱动接口，并说明各条路径的适用条件。"
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
order: 8
---

# 第 8 章 API Wrapper：覆盖范围与异步观测

## 1. 从链接符号到实际调用覆盖 {#_1-链接期包装的边界}

[![观测链：API 与设备活动](/assets/notes/ai-infra/observe-paths.svg)](/assets/notes/ai-infra/observe-paths.svg)

GNU ld 的 `--wrap=symbol` 重定向参与该链接过程的相应未定义引用。已解析的内部引用、独立动态库、`dlsym`/Driver 入口查询和其他 API 变体，需要分别确认。[GNU ld：wrap](https://sourceware.org/binutils/docs/ld/Options.html)

| 路径                     | 应检查的证据         | 不能直接宣称                   |
| ------------------------ | -------------------- | ------------------------------ |
| 参与最终链接的调用点     | 符号与实际命中计数   | 所有独立 DSO 也被改写          |
| Runtime/Driver 调用      | 两套入口及实际库依赖 | 包装 Runtime 已覆盖全部 Driver |
| legacy/per-thread stream | 目标版本符号解析     | `_ptsz` 列表永远完整           |
| 普通 launch/Graph replay | 调用计数与设备活动   | 每次回放必经过普通 launch      |

### 一次 `cudaMalloc()` 从哪里经过

应用调用 CUDA Runtime（运行时）的 `cudaMalloc()`，运行时按当前设备和 Context 处理请求，并借助驱动管理设备分配。CUDA Driver API（驱动接口）也提供可直接调用的分配入口。Runtime API 与公开 Driver 入口没有一一对应的承诺，内部路径会随版本和状态变化。覆盖验收从实际调用点、符号或设备活动取证。[CUDA 12.8.1 Runtime 与 Driver 的差异](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/driver-vs-runtime-api.html)

| 方式                 | 条件与作用                                                                  | 验证边界                                                                   |
| -------------------- | --------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| GNU ld `--wrap`      | 链接器改写该链接输入中的未定义引用                                          | 检查链接映射、符号及运行命中；独立 DSO 内调用未随应用重新链接              |
| `LD_PRELOAD`         | ELF 动态加载器预加载符号，能拦截按其查找顺序绑定的调用                      | 不能改写静态、隐藏、直接绑定或绕开搜索范围的调用。用动态绑定日志与对照验证 |
| `dlsym()`            | 在给定句柄或范围内动态查找符号并返回地址                                    | 显式句柄查找可能避开预加载实现。检查句柄、`dlerror()` 和实际地址所属库     |
| `cuGetProcAddress()` | 按 Driver API、请求的 CUDA 版本与流语义取得函数地址                         | 调用函数指针不会经过普通链接符号引用，检查请求和返回状态                   |
| CUPTI                | 使用 Callback 观察所启用的 API 域，用 Activity 观察所启用的运行时和设备记录 | 记录版本、启用项和丢失记录数，按实际采集范围判断                           |

动态加载语义可查 [Linux man-pages 的 dlsym](https://man7.org/linux/man-pages/man3/dlsym.3.html) 与 [ld.so](https://man7.org/linux/man-pages/man8/ld.so.8.html)，CUDA 入口选择见 [12.8.1 Driver Entry Point Access](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-driver-api/group__CUDA__DRIVER__ENTRY__POINT.html)。

## 2. 最小 Wrapper：保持返回语义

包装函数需要保持原接口的返回值与有效输出语义：`size_t` 用 `%zu`，成功后再读取相应输出，失败时保留错误供调用方处理。

```cpp
#include <cuda_runtime_api.h>
#include <cstdio>
extern "C" cudaError_t __real_cudaMalloc(void**, size_t);
extern "C" cudaError_t __wrap_cudaMalloc(void** out, size_t bytes) {
  cudaError_t rc = __real_cudaMalloc(out, bytes);
  void* logged = (rc == cudaSuccess && out != nullptr) ? *out : nullptr;
  std::fprintf(stderr, "cudaMalloc bytes=%zu ptr=%p rc=%d\n",
               bytes, logged, static_cast<int>(rc));
  return rc;
}
```

```cmake
target_link_options(app PRIVATE
  "$<HOST_LINK:LINKER:--wrap=cudaMalloc>"
)
```

该配置表达 host link 阶段意图。[CMake target_link_options](https://cmake.org/cmake/help/latest/command/target_link_options.html)

### 构建和运行

Linux ELF、GNU ld、CMake 3.18+ 和 CUDA Toolkit 12.8.1。将上面的 wrapper 保存为 `wrap.cpp`。以下保存为 `main.cpp`，显式使用 `void**` 入口。

```cpp
#include <cuda_runtime_api.h>
#include <cstdio>

int main() {
  void* ptr = nullptr;
  cudaError_t rc = cudaMalloc(&ptr, 4096);
  if (rc == cudaSuccess) rc = cudaFree(ptr);
  if (rc != cudaSuccess) {
    std::fprintf(stderr, "%s\n", cudaGetErrorString(rc));
    return 1;
  }
  std::puts("PASS");
  return 0;
}
```

```cmake
cmake_minimum_required(VERSION 3.18)
project(cuda_wrap LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 11)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
find_package(CUDAToolkit 12.8 REQUIRED)
add_executable(app main.cpp wrap.cpp)
target_link_libraries(app PRIVATE CUDA::cudart)
target_link_options(app PRIVATE
  "$<HOST_LINK:LINKER:--wrap=cudaMalloc>"
)
add_executable(plain main.cpp)
target_link_libraries(plain PRIVATE CUDA::cudart)
```

这两个目标都是普通 C++ 宿主链接，`HOST_LINK` 将该选项限制在宿主阶段，`LINKER:` 由 CMake 转交链接器，例如 GCC 驱动下传为 `-Wl,--wrap=cudaMalloc`。在 Linux 上，`extern "C"` 使 `__wrap_cudaMalloc` 与 `__real_cudaMalloc` 使用无 C++ 名字修饰的符号，参数、返回值和调用约定必须匹配头文件 ABI。链接器将应用的未定义 `cudaMalloc` 引用改为 `__wrap_cudaMalloc`，再把包装内的 `__real_cudaMalloc` 引用解析回原符号。

```bash
cmake -S . -B build -DCUDAToolkit_ROOT=/usr/local/cuda-12.8
cmake --build build --verbose
nm -C build/app | grep cudaMalloc
./build/app
./build/plain
```

正常预期是 `app` 有一行 `cudaMalloc bytes=4096 ptr=<设备指针> rc=0` 和 `PASS`，`plain` 只有 `PASS`。在 `app` 的 main 中改用 `cudaMallocManaged(&ptr, 4096, cudaMemAttachGlobal)` 并重编，预期该调用点不会触发 `cudaMalloc` 包装，即使分配成功。CUDA 运行结果待实测。

## 3. 异步内存需要两套账

| 记录项                       | 反映什么               | 释放时要注意                  |
| ---------------------------- | ---------------------- | ----------------------------- |
| requested/live logical bytes | 应用的有效分配请求     | 失败请求不应计为活跃分配      |
| pending stream operations    | 已排队的分配/使用/释放 | host 返回不等于设备已到达该点 |
| pool reserved bytes          | 内存池保留的后备空间   | logical free 后可能仍由池保留 |

`cudaFreeAsync` 入队并不等于后备显存立即归还给系统；释放点之后不能再访问该分配，后续工作也不能因为 host 地址值还在就继续使用。跨 stream 使用必须满足相应顺序和生命周期。[CUDA 12.8.1 流序分配 API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__MEMORY__POOLS.html)

包装层的 host enter/exit 不能冒充 kernel start/end。需要设备时间时使用受支持的 profiler/activity 路径并关联标识。[CUPTI Usage](https://docs.nvidia.com/cupti/main/main.html)

流序内存分配（Stream-Ordered Memory Allocation）把分配和释放置于流顺序中。主机拿到指针后，设备只有在有序执行到分配点之后才能访问。合法例是在 A 流分配并记录 E，B 流等 E 后使用，B 再记录完成事件，A 等到完成后入队释放。同一流中直接按分配、使用、释放提交也合法。若 B 无等待就访问，或 A 的释放未等待 B 的最后使用，指针值仍在也不能保证有效。调用 `cudaFreeAsync()` 后不再提交新的访问。

账本应拆开记录请求字节（含失败）、成功返回后的逻辑存活字节（按约定在成功入队释放后扣除）、尚未确认完成的异步分配和释放、`cudaMemPoolAttrReservedMemCurrent` 的池保留字节，以及进程或设备层可观察显存占用。它们有不同采样时点和统计范围，可能重叠。池保留可以在逻辑释放后继续存在，跨流复用还需满足池策略和依赖条件。前置分配及 Context 归属分别见 [第 4 章](/articles/ai-infra-cuda-memory.html)和[第 5 章](/articles/ai-infra-green-context.html)。

### 将主机调用与设备活动关联

一条可能的时间线为 `API enter → 工作入队 → API exit → kernel start → kernel end → 同步返回`。入队发生在调用内部，设备也可能在 API 返回前开始。一次同步可能涵盖多项工作。CPU 计时只覆盖所量的主机区间。

CUPTI Callback 给出 Runtime 或 Driver 域中的 API 进入和退出。API Activity 提供时间和 Correlation ID（关联标识），设备 Activity 给出 kernel 或 memcpy 执行区间。按记录类型及关联 ID 连接主机提交与设备活动，并保留 Context ID 和 Stream ID 区分执行环境。对 CUDA 12.8.1 所配 CUPTI，`CUpti_ActivityKernel9` 可含 `correlationId`、`contextId`、`streamId`、`graphId` 和 `graphNodeId`。节点级与整图采集粒度不同，整图记录不能分解出每个 kernel 耗时。核对零值、时间戳缺失和丢失记录，跨时钟域使用 CUPTI 时间戳或经过校准的时基，避免将应用时钟直接与设备记录相减。[CUPTI 12.8.1 Kernel9](https://docs.nvidia.com/cupti/12.8.1/api/structCUpti__ActivityKernel9.html) · [CUPTI 12.8.1 Usage](https://docs.nvidia.com/cupti/12.8.1/main/main.html)

## 4. 用覆盖矩阵验证返回值与资源生命周期 {#_4-验收覆盖-而不是只增加符号名单}

覆盖矩阵应包含静态/动态库、Runtime/Driver、异步内存池、Graph、多线程和失败路径。需要比较无包装/有包装时的结果、返回值和资源寿命，并测量采集开销。未捕获的路径应明确记录为“未观测”。

以下矩阵是待执行用例，命中预期仅针对上述单一符号包装。

| 路径                                  | 是否执行 | Wrapper 命中预期                   | 待取证                      |
| ------------------------------------- | -------- | ---------------------------------- | --------------------------- |
| 应用 Runtime `cudaMalloc`             | 待测     | 命中最终链接中的未定义引用         | 符号、日志、返回值          |
| Driver `cuMemAlloc`                   | 待测     | 该调用点不命中                     | Driver API Activity         |
| 静态 cudart                           | 待测     | 外部未定义引用可命中，内部路径另验 | 链接映射、运行计数          |
| 已链接的独立 DSO                      | 待测     | 内部调用不由 app 的链接改写        | DSO 符号、独立日志          |
| 显式句柄 `dlsym` / `cuGetProcAddress` | 待测     | 经解析地址调用不走该引用           | 实际目标库、API 记录        |
| 多线程                                | 待测     | 逐个验证调用点与线程               | 每线程计数、丢失率          |
| Graph Replay                          | 待测     | 该包装未覆盖回放提交或节点执行     | Graph launch 计数、设备活动 |
| `cudaMallocAsync` / `cudaFreeAsync`   | 待测     | 两者是独立入口                     | 顺序证据、逻辑与池账本      |
| `cudaMalloc` 失败                     | 待测     | 可命中，保留错误且不读无效输出     | 错误码、逻辑账本不增加      |

动态拦截使用 `RTLD_NEXT` 时，应确认下一个符号及查找失败的处理，避免重复包装或包装间递归。日志器也可能触发分配，应考虑重入保护、线程安全、缓冲与丢失计数。逐调用输出可能竞争锁并干扰延迟。跟踪符号变体、ABI 和有效输出语义，比较启用前后结果与开销。设备证据不可得时记 UNKNOWN。

[第 9 章](/articles/ai-infra-gpu-containers.html)继续检查实际加载的 Runtime、Driver、工具库及容器注入，这些环境差异会改变符号绑定和可采集范围。
