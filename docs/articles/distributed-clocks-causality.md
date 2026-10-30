---
id: distributed-clocks-causality
title: 第三章 时间、逻辑时钟与因果关系
description: "分析跨节点事件，需要分别观察物理时间、程序顺序和消息传递关系。各机器的时钟可能存在偏差、校正或暂停，日志时间适合提供观察线索；判断事件是否相互影响，还需要建立因果路径。"
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
order: 3
---

# 第三章 时间、逻辑时钟与因果关系

> 阅读标签：通用协议/应用模型，具体前提见本章。

分析跨节点事件，需要分别观察物理时间、程序顺序和消息传递关系。各机器的时钟可能存在偏差、校正或暂停，日志时间适合提供观察线索；判断事件是否相互影响，还需要建立因果路径。本章由此介绍逻辑时钟，以及版本、任期和日志位置的比较范围。

## 1. 物理时间与本地耗时的用途 {#_1-物理时间与本地耗时不是同一用途}

墙上时钟（Wall Clock）表示日期和时间，适合展示日历时间、记录时间戳。单调时钟（Monotonic Clock）提供不倒退的本地读数，适合用两个读数之差测量耗时；它不是多个机器共享的全局时钟，起点、重启和挂起语义要看平台。

时钟偏差（Clock Skew）在本文指同一真实时刻两台机器读数的差，例如 A 比 B 快两秒；时钟漂移（Clock Drift）指时钟走时速率相对于参考时间的偏离，会使偏差随时间积累。前者是读数差，后者是速率差；速率本身还可能随温度等条件变化。术语和时钟误差模型可参照 [RFC 5905 §6](https://datatracker.ietf.org/doc/html/rfc5905#section-6)。

以下为 **Linux 平台行为**，依据 [Linux man-pages 6.9.1 的 clock_gettime(2)](https://manpages.debian.org/trixie/manpages-dev/clock_gettime.2.en.html)，不是所有操作系统的统一保证：

| 时钟                | 用途            | 特点                                |
| ----------------- | ------------- | --------------------------------- |
| `CLOCK_REALTIME`  | 日历时间和时间戳      | 系统时间调整可能使读数跳变                     |
| `CLOCK_MONOTONIC` | 测量持续时间        | 不受系统时间突然跳变影响，仍受频率调整影响，不计入系统挂起时间   |
| `CLOCK_BOOTTIME`  | 需要计入挂起时间的持续时间 | Linux 特有接口，类似 MONOTONIC，但计入系统挂起时间 |

单调不等于每次读取都严格增大：受分辨率影响，相邻读数可以相等。Linux 的 `CLOCK_MONOTONIC` 也不是未经校准的硬件原始计数。

网络时间协议（Network Time Protocol，NTP）通过网络交换时间信息来同步时钟，但链路延迟及其不对称、时钟自身误差等仍会影响同步结果，不能据此推导各节点时间绝对一致。RFC 5905 是 NTPv4 的基础规范，存在后续更新；更新列表见 [IETF 文档状态页](https://datatracker.ietf.org/doc/rfc5905/)，定位见[附录 A](/articles/distributed-version-references.html#_2026-10-30时间资料核查)。

租约如果依赖时间边界，就需要明确谁计时、误差如何控制、检查资格与真正写入之间还能延迟多久。不能仅因部署了 NTP，就推导任意时间租约绝对安全。

## 2. 先发生关系是偏序

先发生关系（Happens-Before，记作 `→`）描述事件间的因果先后，由三个规则建立：

1. 同一进程内，程序执行顺序建立先后关系。
2. 一条消息的发送事件先于该消息的接收事件。
3. 关系具有传递性：`a → b` 且 `b → c`，则 `a → c`。

这些规则构成偏序（Partial Order）：有些事件可以比较先后，有些不能。在所建模的事件与消息完整记录下，若 `a ↛ b` 且 `b ↛ a`，称二者并发。若仅缺少日志，没找到路径还不足以断言没有因果关系。**并发不要求两个事件在物理时间上完全同时发生。** 定义依据见 [Lamport 1978 §“The Partial Ordering”](https://lamport.azurewebsites.net/pubs/time-clocks.pdf)。

教学例子：A 创建订单并发送消息给 B，B 收到后预留库存。创建在因果上先于预留。另一个完全独立的用户查询 C，可能与两者并发；把三条日志按字符串时间排序，不会自动得到业务因果图。

## 3. Lamport 时钟的更新与顺序性质 {#_3-lamport-时钟能证明什么}

Lamport 时钟为每个进程维护一个逻辑计数 `L`，初值为零。下面三个片段是**三种事件各自的教学伪代码**，不是依次执行的步骤：

```python
# 普通本地事件
L = L + 1

# 发送消息：发送本身就是一个事件
L = L + 1
message.timestamp = L

# 接收消息
L = max(L, message.timestamp) + 1
```

发送事件只递增一次，不需要先按“普通本地事件”递增后再为发送递增。接收时取较大值再加一，使接收的逻辑时间大于发送时间。

若 `a → b`，则 `L(a) < L(b)`；反过来不成立：逻辑时间较小，并不能证明存在因果依赖。附加唯一节点 ID 后，按 `(L, node_id)` 的字典序可以构造确定的全序，但它只是协议采用的排序规则，不表示真实物理时间顺序。依据见 [Lamport 1978 的时钟条件与全序构造](https://lamport.azurewebsites.net/pubs/time-clocks.pdf)。

### 三个节点的教学推演

假设 A、B、C 的初始计数均为 0，且 C 与 A、B 没有交换消息：

| 事件  | 节点与动作        | 时钟更新            | 事件时间  |
| --- | ------------ | --------------- | ----- |
| a1  | A 创建订单       | `0 + 1`         | `L=1` |
| a2  | A 向 B 发送订单消息 | `1 + 1`，消息携带 2  | `L=2` |
| b1  | B 接收消息       | `max(0, 2) + 1` | `L=3` |
| b2  | B 预留库存       | `3 + 1`         | `L=4` |
| c1  | C 独立处理用户查询   | `0 + 1`         | `L=1` |

表的行序用于讲解，不表示 C 一定在 B 之后执行。因果链是 `a1 → a2 → b1 → b2`；c1 与这条链上的事件并发。即使 `L(c1)=1 < L(b1)=3`，也不能推出 `c1 → b1`。

![A、B、C 的事件、消息因果箭头与 Lamport 时钟值](/assets/notes/distributed-systems/dist-clocks.svg)

[打开事件时间线原图](/assets/notes/distributed-systems/dist-clocks.svg)。横向位置只用于排版及展示已知顺序，不是可比较的物理时间刻度。

## 4. 版本、任期与日志位置各有范围

Raft 的 term 用来区分选举时代，index 用来定位日志；ZooKeeper 的 znode version 用于某对象条件更新，zxid 用于事务顺序。它们不是可任意互换的时间戳。

| 标识                      | 代表什么、解决什么问题           | 可以比较的范围                               | 不能直接比较的情况                                    |
| ----------------------- | --------------------- | ------------------------------------- | -------------------------------------------- |
| Raft Term（任期）           | 选举时代，帮助识别过期领导者与消息     | 同一 Raft 集群的任期大小                       | 独立集群；较大任期也不等于某条日志已提交                         |
| Raft Index（日志索引）        | 日志条目的位置，用于复制与应用定位     | 同一集群日志的位置                             | 不同集群；未提交的冲突日志在相同 index 可能有不同值，需结合 term 等协议规则 |
| ZooKeeper Version（数据版本） | 某 znode 数据修改计数，用于条件更新 | 同一 znode 生命周期内的数据版本；children、ACL 另有计数 | 不同路径、删除后重建的同名对象；version 不是全局时钟               |
| ZooKeeper ZXID（事务 ID）   | 标识状态变更的全局事务顺序         | 同一 ZooKeeper ensemble 的事务历史           | 独立 ensemble；读请求不会因此获得新的写事务 ID，也不能用它排序任意外部事件  |

Raft 依据为 [2014 扩展论文 §5、图 2](https://raft.github.io/raft.pdf)；ZooKeeper 依据为 [3.9.3 Programmer's Guide 的 Time、Stat 与条件更新说明](https://zookeeper.apache.org/doc/r3.9.3/zookeeperProgrammers.html)。比较日志新旧还要遵循 Raft 的规则，不能用单一数字代替协议判断。

例如两个不同分片都产生版本 12，不能仅凭这个数判断谁更新得更晚；两个独立 ZooKeeper 路径的顺序后缀，也不是天然全局唯一的业务 ID。必须先声明版本的生成范围和比较规则。

## 5. 并发版本不一定有唯一“最新”

多个副本允许独立写入时，可能产生并发版本。向量版本等技术可以表达部分因果关系；也可能由业务进行合并。若简单按墙钟“最后写入获胜”，就选择了一种冲突策略，并不是证明没有冲突。[Dynamo 原论文的版本机制](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)

向量时钟（Vector Clock）为各参与节点保留一个计数分量。教学二维示例中，分量顺序固定为 `(A, B)`：`V_A = (2, 1)`，`V_B = (1, 2)`。比较规则是逐分量“小于等于”，并至少一个分量严格小于，才称一个向量先于另一个。这里第一分量 A 大，第二分量 B 大，两边都不满足规则，因此版本并发，不能按字典序认定谁更新。该结论以完整维护向量信息为前提；截断历史等优化会限制因果判定能力，见 [Dynamo 2007 §4.4](https://www.allthingsdistributed.com/files/amazon-dynamo-sosp2007.pdf)。

纸面推演：两个地区同时修改购物车，一方加入书、一方加入笔。直接覆盖可能丢失其中一次意图；按集合合并又需要考虑删除语义。数据结构与业务规则决定如何解决，不能只靠“时间戳较大”。

## 6. 把日志还原为事件关系 {#_6-读日志时的一组检查问题}

还原日志时，先记录时间来自哪台机器及其比较范围，再标出事件所处的阶段：调用开始、持久化完成或响应发送。版本号也应注明所属对象或配置。这样可以把日志展示顺序、协议顺序和提交顺序分别分析。

### 可运行的 Lamport 教学模拟

保存为 `lamport_demo.py`，运行 `python lamport_demo.py`，不依赖第三方库。为核对已建模的因果关系，代码同时保存因果边；Lamport 数字本身不能识别所有并发事件。

```python
class Clock:
    def __init__(self):
        self.value = 0

    def local(self):
        self.value += 1
        return self.value

    def send(self):
        return self.local()  # 发送只递增一次

    def receive(self, timestamp):
        self.value = max(self.value, timestamp) + 1
        return self.value


a, b, c = Clock(), Clock(), Clock()
events = {"a1": a.local(), "a2": a.send()}
events["b1"] = b.receive(events["a2"])
events["b2"] = b.local()
events["c1"] = c.local()
edges = {"a1": ["a2"], "a2": ["b1"], "b1": ["b2"]}


def before(source, target):
    pending, seen = list(edges.get(source, [])), set()
    while pending:
        event = pending.pop()
        if event == target:
            return True
        if event not in seen:
            seen.add(event)
            pending.extend(edges.get(event, []))
    return False


print("clocks:", events)
print("a1 -> b2:", before("a1", "b2"))
print("c1 concurrent b1:", not before("c1", "b1") and not before("b1", "c1"))
print("L(c1) < L(b1):", events["c1"] < events["b1"])
assert list(events.values()) == [1, 2, 3, 4, 1]
assert all(events[x] < events[y] for x in edges for y in edges[x])
```

已于 2026-10-30 在 Windows、Python 3.8.10 下执行上述命令，退出码为 0，输出与以下预期一致：

```text
clocks: {'a1': 1, 'a2': 2, 'b1': 3, 'b2': 4, 'c1': 1}
a1 -> b2: True
c1 concurrent b1: True
L(c1) < L(b1): True
```

这里的并发来自完整的教学事件图，程序按某个顺序调用这些方法，只是在单进程中模拟独立节点；没有执行网络同步或物理时钟实验。

## 联读

全局ID的唯一、排序与时钟回退要求见[工程速查的ID小节](/articles/distributed-cqrs-cache-ids.html)，UUID时间字段不代替因果关系。

[返回本册目录](/collections/distributed-systems/)
