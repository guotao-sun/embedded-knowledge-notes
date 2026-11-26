# Linux 启动代码：从 stext 到 start_kernel

## 一、先说结论

- 内核有**两个入口**：先跑自解压代码 `arch/arm/boot/compressed/head.S`，解压完跳到真正的入口 `arch/arm/kernel/head.S` 的 `stext`。
- `stext` 做完最要紧的一件事——建页表、开 MMU——之后跳进 `start_kernel()`（`init/main.c`），从此全在内核虚拟地址里跑。
- `start_kernel` 一条龙初始化各子系统，最后调 `rest_init()`：**造出 PID 1 和 PID 2 两个内核线程，自己则退化成 PID 0（idle）**。

所以"Linux 的入口函数是 `start_kernel`"这句话要加个限定：它是**通用内核的 C 入口**，在它之前还有一段和架构绑死的汇编与自解压。

## 二、进 start_kernel 之前发生了什么

| 步骤 | 动作 | 位置 |
|---|---|---|
| 1 | Bootloader 把 zImage/Image 放到内存，跳转 | U-Boot |
| 2 | 自解压：把内核从压缩镜像解开到运行地址 | `arch/arm/boot/compressed/head.S` |
| 3 | 真正的 `stext`：校验 CPU 类型、建立页表、开 MMU、清 BSS | `arch/arm/kernel/head.S` |
| 4 | 跳转 `start_kernel()` | `init/main.c` |

`stext` 进来时寄存器已有约定：r0 = 0，r1 = 机器号（老式做法），r2 = 设备树地址。第 3 步的页表只是"能让内核跑起来"的一版粗页表，后面 `setup_arch` 会换成正式的内存模型。

## 三、start_kernel 里的初始化顺序

| 阶段 | 内容 | 为什么排在这 |
|---|---|---|
| **极早期** | lockdep、栈保护 canary、本地中断关闭、`boot_cpu_init` | 先能"安全地报错"，再谈别的 |
| **架构相关** | `setup_arch`：解析设备树、确定内存布局、初始化页表与 memblock | 后面所有子系统都要申请内存，必须先知道内存长什么样 |
| **内存管理** | 分阶段完成：zonelists → `mm_init` → `kmem_cache_init_late` | 伙伴系统、slab、vmalloc 都要依次可用 |
| **中断与计时** | `trap_init`、`init_IRQ`、时钟与定时器初始化，最后开中断 | 中断开早了，处理函数还没注册好会崩 |
| **调度器** | `sched_init`，`preempt_disable` | 有进程模型之后才能谈调度 |
| **内核子系统** | PID、VFS、cgroup、namespace、proc、security 等 | 依赖内存与调度 |
| **收尾** | `rest_init()` 创建 PID 1、PID 2，当前执行流进入 idle | 内核自身初始化完成，转交用户空间 |

顺序不是随便排的，本质是一条**依赖链**：能报错 → 知道内存 → 有内存分配器 → 有中断与时间 → 有调度 → 建子系统 → 交棒用户态。

## 四、rest_init：三个"特殊进程"在这一步分家

`rest_init()` 干的事可以概括成三句：

```c
/* 造 PID 1：将来 execve 成用户态 init */
kernel_thread(kernel_init, NULL, CLONE_FS);
/* 造 PID 2：内核线程之母 */
kernel_thread(kthreadd, NULL, CLONE_FS | CLONE_FILES);
/* 自己变成 PID 0：进 idle 循环，没事就 hlt */
cpu_startup_entry(CPUHP_ONLINE);
```

> 除了 PID 0、1、2 这三个"固定编号"的特殊进程，Linux 里没有别的固定 PID。

## 五、PID 0：idle 进程（swapper）

- **本质**：一个内核线程，通常称为 **idle** 或 **swapper**。
- **何时运行**：CPU 没有任何其他可运行任务时切到它，它执行"停机"指令（如 `hlt`）降功耗，等下一个中断把它叫醒。
- **怎么来的**：引导 CPU 从 `start_kernel` → `rest_init` → idle 循环，就地变成 idle。多核系统里每个 CPU 都有自己的 idle 线程，但**只有引导 CPU 的那个 PID 为 0**，其他是 `fork_idle` 出来的，PID 是动态分配的。
- **其他作用**：SMP 下 CPU 热插拔时作为初始线程。

