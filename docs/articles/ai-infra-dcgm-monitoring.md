---
id: ai-infra-dcgm-monitoring
title: 第 11 章 DCGM 与 Exporter：部署拓扑、实体与指标
description: "DCGM 提供 GPU 实体与性能字段的观测能力，Exporter 将相应指标暴露给监控系统。本章从部署拓扑开始，依次确定查询实体、字段含义、节点身份和采样窗口，使指标能够与实际任务对应。"
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

DCGM 提供 GPU 实体与性能字段的观测能力，Exporter 将相应指标暴露给监控系统。本章从部署拓扑开始，依次确定查询实体、字段含义、节点身份和采样窗口，使指标能够与实际任务对应。

## 1. 嵌入式与外部 hostengine 部署 {#_1-两种部署模式不要混搭成重复采集}

[![DCGM Exporter：hostengine 使用方式](/assets/notes/ai-infra/dcgm-deployment-modes.svg)](/assets/notes/ai-infra/dcgm-deployment-modes.svg)

Exporter 可以使用嵌入式 hostengine，或连接受管理的已有 hostengine；选择其一并记录实际进程与连接。外部模式通过 `-r Host:Port` 等受支持配置连接，需结合目标进程与连接关系确定实际采集拓扑。客户端 `libdcgm` 与服务端版本也要检查兼容，不只检查 exporter 镜像是否能启动。[DCGM Exporter 部署说明](https://docs.nvidia.com/datacenter/cloud-native/gpu-telemetry/latest/dcgm-exporter.html)

DCGM（Data Center GPU Manager，数据中心 GPU 管理器）发现实体、采样字段并维护数据。客户端通过 `libdcgm` 使用接口。Embedded 模式由 Exporter 在自身进程内启动和停止引擎；External 模式下 `nv-hostengine` 独立运行，Exporter 通过客户端连接，重启 Exporter 不会重启该服务。客户端库版本宜与服务端相同，至少核对 NVIDIA 对客户端不低于服务端的建议和具体兼容性。重复部署可能增加轮询及硬件计数器竞争。

Exporter 将数据暴露到 HTTP `/metrics`，Prometheus 周期抓取和保存时序，Grafana 查询 Prometheus 绘图。沿用[第 10 章](/articles/ai-infra-nvml.html)的 A、B 服务，先把两者映射到节点、GPU UUID 和实例，再对齐 A 延迟升高的时间段。长期采样可以缩小调查范围，具体请求仍要看时间线。

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

本节实验固定 DCGM **4.2.3** 与 Exporter **4.1.1**。下表中的 C 常量为该版头文件名称，也是本例 CSV 使用的 Exporter 指标名。只有字段被配置、实体支持且采集成功，才以 `/metrics` 中实际出现的名称为准。

| Field ID | C 常量 / CSV 指标名               | 阅读口径                                     | 单位  |
| -------: | --------------------------------- | -------------------------------------------- | ----- |
|     1001 | `DCGM_FI_PROF_GR_ENGINE_ACTIVE`   | 采样区间中图形或计算引擎活跃的时间比例       | ratio |
|     1002 | `DCGM_FI_PROF_SM_ACTIVE`          | 至少有一个活跃 warp 的周期比例，在 SM 间平均 | ratio |
|     1003 | `DCGM_FI_PROF_SM_OCCUPANCY`       | 常驻 warp 数相对理论最大值，按经过周期归一   | ratio |
|     1004 | `DCGM_FI_PROF_PIPE_TENSOR_ACTIVE` | Tensor 管线活跃周期相对持续经过周期          | ratio |
|     1005 | `DCGM_FI_PROF_DRAM_ACTIVE`        | 设备显存接口收发活跃周期占比                 | ratio |
|      252 | `DCGM_FI_DEV_FB_USED`             | 当前实体报告的 framebuffer 已用容量          | MiB   |

`dcgmi profile -l` 的列标签可能省略 `DCGM_FI_`，按数值 ID 交叉核对。新版 DCGM 头文件把 1001 和 1002 的主名称分别写作 `DCGM_FI_PROF_GR_ENGINE_UTIL_RATIO` 和 `DCGM_FI_PROF_SM_UTIL_RATIO`，并保留旧 C 名称为别名。ID 相同并不意味着旧版 Exporter 接受新版名称，也不保证 Prometheus 序列改名。Profiling 字段需按设备、驱动、实体和兼容组验证。整卡支持不代表 GI 或 CI 支持同一字段。FB Used 也要确认采集的是整卡还是实例。 [DCGM v4.2.3 头文件](https://raw.githubusercontent.com/NVIDIA/DCGM/v4.2.3/dcgmlib/dcgm_fields.h) · [新版 DCGM 头文件](https://github.com/NVIDIA/DCGM/blob/master/dcgmlib/dcgm_fields.h)

假设 80 个 SM 中 20 个在整个窗口内始终有活跃 warp，其余为空，SM Active 约为 25%。等待访存的 warp 仍可能计入活跃。该值无法推出峰值算力效率、Tensor 管线活跃度或显存带宽。NVML GPU Utilization 则按设备采样窗口中是否有 kernel 执行计时，其分母也与 SM Active 不同。

## 3. 查询实体，再选字段

只读查询示例，假定服务已配置：

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

### 单节点实验

在具备支持的 NVIDIA GPU、Linux、Docker、Container Toolkit 的实验节点运行。宿主安装并启动 DCGM 4.2.3 的独立 `nv-hostengine`，让本机客户端可以连接默认 5555 端口。先核对版本与目标设备。

```bash
nvidia-smi
dcgmi --version
dcgmi discovery -l
dcgmi discovery -c
dcgmi profile -l -i 0
```

`-l` 在 discovery 中列出实体，`-c` 输出层级信息以核对 MIG，`profile -l -i 0` 查询 DCGM GPU ID 0 可采集的 profiling 组合。若该设备不是目标，换成 discovery 得到的 ID。将上面的 CSV 保存为 `collectors.csv`，先验证温度与 FB Used，再在明确支持时添加 `DCGM_FI_PROF_SM_ACTIVE, gauge, SM active ratio.`。

以下走同一节点的外部引擎路径，使用 host network 连接本机引擎，HTTP 只监听回环地址。该发布版的 `-r` 选择外部引擎，`-a` 设置 HTTP 监听地址，`-f` 指定 CSV，`-c 5000` 将采集间隔设为 5000 毫秒。可用相同镜像的 `--help` 复核。Profiling 权限由执行采集的 Hostengine 侧配置，先按现有权限测试并核对日志，避免给 Exporter 默认添加 `--privileged`。

```bash
image=nvcr.io/nvidia/k8s/dcgm-exporter:4.2.3-4.1.1-ubuntu22.04
docker run --rm "$image" --help
docker run --rm --gpus all --network host \
  --mount "type=bind,source=$PWD/collectors.csv,target=/tmp/collectors.csv,readonly" \
  "$image" -r 127.0.0.1:5555 -a 127.0.0.1:9400 -f /tmp/collectors.csv -c 5000
```

在另一个终端运行 `curl -fsS http://127.0.0.1:9400/metrics`。成功标准是看到目标 UUID 和支持的有效字段。若有 N/A、哨兵值或缺系列，查 Exporter 日志和 DCGM 字段支持，而不是填 0。将以下 job 加入运行在同一宿主网络的 Prometheus：

```yaml
scrape_configs:
  - job_name: dcgm-lab
    scrape_interval: 30s
    static_configs:
      - targets: ["127.0.0.1:9400"]
        labels:
          node: gpu-lab
```

检查 Prometheus Targets 和 `up{job="dcgm-lab"}`，在 Grafana 以 Prometheus 为数据源绘制 `DCGM_FI_DEV_FB_USED`，再对照已知 GPU UUID 上持续超过抓取周期的受控负载与空闲期。若已验证 SM 字段可用，同时查看 SM Active 与业务负载时间戳。配置和预期基于[固定 Exporter 发布版](https://github.com/NVIDIA/dcgm-exporter/releases/tag/4.2.3-4.1.1)、[该版 CLI 源码](https://github.com/NVIDIA/dcgm-exporter/blob/4.2.3-4.1.1/pkg/cmd/app.go)和 [DCGM 4.2.3 CLI 源码](https://github.com/NVIDIA/DCGM/blob/v4.2.3/dcgmi/CommandLineParser.cpp)，当前待实测。

## 4. 逐节点发现并保留设备身份标签 {#_4-按节点监控-不能只依赖一个共享-service-名}

[![逐节点抓取：不要把 Service 名当节点身份](/assets/notes/ai-infra/dcgm-node-targets.png)](/assets/notes/ai-infra/dcgm-node-targets.png)

DaemonSet 可以在多个 GPU 节点运行 exporter。普通多 endpoint Service 代表一组后端，一次连接可能选到其中一个。应通过监控发现逐个抓取目标，并保留 node、UUID、GI/CI 等对应标签；具体标签由 exporter 和发现配置决定。[Kubernetes Service](https://kubernetes.io/docs/concepts/services-networking/service/)

观察 node-a 时，应先核对 endpoint、目标身份和返回标签。若连续两次 Service 请求拿到的是不同 GPU 的数据，将它们连成一条曲线就会产生虚假的波动；直接相加整卡与其子实体的数据，也会造成重复计数。

Kubernetes 中可用 DaemonSet 为每个 GPU Node 创建 Exporter Pod，以 PodMonitor 逐 Pod 发现，或用 ServiceMonitor 发现 Service 背后的各 Endpoint。每个目标都有独立地址，发现时把 Pod 所在 Node 映射为 `node` target label。图右侧的风险特指把负载均衡 Service 地址当作唯一静态目标。机房和机柜是可选拓扑标签；GPU、GI、CI 才是此处的 DCGM 设备实体。

例如 GPU A 有 GI 3 和 GI 5，分别含 CI 0。用 `dcgmi discovery -c` 建立父子映射。Exporter 的设备选择和字段支持共同决定采集对象。用本机 `/metrics` 中的 `UUID` 与实际出现的 `GPU_I_ID` 等标签关联实例，以 `node` 保留宿主身份。CI ID 从发现结果关联，只有实际输出提供 CI 标签时才用它做 PromQL 过滤。Pod 标签若有，表示工作负载归属，不能取代节点与 GPU 身份。每张图表固定整卡或子实体粒度，避免父子重复计算。MIG 重建后重新发现映射，避免把复用的实例 ID 接到旧时序。

## 5. 四层时间与两类扰动

应分别记录硬件字段的采样/watch、exporter 更新、Prometheus scrape 和查询聚合窗口。每 1 秒更新、每 30 秒抓取，并不能获得完整的 1 秒历史序列。是否需要滚动更新取决于部署和配置加载方式，“两次重启”并不是采样周期的固有要求。

profiling counters 可能受采集权限、组合限制或多工具竞争影响；DCGM 复用某些字段也不能等同于 Nsight Compute 对应用的 replay。先无采集测业务基线，再短时选择少量指标，比较吞吐、尾延迟和资源开销。

### 三秒突发为什么看不见

假设 Watch 每 1 秒采样，Exporter 每 5 秒取当时最新值，Prometheus 每 30 秒抓取。若突发发生在第 6 到 9 秒，Watch 可能记录第 7、8、9 秒的活跃样本，但 Exporter 在第 5、10 秒取到的都可能是空闲值。即使某次 Exporter 捕获了峰值，它也可能在下一次 30 秒抓取前被更新覆盖。这个例子只描述一种相位和最新值读取方式。三个周期是教学假设，实际 Watch 与 Exporter 是否有独立时钟，要看部署版本和配置。查询端无法恢复未保存的样本。

- 0 表示采到有效零值；N/A 表示字段无有效值；缺系列可能是字段未配置或不支持；目标失联用 `up=0` 等证据判断，目标被移除时 `up` 自身也可能不存在。
- `rate()` 用于单调递增的 counter，在窗口内估计每秒速率并处理重置。SM Active 属于 gauge，应用 `avg_over_time()` 等函数对已经抓到的样本求平均。该函数对窗口内样本等权，不恢复缺失的峰值。[Prometheus 查询函数](https://prometheus.io/docs/prometheus/latest/querying/functions/)

### 协调性能计数器

Profiling Counter 是硬件提供的活动计数资源。若所选字段不能同时采，DCGM 可能按组复用计数器，时间分辨率会受影响。Nsight Compute Replay 则可能重跑 kernel 收集不同组，带来执行和缓存扰动。两者还可能竞争设备计数器，具体取决于 GPU、驱动、权限和所选工具功能。

在隔离实验节点或协调过的窗口中，先记录目标 Hostengine 和正在使用的 profiling 字段，核对 `dcgmi profile --help` 和 Nsight 所需权限。仅当确认需要时，在连接同一 Hostengine 的客户端执行 `dcgmi profile --pause`，短时采集后执行 `dcgmi profile --resume`。Pause 影响整个目标 Hostengine 的 profiling 采集，不应作为业务节点的无影响操作。为异常退出设置清理步骤或 shell trap；若进程被强杀，安排另一操作者手动恢复。最后检查 profiling 字段重新产生有效样本，并标注空窗。[DCGM Profiling](https://docs.nvidia.com/datacenter/dcgm/latest/learn/modules/profiling.html)

如果 A 的延迟仍无法从实体级趋势解释，转到[第 12 章](/articles/ai-infra-performance-profiling.html)定位请求关键路径。
