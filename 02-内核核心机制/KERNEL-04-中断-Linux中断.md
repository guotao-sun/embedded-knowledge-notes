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

### 7.1 EOI 到底由谁写、写在哪一步

EOI 不是"退出中断时顺手做的事"，它是**每一次中断分发末尾、由中断控制器驱动**写的一条寄存器。完整位置见下：

```text
gic_handle_irq
  ├─ readl(GIC_CPU_INTACK)                  ← ① 应答（ACK）：取中断号，同时置为 active
  ├─ handle_domain_irq
  │    ├─ generic_handle_irq
  │    │    └─ handle_fasteoi_irq
  │    │         ├─ handle_irq_event → action->handler()    ← ② 你的 handler
  │    │         └─ chip->irq_eoi → gic_eoi_irq
  │    │              └─ writel(GIC_CPU_EOI)                ← ③ 结束（EOI）：清 active
  │    └─ irq_exit                          ← 注意：在 ③ 之后才执行
  └─ svc_exit → iret
```

三件事别混：

| 动作 | 读/写哪个寄存器 | 作用 |
|---|---|---|
| ACK | 读 `GIC_CPU_INTACK` | 取出中断号，并把该号标记为 active |
| EOI | 写 `GIC_CPU_EOI` | 清掉 active，允许该号再次上报 |
| （GICv2 EOImode=1） | 写 `GIC_CPU_DEACTIVATE` | 分两步结束：先优先级降级，再 deactivate |

底层就是一条写寄存器：

```c
/* drivers/irqchip/irq-gic.c（简化示意） */
static void gic_eoi_irq(struct irq_data *d)
{
    u32 irq = d->hwirq;

    /* EOImode=1 时写 DEACTIVATE，否则写 EOI，二者都等于"这一路结案" */
    writel_relaxed(irq, gic_data_cpu_base(&gic_data[0]) + GIC_CPU_EOI);
}
```

而"谁调 `irq_eoi`"在 core 里只有一处：flow handler 把 `chip->irq_eoi` 当成函数指针调。GIC 给 SPI 注册的 flow handler 是 `handle_fasteoi_irq`，所以顺序永远固定：

```c
/* kernel/irq/chip.c（简化示意，省略判错分支） */
void handle_fasteoi_irq(struct irq_desc *desc)
{
    struct irq_chip *chip = desc->irq_data.chip;

    ...
    handle_irq_event(desc);              /* ①先跑你的 handler */

    ...
    chip->irq_eoi(&desc->irq_data);      /* ②再 EOI，此时 handler 已经返回 */
}
```

由此得到三条结论：

- **EOI 在 handler 之后、在 `irq_exit()` 之前**：`irq_exit` 是 `generic_handle_irq()` 返回后才调的，而 EOI 在 `generic_handle_irq()` 内部就写完了
- **共享中断只 EOI 一次**：一个 `irq_desc` 上挂多条 `action`，`handle_irq_event` 全跑完后写一次 EOI
- **电平触发要小心**：EOI 只是清 active，如果外设的电平还拉着，GIC 会立刻重新上报——所以 handler 里必须把中断源清掉，否则就是"中断风暴"

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

## 八、保存现场与恢复现场：到底在哪几行

"保存现场"不是一条指令干完的，它分三段，**硬件只做了很小一部分**：

| 阶段 | 谁做 | 保存了什么 | 位置 |
|---|---|---|---|
| ① 异常进入 | **硬件** | 只存两个：`CPSR → SPSR_irq`、返回地址 `→ LR_irq`；同时切到 IRQ 模式（用 IRQ 模式的私有 SP）。**通用寄存器一个都不存** | CPU |
| ② `vector_stub` | 汇编 | 把 r0、LR_irq、SPSR_irq 三个值暂存到 IRQ 模式栈；然后借异常返回机制切到 SVC 模式 | `entry-armv.S` |
| ③ `svc_entry` / `usr_entry` | 汇编 | 在当前任务的**内核栈**上开一个 `pt_regs` 帧（ARM32 是 72 字节），存 r0–r12、sp、lr、pc、cpsr；顺手关 IRQ | `entry-armv.S` |
| ④ 内核处理 | C | handler、软中断、调度判定，可能改 `pt_regs`（如信号、系统调用返回值） | — |
| ⑤ `svc_exit` | 汇编 | `msr spsr_cxsf` 恢复 CPSR，`ldmia r0, {r0 - pc}^` 一次恢复所有通用寄存器 + PC | `entry-armv.S` |
| ⑥ 回到原处 | CPU | 已在原 PC、原模式继续执行 | — |

