---
id: kubernetes-deployment
title: 第十五章 Deployment 发布、扩缩容与回滚
description: "Deployment 通过 ReplicaSet 协调符合模板的 Pod。用户通常修改 Deployment 的期望，而不是逐个修改它创建的 Pod。"
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
order: 15
---

# 第十五章 Deployment 发布、扩缩容与回滚

> 面向 Kubernetes 1.28 的无状态副本管理。命令均为未执行的学习示例，涉及更新、回滚和删除的命令不能当成只读检查。

## 1. Deployment 管理的是一组期望

Deployment（部署）通过 ReplicaSet（副本集，简称 RS）协调符合模板的 Pod。用户通常修改 Deployment 的期望，而不是逐个修改它创建的 Pod。Pod 被替换后，新对象会来自相应模板。

修改 `spec.template` 才会触发适用的模板发布过程；只修改 `replicas` 是扩缩容，不因此产生一个新的应用模板版本。Deployment 自己的顶层 metadata 标签变化，也不等于 Pod 模板变化。

[![Deployment 发布：约束过程，不保证零故障](/assets/notes/kubernetes/k8s-deployment-rollout-detail.svg)](/assets/notes/kubernetes/k8s-deployment-rollout-detail.svg)

这个模型适合可互换副本。数据库的复制、主从切换和数据迁移并不会由 Deployment 自动完成，是否适用需要结合应用设计。

## 2. RollingUpdate 与 Recreate

RollingUpdate 逐步调整新旧 ReplicaSet 的副本；Recreate 会先终止旧 Pod，再创建新模板的 Pod。这是策略差异，不是“一个永远零停机，一个永远错误”。

新增教学片段，位于 Deployment spec 下：

```yaml
replicas: 4
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 1
    maxUnavailable: 0
minReadySeconds: 10
progressDeadlineSeconds: 600
```

这些数字用于解释：期望 4 个副本，允许适用的额外副本预算，并要求更新过程中不主动降低到低于期望的可用数量。实际是否有额外调度容量、应用是否 Ready，仍决定发布能否推进。终止中的 Pod 也可能暂时占用资源，不能只按期望副本加 surge 估计任何时刻的所有进程数。

`maxSurge` 百分比向上取整，`maxUnavailable` 百分比向下取整。两项不能同时为 0。`minReadySeconds` 参与“可用”的判断，避免仅短暂 Ready 就立即算成稳定副本。

### 2.1 四副本的数量推演

假设旧 v1 的 4 个 Pod 均可用，发布新 v2，容量允许新增副本，且没有其他故障。下面是可能的教学状态序列；旧、新数量指 RS 目标规模及相应非终止副本，终止中的资源另计：

| 阶段             | 旧 v1 | 新 v2   | 可用副本与预算                                            |
| ---------------- | ----- | ------- | --------------------------------------------------------- |
| A：开始前        | 4     | 0       | 可用 4                                                    |
| B：新增一个      | 4     | 1       | 利用 maxSurge=1；新 Pod 尚未可用时，可用仍为 4            |
| C：新 Pod Ready  | 4     | 1       | 尚需连续 Ready 满 10 秒、期间无容器崩溃，才计为 Available |
| D：新 Pod 已可用 | 4→3   | 1       | 可用曾达到 5，允许缩减旧副本，保持可用至少 4              |
| D 后续：继续协调 | 3→2→1 | 1→2→3→4 | 按实时就绪、可用与规模预算交错调整，不是固定操作节拍      |
| E：更新完成      | 0     | 4       | 新副本全部更新且可用，旧目标规模为 0                      |

Ready（就绪）是 Pod 条件；Available（可用）还需满足 Deployment 的 minReadySeconds。控制器持续读状态并调整 RS，所以不承诺每次严格“先创建一个、再删除一个”。maxUnavailable=0 约束更新主动缩减的可用预算，不防止应用自己故障；maxSurge=1 也不是任何时刻所有容器进程总数绝不超过 5 的保证，终止中的 Pod 仍可能占用资源。

[![四副本滚动发布：等待新副本可用后推进，失败时旧副本保留](/assets/notes/kubernetes/k8s-rollout-four-replicas.svg)](/assets/notes/kubernetes/k8s-rollout-four-replicas.svg)

