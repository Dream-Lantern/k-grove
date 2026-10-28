---
id: redis-strings
title: 第三章 String、计数与原子过期
description: "String 保存字节序列，可以是文本、序列化对象、整数表示或二进制。Redis 不会因为里面看起来是 JSON，就自动知道其字段结构；修改其中一个属性可能仍需要整体读写。"
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
order: 3
---

# 第三章 String、计数与原子过期

String 保存字节序列，可以是文本、序列化对象、整数表示或二进制。Redis 不会因为里面看起来是 JSON，就自动知道其字段结构；修改其中一个属性可能仍需要整体读写。

## 1. SET 与 GET 的基本语义

新增教学示例，未运行：

```redis
SET demo:profile:42 "{\"name\":\"Lin\"}" EX 120
GET demo:profile:42
SET demo:token:42 temporary-value NX EX 30
```

EX 的单位是秒，PX 的单位是毫秒。NX 要求键不存在时才写入，XX 要求键存在时才写入。需要区分条件未满足时的返回结果和网络错误。

把写入和期限放在同一 SET 中，可以消除“先写入成功，来不及 EXPIRE 就崩溃”的窗口。分开两条命令放进 Pipeline 仍不等于获得同样的原子保证。[SET 的参数与返回](https://redis.io/docs/latest/commands/set/)

## 2. 覆盖写入、保留期限与读取续期 {#_2-覆盖值会怎样影响-ttl}

普通覆盖 SET 通常清除原 TTL；需要保留时应核对目标版本是否支持并使用 KEEPTTL。给一个不存在的键 EXPIRE，不会替你创建值。

GETSET 是历史常见读旧值再替换方式，较新版本可用 `SET ... GET` 表达适用需求。Redis 6.2+ 的 GETEX 把读取与修改期限组合起来，因此它是可能改变状态的命令，不应当成普通 GET 的无副作用替代。[GETEX](https://redis.io/docs/latest/commands/getex/)

滑动过期会让热键长时间存活，是否符合隐私、库存或会话规则需要由业务决定，不能只因为访问频繁就不断延长。

## 3. 计数先用原生命令

```redis
INCR demo:counter
INCRBY demo:counter 5
DECRBY demo:counter 2
```

不存在的计数键从 0 开始参与运算；非整数内容、格式不合法或超出范围可能报错。Redis 的整数计数有范围，不能当作任意精度金额系统。

INCR 的单命令原子性，避免了先 GET、再在本地加一、最后 SET 所造成的典型丢更新问题，但无法解决“客户端不知道第一次是否成功，重试又加一次”的情况。后者仍需要业务事件标识与去重。

浮点命令也不应直接承担对精确十进制有严格要求的金额计算。可以按业务单位编码为整数，但仍需核对溢出、舍入与交易语义。

## 4. 固定时间窗计数的原子边界 {#_4-固定时间窗的计数不是两条命令随手拼}

限流常需要“窗口首次创建时设置期限，后续只增加计数”。若把 INCR 和 EXPIRE 分开，崩溃会留下无期限计数；每次都刷新过期又可能变成另一种窗口规则。

应先明确采用固定窗口、滑动窗口还是令牌桶，再选择单命令、Lua 或其他协调方式。第二十八章会更完整地讨论幂等与限流的边界；本章的 SET NX 例子并不是完整的防刷方案。

## 5. MGET、MSET 与数据规模

MGET、MSET 减少了命令数量，但请求和回复仍有字节成本。MGET 涉及的键很多或值很大，依然可能造成排队与带宽压力。

MGET 有一个值得单独记住的返回例外：不存在的键、以及存在但不是 String 的键，都在对应结果位置返回 nil。GET 读取非 String 键时的 WRONGTYPE，不能原样套到 MGET。

纸面例子：A 是 String，B 是 Hash，C 不存在，MGET A B C 的预期结果位置为 `[A 的字符串值, nil, nil]`；后两个 nil 的原因不同。因此 nil 不足以证明键不存在，也可能提示键模型冲突。此处描述的是数据类型语义，不表示调用永远不报错；ACL、连接和 Cluster 约束仍可导致失败。[MGET 返回定义](https://redis.io/docs/latest/commands/mget/)

Cluster 中还需核对同槽要求。客户端把跨节点多个 GET 聚合成一个 API，不意味着服务端执行了一个跨槽原子 MGET。

String 的尺寸上限与实际可接受尺寸也不同。不要按理论最大值规划常规对象；大值会影响复制、持久化、网络和删除。尺寸限制、协议配置和产品实现需要与版本对应。

## 6. 编码只作为诊断线索

String 紧凑编码的阈值属于版本实现细节。以 Redis 7.2.0 为参照，createStringObject 的 embstr 创建阈值为 44 字节，长度小于等于该值走适用的紧凑创建路径；整数编码、更新和其他创建路径还需分别考虑。它不是业务协议，也不保证所有长度相同的值最终编码都一样。[Redis 7.2.0 对象实现](https://raw.githubusercontent.com/redis/redis/7.2.0/src/object.c)

先观察实际对象与读写模式，再决定是否压缩或拆分；压缩节省的内存还要付出 CPU、编解码和调试成本。

[返回本册目录](/collections/redis/)
