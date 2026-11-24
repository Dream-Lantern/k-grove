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

HPA（Horizontal Pod Autoscaler，水平 Pod 自动扩缩容）只做一件事：看指标算出一个新的副本数，再通过目标对象的 Scale 子资源（扩缩容接口）把这个数字写回去。它写的是“我要几个副本”，不是自己动手增删 Pod。Deployment、StatefulSet 是常见目标；能不能当目标不看名字，而看这个对象有没有提供 Scale 子资源。

HPA 只调整副本数，节点扩容要靠 Cluster Autoscaler；数据库响应慢也不在它的处理范围。新增的 Pod 仍需经过控制器创建、调度和启动；节点容量不足时，扩容决定可能只会增加 Pending 状态的数量。

一轮协调按顺序走五步：HPA Controller 先读目标对象当前的副本数和各个 Pod 的指标；再用指标和目标值算出基础建议副本；然后处理缺失指标、未就绪 Pod、容忍区间这些例外；接着套上 min/max、稳定窗口和扩缩速率约束；最后把结果写回目标对象的期望副本。写回之后才轮到别人干活：Deployment 等控制器按新副本数创建或删除 Pod，Scheduler 把新 Pod 分到节点上，kubelet 拉起容器，Pod 变成 Ready 后才接流量；到下一轮协调再重新采样。

HPA 不直接创建 Pod。采样、协调、调度和就绪各有延迟，期望副本增加后，Ready 副本还要等调度与启动；数据库、网络或第三方服务的瓶颈也不会因此消失。

[![HPA 反馈：更多副本还需要资源和依赖](/assets/notes/kubernetes/k8s-hpa-feedback.svg)](/assets/notes/kubernetes/k8s-hpa-feedback.svg)

## 2. 指标从哪里来

指标有三类来源，走的接口不一样：资源指标（CPU、内存这类）由 Metrics Server 这类组件采集后经 metrics.k8s.io 提供；自定义指标和外部指标要先有一个适配器，由它把对应系统的数据转成 HPA 能读的指标 API。所以不能把所有来源都等同于 Metrics Server。它提供的资源观测也不代替完整的长期监控系统。

Metrics API（指标 API）提供控制循环所需的观测；Resource Request（资源请求）则是 Pod 声明的请求基线，不是实时用量。autoscaling/v2 支持以下不同输入，目标为 Utilization、Value 或 AverageValue 时计算也有区别：

| 指标类型          | 主要语义与来源                                                                |
| ----------------- | ----------------------------------------------------------------------------- |
| Resource          | CPU、内存等资源指标，通常通过 metrics.k8s.io，由 Metrics Server 等实现提供    |
| ContainerResource | 指定容器的资源指标；1.28 的 HPAContainerMetrics 为默认开启的 Beta，需核实门控 |
| Pods              | 每 Pod 自定义指标，需相应适配器/提供方                                        |
| Object            | 与特定 Kubernetes 对象关联的指标                                              |
| External          | 外部系统指标，通过对应指标 API/适配器提供                                     |

HPA 的指标来源可以是 Metrics Server、Prometheus 或外部提供方；指标能否取到还受发现、权限与采集配置影响。Metrics Server 只提供资源指标，长期监控要另接系统。[1.28 HPA 指标与算法](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/run-application/horizontal-pod-autoscale.md)与[v1.28.0 特性门控](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/features/kube_features.go)

排查时，先确认指标是否可用、时间是否合适、目标是否支持 scale，再检查算法；一开始就调低目标利用率，往往只是掩盖指标问题。

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

已核对 v1.28.0 GetResourceUtilizationRatio：这个函数把所有 Pod 的使用量加成一个总数，再把各自对应的 request 加成一个总数，两个总数相除；它不是先算出每个 Pod 的百分比、再把百分比求平均。只有带 request 的条目才进入这两个总数。控制器调用它之前还会先筛选 Pod、拼出 request 集合，所以缺少必要的 CPU request 可能直接算不出来，不能理解为一律自动按零。

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

下面假设专用 study 中 catalog Deployment 已存在，单个 app 容器 CPU request=250m，两个初始副本，且指标 API、权限与采集正常：

