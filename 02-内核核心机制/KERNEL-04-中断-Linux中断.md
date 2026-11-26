# Linux 中断：上半部、GIC 与完整调用链

## 一、先说结论

- 中断处理被切成两段：**上半部**只做"最急、最短"的事（清标志、把数据搬进内存），**下半部**做耗时的处理。目的只有一个：让中断函数快进快出。
- 在 CPU 眼里，所有外设中断都是**同一个 IRQ 信号**；进内核后才靠 GIC 读出的中断号 + `irq_domain` 映射，分发到某个驱动注册的函数。
- 所以"中断号"有两套：硬件号（hwirq）和内核号（virq），中间那层映射是设备树的 `interrupt-parent` / `interrupts` 在起作用。
- 中断上下文里**不能睡眠**。凡是"要等、要阻塞"的活，都得挪到下半部或线程化中断里去。
- EOI 和 CPU 的 IRQ 掩码是两件事：EOI 写完不代表 CPU 开门，退出路径上唯一能被打断的窗口在软中断执行期间。

## 二、为什么要分上半部与下半部

有些资料把上半部/下半部叫**顶半部/底半部**，是同一个意思。

用 `request_irq` 注册的中断服务函数属于**上半部**：只要中断触发，它就会执行。而它必须短，因为这段时间里同级中断（甚至所有中断）是被关掉的，拖久了整机响应都受影响。

但有些活天生费时间。**举例**：电容触摸屏用中断通知 SoC"有触摸事件"，SoC 响应中断后要通过 I2C 读坐标，而 I2C 最高才 400 Kbit/s，在中断里读几十个字节就是几百微秒。做法是：中断函数只做"响应中断、清标志位"，I2C 读取推到下半部去做。

于是处理被拆成两半：

- **上半部**：时间敏感、不能等、不能睡的活（读状态寄存器、清中断标志、拷贝数据到内存、唤醒下半部）
- **下半部**：能等、耗时的活（解析数据、走协议栈、上报事件）

> 哪些代码归上半部、哪些归下半部，内核没有硬性规定，按实际情况判断：判断依据就两条——**这段代码能不能等？关中断期间跑它值不值？**

## 三、下半部的三种实现

下半部不是一种机制，是一类机制的统称。常用的三件套差别很大：

| | softirq | tasklet | workqueue |
|---|---|---|---|
| 运行上下文 | 软中断（中断上下文） | 软中断（中断上下文） | 内核线程（进程上下文） |
| 能否睡眠 | 不能 | 不能 | **能** |
| 并发性 | 同一类型可在多 CPU 并行 | 同一 tasklet 串行 | 由工作队列线程调度 |
| 由谁触发 | 内核静态注册（网络、定时器等） | 驱动动态创建 | 驱动动态创建 |
| 典型用途 | 网络收包、定时器 | 简单延后处理 | 需要睡眠/耗时长的活 |

再补一个现代做法：**线程化中断**（`request_threaded_irq`）。上半部只判断"是不是我的中断"，然后返回 `IRQ_WAKE_THREAD`，真正的处理函数跑在一个内核线程里——**可以睡眠**，能直接在里面做 I2C/SPI 传输。RK3568 这类平台上，I2C、SPI 控制器驱动大量使用这种方式。

选择顺序大致是：

```text
能在上半部 3 行代码搞定 → 就放上半部
需要一点延后、不需要睡 → tasklet
需要睡眠、要访问 I2C/SPI/文件 → workqueue 或线程化中断
```

## 四、GIC：ARM 的"总机"

### 4.1 GPIO 中断控制器只是汇总吗

大方向对，但"只是汇总"不准确。GPIO 中断控制器除了汇总多路 GPIO 中断，还负责**检测方式（电平/边沿）、触发配置、屏蔽与状态管理**；它不负责这些中断的"业务含义"。

外设和 CPU 之间通常只有一两根中断线，可外设内部却有一堆中断源。比如 DMA 有很多通路，任一通路传输完成都汇总成"一个 DMA 中断"报给 CPU；CPU 上的 DMA 中断处理函数再去读 DMA 的状态寄存器，判断这次是谁触发的。

### 4.2 级联中断控制器

任何"能管理多个中断源、并向上级产生一个中断"的硬件模块，都可以被抽象成 `interrupt-controller`：

- GIC / NVIC：CPU 级中断控制器
- GPIO / EXTI：二级（级联）中断控制器

Linux 里的 `interrupt-controller` **不一定**是最终连 CPU 的那个，只要它能管一组中断源，就能这么抽象。

```text
                 CPU
                   |
                 GIC
                   |
          ------------------
          |                |
    GPIO IRQ         PCIe IRQ
          |
     ----------------
     |       |       |
   GPIO0  GPIO1   GPIO2
```

