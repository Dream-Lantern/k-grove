---
id: kubernetes-practice-guide
title: 附录 B　catalog 贯穿案例
description: "本合成案例用一组 catalog 应用对象串联第 7、12、13、14、15、19、21、25 章。学习时先跟踪标签、配置、端口和资源之间的关系；镜像为占位符，真实程序和集群测试尚待补齐。"
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
order: 91
---

# 附录 B　catalog 贯穿案例

[返回本册目录](/collections/kubernetes/)

本合成案例用一组 catalog 应用对象串联第 7、12、13、14、15、19、21、25 章。学习时先跟踪标签、配置、端口和资源之间的关系；镜像为占位符，真实程序和集群测试尚待补齐。

## 1. 先约定应用契约

假设 catalog 应用监听 `0.0.0.0:8080`，从 `/etc/study-config/app.conf` 读取配置，并实现三种探针：`/health/startup` 表示初始化完成，`/health/ready` 表示可以接新业务，`/health/live` 表示进程仍能正常推进。只有真实应用实现这些含义后，探针配置才成立，不能拿随便一个返回 200 的路径替代。

镜像 `registry.example.com/study/catalog:DEMO` 是教学占位，未验证可拉取或运行。本例定义的配置语法为 `listen=地址:端口`，例如 `listen=0.0.0.0:8080`，不假定任意真实应用都支持这种格式。

本例每个 Pod 只有一个应用容器，CPU request=250m、limit=1，内存 request=256Mi、limit=512Mi；没有 init 和 overhead 时，每个 Pod 的请求就是 250m/256Mi，QoS 为 Burstable。两个期望副本共请求 500m/512Mi，不代表已经预分配了这些物理内存。

## 2. Namespace、配置、Deployment 和 Service

[![catalog：所有权、选择、配置与扩缩容关系](/assets/notes/kubernetes/k8s-catalog-case-relationships.svg)](/assets/notes/kubernetes/k8s-catalog-case-relationships.svg)

图中实线表示所有权或生命周期关联，虚线分别标明标签选择、配置引用与控制行为。Service 不管理 Deployment；HPA 不直接创建 Pod；ConfigMap 通过卷提供文件，不主动调用应用。HPA 是第 5 节可选接入的控制器，初始清单不包含它。

下面的资源结构相互对应。用于实际实验前，需按上述契约补齐镜像与应用行为，再对照下一节的预期逐项验证。

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: study
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: catalog-config
  namespace: study
data:
  app.conf: |
    listen=0.0.0.0:8080
    log_level=info
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: catalog
  namespace: study
spec:
  replicas: 2
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
          image: registry.example.com/study/catalog:DEMO
          ports:
            - name: http
              containerPort: 8080
          resources:
            requests:
              cpu: 250m
              memory: 256Mi
            limits:
              cpu: "1"
              memory: 512Mi
          startupProbe:
            httpGet:
              path: /health/startup
              port: http
            periodSeconds: 5
            failureThreshold: 24
          readinessProbe:
            httpGet:
              path: /health/ready
              port: http
            periodSeconds: 5
          livenessProbe:
            httpGet:
              path: /health/live
              port: http
            periodSeconds: 10
          volumeMounts:
            - name: config
              mountPath: /etc/study-config
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: catalog-config
---
apiVersion: v1
kind: Service
metadata:
  name: catalog
  namespace: study
spec:
  selector:
    app: catalog
  ports:
    - name: http
      port: 80
      targetPort: http
