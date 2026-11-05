---
id: kubernetes-device-plugin
title: 第三十一章 Device Plugin 与设备资源管理
description: "调度器需要知道节点提供哪些可分配资源，容器运行时又需要知道进程怎样访问实际设备。设备插件与 kubelet 协作，把这两个阶段连接起来。"
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
order: 31
---

# 第三十一章 Device Plugin 与设备资源管理

> Kubernetes 1.28 的经典 Device Plugin 机制复盘。设备驱动、运行时集成与厂商插件未安装或测试；示例不涉及真实 GPU/NPU 配置。

## 1. 设备如何成为可请求资源

调度器需要知道节点提供哪些可分配资源，容器运行时又需要知道进程怎样访问实际设备。设备插件与 kubelet 协作，把这两个阶段连接起来。

插件发现设备并报告健康等信息；kubelet 的设备管理器跟踪这些信息并更新 Node 的相关资源状态；调度器根据请求和适用条件选择节点；节点侧再完成设备分配及运行配置准备。以下用 GPU（Graphics Processing Unit，图形处理器）举例。

[![Device Plugin：调度与分配边界](/assets/notes/kubernetes/k8s-device-plugin-detail.svg)](/assets/notes/kubernetes/k8s-device-plugin-detail.svg)

图中区分调度器的节点选择与 kubelet 的节点侧分配。设备插件常采用 DaemonSet 部署，但部署方式与插件接口是两个层次。上一章的排障方法在这里仍适用：先确认停在发现、调度、节点准备还是应用访问阶段。

## 2. 注册 socket 与插件服务

Device Plugin（设备插件）通过 gRPC 与 kubelet 通信；RPC（Remote Procedure Call，远程过程调用）让两者通过约定接口交换设备信息和配置。Linux 常见的注册 Socket（本地进程通信端点）是 `/var/lib/kubelet/device-plugins/kubelet.sock`；这是 kubelet 提供的注册入口，不是插件自身的服务端点。

完整链路如下，图中前四阶段展示发现与分配，第五阶段展示运行时交付：

1. 插件发现设备，先启动自己的 gRPC 服务，监听设备插件目录内的独立 Unix Socket。
2. 插件向 kubelet 的注册入口提交 `endpoint`、API 版本与资源名，例如 `vendor.example.com/gpu`。endpoint 是插件 Socket 文件名。
3. kubelet 连接插件端点，获取能力选项，并调用 `ListAndWatch`。
4. 插件通过该流式 RPC 返回设备列表及健康状态，状态变化时推送新列表；kubelet 的 Device Manager（设备管理器）据此更新 Node 的 Capacity 和 Allocatable。
5. Scheduler 根据 Pod 请求、节点可分配资源及其他约束选择 Node，不选择物理 GPU 的 Device ID。
6. 在选定节点上，kubelet Device Manager 选择具体 Device ID；可选的优选或拓扑提示参与这个决定。
7. kubelet 调用插件 `Allocate`，传入所选 ID；插件执行适用的设备准备并返回访问配置。
8. kubelet 将配置交给容器运行时；运行时按支持方式配置设备访问，随后容器启动。容器能启动仍不证明应用能够正确使用 GPU。

| RPC                    | 作用                             | 是否必需                             |
| ---------------------- | -------------------------------- | ------------------------------------ |
| ListAndWatch           | 流式上报设备和健康状态           | 核心发现机制                         |
| Allocate               | 为所选 ID 返回容器访问配置       | 核心分配阶段                         |
| GetPreferredAllocation | 建议优选设备组合                 | 可选，需声明可用；不保证最终采用建议 |
| PreStartContainer      | 每次容器启动前执行适用的设备准备 | 可选，需声明 PreStartRequired        |

`GetDevicePluginOptions` 用于获取能力选项。`AllocateResponse` 的容器响应可携带设备节点、环境变量、挂载、注解和 CDI（Container Device Interface，容器设备接口）设备标识。CDI 处理在 1.28 受默认关闭的 Alpha 门控 `DevicePluginCDIDevices` 等条件约束；1.28 文档要求在 kubelet 与 kube-apiserver 启用该门控，还要求运行时支持；不能因 protobuf 中存在字段，就认定普通集群会自动注入 CDI 设备。

