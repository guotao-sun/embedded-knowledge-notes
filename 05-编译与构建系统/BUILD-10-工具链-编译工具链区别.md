# 嵌入式 Linux 编译工具链的区别

## 一、先说结论

名字长这样的一串，**每一段都有含义**，不是随便起的：

```text
aarch64-linux-gnu-gcc
   ↑      ↑    ↑  ↑
 架构   目标OS  C库 编译器
```

对比 RK3568 SDK 里常用的两个：

```text
aarch64-linux-gnu-gcc        → 应用（用户态），链接 glibc
aarch64-none-linux-gnu-gcc   → 内核 / U-Boot，不依赖 C 库
```

**区别不在"能不能编"，在"默认链接什么、默认带不带 sysroot"**。

## 二、名字逐段拆开

| 段 | 取值 | 含义 |
|---|---|---|
| 架构 | `arm` / `aarch64` / `arm-none-eabi` | 目标 CPU 指令集（32 位 / 64 位 / 裸机） |
| 目标 OS | `linux` | 面向 Linux（有系统调用、ELF 动态链接） |
| 目标 OS | `none` | 不假定任何 OS，可为裸机或内核 |
| C 库 | `gnu` | glibc（GNU C Library） |
| C 库 | `eabi` / `eabihf` | 裸机 ABI / 带硬浮点的 EABI |
| — | `hf` 后缀 | hard float，浮点参数用 FPU 寄存器传 |

所以：

- `arm-linux-gnueabihf-gcc` = ARM 32 位 + Linux + glibc + 硬浮点 → **i.MX6ULL 应用**
- `aarch64-linux-gnu-gcc` = ARM 64 位 + Linux + glibc → **RK3568 应用**
- `aarch64-none-linux-gnu-gcc` = ARM 64 位 + 无 C 库假定 → **RK3568 内核 / U-Boot**

## 三、为什么内核不用应用那个 gcc

严格说：**Linux 内核可以用带 glibc 的工具链编，很多时候也能成功**。Rockchip 选 `none` 版本是出于工程整洁：

1. **内核不链接 glibc**：内核自己实现了 `memcpy`/`printk` 等，不依赖用户态 C 库。用 `none` 的工具链，编译参数里不会偷偷带 `-lc`、不会带 crt 启动文件，出问题少一类。
2. **和 U-Boot 统一**：U-Boot 也是 freestanding 环境，SDK 让两者共用一套 `none` 工具链，减少"两套工具链版本不一致"的坑。
3. **避免 sysroot 干扰**：应用工具链常带 sysroot（指向某个 rootfs 的 staging 目录），编内核时若被误用，头文件搜索路径会混入用户态头，出现离奇的编译错误。

反过来：**用 `none` 的工具链编应用也能编**，只是要自己补 `-lc`、`--sysroot`、动态链接器路径，麻烦且易错。

## 四、sysroot 到底是什么

```text
--sysroot=/opt/fsl-imx-x11/4.1.15-2.1.0/sysroots/cortexa7hf-neon-poky-linux-gnueabi
```

它就是"**目标板的根文件系统副本**"。编译器会把：

| 编译器默认路径 | 换成 sysroot 下的 |
|---|---|
| `/usr/include` | `<sysroot>/usr/include` |
| `/usr/lib` | `<sysroot>/usr/lib` |
| `crt1.o`、`crti.o` 等启动文件 | `<sysroot>/usr/lib/...` |

这样交叉编译时不用手写一堆 `-I/-L`，而且**保证用的是目标架构的库**。

判断工具链是否自带 sysroot：

```bash
aarch64-buildroot-linux-gnu-gcc -print-sysroot
# 打印出路径 → 自带；打印 "/" 或空 → 没配
```

## 五、怎么确认工具链真的匹配目标板

```bash
# 1. 看它自己声称的目标
arm-linux-gnueabihf-gcc -dumpmachine
# arm-linux-gnueabihf

# 2. 看编出来的二进制
file hello
# ELF 32-bit LSB executable, ARM, EABI5, dynamically linked ...

# 3. 看 ABI 细节（浮点、架构版本）
arm-linux-gnueabihf-readelf -A hello | head -20
# Tag_CPU_arch: v7
# Tag_ABI_VFP_args: VFP registers    ← 硬浮点标志
```

第 3 条最关键：`Tag_ABI_VFP_args` 缺失 = 软浮点编的。软浮点编的程序跑在硬浮点系统上，涉及 `float` 传参的函数（`printf("%f")`、数学库）会算出垃圾值，而且**不报错**。

## 六、混用的后果

| 混用方式 | 后果 |
|---|---|
| 硬浮点系统 + 软浮点库 | `Illegal instruction`，或浮点结果全错 |
| 32 位程序 + 64 位系统 | `cannot execute binary file`（除非系统装了 32 位兼容库） |
| 应用工具链编内核 | 可能编过，也可能因包含用户态头而报错 |
| 内核工具链编应用 | 通常能编，但缺 `-lc`/动态链接器，运行时各种找不到 |
| 编模块用错工具链版本 | `Invalid module format`（vermagic 里的编译器版本会变） |

## 七、RK3568 SDK 里怎么选

| 要编什么 | 用哪个 |
|---|---|
| `kernel/`（Image、dtb） | SDK `prebuilts` 里的 `aarch64-none-linux-gnu-` 或 `aarch64-linux-gnu-`，**以 `build.sh`/`make.sh` 里写死的为准** |
| U-Boot | 同上（SDK 一般统一） |
| 应用（你的 `xxxApp`） | `buildroot/output/rockchip_rk3568/host/usr/bin/aarch64-buildroot-linux-gnu-gcc` |
| 外部 `.ko` | `ARCH=arm64` + SDK 内核那套 `CROSS_COMPILE` |

**最稳的判断方法不是背名字，而是看 SDK 脚本里怎么设的**：

```bash
grep -rn "CROSS_COMPILE" kernel/make.sh build.sh device/rockchip/ 2>/dev/null | head
```

## 八、一句话总结

**`arch-os-lib-` 三段决定用途：`linux-gnu` 给应用（要 glibc 和 sysroot），`none-linux-gnu` 给内核/U-Boot（不要 C 库）；判断是否匹配别看名字，看 `-dumpmachine`、`file`、`readelf -A` 三连。**
