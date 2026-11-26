# 设备树的概念

## 一、先说结论

- 设备树描述的是**硬件**，而"设备"只是硬件的一部分——所以设备树的范围**比设备模型更广**
- 它是**静态数据**：编译成 DTB 交给内核，内核解析成 `device_node` 树，驱动再去读属性
- 设备树**不描述驱动、不描述策略**，只回答"这台板子上有什么、在哪、连着谁"
- 有了设备树，同一份内核镜像可以配不同板子——这是 ARM 抛弃几千个 `board-xxx.c` 的直接原因

## 二、核心概念

**设备树属于硬件描述机制，而非设备描述机制。而硬件包括设备，因此硬件描述的概念更广。**

设备树是一种硬件拓扑与资源描述机制，它描述的是 SoC/板级硬件结构；Linux 设备模型中的 device 只是设备树描述对象中的一部分。

设备树的范围比设备模型更广，因为它不仅描述设备，还描述 CPU、内存、时钟、复位、电源域、总线等硬件资源。

一个直观的对照：设备树里有 `cpus`、`memory`、`chosen`、`aliases` 这些节点，它们跟"设备"毫无关系，但都是内核启动必需的。

## 三、层次关系

```text
Hardware Description (Device Tree)
        │
┌───────┼───────────────────┐
│       │                   │
Device Model  Resource Framework  Other Framework
│       │                   │
│       │                   │
platform/i2c/spi  clk/regulator  CPU/memory
        │
        │
      driver
        │
        │
     subsystem
        │
        │
   ALSA/GPIO/NET
```

- **Device Model**：把节点变成 device，找 driver
- **Resource Framework**：按节点里的 `clocks` / `regulators` / `resets` / `power-domains` 去建资源
- **Other Framework**：CPU、内存这类不参与 device/driver 匹配，但必须提前解析

三条线都从同一棵 `device_node` 树出发，但走的是不同的子系统。

## 四、三种文件形态

| 文件 | 内容 | 谁用 |
|---|---|---|
| `.dts` | 源码，文本 | 人写 |
| `.dtsi` | 被 include 的公共片段（SoC 级描述） | 板级 `.dts` include |
| `.dtb` | `dtc` 编译出的二进制 | Bootloader / 内核 |
| `.dtbo` | overlay 片段（运行时叠加） | 树莓派、部分嵌入式 |

典型组织方式：

```text
imx6ull.dtsi（SoC 级：所有外设寄存器地址、中断号）
    ↑ include
imx6ull-atk-emmc.dts（板级：哪个外设 status="okay"、接了哪些 pin）
    ↓ dtc
imx6ull-atk-emmc.dtb
```

**SoC 描述在 dtsi，板级差异在 dts**——这是分层，也是为什么一份 dtsi 能配十几块板。

## 五、设备树 vs 设备模型

| 概念 | 描述范围 | 典型内容 |
|------|---------|---------|
| **设备树（Device Tree）** | 硬件拓扑与资源 | CPU、内存、时钟、复位、电源域、总线、外设 |
| **设备模型（Device Model）** | 内核运行时的设备/驱动组织 | device、driver、bus、class |

设备树是"静态的硬件描述"，设备模型是"动态的内核运行时结构"。驱动在 probe 时从设备树读取硬件信息，然后创建设备模型对象。

一句话对照：

```text
设备树  = 图纸（编译进 dtb，开机不变）
设备模型 = 现场（运行时创建，可以热插拔、可以 unbind/bind）
```

## 六、几个必须记住的语法要点

```dts
/ {                                  /* 根节点 */
    model = "Freescale i.MX6ULL ...";/* 给人看的板名 */
    compatible = "fsl,imx6ull-14x14-evk";  /* 给内核看的匹配串 */

    chosen {
        stdout-path = &uart1;        /* 内核 earlycon/console 用 */
    };

    aliases {
        mmc0 = &usdhc1;              /* 固定编号，保证 /dev/mmcblk0 顺序稳定 */
    };

    soc {
        uart1: serial@02020000 {     /* uart1 是 label，serial@... 是节点名 */
            compatible = "fsl,imx6ul-uart", "fsl,imx6q-uart";
            reg = <0x02020000 0x4000>;
            status = "okay";         /* disabled 时内核直接跳过 */
        };
    };
};
```

四个关键字段：

- **`compatible`**：匹配驱动的唯一依据，可写多个（从具体到泛化）
- **`reg`**：寄存器基址 + 长度（`<地址 长度>`）
- **`status`**：`"okay"` / `"disabled"`，`for_each_available_child_of_node` 会跳过后者
- **`label`**（如 `uart1:`）：给 `&uart1` 引用用的名字，编译后变成 `phandle`

`&xxx` 引用的查找顺序：**先找 label，再找 `/aliases` 里的别名**（详见 [pinctrl 与 GPIO](./DRIVER-16-子系统-pinctrl与GPIO.md)）。

## 七、从源码到运行时

```text
dts/dtsi --dtc--> dtb --Bootloader--> 内核
    → unflatten_device_tree() 建立 device_node 树（内存里的结构）
    → of_platform_populate() 把节点变成 platform_device
    → 驱动 probe 时用 of_* API 读属性
```

调试时能直接看内核里那棵树：

```bash
ls /proc/device-tree/            # 兼容接口
ls /sys/firmware/devicetree/base # 新接口，内容一样
cat /proc/device-tree/model
```

> 这两个目录只是**视图层**，不是核心机制——真正被驱动用的是内存里的 `device_node`（详见 [设备树解析流程](./DRIVER-14-设备树-解析流程.md)）。

## 八、一句话总结

**设备树是硬件的静态图纸（连 CPU、内存都画），设备模型是运行时的现场；驱动通过 `compatible` 找到自己的节点，再读 `reg`、`interrupts`、`clocks` 这些属性去申请资源。**
