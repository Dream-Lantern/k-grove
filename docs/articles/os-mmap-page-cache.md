---
id: os-mmap-page-cache
title: 第二十章 mmap、页缓存与 I/O 路径
description: "普通文件 I/O 与文件映射可以通过页缓存联系起来：read 把数据提供给用户缓冲，mmap 建立虚拟地址与后备对象的关系，后续访问再触发页面处理。"
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
order: 20
---

# 第二十章 mmap、页缓存与 I/O 路径

> 阅读标签：现代 Linux 普通缓冲文件 read/mmap/msync；不外推 Direct I/O、DAX 或任意设备映射。

服务读取或修改文件时，数据怎样进入程序？普通文件输入/输出（I/O，Input/Output）与文件映射可以通过页缓存（Page Cache）联系起来：read 把数据提供给用户缓冲，mmap 建立虚拟地址与后备对象的关系，后续访问再触发适用页面处理。沿地址、页表、缓存页、文件与存储的关系，才能区分读取、可见性与持久化。

## 1. read 的典型缓冲路径

固定一个 8 KiB 普通文件、4 KiB 页，文件系统支持普通文件映射；不用直接 I/O，也不使用直接访问（DAX，Direct Access）路径。应用准备至少 4096 字节用户缓冲，调用 `read(fd,buf,4096)`：

1. 内核按打开状态、偏移与访问条件定位文件数据，查询有关页缓存。
2. 已有有效缓存时复用数据；没有适用数据时可能分配缓存、经文件系统请求后备存储并等待，稀疏文件、预读等也会影响过程，不能断言每次 Miss 都读设备。
3. 把本次结果复制/提供给用户缓冲，按实际读取量推进适用文件偏移并返回字节数；短读和错误不能忽略。

[![普通缓冲 read 的数据复制与 mmap 通过页表引用缓存页的对照](/assets/notes/operating-systems/os-mmap.svg)](/assets/notes/operating-systems/os-mmap.svg)

