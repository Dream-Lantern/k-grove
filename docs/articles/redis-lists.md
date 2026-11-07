---
id: redis-lists
title: 第五章 List、阻塞读取与可靠任务转移
description: "List 是按顺序保存字节串的序列，支持两端插入与弹出。它既能表达栈，也能表达队列；选哪一端必须前后一致。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - redis
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: redis
series: redis-learning
order: 5
---

# 第五章 List、阻塞读取与可靠任务转移

List（列表）是按顺序保存字节串的序列，支持两端插入与弹出。它既能表达栈，也能表达队列；选哪一端必须前后一致。

本章 `redis` 代码块均是 Redis 命令，可在 `redis-cli` 交互环境输入。示例和预期返回均未实测；假定学习键起初不存在，无其他客户端修改，除非另有说明。普通命令按 Redis Open Source 7.2.0 语义讲解，历史版本另行标注。

## 1. 先画清左右方向

新增例子，未执行：

```redis
RPUSH demo:tasks task-a task-b
LPOP demo:tasks
LRANGE demo:tasks 0 9
LLEN demo:tasks
```

上述命令预期依次返回列表长度 `2`、`"task-a"`、`["task-b"]`、剩余长度 `1`。RPUSH 依次从右端追加，LPOP 从左端取出，形成 FIFO（First In, First Out，先进先出），适合按入队顺序领取任务。若在 LPUSH 后使用 LPOP，则从同一侧存取，形成 LIFO（Last In, First Out，后进先出）的栈行为。RPOP 则从右端弹出。

LRANGE 的结束下标包含在结果里，0 -1 表示全部。列表很长时，不要把全量范围读取当作无成本查看。

## 2. 阻塞的是等待中的客户端

BLPOP、BRPOP 可以在暂时没有元素时等待，时间单位是秒；0 表示不因该等待超时而结束，不代表永久无条件存活。连接、进程或权限异常仍会终止等待。

一个客户端等待空列表，不会让整个 Redis 停止处理其他命令。这与执行一个耗时脚本占用主要执行路径不同。

BLPOP 检查多个键时，先从参数左侧寻找非空列表。以下使用单实例、全新的学习键；两个列表都已就绪时，优先取 a，不比较两边任务的入队时间：

```redis
RPUSH demo:queue:a task-a
RPUSH demo:queue:b task-b
BLPOP demo:queue:a demo:queue:b 10
```

预期依次返回 `1`、`1` 和 `["demo:queue:a", "task-a"]`。若执行 BLPOP 时两边都为空，会让当前连接等待，最多 10 秒；超时返回 nil。阻塞期间该连接不能像空闲连接一样继续逐条交互，生产者或其他工作应使用另一条连接。

