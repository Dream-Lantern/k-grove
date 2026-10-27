---
id: kubernetes-pod-lifecycle
title: 第十三章 Pod 生命周期、初始化与退出
description: Pod 是运行一组紧密协作容器的资源单元。普通 Pod 中的容器共享网络环境，并可通过卷共享文件；它们不自动共享各自镜像里的所有文件。
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
order: 13
---

# 第十三章 Pod 生命周期、初始化与退出

> 以 Kubernetes 1.28 的普通 Pod 为主。第七章已说明三类探针，本章重点是对象身份、初始化、生命周期钩子和终止。所有命令及片段未执行。

## 1. Pod 的身份比名字更重要

Pod 是运行一组紧密协作容器的资源单元。普通 Pod 中的容器共享网络环境，并可通过卷共享文件；它们不自动共享各自镜像里的所有文件。

Pod 对象有自己的 UID。原 Pod 删除后，即使控制器创建了同名替代对象，也不代表旧 UID 被迁移到另一节点。而在原 Pod 内重启容器，仍属于同一个 Pod 的容器运行过程。

[![Pod 生命周期：同一个对象不会迁移到另一节点](/assets/notes/kubernetes/k8s-pod-lifetime.svg)](/assets/notes/kubernetes/k8s-pod-lifetime.svg)

排查时同时记录 Pod 名、UID、节点、创建时间和容器重启次数，可以避免把“新对象接替”误读成“旧进程恢复”。稳定名称在 StatefulSet 中尤其常见，名称稳定与实例不变是不同概念。

## 2. 初始化容器处理启动前置条件

普通 init containers 按清单顺序运行，前一个成功完成后才进入下一个，正常完成所需初始化后再启动应用容器。适合准备文件、检查必要依赖或做有限的初始化，但操作要考虑失败重试。

这里的普通 init 与可重启 sidecar 不同：v1.28.0 的 SidecarContainers 为默认关闭的 Alpha。本文不将后来版本的 sidecar 默认行为反推回此环境。普通 init 的 CPU/内存核算与 QoS 判定在第十四章给出公式和练习；门控对照见附录的版本表。

下面是新增片段，只表达文件准备关系，省略镜像来源、资源和权限等字段，不能单独提交：

```yaml
initContainers:
  - name: prepare
    image: registry.example.com/study/tools:DEMO
    command: ["sh", "-c", "printf 'ready\n' > /work/marker"]
    volumeMounts:
      - name: work
        mountPath: /work
containers:
  - name: app
    image: registry.example.com/study/app:DEMO
    volumeMounts:
      - name: work
        mountPath: /work
volumes:
  - name: work
    emptyDir: {}
```

两个容器通过同一个卷名共享文件，路径名称不必在两者中相同。init 成功只说明这次初始化满足了命令的退出条件，不保证运行过程中依赖一直可用。

初始化动作应能重试。直接在每次 init 中执行不可重复的数据迁移，可能造成重复副作用。Kubernetes 1.28 还存在受特性门控控制的 sidecar 相关演进，本文的“运行完再启动应用”只针对普通 init，不应外推到所有后续版本的可重启 init 容器。

## 3. lifecycle 与探针不是同一组配置

`lifecycle` 的 `postStart`、`preStop` 是生命周期钩子。startup、liveness、readiness 是探针，不能把 startup probe 当成 lifecycle 下的一项。

postStart 在容器创建后触发，但不保证在 ENTRYPOINT 执行前完成。如果应用必须读取已经准备好的文件，就不能依赖 postStart 与应用进程之间的执行竞速，而应安排明确的初始化流程。

preStop 用于适用终止流程中的收尾。它不是“Pod 对象只要消失就必然执行”的保证，节点故障等情况可能无法完成钩子。应用仍需能处理突然中断和重试。

## 4. 终止过程为何不能画成绝对串行

删除请求记录在 API 后，节点侧开始处理适用的优雅终止；相关控制器也会更新端点信息。二者的传播与处理不会自动成为“所有连接先排空，再向应用发信号”的严格屏障。

`terminationGracePeriodSeconds` 限制适用的优雅终止时间。preStop 消耗其中的时间，不能把“钩子等待时间”和“完整应用收尾时间”当成互不占用的两份预算。

应用需要停止接收新任务、处理已有请求，并适时结束进程。仅在 preStop 中 sleep，而应用不处理停止信号，无法保证请求不丢失；如果等待期间未能正常结束，平台仍可能强制终止剩余进程。

还要检查入口程序是否正确转发信号。镜像通过 shell 间接启动应用时，信号传递与退出码可能不如预期。容器显示 Terminated 后，仍应结合退出原因、退出码和业务审计理解发生了什么。

## 5. 重启策略与成功失败

普通应用容器的策略名是 `Always`、`OnFailure`、`Never`，不是 `Failure`。选择哪一种要结合工作负载：长期服务与执行完即可结束的批处理，不应使用同一种心智模型。

`CrashLoopBackOff` 表示重复失败后的退避现象，并不是一个独立 Pod phase。仅提高探针超时未必能解决进程入口、缺失配置或应用异常；应先定位首次退出的原因。

`Running` 也不等于 Ready，Ready 更不保证业务所有依赖都正确。探针应围绕应用真实的可服务条件设计，避免一份返回固定成功的接口掩盖故障。

## 6. 读日志时保留实例边界

```bash
kubectl get pod POD_NAME -n NAMESPACE -o yaml
kubectl describe pod POD_NAME -n NAMESPACE
kubectl logs POD_NAME -n NAMESPACE -c CONTAINER_NAME
kubectl logs POD_NAME -n NAMESPACE -c CONTAINER_NAME --previous
```

这些是未执行的查询模板。先读事件、状态和退出结果，再决定是否需要进入容器。`--previous` 不承诺恢复已经丢失或轮转的全部历史日志；新 Pod 也不会自动继承旧 Pod 的容器日志。

生命周期依据见 [Kubernetes 1.28 Pod 生命周期](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/pods/pod-lifecycle.md)，钩子边界见 [容器生命周期钩子](https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/)。应用停机与连接排空仍需独立实验验收。

[返回本册目录](/collections/kubernetes/)
