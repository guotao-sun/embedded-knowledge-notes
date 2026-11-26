# 等待队列：条件驱动的睡眠与唤醒

## 一、先说结论

驱动的 `read()` 拿不到数据，不能"循环查"（那是忙等，白烧 CPU），而要**睡在一条等待队列上**；别人把条件准备好，再 `wake_up` 把它叫醒。

最容易被忽略的一点：**被叫醒 ≠ 可以走**。醒来之后必须重新检查条件，条件成立才真正返回。所以那句比喻很准：

> **`wake_up` 是敲门，`condition` 是门锁。**
> 门锁没开（条件假）→ 回去继续睡；门锁开了（条件真）→ 才能进去。

## 二、API 与最小用法

```c
wait_queue_head_t my_waitq;          /* 队列头，通常放在设备结构体里 */
init_waitqueue_head(&my_waitq);

/* 等待方：条件不成立就睡 */
wait_event_interruptible(my_waitq, condition);

/* 唤醒方：条件已经成立，敲门 */
wake_up_interruptible(&my_waitq);
```

`wait_event_interruptible` 的返回值必须看：返回 `-ERESTARTSYS` 表示**被信号打断**（如用户按了 Ctrl+C），此时条件并没有成立，不能当成"数据准备好了"。

## 三、它内部到底做了什么

一句 `wait_event_interruptible` 背后是五步：

```text
① 条件已经成立？→ 成立就直接返回，压根不睡
② 把自己挂到 wait_queue 上，并把状态设成 TASK_INTERRUPTIBLE
③ 再查一次条件（防止②③之间条件被满足而错过唤醒）
④ 条件仍不成立 → schedule() 让出 CPU，睡过去
⑤ 被唤醒后 → 从队列摘掉自己 → 回到①重新判断
```

之所以要在挂队列**之后**再查一次条件，是为了避开经典的 **lost wakeup（丢失唤醒）**：如果先查条件、再挂队列，而唤醒恰好发生在两步之间，唤醒方找不到这个等待者，等待方却已经准备睡了——两边一起卡死。内核用"先入队、后复查"把这个窗口关掉。

## 四、completion：一次性的"事件完成通知"

`completion` 也是基于等待队列，但它多了一个 **`done` 状态**，语义是"这件事已经做完了"，而不是"某个条件现在为真"：

```text
completion = wait_queue + done 计数 + 一次性语义
```

```c
DECLARE_COMPLETION_ONSTACK(done);   /* 通常放在栈上，配合一次性事件 */

wait_for_completion(&done);         /* 等待方：done>0 就立刻过，否则睡 */
complete(&done);                    /* 唤醒方：done++，然后叫醒 */
```

适合的场景：**等一次初始化完成、等一次 DMA 传输结束、等一次硬件上电**——这类"只会发生一次"的事件。

### 和 wait_event 的差别

| 机制 | 语义 | 可重复？ | 适用场景 |
|---|---|---|---|
| `wait_event` | 条件驱动：条件为真就能过 | 可重复等待 | 缓冲区有数据、队列非空 |
| `completion` | 事件驱动：这件事做完了 | 一次性（`done` 被消耗） | 初始化完成、传输结束 |

判断方法：如果"条件"可能反复成立又反复失效，用 `wait_event`；如果是"某件事只会发生一次"，用 `completion` 更省心（不用自己维护条件变量）。

## 五、一个完整的驱动例子

```c
/* 设备结构体里 */
wait_queue_head_t rq;
int data_ready;

/* 读接口：没数据就睡 */
ssize_t my_read(struct file *f, char __user *buf, size_t len, loff_t *off)
{
    if (wait_event_interruptible(dev->rq, dev->data_ready))
        return -ERESTARTSYS;          /* 被信号打断 */

    dev->data_ready = 0;              /* 消费掉这次数据 */
    copy_to_user(buf, dev->buf, len);
    return len;
}

/* 中断里（上半部或下半部）：数据到了，叫醒 */
dev->data_ready = 1;
wake_up_interruptible(&dev->rq);      /* wake_up 本身可以在中断里调用 */
```

注意顺序：**先改条件，再 `wake_up`**。反过来的话，等待方可能醒来查条件、发现是假、又睡回去，而这次唤醒就永久丢了。

## 六、常见坑

| 现象 | 原因 | 修法 |
|---|---|---|
| 进程永久睡死 | 忘了 `wake_up`，或唤醒路径出错 | 检查每条"条件成立"的分支都有唤醒 |
| 偶尔丢一次唤醒 | 先 `wake_up` 后改条件 | 改成先改条件，再唤醒 |
| 被信号打断后行为异常 | 没检查 `-ERESTARTSYS` 返回值 | 直接返回 `-ERESTARTSYS`，让上层处理 |
| 唤醒不起来 | `wait_event_interruptible` 睡的是 `TASK_INTERRUPTIBLE`，却用 `wake_up` 之外的方式唤醒 | 匹配使用 `wake_up_interruptible`；`wake_up` 会唤醒两种状态 |
| 睡眠时死锁 | 持着自旋锁去睡 | 睡眠前必须放锁，条件检查放锁内、`schedule` 放锁外 |

关于最后一条，Wait 的链路是：`prepare_to_wait`（可持锁修改队列）→ 放锁 → `schedule()` → 醒来再拿锁。任何"拿着自旋锁睡觉"的写法都会把整个系统拖住。

## 七、一句话总结

**等待队列管"睡和醒"，条件表达式管"该不该走"**：入队 → 复查 → 睡下 → 被叫醒 → 再复查，这个循环保证既不忙等，也不丢唤醒；`completion` 只是把"条件"简化成"这件事做完了没有"。
