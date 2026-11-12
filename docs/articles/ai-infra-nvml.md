---
id: ai-infra-nvml
title: 第 10 章 NVML：设备、进程和 MIG 对象的只读观察
description: "NVML（NVIDIA Management Library）提供设备管理与监控接口，可以读取 UUID、显存、温度和进程等信息。"
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
order: 10
---

# 第 10 章 NVML：设备、进程和 MIG 对象的只读观察

NVML（NVIDIA Management Library）提供设备管理与监控接口，可以读取 UUID、显存、温度和进程等信息。使用时先定位设备与实例身份，再选择该对象支持的字段；kernel 级执行时间则由相应性能分析工具观察。

NVML 是 NVIDIA Management Library（NVIDIA 管理库），与 NVIDIA 驱动配套。它也有改电源限制、管理 MIG 等接口。本章主动限定为只读查询。设同一节点运行服务 A 和 B，A 的首 Token 延迟上升。先用以下工具确认观察层级。

| 工具                                                 | 解决的问题                                                   |
| ---------------------------------------------------- | ------------------------------------------------------------ |
| NVML、`nvidia-smi`                                   | 设备与实例身份、显存、温度和进程快照。`nvidia-smi` 基于 NVML |
| CUDA Runtime                                         | 初始化计算环境、分配内存和提交计算                           |
| DCGM（Data Center GPU Manager，数据中心 GPU 管理器） | 维护实体和字段采集，支撑长期趋势和诊断                       |
| CUPTI、Nsight                                        | 关联 CUDA API、GPU 活动，进一步分析具体 kernel 和性能计数器  |

## 1. 用 UUID 记录设备身份 {#_1-设备索引不是稳定身份}

GPU 0 只是当前枚举中的编号。重启、调整可见设备设置或设备发生变化后，索引与物理卡的对应关系可能改变。长期记录应保存 UUID，并关联 PCI Bus ID、节点和设备类型；容器内的编号也可能与宿主不同。

[![NVML：查询对象不能混用](/assets/notes/ai-infra/nvml-objects.svg)](/assets/notes/ai-infra/nvml-objects.svg)

