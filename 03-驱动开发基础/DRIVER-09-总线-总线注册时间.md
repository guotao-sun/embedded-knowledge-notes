# Linux 总线注册时间

## 一、先说结论

- **总线是纯软件抽象**，`bus_register()` 不依赖任何硬件控制器，所以它注册得很早
- **platform 总线**：在 `driver_init()` 里注册，比所有驱动都早（`start_kernel` 阶段就完成）
- **SPI / I2C 这类总线**：在各自子系统的 `subsys_initcall` 里注册，也在任何 `device_initcall` 驱动之前
- **控制器（controller）**是 platform 驱动 probe 时才出现的，它出现后才去扫描设备树、创建下属设备
- 所以顺序永远是：**总线 → 控制器 → 下属设备 → 设备驱动 probed**

## 二、内核的实际模型（以 SPI 总线为例）

```text
Driver Model
      │
┌─────┴───────────────┐
│                     │
Platform Bus      SPI Bus (spi_bus_type)
      │                     │
      │           ├── spi_device(flash)
      │           ├── spi_device(codec)
      │           └── spi_driver(...)
      │
├── platform_device(ecspi1)
│         │
│         └──── probe(spi-imx)
│                   │
│                   ▼
│             spi_controller
│                   │
│                   └── 管理整个 SPI Bus 上属于自己的所有 spi_device
│
└── platform_driver(spi-imx)
```

**层级关系要看清**：SPI 控制器自己是一个 platform 设备（挂在 platform 总线上），但它 probe 出来之后，**又成了 SPI 总线的"上游"**——它去创建 SPI 设备、管理 SPI 传输。

## 三、四个概念，四种注册时机

| 概念 | 说明 | 注册时机 |
|------|------|---------|
| bus | 总线类型 | 子系统 init 阶段（`subsys_initcall`） |
| controller | SPI 控制器 | 它自己的 platform 驱动 probe 时（`spi_register_controller`） |
| device | SPI 设备 | controller 注册时扫描设备树创建（`spi_add_device`） |
| driver | SPI 驱动 | 驱动模块加载 / `device_initcall` 时（`spi_register_driver`） |

### 1. bus 是什么时候注册的？

`spi_bus_type` 只是 SPI Core 管理的一部分。SPI 总线是在 SPI 子系统初始化的时候注册的。

内核启动的大致顺序：

```text
start_kernel()
    ↓
do_basic_setup()
    ↓
driver_init()          ← platform_bus_type 在这里注册（最早）
    ↓
do_initcalls()         ← core_initcall → postcore → arch → subsys → fs → device ...
    ↓
SPI 子系统（spi.c）的 init 函数    ← subsys_initcall 级别
```

例如（4.x 内核）：

```c
static int __init spi_init(void)
{
    bus_register(&spi_bus_type);
    class_register(&spi_master_class);
    ...
}
subsys_initcall(spi_init);
```

> `subsys_initcall` 比驱动常用的 `module_init`（在 `device_initcall` 级别）**早一个等级**，这就是"总线一定先于驱动存在"的机制保证。初始化等级详见 [初始化宏](./../02-内核核心机制/KERNEL-03-启动-初始化宏.md)。

### 2. 为什么这么早注册？

因为 Driver Model 要先知道世界上有一种 bus 叫 SPI，以后任何 `spi_device`、`spi_driver` 才能往这个 bus 上挂。

就像：

```text
bus_register()
    ↓
创建了一块停车场
    ↓
以后才能停车
```

**先有停车场，再谈停车位。** 注意这里说的"停车场"完全是内存里的数据结构（`/sys/bus/spi/` 那两个目录），跟芯片上有没有 SPI 控制器毫无关系——所以哪怕板子上一个 SPI 控制器都没有，SPI 总线照样被注册。

### 3. controller 什么时候出现？

```text
设备树里 ecspi1 节点
    ↓ of_platform_populate 创建 platform_device
platform_driver(spi-imx) probe
    ↓
spi_alloc_master / devm_spi_alloc_master
    ↓
spi_register_controller(&spi_bus_type 下挂载 controller)
    ↓
扫描 controller 节点下的子节点 → spi_add_device()（每个从设备一个）
```

**关键点：SPI 设备不是"发现"出来的，是控制器驱动解析设备树"造"出来的。** 这也是为什么把 SPI 叫"非枚举总线"（见 [Platform 与其他总线的区别](./DRIVER-12-总线-Platform与其他总线区别.md)）。

### 4. driver 什么时候出现？

`insmod spi_driver.ko` 或内核内置时 `spi_register_driver()`：

```text
spi_register_driver
    ↓
driver_register(&sdrv->driver)
    ↓
把 driver.probe 换成 spi_drv_probe（多一层包装，负责取设备树、匹配、调你的 probe）
    ↓
遍历 spi_bus_type 上已有设备 → spi_match_device → probe
```

## 四、一张时序表（从上电到 probe）

| 阶段 | 发生什么 | 谁做的 |
|---|---|---|
| `start_kernel` | `driver_init()` → `platform_bus_type` 注册 | 内核核心 |
| `subsys_initcall` | `spi_init()` → `spi_bus_type` 注册 | SPI core |
| `arch_initcall` | `of_platform_populate()` 把 DTS 展开成 platform_device | OF + platform |
| `device_initcall` / `insmod` | platform 驱动 probe → `spi_register_controller()` → 创建 `spi_device` | 控制器驱动 |
| `device_initcall` / `insmod` | SPI 设备驱动 probe | 你的驱动 |

## 五、为什么要分清这些"时机"

因为调试时**九成的"驱动不 probe"都能归到时机问题上**：

- 总线没注册 → `driver_register` 返回 `-ENODEV`，日志里是 `bus xxx not registered`
- 控制器没 probe → `spi_device` 根本没被创建，`/sys/bus/spi/devices/` 是空的
- 控制器 probe 了但设备树子节点写错 → `spi_device` 没创建，驱动等不到匹配
- 驱动比设备晚到没问题，driver core 会重新遍历；**但如果设备比驱动早太多而驱动永不加载，就一直没人管它**

## 六、一句话总结

**总线是纯软件，注册在 `driver_init`/`subsys_initcall`，比所有驱动都早；控制器是 platform 驱动 probe 出来的，设备又是控制器 scan 出来的——所以"总线 → 控制器 → 设备 → 驱动 probe"这条顺序不会乱。**
