---
id: kafka-c-rebalance-shutdown
title: 第 18 章：C 重平衡回调与优雅关闭
description: 客户端可以自动处理适用分区分配；一旦注册自定义 rebalance callback，应用就必须按所选协议履行分配和撤销契约，同时完成自己的业务交接。
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
order: 18
---

# 第 18 章：C 重平衡回调与优雅关闭

> 版本导航：librdkafka v2.8.0 C API。
>
> 学习目标：让业务生命周期服从分区所有权，避免撤销后继续写入、回调使用已释放上下文和销毁时丢失未确认工作。

## 1. 没有回调与自定义回调的责任不同

客户端可以自动处理适用分区分配；一旦注册自定义 rebalance callback，应用就必须按所选协议履行分配和撤销契约，同时完成自己的业务交接。

固定 v2.8.0 中，range、roundrobin 等 eager 路线使用 `rd_kafka_assign()` 设置或清空完整分配；cooperative-sticky 等增量路线使用对应的 incremental assign/unassign。增量函数返回的错误对象也有独立归属，不能忽略或按普通整数错误码处理。

| 事件/状态，C v2.8.0 Classic       | eager自定义回调                      | cooperative自定义回调                    | 业务状态                           |
| --------------------------------- | ------------------------------------ | ---------------------------------------- | ---------------------------------- |
| ASSIGN_PARTITIONS                 | assign设置完整分配                   | incremental_assign加入指定集合           | 初始化这些分区的队列与完成前沿     |
| REVOKE_PARTITIONS，仍有可交接资格 | 停派工作，提交安全前沿后assign(NULL) | 只处理撤销集合，然后incremental_unassign | 未撤销分区继续，禁止提交未完成任务 |
| 所有权已丢失                      | 不假定旧提交仍有效                   | 同样不假定有效                           | 隔离迟到结果，允许新持有者重放     |
| closing，close可能触发回调        | 履行相同完整分配契约                 | 履行相同增量契约                         | opaque与需要的状态必须仍存活       |

这是契约状态表，不是完整回调代码；实际处理还要检查每个返回值及错误对象归属。

## 2. 撤销分区先撤销工作资格

先停止向被撤销分区派发新任务，清点已完成与在途任务，再在可用预算内排空或取消剩余任务，并在仍有提交资格时提交安全前沿。对于没有被撤销的分区，cooperative 路线不应无条件清除全部状态。

若客户端报告所有权已丢失，旧实例不能假定自己仍有提交资格。外部正在执行的 HTTP 或数据库请求也不会因为回调发生自动消失，必须用幂等、任务取消或下游 fencing 处理迟到结果。

## 3. 回调不要承载无限阻塞业务

在回调里等待一个无法结束的任务，会阻碍客户端事件处理，甚至引发新的超时。因此，应提前设计有界排空、状态标记和重试恢复方式。回调中允许调用哪些 API，需要按固定版本文档核对，不能默认所有公共方法都可递归调用。

简化方案可以先采用串行业务和库自动分配，确认基础语义后再增加自定义回调。复杂回调不等于更可靠；若无法描述每个状态的进入、退出和失败路径，应先减少并发范围。

## 4. 优雅关闭不是一个 destroy

![关闭与对象生命周期](/assets/notes/kafka/kf-close.svg)

Producer 停止新发送，服务回调并执行有界 flush，记录仍未完成和最终失败的消息。Consumer 停止新业务派发，处理安全前沿，调用 `rd_kafka_consumer_close()` 并检查结果，随后释放客户端。显式 close 使生命周期更清楚；库在适用 destroy 路径中也可能触发 close 和回调，因此上下文不能提前释放。

| 阶段             | 接口与计时，v2.8.0                                                      | 不能推出的结论                                           |
| ---------------- | ----------------------------------------------------------------------- | -------------------------------------------------------- |
| 应用排空         | 应用自行设置工作预算、取消和恢复记录                                    | 库的close不替线程池收尾                                  |
| Producer投递排空 | rd_kafka_flush(rk,timeout_ms)                                           | 队列空不等于每条成功；仍看Delivery Report                |
| Consumer同步关闭 | rd_kafka_consumer_close(rk)，没有同名timeout参数                        | 文档大致受session.timeout.ms限制，不是任意慢回调的硬截止 |
| Consumer异步关闭 | consumer_close_queue，把事件送指定队列，持续服务直到consumer_closed为真 | 发起异步关闭不等于已经可destroy                          |
| 资源释放         | 完成关闭契约后destroy，最后清理回调上下文                               | 不从另一线程强行destroy作为通用超时补救                  |

同步 close 包含撤销分配、必要的提交和离组等动作，但回调中的业务阻塞仍需单独管理。Producer 的关闭细节见[第16章](/articles/kafka-c-producer.html)，不要把 flush 的毫秒参数误套到 Consumer close 上。

Topic 句柄、应用持有的消息、列表、客户端和回调上下文都有各自顺序。不能先 free opaque，再在 flush 或 close 中触发使用它的回调。

## 5. 停止信号与故障恢复

信号处理器可以设置停止标记，让正常控制流退出；不应在异步信号上下文中直接进行任意复杂的客户端与内存操作。强制杀进程或机器掉电仍可能跳过优雅关闭，设计必须允许从已提交位置重放。

练习至少覆盖四种窗口：处理前退出、业务完成但提交前退出、分区撤销时有在途工作、flush 或 close 超时。这里仅提供测试设计，未实际终止程序、注入故障或操作集群。

## 参考

- [v2.8.0 Rebalance callback 与销毁契约](https://github.com/confluentinc/librdkafka/blob/v2.8.0/src/rdkafka.h)
- [librdkafka 官方示例目录](https://github.com/confluentinc/librdkafka/tree/v2.8.0/examples)

## 联读

先读[串行消费与位点提交](/articles/kafka-c-consumer.html)，再处理本章的所有权交接。