**这就是和 Cortex-M 最大的差别**：Cortex-M 硬件自动压 8 个寄存器；ARM 只自动存 PC 和 CPSR，其余全靠软件（见 [中断对比](./KERNEL-05-中断-imx6ull与STM32中断对比.md) 的"上下文保存差异"）。

### 8.1 第②步：vector_stub 先"占个位"

```asm
/* arch/arm/kernel/entry-armv.S（摘录，省略分支表细节） */
    .macro  vector_stub, name, mode, correction=0
    .align  5
vector_\name:
    .if \correction
    sub     lr, lr, #\correction      @ 修正返回地址：ARM 流水线让 LR 偏 +4
    .endif
    @ 先把这三个值塞进 IRQ 模式栈（这时还没法用 C 栈）
    stmia   sp, {r0, lr}              @ r0 和"被打断的 PC"
    mrs     lr, spsr
    str     lr, [sp, #8]              @ 被打断时的 CPSR

    @ 伪造一个 SPSR，再借异常返回机制切到 SVC 模式
    mrs     r0, cpsr
    eor     r0, r0, #(\mode ^ SVC_MODE | PSR_ISETSTATE)
    msr     spsr_cxsf, r0
    mov     r0, sp
    ldr     lr, [pc, lr, lsl #2]      @ 查分支表
    movs    pc, lr                    @ ★ 跳进 __irq_usr 或 __irq_svc（同时完成模式切换）
```

注意最后那条 `movs pc, lr`：它把 SPSR 拷进 CPSR，于是 CPU 从 IRQ 模式切到 SVC 模式，同时跳到 `__irq_usr`（打断的是用户态）或 `__irq_svc`（打断的是内核态）。**"切模式"和"跳转"在这里是一条指令完成的。**

### 8.2 第③步：svc_entry 在栈上摆出 pt_regs

```asm
/* arch/arm/kernel/entry-armv.S（摘录，省略了 unwind/trace 相关） */
    .macro  svc_entry, stack_hole=0, trace=1
    sub     sp, sp, #(S_FRAME_SIZE + \stack_hole - 4)   @ 开 72 字节的帧
    ...
    stmia   r7, {r2 - r4}              @ 存 r2~r4 以及 sp、lr
    ...
    add     r0, sp, #S_PC
    stmia   r0, {r4 - r6}              @ 存 pc 与 cpsr
    ...
    disable_irq                        @ 关 IRQ：从这行起内核代码不被中断打断
    .endm
```

帧的内存布局就是 `struct pt_regs`，oops 打印的那一屏寄存器就是它：

```text
低地址  r0  r1  r2  ...  r12  sp  lr  pc  cpsr   高地址
        └────────── 18 个字（72 字节），ARM32 ──────────┘
```

两条路径的差别值得记住：

- **打断用户态 → `__irq_usr` → `usr_entry`**：用户态的 SP 不能用，所以先把用户 sp/lr 也存进帧，帧建在**当前任务的内核栈**上
- **打断内核态 → `__irq_svc` → `svc_entry`**：本来就跑在内核栈上，直接继续往下压帧

这也解释了"为什么只有返回用户态时才容易触发调度"——只有 `__irq_usr` 那条路会走到 `ret_to_user`，那里才检查 `TIF_NEED_RESCHED`。

### 8.3 第⑤步：svc_exit 一条指令恢复全部

```asm
/* arch/arm/kernel/entry-armv.S（摘录） */
    .macro  svc_exit, rpsr, irq = 0
    .if \irq != 0
    @ IRQ 已关闭，无需再关
    .else
    disable_irq
    .endif
    ...
    msr     spsr_cxsf, \rpsr           @ 把"被打断时的 CPSR"塞回 SPSR
    ...
    ldmia   r0, {r0 - pc}^             @ ★ 一次弹出 r0~r14 和 pc
    .endm
```

最后那条 `ldmia ..., {r0 - pc}^` 是关键：

- 普通 `ldmia` 只能恢复 r0–r14
- 末尾的 `^` 表示"如果目标寄存器里包含 pc（r15），就顺便把 SPSR 恢复到 CPSR"——于是**寄存器组和状态寄存器在同一条指令里一起回来**，不需要 `msr cpsr` 再单独跳转

