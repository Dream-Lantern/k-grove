---
id: kubernetes-dra
title: 第三十二章 DRA：版本边界与设备分配
description: "Dynamic Resource Allocation 尝试通过资源申领与驱动协作来表达更复杂的设备需求。安装一个插件，并不会让所有硬件自动具备相同的分区和共享能力。"
date: '2026-10-25'
updated: '2026-10-28'
category: engineering
type: explanation
tags:
  - kubernetes
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kubernetes
series: kubernetes-learning
order: 32
---

# 第三十二章 DRA：版本边界与设备分配

> 本册主线是 Kubernetes 1.28。本章分别介绍早期 DRA 模型与后续结构化模型，使用时需匹配 API、门控与驱动版本。

## 1. 先确定讨论的是哪一代模型

DRA（Dynamic Resource Allocation，动态资源分配）尝试通过资源申领与驱动协作来表达更复杂的设备需求。安装一个插件，并不会让所有硬件自动具备相同的分区和共享能力。

1.28 的官方说明将 DRA 标为默认关闭的 Alpha，使用时需显式启用相关能力，并具备匹配的 API 与资源驱动。

[![DRA 先分版本，再讨论对象与分配流程](/assets/notes/kubernetes/k8s-dra-version-boundary.svg)](/assets/notes/kubernetes/k8s-dra-version-boundary.svg)

| 项目          | Kubernetes 1.28                                                           | Kubernetes 1.32                                                      |
| ------------- | ------------------------------------------------------------------------- | -------------------------------------------------------------------- |
| 模型          | 经典 DRA，驱动参与分配协调                                                | 结构化设备模型，调度器依据设备信息分配                               |
| 资源 API 示例 | resource.k8s.io/v1alpha2                                                  | resource.k8s.io/v1beta1                                              |
| 代表对象      | ResourceClass、ResourceClaim、ResourceClaimTemplate、PodSchedulingContext | DeviceClass、ResourceSlice、ResourceClaim、ResourceClaimTemplate     |
| 成熟度        | Alpha，默认关闭                                                           | 整体 Feature Gate 为 Beta、默认关闭；具体类型注释与附加门控见第 3 节 |
| 启用要求      | DRA 门控、对应 API、匹配驱动与调度插件                                    | 对应版本门控、API、驱动；不能照搬旧版安装参数                        |
| 调度协作      | 借助 PodSchedulingContext 与驱动交互                                      | 根据 ResourceSlice 和结构化选择条件，不沿用旧协商链                  |

资源 API 的版本号、特性门控成熟度和节点 gRPC 协议版本是不同维度。`v1beta1` 不能单独证明某类型已经 Beta、GA 或默认启用。

## 2. 1.28：ResourceClass 与早期协调模型

1.28 文档中的 `resource.k8s.io/v1alpha2` 包含 ResourceClass、ResourceClaim、ResourceClaimTemplate 和 PodSchedulingContext 等对象。

| 对象                  | 职责与常见创建者                                         |
| --------------------- | -------------------------------------------------------- |
| ResourceClass         | 关联驱动与公共参数，通常由管理员随驱动安装创建；集群范围 |
| ResourceClaim         | 表达具体需求并记录分配结果，可由用户管理；命名空间范围   |
| ResourceClaimTemplate | 定义 Claim 模板，控制平面可为不同 Pod 创建独立 Claim     |
| PodSchedulingContext  | 协调 Scheduler 与资源驱动的候选节点信息，不是设备目录    |

参数可以引用驱动定义的独立对象，Kubernetes 不负责解释任意厂商参数。多个 Pod 直接引用同一个 Claim 时共享的是该申领；是否允许多消费者、底层如何共享仍受分配结果和驱动限制，不能推成硬件任意共享。

### 启用条件与只读检查

1. kube-apiserver 开启 `DynamicResourceAllocation=true`，并通过 `--runtime-config=resource.k8s.io/v1alpha2=true` 显式服务对应 API 组/版本。
2. kube-scheduler、kube-controller-manager 和 kubelet 也开启该 Feature Gate。
3. 安装匹配的资源驱动，包括相应控制面分配逻辑与节点服务。
4. 默认 v1 Scheduler 配置会在门控启用时加入 DynamicResources 插件；自定义调度配置还要检查是否禁用了它，以及相关扩展点是否保留。

