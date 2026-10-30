---
id: distributed-rpc-retries-idempotency
title: 第二章 RPC、超时、重试与业务幂等
description: "远程过程调用（RPC）让客户端向另一个进程发起操作并等待返回。请求发送、服务端执行和响应返回是不同阶段：客户端超时时，服务端可能尚未执行，也可能已经完成但响应丢失。"
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
order: 2
---

# 第二章 RPC、超时、重试与业务幂等

> 阅读标签：通用协议/应用模型，具体前提见本章。

远程过程调用（Remote Procedure Call，RPC）让客户端向另一个进程发起操作并等待返回。请求发送、服务端执行和响应返回是不同阶段：客户端超时时，服务端可能尚未执行，也可能已经完成但响应丢失。后续的重试与幂等设计，就从辨认这几种状态开始。

## 1. 请求、执行与回复的三种超时历史 {#_1-一次超时对应哪些历史}

假设客户端要求为订单 o-42 扣款 100 元，携带操作 ID `pay-42`，单次等待上限为 100 ms。超时（Timeout）表示一次等待超过限定时长。下面是三种独立的教学时序，时间数字是为讲解设定的，不是测量结果。

| 历史       | 扣款时序                                       | 客户端在 100 ms 时知道什么     |
| -------- | ------------------------------------------ | --------------------- |
| 请求未到达    | 0 ms 发送；请求在网络中丢失，服务端未收到                    | 没有及时得到结果，无法仅凭超时识别请求丢失 |
| 服务端仍在执行  | 0 ms 发送；20 ms 开始处理；100 ms 客户端超时；150 ms 才提交 | 等待已结束，服务端仍可能继续完成扣款    |
| 已提交、响应丢失 | 0 ms 发送；60 ms 数据库提交；回复在网络中丢失；100 ms 客户端超时  | 扣款可能已经成功，只是没有收到回复     |

![Client、Network、Server、Database 四条泳道中的三种独立超时历史及同 ID 重试](/assets/notes/distributed-systems/dist-rpc.svg)

[打开 RPC 时序原图](/assets/notes/distributed-systems/dist-rpc.svg)。图中从上到下表示各分支内部的先后，不按前述毫秒数等比例绘制。示例假设网络最终恢复且原操作最终完成，所以能返回明确结果；持续故障时仍需保留待查询状态。

