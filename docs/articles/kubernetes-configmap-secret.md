---
id: kubernetes-configmap-secret
title: 第二十一章 ConfigMap 与 Secret 配置交付
description: "ConfigMap 保存非敏感配置；Secret 为敏感数据提供专门的 API 类型和使用方式。应用镜像、配置对象和 Pod 是不同资源，它们的版本与生命周期也要分别管理。"
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
order: 21
---

# 第二十一章 ConfigMap 与 Secret 配置交付

> Kubernetes 1.28 背景。关注配置怎样进入容器、什么时候更新和怎样控制泄露风险。没有创建、读取或输出真实 Secret。

## 1. 把配置与镜像分开

ConfigMap（配置映射）保存非敏感配置；Secret（敏感数据资源）提供专门的 API 类型和使用方式。应用镜像、配置对象和 Pod 是不同资源，它们的版本与生命周期也要分别管理。

Secret 中常见的 Base64 是编码，不是加密。它可以直接解码，不应被贴到公开仓库、问题截图或构建日志里。安全还依赖 RBAC、存储加密、传输保护、节点权限及应用如何使用凭据。[1.28 Secret 安全边界](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/secret.md)

| 字段                 | 含义                                                 |
| -------------------- | ---------------------------------------------------- |
| ConfigMap data       | UTF-8 字符串配置                                     |
| ConfigMap binaryData | 二进制字节；在 YAML/JSON 中用 Base64 表达，不是加密  |
| Secret data          | 字节数据在 YAML/JSON 中的 Base64 编码表示            |
| Secret stringData    | 接受明文字符串输入的便利字段，经 API 处理合并到 data |

同一 Secret 键同时出现在 data 与 stringData 时，stringData 的输入优先；它是只写输入字段，不会作为同名字段正常回读，也不会让持久化数据更安全。Server-Side Apply（服务端应用，SSA）涉及字段所有权，1.28 官方文档明确提醒 stringData 与其配合不佳，不应把它当成可任意反复应用的通用声明方案；应按团队工具核实管理方式。改用 data 也只是改变输入形式，不构成加密。[1.28 Secret 字段与 SSA 注意事项](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/secret.md)

不要默认集群已启用 etcd 静态加密，需要核对实际配置；RBAC（Role-Based Access Control，基于角色的访问控制）应最小授权，能创建或访问相关 Pod、进入节点的身份也可能扩大暴露范围。环境变量、调试输出和应用日志都可能泄露凭据。读取、轮换与撤销是不同流程，更新 Secret 也不保证旧凭据已在外部系统失效。本章不使用真实 Secret 实验，不打印真实密码、Token 或私钥。

`immutable: true` 限制对象数据后续修改，不是磁盘加密或防读取开关。对象更新受限后，配置发布流程也需要采用替代对象等方式管理。

## 2. 环境变量、文件与挂载关系

ConfigMap 和 Secret 都可通过适用的环境变量或卷投射方式提供给容器。配置一般需要在 Pod 所在命名空间可引用，不能靠同名跨命名空间自动找到。

以下保存为 `catalog-config-demo.yaml`，使用同一份**非敏感** ConfigMap 对照三种交付方式，并让应用仅在启动时读取普通卷文件。固定版本 busybox:1.36.1 实际提供 8080 静态 HTTP 服务，不是附录 B 的占位程序。

前置条件为能拉取镜像的 Linux 1.28 隔离集群、专用 study 命名空间与相应资源权限。本章是独立实验：不要覆盖前章尚在运行的 catalog 或已有 catalog-config；先清理自己前章的实验，或另选命名空间并同步修改所有 YAML 和命令。本次未运行清单或访问任何实际配置。

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: catalog-config
  namespace: study
data:
  app.conf: |
    log_level=info
    feature_enabled=false
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
  template:
    metadata:
      labels:
        app: catalog
    spec:
      containers:
        - name: app
          image: busybox:1.36.1
          command: ["sh", "-ec"]
          args:
            - |
              cp /etc/study-config/app.conf /tmp/config-at-start
              mkdir -p /www
              cp /tmp/config-at-start /www/index.html
              exec httpd -f -p 8080 -h /www
          ports:
            - name: http
              containerPort: 8080
          readinessProbe:
            httpGet:
              path: /
              port: http
            periodSeconds: 2
          env:
            - name: CATALOG_CONFIG
              valueFrom:
                configMapKeyRef:
                  name: catalog-config
                  key: app.conf
          volumeMounts:
            - name: config
              mountPath: /etc/study-config
              readOnly: true
            - name: config
              mountPath: /etc/study-subpath.conf
              subPath: app.conf
              readOnly: true
      volumes:
        - name: config
          configMap:
            name: catalog-config
            items:
              - key: app.conf
                path: app.conf
