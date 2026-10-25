---
id: redis-hiredis
title: 第十五章 客户端连接、超时与 hiredis 基础
description: 返回本册目录
date: '2026-10-25'
updated: '2026-10-25'
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
order: 15
---

# 第十五章 客户端连接、超时与 hiredis 基础

[返回本册目录](/collections/redis/)

命令在命令行里执行成功，并不代表应用接入已经可靠。应用还要管理连接、请求截止时间、回复解析和失败重试。本章承接原笔记的 C 客户端内容；代码是新增教学片段，未编译或连接服务器验证。

## 1. 一次调用经过哪些等待

![一次请求的时间预算](/assets/notes/redis/redis-study-client-budget.svg)

连接池先决定有没有可用连接，随后才可能发生 DNS、TCP、TLS、认证和命令读写。服务端收到完整请求后也可能排队。Slowlog 只覆盖其中的执行部分，不是完整的调用耗时。

连接超时限制建立连接阶段；命令读写超时限制后续通信；连接池超时限制等待借用连接。Redis 服务端的 `timeout` 又是另一种空闲连接管理参数。把这些参数都设成相同数值，并不能自动得到合理的总超时。

例如业务只允许等待 200 ms，就不能先等连接池 200 ms，再连接 200 ms，最后重试三次。应从业务截止时间反推每段预算，传播剩余时间，并限制重试次数和并发。

## 2. 同步 hiredis 的最小检查路径

下面只演示本机教学地址上的 PING，不包括生产所需的 TLS、ACL、连接池和重连策略。编译时应按实际 hiredis 版本与平台处理头文件和链接参数。

```c
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <hiredis/hiredis.h>

int ping_example(void) {
    long timeout_ms = 500;
    struct timeval tv = {
        .tv_sec = timeout_ms / 1000,
        .tv_usec = (timeout_ms % 1000) * 1000
    };
    redisContext *c = redisConnectWithTimeout("127.0.0.1", 6379, tv);
    if (c == NULL) return 1;
    if (c->err) { redisFree(c); return 1; }
    if (redisSetTimeout(c, tv) != REDIS_OK) {
        redisFree(c); return 1;
    }
    redisReply *r = redisCommand(c, "PING");
    if (r == NULL) { redisFree(c); return 1; }
    int ok = r->type == REDIS_REPLY_STATUS && r->str != NULL
             && r->len == 4 && memcmp(r->str, "PONG", 4) == 0;
    if (ok) printf("%.*s\n", (int)r->len, r->str);
    freeReplyObject(r);
    redisFree(c);
    return ok ? 0 : 1;
}
```

原文中毫秒到 `timeval` 的换算有误：`tv_usec` 的单位是微秒，毫秒余数应乘以 1000。连接超时也不会自动成为所有命令的超时，因此上例另外调用了 `redisSetTimeout`。

`redisCommand` 返回 NULL，通常说明通信或上下文失败；返回一个 `REDIS_REPLY_ERROR` 对象则是已经收到了 Redis 的错误回复。两者不能都归类成“键不存在”。完整业务代码还应核对回复类型、长度、数组元素和错误内容。

以 hiredis v1.2.0 为参照，失败后还应区分连接能否复用：

| 观察结果                                 | 处置思路                                                           |
| ---------------------------------------- | ------------------------------------------------------------------ |
| 收到完整 REDIS_REPLY_ERROR               | 本次命令被服务端拒绝，连接未必损坏；继续按协议处理适用的后续回复   |
| 通信失败、读写超时，存在未确认请求或回复 | 将结果标记未知；不要当成干净连接归还池，也不要继续假定请求回复同步 |
| 已重新建立连接                           | 恢复认证、适用 DB 选择和其他连接状态；并不证明旧写入未执行         |

上下文出错后，应按库约定关闭/重建，不能把“多读一下也许能对齐”当作通用恢复方法。PubSub 还需要恢复订阅，断线期间的普通通知不会自动补发；Cluster 的路由则由相应客户端管理。[hiredis v1.2.0 错误处理](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

## 3. 字节、格式串与内存归属

String 可以包含零字节。二进制值不能简单用 C 的字符串结束符判断长度，应使用 `%b` 或 `redisCommandArgv` 的显式长度。不要把外部输入直接当成格式串。

同步命令返回的回复对象由调用方按约定释放，上例用 `freeReplyObject`。上下文由 `redisFree` 释放；不要在异步回调里照搬同步回复的释放方式，下一章会区分。

hiredis 上下文不能作为共享连接，供多个线程随意并发使用。即使连接池是线程安全的，也不意味着借出的单连接可以同时被多个请求交错读写。应明确连接的所有权，避免 A 请求读到 B 的回复。[hiredis 官方说明](https://github.com/redis/hiredis)

## 4. 超时之后，结果可能未知

假设 `INCR demo:orders` 已在服务端执行，回复却在返回途中丢失。客户端看到超时，再次执行 INCR 就会多加一次。因此“没收到成功”不能推出“没有执行”。

读请求通常更容易重试；写请求需要结合请求唯一标识、条件更新、业务去重和恢复查询判断。即使使用 SET，同一值重试也可能重新计算 TTL，或者覆盖另一位写入者的新值，不能只按命令名称宣布幂等。

排查连接问题时，至少保留错误阶段、耗时、重试次数和业务请求标识；日志中不要记录口令或完整敏感值。连接持续报错时，应先弄清网络、认证、路由和服务器状态，而不是无上限创建新连接。
