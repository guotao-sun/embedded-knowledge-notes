# platform 总线

## 一、先说结论

- platform 是**"虚拟总线"**，没有对应的物理总线，专门挂 SoC 内部那些无法自枚举的外设
- 它的 `bus_type` 里只有 `match`、`uevent`、`pm`，**没有 `probe`**——probe 在 driver 上
- 设备是**先被造出来**（DT / ACPI / 手工注册），再交给 bus 去 match
- 判断一个驱动该不该用 platform：**设备能不能被硬件自动发现？不能 → platform**

## 二、总线定义

```c
struct bus_type platform_bus_type = {
    .name   = "platform",
    .match  = platform_match,
    .uevent = platform_uevent,
    .pm     = &platform_dev_pm_ops,
};

struct bus_type spi_bus_type = {
    .name       = "spi",
    .dev_groups = spi_dev_groups,
    .match      = spi_match_device,
    .uevent     = spi_uevent,
};
```

两个结构对比能看出共同点：**都有 `match`，都没有 `probe`**。这就是"bus 定规则、driver 干活"的最直接证据。

`platform_match` 内部按优先级尝试四种匹配方式：

```text
1. of_driver_match_device()      device tree compatible ↔ of_match_table
2. acpi_driver_match_device()    ACPI
3. platform_match_id()           id_table（老式 platform_device_id）
4. strcmp(drv->name, pdev->name) 名字直接比
```

## 三、platform 总线注册顺序

```text
1. platform_bus_type 注册（driver_init，早期）
2. DT 被解析成 device_node（unflatten_device_tree）
3. of_platform_populate() 被调用（arch_initcall 级别）
4. platform_device 被创建
   （platform_device 不是通过 bus 去发现的，而是：DT / ACPI → 主动创建）
5. platform_driver 开始 match + probe
```

第 3、4 步的关键：`of_platform_populate()` 从根节点往下遍历，把 `simple-bus`、`soc` 这类容器节点下的子节点统统变成 `platform_device`。所以设备树里 `soc { uart1: serial@... { ... }; }` 最终都会出现在 `/sys/bus/platform/devices/` 下。

## 四、platform 与其它总线创建设备的区别

| 总线类型 | 设备创建方式 |
|---------|------------|
| **platform bus** | 设备先由系统 / DT 创建，再交给 bus 做 match |
| **其它 bus（I2C/SPI/PCI 等）** | 设备由相应的 bus 控制器 / 枚举器创建，再交给 bus 做 match |

> platform 设备是"静态描述、主动创建"的，因为 SoC 内部外设无法被硬件自动枚举，必须通过设备树或板级代码提前告知内核。

一个具体的对照：

```text
platform：DTS → of_platform_populate → platform_device(uart1) → platform_driver probe
I2C：     DTS → i2c 控制器 probe → of_i2c_register_devices → i2c_client → i2c_driver probe
```

platform 是"内核启动时一口气全造出来"，I2C 是"控制器活了才造"——前者的"造"发生在 `arch_initcall`，后者发生在控制器 probe 里。

## 五、platform 设备的三个来源

| 来源 | 写法 | 场景 |
|---|---|---|
| 设备树 | `of_platform_populate()` 自动展开 | 现代 ARM 主流 |
| ACPI | `acpi_platform` 扫描 | x86 嵌入式 / 服务器 |
| 手工注册 | `platform_device_register(&pdev)` + `platform_device_alloc/add` | 老式板级代码、极简测试 |

手工注册现在只用于测试和老的 `board-xxx.c`，主线内核已基本淘汰。

## 六、看一眼就懂的实例

```dts
/* 设备树：描述硬件，不管驱动 */
uart1: serial@02020000 {
    compatible = "fsl,imx6ul-uart", "fsl,imx6q-uart";
    reg = <0x02020000 0x4000>;
    interrupts = <GIC_SPI 26 IRQ_TYPE_LEVEL_HIGH>;
    clocks = <&clks IMX6UL_CLK_UART1_IPG>, <&clks IMX6UL_CLK_UART1_SERIAL>;
    status = "okay";
};
```

```c
/* 驱动：声明"我能驱动谁"，probe 里做资源申请 */
static const struct of_device_id imx_uart_dt_ids[] = {
    { .compatible = "fsl,imx6q-uart", .data = &imx_uart_devdata[...] },
    { /* sentinel */ }
};

static struct platform_driver imx_uart_platform_driver = {
    .probe  = imx_uart_probe,
    .remove = imx_uart_remove,
    .driver = {
        .name           = "imx-uart",
        .of_match_table = imx_uart_dt_ids,
    },
};
```

**注意 `compatible` 是两个字符串**：第 1 个精确匹配 `imx6ul-uart`，没有就退到第 2 个 `imx6q-uart`——这就是 [核心骨架](./DRIVER-01-框架-驱动核心骨架.md) 里讲的"设备树优先、顺序查找"。

## 七、一句话总结

**platform 是软件造的虚拟总线，只提供 match；设备由 DT/ACPI 提前造好再送来匹配——正因为它不依赖硬件枚举，SoC 里那些"哑外设"才有个地方挂。**
