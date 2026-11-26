# pinctrl 子系统与 GPIO 子系统

## 一、先说结论

一颗引脚上有**两个独立的开关**，分别归两个子系统管：

| 子系统 | 管什么 | 什么时候生效 |
|---|---|---|
| **pinctrl** | 引脚**复用功能**（GPIO / UART / I2C / SAI）+ 电气属性（上下拉、驱动强度、速率） | 驱动 probe **之前**，由 `pinctrl_bind_pins()` 自动完成 |
| **GPIO** | 当引脚被复用为 GPIO 后，**读电平 / 写电平 / 当中断源** | 驱动 probe 里自己调 `gpiod_*` |

**先后顺序不能反**：先 pinctrl 把引脚切到 GPIO 模式（或切到 UART 模式），GPIO 子系统才有意义。

一句话记：**pinctrl 决定"这根针干什么"，GPIO 决定"这根针是高还是低"。**

## 二、IO 结构：Pin 与 Pad

```text
物理 Pin（封装引出的管脚）
      │
      │
Pad IO 电气单元（pad 包括 Pin Mux）
pinctrl 配置 Pin Mux + PAD 电气属性
      │
      ├────────────────┐
      │                │
  GPIO 功能        外设功能
      │                │
  gpio_chip     UART/SPI/SAI/I2C Controller
      │
GPIO Framework
```

- **Pin**：芯片封装出来的外部引脚（你能用镊子夹到的那块金属）
- **Pad**：芯片内部连接这个引脚的 IO 电路单元

一个 Pin 背后通常对应一个 Pad，Pad 决定这个 Pin 的电气属性和复用功能。

最典型的例子：i.MX6ULL 的 `GPIO1_IO03` 既可以是普通 GPIO（点 LED），也可以复用成 `UART1_TX`、`I2C1_SDA`、`PWM1_OUT`——**选哪个由 IOMUXC 寄存器里的 MUX_MODE 决定，这就是 pinctrl 干的活**。

## 三、pinctrl 框架怎么工作

```text
pinctrl 核心（通用框架，drivers/pinctrl/core.c）
        ↓ 根据 compatible 匹配
加载 SoC 专用 pinctrl 驱动（如 pinctrl-imx）
        ↓ 由这个驱动去解析 fsl,pins（私有格式）
写 IOMUXC 寄存器
```

**分层的意义**：核心框架只认"引脚、功能、组"这些通用概念，具体寄存器怎么摆、`fsl,pins` 怎么编码，全交给 SoC 驱动。所以换一颗芯片只用换 SoC 驱动，核心代码不动。

### Linux pinctrl 三步模型

`pinctrl_bind_pins` 内部执行三步：

| 步骤 | API | 作用 |
|------|------|------|
| **get** | `devm_pinctrl_get(dev)` | 获取所有状态集合（读 `pinctrl-N` 属性） |
| **lookup** | `pinctrl_lookup_state(p, "default")` | 按名字找某个状态对象 |
| **select** | `pinctrl_select_state(p, state)` | 真正配置硬件 IO（写寄存器） |

最终的配置调用链：

```text
pinctrl_bind_pins
        ↓
pinctrl_select_state
        ↓
pinmux_enable_setting
        ↓
ops->set_mux
        ↓
imx_pmx_set
        ↓
writel(mux_mode, base + mux_reg)
```

## 四、调用链：pinctrl 到底在 probe 的哪一步

这一条链是从"驱动注册"走到"你的 probe"的完整路径：

```text
驱动加载（insmod 或 内核内置）
        ↓
__platform_driver_register()          // platform_driver 注册入口
        ↓
driver_register(&drv->driver)         // 注册进内核设备模型
        ↓
bus_add_driver()                      // 挂到 platform 总线
        ↓
driver_attach()                       // 尝试绑定设备
        ↓
__driver_attach()                     // 遍历总线上的设备，调 bus->match
        ↓
driver_probe_device()                 // 找到匹配设备，准备探测
        ↓
really_probe()                        // ★ 核心探测函数 ★
        │
        ├── pinctrl_bind_pins()       // ★★ 在这里引脚复用已经配好了 ★★
        └── dev->bus->probe(dev)      // → platform_drv_probe()
                │
                ├── of_clk_set_defaults()   // 按 assigned-clocks 配时钟
                └── drv->probe(dev)          // ★ 你的 probe，此时引脚已可用 ★
```

