---
id: kafka-network-security
title: 第 21 章：网络、安全与权限边界
description: "客户端先通过配置中的初始地址获取集群元数据，再根据元数据中的 Broker 地址访问相应分区和协调者。初始地址能够连接，并不代表后续所有地址都能解析、路由可达，或与证书匹配。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - kafka
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kafka
series: kafka-learning
order: 21
---

# 第 21 章：网络、安全与权限边界

> 版本基线：Kafka Broker 3.9、Java Client 3.9 与 librdkafka v2.8.0。
>
> 学习目标：沿初始连接、安全握手、元数据地址与资源权限的顺序定位生产和消费问题。

## 1. 从 Bootstrap 获取元数据，再连接目标节点 {#_1-bootstrap-只是入口}

客户端先通过配置中的初始地址获取集群元数据，再根据元数据中的 Broker 地址访问相应分区和协调者。初始地址能够连接，并不代表后续所有地址都能解析、路由可达，或与证书匹配。

容器、NAT、内外网和多 Listener 环境尤其容易出现这种问题：服务端监听成功，却向客户端公布了仅内部可达的主机名。应核对 listeners、advertised.listeners 及适用监听器映射，不要把 0.0.0.0 的监听意义误认为客户端可使用的远端地址。

![初始与后续连接各自完成安全握手](/assets/notes/kafka/kf-security.svg)

客户端首先解析 Bootstrap 域名并建立 TCP 连接。按 Listener 协议建立 TLS，再在适用时完成 SASL 认证，随后请求 Metadata（集群及分区元数据）。客户端从返回结果取得该 Listener 对应的 Broker 公布地址，并定位分区 Leader，或通过 FindCoordinator 查找组和事务协调器。连接新节点时重新执行 DNS、TCP 和相应安全握手，再发送 Produce、Fetch 或组请求。Metadata 本身也涉及 Topic Describe 等权限，失败未必等到读写时才出现。

### Kafka 3.9 多 Listener 示例

以下是单节点、静态 KRaft 仲裁、Broker 与 Controller 合设的隔离实验配置节选。它以已经初始化的测试环境为前提。节点 ID 和端口应与该环境一致。假设内网客户端能解析 `broker-1.lab.example`，外网客户端能解析 `broker-1.example.net`，后者的 9094 直达或经 NAT 转发到这个 Broker 的 9094。地址均为教学占位。示例仅用于验证网络和 TLS，ACL 实验另用已配置身份认证与授权的环境。

```properties
process.roles=broker,controller
node.id=1
controller.quorum.voters=1@broker-1.lab.example:9093
controller.listener.names=CONTROLLER
inter.broker.listener.name=INTERNAL
listeners=INTERNAL://0.0.0.0:9092,EXTERNAL://0.0.0.0:9094,CONTROLLER://0.0.0.0:9093
advertised.listeners=INTERNAL://broker-1.lab.example:9092,EXTERNAL://broker-1.example.net:9094
listener.security.protocol.map=INTERNAL:PLAINTEXT,EXTERNAL:SSL,CONTROLLER:PLAINTEXT
listener.name.external.ssl.keystore.type=PKCS12
listener.name.external.ssl.keystore.location=/path/to/lab-broker.p12
listener.name.external.ssl.keystore.password=<keystore-password>
listener.name.external.ssl.key.password=<key-password>
listener.name.external.ssl.client.auth=none
```

`listeners` 绑定本地网卡和端口，`0.0.0.0` 表示监听所有 IPv4 接口。远端客户端使用 `advertised.listeners` 返回的实际主机名和端口。协议映射决定每个入口怎样完成安全握手。容器的内部 DNS 名可能只在容器网络有效，NAT 也可能改写端口。多 Broker 场景中，每个节点都要公布该客户端网络可达的对应端点，并使用名称匹配的证书。Controller Listener 服务仲裁和控制通信，省略于业务 advertised 列表，并应与客户端网络隔离。若节点只运行 Broker 角色，它仍需配置如何连接 Controller，但不会在本地监听 Controller 端口。

外部 Java CLI 使用 `security.protocol=SSL`，配置信任库的类型、位置及适用密码，保留主机名验证。此例的 INTERNAL 与 CONTROLLER 为明文，仅限隔离实验网络。实际启用双向 TLS 时，还需 Broker 信任客户端证书签发者，并要求客户端提供证书和私钥。

## 2. 加密、认证与授权分开

TLS（Transport Layer Security，传输层安全协议）加密连接，客户端验证服务端证书的信任链、有效期与名称。单向 TLS 由客户端验证服务端，双向 TLS（mTLS）还由服务端验证客户端证书，并可基于证书建立客户端身份。

SASL（Simple Authentication and Security Layer，简单认证与安全层）为 Kafka 连接认证客户端身份。`SASL_SSL` 在 TLS 内运行 SASL，`SASL_PLAINTEXT` 无 TLS 传输保护。PLAIN 使用账号密码，适合放在 TLS 内。SCRAM 通过挑战响应认证，仍可用 TLS 保护通信并验证服务端。GSSAPI 依赖 Kerberos 环境，OAUTHBEARER 依赖相应令牌签发和验证机制。所选机制必须由客户端、Broker Listener 和部署的身份系统共同支持。

