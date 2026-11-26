# Linux 串口驱动

## 一、先说结论

串口驱动是"**三层套娃**"，你写的只是最底下一层：

```text
用户态 open("/dev/ttymxc0") → read/write
        ↓
tty 核心（tty_io.c）           ← 字符设备层，处理 VFS、termios、ldisc
        ↓
serial 核心（serial_core.c）    ← 统一 uart_port 管理，提供 uart_ops 调用框架
        ↓
你的驱动（imx.c 这类）          ← 只实现 uart_ops 里的 set_mctrl / startup / irq ...
```

**驱动不建字符设备、不建 /dev 节点**，这些由 serial core 统一代办；驱动只要把 `uart_port` 填好、`uart_ops` 挂上，最后 `uart_add_one_port()` 交出去。

## 二、总体流程图

```text
DTS
  │
  │ compatible = "fsl,imx6q-uart"
  ↓
platform_driver 匹配
  ↓
serial_imx_probe()
  │
  ├──────┬──────┬──────┬──────────┐
  │      │      │      │          │
获取reg 获取irq 获取clock 配置uart_port
  │      │      │      │
ioremap request_irq clk_get  uart_ops
  │
  ↓
uart_add_one_port()
  │
  ↓
serial core
  │
  ↓
/dev/ttymxc0
```

## 三、关键步骤说明

| 步骤 | 函数/操作 | 作用 |
|------|----------|------|
| 获取 reg | `platform_get_resource()` | 获取寄存器物理地址 |
| 地址映射 | `devm_ioremap_resource()` / `devm_ioremap()` | 物理地址 → 虚拟地址 |
| 获取 irq | `platform_get_irq()` | 获取中断号（可拿 TX/RX 两个） |
| 注册中断 | `devm_request_irq()` | 注册收发中断处理函数 |
| 获取 clock | `devm_clk_get()` | 获取串口时钟（IPG 用于寄存器访问、UART 用于波特率） |
| 使能时钟 | `clk_prepare_enable()` | 开启外设时钟 |
| 配置 port | `uart_ops` + `uart_port` | 填充 serial core 需要的操作集 |
| 注册端口 | `uart_add_one_port()` | 向 serial core 注册端口，生成 `/dev/ttymxc0` |

前几步和普通 platform 驱动没区别，**区别在最后一步**：普通字符驱动要自己 `cdev_add` + `device_create`，串口驱动不用——`uart_add_one_port()` 里 serial core 会替你调 `uart_register_driver` / `tty_register_device`。

## 四、三个核心结构体

```c
/* 1. 驱动级：一份代码一个，描述"我管哪几种 UART" */
static struct uart_driver imx_uart_uart_driver = {
    .owner       = THIS_MODULE,
    .driver_name = "ttymxc",     /* /proc/tty/driver 里显示的名字 */
    .dev_name    = "ttymxc",     /* ← /dev/ttymxcN 的 N 前面这部分就是它 */
    .major       = 0,            /* 0 = 动态分配主号 */
    .nr          = UART_NR,      /* 最多支持几个端口 */
    .cons        = IMX_CONSOLE,  /* 控制台支持 */
};

/* 2. 端口级：一个 UART 一个 */
struct uart_port {
    unsigned long  iobase;       /* 寄存器虚拟地址 */
    unsigned int   irq;
    unsigned int   uartclk;      /* 时钟频率，算波特率用 */
    const struct uart_ops *ops;
    ...
};

/* 3. 操作集：驱动真正要实现的东西 */
struct uart_ops {
    int  (*startup)(struct uart_port *);
    void (*shutdown)(struct uart_port *);
    void (*set_mctrl)(struct uart_port *, unsigned int);
    unsigned int (*get_mctrl)(struct uart_port *);
    void (*stop_tx)(struct uart_port *);
    void (*start_tx)(struct uart_port *);
    void (*set_termios)(struct uart_port *, struct ktermios *, struct ktermios *);
    irqreturn_t (*handle_irq)(struct uart_port *);   /* 老接口，新代码走 request_irq */
    ...
};
```

**为什么设备节点叫 `ttymxc0`**：serial core 用 `uart_driver` 里的名字给 tty 设备命名，imx 把 `driver_name` 和 `dev_name` 都设成 `"ttymxc"`，于是 tty 层建出来的节点就是 `/dev/ttymxc0`、`/dev/ttymxc1`，而不是 `ttyS0`。

## 五、数据是怎么收发的

```text
接收：
硬件 FIFO 满 → 中断 → imx_rxint → 读 URXD → uart_insert_char() → tty_flip_buffer_push()
        → line discipline（默认 n_tty）→ 放入 tty 读缓冲 → 用户 read() 拿到
发送：
用户 write() → n_tty 写入 → uart_write() → 驱动 start_tx → 使能 TX 中断
        → 每次 TX 空中断 → 从环形缓冲取一个字节写 UTXD → 空了 stop_tx
```

所以 **驱动只跟"FIFO 和寄存器"打交道，缓冲、行规程、阻塞唤醒都在 tty/serial core 里**。这也是为什么串口驱动的 `probe` 看起来很轻——重活都在别人身上。

## 六、控制台（console）的特殊之处

- 内核启动早期的打印靠 `earlycon`（只依赖 DTS 里的 `stdout-path` 和寄存器地址，不需要完整驱动）
- 正式 console 靠 `uart_driver.cons` 里的 `write` 回调（`imx_console_write`），**它不能睡眠，也不能依赖中断**
- `console=ttymxc0,115200` 这个 cmdline 就是选它

调试时最常见的现象：**内核起不来、串口一片空白**——先确认 `earlycon` 有没有配上，再看 `stdout-path` 是否指向正确的 UART。

## 七、常见坑

| 现象 | 原因 | 修法 |
|---|---|---|
| 没有 `/dev/ttymxc0` | `uart_add_one_port` 失败或 `nr` 配小了 | 看 `dmesg`；核对 `UART_NR` |
| 波特率不对 | `uartclk` 没填对，`set_termios` 算出的分频错 | 用 `clk_get_rate()` 拿真实频率 |
| 收不到数据 | 中断没注册 / FIFO 没使能 / pinmux 没配 | 查 `/proc/interrupts`、pinctrl 状态 |
| 一收数据就卡死 | 中断里做了会睡眠的事（printk 太多、mutex） | 中断里只搬数据，处理放工作队列 |
| 打印乱码 | 时钟频率与波特率不匹配 | 示波器量波形，核对 `uartclk` |

## 八、一句话总结

**串口驱动 = 填好 `uart_port` + 实现 `uart_ops` + `uart_add_one_port()` 交棒；字符设备、/dev 节点、行规程全由 serial core 和 tty core 代办。**
