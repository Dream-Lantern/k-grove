---
id: kubernetes-pod-lifecycle
title: 第十三章 Pod 生命周期、初始化与退出
description: "Pod 是运行一组紧密协作容器的资源单元。普通 Pod 中的容器共享网络环境，并可通过卷共享文件；它们不自动共享各自镜像里的所有文件。"
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

## 1. Pod 的名称、UID 与替换关系 {#_1-pod-的身份比名字更重要}

Pod 是运行一组紧密协作容器的资源单元。普通 Pod 中的容器共享网络环境，并可通过卷共享文件；它们不自动共享各自镜像里的所有文件。

Pod 对象有自己的 UID（Unique Identifier，唯一标识符）。原 Pod 删除后，即使控制器创建了同名替代对象，也不代表旧 UID 被迁移到另一节点。而在原 Pod 内重启容器，仍属于同一个 Pod 的容器运行过程。

| 场景                              | 名称与 UID                         | 如何理解                                          |
| --------------------------------- | ---------------------------------- | ------------------------------------------------- |
| 同一 Pod 内应用容器异常退出后重启 | Pod 名、UID 通常不变，容器实例改变 | 查看 restartCount 与上次退出状态                  |
| 原 Pod 删除后控制器补副本         | 新对象、新 UID，名称通常也改变     | 不是原对象复活                                    |
| StatefulSet 重建同一序号的 Pod    | 可以复用名称，UID 改变             | 名称稳定不代表对象身份未变                        |
| 已绑定节点发生故障                | 原 UID 不会搬到另一节点            | 控制器按条件创建替代对象；裸 Pod 不会自行获得替代 |

[![Pod 生命周期：同一个对象不会迁移到另一节点](/assets/notes/kubernetes/k8s-pod-lifetime.svg)](/assets/notes/kubernetes/k8s-pod-lifetime.svg)

排查时同时记录 Pod 名、UID、节点、创建时间和容器重启次数，可以避免把“新对象接替”误读成“旧进程恢复”。稳定名称在 StatefulSet 中尤其常见，名称稳定与实例不变是不同概念。

## 2. 初始化容器处理启动前置条件

Init Container（初始化容器，简称 init）完成应用启动前的准备。普通 init 按清单顺序运行，前一个成功完成后才进入下一个，正常完成所需初始化后再启动应用容器。适合准备文件、检查必要依赖或做有限的初始化，但操作要考虑失败重试。

这里的普通 init 与可重启 sidecar 不同：v1.28.0 的 SidecarContainers 为默认关闭的 Alpha。本文不将后来版本的 sidecar 默认行为反推回此环境。普通 init 的 CPU/内存核算与 QoS 判定在第十四章给出公式和练习；门控对照见附录的版本表。

### 2.1 成功、失败与重试

| 场景                                  | 普通 init 的行为                                                                                                 |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| A、B 都成功                           | A 退出码为 0 → B 开始并成功退出 → 应用容器启动                                                                   |
| A 失败，Pod 允许重试                  | kubelet 重试失败的 A，并可能退避；B 和应用继续等待。Pod restartPolicy=Always 时，普通 init 实际按 OnFailure 重试 |
| restartPolicy=Never，A 失败           | 不在原 Pod 内重试失败的 init，Pod 被视为失败；上层是否另建 Pod 由工作负载策略决定                                |
| init 已完成，仅应用容器重启           | 通常复用已完成的初始化，不重新执行 init                                                                          |
| Pod Sandbox（运行沙箱）重建等特殊情况 | 可能重新执行 init；1.28 文档还列出 Always 策略下所有应用容器均已终止且 init 完成记录因垃圾回收丢失的情况         |

init 不是只能执行一次的可靠事务。代码应具备幂等性，即重复执行仍得到同样的目标结果；数据库迁移等副作用应另行设计锁、版本记录与重试协议。[1.28 init 详细行为](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/pods/init-containers.md)

### 2.2 完整共享文件案例

以下保存为 `catalog-init.yaml`，使用固定版本的 Docker Official Image `busybox:1.36.1`，并非附录 B 的占位镜像。复现需要能拉取镜像的 Linux 1.28 隔离集群、创建与观察 Pod 的权限，以及专供本练习的 study 命名空间。若 study 已有其他实验资源，请使用新的命名空间，并同步修改 YAML 和命令。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: catalog-init
  namespace: study
  labels:
    app: catalog-init
