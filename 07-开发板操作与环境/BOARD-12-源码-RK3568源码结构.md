# RK3568 源码结构

## 一、先说结论

RK3568 的"源码"不是一份内核源码，而是**一整套 SDK**，分三层看：

| 层 | 目录 | 你什么时候进去 |
|---|---|---|
| SDK 顶层 | `build.sh`、`device/`、`buildroot/`、`u-boot/`、`kernel/`、`rkbin/` | 改板级配置、打包、烧写 |
| 内核 | `kernel/` | 改驱动、设备树、内核配置 |
| 显示/GPU | `kernel/drivers/gpu/drm/` | 查 DRM、VOP、MIPI/HDMI |

先记一句：**编译入口永远是顶层的 `./build.sh`，不是 `make`。**

换成"最终固件"的视角，这一整套 SDK 只产出**四样东西**：设备树、U-Boot、内核、根文件系统（见下一节）。

## 二、产物视角：烧进去的其实是四样东西

从"板子上到底被烧了什么"往回倒推，SDK 的责任就四块：

| 产物 | 源码在哪 | 编出来的文件 | 烧到哪 |
|---|---|---|---|
| **设备树** | `kernel/arch/arm64/boot/dts/rockchip/rk3568-*.dts` | `rk3568-*.dtb` | 打进 `boot.img`（FIT 容器） |
| **U-Boot** | `u-boot/` | `uboot.img`（正文与它自己的 dtb 已打包在一起） | `uboot` 分区 |
| **内核** | `kernel/` | `Image`（放进 FIT） | `boot` 分区 |
| **根文件系统** | `buildroot/`（配置 + overlay + 包） | `rootfs.img` | `rootfs` 分区 |

注意：U-Boot 也有自己的一份设备树，但它**不单独算一个产物**——打包时它和 U-Boot 正文被合成同一个 `uboot.img`，烧写对象只有 U-Boot 一个（见下节）。

对应到 `parameter.txt` 里的分区，大致是 `uboot` / `trust` / `boot` / `rootfs` / `userdata`——**具体顺序、偏移、大小以你板子的 `parameter.txt` 为准**，不同 SDK 版本会差。

还有一样不在这四块里：`rkbin/` 里的 **loader**（DDR 初始化 + miniloader/ATF）。BootROM 先跑它，DDR 起来之后才轮到 U-Boot。它基本是预编译二进制、日常不改，但换 DDR 颗粒、改启动介质这类事必须动它。

### 设备树为什么是两份

这是最容易搞错的地方——**没有"一个设备树目录"**，U-Boot 和内核各有一份：

| | U-Boot 的 dts | 内核的 dts |
|---|---|---|
| 路径 | `u-boot/arch/arm/dts/rk3568-*.dts` | `kernel/arch/arm64/boot/dts/rockchip/rk3568-*.dts` |
| 谁来解析 | U-Boot / SPL 自己 | 内核 |
| 管什么 | 内存大小、调试串口、存储控制器、`bootcmd` 要用的节点 | 全部外设：pinctrl、panel、codec、regulator、时钟 |
| 特有写法 | `u-boot,dm-spl;`、`u-boot,dm-pre-reloc;` 这类"SPL 阶段也要用"的标记 | 不需要这些标记 |
| 忘改的后果 | 串口没输出、找不到 eMMC、`bootcmd` 找不到镜像 | 驱动 probe 失败、屏幕不亮、网口不通 |

为什么不能合并成一份：**SPL 阶段内存还没初始化完，只能解析极小的 DT**，所以 U-Boot 那份要裁到"够启动用"；内核那份才是完整的。

两份必须在这几处对齐，否则会出现"一边能起、一边起不来"：

| 必须一致 | 不一致的症状 |
|---|---|
| `memory` 节点（DDR 起始地址与容量） | U-Boot 正常、内核启动后跑飞或内存只认一半 |
| 调试串口（`chosen` 的 `stdout-path`） | 一个有输出一个没输出，误判"内核挂了" |
| 存储控制器与分区 | U-Boot 找得到 `boot` 分区、内核找不到 `rootfs` |
| `bootargs` 的 `root=` 与真实分区名 | 内核起来但 panic：`Unable to mount root fs` |

一句话记：**U-Boot 的 dts 决定"能不能把内核搬起来"，内核的 dts 决定"起来之后外设能不能用"。**

### 打包环节：两段合成一个 uboot.img