> 实际代码里 `really_probe` 还有电源域、DMA 配置等旁支步骤，顺序细节各版本略有差异，但**"pinctrl 一定在 `bus->probe` 之前"**这条结论不变。

也就是说，**你的 probe 一进来，引脚复用和电气属性已经就绪**，外设通信链路可直接用。

所以驱动里**不需要**手动调 `pinctrl_select_state(default)`——内核已经替你做了。只有运行时切换状态（比如进休眠切到 `sleep`）才需要自己调：

```c
struct pinctrl *p = devm_pinctrl_get(dev);
struct pinctrl_state *s = pinctrl_lookup_state(p, "sleep");
pinctrl_select_state(p, s);
```

## 五、fsl,pins 六元组：pinctrl 私有数据格式

设备树里 `fsl,pins` 的每个 pin 由 **6 个 u32** 组成：

```dts
pinctrl_led: ledgrp {
    fsl,pins = <
        MX6ULL_PAD_GPIO1_IO03__GPIO1_IO03 0x10B0
    >;
};
```

第一个数是"复用宏"（内部已经编码了 mux_reg 和 mux_val），第二个是 pad 电气配置值。展开成 6 个数是这样：

```c
u32 pins[] = {
    mux_reg, mux_val, input_reg, input_val, config_reg, pad_ctrl
};

for (...) {
    mux_reg   = vals[i++];
    mux_mode  = vals[i++];
    input_reg = vals[i++];
    input_val = vals[i++];
    config    = vals[i++];
    pad_ctrl  = vals[i++];
}
```

驱动里最终就是一句：

```c
writel(mux_mode, base + mux_reg);
```

本质就是：

```c
*(mux寄存器) = mux_mode;
```

### 六个字段各是什么

| 字段 | 含义 | 归属 |
|---|---|---|
| `mux_reg` / `mux_val` | 复用选择寄存器的偏移与值 | 物理引脚属性 |
| `conf_reg` / `pad_ctrl` | 电气属性寄存器偏移与值（上下拉、驱动强度） | 物理引脚属性 |
| `input_reg` / `input_val` | 输入路径选择（某些复用需要从另一条线取输入） | **功能相关**，不是引脚固有 |

所以结构体是这么分的：

```c
struct imx_pin_reg {          /* 物理引脚属性：跟引脚绑定，一份 */
    s16 mux_reg;
    s16 conf_reg;
};

struct imx_pin {              /* 每个复用配置一份：input_reg 属于功能，不属引脚 */
    unsigned int pin;
    unsigned int mux_mode;
    u16 input_reg;
    unsigned int input_val;
    unsigned long config;
};

struct imx_pin_group {
    const char *name;
    unsigned npins;
    unsigned int *pin_ids;
    struct imx_pin *pins;
};
```

`groups` 就是设备树解析结果：`struct imx_pin_group *groups; unsigned int ngroups;`。

> 一句话理解：**mux_reg/conf_reg 是"这根针在芯片上的坐标"（一份），input_reg/input_val 是"这个功能走哪条输入线"（每个功能一份）**——所以前者放 `imx_pin_reg`，后者放 `imx_pin`。

## 六、pinctrl 状态配置

### pinctrl-names

状态名字，多个状态时：

```dts
pinctrl-names = "default", "sleep";
```

> `pinctrl-names` 必须写，否则驱动无法按名字查找——`pinctrl_lookup_state(p, PINCTRL_STATE_DEFAULT)` 会返回 `-ENODEV`，pinctrl 直接不生效，引脚保持复位默认状态。

### pinctrl-0 / pinctrl-1

- `pinctrl-0`：0 是"第 0 个 pinctrl 状态"的索引（index）
- `pinctrl-1`：1 是"第 1 个 pinctrl 状态"的索引（index）

```dts
pinctrl-names = "default", "sleep";
pinctrl-0 = <&pinctrl_led>;
pinctrl-1 = <&pinctrl_led_sleep>;
```

**`pinctrl-N` 的 N 与 `pinctrl-names` 的第 N 个字符串一一对应**——这是最容易写错的地方：名字写了两个，`pinctrl-0` 却指向 `sleep` 的组，就会"开机就进低功耗引脚状态"，现象是"外设完全没反应"。

### 为什么设计成数组？

因为一个设备可能有多个状态：

- `default`（正常工作）
- `sleep`（低功耗，引脚改成高阻或保持）
- `idle`（空闲）

