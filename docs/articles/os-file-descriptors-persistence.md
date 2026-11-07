---
id: os-file-descriptors-persistence
title: 第十二章 文件描述符、文件系统与持久化
description: "文件访问从路径查找开始，经由进程中的文件描述符联系内核打开状态，再到文件系统中的存储对象。沿这条关系，可以理解 fork 后的偏移共享、read/write 的返回量，以及数据何时满足持久化要求。"
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
order: 12
---

# 第十二章 文件描述符、文件系统与持久化

> 阅读标签：POSIX（Portable Operating System Interface，可移植操作系统接口）文件语义与现代 Linux 普通文件案例；具体持久化还依赖文件系统和设备。

程序更新配置文件时，怎样让读者看到完整版本？为什么 `write()` 成功之后，还要考虑同步文件和目录？先沿路径、文件描述符和内核对象建立关系，再区分“接口处理了多少字节”“新版本何时可见”“崩溃后能否恢复”。上一章 Linux 0.11 的缓冲实现是历史案例，不能直接当作本章现代 Linux 的源码调用链。

## 1. 路径与描述符

路径用于查找对象；`open()` 成功返回文件描述符（FD，File Descriptor），即进程描述符表中的非负整数编号。编号引用打开文件描述（Open File Description），后者保存这一次打开的状态，例如文件偏移和文件状态标志；Linux 通常以 `struct file` 承载这类状态。它再联系文件系统对象，对适用普通文件涉及 inode（索引节点）等结构。文件名不是 FD，FD 也不是文件在磁盘上的地址。[open(2)](https://man7.org/linux/man-pages/man2/open.2.html)

[![路径查找、描述符表、共享与独立打开状态及文件对象](/assets/notes/operating-systems/os-file-objects.svg)](/assets/notes/operating-systems/os-file-objects.svg)

虚拟文件系统（VFS，Virtual File System）为不同文件系统提供公共接口。对本章选定的普通缓存文件，访问可能涉及页缓存与存储设备，但缓存命中不必访问设备；直接输入/输出（I/O，Input/Output）、内存文件系统、管道和网络文件系统也有不同路径，不能把所有 FD 都画成“缓存 → 本地磁盘”的单线调用链。

同一个对象可有多个名字、多个打开状态和多个描述符引用。路径被重命名或解除链接，不会立即使已有 FD 失效；解除最后一个硬链接后，仍打开的文件通常要等最后一个相关引用关闭才回收。关闭某个 FD 也不意味着其他引用失效或所有数据落盘。[unlink(2)](https://man7.org/linux/man-pages/man2/unlink.2.html)

## 2. dup 与 fork 形成共享偏移 {#_2-共享偏移怎样出现}

设普通文件内容是 `ABCDEF`，一次 `open()` 返回 fd3，`dup(fd3)` 得到 fd4。数字 3、4 只是教学假设，实际编号不能预先写死。两个表项指向**同一个**打开文件描述，共享其偏移：

| 操作（按顺序执行）  | 读到数据 | 共同偏移 |
| ------------------- | -------- | -------- |
| 初始                | —        | 0        |
| `read(fd3, ..., 2)` | AB       | 2        |
| `read(fd4, ..., 2)` | CD       | 4        |
| `read(fd3, ..., 2)` | EF       | 6        |

相反，再独立 `open()` 同一路径，一般创建另一个打开文件描述，它的初始偏移仍为 0；它与前一个打开状态引用的文件对象可以相同。`fork()` 复制出来的父子 FD 表项引用原来的打开文件描述，因此也共享适用偏移。父子若并发执行，谁先读不能由示例表格保证；表格只演示已规定的串行顺序。[dup(2)](https://man7.org/linux/man-pages/man2/dup.2.html)、[fork(2)](https://man7.org/linux/man-pages/man2/fork.2.html)

| 状态                                               | 存放或关联位置 | 共享边界                                                       |
| -------------------------------------------------- | -------------- | -------------------------------------------------------------- |
| 文件偏移、`O_APPEND` / `O_NONBLOCK` 等文件状态标志 | 打开文件描述   | dup、fork 形成的引用共享；独立 open 通常不共享                 |
| `FD_CLOEXEC` 等描述符标志                          | 各 FD 表项     | dup 的新表项不继承该关闭执行标志；fork 复制标志，之后各自改变  |
| 文件内容、大小等文件对象状态                       | 文件系统对象   | 多次 open 同一对象仍可观察同一内容；独立偏移不等于独立文件副本 |

`FD_CLOEXEC` 表示成功执行 exec 时关闭该描述符；需要原子设置时用适用的 `O_CLOEXEC` 或 `dup3(..., O_CLOEXEC)`，避免在多线程中先创建再设标志的竞态。需要按显式位置读取可考虑 `pread()`，避免把“lseek 后再 read”误当成跨调用的原子操作。

## 3. read 与 write 的返回量

`read()` / `write()` 的正返回值是本次实际处理字节数。想写 10 字节，第一次只返回 4，就从原缓冲第 4 字节偏移处继续写剩余 6 字节；从头重写会重复数据。短读短写不一概表示磁盘故障，可能与可用数据、信号或对象类型有关。[read(2)](https://man7.org/linux/man-pages/man2/read.2.html)、[write(2)](https://man7.org/linux/man-pages/man2/write.2.html)

对本章可定位普通文件，正长度 `read()` 返回 0 表示到达文件末尾（EOF，End Of File）；管道在所有写端关闭且剩余数据读尽后也返回 0。零长度请求本来就可能返回 0，不能把所有对象的 0 一律解释成永久结束。

下面是可以单独编译成目标文件的 C 辅助函数，**不含 main，不是完整可执行程序**。保存为 `write_all.c`，可用 `gcc -std=c11 -Wall -Wextra -Werror -c write_all.c` 检查。适用于按字节连续写入且调用方协调访问的场景，不直接覆盖数据报边界、直接 I/O 对齐和多写者记录原子性。

```c
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <limits.h>
#include <stddef.h>
#include <unistd.h>

/* Valid buf/done pointers; exclusive use of this byte stream while writing.
   Set *done to zero on entry; on failure it records positive write results. */
int write_all(int fd, const void *buf, size_t len, size_t *done)
{
    const unsigned char *p = buf;
    *done = 0;
    while (*done < len) {
        size_t left = len - *done;
        size_t chunk = left > (size_t)SSIZE_MAX ? (size_t)SSIZE_MAX : left;
        ssize_t n = write(fd, p + *done, chunk);
        if (n > 0) {
            *done += (size_t)n;
        } else if (n == 0) {
            errno = EIO;  /* No progress on a nonempty request. */
            return -1;
        } else if (errno != EINTR) {
            return -1;    /* Includes EAGAIN/EWOULDBLOCK; do not busy-loop. */
        }
    }
    return 0;
}
```

成功返回 0；失败返回 −1，`errno` 保留原因，`*done` 记录此前正返回值确认的字节量。`EINTR` 表示本次尚未写入而被信号打断，可重试；如果信号前已写入一部分，则按正返回量推进。非空请求返回 0 被当作无进展错误；`EAGAIN` / `EWOULDBLOCK` 立即交回调用者，等待可写事件或采取超时策略后再处理，不能忙等。永久错误也交给调用者。

若已确认写入 4 字节后遇错，这 4 字节不会自动撤销。不能无条件从头重新发布全部内容；部分完成量也不保证在直接 I/O 错误等特殊情况下完整描述底层修改。上述函数不自动回滚，也不承诺整个循环对并发写者原子。

## 4. 缓存、设备完成与持久化

| 接口          | 主要职责                                                       | 不能直接推出                                   |
| ------------- | -------------------------------------------------------------- | ---------------------------------------------- |
| `write()`     | 把返回值所示数量的字节写给该对象；普通缓存写可能先进入内核缓存 | 断电后必定恢复、整个请求已写完                 |
| `fdatasync()` | 同步数据及后续读取数据所必需的元数据，例如相关文件大小         | 所有非必要元数据都同步、目录项必定同步         |
| `fsync()`     | 同步文件数据和相关元数据，等待适用设备报告完成                 | 包含文件名的目录也已同步、任意故障模型绝对安全 |
| `close()`     | 关闭这个描述符引用，可能报告延迟错误                           | 等价于 fsync、其他引用关闭                     |

必须检查 `write`、同步和关闭的返回值；`fsync()` 可能报告写回错误。现代 Linux 的 `close()` 报错时不要盲目重试同一个整数 FD，以免它已经被释放并复用于别的打开操作；跨系统的细节要另查接口。文件系统、设备写缓存及其刷新能力共同决定实际保证。[fsync(2)](https://man7.org/linux/man-pages/man2/fsync.2.html)、[close(2)](https://man7.org/linux/man-pages/man2/close.2.html)

[![普通缓存文件写入、同步、设备完成与错误处理的分层示意](/assets/notes/operating-systems/os-file.png)](/assets/notes/operating-systems/os-file.png)

原 PNG 与同名 SVG 均保留。图只选取普通缓存文件的一条同步路径；出现的后台线程名称随内核版本变化，设备刷新命令也依协议与状态而定。图中强调 fsync 的位置，不意味着 `O_SYNC` 等其他同步写机制不存在，更不能把设备完成直接等同于应用事务完成。

### 把 config.json 完整发布出来

假设目标旧版本已经按要求持久化，目录可信、由本应用控制，单一发布者在同一目录创建临时文件。完整协议是：

1. 以唯一名字创建临时文件，设置适用权限；完整写入新内容并检查返回量。
2. 对临时文件执行 `fsync()` 并检查结果；随后检查关闭结果，失败则停止发布。
3. 在同一目录 `rename(temp, config.json)`，检查错误。目标原来存在时，适用语义下替换该名字，已有旧 FD 继续引用旧对象。
4. 对父目录 `fsync()` 并检查结果，把名字替换纳入适用持久化要求。跨目录的方案还需分析两边目录，不能直接省略为同步任意一个目录。

[![临时文件写入、文件同步、rename 发布和目录同步的条件化时序](/assets/notes/operating-systems/os-file-publish.svg)](/assets/notes/operating-systems/os-file-publish.svg)

原子可见性（Atomic Visibility）表示适用 rename 替换不会让按目标名字重新打开的读者看到“半个文件”或替换中的空缺；它可以看到旧对象或新对象。崩溃持久性（Crash Durability）讨论重启后内容和名字能否恢复，两者不是同一保证。[rename(2)](https://man7.org/linux/man-pages/man2/rename.2.html)

| 中断或失败位置               | 运行时已发生什么                       | 崩溃后的讨论边界                                                               |
| ---------------------------- | -------------------------------------- | ------------------------------------------------------------------------------ |
| 临时文件写到一半或文件同步前 | 尚未替换目标，旧名字仍在               | 临时内容不能视为持久；旧版本的保证依赖先前同步与文件系统条件                   |
| 文件 fsync 成功、rename 前   | 新文件内容完成适用同步，目标仍指旧对象 | 临时名字也未必已持久；恢复可检查残留文件，但不能假定一定存在                   |
| rename 成功、目录 fsync 前   | 目标已发布新对象                       | 不能承诺名字替换已持久；重启结果取决于具体文件系统与故障时点                   |
| 文件与目录同步均成功         | 内容和名字已按协议请求并完成同步       | 在文件系统及设备遵守相应承诺的条件下提供持久化保证，不是任意断电模型的绝对证明 |

跨文件系统 rename 通常报 `EXDEV`，不能改用“复制再删除”后仍声称相同原子语义。rename 前失败可在确认临时文件身份后清理或保留供排查；rename 后目录同步失败，**新版本可能已对读者可见而持久性未确认**，不能报告“旧版完全没动”，也不宜盲目反向 rename。并发发布者协调、原文件权限和其他元数据继承、重启时残留清理均须单独设计。

## 5. 文件系统日志不等于应用事务

假设先更新 `orders.json`，准备更新 `index.json` 前崩溃。文件系统日志可能让目录、inode 和分配信息恢复到自身规则允许的一致状态，但订单已是新版本、索引仍是旧版本，业务仍不一致。分别对两文件 fsync 也不会把两个独立发布操作变成一个事务。

一种教学性协议是写出不可变的同版本订单与索引文件，分别同步文件及需要的目录，再以一个提交指针发布该版本，并同步提交指针文件和目录。读者先读取一个提交版本，再使用对应的整组文件；旧版本清理也要协调读者。另一种思路是预写日志（WAL，Write-Ahead Log）：先记录可恢复的操作与提交信息，按协议同步后才能确认提交，恢复时重做或撤销。完整实现需要处理重放、校验、幂等和故障顺序，不在本章展开。[OSTEP：文件系统日志](https://pages.cs.wisc.edu/~remzi/OSTEP/file-journaling.pdf)

单文件原子替换、多文件业务原子性和文件系统内部一致性各有边界，不能把一次 rename 描述成任意多文件事务。

## 6. 专用临时目录中的两个实验

以下 Python 3 程序面向 Linux，只使用标准库，每次建立新的私有临时目录，保留实验文件便于核查，不覆盖用户配置。系统调用异常会使实验失败，不伪造成功；Python 的 os 接口对许多可重试信号中断已自动重试，底层 C 的 EINTR 分支见前文。

### 实验 A：共享与独立偏移

保存为 `offset.py`，运行 `python3 offset.py`：

```python
import os
import tempfile
from pathlib import Path

directory = Path(tempfile.mkdtemp(prefix="os-offset-"))
path = directory / "letters.txt"
# All writes are to this newly created private directory.
with path.open("xb") as stream:
    assert stream.write(b"ABCDEF") == 6

fds = []
try:
    first = os.open(path, os.O_RDONLY)
    fds.append(first)
    duplicate = os.dup(first)
    fds.append(duplicate)
    independent = os.open(path, os.O_RDONLY)
    fds.append(independent)
    for fd, expected, position in [(first, b"AB", 2),
                                   (duplicate, b"CD", 4),
                                   (first, b"EF", 6)]:
        data = os.read(fd, 2)
        assert data == expected
        assert os.lseek(first, 0, os.SEEK_CUR) == position
        assert os.lseek(duplicate, 0, os.SEEK_CUR) == position
        print(data.decode(), position)
    assert os.read(first, 2) == b""
    assert os.lseek(independent, 0, os.SEEK_CUR) == 0
    assert os.read(independent, 2) == b"AB"
    print("independent open: AB; shared EOF: PASS")
finally:
    # Try every close even if one reports an error; propagate the first error.
    error = None
    for fd in reversed(fds):
        try:
            os.close(fd)
        except OSError as exc:
            if error is None:
                error = exc
    if error is not None:
        raise error
print("test directory retained:", directory)
```

本轮实测固定部分为 `AB 2`、`CD 4`、`EF 6`，独立打开读到 AB，共享引用再次读取为 EOF。FD 数字与临时目录名随环境变化。

### 实验 B：文件同步与替换

保存为 `publish.py`，运行 `python3 publish.py`。使用 `os.replace()` 表达 POSIX rename 的覆盖替换语义，父目录通过 Linux 的 `O_DIRECTORY` 打开。失败时报告所在阶段并保留专用目录；不在异常分支自动回滚已发生的发布。

```python
import os
import tempfile
from pathlib import Path

def write_all(fd, data):
    position = 0
    while position < len(data):
        try:
            count = os.write(fd, data[position:])
        except InterruptedError:
            continue
        if count <= 0:
            raise OSError("write made no progress")
        position += count

directory = Path(tempfile.mkdtemp(prefix="os-publish-"))
target = directory / "config.json"
dirfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
stage = "prepare"
try:
    # Establish a synchronized old version in the private test directory.
    oldfd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        write_all(oldfd, b'{"version":1}\n')
        os.fsync(oldfd)
    finally:
        os.close(oldfd)
    os.fsync(dirfd)

    fd, name = tempfile.mkstemp(prefix=".config-", dir=directory)
    stage = "write temporary file"
    try:
        write_all(fd, b'{"version":2}\n')
        os.fsync(fd)
    finally:
        os.close(fd)
    stage = "rename"
    os.replace(name, target)   # Same-directory POSIX rename replacement.
    stage = "renamed; directory sync pending"
    os.fsync(dirfd)
    stage = "directory synced"
    assert target.read_bytes() == b'{"version":2}\n'
    print("write -> file fsync -> rename -> directory fsync: PASS")
except BaseException:
    print("failed stage:", stage, "inspect private directory:", directory)
    raise
finally:
    os.close(dirfd)
print("test directory retained:", directory)
```

本轮在 WSL2 的 Ubuntu 22.04、Linux 5.15、Python 3.10 环境运行，正常路径的写入、文件 fsync、rename、目录 fsync 及内容断言通过。目录同步不受支持或设备报错时应视为失败，不能忽略。实验没有断电、重启或注入真实设备故障，只验证这些调用在该环境完成，不证明所有崩溃恢复性质。

## 本章小结与联读

FD 引用打开状态，dup/fork 可共享偏移；read/write 要按实际返回量推进；完整文件发布还要区分文件内容同步、名字替换与目录同步。结合[上一章历史缓冲等待](/articles/os-buffer-io.html)理解分层完成，再到[第二十章现代页缓存](/articles/os-mmap-page-cache.html)看现代文件数据路径。

[返回本册目录](/collections/operating-systems/)
