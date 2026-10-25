---
id: distributed-byzantine-models
title: 第二十七章 PBFT、PoW 与故障模型对照
description: “节点故障”既可能表现为停止响应，也可能表现为向不同接收方发送矛盾信息。停止响应与拜占庭行为属于不同故障模型。原笔记将 Raft、PBFT 和 PoW 列为常用算法，本章保留这一阅读入口，但三者并不是可以直接互换的产品选项。
date: '2026-10-25'
updated: '2026-10-25'
category: distributed-systems
type: explanation
tags:
  - 分布式系统
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: distributed-systems
series: distributed-learning
order: 27
---

# 第二十七章 PBFT、PoW 与故障模型对照

> 阅读标签：经典PBFT1999 / PoW模型对照。

“节点故障”既可能表现为停止响应，也可能表现为向不同接收方发送矛盾信息。停止响应与拜占庭行为属于不同故障模型。原笔记将 Raft、PBFT 和 PoW 列为常用算法，本章保留这一阅读入口，但三者并不是可以直接互换的产品选项。

## 1. Raft 的多数不能直接覆盖恶意行为

在约定崩溃模型中，节点按协议执行，只是可能停止、恢复或暂时失联。拜占庭节点则可能伪造、遗漏、矛盾发送或任意偏离协议。一个节点对 A 说“我投给你”、对 B 又作同样承诺，会破坏普通崩溃容错证明的前提。

TLS 有助于验证身份、保护传输，但不能保证具有合法身份的节点一定诚实。安全通信、访问控制和拜占庭共识分别处理不同层次的问题。

## 2. PBFT 的数量直觉

经典 PBFT 以至少 3f+1 个副本容忍至多 f 个拜占庭副本，结合身份认证、消息与状态协议工作。不是“f 个故障加另一个 f 个坏节点”，而是同一个故障预算覆盖模型允许的拜占庭副本。

在 N=3f+1 时，两组各 2f+1 的集合至少重叠 f+1，因而不可能交点全是至多 f 个坏节点。但这只是交集直觉，完整安全还依赖视图、序号、摘要和正确节点不矛盾参与等约束。[PBFT 系统模型与算法](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/castro.html)

## 3. 不要把每个阶段的计数都写成相同的 ACK

限定经典 PBFT、N=3f+1、论文正常路径：消息必须通过认证并匹配 view、序号和请求摘要，重发不能重复计票。

| 本地判定                 | 所需证据                                                             | f=1、四副本示例                                                          |
| ------------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| prepared(m,v,n,i)        | 已记录请求、匹配 pre-prepare，以及来自不同 backup 的2f份匹配 prepare | 一份pre-prepare和两份backup prepare；backup自己的prepare可在其日志中计入 |
| committed-local(m,v,n,i) | 本地已prepared，另接受不同副本的2f+1份匹配commit，可含自身           | 三份commit，并满足先前prepared条件                                       |
| 客户端接受结果           | 来自不同副本的f+1份有效、结果相同的回复                              | 两份相同结果回复                                                         |

纸面例子：P为Primary，B1/B2/B3为Backup。B1记录P的pre-prepare、自身及B2的prepare后，可满足prepared；不能把P再算成一份backup prepare。随后B1取得来自B1/B2/P的三份匹配commit，并满足更早序号已执行等条件，才可执行当前请求并回复。两份commit不够；三次来自B2的同一commit重发也只算一个发送者。

该表不覆盖视图切换、检查点或全部活性条件；prepared、committed与committed-local也不是同一个谓词。

因此，原笔记中“任意阶段收到 2f+1 个同名消息就执行”的概括过于粗略。视图切换、检查点和重复请求也不能用一张简单的多数图代替。本章提供学习索引，不将省略故障恢复的代码视为完整 PBFT 实现。[原论文算法定义](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node4.html)

## 4. PoW 不是普通节点多数表决

以 Bitcoin 论文为例，工作量证明用可验证的计算成本参与开放环境下的历史选择。安全假设与算力、网络传播和链的工作量相关，不是注册越多节点、IP 越多就获得更多合法票。

“得到多数节点认可就达成共识”不足以描述它。链还可能短暂分叉并重组，确认深度与风险依赖模型；不能将其当成 Raft 那样的确定提交点，也不把本章当成任何资产建议。[Bitcoin 原论文 §4—5](https://bitcoin.org/bitcoin.pdf)

## 5. 对照时先问问题

| 维度     | 崩溃容错日志协议   | 经典 PBFT              | PoW 链模型                  |
| -------- | ------------------ | ---------------------- | --------------------------- |
| 参与身份 | 通常已知成员       | 通常已知、可认证副本   | 开放参与，另处理 Sybil 成本 |
| 故障预算 | 按崩溃与多数等条件 | 按拜占庭预算与协议条件 | 按算力及传播等假设          |
| 结果解释 | 适用提交与恢复规则 | 适用证明与视图规则     | 工作量、确认与重组风险      |

经典 PBFT 正常路径中的全互联通信可呈二次量级，但这一结论不能概括所有 BFT 变体、阶段和部署的性能。算法名称只是阅读入口；判断其保证是否适用，应先核对故障模型。

[返回本册目录](/collections/distributed-systems/)