ACL（Access Control List，访问控制列表）决定已识别的 Principal（安全主体）可以对哪些资源执行哪些操作。身份验证成功后，Topic 读取、组管理和事务操作仍按相应权限判断。

遇到证书问题时，应检查信任链、有效期、主机名和服务端公布的地址，不能把关闭校验当作长期修复方案。明文传输密码或把私钥贴进笔记，会在排查过程中引入新的安全风险。

证书的 SAN（Subject Alternative Name，主题备用名称）应覆盖实际连接名。域名连接匹配 DNS SAN。IP 直连并按 IP 验证时需要对应的 IP SAN。SNI（Server Name Indication，服务端名称指示）帮助支持它的服务端或代理按请求名称选择证书。SNI 发送与证书名称验证是两项独立操作。

从同一客户端网络使用 OpenSSL 3.0 做只读检查，每个 advertised 地址分别测一次：

```bash
openssl s_client -connect broker-1.example.net:9094 \
  -servername broker-1.example.net -verify_hostname broker-1.example.net \
  -CAfile lab-ca.pem -verify_return_error -showcerts </dev/null
```

查看是否完成握手、信任链是否验证通过，以及叶证书的有效期和 SAN。要隔离 DNS 问题，可改用 IP 作为 `-connect` 的地址，同时保留域名的 SNI 和验证参数。要模拟真正的 IP 客户端，则改用 `-verify_ip`，按环境决定是否需要额外的域名 SNI。mTLS 入口还需使用获准的测试客户端证书和密钥。OpenSSL 握手只验证 TLS 层，Kafka SASL、请求权限和客户端实际信任库需另查。

## 3. Topic、Group 与事务身份的资源权限 {#_3-topic-权限不是全部权限}

消费者可能需要对 Topic 和 Group 的适用权限；事务生产者还涉及 TransactionalId 等资源；管理操作又有独立动作。具体权限应按版本授权表和实际调用核对，不能用“加一个 Topic Read”解释所有失败。

观察错误码与请求阶段能帮助定位：初始连接失败、认证失败、Topic 授权失败、组授权失败和事务身份权限失败不是同一件事。临时赋予超级权限可能掩盖根因，也扩大误删和泄露风险。

以下按 Kafka 3.9 常用请求归纳。启用 KRaft ACL 时，各节点使用 `org.apache.kafka.metadata.authorizer.StandardAuthorizer`。实际授权还需考虑资源匹配方式、Host、Allow/Deny、Principal 映射和工具调用的具体 API。

| 角色                   | 典型权限及错误定位                                                                                                                                                          |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 普通 Producer          | 对目标 Topic 的 Write，Metadata 涉及 Describe，适用的 Allow Write 隐含 Allow Describe。Topic 权限不足可报 `TOPIC_AUTHORIZATION_FAILED`                                      |
| 非事务幂等 Producer    | 写入仍需目标 Topic 的 Write。3.9.0 的 InitProducerId 允许 Cluster 的 IdempotentWrite，或通过 Topic 资源类型的 Write 授权检查。不要仅为通过初始化就扩大为集群级授权          |
| Consumer Group 成员    | 对输入 Topic 和 Group 的 Read，涉及 Fetch、JoinGroup、OffsetCommit 等请求。缺失时检查 `TOPIC_AUTHORIZATION_FAILED` 或 `GROUP_AUTHORIZATION_FAILED`                          |
| Transactional Producer | 对对应 TransactionalId 的 Write，并对输出 Topic 有 Write。把输入位点纳入事务时，还需对输入 Group 和 Topic 有 Read。事务身份不足可报 `TRANSACTIONAL_ID_AUTHORIZATION_FAILED` |
| 只读运维工具           | Topic Describe 需要对应 Topic 的 Describe，组进度查询涉及 Group Describe、适用的 Topic Describe，查询配置另需 DescribeConfigs。集群级列表及 ACL 查询有自己的权限            |
| 管理工具               | 按 API 分别授权，例如删除 Topic 需要 Topic Delete，修改 ACL 需要 Cluster Alter。查询 ACL 则需要 Cluster Describe                                                            |

## 4. 多租户还需要资源隔离

配额、命名规范、敏感数据分类和容量预算共同约束共享集群。某客户端过载可能造成节流与延迟，应结合配额指标分析，而不是一味增加重试。

client.id 可以帮助识别流量与适用配额，但不是可靠的应用身份认证凭据。真正的访问控制不能仅靠所有人自觉填写不同 client.id。

为各租户设置独立 Principal，以有边界的 Topic、Group 和事务 ID 命名空间配置权限。Client Quota（客户端配额）可按用户、`client.id` 或组合约束流量，触发节流时共享集群的延迟可能上升。配额管理资源消耗，ACL 管理资源访问权。客户端声明的 `client.id` 可用于观察和配额匹配，认证身份来自安全协议。

