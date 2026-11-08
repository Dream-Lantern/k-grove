---
id: kafka-version-references
title: 附录 A：版本与技术依据
description: "本册复核日期为 2026-10-22。以 Kafka 3.9 为固定的机制复盘基线，用 Kafka 4.0 说明明确的演进边界，librdkafka 则固定为 v2.8.0。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: reference
tags:
  - kafka
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: kafka
series: kafka-learning
order: 90
---

# 附录 A：版本与技术依据

## 版本说明

本册复核日期为 2026-10-22。以 Kafka 3.9 为固定的机制复盘基线，用 Kafka 4.0 说明明确的演进边界，librdkafka 则固定为 v2.8.0。选择这些版本不代表推荐用于新建生产环境，也不表示本册覆盖了截至该日期的全部新特性。

本册分别说明早期 ZooKeeper、旧消息格式与现代机制，阅读时按章节标出的版本定位来源。原始私人导出文件不属于正文或配图。

| 组件                        | 本册口径                                                                                                            |
| --------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| Kafka Broker                | 3.9 为机制基线，兼顾 ZooKeeper 历史模式与 KRaft。4.0 起仅 KRaft                                                     |
| Kafka Java Client           | 以 3.9 文档和对应源码为准。客户端依赖与 Broker 独立升级，具体能力还取决于双方支持的协议版本                         |
| librdkafka                  | 固定 v2.8.0。Classic 是 C 实践基线，KIP-848 在该版本为 Early Access。Kafka 4.0 服务端 GA 不会改变旧客户端的支持阶段 |
| Kafka Connect、Streams、MM2 | 参考 Kafka 3.9 的对应发行组件。第三方 Connector 与封装库另查各自版本与支持范围                                      |

## 主要核对入口