**客户端超时只能说明没有及时获得结果，不能直接证明服务端没有执行。** 因此，超时后不能直接判定“扣款失败”并重新发起一笔扣款。新请求如果更换业务标识，服务端可能将其视为另一笔操作。相关失败历史与重试前提见 [AWS 的超时、重试与退避说明](https://builder.aws.com/content/3EumjoZascWd1oZiEgL8ORlv3qE/timeouts-retries-and-backoff-with-jitter)。

## 2. 幂等键保护的是业务操作身份

幂等（Idempotency）指同一操作重复请求时，不再增加业务副作用。幂等键标识的是这一次业务意图，例如 `tenant_id + operation_type + operation_id`，分别表示租户、操作类型和操作 ID。客户端必须在首次调用前保存 ID，后续查询或重试复用原 ID；每次生成新 ID 会被视为新操作。

只做“先查有没有，再执行”不够。教学推演：请求甲和乙同时查询 `pay-42`，都读到不存在，随后都扣款。唯一约束（Unique Constraint）让数据库保证同一作用范围内的键只能有一条记录；原子插入或条件更新则把“检查并占用执行资格”合成一个不可被并发请求拆开的动作。后续动作还要受事务或执行资格约束，不能让竞争失败的一方也执行业务。

可以用以下概念状态讲解：

```text
NOT_SEEN → IN_PROGRESS → COMPLETED
尚未记录    正在处理       已保存最终结果
```

`NOT_SEEN` 表示不存在记录；`IN_PROGRESS` 表示有一个执行者；`COMPLETED` 表示可以重放结果。参数摘要由规范化后的业务参数生成，用于识别同一 ID 是否被误用于另一笔意图，例如将金额从 100 元改成 200 元。

下面是**业务变更全部位于同一个数据库**时的教学伪代码，不是完整实现：

```text
key = (tenant_id, operation_type, operation_id)
BEGIN
    原子插入 (key, 参数摘要, IN_PROGRESS)，key 有唯一约束
    如果键已被占用：
        按数据库语义等待竞争事务提交或回滚；锁等待受超时限制
        若对方回滚且记录不存在：重新竞争，不能直接跳到业务变更
        若记录存在且参数摘要不同：结束当前事务，拒绝参数冲突
        若为 COMPLETED：结束当前事务，返回已保存结果
        若仍为 IN_PROGRESS：结束当前事务，返回处理中或有界等待
    只有成功插入者：
        执行业务变更
        更新为 COMPLETED，并保存可重放结果
COMMIT
向客户端返回结果
```

这个单事务方案中，外部请求通常看不到尚未提交的 `IN_PROGRESS`，而是先等待唯一键或写锁；崩溃回滚时业务变更和占用记录一起撤销。如果采用“先提交处理中记录、后台再执行”的长任务方案，`IN_PROGRESS` 才会成为独立持久状态，需要执行者身份、条件更新和恢复机制。恢复者应查询实际效果或对账；不能仅因记录超时就删除它并重新扣款。

`UNKNOWN` 是客户端目前无法确认结果的认知状态，不应直接当作服务端已持久化的失败终态。只有能确认未产生副作用的业务拒绝等情况，才适合按协议保存明确失败结果。

关键在于“业务效果”与“去重记录”是否处于同一原子边界。如果先扣款，再到另一个存储中记录已处理，两步之间崩溃仍可能导致重复扣款。副作用若发生在外部支付系统，则需要对方支持稳定操作标识，或提供可查询、可对账的状态协议。

同一个 ID 不能无限期保护所有未来重放。去重记录保留期应覆盖协议允许的重试与迟到请求窗口；清理后再次收到旧 ID，可能被当作新操作。长生命周期的订单还可保留业务唯一约束。历史是否可能恢复到旧版本，也要纳入约束。稳定 ID、参数冲突、原子保存与迟到请求的依据见 [AWS 的幂等 API 设计说明](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)。

## 3. 尝试次数、传输与业务效果 {#_3-不要把-exactly-once-当成传输属性}

先声明讨论的是投递、执行还是效果：

| 语义                             | 含义与边界                          |
| ------------------------------ | ------------------------------ |
| 最多一次投递（At-most-once delivery）  | 交付给接收方零次或一次，可能丢失工作             |
| 至少一次投递（At-least-once delivery） | 在重试、可达性等约定条件满足时最终至少交付一次，可能重复   |
| 恰好一次业务效果（Exactly-once effect）  | 在明确的业务范围和故障假设内，同一操作最终只产生一次约定效果 |

投递语义与确认、重投的产品实例见 [RabbitMQ 的可靠性说明](https://www.rabbitmq.com/docs/reliability#acknowledgements-and-confirms)；这里借用其术语区分层次，不涉及具体版本配置。

网络只投递一次、服务端代码只执行一次、业务效果只发生一次，是三个不同保证。重复执行代码可以读到已有结果而不再扣款；反过来，只发一次请求也可能根本没成功。要实现业务效果一次，需要稳定的业务操作身份、持久化去重记录、业务变更与去重状态的原子边界，以及外部副作用的幂等协议或状态查询机制。对于成功的操作，还需要系统最终恢复并完成它；幂等本身只限制重复副作用。

例如消息消费成功后、确认前崩溃，消息可能再次出现。用消息 ID 去重只有在去重状态与业务提交相容时才有意义；“先把消息 ID 写入 Redis，再修改另一个数据库”仍有两个独立提交点。

**本地数据库事务不能自动让远程支付系统参与同一个原子提交。** 远程扣款成功、本地保存结果前崩溃时，应使用远程系统支持的同一幂等键重试，或查询并对账；查询本身还要能处理仍在执行的操作。这里的原子性要求对应 [AWS 幂等 API 文中的 ACID 讨论](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/)。

## 4. 重试也会制造故障

服务已经过载时，每层都立即重试会放大流量。假设入口 → 订单 → 库存 → 数据库有三层调用，每层独立重试，并且每次都耗尽完整下游尝试：

- 每层**总共尝试三次**，即首次加两次重试，底层最多收到 `3 × 3 × 3 = 27` 次尝试。
- 每层**首次加三次重试**，总共四次，底层最多收到 `4 × 4 × 4 = 64` 次尝试。

这是没有提前成功、没有被截止时间截断的教学上界算例，不是压测结果。重试次数与总尝试次数必须分开计数。逐层放大与选择单层重试的依据见 [AWS 重试说明](https://builder.aws.com/content/3EumjoZascWd1oZiEgL8ORlv3qE/timeouts-retries-and-backoff-with-jitter)。

截止时间（Deadline）是整个操作最晚结束等待的时间边界；单次超时只限制某次尝试。退避（Backoff）是失败后先等待再重试，让下游有机会恢复。指数退避（Exponential Backoff）让等待上限逐次增长；随机抖动（Jitter）让客户端随机选择等待时长，减少大量客户端同一时刻再次冲击下游。

教学参数示例：整个操作预算 1 秒，单次最多等待 200 ms，总共最多三次尝试；两次重试前分别从 `[0, 50 ms]`、`[0, 100 ms]` 均匀随机取等待时长。每次发起前重新计算剩余预算，单次等待不能超过剩余时间；预算耗尽就停止自动重试，保留同 ID 的查询入口。这些数字仅用于讲解，不是推荐的生产参数。

通常选择一层统一管理重试预算，其他层传递失败与剩余截止时间。参数冲突、明确业务拒绝不应盲目重试；结果不明的写操作需要先有幂等协议。即使业务请求已超过截止时间，也不能保证服务端会自动取消已接受的变更。

## 5. 用故障时序检查幂等设计 {#_5-学习验证要检查什么}

纸面检查至少覆盖：首次成功但回复丢失；重复 ID 参数改变；处理中崩溃；成功记录被清理后迟到重试。验收目标不是“没有重复日志”，而是同一业务操作只产生允许的持久效果，且未知状态可以查询或人工对账。

### Python + SQLite 单机教学实验

将以下代码保存为 `rpc_demo.py`，运行 `python rpc_demo.py`。程序在临时目录创建数据库，记录一笔订单扣款；第一次提交后主动抛出超时，模拟响应丢失，再用同一 ID 重试。复合主键提供唯一约束，`BEGIN IMMEDIATE` 让本例的写事务先获得写入资格。SQLite 一次只允许一个写事务，等待写锁也可能超时；这与多节点服务的调度模型不同。依据见 [SQLite 事务](https://www.sqlite.org/lang_transaction.html) 和 [唯一约束冲突处理](https://www.sqlite.org/lang_conflict.html)。

```python
import hashlib
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path


def charge(path, operation_id, amount, lose_reply=False):
    key = ("tenant-1", "charge", operation_id)
    payload = json.dumps(["o-42", amount], separators=(",", ":"))
    digest = hashlib.sha256(payload.encode()).hexdigest()
    db = sqlite3.connect(str(path), isolation_level=None, timeout=5)
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute(
                "INSERT INTO charges VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (*key, digest, "o-42", amount, "IN_PROGRESS", None),
            )
        except sqlite3.IntegrityError:
            row = db.execute(
                "SELECT digest, state, result FROM charges "
                "WHERE tenant=? AND kind=? AND operation_id=?", key,
            ).fetchone()
            if row is None:
                raise
            if row[0] != digest:
                raise ValueError("same ID, different parameters")
            if row[1] != "COMPLETED":
                raise RuntimeError("still processing; query later")
            result = row[2]
        else:
            # 本地扣款账本就是这条记录，不调用外部支付系统。
            result = f"charged:o-42:{amount}"
            db.execute(
                "UPDATE charges SET state='COMPLETED', result=? "
                "WHERE tenant=? AND kind=? AND operation_id=?",
                (result, *key),
            )
        db.execute("COMMIT")
    except Exception:
        if db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()
    if lose_reply:
        raise TimeoutError("reply lost after commit")
    return result


with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "orders.db"
    with closing(sqlite3.connect(str(path))) as db:
        db.execute("""CREATE TABLE charges (
            tenant TEXT NOT NULL, kind TEXT NOT NULL,
            operation_id TEXT NOT NULL, digest TEXT NOT NULL,
            order_id TEXT NOT NULL, amount INTEGER NOT NULL CHECK(amount > 0),
            state TEXT NOT NULL, result TEXT,
            PRIMARY KEY (tenant, kind, operation_id)
        )""")
        db.commit()
    try:
        charge(path, "pay-42", 100, lose_reply=True)
    except TimeoutError as error:
        print(error)
    print("retry:", charge(path, "pay-42", 100))
    try:
        charge(path, "pay-42", 200)
    except ValueError as error:
        print("conflict:", error)
    with closing(sqlite3.connect(str(path))) as db:
        count, total = db.execute(
            "SELECT COUNT(*), SUM(amount) FROM charges WHERE state='COMPLETED'"
        ).fetchone()
    assert (count, total) == (1, 100)
    print(f"charges={count}, total={total}")
```

已于 2026-10-30 在 Windows、Python 3.8.10、SQLite 3.35.5 下执行上述命令，退出码为 0，输出与以下预期一致：

```text
reply lost after commit
retry: charged:o-42:100
conflict: same ID, different parameters
charges=1, total=100
```

这是单机教学实验：事务内的扣款账本与去重记录使用同一行，完成后才提交，崩溃前未提交的变更会一起回滚。它不代表跨数据库、跨服务或外部支付已实现端到端 Exactly-once，也没有模拟真实网络、进程崩溃与锁竞争。

下一步阅读时间与一致性：请求身份回答“是不是同一件事”，时钟和顺序回答“这些事如何比较先后”。

[返回本册目录](/collections/distributed-systems/)