### 4.3 GIC 的版本

GIC 是 ARM 给 Cortex-A/R 的中断控制器，地位相当于 Cortex-M 里的 NVIC。

| 版本 | 适用架构 | 典型内核 |
|---|---|---|
| V1 | 最老，已废弃 | — |
| V2 | ARMv7-A（32 位） | Cortex-A7、A9、A15 |
| V3/V4 | ARMv8-A/R（64 位） | Cortex-A55 等 |

RK3568 是 Cortex-A55（ARMv8），硬件上是 GIC V3；但 GIC V2 的模型最简单，很多教材拿它入门。V2 最多支持 8 个核，ARM 对应售卖的 IP 核叫 GIC400。

### 4.4 只给 CPU 四根线

GIC 收到外部中断后要报给 CPU，但 ARM 只给了四个信号：

| 信号 | 含义 |
|---|---|
| VFIQ | 虚拟 FIQ（虚拟化用） |
| VIRQ | 虚拟 IRQ（虚拟化用） |
| FIQ | 快速中断 |
| IRQ | 普通外部中断 |

不谈虚拟化就只剩 FIQ 和 IRQ，日常驱动用的全是 IRQ——**所以 GIC 管理的上千个中断，最终都压成同一个 IRQ 信号送进 CPU**。

### 4.5 中断号怎么分区

GIC V2 的硬件中断号（hwirq）分区是固定的：

| 号段 | 类型 | 说明 |
|---|---|---|
| 0–15 | SGI | 软件触发中断，用于多核间 IPI（核间通知） |
| 16–31 | PPI | 每个 CPU 私有的中断（如本地定时器） |
| 32–1019 | SPI | 外设共享中断，GPIO、I2C、SPI 都在这里 |

这解释了源码里那句 `if (irqnr < 16) { ... handle_IPI(...) }`：小于 16 的不是外设中断，而是核间消息。

## 五、从硬件到驱动函数：完整路径

```text
【硬件】
外设拉中断线 → GIC 记录 → 向 CPU 拉高 IRQ
    ↓
【汇编层】arch/arm/kernel/entry-armv.S
vector_irq → __irq_svc（软件保存现场）→ irq_handler
    ↓
【架构层】drivers/irqchip/irq-gic.c
handle_arch_irq（函数指针）→ gic_handle_irq
    读 GIC_CPU_INTACK 拿到 hwirq
    ↓
【通用 IRQ 框架】kernel/irq/
__handle_domain_irq → irq_find_mapping(hwirq → virq) → generic_handle_irq
    ↓
irq_desc[virq] → handle_level_irq / handle_edge_irq（按触发类型选择）
    ↓
handle_irq_event  ← 核心：遍历 action 链表
    ↓
【驱动层】
action->handler()   ← request_irq 注册的那个函数
```

两个值得记住的细节：

- **共享中断靠链表**：`irq_desc` 里挂一条 `action` 链表，多个驱动可以注册同一个 virq（如老式 PCI 共享中断），`handle_irq_event` 挨个调用，每个 handler 必须自己判断"这次是不是我的中断"，不是就返回 `IRQ_NONE`。
- **FIQ 走另一条路**：`vector_fiq`，ARM 设计上它有更多 banked 寄存器（r8–r12），切换开销小，留给对实时性要求极高的外设。日常驱动一律走 IRQ。

## 六、三个关键函数

```c
/* 通用入口：把 hwirq 翻译成 virq，再分发 */
int __handle_domain_irq(struct irq_domain *domain, unsigned int hwirq,
                        bool lookup, struct pt_regs *regs)
{
    struct pt_regs *old_regs = set_irq_regs(regs);
    unsigned int irq = hwirq;
    int ret = 0;

    irq_enter();                       /* 进入硬中断上下文，preempt_count++ */

#ifdef CONFIG_IRQ_DOMAIN
    if (lookup)
        irq = irq_find_mapping(domain, hwirq);   /* 查 irq_domain 映射表 */
#endif

    if (unlikely(!irq || irq >= nr_irqs)) {
        ack_bad_irq(irq);              /* 硬件给出了错误的中断号 */
        ret = -EINVAL;
    } else {
        generic_handle_irq(irq);       /* 进入 irq_desc 分发 */
    }

    irq_exit();
    set_irq_regs(old_regs);
    return ret;
}
```

```c
/* 退出中断：这里是"下半部"真正被触发的地方 */
void irq_exit(void)
{
    ...
    account_irq_exit_time(current);
    preempt_count_sub(HARDIRQ_OFFSET);           /* 离开硬中断上下文 */
    if (!in_interrupt() && local_softirq_pending())
        invoke_softirq();                         /* 有软中断待处理就现在做 */

    tick_irq_exit();
    rcu_irq_exit();
    trace_hardirq_exit(); /* must be last! */
}
```

