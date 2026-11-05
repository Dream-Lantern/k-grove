---
id: kubernetes-hpa
title: 第二十五章 HPA 与指标驱动扩缩容
description: "HorizontalPodAutoscaler 根据指标与目标，通过目标资源的 scale 能力调整期望副本数。Deployment、StatefulSet 是常见目标，但能力边界不是“只支持这两个名字”。"
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
order: 25
---

# 第二十五章 HPA 与指标驱动扩缩容

> 本章以 Kubernetes 1.28 的 autoscaling/v2 为范围，说明指标来源、扩缩容建议与稳定策略。示例为纸面推导，实际收益需要负载测试验证。

## 1. HPA 改变什么

HPA（Horizontal Pod Autoscaler，水平 Pod 自动扩缩容）根据指标与目标，通过目标资源的 Scale 子资源（扩缩容接口）调整期望副本数。Deployment、StatefulSet 是常见目标，但能力边界不是“只支持这两个名字”。

HPA 不直接增加节点，也不能解决数据库响应慢的问题。新增的 Pod 仍需经过控制器创建、调度和启动；节点容量不足时，扩容决定可能只会增加 Pending 状态的数量。

典型反馈链是 HPA Controller 周期协调 → 读取目标 Scale 与对应 Pod 指标 → 计算基础建议并处理缺失指标、未就绪、容忍区间 → 应用上下限及行为约束 → 写回期望副本。随后由 Deployment 等控制器创建/删除 Pod，Scheduler 调度，kubelet 启动容器，Pod Ready 后再进入适用服务路径；下一轮重新采样。

HPA 不直接创建 Pod。采样、协调、调度和就绪各有延迟，期望副本增加不等于 Ready 立即增加，也不会自动消除数据库、网络或第三方服务瓶颈。

[![HPA 反馈：更多副本还需要资源和依赖](/assets/notes/kubernetes/k8s-hpa-feedback.svg)](/assets/notes/kubernetes/k8s-hpa-feedback.svg)

## 2. 指标从哪里来

资源指标、自定义指标与外部指标通过相应 API 和适配器提供，不能把所有来源都等同于 Metrics Server。它提供的资源观测也不代替完整的长期监控系统。

Metrics API（指标 API）提供控制循环所需的观测；Resource Request（资源请求）则是 Pod 声明的请求基线，不是实时用量。autoscaling/v2 支持以下不同输入，目标为 Utilization、Value 或 AverageValue 时计算也有区别：

| 指标类型          | 主要语义与来源                                                                |
| ----------------- | ----------------------------------------------------------------------------- |
| Resource          | CPU、内存等资源指标，通常通过 metrics.k8s.io，由 Metrics Server 等实现提供    |
| ContainerResource | 指定容器的资源指标；1.28 的 HPAContainerMetrics 为默认开启的 Beta，需核实门控 |
| Pods              | 每 Pod 自定义指标，需相应适配器/提供方                                        |
| Object            | 与特定 Kubernetes 对象关联的指标                                              |
| External          | 外部系统指标，通过对应指标 API/适配器提供                                     |

不要求所有 HPA 都部署 Prometheus；自定义/外部指标需要适用提供方，指标可获取性还受发现、权限与采集配置影响。Metrics Server 也不等于长期监控数据库。[1.28 HPA 指标与算法](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/run-application/horizontal-pod-autoscale.md)与[v1.28.0 特性门控](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)

排查时，先确认指标是否可用、时间是否合适、目标是否支持 scale，再检查算法，不要一开始就调低目标利用率。

指标组件访问 kubelet 时也需要正确的证书和信任配置。`--kubelet-insecure-tls` 会跳过相应验证，不能代替对证书问题的定位与修复。

## 3. 利用率的分母是 request

采用 CPU 利用率目标时，指标与适用的 CPU request 相关，而不是与整个节点的 CPU 总量或容器 limit 直接比较。字段名应为 `resources.requests`。

新增教学推导：限定 4 个相关 Pod 的 CPU request 相同，观测条件完整，当前聚合 CPU 利用率为 80%，目标为 50%。忽略容忍区间、缺失指标、未就绪及行为策略等修正时，基础比例给出：

```text
建议副本 ≈ ceil(当前副本 × 当前指标 / 目标指标)
         = ceil(4 × 80 / 50)
         = 7
```

这不是一次实际测量，也不是“必定创建 7 个可用 Pod”的承诺。真实控制循环还会处理缺失与未就绪、上下限及稳定等条件。关于目标类型与 request 基线见 [v1.28.0 autoscaling/v2 类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/autoscaling/v2/types.go)。

例如各 Pod request 均为 250m、使用均为 200m 时，这个 80% 可以直接解释为 200m/250m。它不是占节点总 CPU 的 80%，也不是相对 CPU limit 的 80%。如果仅有单个容器，本例就可以与第十四章的容器 request 对照；多个容器则还需核对 Resource 指标计算所包含的容器范围。