这些是配置核对项，不是让读者直接修改现有集群的操作指令。仅打开 API 不代表调度、分配和节点准备已可用。[1.28 启用条件](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/scheduling-eviction/dynamic-resource-allocation.md)、[默认调度插件](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/scheduler/apis/config/v1/default_plugins.go)。

```bash
kubectl get resourceclasses
kubectl get resourceclaims -n study
kubectl get podschedulingcontexts -n study
```

API 存在但没有对象时，可能返回 `No resources found`；未服务该资源类型时，可能提示 `the server doesn't have a resource type`。403 则先检查查询权限，不能把所有报错都当成 API 未启用。查询成功也不能证明驱动正常。

### Claim 与容器的引用关系

以下是 **1.28 合成结构示例，未提交**，假定 study 已存在、虚构驱动 `resource-driver.example.com` 已正确安装；未包含驱动部署或自定义参数配置，不代表可用的 GPU 安装方案。

```yaml
apiVersion: resource.k8s.io/v1alpha2
kind: ResourceClass
metadata:
  name: example-gpu
driverName: resource-driver.example.com
---
apiVersion: resource.k8s.io/v1alpha2
kind: ResourceClaim
metadata:
  name: catalog-gpu
  namespace: study
spec:
  resourceClassName: example-gpu
  allocationMode: WaitForFirstConsumer
---
apiVersion: v1
kind: Pod
metadata:
  name: catalog-dra
  namespace: study
spec:
  resourceClaims:
    - name: gpu
      source:
        resourceClaimName: catalog-gpu
  containers:
    - name: app
      image: busybox:1.36.1
      command: ["sleep", "3600"]
      resources:
        claims:
          - name: gpu
```

`PodSpec.resourceClaims` 声明 Pod 引用的 Claim；`Container.resources.claims` 用 Pod 内局部名 gpu 指定该容器使用哪个引用。两处名称要一致。1.28 的来源位于 `source.resourceClaimName` 或 `source.resourceClaimTemplateName`，不能直接复制 1.32 的扁平字段。[v1.28.0 Pod 字段](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/core/v1/types.go)

### WaitForFirstConsumer：先协调，再绑定

Immediate 表示 Claim 创建后即可启动分配，不等待具体 Pod；WaitForFirstConsumer 表示等实际消费者出现后再与调度协调，它是 1.28 的默认 allocationMode。[默认值实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/apis/resource/v1alpha2/defaults.go)

合成案例：Node A 和 B 都有 GPU，也都通过初步 CPU/内存等检查，但驱动按本例既定资源条件判断 A 不满足、B 满足。这里没有真实硬件测试，也不假定 Scheduler 能自行理解厂商参数。

[![1.28 经典 DRA：候选节点与 Claim 分配协作](/assets/notes/kubernetes/k8s-dra-classic-scheduling.svg)](/assets/notes/kubernetes/k8s-dra-classic-scheduling.svg)

1. 创建 Claim，Pod 引用它；Scheduler 检查尚未分配的 Claim，形成候选节点。
2. Scheduler 创建或更新 PodSchedulingContext，在 `spec.potentialNodes` 中提供候选 A、B。
3. 资源驱动评估资源条件，在 `status.resourceClaims[].unsuitableNodes` 中反馈 A 不适合。
4. Scheduler 综合其他要求，选择 B，并写入 `spec.selectedNode`。这还不是 Pod 已绑定。
5. 驱动为 B 完成 Claim 分配，记录 `status.allocation`；协调过程中还要为 Pod 保留 Claim 的使用资格。
6. 所有所需 Claim 分配并为该 Pod 保留后，正常调度才继续完成 Pod 绑定；随后 kubelet 准备节点设备和容器配置。

图示是成功分支的主要关系，实际是多轮异步协调，可能失败、重试或换候选节点。PodSchedulingContext 不是一次函数返回，也不能因为 Claim 分配成功就承诺节点准备一定成功。手动设置 `spec.nodeName` 会绕过 Scheduler，不是这条正常路径。[1.28 分配说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/scheduling-eviction/dynamic-resource-allocation.md)、[v1.28.0 对象字段](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/api/resource/v1alpha2/types.go)、[DynamicResources 实现](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/scheduler/framework/plugins/dynamicresources/dynamicresources.go)。

## 3. 后续对照：DeviceClass 与 ResourceSlice

1.32 的结构化模型使用以下对象，不能填进 1.28 旧清单：