两份 dts 虽然分别编译，但**到镜像这一层就合并了**：

```text
u-boot/arch/arm/dts/rk3568-*.dts
        │  编译
        ▼
u-boot.dtb  ──┐
              ├──►  make.sh 打包  ──►  uboot.img  ──►  uboot 分区
u-boot-nodtb.bin（正文）┘
```

RK 的 `make.sh` 最后会把 U-Boot 正文和 dtb 打进同一个 `uboot.img`：

- SPL + FIT 方案：`make u-boot.itb`，FIT 里是 `u-boot-nodtb.bin` + `u-boot.dtb`（+ trust 二进制）
- miniloader 方案：`tools/loaderimage --pack --uboot u-boot.bin uboot.img $SYS_TEXT_BASE`

由此有三条实践结论：

| 结论 | 说明 |
|---|---|
| 编译产物是两个文件，烧写产物是一个 | `u-boot-nodtb.bin` + `u-boot.dtb` 便于单独替换调试，但上板只认 `uboot.img` |
| 改 U-Boot 的 dts 必须重跑 `./build.sh uboot` 并重烧 `uboot` 分区 | 只编内核、只烧 `boot.img` 完全不会更新它 |
| 内核的 dtb 走另一条路 | 它和内核 `Image` 一起进 `boot.img` 的 FIT，和 `uboot.img` 无关 |

验证镜像里到底装了什么：

```bash
dumpimage -l output/firmware/uboot.img      # FIT 会列出 uboot / fdt 节点
fdtdump output/firmware/uboot.img | head -40
```

想确认"生效的是哪份 dts"，改一个看得见的字串（如 `model`），U-Boot 打印与 `cat /proc/device-tree/model` 各看一次即可分辨。

## 三、SDK 顶层

```text
rk3568_linux_sdk/
├── build.sh              # 唯一的编译入口（kernel/uboot/rootfs/全量）
├── Makefile
├── device/               # 板级配置：BoardConfig-*.mk、parameter.txt、分区表
│   └── rockchip/rk356x/
├── kernel/               # 内核源码（4.19.x）+ make.sh
│   └── arch/arm64/boot/dts/rockchip/   # 内核那份设备树
├── u-boot/               # U-Boot 源码
│   └── arch/arm/dts/     # U-Boot / SPL 那份设备树
├── buildroot/            # 根文件系统构建（工具链也在这）
│   └── output/rockchip_rk3568/host/usr/bin/   # 交叉编译器实际位置
├── rkbin/                # Rockchip 预编译二进制（loader、DDR 初始化、签名工具）
│   └── tools/rk_sign_tool
├── prebuilts/            # SDK 自带的交叉工具链
├── external/             # 第三方库/应用
├── docs/                 # 官方文档（PDF、开发指南）
├── tools/                # 打包、烧写、调试工具
└── output/               # 编译产物汇总
    ├── firmware/         # 各分区镜像（boot.img、rootfs.img、update.img）
    └── ...
```

几个"找东西必去"的位置：

| 要找什么 | 去哪 |
|---|---|
| 板级配置（内核 defconfig、dtb 名） | `device/rockchip/rk356x/BoardConfig-*.mk` |
| 分区表（p1~p7 各是什么） | `device/rockchip/rk356x/parameter.txt` |
| 打包规则（boot.img 里放什么） | `device/rockchip/common/` 下的 `mk-*.sh`、`*.its` |
| 交叉编译器 | `prebuilts/gcc/...`（内核用）、`buildroot/output/.../host/usr/bin/`（应用用） |
| 最终可烧的镜像 | `output/firmware/` |

## 四、`build.sh` 的用法

```bash
./build.sh              # 全量（uboot + kernel + rootfs）
./build.sh kernel       # 只编内核
./build.sh uboot        # 只编 U-Boot
./build.sh rootfs       # 只做根文件系统
./build.sh firmware     # 打各分区镜像
./build.sh updateimg    # 打整包 update.img
./build.sh -h           # 看全部子命令
```

它读 `device/rockchip/.BoardConfig.mk`（由 `./build.sh lunch` 选出的软链接）来决定：

```bash
./build.sh lunch        # 选板子 → 生成 .BoardConfig.mk
```

**换板子必须先 `lunch`**，否则编出来的是上一块板子的配置——这是"我改了配置但没生效"的头号原因。

## 五、`kernel/drivers/gpu/drm/` 的结构