数据缓存页与用户缓冲是不同角色。用户缓冲自身也受虚拟内存管理，可能另外缺页，不能以为 read 路径绝无页故障。预读、异步与具体文件系统改变细节，不是所有设备、网络存储或特殊映射都必经本图。[read(2)](https://man7.org/linux/man-pages/man2/read.2.html)、[Linux Page Cache](https://docs.kernel.org/mm/page_cache.html)

## 2. mmap 建立地址与后备对象的关系 {#_2-mmap-先建立什么}

考虑 `mmap(NULL,8192,PROT_READ,MAP_PRIVATE,fd,0)`：

| 参数              | 本例含义                                               |
| ----------------- | ------------------------------------------------------ |
| addr=NULL         | 让内核选择合适的进程虚拟地址，不预先指定固定地址       |
| length=8192       | 申请映射范围，不是立即读入字节数的保证                 |
| prot=PROT_READ    | 允许读取；本例不允许直接写                             |
| flags=MAP_PRIVATE | 文件私有映射；若要后续演示私有写，需合法的可写保护配置 |
| fd                | 文件描述符（FD，File Descriptor），应有相应访问能力    |
| offset=0          | 从文件开头建立关系，偏移需满足适用页对齐要求           |

调用成功返回起点，失败为 MAP_FAILED，不是简单用 NULL 判断。内核建立适用虚拟内存区域（VMA，Virtual Memory Area）；当程序访问地址时，若需要才经缺页处理取得缓存/后备数据、建立页表翻译，再通过地址访问页面。[mmap(2)](https://man7.org/linux/man-pages/man2/mmap.2.html)

| 阶段      | 虚拟映射                 | 实际页面与翻译                                                          |
| --------- | ------------------------ | ----------------------------------------------------------------------- |
| mmap 前   | 尚无本次范围             | 不对文件是否已缓存作假设                                                |
| mmap 成功 | 范围和后备关系已建立     | 普通按需模型不保证整份文件驻留或所有 PTE 已建立                         |
| 首次访问  | 范围仍在                 | 可能复用已有缓存，也可能等加载，建立适用页表项（PTE，Page Table Entry） |
| 再次访问  | 未被解除或破坏时继续有效 | 可复用页面/翻译；仍可能受回收与文件变化影响                             |

映射长度不等于常驻集大小（RSS，Resident Set Size）立即增加同样多。只触碰一小段大文件时尤其如此；预读、页尺寸和回收也影响驻留。关闭原 FD 不必然解除已经建立的映射；解除用适用的 munmap，不能把两者生命周期混为一谈。

| 对比项           | read                           | mmap                                                          |
| ---------------- | ------------------------------ | ------------------------------------------------------------- |
| 用户访问形式     | 系统调用给用户缓冲提供字节     | 建映射后以地址加载/存储                                       |
| 页缓存           | 本章普通缓冲路径复用页缓存     | 本章文件映射也可联系同一文件的缓存页                          |
| 独立用户缓冲复制 | 通常有缓存到用户缓冲的复制     | 可减少这次独立复制；程序仍可能自己复制数据                    |
| 缺页成本         | 用户缓冲、运行代码等仍可能缺页 | 映射访问可能触发按需映射与文件页故障                          |
| 系统调用         | 每批读取调用，粒度可设计       | 初始 mmap、生命周期与同步调用；不是每次普通加载都显式 syscall |
| 设备 I/O         | 取决于缓存、后备和文件系统     | 同样不保证免设备 I/O                                          |
| 生命周期         | 缓冲由应用管理，FD 有打开状态  | 映射、FD、文件大小和并发变化要共同管理                        |

匿名映射没有本例文件内容来源，可能按需零填充、写时复制或交换，不应统一画成“文件页缓存 → 读盘”。[缺页与匿名页联读](/articles/os-page-faults.html)

## 3. MAP_PRIVATE 与 MAP_SHARED

从文件前八字节 `ABCDEFGH` 出发，以下两例分别建立映射，不在同一时刻混用旧私有视图来推导额外保证：

| 映射                | 动作                        | 当前映射看到 | 对底层文件的作用                                          |
| ------------------- | --------------------------- | ------------ | --------------------------------------------------------- |
| MAP_PRIVATE、允许写 | 首字节 A 改 X               | XBCDEFGH     | 该私有修改不回写，文件仍 ABCDEFGH                         |
| MAP_SHARED、允许写  | 在未改原文件的基础上 A 改 Y | YBCDEFGH     | 共享更新影响适用文件数据，其他适用共享映射/普通读取可观察 |

[![私有 X 修改形成私有页而文件不变，共享 Y 修改进入适用文件缓存](/assets/notes/operating-systems/os-mmap-modes.svg)](/assets/notes/operating-systems/os-mmap-modes.svg)

私有写按适用写时复制（COW，Copy-On-Write）语义处理，不是多进程共享写机制；但不能将 MAP_PRIVATE 描述为文件永远不再变化的快照。文件在映射后被其他方式改动，其对私有映射的可见性有接口规定的未指定边界，fork 又可能继承私有内容。共享可见性也不等于此刻已经断电持久化，复合更新不自动成为事务。

### 普通文件的同步与映射生命周期

普通文件 MAP_SHARED 映射的写入可使相应文件缓存内容变脏；写回可以由后台发生，也可以按应用需要请求同步。

```text
建立共享映射 → 修改数据 / 形成脏页 → 请求 msync(MS_SYNC)
→ 等待适用同步完成并检查结果 → 按需要 munmap → close
```

[![共享映射的数据可见性、脏页、msync 同步、写回和解除映射时序](/assets/notes/operating-systems/os-mmap-sync.svg)](/assets/notes/operating-systems/os-mmap-sync.svg)

`MS_SYNC` 请求同步指定映射范围并等待完成；`MS_ASYNC` 的接口语义是安排同步后立即返回。**Linux 自 2.6.19 起 MS_ASYNC 实际为 no-op**，因为内核已经跟踪脏页并按需写回；它不提供 MS_SYNC 的等待保证。可移植程序仍应明确选择适用标志。[msync(2)](https://man7.org/linux/man-pages/man2/msync.2.html)

msync 地址须满足适用页对齐条件，返回 −1 时检查 errno 并处理，不能继续报告“已同步”。解除映射、close 和一次正常读取都不能替代应用的完整持久化协议；后台写回也不等于应用已确认完成。同步保证仍有文件系统、存储设备及错误处理边界，本例不覆盖任意设备映射/DAX。

文件数据可见、脏页已写回、同步成功、文件名已发布并持久、业务原子更新，是不同问题。目录项持久化需结合[第十二章 fsync/rename](/articles/os-file-descriptors-persistence.html)的协议，msync 不保证多字段或多文件事务。

### 文件末页、截断与 SIGBUS

纸面例子：4 KiB 页下文件长 5000 字节，映射 12288 字节。文件末页位于偏移 4096～8191，末尾不足页的部分有零填充等适用规则；不能说文件大小之外每个字节都必然立刻报错。完全位于文件末尾之外的页，如从偏移 8192 开始的页，访问可触发总线错误信号 SIGBUS。映射期间并发截断还会破坏先前的数据范围假设，需协作保护生命周期。本章不运行崩溃演示。

## 4. mmap 的复制减少与其他成本 {#_4-mmap-为什么不是免费零拷贝}

讨论零拷贝（Zero-Copy）必须说明减少哪次复制。在本章典型普通文件模型中，mmap 可让程序通过页表引用相应缓存页，减少 read 将缓存内容复制到独立用户缓冲的那一段；不表示设备没有传输、文件数据没有经过内存，或应用之后不再复制。

仍有缺页、分配/回收、页表、翻译后备缓冲（TLB，Translation Lookaside Buffer）、同步与映射生命周期成本；设备直接内存访问（DMA，Direct Memory Access）等传输路径也不能凭“零拷贝”三字忽略。收益受文件大小、访问模式、冷热缓存、内存压力和硬件影响；没有基准数据，不能宣称 mmap 总比 read 快或给出虚构收益。

## 5. 映射不等于应用事务

假设映射含 `balance` 和 `version`：应用先修改 balance，再修改 version，其他执行者可能在两次写之间观察到“新 balance、旧 version”。MAP_SHARED 不自动让两次更新原子，msync 也不是互斥锁、并发内存同步协议或崩溃恢复事务。

需要按应用要求使用适用的进程间锁、原子/版本发布协议、日志或其他一致性机制；进程共享同步对象还要满足它们自己的初始化和内存模型规则，不能用普通变量忙等替代。页与磁盘块也属于不同层次，经具体文件系统和 I/O 路径联系，不能只画“写一个字节就立即写一个磁盘块”。

## 6. 专用临时目录中的 C 实验

保存为 `mmap-demo.c`，运行 `gcc -std=c11 -Wall -Wextra -Werror mmap-demo.c -o mmap-demo`，然后 `./mmap-demo`。程序用 mkdtemp 新建私有目录，用排他创建建立测试文件，文件长 8192、前缀 ABCDEFGH；先测私有 X、解除私有映射，再测共享 Y、MS_SYNC、清理自己创建的文件和目录。没有覆盖用户文件。

```c
#define _POSIX_C_SOURCE 200809L
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

static int write_initial(int fd)
{
    const char text[] = "ABCDEFGH";
    size_t done = 0;
    while (done < 8) {
        ssize_t n = write(fd, text + done, 8 - done);
        if (n > 0) done += (size_t)n;
        else if (n == -1 && errno == EINTR) continue;
        else { if (n == 0) errno = EIO; return -1; }
    }
    return ftruncate(fd, 8192);
}

static int prefix(int fd, char out[9], const char expected[9])
{
    if (lseek(fd, 0, SEEK_SET) == -1) return -1;
    size_t done = 0;
    while (done < 8) {
        ssize_t n = read(fd, out + done, 8 - done);
        if (n > 0) done += (size_t)n;
        else if (n == -1 && errno == EINTR) continue;
        else { if (n == 0) errno = EIO; return -1; }
    }
    out[8] = '\0';
    if (memcmp(out, expected, 8) != 0) { errno = EIO; return -1; }
    return 0;
}

int main(void)
{
    char directory[] = "/tmp/os-mmap-XXXXXX";
    if (mkdtemp(directory) == NULL) { perror("mkdtemp"); return EXIT_FAILURE; }
    int dirfd = -1, fd = -1, created = 0, result = EXIT_FAILURE;
    char *view = MAP_FAILED, bytes[9];
    dirfd = open(directory, O_RDONLY | O_DIRECTORY | O_CLOEXEC);
    if (dirfd == -1) { perror("open directory"); goto cleanup; }
    fd = openat(dirfd, "data.bin", O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd == -1) { perror("openat"); goto cleanup; }
    created = 1;
    if (write_initial(fd) == -1) { perror("initialize"); goto cleanup; }
    view = mmap(NULL, 8192, PROT_READ | PROT_WRITE, MAP_PRIVATE, fd, 0);
    if (view == MAP_FAILED) { perror("mmap private"); goto cleanup; }
    view[0] = 'X';
    if (prefix(fd, bytes, "ABCDEFGH") == -1) { perror("private check"); goto cleanup; }
    printf("private=%.8s; file=%s\n", view, bytes);
    if (munmap(view, 8192) == -1) { perror("munmap private"); goto cleanup; }
    view = MAP_FAILED;

    view = mmap(NULL, 8192, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    if (view == MAP_FAILED) { perror("mmap shared"); goto cleanup; }
    view[0] = 'Y';
    if (prefix(fd, bytes, "YBCDEFGH") == -1) { perror("shared visibility"); goto cleanup; }
    printf("shared before msync: file=%s\n", bytes);
    if (msync(view, 8192, MS_SYNC) == -1) { perror("msync"); goto cleanup; }
    if (prefix(fd, bytes, "YBCDEFGH") == -1) { perror("sync check"); goto cleanup; }
    printf("after MS_SYNC: file=%s\n", bytes);
    result = EXIT_SUCCESS;
cleanup:
    if (view != MAP_FAILED && munmap(view, 8192) == -1) {
        perror("munmap cleanup"); result = EXIT_FAILURE;
    }
    if (fd != -1 && close(fd) == -1) { perror("close file"); result = EXIT_FAILURE; }
    if (created && unlinkat(dirfd, "data.bin", 0) == -1) {
        perror("unlinkat test file"); result = EXIT_FAILURE;
    }
    if (dirfd != -1 && close(dirfd) == -1) { perror("close directory"); result = EXIT_FAILURE; }
    if (rmdir(directory) == -1) { perror("rmdir test directory"); result = EXIT_FAILURE; }
    if (fflush(stdout) == EOF || ferror(stdout)) result = EXIT_FAILURE;
    return result;
}
```

本轮在 WSL2/Linux 编译运行成功，实际输出为 `private=XBCDEFGH; file=ABCDEFGH`、`shared before msync: file=YBCDEFGH`、`after MS_SYNC: file=YBCDEFGH`。这展示当前环境的可见性及调用完成，不证明真实断电恢复保证；实验不清缓存、不截断正在访问的映射，也不测性能。

## 联读

历史对照见[Linux0.11 bread与显式等待](/articles/os-buffer-io.html)；这里以普通文件现代接口为主。结合[第十九章回收](/articles/os-page-replacement-swap.html)理解缓存为何不必永久驻留，再到[第二十一章诊断](/articles/os-troubleshooting.html)观察内存与 I/O 对请求延迟的影响。

[返回本册目录](/collections/operating-systems/)
