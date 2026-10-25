---
id: kubernetes-practice-guide
title: 附录 B　catalog 贯穿案例
description: 返回本册目录
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
order: 91
---

# 附录 B　catalog 贯穿案例

[返回本册目录](/collections/kubernetes/)

这是新增的合成案例，用于串联第 12、14、15、19、21、25 章。下文的对象关系完整，但应用镜像是占位符，也未提供真实程序或完成集群测试，因此不能直接复制运行。

## 1. 先约定应用契约

假设 catalog 应用监听 `0.0.0.0:8080`，从 `/etc/study-config/app.conf` 读取配置，并实现三种探针：`/health/startup` 表示初始化完成，`/health/ready` 表示可以接新业务，`/health/live` 表示进程仍能正常推进。只有真实应用实现这些含义后，探针配置才成立，不能拿随便一个返回 200 的路径替代。

本例每个 Pod 只有一个应用容器，CPU request=250m、limit=1，内存 request=256Mi、limit=512Mi；没有 init 和 overhead 时，每个 Pod 的请求就是 250m/256Mi，QoS 为 Burstable。两个期望副本共请求 500m/512Mi，不代表已经预分配了这些物理内存。

## 2. Namespace、配置、Deployment 和 Service

下面是可以互相对应的资源结构，镜像和应用行为仍需按上述契约补齐。没有附执行命令，也没有将预期状态写成实测结果。

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
    listen=8080
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

Service 选的是同命名空间的 Pod 标签，targetPort=http 对应容器端口名，应用还必须真实监听 8080。标准端点控制器据实际 Pod 状态维护 Slice，而不是把 Deployment 名字直接转换成可用后端。

## 3. 预期观察与失败分支

| 阶段           | 条件满足时的预期                              | 如果没有发生                               |
| -------------- | --------------------------------------------- | ------------------------------------------ |
| 调度和启动     | 两个 Pod 逐步进入运行、探针成功               | 检查事件、资源、镜像和挂载，不先改 Service |
| 服务发现       | Service 关联到相应 Slice，端点条件随 Pod 变化 | 检查标签、命名空间、探针和控制器           |
| 业务访问       | 调用 Service 80 进入符合条件的后端 8080       | 分开 DNS、转发、Pod 网络和应用监听         |
| ConfigMap 修改 | 普通卷投射后续可能反映新文件                  | 区分文件传播与应用是否重新读取             |
| 模板更新       | 按 maxSurge=1/maxUnavailable=0 推进新旧副本   | 容量不足或新 Pod 不就绪可能卡住            |

本例约定应用启动时读取配置，不承诺自动热重载。文件改变后，若应用不重读，应通过受控模板发布让替代实例读取新配置；只修改 ConfigMap 不自动修改 Deployment 的 Pod 模板。配置回滚也需单独管理，不是 rollout undo 一并还原。

## 4. 退出和排空由谁完成

30 秒终止宽限是处理预算，不保证所有请求都能完成。应用需处理 SIGTERM，停止接纳新工作并在期限内处理适用存量；端点和数据平面传播是另一条路径，旧连接也可能继续存在。没有实际应用和负载测试，不能将该配置宣传为零停机。

maxUnavailable=0 控制 Deployment 更新预算，不是对直接删除或机器断电的保护。若增加 `policy/v1` PDB，应按业务可承受能力设计 minAvailable 等条件；经 Eviction API 的维护与直接删除必须分别判断。

## 5. 再接入 HPA

第 25 章的 HPA 指向同名 catalog Deployment，资源指标 API 可用才有计算输入。本例单容器 CPU request=250m，若四个同配置 Pod 各使用 200m，当前利用率为 80%；目标 50% 时，未计其他约束的比例建议为 ceil(4×80/50)=7。

这只是纸面推导，并不表示上面的初始两个副本已经自动变成四个。增加副本还要考虑预算与配额，并经过调度、启动与就绪；HPA 工作后，声明式工具也不应持续用固定 replicas=2 覆盖它。

## 6. 回到对应章节

- 第 12 章解释 YAML、标签和模板层级。
- 第 14 章解释 request、QoS、普通 init 和 PDB。
- 第 15 章解释发布预算、历史和回退范围。
- 第 19 章解释 Service 端口与 EndpointSlice 条件。
- 第 21 章解释配置投射、subPath 与应用重载。
- 第 25 章解释指标、行为约束和实际容量。

先围绕同一组对象关系完成推理，再换成真实镜像、探针和集成条件进行隔离验证，比每章使用一套互不关联的片段更容易形成整体理解。
