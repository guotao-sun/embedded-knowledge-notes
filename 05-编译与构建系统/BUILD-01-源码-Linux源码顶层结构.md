# Linux 源码顶层结构

## 一、先说结论

内核源码有 20 多个顶层目录，但**你 90% 的时间只在 4 个地方活动**：

| 你要做的事 | 去哪找 |
|---|---|
| 改某块板子的硬件描述（外设、引脚、时钟） | `arch/<arch>/boot/dts/` |
| 改 / 加一个设备驱动 | `drivers/`（音频在 `sound/`） |
| 看某个子系统的框架代码 | 对应顶层目录：`mm/ fs/ net/ kernel/` |
| 找一个结构体 / 宏的定义 | `include/` |

其余目录不是"不用看"，而是**按需再进**——先把这 4 个落点摸熟，再看子系统。

## 二、顶层目录一览

```
linux/
├── arch/           # 架构相关：启动代码、异常向量、平台代码、dts
├── drivers/        # 所有设备驱动（整个内核里最大的一块）
├── sound/          # 音频子系统（ALSA core + ASoC）
├── include/        # 头文件（linux/、asm/、uapi/）
├── kernel/         # 进程、调度、定时器、中断框架
├── mm/             # 内存管理（页表、slab、vmalloc）
├── fs/             # 文件系统（vfs + 各具体 fs）
├── net/            # 网络协议栈
├── ipc/            # 进程间通信（socket 之外的 msg/sem/shm）
├── block/          # 块设备层（bio、IO 调度）
├── lib/            # 通用库（string、crc、rbtree）
├── init/           # 内核启动入口 main.c
├── scripts/        # kbuild 脚本、dtc 设备树编译器
├── crypto/         # 加密算法
├── security/       # LSM 等安全模块
├── firmware/       # 固件加载框架
├── Documentation/  # 官方文档（含设备树 bindings）
└── tools/          # 用户态工具（perf、objtool）
```

## 三、四个常用落点

### 1. `arch/arm/boot/dts/` —— 板级描述

```bash
arch/arm/boot/dts/
├── imx6ull.dtsi                      # SoC 级公共描述（被板级 dts include）
├── imx6ull-14x14-emmc-4.3-480x272-c.dts   # 具体板子
├── imx6ull-14x14-evk.dts
└── Makefile                          # dtb-y += xxx.dtb
```

`.dtsi` 是 SoC 公共部分，`.dts` 是板子差异部分，最后 `include` 合成一棵完整的树。改硬件（加设备节点、改引脚复用）就在这一层。

### 2. `drivers/` —— 设备驱动

按总线/子系统分一级子目录：`i2c/ spi/ gpio/ input/ mmc/ net/ video/ gpu/ ...`。找驱动的顺序：

```bash
grep -rn "compatible = \"nxp,imx6ul-tsc\"" drivers/    # 有 compatible 就能直接定位
grep -rn "\.name.*= \"wm8960\""  sound/soc/codecs/      # 无 compatible 的按名字找
```

### 3. `sound/` —— 音频（ALSA + ASoC）

```
sound/
├── core/           # ALSA core：pcm.c control.c timer.c
├── soc/            # ASoC：soc-core.c soc-pcm.c soc-dapm.c
│   ├── codecs/     # 各 Codec 驱动（wm8960.c ...）
│   ├── generic/    # simple-card 通用 Machine
│   └── <vendor>/   # 厂商 platform / cpu-dai 驱动
└── usb/ pci/ ...
```

### 4. `include/` —— 头文件

| 路径 | 内容 |
|---|---|
| `include/linux/` | 内核通用 API（`module.h` `device.h` `gpio.h`） |
| `include/asm-generic/` | 各架构共用的 asm 级定义 |
| `arch/arm/include/asm/` | ARM 专有的 asm 定义 |
| `include/uapi/` | 暴露给用户态的头（ioctl 命令号常在这） |

## 四、一次真实查找：从设备树走到驱动代码

```bash
# 1. 板子上确认设备树里有没有这个节点
cat /proc/device-tree/sound/compatible

# 2. 回源码里用 compatible 定位驱动
grep -rn "simple-audio-card" sound/soc/generic/

# 3. 用函数名定位子系统实现
grep -rn "snd_soc_register_card" sound/soc/soc-core.c

# 4. 用结构体名查定义
grep -rn "struct snd_soc_card {" include/sound/
```

**顺序永远是"字符串 → 文件 → 函数 → 结构体"**，先在运行时确认现象，再回源码定位。

## 五、构建相关的文件（不在 drivers 里，但天天用）

| 文件 | 作用 |
|---|---|
| `Kconfig` | 配置项定义，生成 `.config` 的菜单 |
| `Makefile` | 每个目录都有，写 `obj-y` / `obj-m` |
| `scripts/Makefile.build` | 真正把 `obj-y` 展开成编译规则的脚本 |
| `.config` | 你的配置（`make menuconfig` 改的就是它） |
| `vmlinux` | 未压缩的内核 ELF（带符号，用 gdb/addr2line） |
| `System.map` | 符号地址表，oops 反查函数用 |
| `Module.symvers` | 导出符号的 CRC 表，编译外部模块需要 |

## 六、源码树必须和板子内核版本对上

模块的 `vermagic`（内核版本 + 配置指纹）必须与运行内核一致，否则 `insmod` 直接报：

```text
insmod: ERROR: could not insert module xxx.ko: Invalid module format
```

所以 `KERNELDIR` 指向的必须是**同一份、且已编译过**的源码树——不是"随便一个 4.x 内核"。查板子版本：

```bash
uname -r          # 例如 4.1.15-g3dc0a4b
```

## 七、源码体积与查找技巧

```bash
du -sh drivers/ sound/ arch/     # 看哪块最大（drivers 通常 1G+）
find . -name "*.c" -path "*i2c*"  # 按路径+名字筛
grep -rn "关键词" --include=*.c --include=*.h drivers/
```

大仓库里 `grep -rn` 全量扫会慢，**先缩目录**（`drivers/i2c/`）再扫；`--include` 比事后过滤快得多。

## 八、一句话总结

**改硬件去 `arch/arm/boot/dts`，改驱动去 `drivers`（音频去 `sound`），找定义去 `include`；其余目录等你要看那个子系统时再进，别一上来就在 20 个目录里乱翻。**
