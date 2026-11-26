# GPIO 子系统

## 一、先说结论

- 设备树里 GPIO 永远是**三元组**：`<控制器 phandle  引脚号  flags>`
- 老 API 是"整数 GPIO 号"（`of_get_named_gpio` + `gpio_request` + `gpio_set_value`），新 API 是"描述符"（`gpiod_get` + `gpiod_set_value`），**新代码一律用 gpiod**
- 申请 GPIO 必须带 **label**，它决定 `/sys/kernel/debug/gpio` 里显示"谁占用了这根针"
- GPIO 的中断号不写在设备树里，靠 `gpiod_to_irq()` 现算

## 二、设备树固定写法

GPIO 子系统在设备树中的固定格式：

```text
< phandle  pin  flags >
```

示例：

```dts
<&gpio0 RK_PC0 GPIO_ACTIVE_HIGH>
```

结构解析：

```text
<&gpio0     RK_PC0       GPIO_ACTIVE_HIGH>
    │           │                  │
    │           │                  └─ 有效电平（flags）
    │           └──────────────────── GPIO 引脚（pin）
    └──────────────────────────────── GPIO 控制器（phandle）
```

一个属性里可以放多个三元组：

```dts
led-gpios = <&gpio1 3 GPIO_ACTIVE_HIGH>,
            <&gpio1 4 GPIO_ACTIVE_LOW>;
```

> 注意第 2 个引脚是 `GPIO_ACTIVE_LOW`——**同一组 LED 里可以有不同极性**，这正是 gpiod API 存在的理由。

## 三、驱动中获取 GPIO 号

### 1. of_get_named_gpio（老 API）

```c
of_get_named_gpio(np, "beep-gpios", 0);
```

第三个参数 `0` 为 **index**——第几个 GPIO。这个属性里可能有多个 GPIO，通过 index 取第几个。

```c
of_get_named_gpio(np, "led-gpios", 0);  // gpio1_3
of_get_named_gpio(np, "led-gpios", 1);  // gpio1_4
```

### 2. 解析流程

```c
gpioled.led_gpio = of_get_named_gpio(gpioled.nd, "led-gpio", 0);
```

```text
<&gpio0 RK_PC0 GPIO_ACTIVE_HIGH>
          │
          │ 经过 GPIO 控制器解析（gpiochip 的 of_xlate）
          ▼
      Linux GPIO 号（一个全局整数）
          │
          ▼
    gpioled.led_gpio
```

注意这个整数是**全局编号**，不能硬编码——不同板子、不同内核配置编号会变，所以只能运行时解析。

## 四、申请 GPIO

```c
gpio_request(gpioled.led_gpio, "LED-GPIO");
```

第二个参数 `"LED-GPIO"` 是给这次 GPIO request 起一个 **label（标签/名称）**，用于标识这个 GPIO 是被谁申请的。

申请之后要设方向：

```c
gpio_direction_output(gpioled.led_gpio, 0);
gpio_set_value(gpioled.led_gpio, 1);
```

**用完了要释放**（模块卸载时）：

```c
gpio_free(gpioled.led_gpio);
```

新 API 用 `devm_` 前缀可以省掉这步——设备卸载时自动释放：

```c
desc = devm_gpiod_get(&pdev->dev, "led", GPIOD_OUT_LOW);
```

## 五、新旧 API 对照

| 操作 | 老 API（整数号） | 新 API（描述符） |
|---|---|---|
| 从设备树取 | `of_get_named_gpio()` | `devm_gpiod_get()` / `gpiod_get()` |
| 申请 | `gpio_request()` | 由 `gpiod_get` 一并完成 |
| 设方向 | `gpio_direction_output()` | `gpiod_direction_output()` 或 `GPIOD_OUT_LOW/HIGH` |
| 写电平 | `gpio_set_value(gpio, 1)` | `gpiod_set_value(desc, 1)` |
| 读电平 | `gpio_get_value(gpio)` | `gpiod_get_value(desc)` |
| 释放 | `gpio_free()` | `devm_` 自动，或 `gpiod_put()` |
| 极性 | 驱动自己 `!value` | flags 自动处理 |

**为什么新 API 更好**：老 API 里"1 就是高电平"，低电平点亮的 LED 要在驱动里到处写 `!`；gpiod 里"1 就是有效"，极性写在设备树。

## 六、用 GPIO 当中断源

GPIO 中断是"这根针电平变了 → 触发中断"，所以要先拿到中断号：

```c
irq = gpiod_to_irq(desc);                  /* 新 API */
/* 或 */
irq = gpio_to_irq(gpioled.led_gpio);       /* 老 API */

ret = devm_request_irq(dev, irq, my_isr,
                       IRQF_TRIGGER_FALLING, "my-key", priv);
```

两个必须注意的点：

- **触发类型**（上升/下降/双边）在 `request_irq` 的 flags 里给，不是设备树里的 `interrupts` 属性
- **中断里不能睡眠**：不能 `msleep`、不能拿 mutex；要"消抖"就起个定时器或工作队列

## 七、查看 GPIO 占用情况

```bash
cat /sys/kernel/debug/gpio
```

输出形如：

```text
gpiochip0: GPIOs 0-31, parent: platform/209c000.gpio, 209c000.gpio:
 gpio-3   (LED-GPIO            ) out hi
 gpio-4   (key                 ) in  lo IRQ
```

- 第一列是全局 GPIO 号
- 括号里就是 `gpio_request` / `gpiod_get` 传的 **label**
- 后面是方向、电平、是否被用作 IRQ

**"引脚被占用但功能不对"时第一件事就是看这个文件**——如果 label 是别人的驱动，说明设备树重复声明了同一根针。

sysfs 还有一套老接口（`/sys/class/gpio/export`），现在只建议在用户态调试用，驱动里不要用。

## 八、常见返回码

| 返回值 | 含义 | 处理 |
|---|---|---|
| `-ENOENT` | 设备树里没有这个属性名 | 检查 `xxx-gpios` 拼写 |
| `-EPROBE_DEFER` | gpio 控制器还没注册好 | **返回它，让内核稍后重试**，不要当错误 |
| `-EBUSY` | 引脚已被别人申请 | 查 `/sys/kernel/debug/gpio` |
| `-EINVAL` | 引脚号越界 / 控制器不支持 | 核对引脚号 |

`-EPROBE_DEFER` 是新手最容易踩的坑：看到"probe 失败"就去改代码，实际上应该原样返回，内核会在依赖的控制器就绪后自动重新 probe。

## 九、一句话总结

**设备树给 `<控制器 引脚 flags>`，驱动用 `gpiod_get` 拿描述符、`gpiod_set_value` 写"有效/无效"；要中断就 `gpiod_to_irq` 现算，申请时带 label 方便在 debugfs 里认领。**
