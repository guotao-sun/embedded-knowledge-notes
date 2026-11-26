# Linux 驱动核心骨架（总线驱动模型）

## 一、先说结论

内核驱动是**四层接力**，不是"一个 probe 函数打天下"：

```text
driver core（统一规则）→ 子系统（SPI/I2C/platform）→ controller（碰寄存器）→ 具体设备驱动（业务）
```

每一层只做一件事，靠"统一接口 + 私有扩展"嵌在一起：

- **driver core** 只管通用的 `struct device`，不关心任何子系统的私有字段
- **子系统**（SPI/I2C/platform）在通用结构上长出自己的一套 `device` / `driver`
- **controller** 才是真正操作寄存器、DMA、中断的那一层
- **设备驱动**（sensor、flash、lcd）只写业务

关键的一句话：**bus 只负责"怎么匹配"，probe 永远属于 driver。**

## 二、四层各自干什么

```text
1️⃣ driver core（统一规则）
    - device
    - driver
    - bus
    - match / probe

2️⃣ 各种子系统（SPI / I2C / platform）
    - 定义自己的 device / driver
    - 复用 driver core

3️⃣ controller（硬件入口）
    - 真正操作寄存器 / DMA / 中断

4️⃣ 具体设备驱动
    - 业务逻辑（sensor / flash / lcd）
```

判断某个函数属于哪一层，有个好用的办法：**看它操作的是通用结构还是私有结构**。操作 `struct device` / `struct kobject` 的是 core；操作 `struct spi_device`、`struct i2c_client` 的是子系统；操作 `readl/writel` 的是 controller。

## 三、bus 只是定义了一套规则

- `match()` 是 bus 制定的"游戏规则"，是 bus 提供的服务，**不是 driver 的**
- 一个 `struct bus_type` 上通常只有 `match`、`uevent`、`pm`，`probe` 字段基本不用

platform 总线没有 `bus->probe`，SPI 也没有，只有极少数特殊总线（PCI 之类）才覆盖 `bus->probe`，去处理"总线级"的特殊探测。

所以"设备是怎么 probe 起来的"这条路径永远长这样：

```text
某某_register_driver()
    → driver_register()
        → bus_add_driver()
            → driver_attach() / __driver_attach()   ← 遍历设备，调 bus->match
                → really_probe()
                    → dev->bus->probe(dev)           ← platform 这里是中间层 platform_drv_probe
                        → drv->probe(dev)            ← 你写的 probe
```

## 四、SPI Bus 属于 SPI Core

或者说：**SPI Core 包含了 SPI Bus**。`spi_bus_type` 只是 core 里的一块，注册总线、注册控制器、注册设备、收发数据，全在 core 里：

```text
SPI Core
    ├── spi_bus_type
    ├── spi_register_controller()
    ├── spi_unregister_controller()
    ├── spi_add_device()
    ├── spi_register_driver()
    ├── spi_match_device()
    ├── spi_sync()
    ├── spi_async()
    └── ...
```

`spi_sync` / `spi_async` 这类"对外 API"同样不是放在 bus 结构体里的，实现就在 `spi.c` 里。

## 五、为什么一个叫 register，一个叫 add

因为这两类对象的**生命周期归属**完全不同：

| | `spi_register_driver` | `spi_add_device` |
|---|---|---|
| 语义 | 向总线"声明自己" | 被某个对象"添加进来" |
| 谁拥有 | 驱动自己（主动注册） | 控制器（owned by controller） |
| 类比 | 你去物业登记 | 物业把新住户登记进楼栋 |

驱动是主动注册的，设备是被驱动添加的。名字不是随手起的，是生命周期模型的直接反映。

## 六、DTS 只存"静态常量"，驱动做"动态操作"

这是内核几十年演进出来的工程实践：**设备树只描述"硬件长什么样"，probe 里做资源申请与初始化**。

- DTS 里写寄存器基址、中断号、GPIO、时钟——都是硬件事实
- probe 里 `devm_ioremap_resource()`、`devm_request_irq()`、`devm_clk_get()`——都是运行时动作

这样同一份驱动可以配不同板子，改 DTS 就够了，不用改代码。

## 七、driver core 只处理通用的 struct device

`struct device` 不是"设备的全部信息"，而是**所有设备的最小公共集合**（common denominator）：

```c
struct device {
    struct device *parent;
    struct bus_type *bus;          /* 挂在哪个总线 */
    struct device_driver *driver;  /* 匹配成功后才有 */
    void *driver_data;             /* 子系统/驱动私有数据 */
    struct kobject kobj;           /* sysfs 里的那个目录 */
    ...
};
```

子系统把私有信息"嵌"进去：

```c
struct spi_device {
    struct device dev;      /* 第一个成员就是通用设备 */
    struct spi_controller *controller;
    u32 max_speed_hz;
    ...
};
```

所以 `dev` 和 `spi_device` 之间只差一个 `container_of()`——这不是冗余，是分层。

## 八、内核到底是怎么匹配的

匹配顺序是**"设备树优先，驱动表内按序"**：

1. 取设备树 `compatible` 属性里的**第 1 个**字符串（最具体的那个）
2. 拿它去驱动的 `of_device_id` 表里**从头到尾**（按数组顺序）找
3. 找到就匹配成功，**立即停止，不再往下看**
4. 第 1 个没找到，再取 `compatible` 的**第 2 个**字符串，重复

这也是为什么 `compatible` 常写成 `"vendor,chip", "vendor,family"`——第一个精确匹配，第二个兜底兼容。

匹配成功之后，`__driver_attach` 里会做两件事：

```c
dev->driver = drv;        /* 先把关系绑上 */
...
pinctrl_bind_pins(dev);   /* 再配好引脚复用 */
```

> 所以**设备树 compatible 一匹配上，pinctrl 就先于你的 probe 把引脚配好了**，等你进 probe 时通信链路已经可用。详见 [pinctrl 与 GPIO](./DRIVER-16-子系统-pinctrl与GPIO.md)。

## 九、Linux 内核代码的风格

Linux 倾向"**函数短 + 调用链深**"，而不是"一个大函数做到底"。原因是复杂系统里：

- 短函数容易测、容易改
- 深调用链把"策略"和"机制"分开，子系统可以插在中间
- 出问题时 `dump_stack()` 一看调用链就知道走到哪一层

代价是"想搞清一件事要看七八个文件"，这也是读内核最劝退的地方——但只要抓住"每一层只干一件事"，链路就能拆开。

## 十、一句话总结

**driver core 定规则，子系统做扩展，controller 碰硬件，驱动写业务；bus 只会 match，probe 永远是 driver 的事。**
