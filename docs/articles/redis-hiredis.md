---
id: redis-hiredis
title: 第十五章 客户端连接、超时与 hiredis 基础
description: "应用通过客户端库完成连接、请求发送和回复解析，还要管理截止时间、错误与重试。一次完整调用从等待连接开始，到取得可解释的结果结束。"
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
order: 15
---

# 第十五章 客户端连接、超时与 hiredis 基础

[返回本册目录](/collections/redis/)

应用通过客户端库完成连接、请求发送和回复解析，还要管理截止时间、错误与重试。一次完整调用从等待连接开始，到取得可解释的结果结束。本章用 hiredis 的同步接口说明这条路径；代码为教学片段，尚无编译或连接服务器验证记录。

hiredis 是轻量级 C 客户端库，负责建立连接，将命令格式化并编码为 RESP（Redis Serialization Protocol，Redis 序列化协议），发送请求、接收及解析回复，再转换成 C 数据结构。`redisContext` 是管理一条连接及其通信状态的上下文对象；`redisReply` 是同步调用交给应用处理的回复对象。本章固定以 **hiredis v1.2.0** 为依据，不把其他版本接口混入示例。[v1.2.0 官方说明](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

```text
C 应用 → hiredis 格式化命令 → RESP 编码 → 连接读写 → Redis 服务端
C 应用 ← redisReply        ← RESP 解析 ← 接收回复 ← Redis 服务端
```

## 1. 连接池、建连与命令读写的时间预算 {#_1-一次调用经过哪些等待}

[![Redis 客户端超时：端到端预算模型](/assets/notes/redis/redis-study-client-budget.svg)](/assets/notes/redis/redis-study-client-budget.svg)

连接池先决定有没有可用连接，随后才可能发生 DNS（Domain Name System，域名系统）解析、TCP（Transmission Control Protocol，传输控制协议）建连、TLS（Transport Layer Security，传输层安全）握手、认证和命令读写。复用已建立的连接通常跳过建连阶段。服务端收到完整请求后也可能排队。SLOWLOG（慢查询日志）只覆盖命令执行部分，不是完整调用耗时，参见 [第 29 章慢查询与延迟](/articles/redis-slow-queries.html)。

连接超时限制建立连接阶段；命令读写超时限制后续通信；连接池超时限制等待借用连接。Redis 服务端的 `timeout` 又是另一种空闲连接管理参数。把这些参数都设成相同数值，并不能自动得到合理的总超时。

| 阶段或参数                        | 控制内容                       | 不代表什么                               |
| --------------------------------- | ------------------------------ | ---------------------------------------- |
| Pool Timeout（连接池等待超时）    | 等待借到可用连接，由连接池实现 | Redis 建连时间；hiredis 本身不提供连接池 |
| Connect Timeout（连接超时）       | 建立连接过程中的适用等待       | 完整业务调用总耗时                       |
| Command Timeout（命令超时）       | 命令通信中的适用读写等待       | 服务端执行取消或业务截止时间             |
| Redis timeout                     | 服务端对适用空闲客户端的管理   | 单条命令执行超时                         |
| Business Deadline（业务截止时间） | 整个调用允许持续到的时刻       | 某一个 Socket（套接字）超时设置          |

在 hiredis v1.2.0 中，`redisConnectWithTimeout` 为连接阶段提供超时；同步上下文的 `redisSetTimeout` 设置底层套接字读写超时。`redisOptions` 分别有 `connect_timeout` 和 `command_timeout`，可通过 `redisConnectWithOptions` 使用。它们不是整段业务的统一秒表，分次读写也不能直接等同于一次完整命令的总时限。[v1.2.0 接口定义](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/hiredis.h) · [同步超时设置](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/net.c)

v1.2.0 的 TCP 连接实现会调用系统 `getaddrinfo` 解析域名，不能认为传入的 connect timeout 一定限制 DNS 调用总耗时。连接池等待由应用或其他库管理，TLS 握手和认证又有自己的调用路径，应分别核对配置和计时范围。[v1.2.0 连接实现](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/net.c) · [TLS 接入方式](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

例如业务只允许等待 200 ms，就不能先等连接池 200 ms，再连接 200 ms，最后重试三次。应从业务截止时间反推每段预算，传播剩余时间，并限制重试次数和并发。

如果借连接已经用去 40 ms，后续所有阶段和重试就只剩约 160 ms，而不是每段重新获得 200 ms。总截止时间需要应用协调；某一段超时返回，也不证明服务端写入被取消。

## 2. 同步 hiredis 的最小检查路径

下面只演示本机教学地址上的 PING，不包括生产所需的 TLS、ACL（Access Control List，访问控制列表）、连接池和重连策略。每个阶段的 500 ms 是独立教学设置，未实现上节的 200 ms 总截止时间。可将代码保存为 `demo.c`，示例未经编译或运行验证。

| 项目         | 教学复现基线                                       |
| ------------ | -------------------------------------------------- |
| Redis Server | 本机或隔离测试环境，可采用 Redis Open Source 7.2.0 |
| hiredis      | v1.2.0，开发头文件及库版本一致                     |
| 编译器与标准 | GCC 或 Clang，C11                                  |
| 依赖         | hiredis 开发库、pkg-config                         |
| 地址与命令   | 127.0.0.1:6379，PING                               |
| 预期输出     | PONG；这是预期，不是实测结果                       |

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
    if (c == NULL) {
        fputs("Could not allocate Redis context\n", stderr);
        return 1;
    }
    if (c->err) {
        fprintf(stderr, "Redis connection error: %s\n", c->errstr);
        redisFree(c);
        return 1;
    }
    if (redisSetTimeout(c, tv) != REDIS_OK) {
        fprintf(stderr, "Redis timeout setup error: %s\n", c->errstr);
        redisFree(c);
        return 1;
    }
    redisReply *r = redisCommand(c, "PING");
    if (r == NULL) {
        fprintf(stderr, "Redis communication/context error: %s\n", c->errstr);
        redisFree(c); /* Discard the failed context; do not return it to a pool. */
        return 1;
    }
    int ok = r->type == REDIS_REPLY_STATUS && r->str != NULL
             && r->len == 4 && memcmp(r->str, "PONG", 4) == 0;
    if (r->type == REDIS_REPLY_ERROR) {
        fputs("Redis command error: ", stderr);
        if (r->str != NULL) fwrite(r->str, 1, r->len, stderr);
        fputc('\n', stderr);
    } else if (ok) {
        fwrite(r->str, 1, r->len, stdout);
        putchar('\n');
    } else {
        fputs("Unexpected PING reply\n", stderr);
    }
    freeReplyObject(r);
    redisFree(c);
    return ok ? 0 : 1;
}

int main(void) {
    return ping_example();
}
```

在预先安装对应开发包且 pkg-config 能找到 v1.2.0 的 Linux 或 macOS 开发环境中，可参考以下 Shell 编译命令。它是复现说明，未经实测，也不是 Windows PowerShell 命令：

```bash
cc -std=c11 -Wall -Wextra \
  demo.c \
  $(pkg-config --cflags --libs hiredis) \
  -o hiredis-demo
```

`timeval` 中 `tv_usec` 的单位是微秒，毫秒余数需要乘以 1000。连接阶段与命令读写使用各自的超时设置，因此上例另行调用 `redisSetTimeout`。

`redisCommand` 返回 NULL，通常说明通信或上下文失败；返回一个 `REDIS_REPLY_ERROR` 对象则是已经收到了 Redis 的错误回复。两者不能都归类成“键不存在”。完整业务代码还应核对回复类型、长度、数组元素和错误内容。

| 情况                   | 返回结果                           | 应如何理解                                     |
| ---------------------- | ---------------------------------- | ---------------------------------------------- |
| 收到正常回复           | 非 NULL 的 redisReply              | 仍要核对类型和具体内容，例如 PING 的 PONG      |
| Redis 命令错误         | 非 NULL，type 为 REDIS_REPLY_ERROR | 已收到错误回复，不代表连接已断开               |
| 通信、协议或上下文异常 | NULL                               | 没有可使用的回复对象，先检查 c->err、c->errstr |
| 读写超时               | NULL，错误上下文                   | 请求可能已经执行，结果可能未知                 |

NULL 时不能访问 `r->type` 或 `r->str`；所有非 NULL 的同步回复，包括错误回复，都要释放。上例函数独占创建的上下文，所有返回路径都会释放已有上下文；收到回复时先释放回复，再释放上下文。

以 hiredis v1.2.0 为参照，失败后还应区分连接能否复用：

| 观察结果                                 | 处置思路                                                           |
| ---------------------------------------- | ------------------------------------------------------------------ |
| 收到完整 REDIS_REPLY_ERROR               | 收到服务端错误，连接未必损坏；仍需按具体命令判断错误前是否有副作用 |
| 通信失败、读写超时，存在未确认请求或回复 | 将结果标记未知；不要当成干净连接归还池，也不要继续假定请求回复同步 |
| 已重新建立连接                           | 恢复认证、适用 DB 选择和其他连接状态；并不证明旧写入未执行         |

上下文出错后，应按库约定关闭/重建，不能把“多读一下也许能对齐”当作通用恢复方法。PubSub 还需要恢复订阅，断线期间的普通通知不会自动补发；Cluster 的路由则由相应客户端管理。[hiredis v1.2.0 错误处理](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

## 3. 字节、格式串与内存归属

String 可以包含零字节。二进制值不能简单用 C 的字符串结束符判断长度，应使用 `%b` 或 `redisCommandArgv` 的显式长度。不要把外部输入直接当成格式串。

`%s` 按 `strlen` 确定长度，遇到零字节会停止；`%b` 要求指针和 `size_t` 长度，数据中有零字节也能完整传递。下面是另一个未编译的函数片段：调用者独占并持有健康上下文 `c`，函数只释放自己取得的回复；若出现通信错误，调用者应丢弃该上下文。它不是上面 PING 程序的一部分。

```c
int set_binary_example(redisContext *c) {
    if (c == NULL || c->err) return 1;
    const char *value = "hello";
    size_t value_len = 5;
    redisReply *reply = redisCommand(c, "SET demo:binary %b", value, value_len);
    if (reply == NULL) {
        fprintf(stderr, "Redis communication/context error: %s\n", c->errstr);
        return 1;
    }
    int ok = reply->type == REDIS_REPLY_STATUS && reply->str != NULL
             && reply->len == 2 && memcmp(reply->str, "OK", 2) == 0;
    freeReplyObject(reply);
    return ok ? 0 : 1;
}
```

预期健康实例接受 SET 后得到状态 OK。`redisCommandArgv` 则以参数数组及长度数组传递命令，适合已有独立参数或二进制键值的场景；不要先拼成未经控制的格式串。`%b` 和参数长度的约定见 [v1.2.0 命令格式化说明](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)。

同步命令返回的回复对象由调用方按约定释放，上例用 `freeReplyObject`。上下文由 `redisFree` 释放；不要在异步回调里照搬同步回复的释放方式，下一章会区分。

hiredis v1.2.0 的同步 redisContext 不是线程安全对象。即使连接池是线程安全的，也不意味着借出的单连接可以同时被多个请求交错读写。应明确连接的所有权，避免 A 请求读到 B 的回复。[v1.2.0 线程安全说明](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

```text
线程 A → 借用连接 A → 独占 redisContext A → 发送命令并消费回复
       → 确认状态健康、没有未读回复 → 归还连接 A
```

通信错误、未消费的回复、事务或订阅等连接状态不能留给下一个借用者。Pipeline（流水线，批量发送命令后再按顺序读取回复）尤其要保持请求与回复对齐，见 [第 17 章 Pipeline](/articles/redis-pipeline.html)。

| 场景                       | 同步 API（Application Programming Interface，应用程序编程接口）的适用性 |
| -------------------------- | ----------------------------------------------------------------------- |
| 简单命令、低并发脚本       | 合适，调用顺序清楚                                                      |
| 有界连接池                 | 合适，需控制等待、容量和连接独占                                        |
| 长时间阻塞的调用或业务回调 | 谨慎，可能占住调用线程及连接                                            |
| 高并发事件驱动服务         | 可考虑异步接口，但需承担事件循环和回调管理                              |

异步不保证吞吐一定更高，仍受服务端、网络和回调工作量限制。[第 16 章 hiredis 异步接口](/articles/redis-hiredis-async.html)会继续讨论这部分。

## 4. 超时之后，结果可能未知

假设 `INCR demo:orders` 已在服务端执行，回复却在返回途中丢失。客户端看到超时，再次执行 INCR 就会多加一次。因此“没收到成功”不能推出“没有执行”。

读请求通常更容易重试；写请求需要结合请求唯一标识、条件更新、业务去重和恢复查询判断。即使使用 SET，同一值重试也可能重新计算 TTL，或者覆盖另一位写入者的新值，不能只按命令名称宣布幂等。

排查连接问题时，至少保留错误阶段、耗时、重试次数和业务请求标识；日志中不要记录口令或完整敏感值。连接持续报错时，应先弄清网络、认证、路由和服务器状态，而不是无上限创建新连接。

生产连接还需明确 TLS 证书校验、ACL 用户及最小权限、连接池容量、TCP Keepalive（连接保活）、断线恢复、命令超时和业务 Deadline。Keepalive 检测失联不替代业务截止时间。hiredis v1.2.0 的 TLS 支持需单独构建和链接相关库，不能把普通 localhost 教学连接当作已经启用加密认证的生产方案。[v1.2.0 TLS 与保活说明](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md) · [第 31 章安全与维护](/articles/redis-security-maintenance.html)