```

`volumes` 定义数据来源，`volumeMounts` 定义容器中的挂载位置，通过卷名关联。Deployment 的对应位置在 `spec.template.spec` 内，Pod 则直接在 `spec`；Service 没有这样的容器模板，不能套用这段挂载配置。

## 3. items、subPath 与原目录

`items` 可选择配置键并映射成卷内相对文件路径；`mountPath` 是容器内路径；`subPath` 选择卷内子路径。三者指向不同层级。

本例 items 把键 app.conf 映射为卷内 app.conf，因此 subPath 也写 app.conf。若 items.path 改为 files/app.conf，subPath 必须引用 files/app.conf，而不是继续把它当成 ConfigMap 键的别名。

把卷挂到已有目录上，会遮蔽该挂载位置原本可见的内容，不等于物理删除镜像中的文件。subPath 可以只挂一个文件，但会改变更新语义。

通过 subPath 投射 ConfigMap 或 Secret 时，不能期待与普通卷投射相同的自动更新效果。如果应用尝试通过软链接等方式处理更新，还需验证其打开文件的方式和实际更新行为，不能把某种路径技巧当作通用的热更新保证。

## 4. 配置投射与应用生效 {#_4-配置更新至少有两个阶段}

[![ConfigMap / Secret：配置更新到应用生效](/assets/notes/kubernetes/k8s-config-delivery.svg)](/assets/notes/kubernetes/k8s-config-delivery.svg)

| 消费方式     | 已运行容器中的典型更新语义 | 还需处理                 |
| ------------ | -------------------------- | ------------------------ |
| 环境变量     | 不随对象修改自动刷新       | 受控替换容器或 Pod       |
| 普通卷投射   | 可能在协调与缓存传播后更新 | 应用是否重新读取或重载   |
| subPath 挂载 | 不提供相同的自动更新效果   | 采用合适的发布或替换方式 |

配置对象更新、容器可见内容更新、应用实际采用新配置，是三个不同阶段，需要分别验收。如果应用只在启动时读取一次配置，即使文件已更新，也不会自动采用新内容。普通卷更新受 kubelet 同步与所用缓存/Watch 传播影响，不承诺固定秒数；应用持有旧文件描述符等情况也可能继续看到旧内容。不可变对象则需要另一套变更流程。[1.28 ConfigMap 消费与更新说明](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/configmap.md)

常见做法包括配置版本化、Pod 模板校验和触发发布，或采用经过审核的重载机制；选哪一种要看应用能力。变更方案应明确配置如何交付、应用如何采用，以及失败时怎样回退。

### 4.1 对照配置更新实验

以下 create/apply/patch/delete 是隔离实验资源变更，未执行。部署后先选择一个实际 catalog Pod 名称，下面统一以 POD_NAME 表示；连续观察同一 Pod UID，避免 Deployment 选择到不同实例造成误判：

```bash
# 仅当 study 不存在且专供本实验时创建
kubectl create namespace study
kubectl apply -f catalog-config-demo.yaml
kubectl rollout status deployment/catalog -n study --timeout=180s
kubectl get pods -n study -l app=catalog -o wide
kubectl get pod POD_NAME -n study -o jsonpath='{.metadata.uid}{"\n"}'
# 仅观察本实验的非敏感 ConfigMap 内容
kubectl exec POD_NAME -n study -c app -- printenv CATALOG_CONFIG
kubectl exec POD_NAME -n study -c app -- cat /etc/study-config/app.conf
kubectl exec POD_NAME -n study -c app -- cat /etc/study-subpath.conf
kubectl exec POD_NAME -n study -c app -- cat /tmp/config-at-start
kubectl exec POD_NAME -n study -c app -- wget -qO- -T 5 http://127.0.0.1:8080/
```

预期初始各处均为 log_level=info、feature_enabled=false。printenv/cat 在这里仅因内容明确非敏感而使用，不能照搬到真实 Secret、密码或 Token。HTTP 返回的是启动时复制的配置，不是动态读取源文件。

把对象更新为 debug/true，使用 JSON 字符串中的换行转义表示多行 app.conf；这是对专用测试 ConfigMap 的变更：

```bash
kubectl patch configmap catalog-config -n study --type=merge -p '{"data":{"app.conf":"log_level=debug\nfeature_enabled=true\n"}}'
kubectl get configmap catalog-config -n study -o yaml
kubectl get pod POD_NAME -n study -o jsonpath='{.metadata.uid}{"\n"}'
kubectl exec POD_NAME -n study -c app -- printenv CATALOG_CONFIG
kubectl exec POD_NAME -n study -c app -- cat /etc/study-config/app.conf
kubectl exec POD_NAME -n study -c app -- cat /etc/study-subpath.conf
kubectl exec POD_NAME -n study -c app -- cat /tmp/config-at-start
kubectl exec POD_NAME -n study -c app -- wget -qO- -T 5 http://127.0.0.1:8080/
```

| 观察对象                          | 同一持续运行容器中的预期结果                    |
| --------------------------------- | ----------------------------------------------- |
| API 保存的 ConfigMap              | debug/true                                      |
| CATALOG_CONFIG 环境变量           | 仍为 info/false                                 |
| /etc/study-config/app.conf 普通卷 | 经同步与缓存传播后变为 debug/true，需要重复观察 |
| /etc/study-subpath.conf           | 不接收普通卷那样的自动更新，仍为启动时内容      |
| /tmp/config-at-start 与 HTTP 页面 | 仍为 info/false，因为应用只在启动时复制一次     |

如果容器重启、Pod 替换或配置尚未同步，读数可能不同；先核对 UID、restartCount 和 Events。文件更新不代表业务已采用；本实验没有实现热重载。

恢复原文件中的 info/false，并在同一 Pod 上重新检查对象、投射文件与应用输出，普通卷恢复也可能延迟：

```bash
kubectl apply -f catalog-config-demo.yaml
# 清理自己创建的 Deployment 和非敏感 ConfigMap
kubectl delete -f catalog-config-demo.yaml
```

不要把这两步当成已完成运行验证；清理前应先完成观察。如果要让所有消费方式采用一版新值，应设计受控 Pod 发布或重载，并验收新实例，而不是假定修改 ConfigMap 自动重启所有 Pod。

### 4.2 不可变对象与版本化发布

以下是两个完整的版本化非敏感 ConfigMap，供结构阅读，不与前面的可变 catalog-config 混用：

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: catalog-config-v1
  namespace: study
immutable: true
data:
  app.conf: |
    log_level=info
    feature_enabled=false
---
apiVersion: v1
kind: ConfigMap
metadata:
  name: catalog-config-v2
  namespace: study
immutable: true
data:
  app.conf: |
    log_level=debug
    feature_enabled=true
```

