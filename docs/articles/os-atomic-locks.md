---
id: os-atomic-locks
title: 第八章 竞争条件、原子操作与锁
description: "多个执行流访问同一份可变数据时，需要同步机制保护共享状态。可以先在抽象模型中观察“读取—计算—写回”如何交错，再理解互斥锁和原子操作怎样约束这些步骤。"
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
order: 8
---

# 第八章 竞争条件、原子操作与锁

> 阅读标签：通用并发模型 / C11与Linux锁条件。

两个线程各统计一部分数据，最后都要给同一个总数加一。第七章的调度能让它们都得到 CPU，却不保证两个更新恰好按业务要求完成。同步需要约束共享状态的访问，以及一个线程的写入怎样被另一个线程正确观察。

本章先看抽象交错，再讨论 C11 原子与 POSIX 互斥锁，最后对照 Linux 内核锁。语言规则、库接口和内核执行环境各有边界，不能混成一套通用的“三行加锁代码”。

## 1. 从丢失更新看临界区

共享计数初始为 0，假设“加一”被拆成读取、计算、写回。在顺序交错的纸面模型中可以发生：

| 步骤 | A                | B                | 共享值 |
| ---- | ---------------- | ---------------- | -----: |
| 1    | 读取 0           | —                |      0 |
| 2    | —                | 读取 0           |      0 |
| 3    | 计算自己的 0 + 1 | —                |      0 |
| 4    | —                | 计算自己的 0 + 1 |      0 |
| 5    | 写回 1           | —                |      1 |
| 6    | —                | 写回 1           |      1 |

两次更新却只留下一个增量，这叫丢失更新（Lost Update）。它属于竞争条件（Race Condition）的例子：正确性依赖没有被协议约束的执行交错。临界区（Critical Section）是需要协调访问共享状态的代码区域；这里要保护整个读改写，而不只是某条写入。

[![两线程读取、计算、写回造成丢失更新的抽象时间线](/assets/notes/operating-systems/os-lost-update.svg)](/assets/notes/operating-systems/os-lost-update.svg)

这不是未同步 C 程序的完整合法结果集合。C11 的数据竞争（Data Race）指不同线程中相互冲突、至少一个非原子、且没有适用先行发生关系约束的访问；它会导致未定义行为，不能断言“只能得到 1 或 2”。竞争条件是更广的正确性问题，即使全部相关单次访问是原子的，业务仍可能因交错而出错。多运行几次没有观察到异常也不构成证明。[WG14 N1570（C11 委员会草案）§5.1.2.4 ¶25](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)

**原子计数**：`atomic_fetch_add()` 对指定原子对象做不可分割的读改写，两次加一不会像上图那样把一个增量覆盖掉。但这只保护该操作，不是自动给整个函数加一把锁。

**复合业务**：余额初始为 100，A、B 都要扣 80。若两者先各自原子读取 100，再分别原子扣减 80，余额仍可能从 100 → 20 → -60。这条抽象业务历史不需要非原子数据竞争，也足以违反“余额不得透支”。用原子读取再原子写回 20，同样可能错误地批准两笔支付。

正确方案之一是互斥锁（Mutex，Mutual Exclusion Lock）保护“检查 + 扣减”的整个临界区，所有相关访问都遵守协议；另一种是下节正确设计的 CAS 循环。原子性、互斥与复合操作正确性是不同层次的保证。

互斥需要覆盖访问同一共享状态的所有相关路径，而不只是调用“同一函数名称”的线程。如果只有写者加锁，读者仍随意读取，也未必满足程序语言和业务要求。

## 2. 原子指令的操作与内存顺序 {#_2-原子指令不等于普通赋值的伪代码}

TAS（Test-and-Set，测试并设置）把“读取旧标志并将其设为已占用”作为一个原子操作。初始标志为 false，A 执行后得到旧值 false、标志变 true；B 再执行得到旧值 true，不能据此认为自己也获得了锁。C11 的 `atomic_flag_test_and_set_explicit()` 提供这种 API，释放可用 `atomic_flag_clear_explicit()`；它们不是用普通三行赋值就能自行实现的可移植原子指令。

