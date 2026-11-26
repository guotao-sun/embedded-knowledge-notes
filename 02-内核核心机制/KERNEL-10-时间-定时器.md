# Linux 定时器：jiffies、timer_list 与 hrtimer

## 一、先说结论

- 普通 `timer_list` 的精度就是**一个节拍（1/HZ）**，毫秒级，而且**只保证不早于设定时间**，晚多少取决于当时的负载。
- 要微秒级用 `hrtimer`（高精度定时器），但实际也会有几十微秒的抖动——它比 `timer_list` 准，不是"绝对准时"。
- 定时器回调运行在**软中断上下文**，不能睡眠；要睡眠的活请挪到 workqueue。
- 内核里没有"周期定时器"这个对象，所谓周期 = 在回调里再 `mod_timer` 一次。

## 二、时间是怎么数的：jiffies 与 HZ

| 概念 | 说明 |
|---|---|
| `HZ` | 每秒的节拍数，常见 100 / 250 / 1000 |
| `jiffies` | 内核启动以来的节拍计数（32 位或 64 位，取决于配置） |
| `msecs_to_jiffies(ms)` | 毫秒换算成节拍数 |
| `time_after(a, b)` | 安全的"a 是否晚于 b"比较，处理回绕 |

HZ = 100 时，一个节拍就是 10 ms——这就是 `timer_list` 的精度下限：你设 100 ms，实际可能 100~110 ms，但绝不会 99 ms。

**32 位 `jiffies` 会回绕**（HZ=100 时约 497 天），所以别用 `jiffies > deadline` 这种裸比较，要用 `time_after()`；换算成"还有多少节拍"用 `time_after_eq` / `jiffies_to_msecs` 这类宏。

## 三、最小可用模板

```c
#include <linux/module.h>
#include <linux/kernel.h>
#include <linux/init.h>
#include <linux/timer.h>
#include <linux/jiffies.h>

static struct timer_list test_timer;

/* 定时器回调：运行在软中断上下文，不能睡眠 */
static void timer_callback(struct timer_list *timer)
{
    printk(KERN_INFO "timer callback!\n");

    /* 想要周期性：在回调里再挂一次（这里 1 秒后） */
    mod_timer(&test_timer, jiffies + msecs_to_jiffies(1000));
}

static int __init timer_test_init(void)
{
    printk(KERN_INFO "timer init\n");

    /* 初始化：绑定回调，flags 一般填 0 */
    timer_setup(&test_timer, timer_callback, 0);

    /* 第一次启动：当前时间 + 1000 ms */
    mod_timer(&test_timer, jiffies + msecs_to_jiffies(1000));

    return 0;
}

static void __exit timer_test_exit(void)
{
    printk(KERN_INFO "timer exit\n");

    /* 删除并等待正在执行的回调结束，卸载时必须用它 */
    del_timer_sync(&test_timer);
}

module_init(timer_test_init);
module_exit(timer_test_exit);

MODULE_LICENSE("GPL");
MODULE_AUTHOR("test");
MODULE_DESCRIPTION("simple kernel timer example");
```

## 四、关键 API

| API | 作用 |
|---|---|
| `timer_setup(timer, callback, flags)` | 初始化定时器（4.15 起替代已废弃的 `setup_timer`） |
| `mod_timer(timer, expires)` | 启动/修改定时器；`expires` 是**绝对** jiffies 值，不是"多久之后" |
| `del_timer(timer)` | 删除定时器，**不等**回调结束 |
| `del_timer_sync(timer)` | 删除并**等回调执行完**，卸载/释放资源前必须用 |
| `msecs_to_jiffies(ms)` | 毫秒 → 节拍 |
| `jiffies` | 当前节拍计数 |

两个容易记错的点：

- `mod_timer` 的第二个参数是**绝对时间点**（`jiffies + 延时`），不是延时本身；直接传 `100` 意味着"在开机后第 100 个节拍触发"，通常早就过期了，于是立刻执行。
- `mod_timer` 对已经挂着的定时器会**重新排期**，所以周期定时器不需要 `add_timer` + `del_timer` 来回折腾。

## 五、为什么回调里不能睡

`timer_list` 的回调由软中断（`TIMER_SOFTIRQ`）执行，属于**中断上下文**：

- 不能 `msleep`、不能拿 mutex、不能等信号量
- 不能做长时间 I2C/SPI 传输
- 可以 `wake_up`（唤醒等待队列）、可以 `queue_work`（把活推给线程）

如果确实需要睡眠，标准做法是在回调里 `schedule_work()`，真正的活放在 workqueue 里做。

## 六、精度不够怎么办：hrtimer

| | timer_list | hrtimer |
|---|---|---|
| 精度 | 1 个节拍（ms 级） | 纳秒级设定，实际抖动几十 μs |
| 依赖 | jiffies 节拍 | 硬件高精度计数器 + 红黑树 |
| 上下文 | 软中断 | 软中断或硬中断（可指定） |
| 典型用途 | 轮询、超时、去抖 | 音频、电机控制、精密测量 |

驱动里用 hrtimer 的一般形态是 `hrtimer_init()` + `hrtimer_start()`，回调里返回 `HRTIMER_RESTART` 表示继续周期性触发。但要注意：**hrtimer 回调也在（软）中断上下文**，能睡得活照样不能放进去。

## 七、踩坑清单

| 现象 | 原因 |
|---|---|
| 定时器设了 1 秒，几乎立刻触发 | `mod_timer` 传的是相对延时而不是 `jiffies + 延时` |
| 卸载模块时偶发 crash | 用了 `del_timer` 而不是 `del_timer_sync`，回调还在跑就释放了结构体 |
| 回调里调用 `msleep` 直接报错 | 软中断上下文不能睡眠 |
| 长时间运行后定时器错乱 | 32 位 jiffies 回绕，用了裸比较 |
| 周期定时器越跑越慢 | 在回调里用 `jiffies` 累加而不是重新 `mod_timer(jiffies + 周期)` |
| 精度达不到要求 | `timer_list` 精度就一个节拍，需要更准就换 hrtimer |

## 八、一句话总结

`timer_list` 是"**到点提醒**"，不是"**精确闹钟**"：它挂在 jiffies 节拍上，只保证不早到；回调在软中断里跑，只能做短活；要周期就在回调里再挂一次，要精度就换 hrtimer。
