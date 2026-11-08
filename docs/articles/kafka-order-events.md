---
id: kafka-order-events
title: 第 24 章：订单事件案例与故障推演
description: "场景：订单创建后，库存服务应对每条有效扣减事件最多产生一次扣减效果；系统故障后允许重新读取消息，但不允许静默跳过未完成订单。"
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
order: 24
---

# 第 24 章：订单事件案例与故障推演

> 版本基线：Kafka Broker 3.9、Java Client 3.9 与 librdkafka v2.8.0。
>
> 学习目标：把前面各章的边界放进一条完整链路。以下是合成设计与纸面故障推演，不是个人项目经历或已完成的实验。

## 1. 先定义业务不变量

场景：订单创建后，库存服务应对每条有效扣减事件最多产生一次扣减效果；系统故障后允许重新读取消息，但不允许静默跳过未完成订单。这个要求并不是“网络只发送一次”，而是约束最终业务效果与恢复能力。

事件包含稳定 event_id、order_id、事件类型、模式版本和业务版本等信息。订单路由使用明确且跨客户端一致的 Key 策略；模式演进有兼容检查，不把未识别版本当正常成功。

[![订单 Outbox：分区保序与业务效果幂等](/assets/notes/kafka/kf-case.svg)](/assets/notes/kafka/kf-case.svg)

安全性要求在故障期间也成立。源订单与 Outbox（事务待发表）原子提交，同一扣减操作最多生效一次，库存不为负，旧版本不能覆盖新状态，未完成事件不能被位点跳过。活性要求在依赖恢复、事件仍可取得且业务前置条件满足时，Relay 能重领待发记录，Consumer 能恢复重试。无法自行恢复的事件要进入有记录的隔离与人工修复流程。至少一次投递提供重放机会，永久失败仍需业务处置。

```json
{
  "event_id": "evt-1001",
  "order_id": "order-001",
  "event_type": "INVENTORY_DEDUCT",
  "sku_id": "sku-100",
  "quantity": 2,
  "schema_version": 1,
  "business_version": 1,
  "occurred_at": "2026-10-25T10:00:00Z"
}
```

| 字段                  | 契约                                                                  |
| --------------------- | --------------------------------------------------------------------- |
| `event_id`            | Event ID（事件身份），同一事件重发时稳定                              |
| `order_id`            | Order ID（订单身份），同时是 Kafka 路由 Key                           |
| `event_type`          | 本例只接受 `INVENTORY_DEDUCT`，表示增量扣减                           |
| `sku_id` / `quantity` | 库存品项及正整数扣减量                                                |
| `schema_version`      | Schema Version（消息格式版本），决定解析规则                          |
| `business_version`    | Business Version（业务版本），同一订单从 1 递增，每版恰有一项扣减操作 |
| `occurred_at`         | RFC 3339 UTC 业务时间，用于追踪，顺序以业务版本为准                   |

Business Operation ID（业务操作身份）由本例的订单、版本与类型共同确定。数据库以 `(order_id, business_version)` 约束本例唯一操作，因此不同事件 ID 仍可能指向同一扣减。若业务允许同一版本对多个 SKU 扣减，就应另建稳定操作 ID 或包含行号的唯一键，并重新定义版本推进规则。

## 2. 用 Outbox 连接数据库提交与事件发布 {#_2-源数据库与发布的缺口}

如果先提交订单数据库再发送 Kafka，中间崩溃可能留下订单但没有事件。反过来先发事件再提交数据库，可能产生没有对应订单的事件。

Outbox 将订单与待发事件记录放进同一个本地数据库事务，再由发布器发送。它解决的是源业务变更和待发事实的原子记录问题，不会消除发布器“已发送但状态未更新”造成的重复。因此事件 ID 必须稳定，不能每次重试都生成新 ID。

顺序是另一条不变量：E1(version=1) 先提交，E2(version=2) 后提交，但两个 relay 却先发 E2、再发 E1。即使使用相同的 order_id Key，也只会把 E2→E1 这个发布顺序写入同一分区。两条事件的 event_id 不同，不会触发重复过滤，仍可能出现旧状态覆盖新状态的情况。因此，需要按订单串行发布，或验证 CDC 能否保序，并由消费端分别处理重复、旧版本与版本缺口。[Outbox主文与三类输入](/articles/distributed-saga-tcc-outbox.html)

