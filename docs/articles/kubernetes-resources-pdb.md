---
id: kubernetes-resources-pdb
title: 第十四章 资源请求、限制与可用性预算
description: 运行时 CPU 节流可能表现为延迟增加，内存超限则可能触发 OOM 终止，具体行为还取决于系统、cgroup 与运行时配置。OOMKilled、驱逐和应用主动退出需要分别查证，不能仅凭一次重启就将它们归为一类。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 14
---

# 第十四章 资源请求、限制与可用性预算

> 新增基础章节，补充原笔记中发布、调度和 HPA 共用的前置知识。以 Kubernetes 1.28 的容器级 CPU、内存配置为主，不引入后来版本的 Pod 级资源配置。没有压测或真实资源变更。

## 1. 调度需要的数字与运行时限制

`requests` 描述资源请求，是调度等机制的重要输入；`limits` 描述适用的运行约束。调度器不是只看某一刻的 CPU 空闲率，就随意把所有 Pod 堆到看起来空闲的节点。

| 配置         | 主要用途                                   | 常见误解                     |
| ------------ | ------------------------------------------ | ---------------------------- |
| CPU request  | 调度资源核算等；CPU 竞争时也有相关权重作用 | 每时每刻必须烧掉这部分 CPU   |
| CPU limit    | 限制可获得的 CPU 时间                      | 超过后一定像内存一样被杀死   |
| 内存 request | 调度核算等                                 | 一定已经预分配了物理内存     |
| 内存 limit   | 约束适用的内存使用                         | 配置后就不会发生节点内存压力 |

运行时 CPU 节流可能表现为延迟增加，内存超限则可能触发 OOM 终止，具体行为还取决于系统、cgroup 与运行时配置。OOMKilled、驱逐和应用主动退出需要分别查证，不能仅凭一次重启就将它们归为一类。

## 2. 先读懂单位

新增教学片段，位于容器下；数值仅用于说明：

```yaml
resources:
  requests:
    cpu: "250m"
    memory: "256Mi"
  limits:
    cpu: "1"
    memory: "512Mi"
```

`250m` 表示四分之一个 CPU 单位，不是 250 个 CPU。内存 `Mi` 是二进制单位，`M` 是十进制单位，两者不能不加区分地互换。更不能把 `memory: 400m` 当成 400 MiB。

字段名是复数 `requests`。HPA 的 CPU 利用率以适用 request 为基线。配置建议是显式表达请求与限制，但“模板里没写 request”并不必然意味着最终 Pod 没有 request：对某项资源，仅写 limit、未写 request，且没有准入机制补入其他默认 request 时，Kubernetes 会将该 limit 用作 request。

| 新增 CPU 算例                       | 默认化后的 CPU request | 普通 CPU 请求调度核算          |
| ----------------------------------- | ---------------------- | ------------------------------ |
| requests=100m，limits=2             | 100m                   | 按 100m，不因 limit 较大变成 2 |
| 只写 limits=2，且无其他默认 request | 2                      | 按 2，不是按零                 |

验收应读取最终 Pod 的 resources，而不只看 Deployment 源文件。LimitRange、准入和运行时设置可能影响最终配置。[1.28 requests 与 limits 默认规则](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/manage-resources-containers.md)

资源值应来自启动峰值、稳定负载与故障场景的观察。request 显式固定时，提高 CPU limit 本身不增加上述普通 CPU request 核算；省略 request 而发生默认化，则可能明显提高请求量。实际运行时的资源竞争与调度请求又是两个观察层次。

## 3. 一个 Pod 需要多少资源

限定普通、运行至完成的 init 容器，且没有启用可重启 sidecar 语义，对 CPU、内存等每种资源分别计算：

```text
有效 Pod request = max(普通应用容器 request 之和,
                       各普通 init 容器 request 的最大值)
                   + 适用的 Pod overhead
```

新增纸面练习，不计 overhead：应用 A 请求 300m/256Mi，应用 B 请求 200m/128Mi；init X 请求 800m/64Mi，init Y 请求 100m/512Mi。CPU 为 max(500m,800m)=800m，内存为 max(384Mi,512Mi)=512Mi。两个资源的最大值可以来自不同阶段，不是把全部容器简单相加。

overhead 若由 RuntimeClass 等机制提供，应按实际保存的 Pod 核算。1.28 的 SidecarContainers 是默认关闭的 Alpha；若启用，某些 init 会与后续容器重叠运行，不能套用以上普通 init 简式。[1.28 init 资源共享](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/pods/init-containers.md)

