---
id: ai-infra-api-wrapper
title: 第 8 章 API Wrapper：覆盖范围与异步观测
description: 原包装笔记旨在记录内存分配位置、API 参数与返回值。应先明确它属于“链接期符号包装”，再判断能够覆盖哪些路径；不能因为命中过一次 cudaMalloc，就认定已经观测到全部 GPU 工作。
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
order: 8
---

# 第 8 章 API Wrapper：覆盖范围与异步观测

原包装笔记旨在记录内存分配位置、API 参数与返回值。应先明确它属于“链接期符号包装”，再判断能够覆盖哪些路径；不能因为命中过一次 `cudaMalloc`，就认定已经观测到全部 GPU 工作。

## 1. 链接期包装的边界

![API 调用与设备活动分开观察](/assets/notes/ai-infra/observe-paths.svg)

GNU ld 的 `--wrap=symbol` 重定向参与该链接过程的相应未定义引用。已解析的内部引用、独立动态库、`dlsym`/Driver 入口查询和其他 API 变体，需要分别确认。[GNU ld：wrap](https://sourceware.org/binutils/docs/ld/Options.html)

| 路径                     | 应检查的证据         | 不能直接宣称                   |
| ------------------------ | -------------------- | ------------------------------ |
| 参与最终链接的调用点     | 符号与实际命中计数   | 所有独立 DSO 也被改写          |
| Runtime/Driver 调用      | 两套入口及实际库依赖 | 包装 Runtime 已覆盖全部 Driver |
| legacy/per-thread stream | 目标版本符号解析     | `_ptsz` 列表永远完整           |
| 普通 launch/Graph replay | 调用计数与设备活动   | 每次回放必经过普通 launch      |

## 2. 最小 Wrapper：保持返回语义

新增教学片段，未编译。`size_t` 用 `%zu`，只有成功时读取有效输出值，不吞错误、不假成功。

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

同时记录 `dim3` 字段时，需要匹配无符号类型，也要避免复制时弄错 API 名称。真实采集层还需处理递归、并发、初始化和日志成本，不能直接将高频 `printf` 用于生产实现。

链接选项放在目标的链接配置中，不批量塞进全局编译 flags。以下 CMake 片段假定 `app` 已定义、wrapper 源码已加入，并使用支持 GNU `--wrap` 的 host linker；要求 CMake 至少 3.18，未实际配置或链接：

```cmake
target_link_options(app PRIVATE
  "$<HOST_LINK:LINKER:--wrap=cudaMalloc>"
)
```

该配置表达 host link 阶段意图，不保证覆盖 `nvcc`、Runtime 静/动态链接和独立库的全部组合；仍须查看实际链接命令及命中测试。[CMake target_link_options](https://cmake.org/cmake/help/latest/command/target_link_options.html)

## 3. 异步内存需要两套账

| 记录项                       | 反映什么               | 释放时要注意                  |
| ---------------------------- | ---------------------- | ----------------------------- |
| requested/live logical bytes | 应用的有效分配请求     | 失败请求不应计为活跃分配      |
| pending stream operations    | 已排队的分配/使用/释放 | host 返回不等于设备已到达该点 |
| pool reserved bytes          | 内存池保留的后备空间   | logical free 后可能仍由池保留 |

`cudaFreeAsync` 入队并不等于后备显存立即归还给系统；释放点之后不能再访问该分配，后续工作也不能因为 host 地址值还在就继续使用。跨 stream 使用必须满足相应顺序和生命周期。[CUDA 12.8.1 流序分配 API](https://docs.nvidia.com/cuda/archive/12.8.1/cuda-runtime-api/group__CUDART__MEMORY__POOLS.html)

包装层的 host enter/exit 不能冒充 kernel start/end。需要设备时间时使用受支持的 profiler/activity 路径并关联标识；这里只说明自定义观测的职责，不展开独立接口教程。[CUPTI Usage](https://docs.nvidia.com/cupti/main/main.html)

## 4. 验收覆盖，而不是只增加符号名单

覆盖矩阵应包含静态/动态库、Runtime/Driver、异步内存池、Graph、多线程和失败路径。需要比较无包装/有包装时的结果、返回值和资源寿命，并测量采集开销。未捕获的路径应明确记录为“未观测”；不能为了便于统计而每次强制设备同步，这会改变原有行为。
