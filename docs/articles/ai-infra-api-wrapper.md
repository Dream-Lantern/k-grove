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

## 3. 异步内存需要两套账

| 记录项                       | 反映什么               | 释放时要注意                  |
| ---------------------------- | ---------------------- | ----------------------------- |
| requested/live logical bytes | 应用的有效分配请求     | 失败请求不应计为活跃分配      |
| pending stream operations    | 已排队的分配/使用/释放 | host 返回不等于设备已到达该点 |
| pool reserved bytes          | 内存池保留的后备空间   | logical free 后可能仍由池保留 |

`cudaFreeAsync` 入队并不等于后备显存立即归还给系统；释放点之后不能再访问该分配，后续工作也不能因为 host 地址值还在就继续使用。跨 stream 使用必须满足相应顺序和生命周期。[CUDA 12.8.1 流序分配 API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__MEMORY__POOLS.html)

包装层的 host enter/exit 不能冒充 kernel start/end。需要设备时间时使用受支持的 profiler/activity 路径并关联标识。[CUPTI Usage](https://docs.nvidia.com/cupti/main/main.html)

## 4. 用覆盖矩阵验证返回值与资源生命周期 {#_4-验收覆盖-而不是只增加符号名单}

覆盖矩阵应包含静态/动态库、Runtime/Driver、异步内存池、Graph、多线程和失败路径。需要比较无包装/有包装时的结果、返回值和资源寿命，并测量采集开销。未捕获的路径应明确记录为“未观测”。
