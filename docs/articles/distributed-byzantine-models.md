---
id: distributed-byzantine-models
title: 第二十七章 PBFT、PoW 与故障模型对照
description: "节点故障可以表现为停止响应，也可以表现为向不同接收方发送矛盾信息。不同故障模型需要相应的协议约束。本章分别观察崩溃容错、经典 PBFT 和 PoW 的参与身份、故障预算与结果判定，帮助按适用条件比较它们。"
date: '2026-10-25'
updated: '2026-10-28'
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

节点故障可以表现为停止响应，也可以表现为向不同接收方发送矛盾信息。不同故障模型需要相应的协议约束。本章分别观察崩溃容错、经典 PBFT 和 PoW 的参与身份、故障预算与结果判定，帮助按适用条件比较它们。

## 1. 崩溃行为与拜占庭行为的区别 {#_1-raft-的多数不能直接覆盖恶意行为}

在约定崩溃模型中，节点按协议执行，只是可能停止、恢复或暂时失联。拜占庭节点则可能伪造、遗漏、矛盾发送或任意偏离协议。一个节点对 A 说“我投给你”、对 B 又作同样承诺，会破坏普通崩溃容错证明的前提。

TLS 有助于验证身份、保护传输，但不能保证具有合法身份的节点一定诚实。安全通信、访问控制和拜占庭共识分别处理不同层次的问题。

Safety（安全性）要求正确参与者不能接受相互冲突的协议结果，例如同一日志位置不能执行两个不同请求。Liveness（活性）要求在协议规定的故障预算与通信条件下，请求最终能完成。停止推进可以保住安全性，却不满足活性。

经典 PBFT 的网络模型允许消息延迟、丢失、重复和乱序。安全性不依赖固定消息延迟上界；活性仍需要论文规定的弱同步条件，使重传、超时与视图切换最终能够推进。它不保证网络永久无法通信时还能持续提交。超时表示应怀疑当前主节点、尝试换视图，不表示已经形成的合法安全证据可以清空。[原论文 §2 系统模型](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node2.html)、[§3 安全性与活性条件](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node3.html)

## 2. PBFT 的数量直觉

经典 PBFT 以至少 3f+1 个副本容忍至多 f 个拜占庭副本，其中 f 是允许的故障副本数，N 是副本总数；协议结合身份认证、消息与状态规则工作。不是“f 个故障加另一个 f 个坏节点”，而是同一个故障预算覆盖模型允许的拜占庭副本。

在 N=3f+1 时，两组各 2f+1 的集合至少重叠 f+1，因而不可能交点全是至多 f 个坏节点。但这只是交集直觉，完整安全还依赖视图、序号、摘要和正确节点不矛盾参与等约束。[PBFT 系统模型与算法](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/castro.html)

## 3. 经典 PBFT 各阶段的证据与计数 {#_3-不要把每个阶段的计数都写成相同的-ack}

限定经典 PBFT、N=3f+1、论文正常路径：消息必须通过认证并匹配 view、序号和请求摘要，重发不能重复计票。

这里 view（视图）标识当前协议轮次及主节点，Sequence Number（序号）指定请求的执行位置，Digest（摘要）标识请求内容。下面的 `m、v、n、i` 分别表示请求、视图、序号和本地副本；`prepared(m,v,n,i)` 等谓词描述它们满足的协议条件。

| 判定 / 性质              | 所需证据                                                             | f=1、四副本示例                                                          |
| ------------------------ | -------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| prepared(m,v,n,i)        | 已记录请求、匹配 pre-prepare，以及来自不同 backup 的2f份匹配 prepare | 一份pre-prepare和两份backup prepare；backup自己的prepare可在其日志中计入 |
| committed(m,v,n)         | 至少 f+1 个非故障副本已经满足 prepared，是全局性质，不是额外一类消息 | 至少两个正确副本 prepared；单个副本不能直接观察所有节点的内部状态        |
| committed-local(m,v,n,i) | 本地已prepared，另接受不同副本的2f+1份匹配commit，可含自身           | 三份commit，并满足先前prepared条件                                       |
| 客户端接受结果           | 来自不同副本的f+1份有效、结果相同的回复                              | 两份相同结果回复                                                         |

纸面例子：P为Primary，B1/B2/B3为Backup。B1记录P的pre-prepare、自身及B2的prepare后，可满足prepared；不能把P再算成一份backup prepare。随后B1取得来自B1/B2/P的三份匹配commit，并满足更早序号已执行等条件，才可执行当前请求并回复。两份commit不够；三次来自B2的同一commit重发也只算一个发送者。

