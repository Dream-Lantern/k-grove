---
id: kubernetes-daemonset
title: 第十七章 DaemonSet 与节点级任务
description: "Deployment 管理一组可互换副本，DaemonSet 则让符合条件的节点具有相应 Pod。节点加入、移除或标签条件变化，都会影响期望覆盖范围。"
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
order: 17
---

# 第十七章 DaemonSet 与节点级任务

> 以 Kubernetes 1.28 为背景，理解为什么网络、日志或设备代理常以 DaemonSet 部署。这里只整理资源原理，没有创建节点代理。

## 1. 副本数跟着节点范围走

Deployment 管理一组可互换副本，DaemonSet（守护进程集）则让符合条件的节点具有相应 Pod。节点加入、移除或标签条件变化，都会影响期望覆盖范围。

“每台节点一个”是便于入门的说法，必须补上“符合该 DaemonSet 条件的节点”。节点选择、亲和、污点容忍和平台条件会限制范围；也可以有多个 DaemonSet 分别覆盖不同节点组。

DaemonSet 本身不保证节点代理启动成功。镜像、权限、端口冲突和节点资源都可能让部分节点缺失可用实例。

Kubernetes 1.28 的典型协作为：DaemonSet Controller（守护进程集控制器）根据节点选择等条件计算覆盖需求 → 为需要的节点创建 Pod，并通过 Node Affinity（节点亲和性）表达目标节点约束 → Scheduler（调度器）完成适用的调度绑定 → 目标节点 kubelet 执行节点侧运行。控制器负责“哪些节点需要实例”，不直接绕过调度器强制启动容器。[v1.28.0 DaemonSet 控制器](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/controller/daemon/daemon_controller.go)

假设只考虑 nodeSelector 的 agent=enabled，且这些节点没有其他不被容忍的污点，使用四节点纸面场景：

| 节点   | 初始标签       | 初始是否符合条件 |
| ------ | -------------- | ---------------- |
| node-a | agent=enabled  | 是               |
| node-b | agent=enabled  | 是               |
| node-c | agent=disabled | 否               |
| node-d | 无 agent 标签  | 否               |

阶段 A 期望覆盖 2 个节点；阶段 B 假设在已授权测试中 node-c 改为 enabled，期望变 3；阶段 C 再令 node-b 不符合，期望回到 2，对应节点实例由控制器按条件增减。这里只推演，不执行节点标签变更。资格符合也不代表资源、调度和启动一定成功。

[![DaemonSet 节点覆盖：控制器计算范围，调度器绑定，kubelet 运行](/assets/notes/kubernetes/k8s-daemonset-node-coverage.svg)](/assets/notes/kubernetes/k8s-daemonset-node-coverage.svg)

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

## 3. DaemonSet 的更新预算与取整规则 {#_3-更新字段的默认值不能照抄}

DaemonSet 的 RollingUpdate 使用自己的字段语义。v1.28.0 API 中，`maxUnavailable` 默认是 1，`maxSurge` 默认是 0；不能从 Deployment 抄成两项都是 25%。

两项同时为 0 无法推进更新。DaemonSet 的 maxUnavailable 百分比向上取整，maxSurge 百分比也向上取整，后者百分比结果最小为 1；默认绝对数值 0 则另行理解。Deployment 的 maxUnavailable 百分比反而向下取整，不可照抄。[v1.28.0 DaemonSet 更新类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/apps/v1/types.go)

更严格地说，v1.28 校验要求两者恰有一项非零，不能同时配置为正值。因此从 maxUnavailable=1、maxSurge=0 改成 surge 模式时，必须同时把 maxUnavailable 改为 0。[v1.28.0 更新策略校验](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/apis/apps/validation/validation.go)

新增纸面算例，假定符合条件的期望节点数稳定，两种百分比各自独立比较：

| 期望数量 | DaemonSet 的 25% maxUnavailable | DaemonSet 的 25% maxSurge | Deployment 的 25% maxUnavailable |
| -------- | ------------------------------- | ------------------------- | -------------------------------- |
| 3        | 1                               | 1                         | 0                                |
| 5        | 2                               | 2                         | 1                                |
| 10       | 3                               | 3                         | 2                                |