RK 的显示子系统（DRM）是你查"屏幕不亮/花屏"的地方：

```text
drivers/gpu/drm/
├── drm_core.c        # DRM 核心框架（设备、文件、ioctl 分发）
├── drm_ioctl.c       # ioctl 实现（用户态 modetest/合成器进来的入口）
├── drm_plane.c       # 平面（Plane）：一个图层
├── drm_crtc.c        # 显示控制器（CRTC）：时序、扫描输出
├── drm_connector.c   # 连接器：HDMI/DSI/DP/EDP 与面板的连接
├── drm_encoder.c     # 编码器：TMDS/DSI 打包
└── rockchip/
    ├── rockchip_drm_drv.c   # RK DRM 驱动入口（probe、组件绑定）
    ├── rockchip_vop.c       # VOP（视频输出处理器，图层合成、缩放）
    ├── dw-mipi-dsi.c        # DesignWare MIPI DSI 控制器
    └── dw-hdmi.c            # DesignWare HDMI 控制器
```

按"一条像素走的路"记这几个文件最清楚：

```text
应用（DRM API）→ drm_ioctl → drm_atomic（commit）
   → Plane（图层）→ CRTC/VOP（合成+时序）→ Encoder（DSI/HDMI 打包）
   → Connector（物理接口/面板）→ 屏幕
```

| 文件 | 一句话职责 |
|---|---|
| `drm_core.c` | 建立 `/dev/dri/card0`、管理 DRM 设备生命周期 |
| `drm_ioctl.c` | 用户态所有 DRM 命令的入口（含 atomic commit） |
| `drm_plane.c` | 图层的属性（位置、格式、缩放） |
| `drm_crtc.c` | 时序（h/v sync、像素时钟）与扫描输出 |
| `rockchip_drm_drv.c` | 把 VOP/DSI/HDMI 作为 component 绑成一个 card |
| `rockchip_vop.c` | RK 特有的图层合成硬件（多窗口叠加、alpha） |
| `dw-mipi-dsi.c` | MIPI DSI 时序与命令发送（点屏必调） |
| `dw-hdmi.c` | HDMI 的 EDID、TMDS、音频回传 |

**"屏幕背光亮但黑屏"** 通常卡在 `dw-mipi-dsi.c`（DSI 初始化序列/时钟）或设备树里的 panel 节点；**"完全没 `/dev/dri`"** 则是 `rockchip_drm_drv.c` 的 probe 失败，看 `dmesg | grep -i drm`。

## 六、内核里其它常用目录（RK 版）

```text
kernel/
├── arch/arm64/boot/dts/rockchip/     # rk3568*.dts / rk3568.dtsi
├── arch/arm64/boot/Image             # 编出来的未压缩内核
├── drivers/
│   ├── gpu/drm/rockchip/             # 显示
│   ├── media/                        # V4L2、ISP、编解码（rkvenc/rkvdec）
│   ├── mmc/                          # eMMC/SD
│   ├── net/ethernet/                 # GMAC
│   └── soc/rockchip/                 # RK 平台专用（pm_domain、grf、saradc）
└── sound/soc/rockchip/               # RK 音频（i2s、sai、codec）
```

设备树在 `arch/arm64/boot/dts/rockchip/`——**RK 的板级 dts 名字通常形如 `rk3568-evb1-ddr4-v10.dts`**，和 `BoardConfig` 里的 `RK_KERNEL_DTS` 对应。

## 七、定位一个文件的三步

```bash
# 1. 用 compatible 找驱动（最可靠）
grep -rn "rockchip,rk3568-vop" drivers/gpu/drm/rockchip/

# 2. 用函数名找实现
grep -rn "rockchip_drm_bind" drivers/gpu/drm/rockchip/

# 3. 用文件名猜目录（子系统名一般就是目录名）
ls drivers/gpu/drm/rockchip/
```

大 SDK 里 `grep -rn` 从顶层扫会慢，**先进到对应子目录再扫**。

## 八、一句话总结

**烧进板子的只有四样：设备树（内核那份，进 `boot.img`）、U-Boot（正文与自己的 dtb 合成 `uboot.img`）、内核、根文件系统；源码上则是"SDK 套内核"——`build.sh` 是唯一入口、`device/` 管板级配置与分区、`kernel/` 管驱动与内核那份 dts、`buildroot/output` 给应用工具链；显示问题从 `drivers/gpu/drm/rockchip/` 的 vop、dsi、hdmi 查起。**
