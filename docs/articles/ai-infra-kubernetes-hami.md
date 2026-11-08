---
id: ai-infra-kubernetes-hami
title: 第 16 章 Kubernetes GPU 资源与 HAMi 调度链
description: "Kubernetes 的 GPU 工作负载要经过资源上报、节点与设备选择、分配配置和容器执行。设备插件、调度扩展及运行时分别承担这些环节；显存、拓扑或算力配额是否受管理，取决于启用的组件与策略。"
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
order: 16
---

# 第 16 章 Kubernetes GPU 资源与 HAMi 调度链

Kubernetes 的 GPU 工作负载要经过资源上报、节点与设备选择、分配配置和容器执行。设备插件、调度扩展及运行时分别承担这些环节；显存、拓扑或算力配额是否受管理，取决于启用的组件与策略。

## 1. 设备插件的注册、健康上报与分配 {#_1-普通设备插件负责什么}

设备插件向 kubelet 注册并上报设备健康状态，kubelet 据此发布扩展资源；容器准备阶段再进行设备分配和相应运行配置。`nvidia.com/gpu: 1` 在普通整卡模式中是设备资源请求，不能直接解释为“1% GPU”。NVIDIA 插件还提供 MIG、time-slicing、MPS 等有各自条件的共享模式。[NVIDIA Kubernetes Device Plugin](https://github.com/NVIDIA/k8s-device-plugin)

普通 NVIDIA 整卡插件的生命周期如下。

1. Device Plugin（设备插件）在节点启动 gRPC 服务，向 kubelet 注册扩展资源名，例如 `nvidia.com/gpu`。扩展资源按整数请求，普通整卡模式中一个单位代表一块设备。
2. kubelet 通过 `ListAndWatch()` 接收设备 ID 与健康变化，更新 Node 的 Capacity（总容量）与 Allocatable（可供调度的容量）。设备变为不健康时，Allocatable 可下降，而 Capacity 不必改变。已分配 Pod 不因此自动迁移。
3. Pod 申请扩展资源，kube-scheduler（调度器）结合节点可分配量、已承诺请求及其他约束选节点。Allocatable 也包含已承诺给其他 Pod 的部分，查看剩余量要扣除现有请求。
4. Pod 绑定后，目标 kubelet 在容器准备阶段选设备 ID，调用插件 `Allocate()`。插件返回设备配置、环境变量、挂载等运行所需信息。Container Runtime（容器运行时）按 kubelet 请求创建并启动容器。

Device Plugin 负责节点设备登记与分配协作。调度器负责选节点。设备的拓扑提示也可供 kubelet 的 Topology Manager 参考。[Kubernetes Device Plugins](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)

## 2. HAMi 把调度与容器内控制分开

[![HAMi：调度、分配与就绪的边界](/assets/notes/ai-infra/hami-scheduling.svg)](/assets/notes/ai-infra/hami-scheduling.svg)

图示按典型架构解释各阶段，具体函数顺序需查对应提交。Webhook 修改有关 Pod 配置；调度组件结合节点/设备状态选择位置；kubelet 与设备插件准备设备及注入配置；容器内控制层落实对应策略。Pod 已绑定节点，不意味着镜像、设备配置和业务启动都成功。

HAMi（Heterogeneous AI Computing Virtualization Middleware，异构 AI 计算虚拟化中间件）在传统设备插件链上增加设备维度的选择与用户态限制。以 v2.10.0 Chart 的 NVIDIA HAMi-core 路径为例：

| 阶段       | 组件与交接                                                                                                                                                                                                                                                                                                     |
| ---------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 准入       | Mutating Webhook（变更准入 Webhook）识别需要管理的 Pod，按配置补充设备字段及 `schedulerName`，Chart 默认值是 `hami-scheduler`。这使 Pod 进入配置了 Extender 的调度器。显式指定其他调度器时，Webhook 可按条件跳过修改                                                                                           |
| 筛选与记账 | Scheduler Extender（调度扩展器）结合节点和物理 GPU UUID 的槽位、显存、算力、健康及策略筛选。选定节点后，正常分配路径在调度缓存与配额管理中登记用量，并写入 Pod Annotation（注解） `hami.io/vgpu-devices-allocated` 和 `hami.io/vgpu-devices-to-allocate`。注解包含设备及容器分配元数据，写入失败有相应清理路径 |
| 绑定       | Extender 的 Bind 阶段申请节点锁、更新分配阶段，再向 API Server 提交 Pod Binding。绑定本身尚未启动容器                                                                                                                                                                                                          |
| 节点分配   | kubelet 调用 NVIDIA HAMi Device Plugin 的 `Allocate()`。该插件在节点串行化相关分配步骤，定位待分配 Pod、消费相应设备请求并生成 AllocateResponse                                                                                                                                                                |
| 容器执行   | 在非 MIG 路径，插件配置 `CUDA_DEVICE_MEMORY_LIMIT_<index>`、`CUDA_DEVICE_SM_LIMIT`，挂载 `libvgpu.so`、共享账本位置和启用控制时的 `/etc/ld.so.preload`。运行时落实这些配置，进程启动后加载 HAMi-core，受覆盖的调用才进入控制逻辑                                                                               |

绑定后仍可能因设备数不匹配、插件失败、运行时注入失败、驱动不兼容或模型内存不足而无法启动。分配注解是组件协议，运维观察应读取而非手工补写。[v2.10.0 调度源码](https://github.com/Project-HAMi/HAMi/blob/v2.10.0/pkg/scheduler/scheduler.go) · [Webhook 源码](https://github.com/Project-HAMi/HAMi/blob/v2.10.0/pkg/scheduler/webhook.go) · [NVIDIA 请求和注解源码](https://github.com/Project-HAMi/HAMi/blob/v2.10.0/pkg/device/nvidia/device.go) · [节点 Allocate 源码](https://github.com/Project-HAMi/HAMi/blob/v2.10.0/pkg/device-plugin/nvidiadevice/nvinternal/plugin/server.go)

## 3. 一个明确标版本的资源片段

以下依据 HAMi v2.10.0 文档，仅为容器资源字段片段，不是完整可部署 Pod；本次没有安装 HAMi，也没有提交资源。

```yaml
resources:
  limits:
    nvidia.com/gpu: 1
    nvidia.com/gpumem: 3000
    nvidia.com/gpucores: 50
```

在默认 `memoryFactor: 1` 下，`gpumem: 3000` 表示每个申请设备的 3000 MiB 配额，使用普通整数，不附 `Mi`/`Gi`。字段和单位取决于版本及配置，不能直接套到普通 NVIDIA 插件。[HAMi 显存分配](https://project-hami.io/docs/v2.10.0/userguide/nvidia-device/specify-device-memory-usage)

`gpucores` 也不能解释为“独占一半 SM”，而是代表限制的算力。[HAMi core usage](https://project-hami.io/docs/v2.10.0/userguide/nvidia-device/specify-device-core-usage)

| 字段                           | v2.10.0 教学口径                                                                                    |
| ------------------------------ | --------------------------------------------------------------------------------------------------- |
| `nvidia.com/gpu`               | 申请几个设备分配单位。节点登记的是共享槽位，本例请求一张物理 GPU 上的一个单位。多卡请求逐卡计算资源 |
| `nvidia.com/gpumem`            | 使用普通整数。默认 `memoryFactor: 1` 下是每张申请卡的 MiB，源码在读取正值后按配置因子换算           |
| `nvidia.com/gpumem-percentage` | 按候选卡登记容量计算百分比。应用配置应与绝对值二选一，源码在绝对请求为正时优先使用绝对值            |
| `nvidia.com/gpucores`          | 调度与后端使用的计算资源限制参数。`50` 不承诺独占 SM 或实际吞吐                                     |
| `deviceSplitCount`             | 每张物理卡的逻辑分配槽数，v2.10.0 Chart 默认值为 10。空余显存不能补偿槽位耗尽                       |

假设两卡登记容量均为 24 GiB，GPU 0 已承诺 8 GiB，GPU 1 已承诺 16 GiB。新 Pod 请求 12 GiB（12288 MiB）时，两卡分别剩 16 GiB 和 8 GiB。仅 GPU 0 通过显存检查。算力、槽位、健康、设备类型、命名空间配额和策略仍可能使 GPU 0 不可用。这里的“已承诺”来自调度账本，和 NVML 实时物理占用分别观察。[v2.10.0 Chart 默认值](https://github.com/Project-HAMi/HAMi/blob/v2.10.0/charts/hami/values.yaml)

## 4. Binpack、Spread 与拓扑

binpack 倾向于集中资源，便于保留空卡；spread 倾向于分散资源，可以减少部分争抢，但也可能增加碎片。多卡任务还需考虑 NUMA、PCIe 和 NVLink 连接。

假设节点 A 两张卡分别已分配 12 和 0 GiB，节点 B 分别为 4 和 0 GiB。新请求为 6 GiB，其他条件相同。Node Binpack（节点集中）倾向更忙的 A，Node Spread（节点分散）倾向 B。在 A 内，GPU Binpack 倾向填进已有任务的卡，保留一张空卡；GPU Spread 倾向空卡，可能减少同卡争用，但两张卡都留下较小空余块。分数是多维策略结果，这里只展示方向。

v2.10.0 Chart 默认节点 binpack、设备 spread。通过 `scheduler.defaultSchedulerPolicy.nodeSchedulerPolicy`、`gpuSchedulerPolicy` 配置默认值，Pod 的 `hami.io/node-scheduler-policy` 与 `hami.io/gpu-scheduler-policy` 可覆盖。NUMA-aware 指优先选择合适的非一致内存访问节点，多 GPU 通信还受 PCIe、NVLink 和实际链路影响。v2.10.0 NVIDIA 路径区分 Pod 的 `nvidia.com/numa-bind` 设备选择约束、`enableNumaTopology` 对 kubelet 提供的拓扑信息，以及 GPU 链路拓扑策略。先查实际开启的配置与设备组合，不能用同 NUMA 直接推断有 NVLink，也不能用 Spread 推断更低延迟。[HAMi v2.10.0 调度策略](https://project-hami.io/docs/v2.10.0/userguide/nvidia-device/scheduling-policy)

## 5. 按阶段排查 Pending 和启动失败

先检查 admission 是否生效，再看调度事件和资源余量；绑定后则转向设备插件、runtime、注入库及应用错误。不要把 admission 成功、绑定成功、分配成功、资源限制有效当作同一个验收结果。对 Kubernetes 1.28 的复盘，保持设备插件/调度扩展语境，不把新版本 DRA 能力写成当年的默认行为。

下表按实际发生的阶段排查。示例变量替换为已获读取权限的目标，不创建或修改集群对象。

```bash
kubectl -n "$namespace" get pod "$pod" -o yaml
kubectl -n "$namespace" describe pod "$pod"
kubectl get events -A
kubectl describe node "$node"
kubectl -n "$namespace" logs "$pod" -c "$container"
```

| 阶段                  | 现象与证据                                      | 下一步                                           |
| --------------------- | ----------------------------------------------- | ------------------------------------------------ |
| Admission             | 创建被拒绝，或持久化 Pod 缺预期 `schedulerName` | 看 API 错误、Webhook 匹配条件及最终 Pod spec     |
| Scheduling            | Pending、`FailedScheduling`                     | 对照节点 Allocatable、当前请求、健康和 HAMi 账本 |
| Bind                  | 无 `spec.nodeName` 或分配阶段停滞               | 检查 Extender 事件、注解、节点锁与 API 权限      |
| Device Allocate       | 已绑定，容器未启动，设备分配报错                | 查看 kubelet、目标节点设备插件及待消费分配信息   |
| Container Runtime     | 创建容器报错                                    | 核对 runtime、挂载、设备可见性和镜像依赖         |
| CUDA Initialization   | 容器启动，CUDA 初始化或分配报错                 | 核对可见 GPU、驱动、实际加载的 Hook 及有效限制   |
| Application Readiness | Pod Running，但 Ready 为 False 或服务不达标     | 查 readiness、模型加载、业务错误、吞吐与延迟     |

## 6. 调度控制面与节点执行面分开读

[![HAMi：控制面与节点执行面](/assets/notes/ai-infra/hami-control-node.svg)](/assets/notes/ai-infra/hami-control-node.svg)

| 阶段                | 应检查的证据                   | 成功后仍未证明         |
| ------------------- | ------------------------------ | ---------------------- |
| Admission           | 返回变更与最终 Pod 配置        | 一定有可用 GPU         |
| 节点/设备选择与绑定 | 调度事件、分配元数据与节点     | Allocate 必定成功      |
| Allocate            | 设备、库和环境等分配结果       | 应用 CUDA 初始化成功   |
| 容器执行            | 真实库路径、限制效果和业务输出 | 已达到硬隔离或性能 SLO |

`/etc/ld.so.preload` 文件与 `LD_PRELOAD` 环境变量是不同注入入口。

## 7. DRA 的版本边界

DRA（Dynamic Resource Allocation，动态资源分配）使用 DeviceClass 定义可选择的设备类别，ResourceClaim 描述工作负载的设备请求和分配结果，ResourceSlice 发布驱动发现的设备及属性。它把设备选择和声明纳入结构化 API，传统 Device Plugin 的整数扩展资源则由 kubelet 注册并在节点调用 Allocate。Kubernetes 1.34 中核心 DRA API `resource.k8s.io/v1` 达到稳定；后续扩展功能各有独立阶段。原 Kubernetes 1.28 实验使用传统 Device Plugin 与 Extender。HAMi-DRA 是另一个驱动和调度集成路径，采用时独立核对版本与部署条件。[Kubernetes DRA](https://kubernetes.io/docs/concepts/resource-management/dynamic-resource-allocation/) · [HAMi-DRA](https://github.com/Project-HAMi/HAMi-DRA)

本例的 3000 MiB 与 50 会传给运行时控制层。哪些 API 受控、配额是否可靠、模型是否能载入仍需分别验证，见[第 17 章](/articles/ai-infra-hami-core.html)和[第 18 章](/articles/ai-infra-training-inference-finetuning.html)。
