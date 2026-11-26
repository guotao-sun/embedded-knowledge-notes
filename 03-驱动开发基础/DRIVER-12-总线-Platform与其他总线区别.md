# Platform 总线与其他总线的区别

## 一、先说结论

所有总线都能按**"设备怎么被发现"**分成两类：

| 类型 | 发现方式 | 代表 | 需要设备树吗 |
|---|---|---|---|
| **可枚举** | 硬件/协议自己会报告"我是谁" | PCI、USB | 不需要 |
| **非枚举** | 必须由软件提前告知 | platform、I2C、SPI | 需要（DT/ACPI） |

platform 之所以存在，就是给"**没有正规总线基础设施**"的 SoC 外设一个虚拟落脚点。

## 二、Platform Bus 的设计目的（官方描述）

内核文档中明确说明：

> "This pseudo-bus is used to connect devices on buses with **minimal infrastructure**, like those used to integrate peripherals on many **system-on-chip (SoC)** processors, or some legacy PC interconnects; as opposed to large formally specified ones like PCI or USB."

简单说：Platform Bus 是给"**没有正规总线基础设施**"的设备准备的虚拟总线。

关键词是 **minimal infrastructure**：SoC 内部外设往往连一根地址线都不共享，各自一块寄存器空间、一根中断线，谈不上"总线协议"。但内核的设备模型又要求"设备必须挂在某条 bus 上"，于是造了 platform。

## 三、枚举 vs 非枚举

### 1. 什么是"枚举逻辑"？

**枚举** = 内核（或硬件）主动去"扫描、发现、识别"设备的过程。

以 USB 为例，全过程都是协议规定的：

```text
插上设备 → 主机检测到 D+/D- 电平变化
    → 复位 → 分配地址 0
    → 读设备描述符（VID/PID/class）
    → 读配置描述符 → 选配置
    → 绑定 usb_driver（按 id_table 里的 VID/PID 匹配）
```

全程**不需要你告诉内核"这里有个设备"**，插上就认。

### 2. 什么是"非枚举逻辑"？

**非枚举** = 设备**无法被硬件自动发现**，必须由**软件提前静态告知**内核设备存在。

I2C 的典型困境：

- 总线上只有 SDA/SCL，没有任何"你是谁"的协商
- 主设备按地址盲发，地址错了就没人应答
- 所以必须由设备树写明"0x68 上挂了一个 icm20608"

platform 更彻底：连"总线"都是虚拟的，地址、中断全靠 DTS 或板级代码告诉内核。

## 四、对比总结

| 总线类型 | 发现方式 | 典型代表 | 设备创建者 |
|---------|---------|---------|-----------|
| 可枚举总线 | 硬件自动扫描 | PCI、USB | 总线控制器 / 主机控制器 |
| 非枚举总线 | 软件静态描述（DTS/ACPI） | Platform、I2C、SPI | 子系统 core / 控制器驱动 / OF |

Platform 总线之所以存在，就是因为 SoC 内部的很多外设（如 UART、GPIO、定时器等）没有像 PCI 那样的自描述能力，需要一个虚拟总线来统一管理。

## 五、一个反直觉的点：platform 也管"没有寄存器"的设备

platform 不只用于 MMIO 外设，很多**纯逻辑设备**也挂在它下面：

```dts
gpio-keys {                 /* 按键：只有 GPIO + 中断，没有寄存器窗口 */
    compatible = "gpio-keys";
    ...
};

leds {                      /* LED：只有 GPIO */
    compatible = "gpio-leds";
    ...
};

regulator-fixed {           /* 固定电源：只有一个 GPIO 使能脚 */
    compatible = "regulator-fixed";
    ...
};
```

这类设备的共同点：**在设备树里有节点、需要驱动、但不属于任何真实总线**。所以 platform 更像"没地方去的都来这儿"，而不是"内存映射设备的专用总线"。

## 六、选型判断（工程上很好用）

| 你的设备 | 该挂哪条总线 |
|---|---|
| SoC 内部的 UART / I2C 控制器 / GPIO 控制器 / 定时器 | platform |
| 挂在 I2C 上的 sensor / EEPROM | i2c |
| 挂在 SPI 上的 flash / codec / 显示屏 | spi |
| USB 设备 | usb |
| PCIe 设备 | pci |
| 只有 GPIO、没有寄存器的按键 / LED / 固定电源 | platform |

## 七、一句话总结

**能被硬件自己报出身份的（PCI/USB）走枚举；报不出来的（SoC 外设、I2C/SPI 从设备）必须靠设备树提前告诉内核——platform 就是给后者准备的那条"虚拟总线"。**