一句话概括这三个函数的分工：`__handle_domain_irq` **翻译**（hwirq→virq）、`generic_handle_irq` **分发**（找到 irq_desc 和对应的 flow handler）、`handle_irq_event` **执行**（挨个调用 action）。`irq_exit` 则顺手在这里把软中断（下半部）跑掉。

## 七、中断退出路径上，还能被打断吗

常见误解：EOI 已经写了，硬件那头"复位"了，是不是就随时可能被新中断插进来？

答案要分**两个开关**看：

| 开关 | 谁控制 | 作用 |
|---|---|---|
| EOI（End Of Interrupt） | GIC | 宣告"这一路处理完"，该中断号才允许再次上报 |
| CPSR.I（中断掩码位） | CPU | 决定 CPU 此刻收不收中断信号 |

两者完全独立：**EOI 写完了，不代表 CPU 开门。**

### 7.1 EOI 是什么时候写的

```c
/* kernel/irq/chip.c（简化示意，省略了判错与 oneshot 分支） */
void handle_fasteoi_irq(struct irq_desc *desc)
{
    struct irq_chip *chip = desc->irq_data.chip;

    ...
    handle_irq_event(desc);              /* 先跑你的 handler */

    ...
    chip->irq_eoi(&desc->irq_data);      /* 再告诉 GIC：这一路结案 */
}
```

顺序是**先处理、后 EOI**。所以在 handler 执行期间，这个中断号在 GIC 里处于 active 状态，同源中断不会被再次转发——这也是"handler 里没及时清标志，中断看起来丢了"的由来。

> 不同 flow handler 顺序略有差异（`handle_level_irq` 是"先 mask → 处理 → 再 unmask"），但"处理完才允许同源再来"这个原则一致。

### 7.2 但 CPU 还闭着中断门

ARMv7 的入口代码，进来第一件事就是关 IRQ：

```asm
/* arch/arm/kernel/entry-armv.S（摘录） */
    .macro  svc_entry, stack_hole=0, trace=1
    ...
    disable_irq                 @ cpsid i：整个内核处理期间 IRQ 不响
    ...
    .endm
```

`irq_exit()` 里也仍然是关着的：

```c
void irq_exit(void)
{
#ifndef __ARCH_IRQ_EXIT_IRQS_DISABLED
    local_irq_disable();                       /* 确保 IRQ 关闭 */
#endif
    account_irq_exit_time(current);
    preempt_count_sub(HARDIRQ_OFFSET);         /* 硬中断计数 -1 */
    if (!in_interrupt() && local_softirq_pending())
        invoke_softirq();                      /* 走到这一步才动下半部 */
    ...
}
```

于是从 EOI 到 `invoke_softirq()` 之间，新来的中断只能在 GIC 里挂着（pending），进不来。

### 7.3 软中断那段是开着中断跑的

```c
/* kernel/softirq.c（简化示意） */
asmlinkage __visible void __softirq_entry __do_softirq(void)
{
    ...
    pending = local_softirq_pending();

    __local_bh_disable_ip(_RET_IP_, SOFTIRQ_OFFSET);  /* 关下半部，硬中断不受影响 */
    ...
    set_softirq_pending(0);
    local_irq_enable();                     /* ★ 硬中断在这里重新开门 */
    h = softirq_vec;
    while ((softirq_bit = ffs(pending))) {
        ...
        h->action(h);                       /* 软中断处理函数：可以被硬中断打断 */
        ...
    }
    local_irq_disable();                    /* 收尾再关上 */
    ...
}
```

这解释了那个看着矛盾的结论：**软中断仍然不能睡（没有进程上下文），但可以被硬中断打断（中断门开着）。**

### 7.4 时间线

| 阶段 | GIC 状态 | CPU 掩码 | 新中断会被响应吗 |
|---|---|---|---|
| 你的 handler 执行中 | 未 EOI（active） | 关 | 否，同源根本不上报 |
| EOI 写完，`irq_exit()` 里 | 已 EOI，可 pending | **仍关** | 否，只能挂着 |
| `__do_softirq()` 执行中 | 可 pending | **开** | **是，立即打断** |
| 软中断跑完，`local_irq_disable()` | — | 关 | 否 |
| `iret`（从 SPSR 恢复 CPSR） | — | 开 | 是，回到被打断代码的原始状态 |

### 7.5 嵌套能套多深

- 硬中断 handler 内部 IRQ 是关的 → 普通 IRQ **只会在软中断之上套一层**，不会无限递归
- 还能继续插进来的只有 **FIQ / NMI** 这类不可屏蔽中断
- 所以 `preempt_count` 用一个计数就够了，而不是维护任意深度的嵌套栈