immutable=true 限制原地修改数据，不加密、不阻止授权读取。新建 v2 不会改变仍引用 v1 的 Pod。发布时应把 Pod Template 中 configMapKeyRef.name 与 volumes[].configMap.name 等所有适用引用一同改为 v2，保留 items、挂载关系并受控发布；新 Pod 再读取新配置。回退也要明确切回哪一版引用，并检查应用兼容性。

删除 v1 前，需检查运行实例、工作负载模板及可回滚历史是否仍需它；只查看一个 Pod 不足以证明可以删除。两个版本示例未部署，不提供批量删除配置的通用命令。

## 5. 镜像凭据与服务账户

`imagePullSecrets` 引用适用的仓库凭据，用于镜像获取，不等于把该秘密作为业务环境变量。Pod 可以显式引用，ServiceAccount 等配置也可能影响注入，不能概括成“只对一个 Pod 有效”。

以下是 Pod spec 下的局部引用，不是独立清单，也不包含实际仓库认证数据：

```yaml
imagePullSecrets:
  - name: registry-credential
```

引用的适用 Secret 需要位于 Pod 所在 Namespace。ServiceAccount（服务账户）可以提供新 Pod 的默认镜像凭据引用，但 Kubernetes API 身份/RBAC 与镜像仓库认证是不同问题；拉取凭据不会自动变成业务容器的环境变量。前面的 BusyBox 实验不要求存在这个教学凭据。[1.28 镜像拉取 Secret](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/configuration/secret.md)

避免把密码放在命令行示例中。生产凭据的创建、轮换和撤销应有独立流程，也要避免在 `get -o yaml`、模板渲染和差异报告中泄露。

验证配置交付时，检查对象存在性、引用关系、挂载或环境配置，以及应用采用的配置版本；这些证据通常无需暴露真实密码。

## 6. 按交付阶段定位故障

| 现象                    | 优先排查                                                 |
| ----------------------- | -------------------------------------------------------- |
| 配置对象不存在          | 名称、Namespace、Pod 引用与 Events                       |
| 某个键未正确投射        | items、键名与卷内相对路径                                |
| 更新对象后环境变量不变  | 已运行容器的环境变量更新语义                             |
| 卷文件没有更新          | kubelet 同步、缓存、subPath 与不可变配置                 |
| 文件变了而应用未生效    | 应用读取时机、旧文件描述符与重载机制                     |
| 镜像拉取认证失败        | imagePullSecrets、仓库认证、镜像引用及拉取事件           |
| Secret API 读取权限不足 | RBAC、实际访问身份与授权；不能直接推导成所有卷消费都失败 |

这些是排查方向，不是唯一根因。先读状态、事件与引用关系，无需打印密码或 Token；不要把重启所有 Pod 当作唯一修复方式。

[catalog 案例：配置文件与应用重载约定](/articles/kubernetes-practice-guide.html) · [返回本册目录](/collections/kubernetes/)