### PostgreSQL 17 源库事务

在专用源数据库执行建表。真实应用使用绑定参数，核对版本更新及 Outbox 插入各返回一行再提交。

```sql
CREATE TABLE orders (
    order_id text PRIMARY KEY,
    business_version integer NOT NULL CHECK (business_version > 0)
);

CREATE TABLE order_outbox (
    event_id text PRIMARY KEY,
    order_id text NOT NULL REFERENCES orders,
    business_version integer NOT NULL CHECK (business_version > 0),
    payload jsonb NOT NULL,
    status text NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'SENDING', 'SENT')),
    claim_token uuid,
    lease_until timestamptz,
    retry_at timestamptz NOT NULL DEFAULT now(),
    attempts integer NOT NULL DEFAULT 0,
    last_error text,
    sent_at timestamptz,
    UNIQUE (order_id, business_version)
);

BEGIN;
INSERT INTO orders VALUES ('order-001', 1);
INSERT INTO order_outbox (event_id, order_id, business_version, payload)
VALUES ('evt-1001', 'order-001', 1,
        '{"event_id":"evt-1001","order_id":"order-001",
          "event_type":"INVENTORY_DEDUCT","sku_id":"sku-100","quantity":2,
          "schema_version":1,"business_version":1,
          "occurred_at":"2026-10-25T10:00:00Z"}');
COMMIT;
```

任一语句失败就回滚。创建 E2 时，在新事务用 `UPDATE orders SET business_version = 2 WHERE order_id = 'order-001' AND business_version = 1 RETURNING order_id` 确认推进，再插入 E2 Outbox，最后提交。若更新返回零行应回滚。重试创建请求时，应先核对稳定的业务身份与已有记录，避免误建下一版本。把两个写入拆开提交会重新打开源端缺口。

### Relay 领取、发送和恢复

以下 SQL 是一条短事务内的领取语句。参数 `$1` 绑定本次领取专用 UUID，应用提交领取事务后才发送：

```sql
WITH candidate AS (
    SELECT o.event_id
    FROM order_outbox o
    WHERE (o.status = 'PENDING' AND o.retry_at <= now()
           OR o.status = 'SENDING' AND o.lease_until <= now())
      AND NOT EXISTS (
          SELECT 1 FROM order_outbox older
          WHERE older.order_id = o.order_id
            AND older.business_version < o.business_version
            AND older.status <> 'SENT'
      )
    ORDER BY o.order_id, o.business_version
    LIMIT 1
    FOR UPDATE OF o SKIP LOCKED
)
UPDATE order_outbox o
SET status = 'SENDING', claim_token = $1,
    lease_until = now() + interval '30 seconds', attempts = attempts + 1
FROM candidate
WHERE o.event_id = candidate.event_id
RETURNING o.event_id, o.order_id, o.payload, o.claim_token;
```

1. 领取后按 `order_id` 作为 Key 发送原 Payload，保持事件 ID。等待最终投递结果。
2. 最终成功后更新为 SENT 并记录 `sent_at`。更新条件为事件 ID、`status='SENDING'` 和原 `claim_token`，核对影响行数。零行表示本次已失去数据库领取权。
3. 明确失败或结果未知时，按同样条件记录可脱敏的错误、设退避时间并改回 PENDING。已超过自动重试预算的事件进入告警和人工修复，后续同订单版本仍被挡住。Relay 崩溃则由扫描器在租约到期后重新领取。
4. 租约约束数据库状态更新。旧 Relay 已发出的 Kafka 请求可能仍成功，无法靠租约撤回。新 Relay 必须重用原事件 ID，下游仍需幂等。

这种按订单串行的方案只允许确认较早版本后推进后续版本，代价是慢事件会阻塞同订单后续发布。过期尝试仍可能晚到并产生重复。CDC（Change Data Capture，变更数据捕获）可从数据库变更日志读取已提交的 Outbox，需核对具体插件的事务顺序、任务并行、重试和 Kafka Key 路由。源库提交顺序只有在整条传输链满足相应契约时才会保留。

