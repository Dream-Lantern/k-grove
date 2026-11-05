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

Job（任务）跟踪相应的完成条件，并管理 Pod 的执行尝试；CronJob（定时任务）则按计划创建 Job。两者都无法自动判断外部数据库是否已提交全部预期结果，程序需要明确约定退出码与业务成功的关系。

[![Job 与 CronJob：按可能重复执行设计](/assets/notes/kubernetes/k8s-job-idempotency.svg)](/assets/notes/kubernetes/k8s-job-idempotency.svg)

## 2. completions、parallelism 与失败预算

`completions` 描述目标完成数量，`parallelism` 控制期望并行度；两者不是“容器里启动多少线程”的配置。实际并行还受节点容量、配额和调度等限制。

`backoffLimit` 与失败重试相关，`activeDeadlineSeconds` 限制适用任务活跃时间。容器重启和新的 Pod 尝试也不是同一个层级，应一起观察。

### 2.1 三次完成、并行度二的推演

以下限定 NonIndexed（非索引完成模式）Job，无失败、无额外重叠尝试，completions=3、parallelism=2、backoffLimit=2。这是一种可能路径，不是控制器固定的逐步状态机：

| 阶段                | Running | Succeeded | 目标成功数 | 解释                         |
| ------------------- | ------- | --------- | ---------- | ---------------------------- |
| 初始两个 Pod 已启动 | 2       | 0         | 3          | 调度容量足够时可以并行两个   |
| 首个成功、尚未补足  | 1       | 1         | 3          | 一个执行已完成               |
| 新尝试启动          | 2       | 1         | 3          | 还有两次成功目标，补一个 Pod |
| 又一个成功          | 1       | 2         | 3          | 最后一个仍在运行             |
| 最后一个成功        | 0       | 3         | 3          | 满足该 Job 的完成目标        |

parallelism 不是容器线程数，也不保证实时 Running 数恰为该值。backoffLimit=2 不是“最多只创建两个 Pod”：本例没有失败也需要三次成功。Succeeded 计数只能说明 Kubernetes 观察到的成功尝试，不能证明外部业务恰好提交三次。[1.28 Job 完成与并行](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/job.md)

### 2.2 容器重启、Pod 重试与截止时间

| restartPolicy | 失败后的对象层次                                                                |
| ------------- | ------------------------------------------------------------------------------- |
| Never         | 原容器失败后不在该 Pod 内重启；Job 控制器在预算等条件允许时创建新的 Pod、新 UID |
| OnFailure     | kubelet 可在同一 Pod 内重启失败容器；Job 仍可能因其他条件创建替代 Pod           |
| Always        | 普通 Job 的 Pod Template 不支持                                                 |

backoffLimit 的判定会考虑失败 Pod；OnFailure 还会考虑适用 Pending/Running Pod 中容器的重启计数。它不是简单固定的进程启动总次数，退避、终止和状态传播也会影响观察。本章不启用额外的 podFailurePolicy 等特性。

activeDeadlineSeconds 是 Job 层活跃时间约束，覆盖整个任务，而不是给每个新 Pod 重新发一份完整预算；达到截止条件时，即便失败预算还没耗尽，也会终止适用的运行尝试并将 Job 标为失败。普通未暂停 Job 可结合 status.startTime 判断；若使用 Job suspend，恢复时起始时间与截止计时存在重置规则，不能套用为无限跨暂停的墙钟预算。

纸面失败例：Never、completions=1、parallelism=1、backoffLimit=2。第一次非零退出后，若未达截止条件，可退避并创建新 Pod；第二次成功则完成。若每次都失败，在无其他失败策略的简单情形下，最初一次加最多两次重试仍失败后报告 BackoffLimitExceeded；若更早达到 Job 的 activeDeadlineSeconds，则可能先因 DeadlineExceeded 失败。不要据此推断任何复杂场景都恰有三个 Pod。[v1.28.0 Job 失败判定源码](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/controller/job/job_controller.go)

### 2.3 完整的一次性 Job

