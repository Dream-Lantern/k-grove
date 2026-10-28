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

插件发现设备并报告健康等信息；kubelet 的设备管理器跟踪这些信息并更新 Node 的相关资源状态；调度器根据请求和适用条件选择节点；节点侧再完成设备分配及运行配置准备。

[![Device Plugin：调度与分配边界](/assets/notes/kubernetes/k8s-device-plugin-detail.svg)](/assets/notes/kubernetes/k8s-device-plugin-detail.svg)

图中区分调度器的节点选择与 kubelet 的节点侧分配。设备插件常采用 DaemonSet 部署，但部署方式与插件接口是两个层次。

## 2. 注册 socket 与插件服务

Linux 常见注册路径是 kubelet 设备插件目录下的 `kubelet.sock`，插件还提供自己的服务端点。注册时报告接口版本、资源名等信息；kubelet 通过相应端点调用插件服务。

ListAndWatch 采用流式响应，在设备状态变化时返回更新列表，而不是定期重新建立查询请求。实现还需要处理连接中断、kubelet 重启等情况，完成重新注册与状态恢复。

Allocate 在容器准备阶段返回所需的设备访问配置等内容，不负责为全局 Pod 选择节点。GetPreferredAllocation 与 PreStartContainer 又有各自的可选能力和条件，不能把它们当作普通调度算法。

接口定义以 [v1.28.0 Device Plugin protobuf](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/kubelet/pkg/apis/deviceplugin/v1beta1/api.proto)为依据；本章没有实现或测试服务。

## 3. 数量、占用与健康要分开

Node capacity/allocatable、调度中的已请求数量、插件报告的健康设备列表，是不同信息。一个 Pod 退出释放分配，不意味着硬件总容量需要从 3 自动加回 4。

经典接口没有通用的 Deallocate RPC，不能承诺“插件在每次 Pod 删除时收到标准回收调用并完成全部硬件清理”。具体实现可能有额外跟踪与清理机制，生命周期需要独立设计。

设备变为不健康时，后续可分配信息和已有工作负载的处理也不是同一件事。健康上报不代表所有已使用该设备的容器会立即被安全迁移。

## 4. 整数资源单位与实际设备能力 {#_4-扩展资源不必然等于整张物理卡}

经典扩展资源必须按整数单位请求，不能超卖；同一容器同时声明 request 和 limit 时两者必须相等。只声明 limit 时，相应 request 可按默认规则形成；只声明 request 而缺少这类资源要求的 limit，也不是完整合法配置。[v1.28.0 资源校验](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/core/validation/validation.go) · [扩展资源整数判定](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/core/helper/helpers.go)

新增合成片段，位于容器字段中，资源名不代表实际厂商或可用驱动：

```yaml
resources:
  limits:
    vendor.example.com/gpu: 1
```

1 是一个整数单位，0.5 不是合法的半个经典扩展资源请求。应看 quantity 解析后的数值：1000m 表示 1，不能仅因表面带 m 就与 0.5 混为一谈。

厂商可以把一个单位定义为物理设备、MIG 分区或其他逻辑单元，但这不会让标准数量字段自动支持任意分数。时间共享和虚拟化机制的隔离、显存及性能语义需要另核对，不因单位变多就自动安全共享。

资源名称本身不能说明其显存、计算隔离和拓扑条件。申请一个单位也不保证获得指定型号或吞吐，选择设备型号还可能涉及资源名、节点标签及插件能力。

是否与 CPU、内存或网卡拓扑协调，需要看 Topology Manager、设备信息及具体策略等条件；不能宣称经典接口完全不支持拓扑，也不能承诺所有组合都会成功。

## 5. PodResources 与利用率监控

PodResources API 可以提供适用的 Pod、容器与设备分配信息，用于关联“谁分到了哪些设备”。它不等于 GPU 利用率、显存占用和温度的采集接口。

利用率需要通过厂商或其他遥测手段采集，再根据可靠的设备身份关联分配信息。暴露本地 socket 也涉及权限控制，不应为了监控而向普通 Pod 开放所有节点敏感路径。[设备插件机制](https://kubernetes.io/docs/concepts/extend-kubernetes/compute-storage-net/device-plugins/)

## 6. 排查分成三个阶段

先看设备是否被发现、插件是否注册及 Node 是否暴露资源；再看 Pod 请求是否能调度；最后看 Allocate、运行时设备注入和应用实际访问。

把默认 Docker runtime 改成某个厂商值不是 Kubernetes 1.28 containerd 环境的通用修复。驱动、设备文件、运行时和插件需要对应；没有具体版本信息时，本章不补造一个可执行安装方案。

性能与隔离验证要明确设备型号、分区或共享模式、驱动、运行时、负载和测量口径。这些性能与隔离结果尚待对应环境实验确认。

[返回本册目录](/collections/kubernetes/)