因此，不能只凭一个容器的 request 解释整个 Pod 的调度结果，也不能仅用“requests 总和小于节点物理内存”判断能否调度。Node allocatable、已有请求、系统保留和其他约束都会影响结果。

计算时应把普通 init、Pod 开销和已启用的特性一起纳入。详细条件参见 [Kubernetes 1.28 容器资源管理](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/manage-resources-containers.md)。

## 4. QoS、配额与默认值解决不同问题

在本章普通 1.28 场景，应按默认化后的配置，同时检查普通应用和 init 容器的 CPU、内存：

| QoS        | 判定要点                                                 | 新增最小推理例子，无 init、无其他默认    |
| ---------- | -------------------------------------------------------- | ---------------------------------------- |
| Guaranteed | 每个相关容器的 CPU、内存均有正值 request/limit，分别相等 | 一个容器 CPU=250m/250m，内存=256Mi/256Mi |
| BestEffort | 所有相关容器均无有效的正值 CPU/内存 request 或 limit     | 一个容器完全未设置 CPU/内存资源          |
| Burstable  | 其他情况                                                 | 本章 250m/1、256Mi/512Mi 示例            |

其他资源字段不直接决定这套 CPU/内存 QoS 分类；不要只检查 YAML 是否出现 resources 就下结论。可从 Pod `status.qosClass` 对照结果。[v1.28.0 QoS 判定源码](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/core/v1/helper/qos/qos.go)

QoS 可参与节点压力下的处理，但不是 CPU 性能排名或业务优先级；优先级、驱逐与资源隔离仍需分别理解。

ResourceQuota 可限制命名空间等适用范围的资源总量或对象数量；LimitRange 可施加容器或 Pod 的约束和默认值。提交清单时省略字段，实际对象也可能经过默认化或准入补入配置。排查应同时看声明源和服务端实际保存结果。

这些机制可能让扩容请求被拒绝。即便 HPA 决定增加副本，配额、节点容量或存储仍可能成为限制，不能靠增加 `maxReplicas` 一项解决。

## 5. PodDisruptionBudget 管什么

PDB 是新增补充，用于约束适用的自愿中断中的可用性，例如通过 Eviction API 进行节点维护时。它不会阻止所有故障，也不保证机器断电时依然保留某个副本数。

PDB 的 `minAvailable` 或 `maxUnavailable` 与 Deployment 滚动更新策略中的同名字段属于不同对象。PDB 不能代替 Deployment 自己的更新预算，也不能让应用在没有健康副本时凭空可用。

新增操作分类练习，下面没有执行任何删除或驱逐：

| 操作                                  | 是否由这一路径检查 PDB              |
| ------------------------------------- | ----------------------------------- |
| 通过 Eviction API 受控驱逐            | 检查适用预算，可能被拒绝并等待      |
| 直接删除 Pod 或 Deployment            | 绕过 PDB，不能靠预算阻止            |
| Deployment / StatefulSet 自身滚动更新 | 不直接由 PDB 限速，使用各自更新策略 |
| 节点故障、断电                        | PDB 无法阻止，故障可用性另行设计    |

因更新或故障而不可用的 Pod 仍可能影响预算状态。判断关键不是“是不是管理员主动操作”，而是该操作是否经过受 PDB 约束的驱逐路径。[Pod 中断与预算边界](https://kubernetes.io/docs/concepts/workloads/pods/disruptions/)

设计预算时需要考虑：副本数、每副本承载能力、就绪检查、故障域、节点维护与依赖。单副本服务要求“不允许中断”可能阻塞受控驱逐，但不会让它自动获得高可用。

关于适用的自愿中断和限制，见 [PodDisruptionBudget](https://kubernetes.io/docs/tasks/run-application/configure-pdb/)。本章未执行 drain 或驱逐测试，不能据此声称维护不会影响服务。

## 6. 如何把数字变成可解释的配置

可以先记录负载：分别观察启动阶段与稳定运行时的 CPU、内存、延迟和重启原因，再设置请求与限制，并验证高负载及缩容时的行为。每次变更都保留旧值和观察窗口，不要同时调整资源与应用版本，以免无法判断变化原因。

初次学习可以先读事件和实际对象，不必先改数值：

```bash
kubectl describe pod POD_NAME -n NAMESPACE
kubectl describe node NODE_NAME
kubectl get resourcequota,limitrange -n NAMESPACE
```

命令未执行。资源管理关注容量与约束，可用性预算关注特定中断路径；两者都需要与应用的真实服务能力一起验证。

[catalog 案例：把资源数字放回 Pod](/articles/kubernetes-practice-guide.html) · [版本与门控表](/articles/kubernetes-version-references.html) · [返回本册目录](/collections/kubernetes/)