spec:
  restartPolicy: Always
  initContainers:
    - name: prepare
      image: busybox:1.36.1
      command: ["sh", "-ec"]
      args:
        - |
          printf 'ready\n' > /work/marker.tmp
          mv /work/marker.tmp /work/marker
      volumeMounts:
        - name: work
          mountPath: /work
    - name: verify
      image: busybox:1.36.1
      command: ["sh", "-ec", "grep -qx ready /work/marker"]
      volumeMounts:
        - name: work
          mountPath: /work
  containers:
    - name: app
      image: busybox:1.36.1
      command: ["sh", "-ec"]
      args:
        - |
          cat /work/marker
          mkdir -p /www
          cp /work/marker /www/index.html
          exec httpd -f -p 8080 -h /www
      ports:
        - name: http
          containerPort: 8080
      volumeMounts:
        - name: work
          mountPath: /work
  volumes:
    - name: work
      emptyDir: {}
```

prepare 通过临时文件再替换目标文件，允许重复准备；verify 成功后，app 才读取 marker 并启动 HTTP 服务。这是文件共享演示，未实现附录 B 的业务探针契约。标签使用 app=catalog-init，以免被后文 app=catalog 的 PDB 误选中。

容器通过同一个卷名共享文件，路径名称不必相同，不是共享镜像文件系统。emptyDir 在同一 Pod 内容器重启时保留；Pod 删除后的替代对象不会继承其文件。init 成功不保证运行过程中依赖一直可用。

以下 Bash 命令是复现步骤。创建和清理会修改测试资源：

```bash
# 仅当 study 不存在且确认为本练习专用时创建
kubectl create namespace study
kubectl apply -f catalog-init.yaml

# 只读观察
kubectl get pod catalog-init -n study
kubectl describe pod catalog-init -n study
kubectl get pod catalog-init -n study -o jsonpath='{.status.initContainerStatuses}'
kubectl logs catalog-init -n study -c prepare
kubectl logs catalog-init -n study -c verify
kubectl logs catalog-init -n study -c app

