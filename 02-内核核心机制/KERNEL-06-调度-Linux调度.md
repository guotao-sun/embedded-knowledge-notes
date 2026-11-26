# Linux 调度：CFS 与调度类

## 一、先说结论

Linux 里**不是只有一个调度器**，而是一组按优先级叠起来的"调度类"：

```text
stop > deadline > real-time > fair(CFS) > idle
```

每次选下一个任务时，从最高优先级的类开始问"你有活可干吗"，有就直接给它，没有才往下问。普通进程全在 `fair` 类里，由 **CFS（Completely Fair Scheduler，完全公平调度器）** 负责。

CFS 的核心思想一句话：**不看"还剩多少时间片"，看"到目前为止谁跑得少"**——每个任务维护一个虚拟运行时间 `vruntime`，每次挑 `vruntime` 最小的那个跑。

## 二、调度类的层级

| 调度类 | 管谁 | 策略 |
|---|---|---|
| `stop_sched_class` | 内核内部（CPU 热插拔、迁移） | 最高，抢占一切 |
| `dl_sched_class` | 硬实时任务 | `SCHED_DEADLINE` |
| `rt_sched_class` | 实时任务 | `SCHED_FIFO`、`SCHED_RR` |
| `fair_sched_class` | 普通进程 | `SCHED_NORMAL`（默认）、`SCHED_BATCH` |
| `idle_sched_class` | 空闲 | `SCHED_IDLE`（最低优先级，不是 idle 线程） |

这张表解释了一个常见困惑：**为什么一个 nice 值是 -20 的普通进程，也抢不过一个实时进程？** 因为它们根本不在一个调度类里，nice 只在 `fair` 类内部有效。

## 三、CFS 的三个关键量

### 1. vruntime

把"实际运行时间"按权重折算成"虚拟运行时间"：

```text
vruntime += 实际运行时间 × (NICE_0_LOAD / 该任务权重)
```

- 权重越大（nice 越小），除出来越小 → `vruntime` 涨得越慢 → 越容易被选中
- 这样就实现了"按比例分配 CPU"，而不是"每人平均分"

### 2. 权重：nice 值换算出来的比例

nice 范围 −20（最高）到 +19（最低），每差一级，权重约差 1.25 倍。基准是 nice 0 = 1024，nice +19 只有 15 左右。

所以两个任务 nice 差 5 级，CPU 分配大约是 2:1，而不是"差一点点"。

### 3. 红黑树

CFS 把每个可运行任务挂在红黑树上，键是 `vruntime`。选下一个任务 = **取树最左节点**，O(log n)；任务 `vruntime` 变化时重新插入。

`min_vruntime` 是这棵树里的"水位线"，新任务或被唤醒的任务，`vruntime` 不会低于它太多（避免一个睡了很久的任务醒来后独占 CPU 很久）。

## 四、一次调度大致做了什么

```text
定时器中断 → scheduler_tick()
    → 更新当前任务的 vruntime
    → 若它已明显落后于最左节点 → 置 TIF_NEED_RESCHED
    ↓（不在中断里切换，见 07 章）
__schedule()
    → 从调度类里挑 next 任务（fair 类 = 取红黑树最左）
    → context_switch()：切 mm、切寄存器、切栈
    → 新任务开始跑
```

有三件事容易被误解：

- **CFS 没有"时间片"这个显式字段**，但有一个"目标延迟"：`sched_latency`（默认 6 ms 量级）× 按任务数缩放，保证一轮里每个任务至少被调度一次；任务太多时退化成最小粒度 `sched_min_granularity`。
- **抢占不是"立刻"发生的**：中断里只打标记，真正切换在返回用户态或 `preempt_enable()` 等安全点。
- **睡眠不占 CPU 但保留 vruntime**：所以"睡久了起来更优先"是有限的，靠 `min_vruntime` 兜住。

## 五、几种调度策略

| 策略 | 调度类 | 优先级范围 | 用途 |
|---|---|---|---|
| `SCHED_NORMAL` | fair | nice −20…+19 | 普通进程（默认） |
| `SCHED_BATCH` | fair | nice 同上 | 批处理，不期望被频繁抢占 |
| `SCHED_IDLE` | fair | 最低 | "闲时才跑"的后台任务 |
| `SCHED_FIFO` | rt | 1…99 | 实时，无时间片，跑到自己让出 |
| `SCHED_RR` | rt | 1…99 | 实时，带时间片轮转 |
| `SCHED_DEADLINE` | dl | 按 runtime/deadline/period | 硬实时，按截止时间保证 |

注意两套优先级**不能直接比较**：RT 的 99 和 nice 的 −20 说的是不同维度的东西。

查看与设置：

```bash
chrt -p $$                 # 看当前进程的策略与优先级
chrt -f 50 ./my_task       # 以 SCHED_FIFO、优先级 50 运行
renice -n -5 -p 1234       # 改 nice（普通进程）
```

## 六、抢占发生在哪些点

| 抢占点 | 说明 |
|---|---|
| 中断/异常返回用户态 | 最常见：`TIF_NEED_RESCHED` 置位就在这里生效 |
| 系统调用返回 | 同上 |
| 唤醒时 | 新唤醒的任务 `vruntime` 明显更小 → 立刻检查是否抢占当前任务 |
| `preempt_enable()` | 关抢占的临界区结束时补一次检查 |
| 显式 `cond_resched()` | 长循环里主动让一下，避免独占 CPU |

反过来说，**内核里关抢占的区间（spinlock 保护的临界区）不会被打断**，这也是自旋锁要求"临界区必须短"的另一个原因。

## 七、几个常见误解

| 误解 | 实际 |
|---|---|
| CFS 就是"平均分 CPU" | 按权重分比例；nice 差 5 级就是约 2:1 |
| nice 数字越大越优先 | 反了，越小越优先（−20 最高） |
| 实时进程只是"nice 更小" | 它走另一个调度类，压根不参与 CFS 排序 |
| 线程越多，每个越快 | 同一 CPU 上只可能有一个在跑，线程多了只会增加切换开销 |
| `SCHED_IDLE` 就是 idle 线程 | `SCHED_IDLE` 是最低优先级的普通任务；idle 线程走 `idle_sched_class` |

## 八、一句话总结

CFS 用"虚拟运行时间"把"公平"量化成可比较的数字：**谁累计跑得少，谁先上**；权重决定累计的快慢，红黑树负责快速找到那个"跑得最少"的任务。而它只在 `fair` 这一层里生效——上面还有实时、deadline、stop 三层压着。
