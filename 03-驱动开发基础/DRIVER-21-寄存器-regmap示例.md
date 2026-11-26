# regmap 示例

## 一、先说结论

真实工程里有一种很常见的需求：**芯片挂在 UART 上，但它是"寄存器式"的**——有地址、有读写命令字。

I2C/SPI 有现成的 `regmap_init_i2c/spi`，UART **没有**。这时候就用 `regmap_init()` + 自定义 `regmap_bus`：

- 上层代码照旧写 `regmap_write(map, reg, val)`
- 底下由你的 `uart_write` / `uart_read` 拼帧、收发
- `context` 指针把"哪个 UART fd、哪把锁、哪块缓冲"带进回调

## 二、真实工程例子（UART 音频芯片）

### 定义设备结构体

```c
struct uart_audio_dev {
    int uart_fd;
    struct mutex lock;          /* 串口是独占的，必须自己串行化 */
    uint8_t tx_buf[256];
    struct regmap *map;
};

struct uart_audio_dev *dev = kzalloc(sizeof(*dev), GFP_KERNEL);
dev->uart_fd = open_uart();     /* 打开 /dev/ttySx，配好波特率 */
mutex_init(&dev->lock);
```

### 初始化 regmap

```c
static const struct regmap_config cfg = {
    .reg_bits     = 8,          /* 芯片寄存器地址 8 位 */
    .val_bits     = 8,          /* 寄存器值 8 位 */
    .max_register = 0xFF,
    .cache_type   = REGCACHE_NONE,   /* 串口没回读保证时别开缓存 */
};

map = regmap_init(&uart_bus, dev, &cfg);   /* 第二参 dev 会成为回调里的 context */
```

### bus 里怎么用

```c
static const struct regmap_bus uart_bus = {
    .write = uart_write,
    .read  = uart_read,
};

static int uart_write(void *context, const void *data, size_t count)
{
    struct uart_audio_dev *dev = context;

    mutex_lock(&dev->lock);
    /* 这里就可以访问 UART：data 已经是 "地址 + 值" 拼好的字节流 */
    int ret = write(dev->uart_fd, data, count);
    mutex_unlock(&dev->lock);

    return ret < 0 ? ret : 0;
}
```

### read 也是一样

```c
static int uart_read(void *context, const void *reg_buf, size_t reg_size,
                     void *val_buf, size_t val_size)
{
    struct uart_audio_dev *dev = context;
    int ret;

    mutex_lock(&dev->lock);
    ret = uart_send_cmd(dev->uart_fd, *(const uint8_t *)reg_buf);  /* 发读命令 */
    if (ret == 0)
        ret = uart_recv_data(dev->uart_fd, val_buf, val_size);     /* 收回应 */
    mutex_unlock(&dev->lock);

    return ret < 0 ? ret : 0;
}
```

两个签名细节：

- `write`：`data` 是 regmap **已经拼好的**完整字节流（地址在前、值在后），你只管原样发出去
- `read`：`reg_buf` 是地址（`reg_size` 字节），`val_buf` 是你要填的回读数据（`val_size` 字节）
- **成功返回 0**，失败返回负 errno——返回 `count` 会被 regmap 当成错误

## 三、关键点

- `regmap_init()` 的第二个参数 `dev` 会作为 `context` 传给 `read`/`write` callback
- 通过 `context` 指针，callback 里可以访问到设备的私有数据（如 UART 文件描述符、锁、缓冲区等）
- 这样 regmap 就不局限于 I2C/SPI，任何总线（包括 UART）都可以通过自定义 callback 来适配

## 四、为什么值得这么绕

直接写 `uart_send_cmd()` / `uart_recv_data()` 也能用，但换成 regmap 之后白拿三样东西：

1. **统一 API**：同一份芯片驱动，换到 I2C 版本时只改初始化那一行，业务代码一行不动
2. **位域操作**：`regmap_update_bits()` 的原子读改写，串口场景尤其需要（读改写中间隔了几毫秒，不锁就会丢配置）
3. **调试视图**：`/sys/kernel/debug/regmap/*/registers` 直接看寄存器影子

代价是多一层回调，且**串口的时延要自己心里有数**——`regmap_bulk_read` 一次读 16 个寄存器，在 115200 波特率下就是几十毫秒，别在中断上下文里干这事。

## 五、踩坑

| 现象 | 原因 | 修法 |
|---|---|---|
| `regmap_read` 总是返回 `-EIO` | callback 返回了正数（regmap 只认 0） | 改成 `return 0` |
| 读出来是乱码 | `reg_bits`/`val_bits` 与芯片手册不符 | 核对地址/数据宽度 |
| 偶发配置丢失 | 多线程同时 read-modify-write，没加锁 | callback 里加 mutex，或只用 `regmap_update_bits` |
| 休眠唤醒后配置没了 | 没开缓存也没重下发 | 用 `REGCACHE_RBTREE` + `regcache_sync()` |
| `regmap_init` 返回 `ERR_PTR` | `cfg` 里 `max_register` 为 0 等非法配置 | `IS_ERR()` 判断并打印 |

## 六、一句话总结

**regmap 的扩展点就是 `struct regmap_bus` 的 read/write 两个回调 + 一个 context 指针；把 UART 收发包塞进这两个函数里，上层就照样能 `regmap_write/read`。**
