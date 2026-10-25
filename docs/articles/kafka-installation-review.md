---
id: kafka-installation-review
title: 第 20 章：历史运维速查（兼容原章节入口）
description: 本节用于查询历史运维信息，不是安装教程。旧 ZooKeeper 命令、下载记录与组件边界集中在附录A；这里保留目录风险、只读 describe 模板和变更验收要求，供复盘时查阅。
date: '2026-10-25'
updated: '2026-10-25'
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
order: 20
---

# 第 20 章：历史运维速查（兼容原章节入口）

> 版本导航：历史运维速查，不是新建环境安装教程。
>
> 学习目标：保留原来的下载安装实践，同时明确它的年代与风险。本章不安装、启动、格式化、删除或连接任何集群。

## 1. 版本与组件定位

本节用于查询历史运维信息，不是安装教程。旧 ZooKeeper 命令、下载记录与组件边界集中在[附录A](/articles/kafka-version-references.html)；这里保留目录风险、只读 describe 模板和变更验收要求，供复盘时查阅。

## 2. 数据目录不是随意可清理的缓存

业务日志目录、元数据目录、客户端日志与临时下载目录用途不同。KRaft 的格式化操作会初始化存储身份和元数据条件，不是通用“修复已有目录”的步骤；旧数据目录不能因为报错就直接 format 或 rm。

同样，删除 Topic、调整保留、重置组位点、重分配副本和升级元数据版本都有不同回退边界。即便工具执行成功，也需要验证业务可用性与数据恢复条件。

## 3. 只读观察模板

以下 Bash 模板适用于核对 Kafka 3.9 工具语法，只展示只读 describe。占位符必须替换，并核对网络、授权与安全配置；本次未执行，也不表示当前电脑安装了这些工具。

```bash
bin/kafka-topics.sh --bootstrap-server '<broker-host:port>' \
  --command-config '<client.properties>' --describe --topic '<topic>'

bin/kafka-consumer-groups.sh --bootstrap-server '<broker-host:port>' \
  --command-config '<client.properties>' --describe --group '<group>'
```

安全配置文件不应包含在公开笔记或 Git 仓库里。Describe 可能产生访问日志，也需要权限；只读不等于可以任意连接未授权系统。

## 4. 变更前后的验收

变更前应记录拓扑、有效配置、分区与副本状态、组进度和业务基线，并确认恢复材料是否确实可用。变更后应比较错误率、延迟、ISR、积压和业务一致性，不能只看工具退出码。

练习：把旧笔记中的命令分为查询、写配置、业务写入、破坏性数据操作四类。若无法确认某个操作是否会覆盖存储，应停下来查固定版本帮助，而不是先在现有数据目录试一遍。

## 参考

- [Kafka 3.9 Basic Operations](https://kafka.apache.org/39/operations/basic-kafka-operations/)
- [Kafka 3.9 KRaft 存储与运维](https://kafka.apache.org/39/operations/kraft/)