## 5. 一条故障的观察顺序

先记录客户端版本、错误码、发生时间和受影响的 Topic/Group。初始连接阶段，应检查 Bootstrap 的 DNS/TCP，以及该连接配置的 TLS/SASL，连接成功后才能取得元数据；随后按 advertised 地址建立连接时，还需检查这些地址的路由、证书与认证。最后，再按实际请求核对资源权限和配额。不能等拿到元数据后才排查 Bootstrap 握手，也不应同时修改端口、关闭校验并扩大 ACL。

本册使用占位地址，不复制原笔记中真实环境地址、凭据或会话数据。正式公开前还要单独审查图片、代码和日志中的敏感信息，技术正确不等于已经通过公开授权。

### 三个故障练习与只读诊断

使用隔离的 Kafka 3.9 测试环境及第 20 章的 `review-orders`、`review-c-orders`。先保存一份能通过只读 Describe 的基线。每次只引入一种故障。以下均是复现方案和预期，未在真实集群执行。

| 案例                         | 注入与预期                                                                                                                         | 只读排查及修复方向                                                                                                                                                             |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| A · Bootstrap 可达，业务失败 | 保持一个 Bootstrap Broker 可达，让另一个分区 Leader 公布只在内网可解析的地址。可取得部分元数据，访问受影响分区时出现解析或连接错误 | 在客户端网络分别检查 Bootstrap 和目标地址的 DNS、TCP 与安全握手。用下方 Broker API 版本工具或客户端元数据日志核对公布的地址及节点 ID。修正目标 Listener 的公布地址、DNS 或 NAT |
| B · TCP 成功，TLS 失败       | 用测试客户端的无关 CA，或以证书 SAN 未覆盖的别名连接。预期 Kafka 元数据请求前出现信任链或名称错误                                  | 用本章 OpenSSL 命令检查所连端点、证书链、有效期和名称。另查实际客户端信任库及 TLS 协议是否兼容。修复 CA、证书或地址并保留校验                                                  |
| C · 身份认证成功，授权失败   | 在已经启用认证和 ACL 的隔离环境用有限权限的测试身份，分别对已有 Topic 尝试写入、加入已有组或初始化事务身份。按缺失权限观察对应拒绝 | 记录请求阶段、错误码、认证主体和资源。由有查询权限的运维身份查看匹配的 ACL，按矩阵补足具体操作。分别检查 Topic、Group 和 TransactionalId，避免把失败归于网络                   |

```bash
bin/kafka-broker-api-versions.sh --bootstrap-server broker-1.example.net:9094 \
  --command-config client.properties
bin/kafka-acls.sh --bootstrap-server broker-1.example.net:9094 \
  --command-config audit-client.properties --list --topic review-orders \
  --resource-pattern-type match
```

第一个命令观察发现的 Broker 端点及 API 版本，失败时可对照客户端日志区分初始连接和后续节点。在 Linux 可对每个实际端点执行 `getent ahosts <host>` 和 `nc -vz -w 3 <host> <port>`，再做适用的 TLS 检查。第二个命令列出匹配该 Topic 的规则，包括适用的前缀和通配规则。检查组或事务身份时分别用 `--group review-c-orders` 或 `--transactional-id review-orders-writer` 代替 Topic 选择器。

案例 C 可在测试组用 `kafka-console-consumer.sh --bootstrap-server broker-1.example.net:9094 --consumer.config limited-client.properties --topic review-orders --group review-c-orders --consumer-property enable.auto.commit=false --timeout-ms 5000` 验证消费权限。针对事务身份，可复用[第 14 章](/articles/kafka-transactions.html)的配置和 `initTransactions()`，指定受限身份和 `transactional.id=review-orders-writer`，仅执行到初始化。测试写权限时只对隔离 Topic 发送可识别的测试记录，因为权限实际允许时请求会写入。

排查记录可保留客户端版本、请求阶段、错误码、地址类型、TLS 错误类别及经过替换的 Topic/Group 名称。实际域名和网段、私钥、密码、Token、认证配置及敏感 Payload 应从公开记录中剔除。

## 参考

- [Kafka 3.9 TLS 配置](https://kafka.apache.org/39/security/encryption-and-authentication-using-ssl/)
- [Kafka 3.9.0 Broker 授权实现](https://github.com/apache/kafka/blob/3.9.0/core/src/main/scala/kafka/server/KafkaApis.scala)
- [OpenSSL 3.0 s_client](https://docs.openssl.org/3.0/man1/openssl-s_client/)

- [Kafka Listener Configuration](https://kafka.apache.org/39/security/listener-configuration/)
- [Broker 配置与 advertised.listeners](https://kafka.apache.org/39/configuration/broker-configs/)
- [Authorization and ACLs](https://kafka.apache.org/39/security/authorization-and-acls/)
