---
id: kubernetes-cni-network
title: 第九章 CNI 与 Pod 网络
description: "Pod 有一个 IP、Service 有一个地址、应用能通过服务名访问，它们看起来都与网络有关，实际由不同机制共同完成。"
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
order: 9
---

# 第九章 CNI 与 Pod 网络

> 本章以 Kubernetes 1.28 的 Linux 普通 Pod 为背景，沿运行时网络准备、地址管理和通信验证展开。`hostNetwork`、Windows 及特殊实现需单独核对。

## 1. 先把三类网络问题分开

Pod 有一个 IP、Service 有一个地址、应用能通过服务名访问，它们看起来都与网络有关，实际由不同机制共同完成。

| 问题                     | 主要观察范围                         | 不能代替的检查                 |
| ------------------------ | ------------------------------------ | ------------------------------ |
| Pod 怎样获得网络连接？   | 运行时、CNI 集成、网络方案           | 有 IP 不代表跨节点和策略都正确 |
| 一个稳定入口怎样选后端？ | Service、EndpointSlice、服务数据平面 | 后端集合正确不等于应用端口正常 |
| 服务名怎样变成地址？     | Pod DNS 配置、集群 DNS               | 解析成功不代表业务连接成功     |

CNI（Container Network Interface，容器网络接口）定义网络配置和插件调用约定。它可以用于 Kubernetes 之外的容器场景；选择具体网络方案后，还要确认采用哪种数据路径和地址管理方式。

普通 Pod 在集群网络中获得 Pod IP，同一 Pod 的容器通常共享 Network Namespace（网络命名空间），即接口、地址、路由和端口空间等网络视图，因此可以通过 `localhost` 通信。不同 Pod 通常有各自的网络环境，不能用自己的 localhost 访问另一个 Pod。