| 对象                  | 作用                                     |
| --------------------- | ---------------------------------------- |
| DeviceClass           | 公共设备选择条件与驱动配置               |
| ResourceSlice         | 驱动发布设备、属性、容量及节点可用范围   |
| ResourceClaim         | 描述设备请求与选择条件，状态记录所选设备 |
| ResourceClaimTemplate | 为工作负载生成独立 Claim                 |

必须同时记录三类证据：

- [v1.32.0 resource/v1beta1/types.go](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.32.0/staging/src/k8s.io/api/resource/v1beta1/types.go)中，DeviceClass、ResourceSlice 等类型的 `introduced=1.32` 标记表示该 API 版本中的引入版本；类型注释仍明确写着 Alpha 并要求 DRA 门控，不能擅自把注释改称 GA。
- [v1.32.0 versioned_kube_features.go](https://github.com/kubernetes/kubernetes/blob/v1.32.0/pkg/features/versioned_kube_features.go)将整体 DynamicResourceAllocation 门控标为 Beta、默认 false。它与上述类型注释存在标记差异，应分别陈述，不能仅凭包名判断成熟度，也不能反过来把整体门控说成 Alpha。
- [1.32 官方文档](https://raw.githubusercontent.com/kubernetes/website/release-1.32/content/en/docs/concepts/scheduling-eviction/dynamic-resource-allocation.md)仍要求显式启用门控与 `resource.k8s.io/v1beta1`；[API 默认配置](https://github.com/kubernetes/kubernetes/blob/v1.32.0/pkg/controlplane/instance.go)也将该版本放入默认关闭列表。AdminAccess、Claim 设备状态等附加能力还有各自 Alpha 门控，不能一并当作稳定能力。

### 80GB 与 48GB GPU 的选择推演

假定驱动发布了 GPU A 的显存属性为 80GB，GPU B 为 48GB，用户要求至少 70GB。为避免单位混用，本例约定属性 `vendor.example.com/memoryGB` 是以十进制 GB 为单位的整数；它是驱动定义的教学属性，不是 Kubernetes 内置显存字段。

驱动发布设备属性的局部片段，例如 ResourceSlice `spec.devices` 中的一项；不是完整 ResourceSlice：

```yaml
- name: gpu-a
  basic:
    attributes:
      vendor.example.com/memoryGB:
        int: 80
```

对应的 **1.32 合成选择示例，未提交**：

```yaml
apiVersion: resource.k8s.io/v1beta1
kind: DeviceClass
metadata:
  name: example-gpu
spec:
  selectors:
    - cel:
        expression: 'device.driver == "resource-driver.example.com"'
---
apiVersion: resource.k8s.io/v1beta1
kind: ResourceClaim
metadata:
  name: catalog-gpu-large
  namespace: study
spec:
  devices:
    requests:
      - name: gpu
        deviceClassName: example-gpu
        allocationMode: ExactCount
        count: 1
        selectors:
          - cel:
              expression: 'device.attributes["vendor.example.com"].memoryGB >= 70'
```

CEL（Common Expression Language，通用表达式语言）用于表达选择条件。只有实际 ResourceSlice 按约定发布属性、设备尚可分配且其他条件满足时，本例才可选 A、排除 B。驱动没发布的属性不能假定 Kubernetes 会从硬件自动推断；缺少属性也不能当作已匹配。

结构化模型由 Scheduler 读取设备信息与现有分配、计算选择并记录 Claim 状态，不再用 1.28 的 PodSchedulingContext 与驱动逐轮协商。驱动继续负责发布信息、解释配置并准备设备。属性表达需求不等于自动完成 GPU 分区或隔离。

## 4. 分配决定与节点准备

资源分配、节点准备和运行时设备配置是三个阶段。还要区分“资源对象 API 版本”与“kubelet 节点插件 RPC 版本”：

| 版本与证据                                | 节点接口                                                            |
| ----------------------------------------- | ------------------------------------------------------------------- |
| v1.28.0 的 dra/v1alpha2/api.proto         | 单数 NodePrepareResource / NodeUnprepareResource                    |
| v1.28.0 同时存在的 dra/v1alpha3/api.proto | 复数 NodePrepareResources / NodeUnprepareResources，支持批量 Claim  |
| v1.32.0 的 dra/v1beta1/api.proto          | 复数接口，准备结果包含请求关联、设备名、池名及 CDI 标识等结构化信息 |

**复数接口不是 1.32 才出现。** v1.28.0 kubelet 的 DRA Manager 已按 v1alpha3 调用复数接口；其插件客户端遇到 Unimplemented 时，会转换为旧 v1alpha2 的逐 Claim 单数调用。不能因为资源对象使用 v1alpha2，就认定节点侧只有单数协议；也不能把 1.32 响应字段全部反推到 1.28。

依据：[1.28 单数 proto](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubelet/pkg/apis/dra/v1alpha2/api.proto)、[1.28 批量 proto](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubelet/pkg/apis/dra/v1alpha3/api.proto)、[1.28 兼容客户端](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/kubelet/cm/dra/plugin/client.go)、[1.32 proto](https://github.com/kubernetes/kubernetes/blob/v1.32.0/staging/src/k8s.io/kubelet/pkg/apis/dra/v1beta1/api.proto)。

| 阶段                                     | 职责                                                              |
| ---------------------------------------- | ----------------------------------------------------------------- |
| Claim 分配                               | 确定资源选择和使用资格，不是节点挂载完成                          |
| NodePrepareResources，或兼容旧单数调用   | kubelet 请求节点驱动准备已分配资源，返回适用设备配置              |
| 容器运行时配置                           | kubelet 交付配置，运行时提供容器设备访问能力                      |
| NodeUnprepareResources，或兼容旧单数调用 | 不再需要时清理节点准备状态，不等同于删除整个 Claim 或全局释放分配 |

申领已分配仍可能因节点准备失败而无法启动。驱动要处理重复调用、部分失败、异常退出和节点恢复；清理失败也需要重试和状态恢复，不能只在内存中假定成功。kubelet 会记录准备与引用状态；共享 Claim 还有其他 Pod 使用时，不能无条件清理。[1.28 DRA Manager](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/kubelet/cm/dra/manager.go)、[1.32 DRA Manager](https://github.com/kubernetes/kubernetes/blob/v1.32.0/pkg/kubelet/cm/dra/manager.go)。

CDI（Container Device Interface，容器设备接口）描述设备配置的交付，DRA 处理申领与分配协作，两者不等同。CDI 设备名采用类似 `vendor.example.com/gpu=device0` 的完整命名，不是统称 UUID；实际配置由驱动生成，并要求运行时支持。1.28 的节点协议也可返回 CDI 设备字符串，但这不代表所有运行时天然具备对应支持。

## 5. 共享、分区与性能不能靠抽象名字推断

DRA 的申领和共享语义，不自动等同于 GPU 任意比例切分。设备是否支持分区、何时准备、隔离程度及共享限制，都需要硬件和驱动实现。

DRA 与 Device Plugin 的调度开销需要在相同集群规模、设备需求和测量口径下比较，目前缺少足以支持性能优劣的实验记录。版本缺陷也需关联具体 issue、复现条件与修复版本，才能判断影响范围。

| 维度         | Device Plugin                         | DRA                                      |
| ------------ | ------------------------------------- | ---------------------------------------- |
| 资源表达     | 扩展资源整数数量                      | 申领；结构化版本还可表达设备选择条件     |
| 调度信息     | Node 资源数量等                       | 1.28 驱动协商；1.32 结构化设备信息       |
| 具体设备选择 | kubelet Device Manager                | 对应版本的 DRA 分配机制                  |
| 节点准备     | Allocate、适用的 PreStartContainer 等 | 对应节点 RPC 的准备与清理流程            |
| 模型与限制   | 数量模型较简单，仍可有拓扑和厂商扩展  | 表达更灵活，版本、驱动与运维要求也需核对 |
| 硬件隔离     | 取决于驱动与硬件                      | 同样取决于驱动与硬件                     |

DRA 不是 Device Plugin 的简单替代品，也不必然更快。比较应针对相同的业务约束：设备选择能力、准备和清理、可观测性、失败处理、调度延迟与运维成本。先满足功能和隔离需求，再用同口径实验评估开销。

## 6. 这一章怎样用于 1.28 复盘

复盘普通 1.28 环境时，先理解并确认经典设备插件路径；涉及早期 DRA 的历史实验，则按第二节的版本资料复核。后续模型保留为拓展阅读，不将其写成历史教程中已部署成功的内容。

未来若要升级实践，应另开固定环境的验证记录，检查 API 迁移、驱动兼容和资源生命周期。实践结果应记录实际环境、生命周期测试与故障条件，和这里的原理说明分开保存。

[返回本册目录](/collections/kubernetes/)
