---
id: os-buffer-io
title: 第十一章 bread、缓冲区与 I/O 等待
description: "Linux 0.11 的 bread 按“取得缓冲区、检查数据是否有效、必要时发起设备读取、等待后检查结果”的顺序工作。"
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
order: 11
---

# 第十一章 bread、缓冲区与 I/O 等待

> 阅读标签：Linux 0.11 原始源码的 Buffer Cache（缓冲区缓存）历史案例；不是现代 Linux 页缓存实现。

读取设备上的一个块，是否每次都得访问硬盘？Linux 0.11 的 `bread()` 先取得缓冲区，检查数据是否有效，必要时提交读取，再等待并检查结果。这样既复用已有数据，也让设备执行输入/输出（I/O，Input/Output）时，中央处理器（CPU，Central Processing Unit）可以运行其他任务。但“数据有效”不保证整个获取过程从不等待；“提交读取”也不保证必定切走当前任务。

本章依据 [kernel.org 的 Linux 0.11 原始压缩包](https://www.kernel.org/pub/linux/kernel/Historic/old-versions/linux-0.11.tar.gz)，主要阅读 `include/linux/fs.h`、`fs/buffer.c`、`kernel/sched.c` 和 `kernel/blk_drv/`。下面的状态与时序都是教学推演，不是运行日志。

## 1. 缓冲区先存在，才能提交请求

缓冲区缓存保存设备块的数据与管理状态。Linux 0.11 的 `buffer_head` 是描述结构，`b_data` 才指向数据区；`BLOCK_SIZE` 为 1024 字节。缓存键是 `(b_dev, b_blocknr)`，不能只按块号查找。

| 字段与原版类型               | 职责及边界                                           |
| ---------------------------- | ---------------------------------------------------- |
| `unsigned short b_dev`       | 设备标识                                             |
| `unsigned long b_blocknr`    | 该设备上的块号                                       |
| `char *b_data`               | 对应的 1024 字节数据区地址                           |
| `unsigned char b_count`      | 缓冲引用计数；非零时不能作为无引用缓冲直接改作其他块 |
| `unsigned char b_lock`       | 缓冲相关操作的锁定标志，等待代码据此决定是否睡眠     |
| `unsigned char b_uptodate`   | 数据对当前设备块是否有效                             |
| `unsigned char b_dirt`       | 修改后需要提交写回的脏标记；不是持久化完成标记       |
| `struct task_struct *b_wait` | 历史等待关系的入口指针                               |

[![设备块键、buffer_head 状态与数据区](/assets/notes/operating-systems/os-buffer-state.svg)](/assets/notes/operating-systems/os-buffer-state.svg)

引用计数不是互斥锁；锁定不表示数据有效；有效不表示已经持久化。尤其 `ll_rw_blk.c` 的 `add_request()` 在请求入队时就清除相关 `b_dirt`，因此 `b_dirt == 0` 不能证明设备已完成写入。脏标记需要结合锁、请求及上层语义理解。

### getblk() 怎样取得这个对象

`getblk(dev, block)` 复用预先建立的缓冲池，不是每次 `malloc()` 一份新数据区。按 `fs/buffer.c` 的实际顺序阅读：

1. `get_hash_table()` 查找设备和块号；命中后增加 `b_count`，通过 `wait_on_buffer()` 等待解锁，再复查设备与块号。若不再匹配，就撤销这次引用并重新查找。
2. 未找到目标时，扫描名为 `free_list` 的循环链。这个名字不表示链上每个缓冲都无人引用；代码跳过 `b_count != 0` 者，并按 `BADNESS = (b_dirt << 1) + b_lock` 选择候选，优先干净且未锁定者。
3. 没有候选就 `sleep_on(&buffer_wait)`，醒来后跳到 `repeat` 重做查找。缓冲池压力走等待重试，不是普通的“内存不足就返回 NULL”。
4. 找到候选后仍要等锁，再检查 `b_count`。若它已被别人引用，重新开始；若脏，则调用 `sync_dev()`，等待相关缓冲并反复检查脏状态与引用。这里可能同步该设备的其他缓冲和 inode，不只是当前一块。
5. 任何可能睡眠的过程之后，其他任务都可能已经建立目标块的缓存。因此还要 `find_buffer(dev, block)` 查重，存在则重试。
6. 确认能复用后，设 `b_count=1`、`b_dirt=0`、`b_uptodate=0`，从旧队列移除，设置新设备和块号，再插入哈希链与循环链并返回。

[![getblk 查找命中或复用缓冲后的复查过程](/assets/notes/operating-systems/os-getblk.svg)](/assets/notes/operating-systems/os-getblk.svg)

这解释了为什么“在哈希表中找到对象”“对象数据有效”“过程中无需睡眠”是三个不同判断。源码中 `bread()` 对 `getblk()` 的空指针仍有 `panic()` 防御分支，不应改写成通常以 NULL 报告缓冲不足。

## 2. 缓存未命中的路径

下面保留 `bread()` 主体的原始控制顺序，省去声明与防御性 `panic()`：

```c
bh = getblk(dev, block);
if (bh->b_uptodate)
    return bh;
ll_rw_block(READ, bh);
wait_on_buffer(bh);
if (bh->b_uptodate)
    return bh;
brelse(bh);
return NULL;
```

[![bread 取得缓冲、检查有效性、必要时读取并检查结果](/assets/notes/operating-systems/os-bread.png)](/assets/notes/operating-systems/os-bread.png)

保留原 PNG 及同名 SVG，正文继续使用 PNG。图中“将进入等待状态”应理解为：**检查时仍锁定才睡眠**。getblk 内部本身也可能等待；图中的命中分支仅表示取得有效缓冲后不再提交本次 READ。

统一读取设备 D 的块 B，得到三条路径：

| 情况                  | 关键状态及控制流                                  | 返回与调用者责任                                        |
| --------------------- | ------------------------------------------------- | ------------------------------------------------------- |
| A：已有有效数据       | getblk 取得引用；`b_uptodate=1`                   | 直接返回 bh，不提交本次 READ；用完按调用协议 `brelse()` |
| B：初始无效，读取成功 | 有效位为 0；提交 READ；等待适用操作结束；复查为 1 | 返回有效 bh；持有引用不等于一直持锁                     |
| C：读取最终失败       | READ 经适用重试后失败；锁已解除；有效位仍为 0     | `brelse(bh)` 释放引用，返回 NULL；上层检查错误          |

`brelse()` 先等锁，递减引用计数并唤醒等待可复用缓冲的任务，不是立即释放这块数据区内存。一次设备错误可能先重试，不一定立即走 C；无效设备还可能在提交检查阶段失败。缓存未命中也不必然造成任务切换：数据可能已被别人读好，或请求在检查锁之前就完成。

## 3. 循环检查 b_lock 与等待后的有效性 {#_3-等待为什么循环检查-b-lock}

`fs/buffer.c` 的原版代码是：

```c
cli();
while (bh->b_lock)
    sleep_on(&bh->b_wait);
sti();
```

`cli`/`sti` 是 x86 关闭/开启可屏蔽中断的指令。这里依靠历史单 CPU、中断和内核调度条件，保护“检查锁 → 登记等待 → 睡眠”的衔接，防止完成通知落在登记之前。它不是通用的保存并恢复原中断状态的现代锁接口，也不表示任务睡眠期间整机一直不能响应中断；其他任务恢复运行及中断返回有各自的状态恢复过程。

唤醒只意味着可以重新竞争 CPU；等当前任务实际运行时，缓冲又可能被其他操作锁住，所以使用 `while`。退出等待只证明观察到 `b_lock=0`，随后还必须查 `b_uptodate`，才能区分成功与失败。

Linux 0.11 时钟路径不会直接抢占正在内核态执行的任务，但 `sleep_on()` 可以显式调用调度器。因此等待后必须复查共享状态。不能推广为现代 Linux 内核不抢占，也不能以“关本地中断”解决现代对称多处理（SMP，Symmetric Multiprocessing）的全部并发。[第六章上下文切换](/articles/os-context-switching.html)、[第九章等待条件](/articles/os-semaphores-conditions.html)

## 4. sleep_on 用栈上变量保存等待关系 {#_4-sleep-on-的栈上变量起什么作用}

`kernel/sched.c` 中的不可中断等待版本如下；任务 0 不允许进入这段睡眠路径：

```c
void sleep_on(struct task_struct **p)
{
    struct task_struct *tmp;
    if (!p) return;
    if (current == &(init_task.task))
        panic("task[0] trying to sleep");
    tmp = *p;
    *p = current;
    current->state = TASK_UNINTERRUPTIBLE;
    schedule();
    if (tmp)
        tmp->state = 0;
}
```

`wake_up(p)` 则在 `p && *p` 时将 `(**p).state=0`，再设 `*p=NULL`。这里 0 是 `TASK_RUNNING`，包含可运行状态，不等于立刻占有 CPU。

假设同一 `bh->b_wait` 初始为空，A、B 先后因锁定而睡眠，期间没有其他等待者插入，也不在下面各阶段之间再次进入新的等待：

| 阶段                      | `bh->b_wait` | A 的栈上 tmp | B 的栈上 tmp          | 状态变化                                          |
| ------------------------- | ------------ | ------------ | --------------------- | ------------------------------------------------- |
| 初始                      | NULL         | —            | —                     | 两者尚未登记                                      |
| A 执行 sleep_on           | A            | NULL         | —                     | A 置不可中断等待并调度                            |
| B 执行 sleep_on           | B            | NULL         | A                     | B 保存旧入口 A，自己睡眠                          |
| 完成路径 wake_up          | NULL         | NULL         | A                     | B 变为可运行，A 尚未因此运行                      |
| B 获得 CPU，schedule 返回 | NULL         | NULL         | A                     | B 执行 `tmp->state=0`，使 A 可运行                |
| A 后来获得 CPU            | NULL         | NULL         | —（B 的该调用已返回） | A 的 tmp 为空，不再传递唤醒；各自回到外层条件复查 |

[![两个等待者分别保存在自己内核栈上的 tmp 与唤醒传递](/assets/notes/operating-systems/os-buffer-waiters.svg)](/assets/notes/operating-systems/os-buffer-waiters.svg)

`schedule()` 暂停的是各任务自己的执行；内核栈保留调用帧与局部变量，回来后才执行后面的语句。它像通过各栈保存先前等待者，但不是现代有独立链表节点、完整并发规则的等待队列 API。不能仅凭图形相似就移植到多核或可中断等待路径。

## 5. 中断完成与业务完成

设任务 A 调用 `bread(D, B)`，先经 `getblk()` 取得设备 D、块 B 的缓冲；有效则直接返回。下面选取数据无效、需要提交硬盘 READ 的历史路径，省略预读和其他设备分支：

1. `ll_rw_block()` 在 `kernel/blk_drv/ll_rw_blk.c` 检查设备主设备号及请求函数，再调用 `make_request()`。
2. `make_request()` 锁定缓冲；若发现数据此时已有效，可解锁返回而不发出重复 READ。否则寻找请求槽，槽不足时普通请求还可能睡在 `wait_for_request` 上。A 若进入睡眠，调度器会选择其他可运行任务；没有普通候选时按历史规则选择任务 0。
3. 构造请求，设置 `sector = b_blocknr << 1`、`nr_sectors = 2`，把 1024 字节块对应到两个 512 字节扇区。`add_request()` 入队；队列原来空闲时可以立即调用设备请求函数，否则等待前面的请求。
4. 硬盘驱动 `hd.c` 的 `read_intr()` 按扇区读取数据；尚有扇区时继续等待后续中断。一场中断不一定完成整个块；错误可先重试，达到失败条件才 `end_request(0)`。
5. `blk.h` 的 `end_request(uptodate)` 对有关缓冲设置 `b_uptodate`，调用 `unlock_buffer()` 清 `b_lock` 并 `wake_up(&bh->b_wait)`；另唤醒请求相关等待者及请求槽等待者，释放请求槽并推进队列。
6. 被唤醒任务以后得到调度，恢复自己的内核栈，退出或继续 `while`，回到 `bread()` 复查有效位，随后上层继续使用数据或处理 NULL。

[![请求提交、任务睡眠、设备完成、可运行和实际恢复的区别](/assets/notes/operating-systems/os-block-io-timeline.svg)](/assets/notes/operating-systems/os-block-io-timeline.svg)

设备完成、任务可运行、任务实际运行、系统调用返回、应用业务完成是不同事件。失败也会解锁和唤醒，因此唤醒不是成功通知。若检查时锁已经解除，则直接沿原任务返回，不必经过“睡眠 → 调度回来”的分支。

### 静态源码实验：沿条件追踪，不运行旧内核

取得上述固定 0.11 压缩包，解压后进入 `linux/` 源码根目录，执行以下只读查询；压缩包中的目录名以实际解压结果为准：

```sh
grep -nE 'struct buffer_head|b_count|b_lock|b_uptodate|b_dirt' include/linux/fs.h
grep -nE 'get_hash_table|getblk|bread|wait_on_buffer|brelse|repeat:' fs/buffer.c
grep -nE 'sleep_on|wake_up|tmp =|TASK_UNINTERRUPTIBLE' kernel/sched.c
grep -nE 'make_request|add_request|unlock_buffer|wait_for_request' kernel/blk_drv/ll_rw_blk.c
grep -nE 'end_request|b_uptodate|wake_up' kernel/blk_drv/blk.h
grep -nE 'read_intr|bad_rw_intr|end_request' kernel/blk_drv/hd.c
```

随后阅读命中行所在的完整函数，并在纸上分别标出有效命中、读取成功、最终失败三条路径；再用第四节表格跟踪两个 tmp。查询命中只能定位源码，不能替代对分支顺序的阅读。本轮已对固定版本逐函数静态核验，没有编译或启动 Linux 0.11，也没有宣称重现硬盘中断日志。

## 联读

本章把第九章的“等条件”落到历史缓冲锁上。下一章看[文件对象与持久化](/articles/os-file-descriptors-persistence.html)，第二十章的[现代页缓存、read 与 mmap](/articles/os-mmap-page-cache.html)另讲现代实现；不要把两套缓存画成同一条源码调用链。

[返回本册目录](/collections/operating-systems/)