```

Service 选的是同命名空间 Pod 的 `app=catalog` 标签。客户端访问 Service 的 port=80，`targetPort: http` 引用后端 Pod 名为 http 的容器端口，该声明为 8080。`containerPort` 不会自动让进程监听，应用必须实际监听 `0.0.0.0:8080`。

Startup Probe 成功前，readiness/liveness 暂不执行。readiness 失败通常影响就绪状态与普通服务后端资格；liveness 达到失败条件会触发容器终止及适用重启。[kubelet 与探针](/articles/kubernetes-kubelet.html)及 [Pod 生命周期](/articles/kubernetes-pod-lifecycle.html)分别展开节点执行与终止条件。

## 3. 预期观察与失败分支

| 阶段           | 条件满足时的预期                              | 如果没有发生                               |
| -------------- | --------------------------------------------- | ------------------------------------------ |
| 调度和启动     | 两个 Pod 逐步进入运行、探针成功               | 检查事件、资源、镜像和挂载，不先改 Service |
| 服务发现       | Service 关联到相应 Slice，端点条件随 Pod 变化 | 检查标签、命名空间、探针和控制器           |
| 业务访问       | 调用 Service 80 进入符合条件的后端 8080       | 分开 DNS、转发、Pod 网络和应用监听         |
| ConfigMap 修改 | 普通卷投射后续可能反映新文件                  | 区分文件传播与应用是否重新读取             |
| 模板更新       | 按 maxSurge=1/maxUnavailable=0 推进新旧副本   | 容量不足或新 Pod 不就绪可能卡住            |

本例约定应用启动时读取配置，不承诺自动热重载。文件改变后，若应用不重读，应通过受控模板发布让替代实例读取新配置；只修改 ConfigMap 不自动修改 Deployment 的 Pod 模板。配置回滚也需单独管理，不是 rollout undo 一并还原。

### EndpointSlice 的状态变化

适用的 EndpointSlice Controller 根据 Service selector 与 Pod 状态维护端点，不由 Deployment 名称自动转换，也不是 Service 本身直接启动后端。

| Pod 状态                    | 本例默认设置下的预期                                                 |
| --------------------------- | -------------------------------------------------------------------- |
| Running、Ready=true、未终止 | 通常为就绪后端，仍需看其他条件与传播                                 |
| Running、Ready=false        | 普通就绪后端资格不满足；不代表进程已经退出                           |
| 正在终止                    | 通常 ready=false、terminating=true；serving 可表达终止中是否仍能服务 |
| 已删除                      | 相关端点最终移除，不保证所有数据平面瞬间同步                         |

`publishNotReadyAddresses` 可改变 ready 语义；本例未设置它。终止端点的实际使用还取决于代理模式、流量策略及 serving 等条件；已有连接也可能继续存在。[1.28 EndpointSlice 条件生成](https://github.com/kubernetes/kubernetes/blob/v1.28.0/staging/src/k8s.io/endpointslice/utils.go)

### ConfigMap：文件变化与应用采用分开验证

假设将 log_level 从 info 改成 debug：API 对象更新后，kubelet 后续协调普通 ConfigMap 卷投射，文件可能在传播延迟后变化，不承诺固定秒数。应用是否采用新值取决于重读或热重载能力；本例约定只在启动时读取，因此还需受控替换 Pod。仅修改 ConfigMap 不会自动改变 Deployment Pod Template，回滚 Deployment 也不自动还原 ConfigMap。

| 交付方式              | 更新后的现有容器行为                           |
| --------------------- | ---------------------------------------------- |
| 环境变量              | 已启动进程的环境不会自动更新，通常需替换实例   |
| 普通 ConfigMap Volume | kubelet 后续可更新投射文件；应用需自行采用     |
| subPath 挂载          | 不接收同样的自动投射更新，不能照搬普通卷的推演 |

### 两副本滚动更新

给定旧版本两个 Pod 均健康、容量充足，并且没有 HPA 同时改变期望数，修改 Pod Template 会形成新的 ReplicaSet。下面是可能的教学快照，不是所有内部动作必须按固定线性时序执行：

| 阶段             | 旧副本 | 新副本 | 判断                                      |
| ---------------- | -----: | -----: | ----------------------------------------- |
| 初始             |      2 |      0 | 旧版本可用                                |
| 新建             |      2 |      1 | maxSurge=1，新增实例尚未 Available        |
| 新实例 Ready     |      2 |      1 | 还需连续 Ready 满 minReadySeconds=10      |
| 新实例 Available |      1 |      1 | 预算允许后可缩减旧 ReplicaSet，再继续推进 |
| 完成             |      0 |      2 | 新版本就绪、可用并通过业务验收            |

终止中的旧 Pod 仍可能占用资源，进程总数不一定等于表中受控活动副本数。maxUnavailable=0 约束发布预算，不保证任意故障下零中断。进度超过 progressDeadlineSeconds=600 可报告发布未推进，Deployment 不因此自动回滚，更不会还原数据库和所有外部资源。

## 4. 退出和排空由谁完成

30 秒终止宽限是处理预算，不保证所有请求都能完成。应用需处理 SIGTERM，停止接纳新工作并在期限内处理适用存量；端点和数据平面传播是另一条路径，旧连接也可能继续存在。没有实际应用和负载测试，不能将该配置宣传为零停机。

| 机制                          | 主要管理对象                       |
| ----------------------------- | ---------------------------------- |
| Deployment maxUnavailable     | Deployment 自身更新过程的可用预算  |
| PDB                           | 适用的自愿中断与 Eviction API 请求 |
| terminationGracePeriodSeconds | 单个 Pod 的终止宽限预算            |
| Readiness Probe               | 应用是否适合接收新请求的检查输入   |

可选 PDB（Pod Disruption Budget，Pod 中断预算）教学清单，未创建：

```yaml
apiVersion: policy/v1
kind: PodDisruptionBudget
metadata:
  name: catalog
  namespace: study
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: catalog
```

假定状态已同步、两个副本健康且没有其他在途驱逐，健康数 2、期望最低健康数 1，可用驱逐预算为 1。一个副本不可用时预算可能降为 0，需以 PDB 实际状态和适用条件为准。PDB 不直接控制 Deployment 自身滚动更新，不以相同预算阻止直接删除，也不能阻止机器断电。本轮不执行驱逐或节点维护。

## 5. 再接入 HPA

第 25 章的 HPA 指向同名 catalog Deployment，资源指标 API 可用才有计算输入。本例单容器 CPU request=250m；独立假设四个同配置 Pod 各使用 200m，当前利用率为 80%，目标为 50%。忽略其他修正与约束后的基础建议：

```text
ceil(4 × 80 / 50) = 7
```

这缺失指标、未就绪样本、稳定窗口、扩缩速率和 min/max 副本数都可能改变最终建议。

这是独立的四副本纸面算例；前面资源清单的初始期望仍为两个副本。增加副本还要考虑预算与配额，并经过调度、启动与就绪；HPA 工作后，Helm、GitOps、人工 scale 等写入者也不应持续用固定 replicas=2 覆盖它。

### 实践验证计划（尚未执行）

先确认 Context、命名空间和权限，准备实现本节契约的真实镜像与应用代码；不能根据 YAML 推断业务性能和可用性。HPA 还要求实际可用的资源指标 API，PDB 驱逐实验需要另行明确授权和恢复方案。

| 阶段     | 验证内容与证据                                                 |
| -------- | -------------------------------------------------------------- |
| 对象创建 | Namespace、ConfigMap、Deployment、Service 的名称、标签和引用   |
| Pod 启动 | 镜像可拉取、卷文件、监听地址、三个探针及事件                   |
| 服务发现 | Service selector、端口、EndpointSlice 地址与条件，实际请求路径 |
| 配置更新 | API 对象、卷文件传播与应用采用分开记录                         |
| 滚动发布 | 新旧 ReplicaSet、Ready、Available、确实命中新版本的业务响应    |
| 优雅终止 | SIGTERM、进程退出、端点状态和在途请求，记录时间线              |
| HPA      | 指标有效性、建议副本、实际/Ready 副本、业务收益                |
| PDB      | 适用 Eviction API 的预算与拒绝行为，区别直接删除               |

只读观察命令；即使只读，结果和日志也需按权限读取并脱敏：

```bash
kubectl config current-context
kubectl get deploy,pod,svc -n study
kubectl get endpointslice -n study -l kubernetes.io/service-name=catalog
kubectl get configmap catalog-config -n study
kubectl describe hpa catalog -n study
kubectl get pods -n study -o wide
kubectl get pdb catalog -n study
```

记录版本、配置、观察时间、Pod UID、预期、实际结果与尚未确认条件。以上命令和测试均未在真实集群执行。

## 6. 回到对应章节

- [第 7 章](/articles/kubernetes-kubelet.html)：kubelet 与探针执行。
- [第 12 章](/articles/kubernetes-api-yaml-labels.html)：YAML、标签和模板层级。
- [第 13 章](/articles/kubernetes-pod-lifecycle.html)：Pod 生命周期与终止。
- [第 14 章](/articles/kubernetes-resources-pdb.html)：request、QoS、普通 init 和 PDB。
- [第 15 章](/articles/kubernetes-deployment.html)：发布预算、历史和回退范围。
- [第 19 章](/articles/kubernetes-service-endpointslice.html)：端口与 EndpointSlice 条件。
- [第 21 章](/articles/kubernetes-configmap-secret.html)：配置投射、subPath 与应用重载。
- [第 25 章](/articles/kubernetes-hpa.html)：指标、行为约束和实际容量。

先围绕同一组对象关系完成推理，再换成真实镜像、探针和集成条件进行隔离验证。附录是实验计划，不是已完成的应用运行记录。
