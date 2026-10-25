---
id: kubernetes-daemonset
title: 第十七章 DaemonSet 与节点级任务
description: Deployment 管理一组可互换副本，DaemonSet 则让符合条件的节点具有相应 Pod。节点加入、移除或标签条件变化，都会影响期望覆盖范围。
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
order: 17
---

# 第十七章 DaemonSet 与节点级任务

> 以 Kubernetes 1.28 为背景，理解为什么网络、日志或设备代理常以 DaemonSet 部署。这里只整理资源原理，没有创建节点代理。

## 1. 副本数跟着节点范围走

Deployment 管理一组可互换副本，DaemonSet 则让符合条件的节点具有相应 Pod。节点加入、移除或标签条件变化，都会影响期望覆盖范围。

“每台节点一个”是便于入门的说法，必须补上“符合该 DaemonSet 条件的节点”。节点选择、亲和、污点容忍和平台条件会限制范围；也可以有多个 DaemonSet 分别覆盖不同节点组。

DaemonSet 本身不保证节点代理启动成功。镜像、权限、端口冲突和节点资源都可能让部分节点缺失可用实例。

## 2. 清单里哪些关系与 Deployment 相似

DaemonSet 同样有 `selector` 和 Pod `template`，选择器需要与模板标签匹配。容器、卷、服务账户和安全配置仍写在 Pod 模板的正确层级。

不同之处是，它不通过可随意扩缩的 replicas 表达覆盖目标。期望数量由节点资格等条件决定，因此不能用 `kubectl scale` 的思路代替节点覆盖分析。

新增教学片段，位于 DaemonSet spec 下，省略模板：

```yaml
selector:
  matchLabels:
    app: node-agent
updateStrategy:
  type: RollingUpdate
  rollingUpdate:
    maxUnavailable: 1
    maxSurge: 0
```

该例用于理解更新预算，不是所有节点代理的推荐配置。代理若使用同一个 hostPort 或独占设备，在同一节点允许新旧实例重叠前，还要核对冲突。

## 3. 更新字段的默认值不能照抄

DaemonSet 的 RollingUpdate 使用自己的字段语义。v1.28.0 API 中，`maxUnavailable` 默认是 1，`maxSurge` 默认是 0；不能从 Deployment 抄成两项都是 25%。

两项同时为 0 无法推进更新。DaemonSet 的 maxUnavailable 百分比向上取整，maxSurge 百分比也向上取整，后者百分比结果最小为 1；默认绝对数值 0 则另行理解。Deployment 的 maxUnavailable 百分比反而向下取整，不可照抄。[v1.28.0 DaemonSet 更新类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/apps/v1/types.go)

新增纸面算例，假定符合条件的期望节点数稳定，两种百分比各自独立比较：

| 期望数量 | DaemonSet 的 25% maxUnavailable | DaemonSet 的 25% maxSurge | Deployment 的 25% maxUnavailable |
| -------- | ------------------------------- | ------------------------- | -------------------------------- |
| 3        | 1                               | 1                         | 0                                |
| 5        | 2                               | 2                         | 1                                |
| 10       | 3                               | 3                         | 2                                |

这些是预算上限的换算，不承诺每轮实际恰好替换对应数量；节点状态、就绪、调度和资源仍会影响推进。

OnDelete 则把已有 Pod 的替换留给后续受控操作。一个网络代理的更新可能影响业务流量，即使 DaemonSet 显示更新完成，也需要另行验证数据平面。

## 4. 节点覆盖与权限一起审核

节点代理可能需要 hostPath、主机网络、设备或较高权限，但“它是 DaemonSet”并不自动证明这些权限都必要。

应分别检查：实际要覆盖哪些节点、需要读写哪些主机路径、是否必须 privileged、服务账户能读写哪些 API。对主机路径的只读挂载也要考虑路径本身是否包含敏感信息。

DaemonSet 与 Deployment 都可以运行普通容器；资源类型不决定程序自动获得硬件权限。设备插件的节点侧职责将在第三十一章展开。

## 5. 不要只看期望数量

```bash
kubectl get daemonset AGENT -n NAMESPACE -o wide
kubectl describe daemonset AGENT -n NAMESPACE
kubectl get pods -n NAMESPACE -o wide
```

命令未执行。对比 desired、current、ready、available、updated 等字段，并把缺失实例映射回具体节点。期望 5 个且实际 5 个，不说明其中 5 个都可用；实例存在也不代表节点功能已验收。

节点数变化时，应先确认覆盖范围是否按预期改变，再判断是否发生故障。节点代理配置错误可能影响整个集群，因此发布前应安排分批观察和回退方案，不要同时强制重启所有代理。

[返回本册目录](/collections/kubernetes/)