在没有有意隔离的情况下，Pod-to-Pod 连通性应满足 Kubernetes 网络模型；不同节点上的普通 Pod 也可以通过 Pod IP 通信，不必先经过 Service。实际连接还受 NetworkPolicy、防火墙、路由和网络实现影响。**Pod 网络与 Service 网络解决不同问题，获得 IP 也不能证明跨节点通信已通。** [Kubernetes 网络模型](https://kubernetes.io/docs/concepts/services-networking/)

## 2. CNI 在 Pod 创建过程的什么位置

在常见 containerd CRI 集成中，kubelet 发起运行时请求，运行时的网络集成依据配置调用 CNI 插件，为 Pod 级网络环境配置连接。不要把它简化成“调度器直接给容器分配网卡”。

主要关心四类事情：网络接口如何建立、地址如何分配、路由或转发表如何配置、失败时如何清理。IPAM（IP Address Management，IP 地址管理）负责地址分配、跟踪和回收等，可由独立插件、网络方案自身或云平台能力实现。CNI 约定调用和结果，不要求所有方案都用同一种 IPAM。

以普通 Linux Pod 的 Sandbox 准备为例，可按以下职责理解：

1. kubelet 通过 CRI（Container Runtime Interface，容器运行时接口）的 `RunPodSandbox` 请求准备 Pod 级运行环境。
2. 运行时网络集成依据网络配置和目标网络命名空间等参数调用 CNI 插件。
3. 插件按实现调用 IPAM 或相关地址管理能力，为目标网络准备地址。
4. 配置网络接口、地址、路由等，或通过插件链继续调整网络配置；具体先后和工作分配取决于方案。
5. 插件返回配置结果或错误，运行时据此继续完成 Sandbox 等准备；失败则结合错误信息和清理结果排查。

veth（Virtual Ethernet，虚拟以太网设备）是一对相连的虚拟接口，常用于连接不同网络命名空间；Bridge（网桥）可提供二层转发。它们是常见实现手段，不是所有 CNI 方案的固定组成部分。CNI `ADD` 配置网络，`DEL` 用于移除配置和清理；后续业务包沿已建立的数据路径传输，不是逐包调用 CNI 插件。运行时内部关系见[第八章](/articles/kubernetes-container-runtime.html#_2-1-containerd-1-7-的典型-linux-实现)。

插件配置可以有链式组合。前面的插件建立连接，后面的插件对结果继续调整，具体能力取决于配置和实现。CNI 规范版本也不同；本章采用 [CNI spec 1.0.0](https://raw.githubusercontent.com/containernetworking/cni/spec-v1.0.0/SPEC.md)核对基本的 ADD、DEL、CHECK 与结果传递，不把后来规范的新操作反推成所有 1.28 环境必然支持的能力。

网络准备失败时，业务容器可能尚未进入可运行阶段。与“Pod 没启动”相比，事件中的错误往往更有助于定位故障边界。但出现 CNI 错误，并不一定是插件二进制损坏，也可能涉及地址池耗尽、外部依赖、配置不一致或主机网络问题。

## 3. CNI 接口与网络实现方式 {#_3-为什么-cni-不等于-overlay}

Overlay Network（覆盖网络）常用额外封装，把逻辑的 Pod 网络承载在底层节点网络上。它是一类网络实现路线，不是 CNI 接口的同义词。

另一些方案可以采用原生路由，或与云网络地址和网卡能力集成；同一个网络项目也可能支持多种模式。因此，仅写“使用某某 CNI”还不足以说明实际数据路径，还需记录模式、地址管理、路由、MTU 和策略等条件。

MTU（Maximum Transmission Unit，最大传输单元）描述链路上可传输的数据包大小限制；额外封装会占用空间，需让 Pod 网络、隧道和底层路径的配置相互匹配。

| 路线       | 主要方式                              | 优先关注                           |
| ---------- | ------------------------------------- | ---------------------------------- |
| Overlay    | 在节点底层网络上封装并传输 Pod 数据包 | 底层连通、封装开销、MTU 与相关端口 |
| 原生路由   | 通过路由将数据包送到目标 Pod 网络     | 路由传播、可达性与回程路径         |
| 云网络集成 | 使用云平台的地址、路由或网卡能力      | 地址资源、云网络限制和环境差异     |

项目与路线不是一一对应，Calico、Cilium 等项目可以有不同模式。性能还受配置、负载、硬件和封装影响，本章不在缺少对照实验时作固定排名。[Calico v3.26.1 项目说明](https://github.com/projectcalico/calico/blob/v3.26.1/README.md)、[Cilium v1.14.0 路由模式](https://github.com/cilium/cilium/blob/v1.14.0/Documentation/network/concepts/routing.rst)

[![Pod 网络：两节点布局与跨节点路径](/assets/notes/kubernetes/k8s-cni-two-nodes.png)](/assets/notes/kubernetes/k8s-cni-two-nodes.png)

图中用双节点布局区分创建期配置与运行期通信：

1. 跨节点网络可采用封装、原生路由或云网络集成，具体路径由所选方案决定。
2. 节点、Pod 和 Service 地址分别规划，图中以角色表示。
3. CNI ADD 在网络准备阶段配置连接，后续业务数据包沿已建立的数据路径传输。

图中省略的 veth、网桥、隧道或云网卡，不代表它们永远不存在；只是不能在一张通用图里把其中一种结构写成规范要求。

## 4. 地址段、IPAM 与可达性

“控制器分配节点 Pod CIDR，再由插件分配 Pod IP”是一种配置路线；其他网络方案可以采用不同的地址管理机制。

一些配置会使用 Node 的 PodCIDR，其他方案可能通过自身 IPAM 或云侧分配机制管理地址。分析环境时应核对实际网络方案，而不是只看初始化命令里出现过一个 `--pod-network-cidr` 就认定所有地址都由它控制。

地址规划至少要区分节点网络、Pod 网络和 Service 地址范围。它们承担的角色不同，冲突可能导致路由歧义；但不能把任意三个看起来不同的网段就直接判定为可用，还要考虑所在网络、VPN、云路由以及其他实际地址。

拿到 Pod IP 只说明地址分配相关步骤有了结果。跨节点通信还需要合适的底层连通、转发路径和回程；策略也可能有意阻断访问。对于采用封装的网络，MTU 不合适可能导致小请求正常、大报文异常。这里列的是定位方向，不是对你的环境已确认的根因。

## 5. 按通信范围组织网络测试 {#_5-同-pod、同节点与跨节点-不是一条测试}

普通 Pod 内共享网络环境的容器通常可以通过 localhost 通信；两个不同 Pod 则不能把对方当成自己的 localhost。

同节点 Pod 之间的连接，不一定经过与跨节点相同的路径。因此“本机 Pod 能互通”只能缩小范围，不能证明跨节点网络正常。反过来，“ping 不通”也不能单独证明 TCP 业务端口不可用：ICMP 可能被限制，应用也可能根本不依赖 ICMP。

新增教学推理例子：假设 Pod A 可以访问同节点的 Pod B，却无法访问另一节点的 Pod C。下一步应对比目的端口、策略、源和目标节点及路由条件，而不是立即更换 CNI。若只有某个目标应用失败，还要回到应用监听与后端状态。

这只是通过对照缩小问题范围的教学例子，并非你的实验结果。

### 5.1 一套资源，分别验证四条访问路径 {#network-lab}

以下为隔离测试集群的教学实验。前提：正确的 `kubectl` 上下文及资源管理、exec 权限，节点可调度、镜像可获取，使用 IPv4 Pod 网络及默认集群域 `cluster.local`，测试空间没有其他策略干扰。跨节点实验需要两台可调度 Linux 节点；若只有一台，可让两个节点占位符都使用同一实际值，完成其他对照，但实验 C 必须记为未执行。

网络和策略需要明确的来源、后端及端口，故这里使用独立资源，而不修改前面 `web-demo`。先读取节点的 hostname 标签值；**只修改下方 YAML 中的占位符，不修改节点标签**。`k8s-net-demo` 必须是本实验新建的专用空间，若已存在则换名并同步调整全部清单和命令：

```bash
kubectl config current-context
kubectl get nodes -L kubernetes.io/hostname
kubectl create namespace k8s-net-demo
```

将 `NODE_A_HOSTNAME`、`NODE_B_HOSTNAME` 分别替换为实际标签值，保存为 `network-demo.yaml`。后端监听两个端口，便于稍后区分策略拒绝与端口未监听；同一 Pod 额外放一个查询容器，验证 localhost。

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: backend
  namespace: k8s-net-demo
  labels:
    app: backend
spec:
  nodeSelector:
    kubernetes.io/hostname: NODE_A_HOSTNAME
  containers:
    - name: web
      image: busybox:1.36.1
      command: ["sh", "-c"]
      args:
        - |
          mkdir -p /www
          echo backend > /www/index.html
          httpd -f -p 8081 -h /www &
          exec httpd -f -p 8080 -h /www
      readinessProbe:
        httpGet:
          path: /
          port: 8080
        periodSeconds: 2
    - name: local-client
      image: busybox:1.36.1
      command: ["sleep", "3600"]
---
apiVersion: v1
kind: Pod
metadata:
  name: frontend
  namespace: k8s-net-demo
  labels:
    role: frontend
spec:
  nodeSelector:
    kubernetes.io/hostname: NODE_A_HOSTNAME
  containers:
    - name: client
      image: busybox:1.36.1
      command: ["sleep", "3600"]
---
apiVersion: v1
kind: Pod
metadata:
  name: other-client
  namespace: k8s-net-demo
  labels:
    role: other
spec:
  nodeSelector:
    kubernetes.io/hostname: NODE_B_HOSTNAME
  containers:
    - name: client
      image: busybox:1.36.1
      command: ["sleep", "3600"]
---
apiVersion: v1
kind: Service
metadata:
  name: backend
  namespace: k8s-net-demo
spec:
  selector:
    app: backend
  ports:
    - port: 8080
      targetPort: 8080
      protocol: TCP
```

```bash
kubectl apply -f network-demo.yaml
kubectl wait --for=condition=Ready pod/backend pod/frontend pod/other-client -n k8s-net-demo --timeout=120s
kubectl get pods -n k8s-net-demo -o wide
BACKEND_IP=$(kubectl get pod backend -n k8s-net-demo -o jsonpath='{.status.podIP}')
```

等待超时应查看 Events 和容器状态，不能继续假装准备成功。先核对 `frontend` 与 `backend` 同节点，`other-client` 在不同节点；后续命令在同一个 Bash 终端使用实际 `BACKEND_IP`。

| 实验              | 执行命令                                                                                                     | 条件满足时的预期与证明范围                                                      |
| ----------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| A：同 Pod         | `kubectl exec -n k8s-net-demo backend -c local-client -- wget -qO- -T 5 http://127.0.0.1:8080`               | 返回 `backend`，说明查询容器可通过共享网络环境访问另一个容器的监听端口          |
| B：同节点 Pod IP  | `kubectl exec -n k8s-net-demo frontend -- wget -qO- -T 5 "http://$BACKEND_IP:8080"`                          | 返回页面，验证这两个 Pod 在目标端口的同节点连接                                 |
| C：跨节点 Pod IP  | `kubectl exec -n k8s-net-demo other-client -- wget -qO- -T 5 "http://$BACKEND_IP:8080"`                      | 节点确实不同时，返回页面才支持这条跨节点 TCP 路径可达；单节点不作此结论         |
| D：Service 与 DNS | `kubectl exec -n k8s-net-demo frontend -- wget -qO- -T 5 http://backend.k8s-net-demo.svc.cluster.local:8080` | 返回页面，验证这条服务名解析与 Service 访问组合路径；不能代替前面的 Pod IP 对照 |

若 D 失败，先用 `kubectl exec -n k8s-net-demo frontend -- nslookup backend.k8s-net-demo.svc.cluster.local` 分离 DNS，再检查 Service、端点和转发。测试用 HTTP 请求，不以 ICMP ping 的结果代替 TCP 判断。若只做到这里，可立即按第 6.4 节删除专用空间；继续策略实验则暂不清理。

## 6. NetworkPolicy 是另一层契约

NetworkPolicy 用 API 描述适用的网络访问约束，但需要具备相应能力的网络实现执行。创建对象成功，不等于策略已经被所有数据路径执行。

没有适用隔离策略与存在允许规则不是同一种状态。分析策略时还要分别看 ingress 和 egress、源和目标选择器及协议端口。不能用“集群有 CNI”推导出“已经按默认拒绝保护”，也不能把网络策略当成 HTTP 路径级授权。基础边界参见 [Kubernetes 1.28 NetworkPolicy](https://raw.githubusercontent.com/kubernetes/website/release-1.28/content/en/docs/concepts/services-networking/network-policies.md)；权限章节会继续区分 API 权限与网络访问权限。

### 6.1 按什么顺序判断一次连接

对支持策略的普通 Pod 网络，先分别判断源的 egress 与目标的 ingress。某方向没有策略选中并隔离时，该方向默认允许；隔离后，适用策略的允许规则取并集，不按创建先后覆盖。源出口和目标入口都需要允许，请求才可能通过这层限制。DNS、应用监听和其他网络条件仍需正常。

### 6.2 一个列表项的差别就是 AND 与 OR

以下为新增片段，位于策略 spec 的 ingress 中，仅用于比较来源集合，未部署。标签 team=frontend 是 Namespace 标签，role=client 是 Pod 标签：

```yaml
ingress:
  - from:
      - namespaceSelector:
          matchLabels:
            team: frontend
        podSelector:
          matchLabels:
            role: client
```

同一个 peer 中两个选择器同时成立：只允许 team=frontend 命名空间里的 role=client Pod。若改成两个 peer：

```yaml
ingress:
  - from:
      - namespaceSelector:
          matchLabels:
            team: frontend
      - podSelector:
          matchLabels:
            role: client
```

现在是两组来源的并集：team=frontend 命名空间中的全部 Pod，或者策略所在命名空间里的 role=client Pod。第二个 podSelector 单独出现时，不是选择所有命名空间。两个例子没有限制 ports，表示这条规则没有另加端口筛选，不应误读为只开放某个业务端口。

### 6.3 完整策略：只允许 frontend 访问后端 TCP 8080

延续第 5.1 节的三 Pod 实验。先确认网络实现支持并执行标准 NetworkPolicy，且没有其他策略为目标流量增加允许规则或施加额外限制。保存下面内容为 `backend-policy.yaml`：

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-from-frontend
  namespace: k8s-net-demo
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
    - Ingress
  ingress:
    - from:
        - namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: k8s-net-demo
          podSelector:
            matchLabels:
              role: frontend
      ports:
        - protocol: TCP
          port: 8080
```

`metadata.namespace` 确定策略所在空间，`spec.podSelector` 选择受保护的后端 Pod；`ingress.from` 才是允许来源。这里同一个 peer 中的 `namespaceSelector` 与 `podSelector` 取交集，要求来源同时位于指定空间且具有 `role=frontend`；命名空间的 `kubernetes.io/metadata.name` 是该基线版本可用的标准标签。`ports` 将这条允许规则限制为 TCP 8080。

`policyTypes: [Ingress]` 只对选中的后端入口建立隔离，不自动隔离来源的 Egress。只有 podSelector 的 peer 默认选择策略所在空间中的 Pod；多个 peer 或多条适用策略的允许集合取并集，不能靠后创建一条“更严格策略”覆盖已有允许。若另加 Egress 隔离，DNS 等正常依赖也要分别放行。该规则不检查 HTTP 路径，也不替代 API 权限和应用认证。[1.28 NetworkPolicy 语义](https://github.com/kubernetes/website/blob/release-1.28/content/en/docs/concepts/services-networking/network-policies.md)

### 6.4 验证允许、拒绝与未开放端口

先在**没有本节策略**时确认两个来源都能访问后端 8080，并额外确认 8081 也真实监听，保留成功基线：

```bash
kubectl exec -n k8s-net-demo frontend -- wget -qO- -T 5 "http://$BACKEND_IP:8080"
kubectl exec -n k8s-net-demo other-client -- wget -qO- -T 5 "http://$BACKEND_IP:8080"
kubectl exec -n k8s-net-demo frontend -- wget -qO- -T 5 "http://$BACKEND_IP:8081"
kubectl apply -f backend-policy.yaml
kubectl describe networkpolicy backend-from-frontend -n k8s-net-demo
```

策略传播后，分别发起新的连接；不复用此前已建立的连接来判断策略行为：

| 测试               | 命令                                                                                    | 预期                                 |
| ------------------ | --------------------------------------------------------------------------------------- | ------------------------------------ |
| 允许来源、允许端口 | `kubectl exec -n k8s-net-demo frontend -- wget -qO- -T 5 "http://$BACKEND_IP:8080"`     | 返回 `backend`                       |
| 其他来源、相同端口 | `kubectl exec -n k8s-net-demo other-client -- wget -qO- -T 5 "http://$BACKEND_IP:8080"` | 请求失败，例如超时；具体形式依赖实现 |
| 允许来源、其他端口 | `kubectl exec -n k8s-net-demo frontend -- wget -qO- -T 5 "http://$BACKEND_IP:8081"`     | 请求失败，即使该端口在策略前能访问   |

不将某一次超时直接归因为策略。对照 Pod 健康、监听、IP、策略选择器和网络组件证据；若拒绝组仍成功，应检查插件支持、策略传播和其他允许规则，不能仅凭对象存在宣布策略生效。非支持实现上的这些测试不能作为策略验收。

在专用测试空间中移除本节策略，再用同样请求确认 `other-client → 8080` 和 `frontend → 8081` 恢复，形成前后对照；最后清理全部实验资源：

```bash
kubectl delete networkpolicy backend-from-frontend -n k8s-net-demo
kubectl exec -n k8s-net-demo other-client -- wget -qO- -T 5 "http://$BACKEND_IP:8080"
kubectl exec -n k8s-net-demo frontend -- wget -qO- -T 5 "http://$BACKEND_IP:8081"
kubectl delete namespace k8s-net-demo
```

## 7. 不改变现场的观察方式

下面只是授权环境中的命令模板；名称、命名空间和上下文需要先确认。`kube-system` 只是常见系统组件所在位置，并不是所有网络方案的固定部署目录。

```bash
kubectl get nodes -o wide
kubectl get pods -A -o wide
kubectl describe pod POD_NAME -n NAMESPACE
kubectl get networkpolicy -n NAMESPACE
```

相比直接重装，先按以下问题整理一份简短的观察记录更有助于定位：

- 源、目标分别是什么 Pod、节点、地址族和端口？
- 失败发生在创建 sandbox、获得 IP，还是业务连接阶段？
- 同节点和跨节点、Pod 地址和 Service 地址是否表现不同？
- 是否只有某类流量、某个大小范围或某个命名空间失败？
- 最近是否改过插件配置、节点网络或访问策略？

可按下面的差异选择下一层证据，表中均是排查方向，不是已确认根因：

| 现象                               | 优先排查方向                                                                  |
| ---------------------------------- | ----------------------------------------------------------------------------- |
| `FailedCreatePodSandBox`           | 先读具体错误，检查运行时、CNI 配置、IPAM 地址资源及节点条件；并非都由网络引起 |
| 已有 Pod IP，同节点通信失败        | 应用端口监听、接口、路由和策略；有地址不等于接口与路径全部正常                |
| 同节点正常，跨节点失败             | 底层路由、封装、回程、防火墙及源目标节点差异                                  |
| 小报文正常，大报文异常             | MTU、路径 MTU、分片与重传证据；也要排除应用层限制                             |
| Pod IP 可访问，Service IP 不可访问 | Service 选择器、EndpointSlice 和服务数据平面，避免直接重装 CNI                |
| Pod IP 可访问，服务名解析失败      | Pod DNS 配置、CoreDNS、域名和解析路径；DNS 成功后仍需检查连接                 |

本章不提供清空 iptables、删除 CNI 目录、批量删除网卡的“万能修复”。这些操作会改变现场，也可能破坏已有工作负载。插件、节点与内核参数的修复必须建立在具体证据上。

## 8. 本章小结

CNI 定义如何配置网络连接，实际网络方案决定具体的数据路径与地址管理。建立了 Pod 网络以后，应用仍需要稳定的访问入口；下一章解释 Service 如何与 kube-proxy 配合，以及为什么规则更新路径与业务流量路径必须分开画。

[返回本册目录](/collections/kubernetes/) · [下一章：kube-proxy 与 Service 转发](/articles/kubernetes-kube-proxy.html)
