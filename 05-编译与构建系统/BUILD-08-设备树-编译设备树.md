# 编译设备树

## 一、先说结论

设备树的三件套关系：**`.dtsi`（SoC 公共） + `.dts`（板子差异） → dtc 编译 → `.dtb`（二进制）**。

三个最容易卡住的地方：

| 问题 | 真相 |
|---|---|
| 改了 `.dts` 但板子行为没变 | 改的 dts **不是** U-Boot 实际加载的那个；看 `fdt_file` |
| 编译后找不到 `.dtb` | 该 dts 没在 `arch/arm/boot/dts/Makefile` 的 `dtb-y` 里 |
| 手写 `phandle = <0x50>` | 不该手写——用 label 引用，dtc 自动分配 |

## 二、确认板子当前用的是哪份设备树

### 方法一：板子上看运行时展开的设备树

```bash
cat /proc/device-tree/compatible | tr '\0' '\n'    # 兼容性字符串（可能有多条）
cat /proc/device-tree/model | tr '\0' '\n'        # 板子型号描述
cat /proc/device-tree/chosen/bootargs | tr '\0' '\n'   # 顺便看启动参数
```

`compatible` 是**驱动匹配用**的字符串（对应源文件里的根节点 `compatible` 属性），`model` 是给人看的。两者都改过的话，能据此反推是哪份 dts。

### 方法二：U-Boot 里看 `fdt_file`

```bash
=> print fdt_file
fdt_file=imx6ull-14x14-emmc-4.3-480x272-c.dtb
=> printenv | grep fdt        # 环境变量里所有和 fdt 有关的
```

**这就是"改 dts 不生效"的根因**：U-Boot 只按 `fdt_file` 这个名字去 boot 分区里找 `.dtb`。你在内核里编了新 dts，但：

1. 新 dtb 名字不等于 `fdt_file` → 根本不被加载；
2. 或者旧 dtb 还在同目录、你没覆盖它 → 加载的还是旧的。

## 三、切到另一份设备树（不改代码）

```bash
=> setenv fdt_file imx6ull-14x14-emmc-4.3-800x480-c.dtb
=> saveenv          # 写进环境变量存储区（eMMC/Flash 的环境分区）
=> boot
```

`saveenv` 不做的话，重启就回到旧值——这是第二个高频"改了没生效"。

救砖思路：换回一份确定能启动的 dtb。

```bash
=> setenv fdt_file imx6ull-14x14-emmc.dtb
=> saveenv
=> boot
```

## 四、编译设备树

```bash
export ARCH=arm
export CROSS_COMPILE=/usr/local/arm/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-
```

两种编译位置，效果一样：

```bash
# ① 内核根目录下（推荐）
make dtbs

# ② dts 目录下（-C 回根目录，仍然只做 dtbs 目标）
cd arch/arm/boot/dts
make -C ../../../../ dtbs
```

只要一个：

```bash
make arch/arm/boot/dts/imx6ull-14x14-emmc-4.3-480x272-c.dtb
```

产物：

```bash
arch/arm/boot/dts/*.dtb
```

**编译不出来只有一个原因**：该 dts 没写进同目录的 `Makefile`：

```makefile
dtb-$(CONFIG_SOC_IMX6ULL) += imx6ull-14x14-emmc-4.3-480x272-c.dtb
```

`dtb-y` 决定"哪些 dts 参与 `make dtbs`"，不在这里的 dts 永远不会被编译。

## 五、`dtsi` 与 `dts` 的关系

```dts
/* imx6ull.dtsi —— SoC 级公共描述，被所有板子 include */
/ {
    soc {
        uart1: serial@02020000 { compatible = "fsl,imx6ul-uart"; status = "disabled"; };
    };
};

/* imx6ull-xxx-board.dts —— 板子差异，引用 label 覆盖属性 */
#include "imx6ull.dtsi"
&uart1 {
    pinctrl-names = "default";
    pinctrl-0 = <&pinctrl_uart1>;
    status = "okay";          /* 打开：把 disabled 覆盖成 okay */
};
```

三条铁律：

1. `.dtsi` 里默认 `status = "disabled"`，板子想用就 `status = "okay"`；
2. `&label` 覆盖属性能"追加/替换"，但**不能改变节点类型**；
3. `#include` 是文本包含，`/include/` 也是，别和 C 的 `#include` 混淆。