### 7.6 为什么这么设计

| 设计 | 好处 | 代价 |
|---|---|---|
| 硬中断不嵌套 | 内核栈深度可控，共享数据只需考虑"中断 vs 进程"两种上下文 | 高优先级中断也得等前一个 handler 跑完 |
| 软中断开着中断跑 | 收尾工作不会把整机中断响应堵死，tick、网络、串口还能进来 | 软中断 handler 必须自己防"被硬中断打断" |

所以软中断里操作共享数据，标准做法是 per-CPU 变量，或 `local_bh_disable()`——**关下半部不等于关硬中断**，这两件事别混。

### 7.7 preempt_count 是怎么记这笔账的

| 位段 | 谁 +1 |
|---|---|
| HARDIRQ | `irq_enter()` |
| SOFTIRQ | `__local_bh_disable()` / 执行软中断 |
| NMI | 进不可屏蔽中断 |
| PREEMPT | `preempt_disable()`（关抢占的临界区） |

`in_interrupt()` 的含义就是"前三个里任意一个非零"。所以 `irq_exit()` 里减完 HARDIRQ 才变假、进 `__do_softirq()` 又加 SOFTIRQ 变真——计数在来回跳，**但"在中断上下文"这个事实一直没断**。

### 7.8 一句话记

**EOI 管"控制器能不能再报"，CPSR.I 管"CPU 收不收"；退出路径上唯一开着门的窗口，是 `__do_softirq()` 里 `local_irq_enable()` 到 `local_irq_disable()` 之间。**

## 八、disable_irq 的坑

| API | 行为 | 什么时候用 |
|---|---|---|
| `disable_irq()` | 关闭中断，并**等正在执行的 handler 跑完**才返回 | 进程上下文，要确保 handler 不再访问资源时 |
| `disable_irq_nosync()` | 关闭后立即返回，不等 | **中断上下文**里，或明确不需要等 |

在中断处理函数里调 `disable_irq()` 是经典死锁：当前 handler 还没返回，而 `disable_irq` 就在等"当前 handler 结束"——互相等，永远不结束。这种情况只能用 `disable_irq_nosync()`。

那 `disable_irq()` 的"等待"有什么意义？两个真实场景：

- **多核**：CPU0 正在 handler 里操作网卡资源，CPU1 想关中断并释放这块资源。不等的话，CPU0 可能在释放后继续访问，直接崩。
- **卸载驱动**：`free_irq` 之前必须确保没有 handler 还在跑，否则访问的是已经被释放的内存。

`disable_irq_nosync()` 只是关掉"开关"，不释放任何资源；资源一直留到 `free_irq()`。

## 九、中断上下文里不能做的事

| 不能做 | 原因 | 替代 |
|---|---|---|
| `msleep`、`mutex_lock`、等信号量 | 中断上下文没有"进程"可调度，睡下去没人能把它叫醒 | 用 spinlock，或挪到下半部 |
| `kmalloc(GFP_KERNEL)` | 可能睡眠等待内存 | 用 `GFP_ATOMIC`，或提前分配 |
| 大块 I2C/SPI 传输 | 关中断时间过长，丢中断、抖动变大 | 线程化中断或 workqueue |
| `copy_to_user` / `copy_from_user` | 可能缺页睡眠，且不能直接碰用户地址 | 挪到进程上下文 |
| 调 `disable_irq()` | 自等死锁 | `disable_irq_nosync()` |

## 十、两条常见误解

**"驱动上报事件后，用户层 read 的数据就自动变成事件了？"**

不是"自动变成"。`input_report_key()` 把事件塞进 input 子系统的事件队列，用户层 `read()` 读的是队列里的 `struct input_event`；中间的转换是 input 框架做的，不是数据的魔法变形。

**"input 子系统简化了按键检测流程？"**

它简化的是**驱动和应用之间的交互**，外加统一各类输入设备的事件模型；它并不减少 GPIO 检测、消抖、中断这些硬件侧的工作。所以它是软件架构层面的封装，不是硬件处理的替代品。

## 十一、一句话总结

外设 → GIC → 同一个 IRQ 信号 → 汇编入口 → GIC 驱动读出 hwirq → `irq_domain` 翻译成 virq → `irq_desc` 按类型分发 → 驱动 handler；handler 只做最急的事，剩下的一半留给软中断、tasklet、workqueue 或线程化中断；而 EOI 之后到 `iret` 之前，新中断只能在 GIC 里挂着——退出路径上唯一开着中断门的窗口，是 `__do_softirq()` 里的那段 `local_irq_enable()`。
