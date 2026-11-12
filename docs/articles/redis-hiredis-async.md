---
id: redis-hiredis-async
title: 第十六章 hiredis 异步接口与事件循环
description: "hiredis 异步接口通过事件循环推进网络连接与命令读写，让应用在等待期间处理其他事件。理解调用过程时，可以依次跟踪连接开始、命令排队、回调取得结果和对象收尾；事件循环的并发机会与服务端处理能力分别评价。"
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
order: 16
---

# 第十六章 hiredis 异步接口与事件循环

[返回本册目录](/collections/redis/)

hiredis 异步接口通过事件循环推进网络连接与命令读写，让应用在等待期间处理其他事件。理解调用过程时，可以依次跟踪连接开始、命令排队、回调取得结果和对象收尾；事件循环的并发机会与服务端处理能力分别评价。

本章固定采用 **hiredis v1.2.0**。Event Loop（事件循环）等待网络可读、可写等事件，再调用相应处理函数；Callback（回调）是事件就绪后被调用的应用函数。异步把网络就绪等待交给事件循环，不代表为每个请求创建线程。同步连接基础见 [第 15 章](/articles/redis-hiredis.html)。[v1.2.0 官方说明](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

[![hiredis 异步回复：对象所有权](/assets/notes/redis/redis-study-async.svg)](/assets/notes/redis/redis-study-async.svg)

## 1. 从创建连接到命令回调 {#_1-四个时刻不要混在一起}

调用 `redisAsyncConnect` 并取得上下文，只是连接过程的起点，并不等于连接成功。应先检查立即可见的错误，再通过连接回调获取后续结果。

`redisAsyncCommand` 返回成功，表示命令被客户端接受并排队，而不是 Redis 已经执行。网络事件由 libevent、libev 等适配器绑定的事件循环推进；应用最终在命令回调里检查回复或连接失败。

下面是结构示意，不是可以直接编译的完整程序：

```text
创建 async context → 检查立即错误
绑定一种受支持的事件循环适配器
分别设置连接回调与断开回调
连接完成后按业务状态提交命令
事件循环驱动读写 → 命令回调检查 reply
退出时停止新请求 → 收尾现有请求 → 释放连接和事件资源
```

连接与断开通知分别注册：使用该版本提供的 `redisAsyncSetConnectCallback` 获取连接结果，使用 `redisAsyncSetDisconnectCallback` 处理断开后的收尾。

完整的逻辑时序可按下面的示意理解。TCP（Transmission Control Protocol，传输控制协议）连接可能从创建调用中就已开始尝试；绑定适配器后，后续完成通知和读写由事件循环推进：

```text
应用                         hiredis / 事件循环                   Redis
redisAsyncConnect   ------> 创建上下文，发起非阻塞连接 --------> 建连
取得上下文          <------ 返回，不等待连接最终成功
绑定适配器、注册回调 ------> 监听网络事件
连接回调            <------ 确认连接成功或失败 <--------------- 建连结果
redisAsyncCommand   ------> 命令排队
REDIS_OK            <------ 本地提交成功
                            可写时发送命令 -------------------> 执行
命令回调            <------ 读入并解析回复 <------------------- 回复
                            回调返回后释放默认 reply
请求断开            ------> 收尾连接，解绑事件并释放上下文
```

| 时刻                                   | 已确认                                     | 尚未确认               |
| -------------------------------------- | ------------------------------------------ | ---------------------- |
| redisAsyncConnect 返回非空且无立即错误 | 已获得 redisAsyncContext（异步连接上下文） | 网络最终是否连接成功   |
| 连接回调成功                           | 网络连接建立                               | 认证和业务命令是否成功 |
| redisAsyncCommand 返回 REDIS_OK        | 命令被本地客户端接受                       | 服务端是否收到、执行   |
| 命令回调得到正常回复                   | 已收到可解析结果，仍需核对类型和值         | 外部业务是否完成       |

本地提交成功、网络连接成功、Redis 命令成功是三个不同状态。[v1.2.0 异步实现](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/async.c)

下面是一份完整的教学程序文本，可另存为 `async-demo.c`，示例未经编译或运行验证。前提是 Linux 等开发环境安装匹配的 hiredis v1.2.0、libevent 2.x 开发库及 pkg-config，测试实例位于 127.0.0.1:6379。它只演示默认所有权模式下的 PING，不包括认证和重连：

```c
#include <stdio.h>
#include <string.h>
#include <sys/time.h>
#include <event2/event.h>
#include <hiredis/async.h>
#include <hiredis/adapters/libevent.h>

typedef struct {
    struct event_base *base;
    redisAsyncContext *ac;
    int ok;
} App;

static void on_ping(redisAsyncContext *ac, void *reply, void *privdata) {
    App *app = privdata;
    redisReply *r = reply;
    if (r == NULL) { /* Failure/free path will finish the connection cleanup. */
        app->ok = 0;
        return;
    }
    app->ok = r->type == REDIS_REPLY_STATUS && r->str != NULL
              && r->len == 4 && memcmp(r->str, "PONG", 4) == 0;
    if (app->ok) puts("PONG");
    else fputs("PING returned an error or unexpected reply\n", stderr);
    redisAsyncDisconnect(ac); /* Do not free r or ac here. */
}

static void on_disconnect(const redisAsyncContext *ac, int status) {
    App *app = ac->data;
    if (status != REDIS_OK) app->ok = 0;
    app->ac = NULL; /* Default mode: the library owns final context release. */
    event_base_loopbreak(app->base);
}

static void on_connect(const redisAsyncContext *ac, int status) {
    App *app = ac->data;
    if (status != REDIS_OK) {
        fprintf(stderr, "Connect failed: %s\n", ac->errstr);
        app->ac = NULL; /* The library frees it after this failure callback. */
        event_base_loopbreak(app->base);
        return;
    }
    if (redisAsyncCommand(app->ac, on_ping, app, "PING") != REDIS_OK) {
        fputs("Could not enqueue PING\n", stderr);
        redisAsyncDisconnect(app->ac);
    }
}

int main(void) {
    App app = {0};
    app.base = event_base_new();
    if (app.base == NULL) return 1;
    app.ac = redisAsyncConnect("127.0.0.1", 6379);
    if (app.ac == NULL) goto cleanup;
    app.ac->data = &app;
    if (app.ac->err) {
        fprintf(stderr, "Immediate error: %s\n", app.ac->errstr);
        goto cleanup;
    }
    if (redisLibeventAttach(app.ac, app.base) != REDIS_OK ||
        redisAsyncSetDisconnectCallback(app.ac, on_disconnect) != REDIS_OK ||
        redisAsyncSetConnectCallback(app.ac, on_connect) != REDIS_OK)
        goto cleanup;

    struct timeval stop_after = {3, 0}; /* Application-level exit guard. */
    if (event_base_loopexit(app.base, &stop_after) != 0) goto cleanup;
    if (event_base_dispatch(app.base) < 0) app.ok = 0;
    if (app.ac != NULL) app.ok = 0; /* Guard expired or loop stopped early. */
cleanup:
    if (app.ac != NULL) {
        redisAsyncContext *remaining = app.ac;
        app.ac = NULL;
        redisAsyncFree(remaining); /* May run pending callbacks with NULL. */
    }
    event_base_free(app.base);
    return app.ok ? 0 : 1;
}
```

Shell 编译说明；不是 Redis 命令或 PowerShell 命令：

```bash
cc -std=c11 -Wall -Wextra async-demo.c \
  $(pkg-config --cflags --libs hiredis libevent) -o hiredis-async-demo
```

正常预期是输出 PONG 后请求断开，在断开回调里停止循环；连接失败也会停止。3 秒退出保险由应用设置，不是 hiredis 命令超时，更不保证强行中断耗时回调。循环退出后，如果上下文仍归应用持有，就先释放上下文，再释放事件循环。App 一直活到全部收尾结束，避免回调访问已失效的 privdata；程序不在回调外使用 reply。函数签名及绑定过程依据 [async.h](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/async.h)、[libevent 适配器](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/adapters/libevent.h)和 [libevent 循环退出说明](https://libevent.org/libevent-book/Ref3_eventloop.html)，尚未做编译或连接验证。

## 2. 回调可能拿不到回复

连接中断时，待处理回调可能收到 NULL reply。这不代表正常的 Redis NIL 回复：NIL 是一个有类型的回复对象，而 NULL 表示没有可供解析的回复。处理代码必须先判空，再检查类型和业务字段。

默认情况下，异步 redisReply（回复对象）由 hiredis 在命令回调返回后释放，应用不应再次手工释放，也不能保存裸指针供以后使用。若需要长期保留数据，应复制所需字段；非默认选项另见下文。API（Application Programming Interface，应用程序编程接口）的所有权约定见 [v1.2.0 官方说明](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)。

下面用命令回调片段说明回复处理：

```c
void on_reply(redisAsyncContext *ac, void *reply, void *privdata) {
    (void)ac;
    (void)privdata;
    redisReply *r = reply;
    if (r == NULL) return;                    /* No reply: result may be unknown. */
    if (r->type == REDIS_REPLY_NIL) return;   /* A valid Redis nil result. */
    if (r->type == REDIS_REPLY_ERROR) return; /* Server-side command error. */
    /* Handle the expected type and copy needed data before returning. */
}
```

NULL 不等于 NIL（空值回复）：前者没有回复对象，不能据此认定键不存在；后者如 GET 缺失键时的合法结果。ERROR 是服务端错误回复，仍要按具体命令判断结果。

| 对象                | 默认归属                                               | 生命周期边界                                        |
| ------------------- | ------------------------------------------------------ | --------------------------------------------------- |
| redisAsyncContext   | 库按异步连接与断开流程管理；创建时立即失败由调用方清理 | 不可重复释放或在释放后提交命令                      |
| redisReply          | 命令回调返回后由库释放                                 | 跨回调使用需复制必要数据                            |
| privdata / ac->data | 示例由应用持有，库不会自动替任意应用指针释放           | 要覆盖所有可能回调的期间；显式 dataCleanup 契约另算 |
| Event Loop          | 应用创建并管理                                         | 上下文解绑、回调收尾前不能销毁                      |

以下新增归属表以 hiredis v1.2.0 为参照，不冒充完整应用退出代码：

| 时刻                                                     | 默认模式下的上下文归属                                          |
| -------------------------------------------------------- | --------------------------------------------------------------- |
| 创建调用返回 NULL                                        | 没有上下文可释放；处理应用自己的错误状态                        |
| 返回非空上下文但立即检查到错误，尚未进入异步连接回调流程 | 调用方按 API 清理该上下文，不能等待一个没有启动的流程替自己收尾 |
| 后续连接回调报告失败                                     | 库在适用失败回调之后自动释放；不要再次释放或长期保存其地址      |
| 正常请求异步断开或通信异常断开                           | 默认由库按断开流程收尾，外部状态和事件循环资源仍需应用管理      |

`REDIS_OPT_NOAUTOFREE` 阻止连接/通信失败时自动释放上下文，应用需显式安排收尾；v1.2.0 中显式 `redisAsyncDisconnect` 会清除此限制并进入正常断开释放流程。`REDIS_OPT_NOAUTOFREEREPLIES` 则禁止库在已调用的命令回调返回后自动释放回复，应用必须承担相应回复的释放责任。一个管上下文，一个管回复，不能互相替代；也不要与 RESP（Redis Serialization Protocol，Redis 序列化协议）第 3 版 PUSH（主动推送）回复的独立选项混用。[v1.2.0 所有权选项](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

`redisAsyncDisconnect` 停止新命令提交，尝试发送剩余缓冲并处理在途回复后正常断开；`redisAsyncFree` 不等待它们成功完成，清理时会对适用的待处理回调传入 NULL。回调中调用 Free 时，库先标记释放，在回调返回后的安全位置收尾。因此请求释放后不要继续提交，也不要在另一处重复 Free；释放回调资源和 App 时，还要考虑这些 NULL 回调。[v1.2.0 断开、延迟释放与回调源码](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/async.c)

`privdata` 的归属也要写清楚：谁创建，哪些回调还可能访问，何时释放。把已经离开作用域的栈变量地址留给未来回调，或者断开时提前释放共享状态，都会形成悬空引用；上例中的 App 则始终保留到全部收尾完成。

## 3. 回调与工作队列的职责分工 {#_3-不要让回调堵住事件循环}

如果消息回调里进行长时间数据库查询、磁盘写入或等待另一把锁，其他网络事件也可能得不到处理。异步并不意味着回调可以无限耗时。

常见做法是让回调只负责校验、复制必要数据，并将任务投递到有界队列，耗时工作交给合适的工作线程。跨线程结果返回连接所属的事件循环时，也应通过安全机制投递，不能直接并发操作同一个 async context。

事件循环可以由主线程运行，也可以由专用线程运行；“异步只能启动一个新线程”不是库的要求。重要的是上下文与事件资源遵循一致的线程归属。

```text
Event Loop：网络读写 → Reply 回调 → 校验并复制必要数据
                                      ↓
                                有界任务队列
                                      ↓
Worker Thread（工作线程）：耗时业务处理 → 通过线程安全机制投回 Event Loop
```

hiredis v1.2.0 的 redisAsyncContext 不是线程安全对象，工作线程不能直接并发操作同一个上下文。任务队列需限制条数和内存，回调尽量短；异步增加的是客户端利用等待时间的机会，不会自动提高 Redis 服务端的命令执行能力。[v1.2.0 线程安全说明](https://raw.githubusercontent.com/redis/hiredis/v1.2.0/README.md)

## 4. 订阅、重连和背压

PubSub 回调会多次触发，包括订阅确认与消息内容，不能按“一条命令只有一个业务消息”解析。断线后重新连接，还要重新认证并恢复订阅；断线期间的普通 PubSub 消息不会自动补发。

PubSub（Publish/Subscribe，发布订阅）的恢复边界见 [第 11 章](/articles/redis-pubsub.html)。恢复流程应先区分状态：

```text
断开 → 停止使用旧 Context → 区分已确认与结果未知的请求
     → 退避重连 → 恢复认证和适用的连接状态 → 恢复订阅
     → 按业务规则处理待发任务，而非无条件重放
```

重连应带退避、随机抖动和上限。连接恢复后瞬间重放所有待发命令，可能再次压垮服务器，也可能重复执行已完成的写入。请求队列应同时限制条数、总字节和等待时间。

例如指数退避逐次延长等待，再设置最大间隔及最大重试次数；没有收到回复的写入仍可能已经执行，重连不会替应用消除这种未知状态。Backpressure（背压）是下游处理不过来时限制上游继续提交，具体上限需按业务预算验证：

| 限制维度     | 超限后的处理                    |
| ------------ | ------------------------------- |
| 在途请求数量 | 暂停或拒绝新提交                |
| 待发送字节数 | 限流并等待缓冲消耗              |
| 排队时间     | 按 Deadline（截止时间）结束等待 |
| 重连次数     | 退避并限制最大次数              |
| 回调耗时     | 缩短回调或转移耗时任务          |

异步与 Pipeline（流水线批量通信）可以结合，但提交和回复仍需对应，继续见 [第 17 章](/articles/redis-pipeline.html)。

观察异步应用时，除了 Redis 延迟，还应记录事件循环延迟、待发队列深度、回调耗时和失联次数。服务器正常而回调迟迟不运行，根因可能就在应用自己的调度链路。