## 3. 生产与复制的可靠性条件

明确 Topic 分区与副本规划、acks/minISR、幂等生产、结果回调与重试预算，并监控副本状态。收到成功后才按约定推进发布状态；超时则按未知结果处理，不假定完全没发生。

即便配置正确，也不能省略跨故障域部署、保留策略、备份和权限设计。若操作失误删除了全部保留数据，消费组位点也无法凭空恢复业务事件。

教学配置可取 3 个 Partition、RF=3、`min.insync.replicas=2`、`acks=all` 和显式 `enable.idempotence=true`，前提是至少 3 个可用 Broker 和适当的机架故障域分布。Leader 按当前 ISR 确认，ISR 低于最小门槛时写入可失败。确认不等于所有副本同步刷盘，也无法覆盖同时失去所有副本或误删。保留窗应覆盖预期恢复时长，并准备可核对的备份或源事件。

幂等生产减少适用会话内重试的重复追加，Relay 重启或主动重新发送同一事件仍需业务去重。立即入队成功与最终投递报告分开记录。投递超时或响应丢失时，Kafka 可能已写入，应按未知结果恢复，不能据此生成新事件 ID。[C 生产者回调与退出](/articles/kafka-c-producer.html)

## 4. 消费数据库中的原子效果

库存消费者在一个本地事务中写入 event_id 去重记录并执行库存状态更新，必要时验证订单版本。成功后推进分区安全完成前沿，再提交恢复位置。

若外部效果是不能加入数据库事务的 HTTP 请求，则需要对端提供幂等键或另一种明确协议；仅在本地写一行“准备调用”不能证明对端已经或尚未执行。

### PostgreSQL 17 库存事务

在独立库存数据库建表。教学规则将库存不足视为可持久化的业务拒绝，拒绝也终结本版本。若业务允许等待补货，则应返回可重试结果并保留该版本，不能沿用此处的拒绝路径。

```sql
CREATE TABLE inventory (
    sku_id text PRIMARY KEY,
    available integer NOT NULL CHECK (available >= 0)
);

CREATE TABLE inventory_order_progress (
    order_id text PRIMARY KEY,
    last_version integer NOT NULL CHECK (last_version >= 0)
);

CREATE TABLE inventory_operation (
    order_id text NOT NULL REFERENCES inventory_order_progress,
    business_version integer NOT NULL CHECK (business_version > 0),
    event_id text NOT NULL UNIQUE,
    sku_id text NOT NULL REFERENCES inventory,
    quantity integer NOT NULL CHECK (quantity > 0),
    outcome text NOT NULL CHECK (outcome IN ('APPLIED', 'REJECTED_STOCK')),
    PRIMARY KEY (order_id, business_version)
);

CREATE TABLE inventory_event_identity (
    event_id text PRIMARY KEY,
    order_id text NOT NULL,
    business_version integer NOT NULL,
    FOREIGN KEY (order_id, business_version)
        REFERENCES inventory_operation (order_id, business_version)
        DEFERRABLE INITIALLY DEFERRED
);

INSERT INTO inventory VALUES ('sku-100', 10);

CREATE FUNCTION deduct_inventory(
    p_event text, p_order text, p_version integer,
    p_sku text, p_quantity integer
) RETURNS text LANGUAGE plpgsql AS $$
DECLARE
    current_version integer;
    prior inventory_operation%ROWTYPE;
    result text;
BEGIN
    IF p_event IS NULL OR p_order IS NULL OR p_sku IS NULL
       OR p_version IS NULL OR p_version <= 0
       OR p_quantity IS NULL OR p_quantity <= 0 THEN
        RAISE EXCEPTION 'invalid inventory event';
    END IF;

    INSERT INTO inventory_order_progress VALUES (p_order, 0)
    ON CONFLICT (order_id) DO NOTHING;

    SELECT last_version INTO STRICT current_version
    FROM inventory_order_progress WHERE order_id = p_order FOR UPDATE;

    INSERT INTO inventory_event_identity VALUES (p_event, p_order, p_version)
    ON CONFLICT (event_id) DO NOTHING;
    IF NOT EXISTS (
        SELECT 1 FROM inventory_event_identity
        WHERE event_id = p_event AND order_id = p_order
          AND business_version = p_version
    ) THEN
        RAISE EXCEPTION 'event identity conflict';
    END IF;

    SELECT * INTO prior FROM inventory_operation
    WHERE order_id = p_order AND business_version = p_version;
    IF FOUND THEN
        IF prior.sku_id <> p_sku OR prior.quantity <> p_quantity THEN
            RAISE EXCEPTION 'operation payload conflict';
        END IF;
        RETURN prior.outcome;
    END IF;

    IF p_version <= current_version THEN
        RAISE EXCEPTION 'old version has no matching operation';
    ELSIF p_version <> current_version + 1 THEN
        RAISE EXCEPTION 'business version gap';
    END IF;

    UPDATE inventory SET available = available - p_quantity
    WHERE sku_id = p_sku AND available >= p_quantity;
    IF FOUND THEN
        result := 'APPLIED';
    ELSE
        IF NOT EXISTS (SELECT 1 FROM inventory WHERE sku_id = p_sku) THEN
            RAISE EXCEPTION 'unknown SKU';
        END IF;
        result := 'REJECTED_STOCK';
    END IF;

    INSERT INTO inventory_operation
    VALUES (p_order, p_version, p_event, p_sku, p_quantity, result);
    UPDATE inventory_order_progress SET last_version = p_version
    WHERE order_id = p_order;
    RETURN result;
END;
$$;
```