CAS（Compare-And-Swap，比较并交换）尝试在当前值等于预期值时更新。C11 的对应接口名为 `atomic_compare_exchange_*`，还会在比较失败时把观察到的当前值写回 `expected`。例如余额为 100：

| 操作             | expected | desired | 结果与后续                                       |
| ---------------- | -------: | ------: | ------------------------------------------------ |
| A 尝试扣款       |      100 |      20 | 成功，余额变 20                                  |
| B 使用旧预期尝试 |      100 |      20 | 比较失败，余额仍为 20，B 的 expected 被更新为 20 |
| B 再判断         |       20 |       — | 不足 80，拒绝扣款，不继续使用旧条件批准          |

下面是 API 使用片段，假设 `balance` 是正确初始化、只承载余额的 `atomic_int`；不是完整支付程序：

```c
int expected = atomic_load_explicit(&balance, memory_order_relaxed);
while (expected >= 80) {
    if (atomic_compare_exchange_weak_explicit(
            &balance, &expected, expected - 80,
            memory_order_relaxed, memory_order_relaxed)) {
        return true;
    }
    /* 失败后 expected 已更新；weak 还可能出现虚假失败。 */
}
return false;
```

每次失败都重新判断并计算，不是盲目重试旧业务决定。这里只需协调一个原子余额，使用 relaxed；若还要与订单、账本等其他数据一起更新，必须另行设计同步与事务协议。原子 API 也不承诺每种类型在所有平台都由一条无锁硬件指令完成。[N1570 §7.17.7.4](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)

### 原子性之外，还需要怎样的内存顺序

原子性回答“该对象的操作是否可被拆开”；内存顺序回答“哪些操作之间建立观察与先后约束”。常见 C11 顺序为：

| 顺序                   | 本章先掌握的用途                                                                                 |
| ---------------------- | ------------------------------------------------------------------------------------------------ |
| `memory_order_relaxed` | 保持指定原子操作本身的保证，不单独建立其他数据的跨线程发布关系                                   |
| `memory_order_release` | 配合适用的获取操作发布本线程先前的写入                                                           |
| `memory_order_acquire` | 在满足读取来源等条件时，与发布操作建立同步，再读取相应数据                                       |
| `memory_order_seq_cst` | 在相应 acquire/release 保证之外，对 seq_cst 原子操作增加一致的单一总序约束；仍不自动合并多步业务 |

单次发布例子：`payload` 为普通整数，初值 0；`ready` 为原子布尔，初值 false。生产者写 `payload = 42`，再对 ready 做 release 存储 true；消费者用 acquire 读取 ready，**实际读到这次发布的 true** 后才读取 payload，可依协议看到 42。假设没有其他写者，且发布后不再修改 payload，也不把 ready 重置复用，这是一条可成立的单次交接。

[![发布数据、release 标志与 acquire 读取的同步关系](/assets/notes/operating-systems/os-release-acquire.svg)](/assets/notes/operating-systems/os-release-acquire.svg)