接口和字段核对了 [v1.28.0 Device Plugin protobuf](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1/api.proto)、[设备管理器](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/kubelet/cm/devicemanager/manager.go)与 [CDI 配置处理](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/kubelet/cm/devicemanager/pod_devices.go)；本章没有实现或调用插件服务。

## 3. 数量、占用与健康要分开

Node capacity/allocatable、调度中的已请求数量、插件报告的健康设备列表，是不同信息。一个 Pod 退出释放分配，不意味着硬件总容量需要从 3 自动加回 4。

经典接口没有通用的 Deallocate RPC，不能承诺“插件在每次 Pod 删除时收到标准回收调用并完成全部硬件清理”。具体实现可能有额外跟踪与清理机制，生命周期需要独立设计。

设备变为不健康时，后续可分配信息和已有工作负载的处理也不是同一件事。健康上报不代表所有已使用该设备的容器会立即被安全迁移。

合成案例：Node A 有 4 个设备，其中一个运行期间变为 Unhealthy，插件通过 ListAndWatch 更新列表。按 1.28 Device Manager 的 `GetCapacity`，在列表仍包含这 4 个设备、只有健康状态改变的假设下，Capacity 仍为 4，Allocatable 变为 3。后续分配不使用该不健康设备；已运行 Pod 是否退出、如何重试或迁移，由应用、设备故障表现和厂商恢复机制共同决定，不存在自动安全迁移保证。

插件重启后要重新启动服务并注册；kubelet 重启会清理设备插件目录中的 Socket，插件应检测并重新注册。kubelet 还会从 checkpoint（本地检查点）恢复已分配设备记录，避免把旧分配误当作空闲；恢复仍需结合插件重新上报。Pod 生命周期结束后的分配记账回收，与厂商复位、外部状态清理是不同事情。经典协议没有通用 Deallocate，插件不能依赖每次删除都有标准清理回调。[1.28 插件重启与健康处理](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins.md)

## 4. 整数资源单位与实际设备能力 {#_4-扩展资源不必然等于整张物理卡}

经典扩展资源必须按整数单位请求，不能超卖；同一容器同时声明 request 和 limit 时两者必须相等。只声明 limit 时，相应 request 可按默认规则形成；只声明 request 而缺少这类资源要求的 limit，也不是完整合法配置。[v1.28.0 资源校验](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/core/validation/validation.go) · [扩展资源整数判定](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/core/helper/helpers.go)

下面是假设设备均健康、尚无设备请求占用时的教学数据，资源名不代表实际厂商或已安装驱动：

| Node   | Capacity | Allocatable |
| ------ | -------: | ----------: |
| Node A |        4 |           4 |
| Node B |        2 |           2 |

合成 Pod 清单，未提交；busybox 仅保持容器运行，不包含 GPU 验证程序：

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: catalog-gpu
  namespace: study
spec:
  containers:
    - name: app
      image: busybox:1.36.1
      command: ["sleep", "3600"]
      resources:
        limits:
          vendor.example.com/gpu: 2