# 仅清理本练习的 Pod
kubectl delete -f catalog-init.yaml
```

预期观察：两个 init 的 state.terminated.reason 为 Completed、exitCode 为 0 后，app 才运行，日志输出 ready。prepare、verify 不主动打印日志，空日志本身不代表失败。连续检查 initContainerStatuses 中的 restartCount、state、lastState 和事件判断重试；单次快照与日志保留不能证明历史上从未重复执行。

初始化动作应能重试。直接在每次 init 中执行不可重复的数据迁移，可能造成重复副作用。Kubernetes 1.28 还存在受特性门控控制的 sidecar 相关演进，本文的“运行完再启动应用”只针对普通 init，不应外推到所有后续版本的可重启 init 容器。

## 3. 生命周期钩子与探针的分工 {#_3-lifecycle-与探针不是同一组配置}

`lifecycle` 的 `postStart`、`preStop` 是生命周期钩子。startup、liveness、readiness 是探针，不能把 startup probe 当成 lifecycle 下的一项。

postStart 在容器创建后触发，但不保证在 ENTRYPOINT 执行前完成。如果应用必须读取已经准备好的文件，就不能依赖 postStart 与应用进程之间的执行竞速，而应安排明确的初始化流程。

preStop 用于适用终止流程中的收尾。它不是“Pod 对象只要消失就必然执行”的保证，节点故障等情况可能无法完成钩子。应用仍需能处理突然中断和重试。

| 目标                   | 更合适的机制                | 边界                                 |
| ---------------------- | --------------------------- | ------------------------------------ |
| 应用启动前必须生成文件 | 普通 Init Container         | 成功完成后才启动应用                 |
| 容器创建后的辅助动作   | PostStart                   | 不保证先于 ENTRYPOINT 完成           |
| 判断能否承接请求       | Readiness Probe（就绪探针） | 更新就绪状态，不负责重启             |
| 判断是否仍能正常推进   | Liveness Probe（存活探针）  | 达到失败阈值可触发容器重启           |
| 保护较慢的启动过程     | Startup Probe（启动探针）   | 成功前抑制 liveness/readiness 的检查 |
| 终止前收尾             | PreStop + 应用停止信号处理  | 占用终止预算，断电时不保证执行       |

钩子交付以至少一次为目标，可能重复调用，不具备严格一次语义；操作都要能重复执行。[1.28 容器生命周期钩子](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/containers/container-lifecycle-hooks.md)

## 4. 优雅终止与端点状态传播 {#_4-终止过程为何不能画成绝对串行}

删除请求记录在 API 后，节点侧开始处理适用的优雅终止；相关控制器也会更新端点信息。二者的传播与处理不会自动成为“所有连接先排空，再向应用发信号”的严格屏障。

`terminationGracePeriodSeconds` 限制适用的优雅终止时间。preStop 消耗其中的时间，不能把“钩子等待时间”和“完整应用收尾时间”当成互不占用的两份预算。

假设某测试容器宽限期为 30 秒，PreStop 执行 8 秒。以下仅为 Pod spec 下局部字段，不能单独提交：

```yaml
terminationGracePeriodSeconds: 30
containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command: ["sh", "-c", "sleep 8"]
```

| 教学阶段               | 节点终止分支                                          | 时间含义                         |
| ---------------------- | ----------------------------------------------------- | -------------------------------- |
| T0                     | API 接受删除请求，记录 deletionTimestamp 和适用宽限期 | 不代表所有组件同时看到变化       |
| T0 后                  | kubelet 观察到删除，开始本地终止处理                  | 观察与执行有传播延迟             |
| 本地开始后的约 0～8 秒 | PreStop 执行 8 秒                                     | 消耗总计 30 秒预算               |
| PreStop 返回后         | 运行时通常向容器 PID 1 发送 SIGTERM（终止信号）       | 实际停止信号结合镜像、运行时确认 |
| 剩余约 22 秒（理想化） | 应用处理在途请求并主动退出                            | 不承诺始终有完整 22 秒           |
| 预算耗尽仍未退出       | 强制终止剩余进程，通常使用 SIGKILL                    | 不能依赖强杀完成业务收尾         |

秒数用于解释预算，不是 T0 起严格可测的全局时钟。1.28 在 PreStop 超过宽限期仍未完成时，会请求一次额外 2 秒的短暂延长；这是特定处理，不是任意应用都能额外获得的收尾预算。[1.28 Pod 终止流程](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/pods/pod-lifecycle.md)

[![Pod 优雅终止：节点与端点传播并行，PreStop 占用宽限期](/assets/notes/kubernetes/k8s-pod-termination-timeline.svg)](/assets/notes/kubernetes/k8s-pod-termination-timeline.svg)

EndpointSlice（服务端点切片）更新是并行分支：终止中的端点通常表现为 terminating=true、ready=false，serving 可表达终止期间是否仍能服务；各数据平面观察与应用变化需要时间。Terminating 不等于已有连接排空，也没有“所有代理确认后才发 SIGTERM”的屏障。端点条件可回看[第十九章 Service 与 EndpointSlice](/articles/kubernetes-service-endpointslice.html)。

应用需要停止接收新任务、处理已有请求，并适时结束进程。仅在 preStop 中 sleep，而应用不处理停止信号，无法保证请求不丢失；如果等待期间未能正常结束，平台仍可能强制终止剩余进程。

还要检查入口程序是否正确转发信号。镜像通过 shell 间接启动应用时，信号传递与退出码可能不如预期。容器显示 Terminated 后，仍应结合退出原因、退出码和业务审计理解发生了什么。

使用 exec 让业务进程成为 PID 1，或使用能正确转发信号并回收子进程的入口，仍需实际信号实验确认。

## 5. 重启策略与成功失败

普通应用容器的重启策略为 `Always`、`OnFailure`、`Never`，分别表达不同退出条件下的重启行为。选择哪一种要结合工作负载：长期服务与执行完即可结束的批处理，不应使用同一种心智模型。

`CrashLoopBackOff` 表示重复失败后的退避现象，并不是一个独立 Pod phase。仅提高探针超时未必能解决进程入口、缺失配置或应用异常；应先定位首次退出的原因。

`Running` 也不等于 Ready，Ready 更不保证业务所有依赖都正确。探针应围绕应用真实的可服务条件设计，避免一份返回固定成功的接口掩盖故障。

## 6. 读日志时保留实例边界

在隔离环境记录同一名称的多次快照，比较 UID、restartCount、deletionTimestamp、state 与 lastState。下列均为只读模板，先替换名称；本章不主动注入故障或触发删除来制造结果。

```bash
kubectl get pod POD_NAME -n NAMESPACE -o jsonpath='{.metadata.uid}{"\n"}{.metadata.deletionTimestamp}{"\n"}{.status.containerStatuses}{"\n"}'
kubectl get pod POD_NAME -n NAMESPACE -o yaml
kubectl describe pod POD_NAME -n NAMESPACE
kubectl logs POD_NAME -n NAMESPACE -c CONTAINER_NAME
kubectl logs POD_NAME -n NAMESPACE -c CONTAINER_NAME --previous
```

同一 UID 中 restartCount 增加通常是容器重启；UID 改变则是新 Pod 接替，即使名称相同。先读事件、状态和退出结果，再决定是否需要进入容器。`--previous` 只尝试读取指定容器上一个可用实例的日志，受节点日志保留、轮转、垃圾回收及节点可访问性限制，不承诺恢复所有历史；新 Pod 也不会自动继承旧 Pod 的容器日志。

生命周期依据见上述 Kubernetes 1.28 官方资料。应用停机与连接排空仍需独立实验验收。

Pod 怎样运行和终止已经清楚，接下来在[第十四章](/articles/kubernetes-resources-pdb.html)计算资源请求与可用性预算。

[返回本册目录](/collections/kubernetes/)