展开这个 `f=1、N=4` 的例子，假设 P、B1、B2 正确，B3 是可能故障的副本且本次保持沉默：

| 阶段                       | B1 或客户端具体得到什么                                                                 |
| -------------------------- | --------------------------------------------------------------------------------------- |
| Request（请求）            | Client 将请求交给 P                                                                     |
| Pre-Prepare（预准备）      | P 为请求指定 `(v,n,d)`，发送合法提案给 Backup                                           |
| Prepare（准备）            | B1 记录自身与 B2 的两份匹配 Prepare，连同请求和 Pre-Prepare，满足 `2f=2` 的准备条件     |
| Commit（提交）             | B1 已 prepared，再收到 P、B1、B2 的三份匹配 Commit，满足 `2f+1=3`，形成 committed-local |
| Execute（执行）            | B1 还需等所有更早序号执行完成，再执行本请求                                             |
| Client Reply（客户端回复） | 客户端收到 B1、B2 等两个不同副本针对同一请求的相同有效结果，达到 `f+1=2` 才接受         |

![经典 PBFT 正常路径的消息与计数](/assets/notes/distributed-systems/dist-pbft-normal-case.svg)

P 发 Pre-Prepare，Backup 发 Prepare；P 的 Pre-Prepare 不是第三份 Prepare。P 也会收集 Backup 的 Prepare，在自身 prepared 后发送 Commit。Commit 计数来自不同副本，可以包括接收者自己；客户端的回复计数则匹配请求标识与结果，不是再收集一遍 Commit。

对**正确副本 i**，committed-local 成立可以推出 committed：2f+1 份 Commit 中至少 f+1 份来自正确副本，而正确副本只有在 prepared 后才发送 Commit；本例对应三份中至少两份正确。故障副本任意声称“我 committed-local”不构成证明。prepared 本身也不是执行和回复条件；committed 是全局谓词，committed-local 才是副本依据本地证据判定的条件。[原论文 §4.1—4.2](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node4.html)

该表不覆盖视图切换、检查点或全部活性条件；prepared、committed与committed-local也不是同一个谓词。

各阶段需要核对消息身份、匹配条件与此前的本地状态，视图切换、检查点和重复请求还各有处理规则。本章说明正常路径的计数与学习入口，完整实现还需覆盖这些恢复条件。[原论文算法定义](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node4.html)

### View Change 与 Checkpoint 各管一条恢复路径

View Change（视图切换）在主节点无法推进时更换 Primary。教学流程是：请求迟迟未完成 → 超时发起 View Change → 收集合法历史证据 → 构造并验证 New View（新视图）→ 在新视图继续协议。大量网络延迟也会触发怀疑，不能把超时直接当作主节点确定作恶。

原论文中新主收集另外 `2f` 份合法 View-Change，加上自身一份，共 `2f+1` 份证据，携带稳定检查点和此前的准备证明。它按规则为相关序号选取准备证据中的最高视图请求，缺口按规则处理；Backup 也要验证，不能由新主随意挑自己最后收到的请求。携带与验证准备证据保护已经形成的安全约束，特别是正确副本已 committed-local 的请求；“某个副本单独 prepared”不等于该值已经永久确定。

Checkpoint（检查点）处理日志增长。副本周期性地对执行到某个序号的状态生成摘要，收到 **2f+1 个不同副本**针对同一序号与摘要的有效 Checkpoint 消息（可含自身），才形成 Stable Checkpoint（稳定检查点）。这份证明允许清理不超过该序号的旧协议消息，并推进接收消息的水位；缺状态的副本仍需按协议获取和验证状态。

| 触发情况       | 主路径                                                |
| -------------- | ----------------------------------------------------- |
| 普通请求       | Pre-Prepare → Prepare → Commit → 按序 Execute → Reply |
| 当前主无法推进 | View Change → 验证 New View 与历史证据 → 继续普通协议 |
| 到达周期检查点 | Checkpoint 消息 → 稳定检查点证明 → 安全清理旧日志     |