若第十四章中的单 Pod request 为 250m/256Mi，正常四副本请求合计为 1000m/1024Mi；额外一个同配置 surge 副本需再容纳 250m/256Mi，还要为终止重叠等留余量。缺少资源时，新 Pod 可因调度失败而 Pending，发布停滞，不会因旧 Pod 实时 CPU 使用率低就忽略 request。

发布失败条件不是自动回滚数据库的指令，`progressDeadlineSeconds` 也不等于“超时后平台自动还原所有状态”。参数定义以 [v1.28.0 Deployment API 类型](https://raw.githubusercontent.com/kubernetes/kubernetes/v1.28.0/staging/src/k8s.io/api/apps/v1/types.go)为准。

## 3. 更新策略与应用兼容性 {#_3-为什么滚动更新仍会中断}

更新策略可以约束副本调整，但无法修复错误探针、协议不兼容、共享依赖故障或数据库迁移问题。如果新副本过早 Ready，旧副本停止后，客户端仍可能收到错误。

发布前需要确认新旧版本能否同时工作：请求格式、缓存格式、数据库 schema、消息格式是否兼容？只要旧版仍可能接到请求，就不能假设整个系统已经原子切换。

同理，更新中途又修改模板，控制器会继续协调新的目标，不是承诺“先完成上一版再开始下一版”，也不能概括成“立即删除所有刚更新过的 Pod”。

纸面失败场景：v1 正常，v2 镜像拉取失败或应用无法就绪。新的 RS 已存在，但新 Pod 可能处于 Pending phase，其中容器状态为 Waiting、reason 为 ErrImagePull/ImagePullBackOff；若进程启动后探针失败，也可能是 Running 但不 Ready。phase、容器状态与 kubectl 显示的 STATUS 不是同一字段。在本例预算与旧副本保持健康的前提下，旧 v1 通常继续承接请求，新 v2 卡在新增位置。

检查新 Pod 的 Events、镜像引用、调度资源、探针、退出状态和日志，而不是仅增加等待时间。持续没有满足进度条件，达到 progressDeadlineSeconds 后，Deployment 会报告 Progressing=False、reason=ProgressDeadlineExceeded；这是失败状态报告，不会自动执行模板回滚，也不会恢复数据库或外部状态。[1.28 Deployment 进度与失败条件](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/deployment.md)

## 4. 观察发布与历史

以下为学习模板，查询只读取状态；undo 和 scale 会改变目标状态。将 APP、NAMESPACE 替换为实际值；app=catalog 适用于本章案例：

```bash
kubectl rollout status deployment/APP -n NAMESPACE
kubectl rollout history deployment/APP -n NAMESPACE
kubectl describe deployment APP -n NAMESPACE
kubectl get rs -n NAMESPACE
kubectl get pods -n NAMESPACE -l app=catalog

# 变更示例，未执行
kubectl rollout undo deployment/APP -n NAMESPACE --to-revision=2
kubectl scale deployment/APP -n NAMESPACE --replicas=4
```

`--to-revision` 指定目标修订版本。回滚依赖保留的发布历史，`revisionHistoryLimit` 影响旧 ReplicaSet 的保留；历史是 Pod 模板的相关记录，不包括数据库备份、所有 ConfigMap 内容和外部副作用。

如果镜像标签可变，即使模板中保留了旧标签，也不能保证拉取到当时的同一份内容。因此，发布交接时需要固定镜像版本或 digest，并保存配置与兼容性说明。

Revision（修订版本）关联 Pod Template（Pod 模板），通常以历史 RS 保留。清理旧 RS 后便失去相应回滚入口；revisionHistoryLimit 控制可保留的历史数量，不是数据备份策略。

| 内容                       | rollout undo 是否直接恢复                  |
| -------------------------- | ------------------------------------------ |
| 历史 Pod Template          | 可以尝试恢复，仍需重新协调并通过可用性验收 |
| 旧 replicas 值             | 不属于模板回滚的主要范围，按当前规模协调   |
| ConfigMap、Secret 的旧内容 | 不自动恢复；模板中的引用不等于内容快照     |
| 数据库 Schema              | 不自动恢复                                 |
| 已完成的外部副作用         | 不自动撤销                                 |

应独立记录镜像 digest（内容摘要）、配置版本及应用兼容性。历史模板引用可变 tag 时，同名镜像可能已指向另一份内容，undo 不能据此构成完整灾难恢复。

## 5. 暂停、补丁与声明式源

Deployment 支持 pause / resume，用于暂停模板发布的推进；它不是冻结整个集群，也不表示其他控制器停止工作。准备多项模板变更时，需要同时保证声明源和在线对象最终一致。

JSON Patch 使用操作列表；直接写 `{"spec":{"replicas":3}}` 属于对象式补丁，不能同时宣称它是 `--type=json`。为避免低层补丁格式混乱，简单副本变更可以先理解 scale；正式流程则按团队确定的声明式工具管理。

暂停期间仍需考虑 HPA 或 GitOps 等其他字段管理者。多个工具反复覆盖 replicas，会使手工扩容看起来“自动失效”。

以下 pause/resume 会修改在线资源，本次未执行。暂停主要阻止模板变更触发新的发布，不停止 RS 补副本或 HPA 扩缩容；暂停状态下不能执行 Deployment 回滚，需要先恢复。GitOps（以 Git 声明源持续同步资源的管理方式）也可能覆盖人工修改，最终须使声明源与在线状态一致。

```bash
kubectl rollout pause deployment/catalog -n study
kubectl rollout resume deployment/catalog -n study
```

## 6. 删除前先看所有权和数据

典型 Deployment 的 ReplicaSet 与 Pod 会随适用的级联删除处理；Service 通常是独立对象，不因为标签相同就一起删除。孤儿化与后台、前台删除策略也会影响过程。

删除改变资源生命周期，回滚恢复相关模板版本，二者处理不同层次的问题。在确认数据、依赖和恢复路径之前，不应通过“全删重建”处理仅需修改配置的问题。

## 7. 隔离环境中的发布与回滚练习

下面均为未执行的教学步骤，不是测试成功记录。需要专用 Linux 1.28 测试集群、能拉取 busybox:1.36.1 的网络和命名空间内管理 Deployment/Pod 的权限。使用全新的专用 study 命名空间；若已存在前面章节或其他人的资源，请另选名称并同步修改所有 YAML 与命令。不要覆盖现有 catalog，也不要在生产集群操作。

这是基于真实固定版本镜像的轻量 HTTP 演示，复用 catalog、app=catalog 和端口 8080；没有实现附录 B 的业务配置、startup/liveness 接口，也不代表附录 B 已验证。本例 readiness 只检查静态页面能否访问，用于观察发布门槛，不代表生产业务依赖全部健康。

### 7.1 创建与观察初始版本

以下保存为 `catalog-rollout.yaml`。每个 Pod request 为 250m/256Mi，四副本合计 1000m/1024Mi，surge 还需要额外容量；实验资源值不是性能建议。

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog
  namespace: study
spec:
  replicas: 4
  revisionHistoryLimit: 5
  selector:
    matchLabels:
      app: catalog
  strategy:
    type: RollingUpdate
    rollingUpdate:
      maxSurge: 1
      maxUnavailable: 0
  minReadySeconds: 10
  progressDeadlineSeconds: 600
  template:
    metadata:
      labels:
        app: catalog
    spec:
      terminationGracePeriodSeconds: 30
      containers:
        - name: app
          image: busybox:1.36.1
          command: ["sh", "-ec"]
          args:
            - |
              mkdir -p /www
              printf 'catalog %s\n' "$RELEASE" > /www/index.html
              exec httpd -f -p 8080 -h /www
          env:
            - name: RELEASE
              value: v1
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 2
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
```

以下命令按 Bash 编写。create/apply、后续 set env、patch、undo、delete 均会改变测试资源；status/history/get/describe 为观察。客户端 kubectl 需与服务端版本兼容。

```bash
# 确认 study 不存在并且专供本实验后创建
kubectl create namespace study
kubectl apply -f catalog-rollout.yaml
kubectl rollout status deployment/catalog -n study --timeout=180s
kubectl rollout history deployment/catalog -n study
kubectl get rs,pods -n study -l app=catalog
kubectl get deployment catalog -n study -o yaml
```

预期初始 RS 管理 4 个 Pod，最后 readyReplicas、availableReplicas、updatedReplicas 均为 4；记录实际 revision，而非假设一定从 1 开始。若未完成，先检查调度、镜像和探针，不继续后面的变更。

### 7.2 修改模板并保存已知可用 Revision

只改变 RELEASE 环境变量，镜像仍固定为 busybox:1.36.1。环境变量位于 spec.template 中，会形成新模板修订；页面在进程启动时写成 catalog v2。

```bash
kubectl set env deployment/catalog -n study RELEASE=v2
kubectl get rs,pods -n study -l app=catalog -w
```

观察新旧 RS 和 Pod 数量，按 Ctrl+C 结束只读 watch，再继续：

```bash
kubectl rollout status deployment/catalog -n study --timeout=180s
kubectl get deployment catalog -n study -o jsonpath='{.status.readyReplicas}{" "}{.status.availableReplicas}{" "}{.status.updatedReplicas}{"\n"}'
kubectl exec deployment/catalog -n study -c app -- wget -qO- -T 5 http://127.0.0.1:8080/
kubectl rollout history deployment/catalog -n study
CATALOG_GOOD_REVISION=$(kubectl get deployment catalog -n study -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}')
printf 'known good revision=%s\n' "$CATALOG_GOOD_REVISION"
```

只有发布成功、三个副本计数为 4 且页面返回 catalog v2 后，才把读出的非空 Revision 作为已知可用目标。exec 会在容器内执行一次 HTTP 查询，仅验证选中的一个实例；若需业务验收，还应检查所有副本与真实流量路径。

### 7.3 受控失败、诊断与明确回滚

为避免依赖某个镜像标签是否存在，本实验使用确定不存在的静态路径制造 readiness 失败，镜像保持不变。以下战略合并补丁按容器名 app 修改探针，属于在线变更；未在实际集群执行：

```bash
kubectl patch deployment catalog -n study --type=strategic -p '{"spec":{"template":{"spec":{"containers":[{"name":"app","readinessProbe":{"httpGet":{"path":"/not-ready-for-review","port":"http"}}}]}}}}'
kubectl rollout status deployment/catalog -n study --timeout=120s
kubectl describe deployment catalog -n study
kubectl get rs,pods -n study -l app=catalog
kubectl rollout history deployment/catalog -n study
```

预期新 RS 的 Pod 因该路径返回 404 而未 Ready，旧的健康 v2 通常保留，发布卡住。120 秒是客户端等待超时，不等于服务端 600 秒进度期限，也不自动回滚；如需观察 ProgressDeadlineExceeded，应在专用实验中继续等待相应进度期限并读取 Deployment conditions。选择新失败 Pod 的实际名称替换下列 POD_NAME，查看证据：

```bash
kubectl describe pod POD_NAME -n study
kubectl logs POD_NAME -n study -c app
kubectl get deployment catalog -n study -o jsonpath='{.status.conditions}{"\n"}'
```

确认当前未处于 paused，CATALOG_GOOD_REVISION 非空、仍在 history 中并对应刚才验收的模板，再执行明确目标的回滚；若换了终端，应从历史重新核对并赋值，不能照抄某个固定数字：

```bash
kubectl rollout undo deployment/catalog -n study --to-revision="$CATALOG_GOOD_REVISION"
kubectl rollout status deployment/catalog -n study --timeout=180s
kubectl get rs,pods -n study -l app=catalog
kubectl get deployment catalog -n study -o jsonpath='{.status.readyReplicas}{" "}{.status.availableReplicas}{" "}{.status.updatedReplicas}{"\n"}'
kubectl exec deployment/catalog -n study -c app -- wget -qO- -T 5 http://127.0.0.1:8080/
kubectl rollout history deployment/catalog -n study
```

预期恢复正确探针和 RELEASE=v2、发布完成且三个计数为 4、查询返回 catalog v2。回滚本身也更新修订历史，不代表历史编号倒退；未达到这些条件不能宣布恢复成功。实验若需保留，须同步维护声明文件中的已知可用模板，避免重新 apply 旧文件恢复到 v1。

### 7.4 清理实验资源

下面只删除由本实验创建的 Deployment。若另外部署了第十四章 PDB，应先确认其来源再清理；直接删除会绕过 PDB，不能据此验证驱逐预算。不删除整个命名空间或使用标签批量删除其他对象。

```bash
kubectl delete -f catalog-rollout.yaml
# 仅当该文件对应自己另外创建的教学 PDB 时使用
# kubectl delete -f catalog-pdb.yaml
```

Deployment 适合通常可互换的副本；有状态应用还需要稳定身份、数据与顺序约束，继续阅读[第十六章 StatefulSet](/articles/kubernetes-statefulset.html)。滚动发布依据见 [1.28 Deployment 文档](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/workloads/controllers/deployment.md)。

[catalog 案例：配置、探针与发布一起推演](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