```yaml
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: catalog
  namespace: study
spec:
  # HPA 控制的目标工作负载；不是直接列出需要修改的 Pod。
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
          # CPU 利用率目标按 CPU request 为分母，不是按节点总 CPU 或容器 limit 计算。
          averageUtilization: 50
  behavior:
    scaleDown:
      # 缩容稳定窗口，单位秒，用于平滑近期建议，不是每隔这么久固定缩容一次。
      stabilizationWindowSeconds: 300
```

这份清单只覆盖 HPA 对象，应用资源设置要另配；50% 也只是示例目标。目标太低可能浪费资源，太高可能无法为突发负载留出余量；是否合适，需要结合启动时间、延迟目标和负载性质验证。

所依赖的资源设置位于 Deployment 的 spec.template.spec.containers，下列是局部片段，不是完整 Deployment；直接覆盖到现有生产对象会丢字段：

```yaml
containers:
  - name: app
    resources:
      # 声明调度资源需求；CPU 的 m 表示千分之一核，内存 Mi 表示二进制兆字节（按字段单位）。
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

控制器参数 horizontal-pod-autoscaler-initial-readiness-delay 默认 30 秒，horizontal-pod-autoscaler-cpu-initialization-period 默认 5 分钟；这两个参数是 HPA 控制器自己的设置，用来决定刚启动、还没就绪的 Pod 的 CPU 样本算不算数；它们不是 Pod 上的 Readiness Probe 配置，也不表示每个新 Pod 一律禁止采样五分钟。1.28 默认容忍比例为 0.1，仍以实际控制器设置为准。[v1.28.0 HPA 默认配置](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/controller/podautoscaler/config/v1alpha1/defaults.go)

### 5.3 缩容稳定窗口

缩容稳定窗口不是简单等一个倒计时结束，而是考虑窗口内较高的历史建议。1.28 的默认缩容稳定窗口为 300 秒，可由相应控制器配置或对象行为设置改变。以下是新增的纸面判断：

| 场景                                          | 基础判断，不计其他限制       |
| --------------------------------------------- | ---------------------------- |
| 两个有效指标分别建议 3 和 8，maxReplicas 足够 | 使用较大的 8，再进入行为约束 |
| 当前 6，一个指标失败，另一个建议 3            | 跳过这次缩容                 |
| 当前 6，一个指标失败，另一个建议 8            | 仍可能扩容，再检查其他限制   |
| 窗口内曾建议 8，当前短暂建议 3                | 不因一次下降就立即按 3 缩容  |

这些规则对照 [1.28 HPA 算法与稳定窗口](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/run-application/horizontal-pod-autoscale.md)。这三件事管的是不同问题：稳定窗口决定要不要采用窗口内更高的历史建议，速率限制决定一段时间内副本数最多变多少，指标获取失败决定这一轮要不要跳过某个方向。“等待五分钟”只对应第一件。

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
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n study 限定命名空间
kubectl get hpa catalog -n study
# 查看指定资源的状态详情及相关事件，用于核对调度、启动或控制器失败原因
# -n study 限定命名空间
kubectl describe hpa catalog -n study
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n study 限定命名空间
kubectl get deployment catalog -n study
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n study 限定命名空间
# -l app=catalog 按标签选择对象，不是按名称匹配
kubectl get pods -n study -l app=catalog
# 查询 Metrics API 提供的 Pod CPU/内存使用量；需要 Metrics Server 等提供指标，不等于 requests/limits
kubectl top pods -n study
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n NAMESPACE 限定命名空间
kubectl get hpa -n NAMESPACE
# 查看指定资源的状态详情及相关事件，用于核对调度、启动或控制器失败原因
# -n NAMESPACE 限定命名空间
kubectl describe hpa HPA_NAME -n NAMESPACE
# 查询命令中指定的资源及对象名；只读返回当前状态
# -n NAMESPACE 限定命名空间
kubectl get deployment APP -n NAMESPACE
```

观察指标状态、建议副本、目标实际副本、Ready 数量及业务延迟。扩容成功的验收应包含应用收益与依赖容量，不能只看 HPA 对象已创建。

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