这些是预算上限的换算，不承诺每轮实际恰好替换对应数量；节点状态、就绪、调度和资源仍会影响推进。

五个合格节点旧版本都正常时，maxUnavailable=1、maxSurge=0 的一种路径是：先允许一个节点的旧实例退出 → 在该节点创建新实例 → 新实例达到可用条件 → 再处理其他节点。新实例不 Ready 时可消耗唯一不可用预算，使更新卡住；这不是每轮必定替换一个的固定节拍。

对比以下 spec.updateStrategy 下的完整局部字段：

```yaml
type: RollingUpdate
rollingUpdate:
  maxUnavailable: 0
  maxSurge: 1
```

surge 模式允许适用节点临时同时存在新旧实例，新实例满足可用条件后再收掉旧实例；主机端口 hostPort、独占设备、内存等可能让这种重叠不可行。minReadySeconds 决定持续就绪多久才视为可用，默认 0。预算主要约束更新主动造成的变动，不阻止节点故障，也不保证业务数据平面无损。

OnDelete 则把已有 Pod 的替换留给后续受控操作。一个网络代理的更新可能影响业务流量，即使 DaemonSet 显示更新完成，也需要另行验证数据平面。

## 4. 节点覆盖与权限一起审核

节点代理可能需要 hostPath、主机网络、设备或较高权限，但“它是 DaemonSet”并不自动证明这些权限都必要。

应分别检查：实际要覆盖哪些节点、需要读写哪些主机路径、是否必须 privileged、服务账户能读写哪些 API。对主机路径的只读挂载也要考虑路径本身是否包含敏感信息。

DaemonSet 与 Deployment 都可以运行普通容器；资源类型不决定程序自动获得硬件权限。设备插件的节点侧职责将在第三十一章展开。

### 4.1 污点与自动容忍

Taint（污点）表达节点对 Pod 的排斥条件，Toleration（容忍）允许 Pod 忽略匹配污点。NoSchedule 阻止不容忍的新 Pod 调度，NoExecute 还可能驱逐已有的不容忍 Pod。容忍不是节点选择，也不是成功调度保证。

1.28 官方文档列出 DaemonSet Pod 自动添加的以下容忍，用于节点代理在部分节点管理状态下仍能工作：

| 污点键                                 | Effect     | 条件                                          |
| -------------------------------------- | ---------- | --------------------------------------------- |
| node.kubernetes.io/not-ready           | NoExecute  | 自动添加，无 tolerationSeconds 期限           |
| node.kubernetes.io/unreachable         | NoExecute  | 自动添加，无 tolerationSeconds 期限           |
| node.kubernetes.io/disk-pressure       | NoSchedule | 自动添加                                      |
| node.kubernetes.io/memory-pressure     | NoSchedule | 自动添加                                      |
| node.kubernetes.io/pid-pressure        | NoSchedule | 自动添加                                      |
| node.kubernetes.io/unschedulable       | NoSchedule | 自动添加，因此 cordon 不等于阻止此类 Pod      |
| node.kubernetes.io/network-unavailable | NoSchedule | 仅 hostNetwork=true 的 DaemonSet Pod 自动添加 |

这不是容忍所有污点，例如控制平面或业务专用污点仍需逐项判断。不要为了方便添加无限制通配容忍；资源、平台条件和其他调度约束依旧有效。[1.28 DaemonSet 自动容忍与调度](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/daemonset.md)

### 4.2 节点代理的权限边界

| 能力                                                  | 需要考虑的风险                                           |
| ----------------------------------------------------- | -------------------------------------------------------- |
| hostNetwork                                           | 使用主机网络，影响端口及网络隔离                         |
| hostPath                                              | 访问主机文件；只读路径也可能泄露敏感信息                 |
| privileged                                            | 扩大主机访问能力，不能因类型是节点代理就默认启用         |
| ServiceAccount（服务账户）                            | Pod 使用的 Kubernetes API 身份                           |
| RBAC（Role-Based Access Control，基于角色的访问控制） | 限制 Kubernetes API 操作，不能替代主机内核和文件系统隔离 |
| hostPort                                              | 节点端口冲突，限制同节点新旧实例重叠                     |