简单理解：PID 0 是"CPU 空闲时的占位进程"，保证任何时候都有一个东西在跑。

## 六、PID 1：init 进程

- **本质**：第一个**用户态**进程，所有用户进程的祖先。
- **怎么来的**：`rest_init` 里 `kernel_thread(kernel_init, ...)` 造出来的。它起初是内核线程，很快通过 `execve` 加载用户空间 init 程序（`/sbin/init`、`/usr/lib/systemd/systemd` 等）。
- **主要职责**：
  - 初始化系统：挂载文件系统、配置网络、启动服务（cron、sshd、getty 等）
  - 切换运行级别（SysV init 风格）
  - **收养孤儿进程**：父进程终止的子进程都归它收养，由它 `wait()` 收尸，避免僵尸进程堆积
  - 处理 SIGINT、SIGTERM 等信号，实现重启与关机
- **危险点**：PID 1 意外退出，内核直接 panic——用户空间的"根"没了。

简单理解：PID 1 是系统总管，启动所有用户进程，并照顾"无父进程"的孤儿。

## 七、PID 2：kthreadd

- **本质**：一个内核线程，专门**创建其他内核线程**。
- **怎么来的**：`rest_init` 里紧跟在 PID 1 之后 `kernel_thread(kthreadd, ...)`；而 PID 1 开跑前会先等它就绪（`wait_for_completion(&kthreadd_done)`），所以实际干活顺序是 kthreadd 先准备好。
- **工作机制**：别的内核模块要造线程，不直接 `do_fork`，而是用 `kthread_create` / `kthread_run` 向 kthreadd 提请求，由它统一创建。集中管理，避免各处自己搞同步。
- **怎么看**：`ps -ef` 或 `pstree` 里的 `[kthreadd]`。

简单理解：PID 2 是内核线程的母亲，`ksoftirqd`、`kworker`、`kswapd` 这些都由它生出来。

## 八、三者关系

### 启动顺序

```text
PID 0（idle）先存在
    ↓
rest_init() 创建 PID 2（kthreadd）和 PID 1（init）
    ↓
PID 2 再创建其他内核线程
    ↓
PID 1 启动用户空间
```

### 生命周期与地址空间

- PID 0、PID 2 永远运行（除非关机）；PID 1 一直运行到关机/重启。
- PID 0、PID 2 都是内核线程，共享内核地址空间，没有用户空间内存；PID 1 有完整的用户态地址空间。

## 九、其他核心内核线程

内核里还有一批没有固定 PID、但很关键的线程：

| 线程 | 作用 |
|---|---|
| `ksoftirqd/N` | 处理软中断（softirq），如网络收包、定时器软中断 |
| `kworker/N` | 执行工作队列（workqueue）里的任务 |
| `migration/N` | SMP 下在 CPU 间迁移任务，支撑负载均衡 |
| `rcu_sched` 等 | 实现 RCU（Read-Copy-Update） |
| `kswapd` | 页面回收，内存紧张时唤醒 |
| `kdevtmpfs` | 管理 `/dev` 下设备节点的动态创建与删除 |
| `khugepaged` | 透明大页（THP）的后台整理 |
| `jbd2/sda1-8` | ext4 等日志文件系统的日志线程 |

这些线程的 PID 都是创建时动态分配的（通常从几十开始），所以**不要用 PID 号去认它们**，认名字。

## 十、自己动手看一遍

```bash
ps -ef | head          # PID 0/1/2 和一堆 [kthreadd] 的子线程
pstree -p 1 | head     # 用户空间的进程树从 PID 1 展开
cat /proc/1/comm       # init 到底 exec 成了谁
ls /proc/0             # 看不到：PID 0 不在 /proc 里
```

最后一条是个常见误解：**PID 0 没有 `/proc` 条目**，因为它不是普通进程，也不会被信号杀掉。

## 十一、一句话总结

`stext` 解决"能跑"，`start_kernel` 解决"能用"，`rest_init` 解决"谁接着跑"——内核把自己的初始化收尾，同时造出 PID 1 去接管用户空间，自己退成 PID 0 待命。