### 3.1 异构 Request 按总量聚合

已核对 v1.28.0 GetResourceUtilizationRatio：函数遍历有效指标集合，仅聚合存在对应 request 的条目，以总使用量除以总请求量，不是对每个 Pod 的百分比直接求算术平均。控制器在进入此计算前还会筛选 Pod 和构造请求集合，缺少必要 CPU request 可能导致无法计算，不能理解为一律自动按零。

```text
基础聚合利用率 = sum(纳入计算的 CPU usage)
                 / sum(相应 CPU request) × 100%
```

下面是独立于 catalog 等 Request 部署的纸面场景，假设指标完整有效、两个 Pod 都满足纳入条件：

| Pod | CPU Request | CPU Usage | 单 Pod 利用率 |
| --- | ----------- | --------- | ------------- |
| A   | 100m        | 100m      | 100%          |
| B   | 900m        | 300m      | 约 33.3%      |

```text
错误的简单平均：(100% + 33.3%) / 2 ≈ 66.7%
正确的聚合利用率：(100m + 300m) / (100m + 900m) × 100% = 40%
当前 2 副本、目标 50%：ceil(2 × 40 / 50) = 2
```

B 的 Request 是 A 的九倍，两项百分比不能等权相加。错误使用 66.7% 会得到 ceil(2×66.7/50)=3，放大副本建议。该函数先用整数计算 `currentUtilization = (metricsTotal * 100) / requestsTotal`，再求与目标的比值，因此还存在整数截断；本例恰为 40%。[v1.28.0 GetResourceUtilizationRatio](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/controller/podautoscaler/metrics/utilization.go)

[![异构 CPU Request：总使用量 400m 除以总请求 1000m，利用率为 40%](/assets/notes/kubernetes/k8s-hpa-weighted-utilization.svg)](/assets/notes/kubernetes/k8s-hpa-weighted-utilization.svg)

这是资源利用率目标的基础模型，不能无条件套用到 Pods、Object、External 等所有指标。缺失指标、未就绪、容忍区间、min/max 和稳定/速率策略仍会影响最终输出。

## 4. 一份只用于解释的 HPA

下面假设专用 study 中 catalog Deployment 已存在，单个 app 容器 CPU request=250m，两个初始副本，且指标 API、权限与采集正常；本次未创建 HPA、修改工作负载或发起负载测试：

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: catalog
  namespace: study
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: catalog
  minReplicas: 2
  maxReplicas: 8
  metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 50
  behavior:
    scaleDown:
      stabilizationWindowSeconds: 300
```

这份清单不包含应用资源设置，也不能说明 50% 就是合适的目标。目标太低可能浪费资源，太高可能无法为突发负载留出余量；是否合适，需要结合启动时间、延迟目标和负载性质验证。

所依赖的资源设置位于 Deployment 的 spec.template.spec.containers，下列是局部片段，不是完整 Deployment；不要把它直接覆盖到现有生产对象：

```yaml
containers:
  - name: app
    resources:
      requests:
        cpu: 250m
