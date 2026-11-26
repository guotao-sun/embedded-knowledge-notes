# Linux 总线驱动模型设备创建顺序

## 一、先说结论

设备对象不是凭空来的，也不是"总线去发现的"，而是**一层一层的驱动把下一层造出来**：

```text
DTS（静态描述）→ platform_device → 控制器驱动 probe → i2c_adapter / spi_controller
                                                          ↓ 扫描子节点
                                                      i2c_client / spi_device
                                                          ↓ match
                                                       你的驱动 probe
```

- **DTS 全程只提供数据**，不创建任何对象
- **控制器驱动才是"造设备的人"**，它解析设备树子节点，逐个 `i2c_new_device` / `spi_add_device`
- 设备造好后才进 `bus->match`，匹配上才进你的 `probe`

## 二、以 I2C 为例：五步

```text
1. DTS 解析 → device_node（只是描述，没有对象）
2. I2C controller driver 注册 → i2c_adapter 出现
3. i2c-core 扫描 device_node 的子节点
4. 创建 i2c_client（真正的设备对象）
5. match driver → probe
```

第 3 步的触发点很具体：`i2c_add_adapter()` → `of_i2c_register_devices(adap)`，里面用 `for_each_available_child_of_node()` 遍历 adapter 节点的所有子节点，每个子节点造一个 `i2c_client`。

## 三、谁把 reg 填到 client->addr？

在内核里是 I2C 核心代码（不是你写的驱动），核心函数路径大致是：

```text
of_i2c_register_devices()
    ↓
of_i2c_get_board_info()      ← 读子节点的 reg / compatible
    ↓
info.addr = reg              ← 7 位地址从这里来
    ↓
i2c_new_device(adap, &info)
    ↓
client->addr = info.addr
```

设备树里写的就是这个：

```dts
&i2c1 {
    status = "okay";

    icm20608: imu@68 {              /* 68 是十六进制 7 位地址 */
        compatible = "invensense,icm20608";
        reg = <0x68>;
    };
};
```

**`reg` 就是 `client->addr`**，不用在驱动里再写一遍地址——这正是"设备树描述硬件、驱动只管逻辑"的分工。

### 遍历子节点的宏

```c
#define for_each_available_child_of_node(parent, child) \
    for (child = of_get_next_available_child(parent, NULL); \
         child; \
         child = of_get_next_available_child(parent, child))
```

`available` 的意思是**会跳过 `status = "disabled"` 的节点**——只遍历被使能的。

## 四、bus / driver / driver core 各干什么

| 角色 | 核心职能 |
|------|---------|
| **bus** | 1. match（判断 device 和 driver 是否匹配）<br>2. 提供统一管理机制（pm / uevent / sysfs） |
| **driver** | 1. probe（初始化设备）<br>2. remove（释放资源） |
| **driver core** | 在 match 成功后调用 probe / remove，并在失败时处理 cleanup |

> bus 的职责是定义"匹配规则"，probe 永远属于 driver，由 driver core 在 match 成功后统一调用。

> 不是所有 bus 都"只做 match/probe/remove"，而是所有 bus 都至少做这三件事，但很多 bus 还做更多（尤其 PCI / USB，涉及电源管理、配置空间、枚举）。

## 五、spi_sync / spi_async 在哪

不是放在 bus 结构体里的，也不是"只在头文件中"。它们是 SPI core 提供的"对外 API"，实现写在 `spi.c` 中：

```text
spi_sync()            ← 同步传输，内部会 sleep 等完成
    ↓
__spi_sync()
    ↓
spi_controller->transfer()   ← 最终落到控制器驱动实现的传输函数
```

`spi_async()` 则是不等待的回调式接口。**API 在 core，机制在 controller**，分工很清楚。

## 六、设备模型 vs 设备树

| 概念 | 本质 | 特点 |
|------|------|------|
| **设备模型（Driver Model）** | Linux 内核运行时模型（核心机制） | 逻辑关系模型，bus 平级注册 |
| **设备树（Device Tree）** | 硬件描述数据（静态描述） | 硬件连接关系（拓扑） |

- bus 在 Linux device model 中是平级概念：platform / i2c / spi / usb / pci（并列 bus）
- `bus_register()` 只是在 Linux 内核里"注册一种总线类型"，不依赖任何硬件控制器
- bus = 软件抽象层（规则 + 组织方式）
- 总线下的设备是由相应的控制器驱动从设备树解析出来并创建的

### 设备模型的结构

```text
Linux 设备模型
────────────────────────────────
bus framework 层
┌────┬────┬────┬─────────┐
│    │    │    │         │
platform i2c spi usb   pci
│    │    │    │
└──── device / driver binding ────┘
```

**为什么强调"平级"**：platform 不是 i2c 的父总线。虽然 i2c 控制器本身是一个 platform 设备，但 `i2c_client` 挂的是 `i2c_bus_type`，不挂 platform——"控制器是 platform 的孩子"和"控制器管出来的设备属于 i2c 总线"是两件事。

### 设备树模型（容易画反）

```text
device model（设备模型）
─────────────────────────────────────
bus（总线框架） platform / i2c / spi / usb / pci
─────────────────────────────────────
device（设备）  driver（驱动）
```

## 七、为什么 I2C 必须依赖外部描述

I2C 这种总线，本质上是"**无自描述能力**"的总线：

- 电气上只有 SDA/SCL 两根线，没有任何"你是谁、地址多少"的协商机制
- 主设备只能按地址盲发，地址错了就是没人应答（`Remote I/O error`）
- 所以必须靠 DT/ACPI **在外面把地址告诉内核**

对比 USB：插上就能读描述符、分配地址，属于"可枚举"，不需要设备树。详见 [Platform 与其他总线的区别](./DRIVER-12-总线-Platform与其他总线区别.md)。

## 八、一句话总结

**DTS 只描述、控制器驱动才造对象：`i2c_add_adapter` 时 `of_i2c_register_devices` 遍历子节点，把 `reg` 填进 `client->addr`，造出 `i2c_client` 后才轮到 match 和 probe。**
