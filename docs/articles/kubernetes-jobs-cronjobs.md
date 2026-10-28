---
id: kubernetes-jobs-cronjobs
title: 第十八章 Job 与 CronJob 批处理
description: "长期服务通常希望持续运行；一次数据处理任务则可能执行完成后正常退出。若把它当作需要持续 Running 的服务，正常结束反而可能被错误地重启。"
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
order: 18
---

# 第十八章 Job 与 CronJob 批处理

> 本章以 Kubernetes 1.28 的 batch/v1 API 为范围，介绍一次性任务和定时任务的完成条件、重试与结果管理。示例尚未实际运行。

## 1. 任务的成功条件与服务不同

长期服务通常希望持续运行；一次数据处理任务则可能执行完成后正常退出。若把它当作需要持续 Running 的服务，正常结束反而可能被错误地重启。

Job 跟踪相应的完成条件，并管理 Pod 的执行尝试；CronJob 则按计划创建 Job。两者都无法自动判断外部数据库是否已提交全部预期结果，程序需要明确约定退出码与业务成功的关系。

[![Job 与 CronJob：按可能重复执行设计](/assets/notes/kubernetes/k8s-job-idempotency.svg)](/assets/notes/kubernetes/k8s-job-idempotency.svg)

## 2. completions、parallelism 与失败预算

`completions` 描述目标完成数量，`parallelism` 控制期望并行度；两者不是“容器里启动多少线程”的配置。实际并行还受节点容量、配额和调度等限制。

`backoffLimit` 与失败重试相关，`activeDeadlineSeconds` 限制适用任务活跃时间。容器重启和新的 Pod 尝试也不是同一个层级，应一起观察。

新增教学示例，镜像为占位，未执行：

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: report-demo
  namespace: study
spec:
  completions: 1
  parallelism: 1
  backoffLimit: 2
  activeDeadlineSeconds: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: report
          image: registry.example.com/study/report:DEMO
```

这份清单没有证明某个镜像存在，也未配置业务输出。Job 的普通 Pod 模板不能照搬 Deployment 的 Always 重启策略；适用值为 Never 或 OnFailure，具体字段可核对 [v1.28.0 batch API](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/batch/v1/types.go)。

## 3. 重复尝试与业务幂等 {#_3-至少按可能重复执行来设计}

节点故障、控制器重试或人工再次提交，都可能让任务重复尝试。即使 completions 是 1、parallelism 是 1，也不能把调度和重试机制当作业务 exactly-once。

例如，任务发送账单后，还未可靠记录完成状态就失败，再次尝试便可能重复发送。对此，需要业务幂等键、事务、去重或可恢复的分阶段记录，不能只依赖 Pod 名字。

任务使用共享文件或输出路径时，也要避免多次尝试互相覆盖。成功后再清理临时文件，失败现场则应按保留策略留出诊断窗口。

## 4. CronJob 的计划、并发与截止条件 {#_4-cronjob-是计划器-不是可靠外部事务}

CronJob 的 `schedule` 表达计划，`concurrencyPolicy` 可以选择 Allow、Forbid 或 Replace 来约束同一个 CronJob 所创建任务的重叠行为。它不协调所有其他 CronJob，也不保证每个计划点都准时执行一次。

`startingDeadlineSeconds` 影响错过计划后的启动判断；`suspend` 暂停后续调度，不等于终止所有已经运行的 Job。时区也应明确，1.28 的 `timeZone` 字段需采用适用的合法时区，不能依赖读者机器的本地时间猜测。

关于 missed schedule、并发和幂等边界，参阅 [CronJob 文档](https://kubernetes.io/docs/concepts/workloads/controllers/cron-jobs/)，新增字段与历史行为再以 1.28 API 定位。本章没有提供会调用业务系统的定时命令。

## 5. 保留结果，也要控制残留资源

CronJob 的成功与失败历史保留，和 Job 的 TTL 清理机制解决相关但不同的问题。保留太少会失去诊断材料，保留太多会积累对象与日志。

清理对象不会同时清理外部结果，也不能代替结果审计和持久存储备份。查询时应先确认 CronJob → Job → Pod 的拥有关系，避免混淆不同次计划的日志。

```bash
kubectl get cronjob,job -n NAMESPACE
kubectl describe job JOB_NAME -n NAMESPACE
kubectl get pods -n NAMESPACE -l job-name=JOB_NAME
```

命令未执行。确认失败次数、截止条件、容器退出结果与业务提交记录后，再决定是否人工重跑；重跑本身属于新的业务操作。

[返回本册目录](/collections/kubernetes/)