以下实验 A 保存为 `report-demo.yaml`，对应上面的三次完成推演。使用固定版本 busybox:1.36.1，只打印文本并休眠，不访问业务数据库或外部存储。前置条件为专用 Linux 1.28 隔离集群、可拉取镜像、专用 study 命名空间及创建和观察批处理资源的权限。study 已有其他人的资源时另选名称并同步修改；本章所有命令均未执行。

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: report-demo
  namespace: study
spec:
  completionMode: NonIndexed
  completions: 3
  parallelism: 2
  backoffLimit: 2
  activeDeadlineSeconds: 600
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: report
          image: busybox:1.36.1
          command: ["sh", "-ec", "printf 'report demo\n'; sleep 10"]
```

create/apply/delete 会修改实验资源；下面其余命令观察状态：

```bash
# 仅当 study 不存在且专供本实验时创建
kubectl create namespace study
kubectl apply -f report-demo.yaml
kubectl get job report-demo -n study -w
```

观察后按 Ctrl+C 退出 watch，再查询；预期最终 Complete=True、Succeeded=3，不要求恰好捕捉到表中的每个瞬间：

```bash
kubectl describe job report-demo -n study
kubectl get pods -n study -l batch.kubernetes.io/job-name=report-demo
kubectl logs job/report-demo -n study
# 仅清理本实验的 Job 及其依赖 Pod
kubectl delete -f report-demo.yaml
```

logs job/report-demo 只选取某个 Pod 的日志；检查三次尝试时，应列出 Pod 后按实际名称逐个读取。batch.kubernetes.io/job-name 是 v1.28 使用的自动标签，旧的无前缀 job-name 为兼容仍被识别；不要自行指定或复制 Job UID 选择器。[v1.28.0 batch 标签和 API](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/batch/v1/types.go)

### 2.4 无业务副作用的受控失败

实验 B 保存为 `report-fail.yaml`，始终 exit 1，只用于观察失败预算，不读写外部系统。它不会在某次重试突然成功：

```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: report-fail
  namespace: study
spec:
  completions: 1
  parallelism: 1
  backoffLimit: 2
  activeDeadlineSeconds: 300
  template:
    spec:
      restartPolicy: Never
      containers:
        - name: report
          image: busybox:1.36.1
          command: ["sh", "-c", "printf 'intentional failure\n'; exit 1"]