同一个键有多个阻塞客户端时，等待更久的客户端优先。客户端被唤醒后若再次阻塞，会重新排入等待顺序，不保留原优先位置。阻塞后多个键先后变为就绪还涉及就绪顺序，因此这些规则不代表所有生产者、消费者和键之间存在全局公平保证。[BLPOP 优先级规则](https://redis.io/docs/latest/commands/blpop/#what-key-is-served-first-what-client-what-element-priority-ordering-details)

| 命令   | 行为                                                     |
| ------ | -------------------------------------------------------- |
| LMOVE  | 立即尝试在源、目标 List 之间移动一个元素；源为空返回 nil |
| BLMOVE | 移动一个元素；源为空时阻塞等待                           |
| BLPOP  | 阻塞等待并删除返回列表的头部元素，不放入处理中列表       |
| BRPOP  | 阻塞等待并删除返回列表的尾部元素，不放入处理中列表       |

LMOVE、BLMOVE 自 Redis Open Source 6.2.0 起可用。BLMOVE 的 timeout 单位为秒，可用小数，`0` 表示无限等待数据，但不排除连接异常。以下源和目标都不存在，若没有其他连接在两秒内写入源列表，预期超时返回 nil；等待本身不会创建任务：

```redis
BLMOVE demo:{blocking}:ready demo:{blocking}:processing LEFT RIGHT 2
```

多键命令在 Redis Cluster（Redis 集群）中须满足同一 Hash Slot（哈希槽，即键所在的分片单元）约束。上面的 a、b 示例仅供单实例使用；`{blocking}` 是 Hash Tag（哈希标签），让源和目标按相同内容计算槽。[BLMOVE](https://redis.io/docs/latest/commands/blmove/) · [Cluster 多键规范](https://redis.io/docs/latest/operate/oss_and_stack/reference/cluster-spec/#implemented-subset)

## 3. 简单弹出队列的丢失窗口

如果消费者 LPOP 成功后立即崩溃，任务已离开待处理列表，业务却没有完成。List 本身没有自动给这条任务补一个确认与重投协议。

一种教学设计是把待处理项原子地移到处理中列表，再由应用完成业务后确认并清理。任务因此先保留在可追踪的处理中状态：

![待处理、处理中与业务确认的分工](/assets/notes/redis/redis-study-list-work.svg)

LMOVE / BLMOVE 的原子性（Atomicity）保证两个 Redis List 的移动操作不会被其他客户端命令插入：不会出现任务已从源移除、却尚未放入目标的可见中间状态。以下正常路径使用 Redis Open Source 6.2.0 起支持的 LMOVE，假定学习键起初不存在、任务 ID（Identifier，标识符）唯一，没有其他消费者，未执行：

```redis
RPUSH demo:{tasks}:ready task-a task-b
LMOVE demo:{tasks}:ready demo:{tasks}:processing LEFT RIGHT
LRANGE demo:{tasks}:processing 0 9
```

预期 task-a 从 ready 左侧进入 processing 右侧，而不是消失；task-b 仍待领取。业务成功提交后，按实际领取的唯一 ID 清理该项：

```redis
LREM demo:{tasks}:processing 1 task-a
```

在上述无竞争前提下，预期删除数为 1。若业务失败或消费者崩溃，不应提前执行这次确认。这段流程只覆盖正常处理时的移动—业务—确认过程，下面的接管协议仍需由应用实现。

两个键使用相同 Hash Tag 是为了满足 Cluster 同槽约束。**LMOVE 只保证 Redis 内部移动的原子性，不保证 Redis 操作与数据库扣款等外部业务构成同一个原子事务。**它能避免移动过程中的任务丢失窗口，却不能保证外部业务只执行一次；Redis 数据在故障后的保留仍取决于持久化和复制策略。[LMOVE 的版本和可靠队列模式](https://redis.io/docs/latest/commands/lmove/)

例如：消费者移动任务到 processing → 数据库扣款成功 → 消费者崩溃，尚未 LREM → 应用发现超时后重投 → 新消费者再次扣款。业务实际成功与 Redis 确认完成之间的窗口会产生 Duplicate Processing（重复处理，即同一任务再次执行）。

在队列数据仍然保留、应用持续恢复未确认任务的前提下，这种协议可实现 At-least-once Delivery（至少一次投递）：任务可能交给消费者多次，不能因已投递过就直接丢弃。应用需要 Idempotency（幂等性），使同一业务操作重复请求时不重复扣款，例如由数据库在提交扣款的同一事务中校验并记录业务事件标识。Exactly-once Processing（恰好一次处理）要求在明确范围内业务效果只发生一次，不是 LMOVE 或 LREM 自动提供的保证。业务失败、消费者崩溃、确认命令结果丢失，都应纳入恢复与去重设计。

## 4. 发现超时任务、重新领取与幂等恢复 {#_4-可靠性仍有应用部分}

应用要记录处理时间、重试次数、任务标识和可接管条件。Lease（租约）是应用授予一次处理尝试的有限有效期，用于决定何时可接管；它不是消费者已死亡的证明。典型竞争如下，属于故障场景推演：

```text
消费者 A 领取任务 → A 长时间暂停 → 租约过期
                                      ↓
                                B 接管并重新领取
                                      ↓
                                A 恢复，仍想执行
```

A、B 可能同时操作同一任务。每次领取应有新的 Attempt ID（Attempt Identifier，处理尝试标识），确认和恢复时原子地校验它仍是当前尝试，拒绝旧 A 清理 B 的处理中记录。单纯在客户端先检查、再单独 LREM 仍有竞争窗口；上节无竞争示例中的 LREM 不是完整并发确认协议。

Fencing Token（栅栏令牌）进一步用单调递增的令牌表示处理资格，由下游系统校验并拒绝旧令牌，防止暂停后恢复的旧消费者继续写入。随机 Attempt ID 本身不具备这种大小顺序；外部业务仍需要幂等或版本校验，只有 Redis 里记录令牌并不够。基本思想与完整边界见 [第 28 章：锁、限流与业务幂等](/articles/redis-locks-rate-limits.html)。

恢复状态机的教学顺序是：识别超时任务 → 验证当前处理资格/尝试标识 → 原子地登记重试并转回待处理状态 → 再次领取 → 幂等处理 → 按当前尝试确认。processing List 本身没有处理时间、owner（当前处理者）或租约字段，不能单靠 LRANGE 判断旧进程已死；租约等关联状态与转移若分开更新，也会产生新的崩溃窗口。完整实现需要受控原子逻辑和外部副作用幂等，不是后台定时 LREM 后 RPUSH 两步就自动可靠。

若列表中允许任务内容重复，仅用 LREM 删除某个字符串，可能误删另一份内容相同的任务。因此，应为任务设置明确身份，不能因内容相等就认定属于同一次处理。

需要消费组和 Pending Entries List（PEL，待确认条目列表，用于追踪已投递未确认消息）时，可以考虑 Streams（带消息标识的流）。两者的分工如下：

| 维度                                | List                             | Streams                                       |
| ----------------------------------- | -------------------------------- | --------------------------------------------- |
| 数据组织                            | 有序列表                         | 带 ID 的消息流                                |
| 消费进度                            | 应用自行管理                     | 支持 Consumer Group（消费者组）分配与跟踪消息 |
| Pending 状态                        | 应用自行维护                     | 内置 PEL                                      |
| ACK（Acknowledgment，处理完成确认） | 应用实现，例如受控清理处理中记录 | 使用 XACK                                     |
| 故障接管                            | 应用实现                         | 支持消息认领，应用仍需决定何时接管            |
| 典型用途                            | 简单队列                         | 消息处理和事件流                              |

Streams 也不自动提供外部业务的恰好一次效果，详见 [第 12 章：Streams](/articles/redis-streams.html)。本章不展开其详细命令。

## 5. 修剪、随机访问与对象规模

LREM 根据 count 的正负与大小决定方向和数量；LTRIM 保留指定下标范围，会丢弃范围外内容，属于真实数据变更。

中间位置访问、删除匹配元素与两端操作的成本不同。下表是官方命令文档描述的时间复杂度，即工作量随数据规模增长的趋势，不是固定耗时：

| 命令          | 复杂度特点                      | 说明                                        |
| ------------- | ------------------------------- | ------------------------------------------- |
| LPUSH / RPUSH | 每个元素 O(1)，添加 K 个为 O(K) | 批量添加按元素数量增长                      |
| LPOP / RPOP   | 每个元素 O(1)，返回 K 个为 O(K) | count 参数自 Redis Open Source 6.2.0 起可用 |
| LLEN          | O(1)                            | 读取已维护的长度                            |
| LMOVE         | O(1)                            | 原子移动一个元素                            |
| LRANGE        | O(S+N)                          | 定位起点，再返回指定范围                    |
| LREM          | O(N+M)                          | 扫描列表并删除匹配元素                      |
| LINDEX        | O(N)                            | 中间位置需遍历；首尾访问为 O(1)             |

K 是批量添加或返回的元素数；LRANGE 中 S 是定位起始位置需走过的距离，N 是返回数量（官方文档区分小列表从头与大列表从较近端定位）；LREM 中 N 是列表长度、M 是删除数量；LINDEX 中 N 是到目标位置需遍历的数量。各行的符号按该行含义解释。[LPUSH](https://redis.io/docs/latest/commands/lpush/) · [RPUSH](https://redis.io/docs/latest/commands/rpush/) · [LPOP](https://redis.io/docs/latest/commands/lpop/) · [RPOP](https://redis.io/docs/latest/commands/rpop/) · [LLEN](https://redis.io/docs/latest/commands/llen/) · [LRANGE](https://redis.io/docs/latest/commands/lrange/) · [LREM](https://redis.io/docs/latest/commands/lrem/) · [LINDEX](https://redis.io/docs/latest/commands/lindex/)

内部编码用于平衡内存和访问成本。quicklist（快速列表）把多个紧凑节点连成双向链表：节点内连续存放多个元素，减少逐元素指针开销；两端操作通常只需处理端部节点，避免每次重排整个长列表。紧凑节点内部的插入和移动仍有成本，节点大小也会影响内存和延迟。

| Redis Open Source 版本参照 | List 的表示                                                                                       |
| -------------------------- | ------------------------------------------------------------------------------------------------- |
| 6.2.0                      | quicklist，紧凑节点使用 ziplist（压缩列表）                                                       |
| 7.0.0                      | quicklist，紧凑节点改为 listpack（紧凑列表）；大元素可用单独节点                                  |
| 7.2.0                      | 小 List 可直接用 listpack，超出节点大小或元素数量条件时转为 quicklist；符合条件的缩小路径也可转回 |
| 7.4.0、8.0.0               | 仍有 listpack / quicklist 及相应转换路径，不概括为所有 List 只有一种编码                          |

这里以固定版本为证，不把“6.2 及以前”外推到更早曾使用其他结构的版本。7.2.0 的转换检查使用 `list-max-listpack-size` 对应的节点容量规则，还会检查节点数量与安全余量，不能只看 List 元素总数。具体诊断可用 `OBJECT ENCODING`，但不应把内部阈值当成应用协议。[6.2.0 t_list.c](https://raw.githubusercontent.com/redis/redis/6.2.0/src/t_list.c) · [7.0.0 quicklist.c](https://raw.githubusercontent.com/redis/redis/7.0.0/src/quicklist.c) · [7.2.0 t_list.c](https://raw.githubusercontent.com/redis/redis/7.2.0/src/t_list.c) · [7.4.0 t_list.c](https://raw.githubusercontent.com/redis/redis/7.4.0/src/t_list.c) · [8.0.0 t_list.c](https://raw.githubusercontent.com/redis/redis/8.0.0/src/t_list.c)

持续积压时，关注任务数量、每条尺寸、消费者速率和失败比例。只是不断增大 List 容量，通常不能修复消费者错误或下游瓶颈。

[返回本册目录](/collections/redis/)