切换时调 `pinctrl_select_state(...)` 即可，不用改驱动代码。

## 七、GPIO_ACTIVE_HIGH / LOW：极性由谁决定

驱动只用 `gpiod_set_value(desc, 1)` / `0`，**电平翻转由 flags 决定**：

| flags | 传 1 | 传 0 |
|-------|------|------|
| `GPIO_ACTIVE_HIGH` | 输出高电平 | 输出低电平 |
| `GPIO_ACTIVE_LOW` | 输出低电平 | 输出高电平 |

```c
gpiod_set_value(desc, 1);  // LED 总是亮，不管硬件是高激活还是低激活
```

这就是 gpiod API 相对老 `gpio_set_value()` 的最大价值：**"逻辑 1 = 有效"**，硬件是低电平点亮还是高电平点亮，写进设备树就行，驱动代码不用管。老 API 里你得自己写 `!value`，多一个板子就多一个坑。

## 八、注册顺序与完整示例

1. `insmod` → 注册 `platform_driver`
2. 内核根据 `compatible = "atkalpha-led"` 匹配驱动 `.of_match_table`
3. `really_probe` 里先 `pinctrl_bind_pins`，再进你的 probe——**一进 probe，就已经知道自己对应哪个设备树节点、引脚也已经配好**

### 设备树

```dts
pinctrl_led: ledgrp {
    fsl,pins = <
        MX6ULL_PAD_GPIO1_IO03__GPIO1_IO03 0x10B0
    >;
};

led {
    compatible = "atkalpha-led";

    pinctrl-names = "default";
    pinctrl-0 = <&pinctrl_led>;

    led-gpios = <&gpio1 3 GPIO_ACTIVE_HIGH>;
};
```

### 驱动代码

```c
struct gpio_desc *desc;

static int led_probe(struct platform_device *pdev)
{
    desc = devm_gpiod_get(&pdev->dev, "led", GPIOD_OUT_LOW);
    if (IS_ERR(desc))
        return PTR_ERR(desc);

    gpiod_set_value(desc, 1);
    return 0;
}
```

## 九、gpiod 调用流程

```text
设备树
    ↓
led-gpios = <&gpio1 3 ...>
    ↓
gpiod_get(dev, "led", ...)           ← 属性名 = "led" + "-gpios"
    ↓
of_get_named_gpiod_flags()
    ↓
找到 gpio1（gpiochip）
    ↓
创建 gpio_desc（第 3 个引脚，含 flags 极性）
    ↓
gpiod_direction_output()
    ↓
gpio_chip->direction_output()
    ↓
写 GDIR 寄存器（设方向）
    ↓
gpiod_set_value()
    ↓
gpio_chip->set()
    ↓
写 DR 寄存器（设电平）
```

**注意属性名规则**：`gpiod_get(dev, "led", ...)` 找的是 `led-gpios`（新规范），老写法 `led-gpio` 也兼容。名字写错就返回 `-ENOENT`。

## 十、备注：GPIO 上电默认状态

芯片在上电后、内核软件初始化之前，所有 GPIO 会进入一个确定的、安全的状态。这个状态通常在芯片数据手册的"GPIO 章节"或"系统复位与控制章节"有明确说明。

主要有两种安全机制：

- **默认高阻态（Hi-Z）**：大多数 IO 口复位后默认为高阻态的输入模式。相当于引脚内部和电路断开了，电平由外部电路决定。这能极大避免短路，因为高阻态下引脚不会主动输出高或低电平来对抗外部电路。
- **默认内部上下拉**：部分关键引脚（如启动配置脚、调试接口）在复位后会有确定的内部弱上拉或下拉，确保其在软件配置前有确定的逻辑电平。

工程含义：**从上电到 probe 之间有一段"没人管"的窗口**。如果外部电路在这段时间需要确定电平（比如功率器件的使能脚），必须靠硬件下拉/上拉电阻兜底，不能指望软件。

> 相关缩写：**SNVS** = Secure Non-Volatile Storage（i.MX 的 siempre-on 电源域）；**gpiod** 的 d = descriptor（描述符）。

## 十一、一句话总结

**pinctrl 在 `really_probe` 里、你的 probe 之前就把引脚复用和电气属性写好了；GPIO 子系统只负责"这根已经是 GPIO 的针，读它/写它/用它当中断"，极性交给设备树的 ACTIVE_HIGH/LOW。**