`irq_exit()` 之后的 `enable_irq`（或 `ret_to_user` 路径里的恢复）才把 IRQ 掩码真正打开，这就是第七节时间线里"CPU 到 `iret` 才开门"那句话的落点。

### 8.4 ARM64（RK3568）上的对应物

64 位平台换了一套宏，但结构一样：

```asm
/* arch/arm64/kernel/entry.S（摘录） */
el1_irq:
    kernel_entry 1              @ 保存 x0~x29、lr、sp、elr_el1、spsr_el1 到 pt_regs
    enable_da_f                 @ 放开调试异常、SError、FIQ；IRQ 位仍然关着
    irq_handler                 @ → gic_handle_irq → … → 你的 handler
    ...
    kernel_exit 1               @ 恢复上面那一整套，eret 回原处
```

差别在于：ARM64 没有"IRQ 模式私有栈"这一层，`kernel_entry` 直接在当前栈上建帧；寄存器更多（31 个通用 + SP + ELR + SPSR），帧也更大，浮点/SIMD 状态另由 C 代码按需保存。

### 8.5 想看真实的现场，从哪看

```bash
dmesg | tail            # oops/panic 打印的 "PC is at ..." 和寄存器表就是 pt_regs
cat /proc/interrupts    # 每个 virq 的计数与名字，确认中断到底进没进
```

内核里对应的打印函数是 `show_regs(regs)`，参数就是中断/异常入口建好的那个 `pt_regs`。

## 九、disable_irq 的坑

| API | 行为 | 什么时候用 |
|---|---|---|
| `disable_irq()` | 关闭中断，并**等正在执行的 handler 跑完**才返回 | 进程上下文，要确保 handler 不再访问资源时 |
| `disable_irq_nosync()` | 关闭后立即返回，不等 | **中断上下文**里，或明确不需要等 |

在中断处理函数里调 `disable_irq()` 是经典死锁：当前 handler 还没返回，而 `disable_irq` 就在等"当前 handler 结束"——互相等，永远不结束。这种情况只能用 `disable_irq_nosync()`。

那 `disable_irq()` 的"等待"有什么意义？两个真实场景：

- **多核**：CPU0 正在 handler 里操作网卡资源，CPU1 想关中断并释放这块资源。不等的话，CPU0 可能在释放后继续访问，直接崩。
- **卸载驱动**：`free_irq` 之前必须确保没有 handler 还在跑，否则访问的是已经被释放的内存。

`disable_irq_nosync()` 只是关掉"开关"，不释放任何资源；资源一直留到 `free_irq()`。

## 十、中断上下文里不能做的事

| 不能做 | 原因 | 替代 |
|---|---|---|
| `msleep`、`mutex_lock`、等信号量 | 中断上下文没有"进程"可调度，睡下去没人能把它叫醒 | 用 spinlock，或挪到下半部 |
| `kmalloc(GFP_KERNEL)` | 可能睡眠等待内存 | 用 `GFP_ATOMIC`，或提前分配 |
| 大块 I2C/SPI 传输 | 关中断时间过长，丢中断、抖动变大 | 线程化中断或 workqueue |
| `copy_to_user` / `copy_from_user` | 可能缺页睡眠，且不能直接碰用户地址 | 挪到进程上下文 |
| 调 `disable_irq()` | 自等死锁 | `disable_irq_nosync()` |

## 十一、两条常见误解

**"驱动上报事件后，用户层 read 的数据就自动变成事件了？"**

不是"自动变成"。`input_report_key()` 把事件塞进 input 子系统的事件队列，用户层 `read()` 读的是队列里的 `struct input_event`；中间的转换是 input 框架做的，不是数据的魔法变形。

**"input 子系统简化了按键检测流程？"**

它简化的是**驱动和应用之间的交互**，外加统一各类输入设备的事件模型；它并不减少 GPIO 检测、消抖、中断这些硬件侧的工作。所以它是软件架构层面的封装，不是硬件处理的替代品。

## 十二、一句话总结

外设 → GIC → 同一个 IRQ 信号 → 汇编入口 → GIC 驱动读出 hwirq → `irq_domain` 翻译成 virq → `irq_desc` 按类型分发 → 驱动 handler；handler 只做最急的事，剩下的一半留给软中断、tasklet、workqueue 或线程化中断；而 EOI 之后到 `iret` 之前，新中断只能在 GIC 里挂着——退出路径上唯一开着中断门的窗口，是 `__do_softirq()` 里的那段 `local_irq_enable()`。