| 主题             | 固定版本官方依据                                                                                                                                   | 用途                               |
| ---------------- | -------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| 事件流与核心概念 | [3.9 Introduction](https://kafka.apache.org/39/getting-started/introduction/)                                                                      | 角色、分区与事件日志               |
| 复制、语义与清理 | [3.9 Design](https://kafka.apache.org/39/design/design/)                                                                                           | 与原文交叉核对，不照搬历史性能数字 |
| Java 生产参数    | [3.9 Producer](https://kafka.apache.org/39/configuration/producer-configs/)                                                                        | acks、幂等、批次、超时             |
| Java 消费参数    | [3.9 Consumer](https://kafka.apache.org/39/configuration/consumer-configs/)                                                                        | 起点、隔离、Poll 与组身份          |
| Topic 策略       | [3.9 Topic Configs](https://kafka.apache.org/39/configuration/topic-level-configs/)                                                                | minISR、保留、清理、刷新           |
| 稀疏索引         | [3.9.0 OffsetIndex.java](https://github.com/apache/kafka/blob/3.9.0/storage/src/main/java/org/apache/kafka/storage/internals/log/OffsetIndex.java) | 逻辑 Offset 到物理位置             |
| 记录格式         | [3.9 Message Format](https://kafka.apache.org/39/implementation/message-format/)                                                                   | 旧 Message 与 Record Batch 区分    |
| KRaft            | [3.9 KRaft](https://kafka.apache.org/39/operations/kraft/)                                                                                         | 元数据 quorum 与部署角色           |
| 模式差异         | [4.0 KRaft vs ZooKeeper](https://kafka.apache.org/40/getting-started/zk2kraft/)                                                                    | ZooKeeper 模式移除背景             |
| 新消费协议       | [4.0 Consumer Rebalance](https://kafka.apache.org/40/operations/consumer-rebalance-protocol/)                                                      | GA 与客户端阶段分开                |
| C API 契约       | [v2.8.0 rdkafka.h](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)                                                           | 对象归属、回调、提交、关闭         |
| C 默认配置       | [v2.8.0 CONFIGURATION](https://github.com/confluentinc/librdkafka/blob/v2.8.0/CONFIGURATION.md)                                                    | 与 Java 对照，避免跨家族拼接       |
| C 运行机制       | [v2.8.0 INTRODUCTION](https://github.com/confluentinc/librdkafka/blob/v2.8.0/INTRODUCTION.md)                                                      | 线程、可靠性、消费组、Early Access |
| 安全与监控       | [ACL](https://kafka.apache.org/39/security/authorization-and-acls/) · [Monitoring](https://kafka.apache.org/39/operations/monitoring/)             | 权限与指标口径                     |
| 生态             | [Connect](https://kafka.apache.org/39/kafka-connect/overview/) · [Streams](https://kafka.apache.org/39/streams/introduction/)                      | 框架职责和语义边界                 |

### 按章节查证

| 正文  | 主要内容                            | 证据入口                                                                                                                               |
| ----- | ----------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| 1–3   | 日志模型、Key 路由、Broker 与控制器 | Introduction、KRaft                                                                                                                    |
| 4–7   | ISR、写入确认、索引、保留与压缩     | Design、Topic 配置、OffsetIndex                                                                                                        |
| 8–9   | 批次、重试、幂等与未知结果          | Producer 配置、[Java Producer API](https://kafka.apache.org/39/javadoc/org/apache/kafka/clients/producer/KafkaProducer.html)           |
| 10–12 | 分配、恢复位点、重平衡              | Consumer 配置、[Java Consumer API](https://kafka.apache.org/39/javadoc/org/apache/kafka/clients/consumer/KafkaConsumer.html)、协议演进 |
| 13–14 | 投递语义、事务与外部副作用          | Design、Java Producer 与 Consumer API                                                                                                  |
| 15–18 | C 所有权、投递、提交和关闭          | v2.8.0 头文件与使用说明                                                                                                                |
| 19–21 | 配置对照、存储、Listener 和 ACL     | 配置表、KRaft、[Listener 配置](https://kafka.apache.org/39/security/listener-configuration/)、ACL                                      |
| 22–24 | 积压、生态与订单事务                | Monitoring、Connect、Streams、[PostgreSQL 17 并发隔离](https://www.postgresql.org/docs/17/transaction-iso.html)                        |

## 官方页面也需要版本交叉检查

3.9 的 Log 页面仍保留了早期关于字节 Offset 等内容的叙述，不能直接等同于现代机制。正文对 Offset/索引的说明采用固定源码和现代消息格式交叉核对，不会仅因页面位于 3.9 路径下，就直接沿用其中所有历史段落。

部分文档对 HW/LSO 使用“最后一条”或“下一位置”语言。本册图与算例统一为排他上界；阅读具体 API 时仍应查看其返回值契约，不能把解释中的加一直接重复应用到 API。

## 验证与限制

2026-10-22 的历史复核覆盖了来源映射、技术依据、静态链接、代码块和配图。该次记录未覆盖 C 编译、命令运行、Mermaid 渲染或完整浏览器交互。后续检查按实际环境和检查项目分别记录，静态检查、对象编译和集成实测各有独立结论。

| 证据类型   | 核对口径                               |
| ---------- | -------------------------------------- |
| 官方文档   | 固定版本、组件和配置作用域             |
| KIP 或标准 | 提案适用范围及落地版本                 |
| 源码       | 固定 Tag、文件、函数与触发条件         |
| 数学推导   | 输入、公式、假设及计算过程             |
| 工程经验   | 适用条件、代价和失败边界               |
| 运行实验   | 环境、版本、命令、实际结果与可追溯记录 |
| 待验证假设 | 标记 NOT VERIFIED，保留复现条件        |

链接可以打开只表明资料可访问。技术结论还需核对对应段落或实现。图示解释核心关系，完整协议分支应查相应契约。

公开维护时应检查内容授权、引用与敏感信息。正文使用重新表达机制的教学图。既有 PNG 和配套 SVG 按原样保留。独立 SVG 只有确认存在技术问题时才做定点修订。

## 历史运维材料

关键实现定位：[Java3.9.0 BuiltInPartitioner.partitionForKey](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/internals/BuiltInPartitioner.java)、[C2.8.0 rdkafka_msg.c分区器](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka_msg.c)、头文件中的consumer_close/close_queue/closed/flush，以及3.9的delete.retention.ms与Consumer事务读取。固定字节映射只运行了独立哈希算术，没有启动客户端发送。

旧记录包含 ZooKeeper 启动、旧 --zookeeper 管理命令，以及 Java/C/Python 不同组件的安装步骤，不能直接拼成 Kafka4.0 教程。Broker 服务、Java 客户端包、librdkafka 与封装库应分别管理；新建环境时，应另行选择受支持的版本。下载时需核对可信发布入口和签名/校验和；仅计算本地 SHA256 并不等于验证了发布者身份。

[历史目录风险与只读查询速查](/articles/kafka-installation-review.html)保留原路径，不移动或删除原始实践。
