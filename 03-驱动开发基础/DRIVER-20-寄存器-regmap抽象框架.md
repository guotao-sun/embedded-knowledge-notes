# regmap 寄存器访问抽象框架

## 一、先说结论

regmap 解决的问题是：**同一颗芯片，可能挂在 I2C 上，也可能挂在 SPI 上，但你不想写两套寄存器读写代码。**

它把"**寄存器地址 + 值**"这个抽象层立起来，底下挂什么总线由 `regmap_bus` 决定：

| 模式 | 底下是谁 | 你写什么 |
|---|---|---|
| **标准寄存器模式** | I2C / SPI / MMIO | 什么都不用写，`regmap_init_i2c` / `regmap_init_spi` 一调就行 |
| **自定义 IO 模式** | 任何东西（UART、FPGA、私有总线） | 自己实现 `read` / `write` 回调 |

**"标准"和"自定义"的分界线，是"有没有标准寄存器地址语义"**——不是"挂在哪条总线"。

## 二、标准寄存器模式

```text
regmap_read(map, reg, &val)
    ↓
自动拼 "读命令 + 寄存器地址"（可能带 read_flag_mask）
    ↓
i2c_transfer / spi_sync 发出去
    ↓
解出返回值 → 填进 &val
```

**适用：** IMU / codec / sensor 等有标准寄存器地址的芯片，比如 ICM20608、WM8960。

```c
/* 一行搞定，I2C/SPI 都一样用 */
regmap_write(map, REG_CTRL, 0x01);
regmap_read(map, REG_STATUS, &val);
```

**为什么它能跨总线**：`regmap_init_i2c()` 内部只是把一个 `regmap_bus`（`regmap_i2c`）传进去，这个 bus 的 read/write 就是 `i2c_transfer`。所以驱动代码里完全看不到 I2C 的影子。

## 三、自定义 IO 模式

```text
regmap_read(map, reg, &val)
    ↓
调你提供的 reg_read 回调
    ↓
你自己拼协议（命令字 + 地址 + 数据）
```

**适用：** Flash / NAND / FPGA / UART 转接的芯片——它们没有"标准寄存器地址映射"，命令字格式千奇百怪，regmap 没法猜。

```c
static const struct regmap_bus my_bus = {
    .read  = my_reg_read,
    .write = my_reg_write,
};

map = regmap_init(dev, &my_bus, priv, &cfg);
```

`priv`（也就是第二个参数后面那个 context）会原样传给回调，回调里靠它找到自己的设备私有数据。

## 四、对比总结

| 模式 | 数据传输方式 | 典型设备 |
|------|------------|---------|
| 标准寄存器模式 | regmap 自动拼地址+数据，走总线 burst | IMU、codec、sensor |
| 自定义 IO 模式 | 驱动自己实现 read/write callback | Flash、NAND、FPGA、UART 芯片 |

## 五、配置结构体：几个必须填对的字段

```c
static const struct regmap_config cfg = {
    .reg_bits      = 8,      /* 寄存器地址几位（8/16/32） */
    .val_bits      = 8,      /* 寄存器值几位 */
    .reg_stride    = 1,      /* 地址步长，有的芯片是 4 */
    .max_register  = 0x7F,   /* 最大合法地址，越界直接返回 -EIO */
    .read_flag_mask = 0x80,  /* SPI 读时地址要或上的标志位 */
    .write_flag_mask = 0x00,
    .cache_type    = REGCACHE_RBTREE,
    .volatile_reg  = my_volatile_reg,   /* 哪些寄存器不能缓存 */
};
```

三个最容易填错的：

- **`reg_bits` / `val_bits`**：填错会"读出来全是 0 或全 0xFF"，因为地址拼错了
- **`max_register`**：填小了，后面合法的寄存器全被 regmap 拦掉，返回 `-EIO`
- **`read_flag_mask`**：SPI 读通常要把地址最高位置 1，I2C 一般不用——跨总线时这点差异正是 regmap 帮你吸收的

## 六、三个真正省事的特性

### 1. 读改写位域：regmap_update_bits

```c
/* 只改 bit3:1，其他位保持 */
regmap_update_bits(map, REG_CTRL, GENMASK(3, 1), 0x5 << 1);
```

内部是 "read → 改 → write"，而且**在 regmap 自己的锁里完成**，不会跟别的线程的读改写打架。手写这套很容易漏锁。

### 2. 寄存器缓存

```c
regcache_cache_only(map, true);     /* 进休眠：只写缓存不碰硬件 */
regcache_sync(map);                 /* 唤醒：把缓存里的值一次性刷回芯片 */
```

对"休眠时要保持配置、唤醒后要恢复"的芯片（codec、sensor 最常见）几乎是刚需，否则你得自己维护一份影子寄存器表。

### 3. debugfs 直接看寄存器

```bash
cat /sys/kernel/debug/regmap/1-0068/registers
```

不用示波器、不用写测试程序，直接看"驱动认为寄存器是什么值"——排查"配置没生效"第一站。

## 七、常用 API 一览

```c
regmap_write(map, reg, val);
regmap_read(map, reg, &val);
regmap_update_bits(map, reg, mask, val);
regmap_bulk_read(map, reg, buf, count);     /* 连续读，burst */
regmap_bulk_write(map, reg, buf, count);
regmap_multi_reg_write(map, regs, n);       /* 一串初始化值一次写完 */
devm_regmap_init_i2c(client, &cfg);         /* 推荐：devm 自动释放 */
devm_regmap_init_spi(spi, &cfg);
```

初始化时用 `devm_` 版本，省掉 `regmap_exit()`。

## 八、一句话总结

**regmap = "寄存器地址 + 值"的抽象层：标准芯片换总线不用改代码，非标芯片自定义 read/write 回调；顺带白送 update_bits 的原子读改写、寄存器缓存和 debugfs 视图。**