## 六、把 dtb 拷到板子

```bash
# 先备份板上旧的，再覆盖
ssh root@192.168.55.71 'cp /run/media/mmcblk1p1/imx6ull-14x14-emmc-4.3-480x272-c.dtb \
                       /run/media/mmcblk1p1/imx6ull-14x14-emmc-4.3-480x272-c.dtb.bak'

scp arch/arm/boot/dts/imx6ull-14x14-emmc-4.3-480x272-c.dtb \
    root@192.168.55.71:/run/media/mmcblk1p1/
```

**备份这一步别省**：dtb 写坏（比如时钟配错）表现是"卡在启动、串口无输出"，那时你连 SSH 都进不去，只能靠备份 dtb 从 U-Boot 里救回来。

## 七、反编译：从 dtb 回到 dts

```bash
# 用内核自带的 dtc（版本和内核匹配，别用系统里的旧 dtc）
cd kernel/scripts/dtc
./dtc -I dtb -O dts \
      imx6ull-14x14-emmc-4.3-480x272-c.dtb \
      -o imx6ull-14x14-emmc-4.3-480x272-c.dts
```

用途：

- 确认**板子上实际跑的那份 dtb** 里到底写了什么（和源码对照，能立刻发现"源码改了但没编进去"）；
- 找不到源码时，从 dtb 反推硬件描述。

注意反编译结果里 **label 全丢了**，只剩下数字 `phandle`，所以别指望反编译回来的 dts 能直接再编回去用。

## 八、phandle 别手写

反编译出来的 dts 里会看到：

```dts
codec: wm8960@1a {
    phandle = <0x4e>;
};
sound {
    audio-codec = <&codec>;    /* 反编译后可能变成 <0x4e> */
};
```

有人发现"当前最大是 `0x4e`，那我手写 `0x50` 就安全了"。**这个做法能跑，但很脆**：

- phandle 必须是全树唯一；手写的值可能与某个 `dtsi` 里已有的值撞车；
- 内核里多处按 phandle 反查节点，撞车会表现为"某个设备莫名拿到别人的资源"。

**正确做法**：在源码里写 label 引用，让 dtc 自己分配：

```dts
sound {
    audio-codec = <&wm8960>;     /* 编译时 dtc 自动给 wm8960 分一个 phandle */
};
```

只有在**手工改反编译 dts 又无法回到源码**（临时验证）时，才临时用"取一个没用到的值"的土办法，验证完必须回到源码改。

## 九、查看运行时设备树

```bash
ls /proc/device-tree                       # 看有哪些顶层节点
ls /proc/device-tree/sound                 # 看某个节点的属性文件
cat /proc/device-tree/sound/compatible | tr '\0' '\n'
```

`/proc/device-tree` 是**内核启动时把 dtb 展开成目录**的结果（`of_` 框架生成），只读，改不了。属性和值都是文件：字符串是裸文本、数字是 4 字节大端、`stringlist` 是多个 `\0` 分隔——所以要看懂就得 `hexdump`：

```bash
for f in /proc/device-tree/sound/*; do
    echo "---- $f ----"
    hexdump -C "$f" | head -4
done
```

## 十、常见报错

| 报错 | 原因 | 修法 |
|---|---|---|
| `ERROR (phandle_references): Reference to non-existent node or label "xxx"` | `&label` 引用了不存在的节点 | 查 label 拼写，或该节点在对应的 dtsi 里没被包含 |
| `ERROR (duplicate_label): Duplicate label 'xxx'` | 同一 label 定义两次 | 改名，或确认没重复 include |
| `Warning (unit_address_vs_reg)` | 节点名有 `@地址` 但缺 `reg`，或反之 | 补 `reg` 或去掉 `@` |
| `make dtbs` 没产物 | dts 没进 `dtb-y` | 加进 Makefile |
| 拷了 dtb 但板子行为没变 | `fdt_file` 指向别的文件 / 没覆盖旧的 | `print fdt_file`、比对 MD5 |
| 启动卡死、串口无输出 | dtb 里时钟/引脚配错 | U-Boot 里换回备份 dtb |

## 十一、一句话总结

**`make dtbs` 出 `.dtb`，能不能生成看 `dtb-y`，板子加载哪一份看 `fdt_file`；看运行时用 `/proc/device-tree`，反编译用内核自带 `dtc`，phandle 交给 dtc 自动分配、别手写。**
