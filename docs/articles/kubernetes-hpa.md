---
id: kubernetes-hpa
title: 第二十五章 HPA 与指标驱动扩缩容
description: HorizontalPodAutoscaler 根据指标与目标，通过目标资源的 scale 能力调整期望副本数。Deployment、StatefulSet 是常见目标，但能力边界不是“只支持这两个名字”。
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

> Kubernetes 1.28、autoscaling/v2 学习范围。未安装 Metrics Server，未跳过证书校验，未创建 HPA 或改变副本。

## 1. HPA 改变什么

HorizontalPodAutoscaler 根据指标与目标，通过目标资源的 scale 能力调整期望副本数。Deployment、StatefulSet 是常见目标，但能力边界不是“只支持这两个名字”。

HPA 不直接增加节点，也不能解决数据库响应慢的问题。新增的 Pod 仍需经过控制器创建、调度和启动；节点容量不足时，扩容决定可能只会增加 Pending 状态的数量。

[![HPA 反馈：更多副本还需要资源和依赖](/assets/notes/kubernetes/k8s-hpa-feedback.svg)](/assets/notes/kubernetes/k8s-hpa-feedback.svg)

## 2. 指标从哪里来

资源指标、自定义指标与外部指标通过相应 API 和适配器提供，不能把所有来源都等同于 Metrics Server。它提供的资源观测也不代替完整的长期监控系统。

排查时，先确认指标是否可用、时间是否合适、目标是否支持 scale，再检查算法，不要一开始就调低目标利用率。

原笔记中的 `--kubelet-insecure-tls` 不作为正常安装步骤。证书或信任配置问题应按部署环境解决，跳过验证会改变安全条件；本次没有安装任何指标组件。

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

不同 Pod request 不相同时，不应照搬这个等 request 算例并直接取各百分比的算术平均。复核报告提出了按总 usage/总 request 聚合的实现说明；本轮未能独立取得 [v1.28.0 GetResourceUtilizationRatio 源码](https://github.com/kubernetes/kubernetes/blob/v1.28.0/pkg/controller/podautoscaler/metrics/utilization.go)，因此没有将异构 request 的精确公式升级为已完成核验的通用结论。本文的计算练习保持在上述等 request 范围；真实算法还会筛选数据并处理缺失值。

## 4. 一份只用于解释的 HPA

下面假设 catalog Deployment 已存在，容器配置了适当 CPU requests，资源指标 API 可用；未执行：

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
```

这份清单不包含应用资源设置，也不能说明 50% 就是合适的目标。目标太低可能浪费资源，太高可能无法为突发负载留出余量；是否合适，需要结合启动时间、延迟目标和负载性质验证。

HPA 也可使用内存或其他指标，但内存不一定会随空闲立即下降，用它缩容要理解应用的缓存和内存管理行为。

## 5. 稳定与扩缩速率

`behavior` 中的扩缩策略和稳定窗口可控制适用的调整方式。指标瞬时下降，不一定意味着应该马上回收全部空余副本；反复扩缩会让启动开销与缓存波动增加。

多指标分别计算建议副本，选择较大的建议，再经过上下限、稳定和扩缩速率等约束。若部分指标获取失败，而可用指标只建议缩容，会跳过缩容；其他可用指标建议扩容时，仍可能扩容。不能将“一个指标错误”概括成任何方向都必然停止。

缩容稳定窗口不是简单等一个倒计时结束，而是考虑窗口内较高的历史建议。1.28 的默认缩容稳定窗口为 300 秒，可由相应控制器配置或对象行为设置改变。以下是新增的纸面判断，不是控制器实测记录：

| 场景                                          | 基础判断，不计其他限制       |
| --------------------------------------------- | ---------------------------- |
| 两个有效指标分别建议 3 和 8，maxReplicas 足够 | 使用较大的 8，再进入行为约束 |
| 当前 6，一个指标失败，另一个建议 3            | 跳过这次缩容                 |
| 当前 6，一个指标失败，另一个建议 8            | 仍可能扩容，再检查其他限制   |
| 窗口内曾建议 8，当前短暂建议 3                | 不因一次下降就立即按 3 缩容  |

这些规则对照 [1.28 HPA 算法与稳定窗口](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/tasks/run-application/horizontal-pod-autoscale.md)。稳定窗口、速率限制与指标错误属于不同环节，不应混成一个“等待五分钟”的解释。

## 6. 多个写入者与验收

如果 HPA 管理 replicas，人工 scale、声明式 apply 或其他自动化也反复写同一字段，就可能互相覆盖。发布流程要明确字段归属。

```bash
kubectl get hpa -n NAMESPACE
kubectl describe hpa HPA_NAME -n NAMESPACE
kubectl get deployment APP -n NAMESPACE
```

命令未执行。观察指标状态、建议副本、目标实际副本、Ready 数量及业务延迟。扩容成功的验收应包含应用收益与依赖容量，不能只看 HPA 对象已创建。

[catalog 案例：从 request 到扩容建议](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