DaemonSet 类型本身不授予这些能力，应逐项按最小权限配置。

## 5. 从期望覆盖到实际可用 {#_5-不要只看期望数量}

```bash
kubectl get daemonset AGENT -n NAMESPACE -o wide
kubectl describe daemonset AGENT -n NAMESPACE
kubectl get pods -n NAMESPACE -o wide
```

查询时对比 desired、current、ready、available、updated 等字段，并把缺失实例映射回具体节点。期望 5 个且实际 5 个，不说明其中 5 个都可用；实例存在也不代表节点功能已验收。

| 显示名称  | status 字段            | 含义                                                                   |
| --------- | ---------------------- | ---------------------------------------------------------------------- |
| Desired   | desiredNumberScheduled | 应有实例覆盖的节点数                                                   |
| Current   | currentNumberScheduled | 应被覆盖且已有至少一个此 DaemonSet Pod 的节点数，不是 Running 容器总数 |
| Ready     | numberReady            | 应被覆盖且有 Ready 实例的节点数                                        |
| Available | numberAvailable        | 应被覆盖且有满足 minReadySeconds 等可用条件实例的节点数                |
| Updated   | updatedNumberScheduled | 已有更新模板实例的目标节点数，不保证该实例已 Ready                     |

这几列可能暂时不同；surge 时一个节点有两个实例，也不能把 Current 直接当 Pod 总数。[v1.28.0 DaemonSet 状态类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/apps/v1/types.go)

节点数变化时，应先确认覆盖范围是否按预期改变，再判断是否发生故障。节点代理配置错误可能影响整个集群，因此发布前应安排分批观察和回退方案，不要同时强制重启所有代理。

## 6. 无主机权限的隔离练习

以下保存为 `study-node-agent.yaml`。前置条件：专用 study 命名空间、固定版本 busybox:1.36.1 可拉取，且管理员已把**明确指定的测试节点**标记为 study-node-agent=enabled。这个专用标签和第一节的 agent 纸面标签不同，避免误覆盖已有节点组；没有授权或目标标签时只阅读清单，不修改节点、不部署。

本例在容器内周期打印自身 Pod 名。它不使用 hostNetwork、hostPath、hostPort 或 privileged，也不挂载 API 令牌；namespace 已存在其他实验资源时应另选名称并同步修改。

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: study-node-agent
  namespace: study
spec:
  selector:
    matchLabels:
      app: study-node-agent
  minReadySeconds: 5
  updateStrategy:
    type: RollingUpdate
    rollingUpdate:
      maxUnavailable: 1
      maxSurge: 0
  template:
    metadata:
      labels:
        app: study-node-agent
    spec:
      nodeSelector:
        study-node-agent: enabled
      automountServiceAccountToken: false
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: agent
          image: busybox:1.36.1
          command: ["sh", "-ec"]
          args:
            - |
              while true; do
                printf 'study agent %s\n' "$HOSTNAME"
                sleep 30
              done
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop: ["ALL"]
          resources:
            requests:
              cpu: 10m
              memory: 16Mi
            limits:
              cpu: 100m
              memory: 32Mi
```

以下步骤未执行，apply/delete 会改变实验资源；不包含节点标签修改命令：

```bash
kubectl get nodes -l study-node-agent=enabled -o wide
kubectl apply -f study-node-agent.yaml
kubectl get daemonset study-node-agent -n study -o wide
kubectl describe daemonset study-node-agent -n study
kubectl get pods -n study -l app=study-node-agent -o wide
kubectl get daemonset study-node-agent -n study -o yaml
# 仅清理本实验的 DaemonSet
kubectl delete -f study-node-agent.yaml
```

预期稳定后各目标节点有一个实例，Ready 后再满足 5 秒门槛计入 Available；若 Desired=0，先查测试标签和节点资格；若 Desired>Current 或 Ready/Available 较少，逐个查 Pod、Events、资源、污点与镜像。标签清理由原授权管理者决定，本章不操作。

节点覆盖与任务完成是两类目标，下一章介绍[Job 与 CronJob](/articles/kubernetes-jobs-cronjobs.html)。

[返回本册目录](/collections/kubernetes/)
