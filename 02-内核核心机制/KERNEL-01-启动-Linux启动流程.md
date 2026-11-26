# Linux 启动流程

## 一、先说结论

从按下电源到能登录，是一条**五级接力**：BootROM → U-Boot（含 SPL）→ 内核 → 挂载根文件系统 → init 拉起用户空间。

每一级只做三件事：初始化自己要用到的硬件、把下一级搬进内存、跳过去执行。所以"启动失败"几乎总能定位到**某一棒没交出去**，而不是笼统的"系统坏了"。

![Linux 启动流程](../images/image40.jpeg)

*图：从 Bootloader 加载内核到用户空间启动的完整过程。*

## 二、五级接力各自干什么

| 阶段 | 谁在跑 | 主要工作 | 产物 / 位置 |
|---|---|---|---|
| ① BootROM | SoC 内部固化的代码（RK3568 叫 MaskROM） | 按启动引脚选择介质（eMMC / SD / SPI Flash / USB），读出头几个扇区 | 一级引导程序 |
| ② SPL（一级 bootloader） | 一小段 U-Boot 代码（`u-boot-spl.bin`） | 初始化 DDR、时钟等最小硬件，把完整 U-Boot 搬进内存 | 完整 U-Boot |
| ③ U-Boot | 完整 bootloader | 初始化外设与命令行、读分区、加载内核镜像与设备树、设置启动参数，跳转 | zImage / Image + DTB |
| ④ 内核 | Linux 内核 | 自解压、建页表开 MMU、`start_kernel` 初始化各子系统 | 可用的内核 + 根文件系统挂载点 |
| ⑤ 用户空间 | init（systemd / busybox init） | 挂载文件系统、启服务、拉起 shell | 能登录的系统 |

### 几个容易含混的点

- **BootROM 不是 bootloader**，它是芯片里烧死的固码，改不了；能改的是它加载的东西。
- **SPL 不是"另一个 bootloader"**，它就是 U-Boot 的精简版，目的只有一个：DDR 还没初始化时，先在片内 SRAM 里跑起来，把 DDR 点亮。
- **内核自己也分两段**：先是自解压代码（`arch/arm/boot/compressed/head.S`），解压完才跳进真正的入口 `stext`（`arch/arm/kernel/head.S`），详见 [Linux 启动代码](./KERNEL-02-启动-Linux启动代码.md)。

## 三、交接棒靠什么传

| 交接 | 传递内容 | 靠什么约定 |
|---|---|---|
| BootROM → SPL | 一段可执行镜像 | 启动介质上的固定偏移 + 镜像头（RK3568 是 idbloader 格式） |
| SPL → U-Boot | U-Boot 镜像 | 内存里的固定加载地址 |
| U-Boot → 内核 | 内核镜像、设备树、启动参数 | `bootargs`（`console=`、`root=` 等）+ 入口地址；ARM 约定 r0=0、r1 机器号（老式）、r2 设备树地址 |
| 内核 → init | 根文件系统 | `root=` 指定设备，或 initramfs；`init=` / `rdinit=` 指定要执行的程序 |

`bootargs` 是整条链上最容易出事的一处：`console=` 写错，内核照样在跑，但你看不到任何打印，表现就像"卡死了"。

## 四、卡住了，先判断停在哪一棒

| 现象 | 多半卡在 | 怎么查 |
|---|---|---|
| 串口一个字都没有 | ① BootROM 没找到启动介质 / ② SPL 没跑起来 / 串口线或波特率不对 | 换启动方式（SD 卡）、量串口波形、确认 115200 |
| 有 U-Boot 打印，停在 `Loading kernel...` | ③ 镜像地址、格式或分区读错 | 核对 `loadaddr`、`fatload` 路径、镜像是否损坏 |
| 打印 `Starting kernel ...` 后再无输出 | ④ 内核早期（`console=`、`earlycon`、设备树 `chosen` 节点） | 加 `earlycon`、检查 DTB 与板子是否匹配 |
| `VFS: Unable to mount root fs` | ④ 挂载根文件系统 | `root=` 设备名、文件系统驱动是否编进内核、分区是否存在 |
| 内核起来了但进不了 shell | ⑤ init 路径错或服务崩 | `init=` 参数、`/etc/inittab`、systemd 日志 |

## 五、和 STM32 启动对比

| | STM32 | Linux（Cortex-A） |
|---|---|---|
| 起点 | 上电从 0x00000000 取 SP、0x00000004 取 PC | BootROM 按介质找镜像，多级接力 |
| 有没有 bootloader | 没有（可加，但非必需） | 必须有，且往往两级（SPL + U-Boot） |
| 地址空间 | 全程物理地址，无 MMU | 内核早期就建页表、开 MMU，之后全走虚拟地址 |
| 启动结束标志 | 进 `main()` 就算启动完成 | 内核初始化完 → 挂载根文件系统 → 执行 init 才算 |

## 六、往下看

- `start_kernel` 里面按什么顺序初始化、PID 0/1/2 怎么来的：见 [Linux 启动代码](./KERNEL-02-启动-Linux启动代码.md)
- 驱动怎么在启动末期被自动调用：见 [初始化的宏](./KERNEL-03-启动-初始化宏.md)
- U-Boot 的具体配置与命令：见 `06-U-Boot与启动`
