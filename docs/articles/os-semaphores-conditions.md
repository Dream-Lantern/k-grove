---
id: os-semaphores-conditions
title: 第九章 信号量、条件变量与丢失唤醒
description: "信号量和条件变量用于协调执行流的等待与继续。一次可靠的等待要把条件检查、等待注册、状态修改和唤醒衔接起来，使资源已经就绪时的通知不会落在空隙中。"
date: '2026-10-25'
updated: '2026-10-28'
category: distributed-systems
type: explanation
tags:
  - 操作系统
draft: false
source:
  kind: study-notes
  note: 个人学习整理；来源、适用版本与验证边界见正文。日期为本站首次发布日期。
collection: operating-systems
series: os-learning
order: 9
---

# 第九章 信号量、条件变量与丢失唤醒

> 阅读标签：通用同步原语 / POSIX条件等待。

生产者从文件读出数据块，消费者统计内容。第八章的互斥锁可以保护队列，却不能让“暂时没有数据”自动变成“稍后安全继续”：消费者若持锁干等，生产者可能连入队的机会都没有；若随意解锁再睡眠，又可能错过通知。

信号量和条件变量协调等待与继续。可靠协议必须把条件检查、等待注册、状态修改和通知衔接起来。本章先区分许可与通知，再用容量为 2 的有界队列追踪整个生产消费过程。

## 1. 计数信号量的资源语义

计数信号量（Counting Semaphore）维护许可数量。`sem_wait()` 尝试取得一个许可，`sem_post()` 归还或发布一个许可。传统教材也把这两类操作称为 P/V。若用它代表容量为 2 的资源池，协议还必须保证许可不会被重复归还，信号量本身并不知道真实资源有几份。

假设初始有 2 个许可，A、B、C 都要使用资源：

| 步骤 | 操作               | 逻辑可用许可与状态                          |
| ---- | ------------------ | ------------------------------------------- |
| 0    | 初始化             | 2；无人持有                                 |
| 1    | A 成功 sem_wait    | 2 → 1；A 使用一份                           |
| 2    | B 成功 sem_wait    | 1 → 0；A、B 各使用一份                      |
| 3    | C 调用 sem_wait    | 没有许可，C 等待；不占用一份不存在的资源    |
| 4    | A 完成并 sem_post  | 释放一份，C 获得推进机会；不保证立即运行    |
| 5    | C 后续成功取得许可 | 若无其他竞争，B、C 各使用一份，空闲许可为 0 |

有等待者时，不要机械地声称内部计数必定经历一个可观察的 `0 → 1 → 0`：许可转交和等待者运行取决于实现，读取计数也只是易变化的观察，不是资源已经归某个线程的保证。

| POSIX 接口        | 没有可用许可时的行为与错误                                     |
| ----------------- | -------------------------------------------------------------- |
| `sem_wait()`      | 可以阻塞；被适用信号处理打断时可返回 `-1` 并设置 `EINTR`       |
| `sem_trywait()`   | 不等待，返回 `-1` 并设置 `EAGAIN`                              |
| `sem_timedwait()` | 受绝对超时限制；超时可返回 `ETIMEDOUT`，也需处理适用的信号中断 |
| `sem_post()`      | 发布许可，适用时使等待者可继续；仍要检查例如计数溢出错误       |

