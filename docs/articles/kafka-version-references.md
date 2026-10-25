---
id: kafka-version-references
title: 附录 A：版本与技术依据
description: 本册复核日期为 2026-10-22。以 Kafka 3.9 为固定的机制复盘基线，用 Kafka 4.0 说明明确的演进边界，librdkafka 则固定为 v2.8.0。选择这些版本不代表推荐用于新建生产环境，也不表示本册覆盖了截至该日期的全部新特性。
date: '2026-10-25'
updated: '2026-10-25'
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

原文包含较早 ZooKeeper 与消息格式资料。保留其学习线索，正文将现代机制和历史背景拆开；未改写原始导出文件，未公开发布私人笔记。

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

## 官方页面也需要版本交叉检查

3.9 的 Log 页面仍保留了早期关于字节 Offset 等内容的叙述，不能直接等同于现代机制。正文对 Offset/索引的说明采用固定源码和现代消息格式交叉核对，不会仅因页面位于 3.9 路径下，就直接沿用其中所有历史段落。

部分文档对 HW/LSO 使用“最后一条”或“下一位置”语言。本册图与算例统一为排他上界；阅读具体 API 时仍应查看其返回值契约，不能把解释中的加一直接重复应用到 API。

## 验证与限制

已进行原文覆盖映射、技术依据核对、链接与代码块静态检查、SVG/PNG 图示检查。C 片段未编译，命令未执行，Mermaid 未运行渲染器，HTML 未经过完整交互式浏览器验收；不冒充实测记录。图示用于解释核心关系，不代替完整协议状态机。

正式公开前需再次审查内容授权、引用和敏感信息。原图保存在私有来源，正文新图采用 #0369A1，并提供可编辑图源。

## 历史运维材料

本轮精确核对补充：[Java3.9.0 BuiltInPartitioner.partitionForKey](https://github.com/apache/kafka/blob/3.9.0/clients/src/main/java/org/apache/kafka/clients/producer/internals/BuiltInPartitioner.java)、[C2.8.0 rdkafka_msg.c分区器](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka_msg.c)、头文件中的consumer_close/close_queue/closed/flush，以及3.9的delete.retention.ms与Consumer事务读取。固定字节映射只运行了独立哈希算术，没有启动客户端发送。

旧记录包含 ZooKeeper 启动、旧 --zookeeper 管理命令，以及 Java/C/Python 不同组件的安装步骤，不能直接拼成 Kafka4.0 教程。Broker 服务、Java 客户端包、librdkafka 与封装库应分别管理；新建环境时，应另行选择受支持的版本。下载时需核对可信发布入口和签名/校验和；仅计算本地 SHA256 并不等于验证了发布者身份。

[历史目录风险与只读查询速查](/articles/kafka-installation-review.html)保留原路径，不移动或删除原始实践。