Consumer 校验完整 Schema、事件类型、版本和数量，再执行 `BEGIN ISOLATION LEVEL READ COMMITTED`、绑定参数调用函数并 `COMMIT`。确认提交成功后才把记录标为已处理，由[分区连续完成前沿](/articles/kafka-offset-watermarks.html)决定 Kafka 提交位置。函数异常、死锁或连接故障时回滚或丢弃失效连接。重试时保持相同事件和业务操作身份，提交响应丢失也按同一身份核对。身份冲突、未知 Schema 或 SKU 需诊断和修复，不能直接当作已完成。

同订单由进度行锁串行化。相同事件或不同 ID 的同一操作，经内容匹配后返回原终态。不同订单竞争同一个 SKU 时，条件 UPDATE 对库存行加锁，并在 Read Committed 下重新判断扣减条件。先 SELECT 再把应用算出的绝对库存写回，可能覆盖其他事务的结果，造成 Lost Update（丢失更新）。若操作表插入因唯一约束失败，整个事务回滚，之前的扣减也撤销。

事件身份表保留每个已接受的事件 ID，包括同一业务操作的等价别名。延迟外键允许在同一事务中先登记事件，再插入操作终态。若相同 ID 被用于其他操作，事务会报错并回滚。

### E1 与 E2 的到达次序

以 E1 扣 2、E2 扣 3 为例。增量扣减还影响库存不足时哪个订单获准，不能把状态快照的覆盖规则套在这里。

| 到达情况               | 库存和版本              | 处理                                                   |
| ---------------------- | ----------------------- | ------------------------------------------------------ |
| E1 首次                | 10 → 8，版本 1          | 记录 APPLIED                                           |
| E1 重复或等价新事件 ID | 仍为 8，版本 1          | 返回原结果                                             |
| E2 随后到达            | 8 → 5，版本 2           | 记录 APPLIED                                           |
| E2 先于 E1             | 仍为 10，无有效版本推进 | 回滚并报告缺口                                         |
| 版本 2 已处理后重放 E1 | 仍为 5，版本 2          | 找到原操作并返回原结果。内容冲突或无历史凭证时停下核对 |

若 E2 在分区日志里早于 E1，仅暂停分区会挡住缺失事件。实验可有界读取并暂存后续记录，保留 E2 的提交缺口，先处理 E1 再重试 E2。若窗口内找不到 E1，停止推进并从源 Outbox 核对。生产设计若改用持久化隔离，必须先定义可靠移交与恢复协议。只有业务契约允许替代中间状态的完整快照，才可以按版本覆盖旧快照。

## 5. 四个窗口的纸面检查

