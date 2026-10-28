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

## 1. 用 UUID 记录设备身份 {#_1-设备索引不是稳定身份}

GPU 0 只是当前枚举中的编号。重启、调整可见设备设置或设备发生变化后，索引与物理卡的对应关系可能改变。长期记录应保存 UUID，并关联 PCI Bus ID、节点和设备类型；容器内的编号也可能与宿主不同。

[![NVML：查询对象不能混用](/assets/notes/ai-infra/nvml-objects.svg)](/assets/notes/ai-infra/nvml-objects.svg)

GPU handle、GI handle、CI handle 和 MIG device handle 表示不同层次的对象。`nvmlGpuInstanceGetComputeInstanceById` 从父 GI 查询 CI，因此其父对象使用 GI handle。[NVML API](https://docs.nvidia.com/deploy/nvml-api/latest/index.html)

## 2. 一个只读 Python 教学例

Python 包通常通过 `nvidia-ml-py` 分发，导入名为 `pynvml`。

```python
import pynvml

pynvml.nvmlInit()
try:
    for index in range(pynvml.nvmlDeviceGetCount()):
        h = pynvml.nvmlDeviceGetHandleByIndex(index)
        uuid = pynvml.nvmlDeviceGetUUID(h)
        try:
            m = pynvml.nvmlDeviceGetMemoryInfo(h)
            print(uuid, "used_GiB=", m.used / 1024**3,
                  "total_GiB=", m.total / 1024**3)
        except pynvml.NVMLError as exc:
            print(uuid, "memory query unavailable:", str(exc))
finally:
    pynvml.nvmlShutdown()
```

## 3. 根据当前模式与 Profile 枚举 MIG 实例 {#_3-mig-枚举不能依赖硬编码数字}

先确认设备支持和当前 MIG 模式，再查询可用 profile、GI/CI 及其 UUID。profile 枚举值、profile ID、创建出的 instance ID、设备索引是不同概念。“整卡时 id 一律填 0”“最多八张卡”“A30 只有两种 profile”都不应成为跨型号规则。

## 4. 监控能力的缺失也是信息

MIG 下某些 NVML 利用率接口可能返回不支持，`nvidia-smi` 显示 N/A 也不代表工作没有执行。进程显存、设备利用率、GI/CI 指标的支持范围不同，应该分别记录；需要更细的实体指标时转向 DCGM 等支持路径，而不是把整卡平均值按显存比例拆给实例。

## 5. 只读 GI/CI 查询的类型链

以 NVML R535 的 C 签名为参照，`nvmlDeviceGetGpuInstanceById` 接受 device handle 并返回 GI handle；`nvmlGpuInstanceGetComputeInstanceById` 再接受该 GI handle 并返回 CI handle。不要用 MIG device handle 或物理 GPU handle 替代第二步的父 GI。[NVML R535 MIG API](https://docs.nvidia.com/deploy/archive/R535/nvml-api/group__nvmlMultiInstanceGPU.html)

下面是 Python 绑定调用关系片段，未运行；`physical`、`gi_id`、`ci_id` 必须来自当前枚举结果，包签名也需核对，不是创建操作：

```python
gi = pynvml.nvmlDeviceGetGpuInstanceById(physical, gi_id)
ci = pynvml.nvmlGpuInstanceGetComputeInstanceById(gi, ci_id)
```

遇到 NOT_SUPPORTED、NO_PERMISSION、NOT_FOUND 等状态，分别检查能力、权限和实例是否已重建。重置或销毁后重新获取句柄，不能缓存旧 handle 无限重试。枚举 selector、返回的 profileId、GI/CI ID 和 UUID 仍要分别保存，不用一列“GPU id”混装。