```

```bash
kubectl apply -f report-fail.yaml
kubectl get job report-fail -n study -w
```

退出 watch 后检查；预期在简单、资源充足场景下经历退避与新 Pod 尝试，最终 Failed=True。若期限先耗尽，则失败原因不同，不能伪定实际 Events 或重试精确时刻：

```bash
kubectl describe job report-fail -n study
kubectl get pods -n study -l batch.kubernetes.io/job-name=report-fail
kubectl logs job/report-fail -n study
kubectl delete -f report-fail.yaml
```

## 3. 重复尝试与业务幂等 {#_3-至少按可能重复执行来设计}

节点故障、控制器重试或人工再次提交，都可能让任务重复尝试。即使 completions 是 1、parallelism 是 1，也不能把调度和重试机制当作业务 Exactly-Once（恰好一次效果语义）。

例如，任务发送账单后，还未可靠记录完成状态就失败，再次尝试便可能重复发送。对此，需要业务幂等键、事务、去重或可恢复的分阶段记录，不能只依赖 Pod 名字。

每日结算报告也有相同窗口：读取某日数据 → 报告已写入外部存储 → 容器尚未可靠记录完成便异常退出 → 重试再次生成同一天报告。可用结算日期与报表类型组成稳定幂等键，以唯一约束或事务防止重复提交；也可先写临时输出，验证后再原子发布。是否实现恰好一次效果取决于业务存储和提交协议，不由 Job 完成计数提供。将重试预算设为零既不能消除“提交后状态未知”的窗口，也不能代替幂等设计。

任务使用共享文件或输出路径时，也要避免多次尝试互相覆盖。成功后再清理临时文件，失败现场则应按保留策略留出诊断窗口。

## 4. CronJob 的计划、并发与截止条件 {#_4-cronjob-是计划器-不是可靠外部事务}

CronJob 的 `schedule` 使用 Cron Expression（Cron 时间表达式）表达计划，`concurrencyPolicy` 可以选择 Allow、Forbid 或 Replace 来约束同一个 CronJob 所创建任务的重叠行为。它不协调所有其他 CronJob，也不保证每个计划点都准时执行一次。

`startingDeadlineSeconds` 影响 Missed Schedule（错过的计划触发）之后允许创建 Job 的窗口，不是 Job 运行时长限制。`suspend` 暂停后续调度，不等于终止所有已经运行的 Job。Time Zone（时区）也应明确，timeZone 在 v1.27 已稳定，1.28 可使用合法 IANA 时区名称；未指定时按 kube-controller-manager 的本地时区解释，不能猜读者电脑的时间。

### 4.1 两分钟计划与三分钟任务

假设计划在 10:00、10:02、10:04 触发，任务若不被终止会运行三分钟，忽略调度延迟。为让 Forbid 一栏不混入迟到补调度，**这张表额外假设 startingDeadlineSeconds=30**，因此 10:02 计划的窗口在 A 于 10:03 完成前已关闭；这不是 Forbid 默认自带的窗口。

| 计划时间 | Allow                       | Forbid                                      | Replace                    |
| -------- | --------------------------- | ------------------------------------------- | -------------------------- |
| 10:00    | 启动 A，计划至 10:03        | 启动 A，计划至 10:03                        | 启动 A                     |
| 10:02    | 启动 B，至 10:05，与 A 重叠 | A 活跃，跳过当前计划；本例不会在 10:03 补跑 | 请求删除活跃 A，并创建 B   |
| 10:04    | 启动 C，至 10:07，与 B 重叠 | A 已结束，可启动 C，至 10:07                | 请求替换仍活跃的 B，创建 C |

Replace 是控制器尝试删除旧 Job 并创建新 Job，不是“旧进程已彻底退出”的全局互斥屏障，更不会回滚旧任务已经写入的业务结果。并发策略只针对同一 CronJob 的 Job，不同 CronJob 之间仍需业务锁或事务协议。

若 Forbid 没有上述短截止窗口，先前跳过的计划属于 missed schedule，在前一个任务结束后仍可能于允许窗口内补调度；不能机械断言“10:02 跳过就永不再执行”。时间表是有明确条件的教学模型，不是实际调度保证。[v1.28.0 CronJob 并发处理源码](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/controller/cronjob/cronjob_controllerv2.go)

[![CronJob：Allow 重叠，Forbid 跳过，Replace 请求替换](/assets/notes/kubernetes/k8s-cronjob-concurrency-timeline.svg)](/assets/notes/kubernetes/k8s-cronjob-concurrency-timeline.svg)

### 4.2 时区、错过计划与完整 CronJob

实验 C 保存为 `report-schedule.yaml`，每五分钟创建一个只打印 UTC 时间的 Job，与上面的两分钟时间线不同：

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: report-schedule
  namespace: study
spec:
  schedule: "*/5 * * * *"
  timeZone: Etc/UTC
  concurrencyPolicy: Forbid
  startingDeadlineSeconds: 120
  suspend: false
  successfulJobsHistoryLimit: 2
  failedJobsHistoryLimit: 1
  jobTemplate:
    spec:
      backoffLimit: 1
      activeDeadlineSeconds: 60
      ttlSecondsAfterFinished: 3600
      template:
        spec:
          restartPolicy: Never
          containers:
            - name: report
              image: busybox:1.36.1
              command: ["sh", "-ec", "date -u; printf 'scheduled report demo\n'"]
```

CronJob 不是严格实时定时器。120 秒表示错过计划后允许创建的窗口，不承诺必定补齐所有错过任务。从 suspend=true 恢复时，错过的计划可能重新进入调度判断，仍受窗口和并发策略约束；较短窗口会限制考虑的时间范围。小于 10 秒的 startingDeadlineSeconds 还可能因控制器检查节奏而错过创建。[1.28 CronJob 时区与计划说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/cron-jobs.md)

