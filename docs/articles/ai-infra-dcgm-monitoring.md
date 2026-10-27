---
id: ai-infra-dcgm-monitoring
title: 第 11 章 DCGM 与 Exporter：部署拓扑、实体与指标
description: 本章先介绍指标来源，再说明如何避免将其他节点或整卡的数据误归到某个任务。
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
order: 11
---

# 第 11 章 DCGM 与 Exporter：部署拓扑、实体与指标

本章先介绍指标来源，再说明如何避免将其他节点或整卡的数据误归到某个任务。

## 1. 两种部署模式不要混搭成重复采集

[![DCGM Exporter：hostengine 使用方式](/assets/notes/ai-infra/dcgm-deployment-modes.svg)](/assets/notes/ai-infra/dcgm-deployment-modes.svg)

Exporter 可以使用嵌入式 hostengine，或连接受管理的已有 hostengine；选择其一并记录实际进程与连接。外部模式通过 `-r Host:Port` 等受支持配置连接，不能继续写成“DCGM 与 exporter 一律不能并存”。客户端 `libdcgm` 与服务端版本也要检查兼容，不只检查 exporter 镜像是否能启动。[DCGM Exporter 部署说明](https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/latest/dcgm-exporter.html)

## 2. 指标字典：实体、分母和单位一起读

| 字段示例                | 主要含义                         | 常见单位/范围          | 不能替代               |
| ----------------------- | -------------------------------- | ---------------------- | ---------------------- |
| PROF_GR_ENGINE_ACTIVE   | 相关引擎在区间内的活跃程度       | 比例 0—1               | 所有算术单元的峰值效率 |
| PROF_SM_ACTIVE          | SM 活跃的空间/时间聚合           | 比例 0—1               | 常驻 warp 数           |
| PROF_SM_OCCUPANCY       | 常驻 warp 相对支持上限的时间平均 | 比例 0—1               | 每周期发射效率         |
| PROF_PIPE_TENSOR_ACTIVE | 相应 Tensor 管线活跃             | 比例 0—1               | 模型 Tensor FLOP/s     |
| PROF_DRAM_ACTIVE        | DRAM 相关活动周期比例            | 比例 0—1               | 显存容量或直接字节带宽 |
| DEV_FB_USED             | 已用 framebuffer 容量            | 依该字段定义，常为 MiB | 活跃计算比例           |

字段可用性取决于设备、驱动、DCGM 与实体范围。采集到的 N/A、未支持或无效状态必须保留，不转换成业务利用率 0。若需要 bytes/s，查询实际传输计数字段及其单位，不能把 DRAM_ACTIVE 直接乘一个宣传峰值当作实测带宽。[DCGM 字段与功能说明](https://docs.nvidia.com/datacenter/dcgm/latest/user-guide/feature-overview.html)

## 3. 查询实体，再选字段

只读查询示例，假定服务已配置，未执行：

```bash
dcgmi discovery -l
dcgmi discovery -c
dcgmi profile -l -i 0
```

区分物理 GPU、GI、CI 的 entity；重建 MIG 后重新发现 ID。`stats` 的作业统计与 `dmon` 的字段观察不是互为必要前置，也不保证支持所有 MIG 指标。配置 CSV 时检查字段支持，避免只复制旧截图里的编号。

```text
DCGM_FI_DEV_GPU_TEMP, gauge, GPU temperature (C).
DCGM_FI_DEV_FB_USED, gauge, Framebuffer used (MiB).
```

## 4. 按节点监控，不能只依赖一个共享 Service 名

[![逐节点抓取：不要把 Service 名当节点身份](/assets/notes/ai-infra/dcgm-node-targets.png)](/assets/notes/ai-infra/dcgm-node-targets.png)

DaemonSet 可以在多个 GPU 节点运行 exporter。普通多 endpoint Service 代表一组后端，一次连接可能选到其中一个。应通过监控发现逐个抓取目标，并保留 node、UUID、GI/CI 等对应标签；具体标签由 exporter 和发现配置决定。[Kubernetes Service](https://kubernetes.io/docs/concepts/services-networking/service/)

观察 node-a 时，应先核对 endpoint、目标身份和返回标签。若连续两次 Service 请求拿到的是不同 GPU 的数据，将它们连成一条曲线就会产生虚假的波动；直接相加整卡与其子实体的数据，也会造成重复计数。

## 5. 四层时间与两类扰动

应分别记录硬件字段的采样/watch、exporter 更新、Prometheus scrape 和查询聚合窗口。每 1 秒更新、每 30 秒抓取，并不能获得完整的 1 秒历史序列。是否需要滚动更新取决于部署和配置加载方式，“两次重启”并不是采样周期的固有要求。

profiling counters 可能受采集权限、组合限制或多工具竞争影响；DCGM 复用某些字段也不能等同于 Nsight Compute 对应用的 replay。先无采集测业务基线，再短时选择少量指标，比较吞吐、尾延迟和资源开销。