| 故障位置                       | 恢复时可能发生什么     | 需要的机制                 |
| ------------------------------ | ---------------------- | -------------------------- |
| 订单事务未提交                 | 订单与 Outbox 均不生效 | 同一本地事务               |
| Kafka 已接收，发布状态未更新   | 发布器再次发送         | 稳定事件 ID、下游去重      |
| 库存事务已提交，消费位点未提交 | 消费者重新处理         | 数据库原子去重与更新       |
| 位点已经越过未完成库存任务     | 恢复时遗漏该业务       | 禁止提前提交，维护连续前沿 |

前三个窗口可以通过相应设计恢复；第四个窗口则说明，即使“Kafka 很可靠”，也无法弥补错误提交。发生重平衡时，还需防范旧工作线程延迟完成的操作带来影响。

下面扩展原图的四个窗口。以 E1 扣 2、正常恢复点从 100 到 101 为例：

| 注入位置                   | 崩溃前已知与未知状态                 | 恢复动作及验收                                             |
| -------------------------- | ------------------------------------ | ---------------------------------------------------------- |
| 源事务提交前               | 订单和 Outbox 都未持久化             | 核对两表均无记录，按稳定订单身份重试                       |
| 源事务提交后、Relay 前     | 有订单和待发事件，Kafka 尚未发布     | 重新扫描，确认相同事件 ID 到达                             |
| Kafka 接收后、标记 SENT 前 | 记录可能已可见，Outbox 仍待确认      | 租约过期后重发同一 ID，允许日志重复，库存只扣一次          |
| 多 Relay 乱序              | E2 可能先进入日志，E1 尚未处理       | E2 保留提交缺口，按版本补齐并核对两项操作                  |
| Consumer 处理前            | 库存未变，恢复点仍为 100             | 重放 E1 后扣到 8                                           |
| 库存事务提交前             | 可能已执行 UPDATE，事务仍未提交      | 确认操作记录与扣减均回滚，从 100 重试                      |
| 库存事务提交后、位点提交前 | 库存为 8，位点为 100 或提交结果未知  | 查 Broker 的实际恢复点。重放时确认只有一条操作             |
| 位点提前提交               | 101 已确认，库存可能仍为 10          | 从独立源事实识别缺项，经审核恢复。修复应用的连续前沿策略   |
| Rebalance 时旧任务在途     | 新旧实例可能同时尝试相同操作         | 通过数据库唯一键和锁串行化，旧任务结果不得推进新世代的位点 |
| 库存数据库不可用           | Kafka 仍可积压，业务结果未确认       | 有界重试并施加背压，恢复后核对提交前沿与库存               |
| 事件超过保留窗             | 有效恢复位置对应的数据可能已无法读取 | 停止自动跳过，使用源 Outbox 或备份补齐并核对事件与业务结果 |

## 6. 联合核对源状态、消费进度与业务效果 {#_6-验收不只看-lag-为零}

设计演练时核对源订单数、待发状态、稳定事件 ID、去重记录、最终库存效果、提交前沿及错误隔离记录。Lag 为零但业务失败全部被跳过，不算验收通过。

本文案例为纸面设计，尚无数据库、事件发送或故障实验结果。后续运行验证应在授权隔离环境中固定版本、负载和故障步骤，并记录预期与实际差异。

### 分阶段故障实验

前置条件为 PostgreSQL 17 两个专用数据库、隔离的 Kafka 3.9 和测试用 `review-orders-inventory` Topic。单分区可用于验证顺序，若只运行一个 Broker，则使用 RF=1 做功能测试。准备独立消费组 `review-inventory`。单 Broker 还需满足[内部位点 Topic 的创建条件](/articles/kafka-log-model.html)。以下 SQL 和集成步骤未在 PostgreSQL/Kafka 联机环境实测。

