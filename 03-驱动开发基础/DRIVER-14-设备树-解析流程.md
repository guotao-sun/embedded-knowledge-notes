# 设备树解析流程

## 一、先说结论

设备树解析分**两段**，中间隔着"驱动什么时候加载"：

```text
第一段（内核早期，跟驱动无关）：DTB → device_node 树
第二段（驱动 probe 时）：       device_node 树 → 读属性 → 配硬件
```

- **第一段是纯数据结构转换**：`unflatten_device_tree()` 把 DTB 的字节流变成内核里的 `struct device_node` 链表树，不涉及任何硬件语义、不依赖任何驱动
- **第二段才是硬件动作**：驱动或子系统读 `reg` / `interrupts` / `fsl,pins`，然后 `ioremap`、注册中断、写复用寄存器
- `/sys/firmware/devicetree` 和 `/proc/device-tree` 只是**视图层**，不是解析机制本身

## 二、注意事项

- `/sys` 和 `/proc` 都只是"展示"，真正被驱动使用的是内核已经展开好的 `device_node` 树
- `imx_pinctrl_parse_groups()` 解析的是 `struct device_node`（内核内存中的设备树结构），不是 DTB 文件
- `/sys/firmware/devicetree` 和 `/proc/device-tree` 只是 device tree 的调试/兼容"视图层"，不是核心机制，可以在内核配置中关闭，但不能理解为可随意删除的运行时组件——很多"用 cat 看设备树"的现场排查都靠它
- `unflatten_device_tree()` 完全不依赖任何驱动（包括 SoC 适配驱动）。它只做：**纯数据结构构建**，本质就是把 DTB（二进制设备树）解析成内核的 `device_node` 树结构

## 三、解析流程

```text
Bootloader (U-Boot)
        ↓
DTB 传入内核
        ↓
start_kernel()
        ↓
setup_arch() → unflatten_device_tree()
    （实现位置：drivers/of/fdt.c）
        ↓
内核得到 device_node（核心节点）
        ↓
根据 device_node 创建用户接口映射（可选）：
    /sys/firmware/devicetree
    /proc/device-tree（兼容）
        ↓
of_platform_populate()（arch_initcall 级别）
        ↓
platform_device 被创建 → 开始 device/driver 匹配
        ↓
driver probe（依赖 device_node）
        ↓
imx_pinctrl_parse_groups()
        ↓
pinctrl 生效（写寄存器）
```

注意最后两行：**pinctrl 的解析发生在 probe 阶段**，而 `device_node` 的建立在 `start_kernel` 阶段——中间隔了几百毫秒，两者不是一回事。

## 四、关键阶段说明

| 阶段 | 函数 | 作用 |
|------|------|------|
| DTB 传入 | Bootloader 完成 | 将 DTB 地址通过寄存器传给内核（ARM32 用 `r2`，ARM64 用 `x0`） |
| 初步扫描 | `early_init_dt_scan()` | 只读必要节点（`/chosen`、`/memory`），建立早期可用内存信息 |
| 解析 DTB | `unflatten_device_tree()` | 纯数据结构解析，DTB → `device_node` 树 |
| 视图层创建 | 可选 | 创建 `/sys/firmware/devicetree`、`/proc/device-tree` 等调试接口 |
| 建 platform 设备 | `of_platform_populate()` | 把 `simple-bus`/`soc` 下的子节点变成 `platform_device` |
| 驱动使用 | `probe()` 中 | 驱动通过 `of_*` API 读取 `device_node` 中的属性 |
| 硬件配置 | 各子系统 | 如 pinctrl 解析后写寄存器配置引脚复用 |

`early_init_dt_scan()` 为什么必须单独有一步：**那时候内存管理还没起来**，只能先解析 `/memory` 知道有多少 RAM、`/chosen` 知道 `stdout-path` 和 `bootargs`，否则连打印都出不来。

## 五、驱动侧的 of_* API

```c
/* 1. 判断节点有没有某个属性 */
if (of_property_read_bool(np, "gpio-poweroff")) ...

/* 2. 读整数数组 */
of_property_read_u32(np, "clock-frequency", &rate);
of_property_read_u32_array(np, "reg", vals, 2);

/* 3. 按名字读 GPIO */
desc = gpiod_get(dev, "led", GPIOD_OUT_LOW);      /* led-gpios 属性 */

/* 4. 遍历子节点 */
for_each_available_child_of_node(np, child) { ... }

/* 5. 按名字取子节点 */
of_get_child_by_name(np, "port");
```

这些 API 的操作对象**全部是内存里的 `device_node`**，跟 DTB 文件已经没关系了。

## 六、一个常见误解

> "设备树解析要等 pinctrl 驱动起来才能做吧？"

不对。`unflatten_device_tree()` 在 `setup_arch` 里就跑完了，那时候连 `kmalloc` 都还没完全可用（它用的是 memblock 早期分配）。pinctrl 驱动起来之后做的是**读属性 + 写寄存器**，属于"使用设备树"，不是"解析设备树"。

同理，`of_clk_add_provider`、`of_gpiochip_add` 这些也都是"消费"阶段的事。

## 七、一句话总结

**DTB 在内核启动最早期就被 `unflatten_device_tree()` 变成纯数据的 `device_node` 树（不依赖任何驱动），之后 `of_platform_populate()` 造设备、驱动 probe 时读属性配硬件——"解析"和"使用"是两段，别混。**
