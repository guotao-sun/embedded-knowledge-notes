# Linux ioctl 操作

## 一、先说结论

- `ioctl` 是**字符设备的多路复用通道**：read/write 只能传数据，控制类操作全靠它
- 命令不要裸写 `0`、`1`，要用 `_IO/_IOW/_IOR/_IOWR` 宏编码，把**方向、类型、序号、参数大小**一起编进 32 位数
- `unlocked_ioctl` 不是"不加锁"，是"**内核不再帮你加 BKL**，并发安全归你自己管"
- 有指针参数时，必须 `copy_from_user` / `copy_to_user`，不能直接解引用用户指针

## 二、ioctl 命令定义

```c
#define LED_MAGIC 'L'
#define LED_ON    _IO(LED_MAGIC, 1)
#define LED_SET   _IOW(LED_MAGIC, 2, int)
```

含义：设备类型 = `L`，命令编号 = 1，无参数。

## 三、命令编码的位域

这几个宏不是随便定义的，`_IOC()` 把 32 位切成四段：

```text
 31   30 29   16 15   8 7    0
┌────┬────┬──────┬──────┬─────┐
│dir │size│ type │ nr   │ ... │
│2bit│14b │ 8bit │ 8bit │     │
└────┴────┴──────┴──────┴─────┘
```

- **dir**：读/写方向（`_IOC_NONE` / `_IOC_READ` / `_IOC_WRITE`）
- **size**：参数类型的大小（`_IOW(..., int)` 里的 `int` 就算成 4）
- **type**：magic，8 位
- **nr**：同一设备内的命令序号，8 位

所以一个设备最多 256 条命令，magic 冲突时会出现"两个驱动抢同一个命令号"，改 magic 即可解决。

## 四、参数类型区别

| 宏 | 方向 | 典型场景 |
|----|------|---------|
| `_IO` | 无参数 | 开灯（仅触发动作） |
| `_IOW` | 用户 → 内核 | 设置亮度 |
| `_IOR` | 内核 → 用户 | 读取温度 |
| `_IOWR` | 双向 | 配置并返回结果 |

方向不是"给用户看的注释"，而是给 `strace`、给 32/64 位兼容层用的——`compat_ioctl` 就靠方向判断要不要做指针转换。

## 五、驱动侧实现

```c
static long led_ioctl(struct file *filp, unsigned int cmd, unsigned long arg)
{
    struct led_dev *dev = filp->private_data;
    int val;

    switch (cmd) {
    case LED_ON:
        gpiod_set_value(dev->desc, 1);
        break;
    case LED_SET:
        if (copy_from_user(&val, (void __user *)arg, sizeof(int))
            return -EFAULT;
        ...
        break;
    default:
        return -ENOTTY;          /* 未实现的命令，固定返回这个 */
    }
    return 0;
}

static const struct file_operations led_fops = {
    .owner          = THIS_MODULE,
    .unlocked_ioctl = led_ioctl,
    .compat_ioctl   = led_ioctl,   /* 32 位程序跑 64 位内核时需要 */
};
```

两个约定：

- **未识别的命令返回 `-ENOTTY`**，不是 `-EINVAL`。用户态的 `perror` 会打出 "Inappropriate ioctl for device"，一看就知道是命令没实现
- **`arg` 是 `unsigned long`**，可能是指针也可能是个整数，取决于命令定义；指针一定要走 `copy_*_user`

## 六、unlocked_ioctl 的"unlocked"是什么意思

`unlocked_ioctl` 不是"不加锁"，而是：**内核不再自动加旧的大内核锁（BKL，Big Kernel Lock），驱动需要自己保证并发安全**。

老内核有个全局 BKL，任何 ioctl 进来都自动串行化；2.6.36 之后 BKL 逐步拆除，接口改名成 `unlocked_ioctl`，含义变成"内核不管了，你自己管"。所以涉及共享数据的驱动要自己加 `mutex`：

```c
mutex_lock(&dev->lock);
... 改寄存器 ...
mutex_unlock(&dev->lock);
```

## 七、常见问题

### Q：这个 magic 必须是 L 吗？

**A：** 不必须是 `'L'`。`LED_MAGIC` 可以是任意一个合适的值，`'L'` 只是一个人为约定，用来表示"这是 LED 设备的 ioctl 命令"。

> 注意：magic 不是固定值，但是**内核驱动和用户程序必须使用同一个 magic 定义**。magic 主要是为了保证 ioctl 接口（用户空间 ABI）的命名和管理不混乱，而不是为了防止内核根据 ioctl 找错设备（找设备靠 dev_t，跟 magic 无关）。

工程上的常规做法是把 `#define` 放进一个公共头文件，驱动和测试程序都 `#include` 它，避免两边各写一份写错。

## 八、用户态怎么调

```c
int fd = open("/dev/led", O_RDWR);
ioctl(fd, LED_ON);                 /* 无参命令 */
ioctl(fd, LED_SET, &brightness);   /* 指针参数 */
```

调试时用 `strace -e ioctl ./app`，能直接看到命令码和返回值——排查"命令号对不上"最快的办法。

## 九、一句话总结

**ioctl = 一条 32 位的命令 + 一个万能参数；命令用宏编码（方向/类型/序号/大小），参数是指针就必须 copy_*_user，没实现的命令返回 ENOTTY。**