View Change 与 Checkpoint 不是每个请求都必须再串行经过的两个阶段。本章只解释作用、关键证据和计数，未展开完整消息格式、状态传输与实现优化。[原论文 §4.3—4.4](https://www.usenix.org/legacy/publications/library/proceedings/osdi99/full_papers/castro/castro_html/node4.html)

### 认证还要配合协议状态检查

论文使用数字签名、Message Authentication Code（MAC，消息认证码）及抗碰撞摘要保护来源与完整性；正常路径的简化描述使用签名，§5 讨论 MAC 优化。TLS 保护连接，仍不能替代协议消息认证、视图与水位检查、摘要匹配，以及按发送者去重计票。客户端请求身份和已保存回复还用于识别旧请求与重复请求，防止重放被当作新的业务操作。

副本通常无法预先识别哪个节点会作恶。未认证、冲突、过期或不满足接收条件的消息不能计入有效证据；来自故障节点的消息若满足验证条件，并不因观察者“知道它可能故障”就自动被排除，协议靠故障预算和交集保护安全。本图让 B3 沉默，证明无需依赖它的任何票即可推进，没有把无效消息画成有效投票。

## 4. PoW 用计算成本参与历史选择 {#_4-pow-不是普通节点多数表决}

以 Bitcoin 论文为例，工作量证明用可验证的计算成本参与开放环境下的历史选择。安全假设与算力、网络传播和链的工作量相关，不是注册越多节点、IP 越多就获得更多合法票。

“得到多数节点认可就达成共识”不足以描述它。链还可能短暂分叉并重组，确认深度与风险依赖模型；不能将其当成 Raft 那样的确定提交点，也不把本章当成任何资产建议。[Bitcoin 原论文 §4—5](https://bitcoin.org/bitcoin.pdf)

PoW（Proof of Work，工作量证明）比较通过有效性检查的候选链的**累计工作量**。论文的“最长链”应结合其“投入最多工作量”的解释阅读，不是简单数区块，也不是多数普通节点表决。

只看累加规则的教学算术例子：分支 A 有三个区块，抽象工作量为 `1+1+1=3`；分支 B 有两个区块，为 `1+3=4`，数量更少却累计更多。这个例子不代表真实 Bitcoin 的任意两个同高度区块可以自由设置难度；每块的计入权重必须符合链的合法目标难度规则。实际试了多少次哈希、偶然得到更多前导零，都不能直接当作额外可计入的工作量。作为实现对照，Bitcoin Core **v29.0** 的 `GetBlockProof` 按区块声明且需通过规则校验的目标值计算工作量。[固定版本源码](https://github.com/bitcoin/bitcoin/blob/v29.0/src/chain.cpp#L119)

不同节点可能暂时看到不同分支；后续区块让另一条有效分支的累计工作量超过当前分支时，节点可能重组到它。更多确认通常提高追赶所需的工作量；在论文的诚实算力与传播假设下，落后攻击者追上的概率随确认深度降低。但这不是确定的提交证明，也不是脱离攻击者算力比例和网络条件的统一安全阈值。[Bitcoin 原论文 §4—5、§11](https://bitcoin.org/bitcoin.pdf)

## 5. 按身份、故障预算与结果解释对照 {#_5-对照时先问问题}

| 维度     | 崩溃容错日志协议   | 经典 PBFT              | PoW 链模型                  |
| -------- | ------------------ | ---------------------- | --------------------------- |
| 参与身份 | 通常已知成员       | 通常已知、可认证副本   | 开放参与，另处理 Sybil 成本 |
| 故障预算 | 按崩溃与多数等条件 | 按拜占庭预算与协议条件 | 按算力及传播等假设          |
| 结果解释 | 适用提交与恢复规则 | 适用证明与视图规则     | 工作量、确认与重组风险      |

PBFT 的结果依赖已认证成员的阶段证据，典型风险包括超过故障副本预算、网络条件不足导致无法推进；PoW 的参与资格与工作量有关，典型风险包括算力攻击、传播受阻和链重组。PBFT 的 f 是副本故障预算，不能套成 PoW 的节点数量比例；PoW 的多数算力假设也不是多数 IP 或节点投票。

经典 PBFT 正常路径中的全互联通信可呈二次量级，但这一结论不能概括所有 BFT 变体、阶段和部署的性能。算法名称只是阅读入口；判断其保证是否适用，应先核对故障模型。

故障前提可回看[第 1 章故障模型](/articles/distributed-failure-models.html)；与崩溃容错比较时联读[第 8 章 Paxos](/articles/distributed-paxos.html)和[第 9 章 Raft](/articles/distributed-raft-election.html)。前一章的[故障验证](/articles/distributed-observability-backpressure.html)也应先选定模型，再决定要检查哪些不变量。

[返回本册目录](/collections/distributed-systems/)