实际代码应区分成功取得许可与错误返回，再决定重试、超时退出或回滚，不能把每个返回都视为已经获得资源。[sem_wait(3)](https://man7.org/linux/man-pages/man3/sem_wait.3.html)、[sem_post(3)](https://man7.org/linux/man-pages/man3/sem_post.3.html)

有些教学实现用负数表示等待者数量，这是内部计数约定。使用 POSIX 接口时，应按该接口的返回值和计数语义理解状态。P/V 的计数更新与等待队列必须在同步协议中原子配合。[OSTEP Semaphores](https://pages.cs.wisc.edu/~remzi/OSTEP/threads-sema.pdf)

二值信号量和互斥锁也不是可随意替换的同一对象：mutex 有适用的持有者/解锁规则，信号量可用于一个线程发布、另一个线程取得的许可交接。

## 2. 条件变量等待受锁保护的谓词 {#_2-条件变量不保存一份资源计数}

条件变量（Condition Variable）配合互斥锁等待业务谓词（Predicate），即一个能判断真假的条件，例如“队列非空”或“队列已经关闭”。通知提醒等待者重新检查，**不把某一份资源预留给该线程，也不自行保存业务数量**。

比较同一场景：生产者先完成一份工作，消费者稍后才来。

- 信号量初值为 0，生产者先 post 留下一份许可；消费者后来 wait 可以取得它，无需再等一次 post。
- 条件变量的 signal 若发生时没有等待者，通知不会被储存。但生产者在同一互斥锁下把 `queue_nonempty` 等真实状态更新了；消费者后来持锁看到条件已满足，应直接取数据，而不是无条件等下一次 signal。

[![通知先于等待时，信号量许可与条件变量谓词的不同](/assets/notes/operating-systems/os-semaphore-condition.svg)](/assets/notes/operating-systems/os-semaphore-condition.svg)

如果只发 signal、不维护持久业务谓词，后来的消费者便无法据此判断工作已经完成。通知没有“存起来”，不等于数据本身也消失了。

教学伪代码：

```text
消费者：
    加锁
    while 队列为空:
        condition_wait：原子释放锁并等待，返回时重新持锁
    取出一项
    解锁
生产者：
    加锁，放入一项并更新谓词
    按协议通知等待者
    解锁
```

伪代码展示检查与等待的配合，实际使用时还要按 API 处理错误、取消和对象生命周期。

## 3. 唤醒后用 while 重新检查条件 {#_3-为什么必须用-while}

等待者从被唤醒到重新获得锁之间，资源可能已被其他线程取走；接口也可能允许虚假唤醒。如果只用 if，唤醒后直接访问队列而不重新检查，就可能尝试取出不存在的元素。

设 A、B 都在空队列上等待，生产者 P 放入 1 个元素后 broadcast：

1. A、B 都获得重新竞争互斥锁的机会，但不表示同时持锁。
2. A 先取得锁，看到队列非空，取走唯一元素并解锁。
3. B 随后取得锁，此时队列又为空。B 必须重新等待，不能仅凭“刚才收到通知”就执行出队。

即使没有其他消费者，POSIX 仍允许虚假唤醒（Spurious Wakeup），因此应用也不应省略重检。常见代码片段为：

```c
/* 调用前已持有 mutex；实际程序还需处理返回错误和退出条件。 */
while (queue_empty()) {
    pthread_cond_wait(&cond, &mutex);
}
```

while 每次发现条件不满足会调用等待接口，释放锁并阻塞，不是持续占用 CPU 的忙等循环。实际队列还应把“已经关闭”放入等待与退出判断，见后面的完整程序。

POSIX 条件等待要求调用方先持有指定互斥锁，等待过程相对于其他线程取得该锁并通知的行为，原子地释放锁并阻塞；正常返回时重新持锁。这里的“原子”保证等待协议的衔接，不意味着消费者睡眠期间仍占有锁。不能替换为“解锁；普通 sleep”。[pthread_cond_wait 的 POSIX 说明](https://man7.org/linux/man-pages/man3/pthread_cond_wait.3p.html)

## 4. 丢失唤醒的反例

以下是错误协议的纸面反例，不是要求读者运行一个会挂起的 C 程序：

| 顺序 | 消费者 C                                     | 生产者 P                                     |
| ---- | -------------------------------------------- | -------------------------------------------- |
| 1    | 持锁发现队列为空，保存这个判断，然后单独解锁 | —                                            |
| 2    | 尚未登记等待，出现竞态窗口                   | 取得锁、入队、signal；此时没有等待者，再解锁 |
| 3    | 后来重新加锁，却不重检旧判断就调用 cond_wait | 不再产生新数据或通知                         |
| 4    | 等待未来通知，可能一直停在这里               | 队列实际已有数据                             |

步骤 3 即使重新持锁后再调用合法的等待接口，也不能修补先前那次过期检查。用不具备条件变量协议的普通睡眠替换等待，同样无法堵住窗口。

[![错误检查与等待空隙，对照同锁谓词和原子等待协议](/assets/notes/operating-systems/os-wakeup.svg)](/assets/notes/operating-systems/os-wakeup.svg)

正确协议中，C 持锁检查；条件不满足时直接调用 cond_wait，让“放锁 + 等待”与其他线程取锁通知正确协调。P 取得同一锁、修改谓词后通知；C 返回时重新持锁，并通过 while 重检。若 P 先完成，C 检查时就看到数据；若 C 先检查到空，P 在取得该锁之后的通知又不会落进上述窗口。

修复时，需要正确协调谓词访问、等待注册和锁释放，而不是反复发送通知。内核等待队列也面临类似问题，只是所用原语和执行上下文不同。

**POSIX 并不要求每次 signal/broadcast 都必须由持有互斥锁的线程调用。** 关键是共享谓词的保护、对象生命周期和等待协议。本章选择锁内更新并通知，便于推演；某些正确设计可在更新后解锁再通知，但不能因此允许无同步地检查、修改谓词。[pthread_cond_signal / broadcast 的 POSIX 说明](https://man7.org/linux/man-pages/man3/pthread_cond_broadcast.3p.html)

## 5. 用有界缓冲区练习

固定容量 K=2，初始队列为空。信号量方案令 empty=2 表示可保留的空位，full=0 表示可保留的数据项，再用 mutex 保护队列结构。下面是成功路径的伪代码，不是省略错误检查即可投产的实现：

```text
生产者：                        消费者：
wait(empty) 成功保留空位         wait(full) 成功保留数据项
lock(mutex)                     lock(mutex)
入队并更新队列结构              出队并更新队列结构
unlock(mutex)                   unlock(mutex)
post(full) 发布数据项            post(empty) 归还空位
```

empty/full 管理两类许可，mutex 防止多个执行流同时损坏队列索引与内容，二者分工不同。不能任意换成先 lock 再 wait：例如队列为空，消费者持有 mutex 等 full，生产者却必须先拿 mutex 才能入队并 post full，于是相互等待。

[![容量 2 的信号量队列中，保留空位、入队、发布与消费的状态](/assets/notes/operating-systems/os-buffer-protocol.svg)](/assets/notes/operating-systems/os-buffer-protocol.svg)

按这条无并发插入的指定路径：初始 `(empty, full, 项数) = (2,0,0)`；生产者 wait empty 后为 `(1,0,0)`；入队但尚未 post full 时为 `(1,0,1)`；发布后为 `(1,1,1)`。所以 **empty + full 不必在任意中间时刻都等于 K**，还存在执行流已经保留、尚未转交的许可。消费者取得 full 后到归还 empty 前也有类似阶段，不能把许可计数当作所有时刻队列长度的直接快照。

协议应保持 `0 <= 队列项数 <= K`，不丢失、不重复消费数据，也不消费尚未入队的项；还要为停止和取消设计能够解除等待的路径。

上述目标还需要结束协议才能成立。成功修改队列并转交对应许可后，适用等待者才有机会继续；失败或取消发生在保留许可之后时，需要按阶段回滚，不能丢掉许可或重复归还。只设一个普通停止标志不会自动解除 sem_wait。有限工作量可设计与消费者数量匹配的结束项，或采用可超时等待和明确关闭协议；不能随意多 post 几次、让消费者误认为凭空出现了数据。

## 6. 实验：可关闭的有限条件变量队列

下面采用另一种实现：**一个 mutex、两个条件变量，不再叠加信号量**。容量仍为 2，1 个生产者放入 1～20，2 个消费者处理；生产结束后在锁内设置 closed 并广播。消费者先排空已有数据，看到“关闭且空”才退出。

在现代 Linux、GCC/pthread 环境保存完整程序为 `bounded-queue.c`：

```c
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { K = 2, N = 20 };
static int queue[K], head, tail, count, closed;
static int seen[N + 1], consumed, sum;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t not_empty = PTHREAD_COND_INITIALIZER;
static pthread_cond_t not_full = PTHREAD_COND_INITIALIZER;

static void check(int error, const char *operation) {
    if (error != 0) {
        fprintf(stderr, "%s: %s\n", operation, strerror(error));
        exit(EXIT_FAILURE);
    }
}

static void *producer(void *unused) {
    (void)unused;
    for (int item = 1; item <= N; ++item) {
        check(pthread_mutex_lock(&mutex), "lock");
        while (count == K && !closed)
            check(pthread_cond_wait(&not_full, &mutex), "wait not_full");
        if (closed) {
            check(pthread_mutex_unlock(&mutex), "unlock");
            return NULL;
        }
        queue[tail] = item;
        tail = (tail + 1) % K;
        ++count;
        check(pthread_cond_signal(&not_empty), "signal not_empty");
        check(pthread_mutex_unlock(&mutex), "unlock");
    }
    check(pthread_mutex_lock(&mutex), "lock close");
    closed = 1;
    check(pthread_cond_broadcast(&not_empty), "broadcast not_empty");
    check(pthread_cond_broadcast(&not_full), "broadcast not_full");
    check(pthread_mutex_unlock(&mutex), "unlock close");
    return NULL;
}

static void *consumer(void *unused) {
    (void)unused;
    for (;;) {
        check(pthread_mutex_lock(&mutex), "lock");
        while (count == 0 && !closed)
            check(pthread_cond_wait(&not_empty, &mutex), "wait not_empty");
        if (count == 0 && closed) {
            check(pthread_mutex_unlock(&mutex), "unlock end");
            return NULL;
        }
        int item = queue[head];
        head = (head + 1) % K;
        --count;
        if (item < 1 || item > N) exit(EXIT_FAILURE);
        ++seen[item];
        ++consumed;
        sum += item;
        check(pthread_cond_signal(&not_full), "signal not_full");
        check(pthread_mutex_unlock(&mutex), "unlock");
    }
}

int main(void) {
    pthread_t p, c[2];
    for (int i = 0; i < 2; ++i)
        check(pthread_create(&c[i], NULL, consumer, NULL), "create consumer");
    check(pthread_create(&p, NULL, producer, NULL), "create producer");
    check(pthread_join(p, NULL), "join producer");
    for (int i = 0; i < 2; ++i)
        check(pthread_join(c[i], NULL), "join consumer");
    check(pthread_cond_destroy(&not_empty), "destroy not_empty");
    check(pthread_cond_destroy(&not_full), "destroy not_full");
    check(pthread_mutex_destroy(&mutex), "destroy mutex");
    int valid = count == 0 && closed && consumed == N && sum == N * (N + 1) / 2;
    for (int i = 1; i <= N; ++i) valid = valid && seen[i] == 1;
    printf("consumed=%d sum=%d valid=%d\n", consumed, sum, valid);
    return valid ? EXIT_SUCCESS : EXIT_FAILURE;
}
```

```bash
gcc -std=c11 -Wall -Wextra -O0 -pthread bounded-queue.c -o bounded-queue
./bounded-queue
```

预期正常输出 `consumed=20 sum=210 valid=1` 并退出。程序用 seen 检查每个输入恰好被消费一次；统计也受同一锁保护，主线程在 join 全部完成后读取。队列操作保持 `0 <= count <= K`，不同消费者各取到哪些项由调度决定，不是固定交替。

本轮已在 Ubuntu 22.04.5 / WSL2、Linux `5.15.167.4-microsoft-standard-WSL2`、x86-64、GCC 11.4.0、glibc 2.35 下额外加 `-Werror` 编译并运行 3 次，均得到上述结果并在限时内结束。这验证了指定环境的有限工作量路径，不是对全部调度交错、超时、取消或错误恢复的穷尽证明。

程序对 pthread 错误采用明确的进程级失败策略：check 报错后终止整个进程，避免线程创建失败后让其他线程永久等一个不存在的生产者。正常路径 join 后才销毁同步对象。这不是可恢复错误框架，也不支持外部取消；真实系统需要按故障阶段关闭队列、归还资源并通知受影响的等待者。

## 7. 超时、关闭与取消的边界

- 条件等待正常返回但谓词仍不满足：按 while 重新等待，或依据 closed 退出。
- `pthread_cond_timedwait()`：处理 `ETIMEDOUT` 后仍要在持锁状态下检查谓词，数据可能与超时竞争到达；绝对期限所用时钟由条件变量属性等规则决定，不要与相对时长混写。它与 sem_wait 的信号中断返回规则不同，不能统一套 `EINTR` 重试。
- 关闭队列：在同一锁下更新状态，唤醒可能等待“非空”与“非满”的相关线程，并明确排空还是丢弃剩余数据。广播本身不会让不满足退出条件的线程自动结束。
- 线程取消：条件等待是取消点，适用的取消处理会先重新取得 mutex；清理处理程序需要解除锁及其他已保留资源。上面的实验没有调用 `pthread_cancel()`，不能把它当作已经支持取消清理的生产级队列。[POSIX 条件等待的取消与超时规则](https://man7.org/linux/man-pages/man3/pthread_cond_wait.3p.html)

## 本章小结

- 信号量保存许可，条件变量不保存业务资源数量；真实谓词需要在共享状态中表达。
- 持锁检查、原子等待和 while 重检共同保证协议，唤醒不等于立即获锁或得到资源。
- 有界队列要同时处理容量、结构互斥和结束条件，许可的中间状态不能忽略。

## 常见误区

signal 不是给某个线程预留数据；while 也不是必须忙等。只加一个停止标志、只广播一次或任意多 post，都不能替代完整的关闭与回收协议。

## 下一章衔接

等待与加锁顺序设计错误时，参与者可能互相等待。[第十章](/articles/os-deadlocks)继续分析死锁条件与处理方法，本章不提前展开完整算法。

[返回本册目录](/collections/operating-systems/)