图中程序顺序与跨线程同步箭头分开标注。这依赖正确的原子对象、内存顺序与读取来源，不是“所有变量立即刷新到所有 CPU”。若两边都只用 relaxed 标志，不能据此建立普通 payload 的发布关系；反复发布还要另设生命周期协议。这里没有展开 release sequence 等完整规则，可对照 [N1570 §5.1.2.4、§7.17.3](https://www.open-std.org/jtc1/sc22/wg14/www/docs/n1570.pdf)。

`volatile` 的访问语义不替代标准线程同步，不提供这种跨线程先行发生（Happens-Before）关系，也不自动把普通自增变为原子操作。原图保留这项边界对照：

[![volatile 与线程同步的职责边界](/assets/notes/operating-systems/os-lock.svg)](/assets/notes/operating-systems/os-lock.svg)

## 3. 关中断只能处理一部分并发

单 CPU 的特定内核场景可通过屏蔽本地中断，防止相关中断路径插入；多个 CPU 上，别的 CPU 仍能访问同一数据。因此，本地 cli 的保护范围只覆盖相应 CPU 的中断路径。

即使单核能在不同线程之间交错，关本地中断也不是用户态 pthread mutex 的替代品，更不能阻止其他核访问共享数据。还要避免在关中断或持有不允许睡眠的锁时等待可能阻塞的操作：等待对象可能需要本核中断处理或别的任务推进，造成无法继续。长临界区也会抬高中断与调度延迟。[Linux 6.6 锁说明](https://docs.kernel.org/6.6/locking/spinlocks.html)

## 4. 自旋与睡眠等待

假设 A 持有锁，B 竞争同一锁。自旋等待让 B 持续尝试获取，期间可能一直消耗 CPU；A 释放后 B 还需真正成功取得锁才能访问数据。睡眠等待允许 B 在竞争时阻塞，A 释放锁后按实现使等待者有机会推进，但被唤醒不等于立刻获锁，还涉及调度成本。

[![A 持锁时 B 自旋或睡眠的两种等待路径](/assets/notes/operating-systems/os-lock-wait.svg)](/assets/notes/operating-systems/os-lock-wait.svg)

短临界区不自动意味着自旋总是更好：多核上 A 可能正运行并很快释放，单核或超额订阅时 A 却可能没有运行机会；调度、缓存争用和锁实现也会影响成本。用户态 mutex 还可能采用先尝试、自旋一段再睡眠等混合策略，不宜仅凭名字推导内部实现。

对 Linux 内核必须看锁类型与配置：非 PREEMPT_RT 的 `spinlock_t` 通常属于禁止抢占的自旋锁；PREEMPT_RT（Real-Time Preemption，实时抢占配置）会改变 `spinlock_t` 的实现与部分语义，而 `raw_spinlock_t` 仍保留严格自旋语义。这不意味着 RT 下可在任意持锁区随意调用阻塞操作，仍须遵守具体锁和嵌套规则。[Linux 6.12 Lock types and their rules](https://docs.kernel.org/6.12/locking/locktypes.html)

## 5. 互斥、公平与死锁的分别检查 {#_5-互斥不自动保证公平或无死锁}

一个实现可能保证同一时刻只有一个持有者，却让某线程长期得不到机会；也可能因嵌套锁顺序不一致形成死锁。有界等待是额外性质，不因函数名为 mutex 就当然满足。

例如 A 持有 L1 再等 L2，B 持有 L2 再等 L1，即使两把锁各自都保证互斥、各自排队公平，仍可能相互等待。互斥、公平、无死锁和业务正确性需要分别检查，完整死锁机制留给[第十章](/articles/os-deadlocks)。

检查时应明确：谁会访问共享状态、哪个锁保护哪些字段、能否睡眠、是否存在逆序加锁，以及退出和错误路径是否释放锁。缺少这些约束，增加锁反而可能引入新故障。

## 6. 实验：两种正确的计数同步

环境为现代 Linux、GCC、pthread 与 C11 原子支持。两个线程各增加 100000 次，目标为 200000；不是通过运行一个数据竞争程序来“验证丢失更新”。以下两份都是完整独立程序。

第一份保存为 `atomic-count.c`。只统计单个原子对象，不用于发布其他数据，所以可使用 relaxed：

```c
#include <pthread.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { LOOPS = 100000 };
static atomic_ulong total = ATOMIC_VAR_INIT(0);

static void check(int error, const char *operation) {
    if (error != 0) {
        fprintf(stderr, "%s: %s\n", operation, strerror(error));
        exit(EXIT_FAILURE);
    }
}

static void *worker(void *unused) {
    (void)unused;
    for (int i = 0; i < LOOPS; ++i) {
        atomic_fetch_add_explicit(&total, 1UL, memory_order_relaxed);
    }
    return NULL;
}

int main(void) {
    pthread_t threads[2];
    for (int i = 0; i < 2; ++i)
        check(pthread_create(&threads[i], NULL, worker, NULL), "pthread_create");
    for (int i = 0; i < 2; ++i)
        check(pthread_join(threads[i], NULL), "pthread_join");
    unsigned long result = atomic_load_explicit(&total, memory_order_relaxed);
    printf("atomic total=%lu\n", result);
    return result == 2UL * LOOPS ? EXIT_SUCCESS : EXIT_FAILURE;
}
```

第二份保存为 `mutex-count.c`，用同一互斥锁保护每次完整更新；主线程等所有工作线程结束后才读取普通计数器：

```c
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

enum { LOOPS = 100000 };
static unsigned long total;
static pthread_mutex_t mutex = PTHREAD_MUTEX_INITIALIZER;

static void check(int error, const char *operation) {
    if (error != 0) {
        fprintf(stderr, "%s: %s\n", operation, strerror(error));
        exit(EXIT_FAILURE);
    }
}

static void *worker(void *unused) {
    (void)unused;
    for (int i = 0; i < LOOPS; ++i) {
        check(pthread_mutex_lock(&mutex), "pthread_mutex_lock");
        ++total;
        check(pthread_mutex_unlock(&mutex), "pthread_mutex_unlock");
    }
    return NULL;
}

int main(void) {
    pthread_t threads[2];
    for (int i = 0; i < 2; ++i)
        check(pthread_create(&threads[i], NULL, worker, NULL), "pthread_create");
    for (int i = 0; i < 2; ++i)
        check(pthread_join(threads[i], NULL), "pthread_join");
    check(pthread_mutex_destroy(&mutex), "pthread_mutex_destroy");
    printf("mutex total=%lu\n", total);
    return total == 2UL * LOOPS ? EXIT_SUCCESS : EXIT_FAILURE;
}
```

```bash
gcc -std=c11 -Wall -Wextra -O0 -pthread atomic-count.c -o atomic-count
gcc -std=c11 -Wall -Wextra -O0 -pthread mutex-count.c -o mutex-count
./atomic-count
./mutex-count
```

预期分别输出 `atomic total=200000` 与 `mutex total=200000`。这些例子不比较锁性能，也不证明算法在所有环境中的公平性。若平台对所用原子类型需要额外运行库，须按工具链配置链接，不能直接声称所有 C11 原子对象必定无锁。

本轮已在 Ubuntu 22.04.5 / WSL2、Linux `5.15.167.4-microsoft-standard-WSL2`、x86-64、GCC 11.4.0、glibc 2.35 下，以文中命令额外加 `-Werror` 编译，并分别运行 3 次；全部正常结束且结果为 200000。没有执行未同步普通自增反例，也未验证其他架构的内存模型表现或注入 pthread 错误。

`check()` 对 pthread 创建、等待及锁操作错误直接终止整个进程，避免把创建失败当成有效线程继续 join，或只让一个线程悄悄退出、留下其他线程等待。它是明确的示例失败策略，不是可恢复的生产级错误处理；没有使用 `pthread_cancel()`，取消清理另需设计。

## 本章小结

- 丢失更新的纸面历史有助于理解机制，但未同步 C11 数据竞争意味着未定义行为。
- 单次原子操作不自动保护“检查 + 更新”的业务，互斥必须覆盖相关访问路径。
- CAS 失败后要重新判断，原子性与内存顺序需要分别设计。
- 锁的等待成本、可睡眠条件、公平与死锁都需单独分析。

## 常见误区

`volatile` 不等于原子或同步；一次计数正确不代表整个业务正确。内核自旋锁规则也不能直接当作用户态 mutex 的规则。

## 下一章衔接

互斥解决“谁能修改共享状态”，但数据尚未到达时不应一直占着锁等待。[第九章](/articles/os-semaphores-conditions)用信号量与条件变量解释怎样等待、通知和重新检查条件。

[返回本册目录](/collections/operating-systems/)