1. **正常流程**。分别用 `psql -v ON_ERROR_STOP=1` 执行源库与库存库的建表脚本。建立 E1 和 E2 两条 Outbox，E2 使用 `evt-1002`、版本 2、数量 3。用 Relay 伪代码连接 Producer，或由实验人员代替 Relay 执行领取、按 Key 发送和标记。用 Consumer 获取事件并执行库存事务，再按安全前沿提交。空 Topic 的首条记录从 Offset 0 开始，确认实际 Kafka Offset，两个相邻记录都完成后预期恢复位置为 2。
2. **故障注入**。每组用新实验数据和新组。Relay 在投递成功、标记 SENT 之前退出，等待租约回收。模拟未知结果时忽略一次成功响应，再重发同一事件。乱序实验只在专用 Topic 手工先发 E2 再发 E1。库存事务可在函数返回后、COMMIT 前显式 ROLLBACK，观察原状。然后另做一次数据库 COMMIT 后、Kafka Commit 前退出，重启验证重复交付。启动第二个 Consumer。将旧实例的任务停在调用库存事务前，使用动态成员并暂停旧实例 Poll 直到超过 `max.poll.interval.ms`，让第二个实例接管。用组分配查询确认目标分区已易主，再释放旧任务，验证幂等及旧世代结果隔离。单分区时，仅加入第二个成员可能不会转移原分区。
3. **恢复验收**。源库查订单版本、两条 Outbox 的事件 ID、尝试次数和最终 SENT 状态。Kafka 查实际 Key、Offset、重复记录与组提交位置。库存库查操作终态、版本与余额。正常与重放实验的预期均为两条 APPLIED、版本 2、余额 5。检查人工隔离记录是否为空或可追踪。只有位点确实跨过的每项事件都具备完成或约定的持久化终态，才通过验收。

集成时可按下面的教学伪代码驱动。确认 Producer 最终成功后才调用带领取令牌的状态更新。验证重放时用相同组重启，关闭自动提交。

```text
Relay:
    领取并提交源库事务
    发送 payload，Kafka Key = UTF-8(order_id)
    等待最终报告
    成功 → 条件更新 SENT
    失败或未知 → 条件更新诊断及退避，或让租约到期

Consumer（串行正常路径）:
    poll，检查消息错误并验证 Schema 和 Key
    BEGIN，调用 deduct_inventory，COMMIT
    APPLIED / REJECTED_STOCK 已确认持久化 → 标记完成
    只提交仍持有分区的安全下一位置
    业务异常或数据库结果未知 → 保留提交缺口，按原身份核对
```

如果已经耗尽 Relay 自动重试预算，可在带原令牌的状态更新中写回 PENDING 并设 `retry_at='infinity'`，使扫描器不再自动领取。人工修复后再恢复具体重试时间。Outbox 的 SENT 只表示发布已确认，库存结果需独立验收。

也可先脱离 Kafka 在库存库演练。用两个 `psql` 会话执行：

```sql
BEGIN ISOLATION LEVEL READ COMMITTED;
SELECT deduct_inventory('evt-1001', 'order-001', 1, 'sku-100', 2);
COMMIT;

SELECT deduct_inventory('evt-copy', 'order-001', 1, 'sku-100', 2);
SELECT deduct_inventory('evt-1002', 'order-001', 2, 'sku-100', 3);
SELECT * FROM inventory;
SELECT * FROM inventory_order_progress;
SELECT * FROM inventory_operation ORDER BY order_id, business_version;
```

并发验证时先让会话 A 调用 E1、暂不提交，会话 B 调用相同 E1。预期 B 等待 A 完成，随后返回已有 APPLIED，库存只从 10 到 8。另一轮让 A 回滚，B 应能完成唯一一次扣减。也可用两个不同订单同时竞争同一 SKU，剩余库存只够一笔时，预期一条 APPLIED、一条 REJECTED_STOCK。每个场景从独立初始化的数据开始。

## 参考

- [PostgreSQL 17 事务隔离与并发 UPDATE](https://www.postgresql.org/docs/17/transaction-iso.html)
- [PostgreSQL 17 INSERT 与冲突处理](https://www.postgresql.org/docs/17/sql-insert.html)
- [PostgreSQL 17 SELECT 与 SKIP LOCKED](https://www.postgresql.org/docs/17/sql-select.html)
- [PostgreSQL 17 PL/pgSQL 语句](https://www.postgresql.org/docs/17/plpgsql-statements.html)

- [Kafka 消息语义与外部存储边界](https://kafka.apache.org/39/design/design/#message-delivery-semantics)
- [Kafka Consumer 与 Producer 事务说明](https://kafka.apache.org/39/configuration/producer-configs/)