大量 missed schedules 的处理应进一步核对固定版本源码：v1.28.0 在超过 100 次时记录 TooManyMissedTimes 告警，仍返回最近的适用计划，后续继续检查截止与并发条件；不是逐条补齐积压任务，也不能无条件写成“超过 100 次就不再创建 Job”。历史文档对此的简化描述与该版本实现存在差异，这里以固定版本实现为准。[v1.28.0 CronJob 计划计算](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/pkg/controller/cronjob/utils.go)

本例不依赖后续版本增加的计划时间 annotation；不要把新版本观测字段反推为 1.28 默认行为。Job 名称与 ownerReferences 才是本章跟踪资源归属的依据。

```bash
kubectl apply -f report-schedule.yaml
kubectl get cronjob,job -n study
kubectl describe cronjob report-schedule -n study
```

等待计划窗口后，预期出现归属于 report-schedule 的 Job，Job 再拥有 Pod。把下面 JOB_NAME 替换成实际生成的名称；成功或失败历史只有出现相应终态后才有内容，本例正常执行不会主动制造失败 Job：

```bash
kubectl get job JOB_NAME -n study -o yaml
kubectl describe job JOB_NAME -n study
kubectl get pods -n study -l batch.kubernetes.io/job-name=JOB_NAME
kubectl logs job/JOB_NAME -n study
# 只清理本实验的 CronJob 及适用的依赖 Job/Pod
kubectl delete -f report-schedule.yaml
```

通过 Job、Pod 的 metadata.ownerReferences 分别核对 CronJob → Job → Pod，避免把其他实验日志误认成本次计划。所有创建、清理和观察仍待实际集群验证。

## 5. 保留结果，也要控制残留资源

CronJob 的成功与失败历史保留，和 Job 的 TTL（Time to Live，生存时间）清理机制解决相关但不同的问题。保留太少会失去诊断材料，保留太多会积累对象与日志。

| 配置                       | 所属位置                                 | 作用                                                            |
| -------------------------- | ---------------------------------------- | --------------------------------------------------------------- |
| successfulJobsHistoryLimit | CronJob spec                             | 成功 Job 的历史数量上限，本例 2                                 |
| failedJobsHistoryLimit     | CronJob spec                             | 失败 Job 的历史数量上限，本例 1                                 |
| ttlSecondsAfterFinished    | Job spec，或 CronJob 的 jobTemplate.spec | Job 成功或失败结束后，经过适用 TTL 可由控制器清理，本例 3600 秒 |

数量上限与 TTL 可同时生效；不能据此保证恰好保存两份成功日志一小时。TTL 清理适用 Job 及其依赖对象，不撤销外部操作。清理前应把需要的日志、审计和业务结果送到独立保留系统，Job 历史不是结果备份。

清理对象不会同时清理外部结果，也不能代替结果审计和持久存储备份。查询时应先确认 CronJob → Job → Pod 的拥有关系，避免混淆不同次计划的日志。

```bash
kubectl get cronjob,job -n NAMESPACE
kubectl describe job JOB_NAME -n NAMESPACE
kubectl get pods -n NAMESPACE -l batch.kubernetes.io/job-name=JOB_NAME
```

命令未执行。确认失败次数、截止条件、容器退出结果与业务提交记录后，再决定是否人工重跑；重跑本身属于新的业务操作。

这些控制器分别解决不同目标，不是逐级替代关系：

| 控制器      | 关注重点             |
| ----------- | -------------------- |
| Deployment  | 可互换副本与应用发布 |
| StatefulSet | 稳定身份、存储和顺序 |
| DaemonSet   | 合格节点覆盖         |
| Job         | 一次性任务完成       |
| CronJob     | 按计划创建 Job       |

下一章进入 [Service 与 EndpointSlice](/articles/kubernetes-service-endpointslice.html) 的资源实践，随后继续学习配置与存储。

[返回本册目录](/collections/kubernetes/)