```

HPA 也可使用内存或其他指标，但内存不一定会随空闲立即下降，用它缩容要理解应用的缓存和内存管理行为。

## 5. 稳定与扩缩速率

`behavior` 中的扩缩策略和稳定窗口可控制适用的调整方式。指标瞬时下降，不一定意味着应该马上回收全部空余副本；反复扩缩会让启动开销与缓存波动增加。

多指标分别计算建议副本，选择较大的建议，再经过上下限、稳定和扩缩速率等约束。若部分指标获取失败，而可用指标只建议缩容，会跳过缩容；其他可用指标建议扩容时，仍可能扩容。不能将“一个指标错误”概括成任何方向都必然停止。

### 5.1 多指标与错误处理

独立假设当前 4 副本、CPU 建议 5、自定义请求指标建议 8、maxReplicas=10，基础建议为 max(5,8)=8，再进入其他约束。这不是前面 maxReplicas=8 清单的配置变更。

若 CPU 获取失败，而其他有效指标建议缩到 3，则跳过这次缩容；若有效指标建议扩到 8，仍可继续检查扩容。这种不对称处理避免在观测不完整时冒然削减容量，又允许有明确高负载证据时增加容量。并非任意指标错误都会停止扩容。

### 5.2 缺失 CPU 指标与未就绪 Pod

v1.28 的资源利用率路径会忽略正在终止、已 Failed 的 Pod；Pending 或 CPU 初始化/就绪条件不满足的 Pod 会被单独处理，不是把所有 Pod 不加筛选地放进第三节公式。

| 情况                                 | 适用控制目的                                                                                 |
| ------------------------------------ | -------------------------------------------------------------------------------------------- |
| 部分 Pod 缺少 CPU 指标，初步建议缩容 | 以保守较高用量估算缺失项，抑制过度缩容；源码使用 request 的 100%，目标超过 100% 时取更高目标 |
| 部分 Pod 缺少指标，初步建议扩容      | 以零使用量估算缺失项，可能降低扩容幅度，并非必定禁止扩容                                     |
| 扩容时有尚未就绪的 Pod               | 可按零贡献重新计算，避免尚未承接流量的新副本放大扩容建议                                     |
| CPU 采样发生在 Pod Ready 之前        | 结合初始化时间、Ready 转换与采样窗口判断是否纳入，避免启动峰值误导                           |

重新计算若落入容忍区间、方向反转或出现不一致的副本建议，可保持当前副本。指标完全不可用也不同于“部分缺失”，应读取 HPA conditions 和事件。[v1.28.0 ReplicaCalculator](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/controller/podautoscaler/replica_calculator.go)

控制器参数 horizontal-pod-autoscaler-initial-readiness-delay 默认 30 秒，horizontal-pod-autoscaler-cpu-initialization-period 默认 5 分钟；它们用于解释启动/就绪阶段 CPU 样本，与 Pod 的 Readiness Probe 不是同一配置层，也不表示每个新 Pod 一律禁止采样五分钟。1.28 默认容忍比例为 0.1，仍以实际控制器设置为准。[v1.28.0 HPA 默认配置](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/controller/podautoscaler/config/v1alpha1/defaults.go)

### 5.3 缩容稳定窗口

缩容稳定窗口不是简单等一个倒计时结束，而是考虑窗口内较高的历史建议。1.28 的默认缩容稳定窗口为 300 秒，可由相应控制器配置或对象行为设置改变。以下是新增的纸面判断，不是控制器实测记录：

| 场景                                          | 基础判断，不计其他限制       |
| --------------------------------------------- | ---------------------------- |
| 两个有效指标分别建议 3 和 8，maxReplicas 足够 | 使用较大的 8，再进入行为约束 |
| 当前 6，一个指标失败，另一个建议 3            | 跳过这次缩容                 |
| 当前 6，一个指标失败，另一个建议 8            | 仍可能扩容，再检查其他限制   |
| 窗口内曾建议 8，当前短暂建议 3                | 不因一次下降就立即按 3 缩容  |

这些规则对照 [1.28 HPA 算法与稳定窗口](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/run-application/horizontal-pod-autoscale.md)。稳定窗口、速率限制与指标错误属于不同环节，不应混成一个“等待五分钟”的解释。

再假设当前为 8 副本，300 秒缩容窗口内的原始建议如下，忽略其他限制：

| 时间   | 本次计算建议 | 窗口仍包含较高历史建议时 |
| ------ | ------------ | ------------------------ |
| T0     | 8            | 保留 8                   |
| T+60s  | 6            | 仍参考窗口内的 8         |
| T+120s | 3            | 不立即缩到 3，仍参考 8   |

窗口会随每轮协调滚动，高建议逐步过期；8 出窗后，6 可能仍在窗口内，不是固定倒计时结束就直接采用当前最小值。稳定窗口选择适用历史建议，速率策略限制每段时间可变化多少，两者分工不同。

## 6. 多个写入者与验收

如果 HPA 管理 replicas，人工 scale、声明式 apply 或其他自动化也反复写同一字段，就可能互相覆盖。发布流程要明确字段归属。

HPA 通过 Scale 写入副本数，而 Helm Chart 可能渲染固定 spec.replicas；Helm upgrade、人工 scale、GitOps 同步可能再次改它。应协调自动扩缩容与声明源的责任，例如让支持 HPA 的 Chart 按设计省略固定 replicas，而不是假定这些工具天然互不干扰。

```bash
kubectl get hpa catalog -n study
kubectl describe hpa catalog -n study
kubectl get deployment catalog -n study
kubectl get pods -n study -l app=catalog
kubectl top pods -n study
kubectl get hpa -n NAMESPACE
kubectl describe hpa HPA_NAME -n NAMESPACE
kubectl get deployment APP -n NAMESPACE
```

命令未执行。观察指标状态、建议副本、目标实际副本、Ready 数量及业务延迟。扩容成功的验收应包含应用收益与依赖容量，不能只看 HPA 对象已创建。

kubectl top 依赖相应资源指标 API，不是无需采集组件的独立测量。以下是排查方向，不是唯一根因：

| 现象                     | 优先检查                                   |
| ------------------------ | ------------------------------------------ |
| 指标 Unknown             | 指标 API、权限、采集和必要 request         |
| Desired 增加，Ready 不变 | 调度、镜像、探针、节点容量                 |
| 指标下降仍未缩容         | 稳定窗口、其他指标与速率限制               |
| replicas 被反复覆盖      | HPA、人工 scale、Helm 与 GitOps 的字段责任 |
| 扩容后延迟仍高           | 下游瓶颈、负载分布与应用性能               |

下一章学习 [kubectl 的查询、验证与变更边界](/articles/kubernetes-kubectl.html)。

[catalog 案例：从 request 到扩容建议](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