GPU handle、GI handle、CI handle 和 MIG device handle 表示不同层次的对象。`nvmlGpuInstanceGetComputeInstanceById` 从父 GI 查询 CI，因此其父对象使用 GI handle。[NVML API](https://docs.nvidia.com/deploy/nvml-api/latest/index.html)

### 设备身份与实例生命周期

Node 是宿主节点身份。GPU Index 是本次枚举序号，GPU UUID（Universally Unique Identifier，通用唯一标识符）用于跨次关联物理卡。PCI Bus ID 描述本次系统拓扑中的 PCI 地址，设备换槽或拓扑变化后需要重查。容器内序号可随可见集合重排。假设节点 N 原先枚举 A、B 为 0、1，调整设备后交换顺序，仍可按物理 UUID 关联 A、B，并更新索引和 PCI 地址。

MIG（Multi-Instance GPU，多实例 GPU）在支持的硬件上划分 GPU。GI（GPU Instance，GPU 实例）提供一组计算及显存资源，CI（Compute Instance，计算实例）进一步划分所属 GI 的计算资源，共享该 GI 的相关内存资源。Profile ID 标识一种资源规格，GI ID 和 CI ID 标识当前实例，CI ID 应和父 GI 一起解释。

| 教学对象   | 物理 UUID | GI ID | CI ID | 设备视图                       |
| ---------- | --------- | ----: | ----: | ------------------------------ |
| 整卡 A     | GPU-A     |     — |     — | 物理 `nvmlDevice_t`            |
| A 的实例一 | GPU-A     |     3 |     0 | MIG UUID X、MIG `nvmlDevice_t` |
| A 的实例二 | GPU-A     |     3 |     1 | MIG UUID Y、MIG `nvmlDevice_t` |
| A 的实例三 | GPU-A     |     5 |     0 | MIG UUID Z、MIG `nvmlDevice_t` |

表中 ID 与 UUID 均为示意。MIG Device 是对 GI/CI 组合的设备视图，可用物理句柄和有效索引通过 `nvmlDeviceGetMigDeviceHandleByIndex()` 获取，再查询 MIG UUID、GI ID 与 CI ID。它与资源管理的 `nvmlGpuInstance_t`、`nvmlComputeInstance_t` 句柄分开。MIG 重建可改变 UUID、复用 ID 并使旧句柄失效，应重新发现并记录实例代次。设备支持、可用 Profile 和枚举权限按实际型号与驱动确认。[NVIDIA MIG 用户指南](https://docs.nvidia.com/datacenter/tesla/mig-user-guide/)

## 2. 一个只读 Python 教学例

Python 包通常通过 `nvidia-ml-py` 分发，导入名为 `pynvml`。在有 NVIDIA 驱动和设备访问权限的 Python 3 环境中安装 `python -m pip install nvidia-ml-py==12.570.86`，保存为 `observe_nvml.py`，执行 `python observe_nvml.py`。预期逐设备输出实际值或字段错误，空进程列表表示本次查询成功且没有返回计算进程。当前仅做静态与模拟检查。[固定包版本](https://pypi.org/project/nvidia-ml-py/12.570.86/)

```python
import pynvml as nv

STATUS = {
    nv.NVML_ERROR_NOT_SUPPORTED: "NOT_SUPPORTED",
    nv.NVML_ERROR_NO_PERMISSION: "NO_PERMISSION",
    nv.NVML_ERROR_NOT_FOUND: "NOT_FOUND",
    nv.NVML_ERROR_GPU_IS_LOST: "GPU_IS_LOST",
}

def read(field, query, *args):
    try:
        value = query(*args)
        print(f"  {field}: {value}")
        return value
    except nv.NVMLError as exc:
        print(f"  {field}: {STATUS.get(exc.value, 'ERROR')} ({exc})")
        return None

def memory(handle):
    value = nv.nvmlDeviceGetMemoryInfo(handle)
    return {"used_MiB": value.used / 2**20, "total_MiB": value.total / 2**20}

def utilization(handle):
    value = nv.nvmlDeviceGetUtilizationRates(handle)
    return {"gpu_percent": value.gpu, "memory_percent": value.memory}

def processes(handle):
    rows = []
    for process in nv.nvmlDeviceGetComputeRunningProcesses(handle):
        used = process.usedGpuMemory
        rows.append({
            "pid": process.pid,
            "used_bytes": (
                "N/A" if used in (None, nv.NVML_VALUE_NOT_AVAILABLE_ulonglong)
                else used
            ),
        })
    return rows

def main():
    try:
        nv.nvmlInit()
    except nv.NVMLError as exc:
        print(f"NVML init failed: {exc}")
        return 1

    try:
        read("driver", nv.nvmlSystemGetDriverVersion)
        count = read("device_count", nv.nvmlDeviceGetCount)
        if count is None:
            return 1
        for index in range(count):
            print(f"GPU index {index}")
            handle = read("handle", nv.nvmlDeviceGetHandleByIndex, index)
            if handle is None:
                continue
            read("uuid", nv.nvmlDeviceGetUUID, handle)
            read("name", nv.nvmlDeviceGetName, handle)
            read("pci_bus_id", lambda h: nv.nvmlDeviceGetPciInfo(h).busId, handle)
            read("memory", memory, handle)
            read("temperature_C", nv.nvmlDeviceGetTemperature, handle, nv.NVML_TEMPERATURE_GPU)
            read("utilization", utilization, handle)
            read("compute_processes", processes, handle)
        return 0
    finally:
        nv.nvmlShutdown()

if __name__ == "__main__":
    raise SystemExit(main())
```

## 3. 根据当前模式与 Profile 枚举 MIG 实例 {#_3-mig-枚举不能依赖硬编码数字}

先确认设备支持和当前 MIG 模式，再查询可用 profile、GI/CI 及其 UUID。profile 枚举值、profile ID、创建出的 instance ID、设备索引是不同概念。“整卡时 id 一律填 0”“最多八张卡”“A30 只有两种 profile”都不应成为跨型号规则。

## 4. 监控能力的缺失也是信息

MIG 下某些 NVML 利用率接口可能返回不支持，`nvidia-smi` 显示 N/A 也不代表工作没有执行。进程显存、设备利用率、GI/CI 指标的支持范围不同，应该分别记录；需要更细的实体指标时转向 DCGM 等支持路径，而不是把整卡平均值按显存比例拆给实例。

| 指标               | 读法                                                                     |
| ------------------ | ------------------------------------------------------------------------ |
| GPU Utilization    | 在产品相关采样窗口中有一个或多个 kernel 执行的时间比例，不是算力峰值效率 |
| Memory Used        | 已用显存容量，单位为字节，不反映带宽                                     |
| Memory Utilization | 采样窗口中全局显存被读写的时间比例，不是已用显存百分比                   |
| 进程显存           | 指定设备视图上报告的进程占用，可能不可用，不代表计算贡献                 |
| 进程利用率         | 支持时由独立 API 查询带时间戳的进程采样，不能从显存或整卡活动反推        |

即使整卡活动为假设的 90%，A、B 可能轮流运行，也可能重叠。一条整卡时间比例无法确定各自占用，MIG 视图上的部分查询还可能不支持。保留字段、采样窗口、对象和状态，再把进程与服务记录关联。[NVML 设备查询](https://docs.nvidia.com/deploy/nvml-api/latest/group__nvmlDeviceQueries.html)

## 5. 只读 GI/CI 查询的类型链

以 NVML R535 的 C 签名为参照，`nvmlDeviceGetGpuInstanceById` 接受 device handle 并返回 GI handle；`nvmlGpuInstanceGetComputeInstanceById` 再接受该 GI handle 并返回 CI handle。不要用 MIG device handle 或物理 GPU handle 替代第二步的父 GI。[NVML R535 MIG API](https://docs.nvidia.com/deploy/archive/R535/nvml-api/group__nvmlMultiInstanceGPU.html)

下面是 Python 绑定调用关系片段；`physical`、`gi_id`、`ci_id` 必须来自当前枚举结果，包签名也需核对，不是创建操作：

```python
gi = pynvml.nvmlDeviceGetGpuInstanceById(physical, gi_id)
ci = pynvml.nvmlGpuInstanceGetComputeInstanceById(gi, ci_id)
```

遇到 NOT_SUPPORTED、NO_PERMISSION、NOT_FOUND 等状态，分别检查能力、权限和实例是否已重建。重置或销毁后重新获取句柄，不能缓存旧 handle 无限重试。枚举 selector、返回的 profileId、GI/CI ID 和 UUID 仍要分别保存，不用一列“GPU id”混装。

| 返回状态                   | 处理                                                                 |
| -------------------------- | -------------------------------------------------------------------- |
| `NVML_SUCCESS`             | 使用返回值，仍检查字段级 N/A 哨兵                                    |
| `NVML_ERROR_NOT_SUPPORTED` | 当前硬件、模式或对象不支持，保留状态                                 |
| `NVML_ERROR_NO_PERMISSION` | 核对设备节点和调用权限，勿推断设备不支持                             |
| `NVML_ERROR_NOT_FOUND`     | 实例或索引已不存在时重新发现                                         |
| `NVML_ERROR_GPU_IS_LOST`   | 停止用旧句柄轮询该设备，检查驱动和系统事件                           |
| 其他错误                   | 保留原始码，例如未初始化、无效参数、驱动未加载或符号不可用，分别排查 |

R535 文档在两个 ById 查询中均列出 `NVML_ERROR_NO_PERMISSION`，应按目标驱动的权限要求处理。管理接口的权限还需逐函数核对。先以当前用户执行只读诊断，权限不足时再按部署策略处理。用本章确认 A、B 的物理 GPU 或 MIG 实例，再到[第 11 章](/articles/ai-infra-dcgm-monitoring.html)建立同一实体的时序。