```

若其他条件满足，A 和 B 都可成为候选；Scheduler 选节点，选中后 kubelet 选两个具体 Device ID，再调用插件 Allocate。假设该 Pod 最终在 A 使用两个设备，A 的 Capacity/Allocatable 仍可为 4/4，而设备请求占用为 2、按调度记账可剩 2；Allocatable 不是每次分配后直接减小的“实时空闲数”。若 B 的两个单位已被其他 Pod 请求占用，B 即使显示 2/2，也不能再接纳这个请求。

Quantity（资源数量）的合法性取决于解析后的值，而不是有没有后缀：

| 数量写法 | 解析后的单位数 | 扩展资源整数校验 |
| -------- | -------------: | ---------------- |
| `3`      |              3 | 有效             |
| `3000m`  |              3 | 有效             |
| `3Ki`    |           3072 | 有效             |
| `0.5`    |            0.5 | 无效             |
| `1500m`  |            1.5 | 无效             |

有效只表示通过该数量规则，不证明集群有这么多设备。扩展资源必须在 limits 中声明；同时写 requests/limits 必须相等。若 request 未被其他准入机制设置，只写 limit 时会默认出相同 request，不能用不同 request/limit 超卖设备。[1.28 扩展资源 Quantity 示例](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/manage-resources-containers.md)与前述资源校验源码都按数值判定整数。

厂商可以把一个单位定义为物理设备、MIG 分区或其他逻辑单元，但这不会让标准数量字段自动支持任意分数。时间共享和虚拟化机制的隔离、显存及性能语义需要另核对，不因单位变多就自动安全共享。

资源名称本身不能说明其显存、计算隔离和拓扑条件。申请一个单位也不保证获得指定型号或吞吐，选择设备型号还可能涉及资源名、节点标签及插件能力。

NUMA（Non-Uniform Memory Access，非一致性内存访问）使 CPU 访问不同位置内存的成本不同。例如 GPU 靠近 NUMA Node 1，而可用的独占 CPU 位于 NUMA Node 0，就可能难以满足单 NUMA 对齐要求。

Topology Manager（拓扑管理器）在 kubelet 侧收集 CPU、设备等资源管理器的拓扑提示，按策略判断是否接受组合。假设相关提示不能形成单 NUMA 对齐，`single-numa-node` 策略可能拒绝节点侧准入；`best-effort` 又有不同容忍语义。因此 Pod 已被 Scheduler 选中节点，也可能在 kubelet 侧失败。Topology Manager 不是另一种 Scheduler 节点选择算法；具体结果依赖管理策略、作用域和插件提供的拓扑信息。[1.28 Topology Manager](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/administer-cluster/topology-manager.md)

## 5. PodResources 与利用率监控

PodResources API 可以提供适用的 Pod、容器与设备分配信息，用于关联“谁分到了哪些设备”。它不等于 GPU 利用率、显存占用和温度的采集接口。

Linux 常见 Socket 为 `/var/lib/kubelet/pod-resources/kubelet.sock`，与插件注册 Socket 不同：

| 接口                    | 用途与 1.28 条件                                                         |
| ----------------------- | ------------------------------------------------------------------------ |
| List                    | 列出 Pod、容器与设备等分配关联                                           |
| Get                     | 按 Pod 名和命名空间查询；KubeletPodResourcesGet 为 Alpha，默认关闭       |
| GetAllocatableResources | 查询 kubelet 已知的可分配资源集合；不是扣除所有 Pod 占用后的实时空闲清单 |

1.28 的基础 PodResources 和 GetAllocatableResources 已 GA；不要据此推断 Get 也默认可用。[v1.28.0 PodResources protobuf](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/kubelet/pkg/apis/podresources/v1/api.proto)、[特性门控](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/features/kube_features.go)。

| 数据                         | 主要来源           |
| ---------------------------- | ------------------ |
| Pod 分配了哪些 GPU           | PodResources API   |
| 设备是否健康                 | Device Plugin 上报 |
| GPU 利用率、显存使用量、温度 | 厂商遥测工具       |

利用率需通过厂商等遥测采集，再用可靠设备身份关联分配信息。本地 Socket 属于节点敏感接口，不应随意暴露给普通容器，也不在这里挂载或调用。

## 6. 排查分成三个阶段

先看设备是否被发现、插件是否注册及 Node 是否暴露资源；再看 Pod 请求是否能调度；最后看 Allocate、运行时设备注入和应用实际访问。

未执行的只读查询模板：

```bash
kubectl get nodes -o yaml
kubectl describe node NODE_NAME
kubectl get pod catalog-gpu -n study -o wide
kubectl describe pod catalog-gpu -n study
```

依次观察扩展资源是否出现、已有请求占用、调度事件及 Allocate/容器准备错误。Node 分配记账不能代替 Device ID 关联或厂商健康遥测；查看已确认的插件 Pod 日志也需要相应权限，避免打印凭据。

把默认 Docker runtime 改成某个厂商值不是 Kubernetes 1.28 containerd 环境的通用修复。驱动、设备文件、运行时和插件需要对应；没有具体版本信息时，本章不补造一个可执行安装方案。

性能与隔离验证要明确设备型号、分区或共享模式、驱动、运行时、负载和测量口径。这些性能与隔离结果尚待对应环境实验确认。

[返回本册目录](/collections/kubernetes/)
