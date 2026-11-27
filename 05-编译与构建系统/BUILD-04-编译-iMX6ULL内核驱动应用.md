# i.MX6ULL 编译 Linux 内核（全流程与烧写）

## 一、先说结论

一台新机器上"从零编出能跑的 `zImage`"，顺序是**固定**的：

```text
设 ARCH/CROSS_COMPILE → defconfig（或沿用板子配置）→ 可选 menuconfig
      → make -jN 出 zImage + dtb → scp 到 boot 分区 → 改 MD5 验证 → reboot
```

四个最容易踩的点：

1. `CROSS_COMPILE` 要带**完整路径 + 前缀**（结尾那个 `-` 不能丢）
2. 板子上跑的内核源码版本必须和编译的**同一份**，否则模块 `Invalid module format`
3. 从板子捞 `.config` 用 `scripts/extract-ikconfig`，不是 `strings | grep CONFIG_`
4. 拷完一定核对 MD5，`scp` 成功 ≠ 板子在跑你的镜像

## 二、设置交叉编译器

```bash
export ARCH=arm
export CROSS_COMPILE=/usr/local/arm/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-
```

`CROSS_COMPILE` 是**前缀**，kbuild 会自己拼 `$(CROSS_COMPILE)gcc`。所以它必须以 `-` 结尾，且包含路径（除非你把 `bin` 加进了 `PATH`）。

验证：

```bash
${CROSS_COMPILE}gcc -v
```

能打印出版本，才说明路径对。

## 三、取配置：defconfig / 旧 .config / 板子掏出来的 .config

### 路径 A：用 BSP 给的默认配置（最常见）

```bash
make imx_v6_v7_defconfig          # 通用 i.MX6 系列
# 或厂商板级默认（名字以 SDK 为准，正点原子/野火各不相同）
make imx6ull_alientek_emmc_defconfig
```

执行完会生成 `.config`。**这一步会把已有的 `.config` 覆盖掉**，别在没有备份的情况下随手跑。

### 路径 B：沿用上一次的 `.config`

什么都不用做，直接编。但如果源码更新过（新增了配置项），先：

```bash
make oldconfig        # 逐条问新增项（要交互）
make olddefconfig     # 不问，新项一律取默认（推荐）
```

### 路径 C：从板子上把正在跑的配置掏出来

```bash
# 板子上确认内核编进了 IKCONFIG
zcat /proc/config.gz | head        # 有输出就最简单

# 没有 /proc/config.gz，就用内核自带的提取脚本（在源码树里执行）
scripts/extract-ikconfig /path/to/zImage > board.config
```

> 原文里"`strings vmlinuz | grep CONFIG_`"这个办法**不可靠**：压缩过的镜像根本 `strings` 不出东西；未压缩的 `vmlinux` 里能捞到的也只是部分字符串，不是完整可用的配置。正确工具是 `scripts/extract-ikconfig`（依赖内核编译时打开了 `CONFIG_IKCONFIG`）。

拿到 `board.config` 后：

```bash
cp board.config .config
make olddefconfig
```

## 四、prepare / modules_prepare 到底干什么

这三个命令经常混着用，区别是：

| 命令 | 干什么 | 什么时候需要 |
|---|---|---|
| `make prepare` | 生成 `include/generated/`（`autoconf.h` 等）、建立 `arch/arm/include/generated/asm/` 的符号链接、生成 `asm-offsets.h` | 编任何东西之前都要有 |
| `make modules_prepare` | 在 `prepare` 基础上，额外准备**外部模块**编译所需的脚本与头文件，但**不编译 vmlinux** | 只编外部 `.ko`、不需要出镜像时 |
| `make -j16`（默认目标） | 完整编译：`vmlinux` → `Image`/`zImage` + 模块 | 要烧镜像时 |

要点：`modules_prepare` **不会生成 `Module.symvers`**。所以只做 `modules_prepare` 就编外部模块，会看到：

```text
WARNING: Symbol version dump "Module.symvers" is missing.
```

模块仍能编出来，但没有符号 CRC 校验。要彻底干净，**先完整编译一次内核**，再编模块。

## 五、完整编译

```bash
cd workspace_imx6ull/kernel
make -j16
```

`-jN` 取 `CPU 核数 × 1~2`。内存小于 4G 时别开太大，否则会被 OOM killer 杀掉 `cc1`，报的是莫名其妙的 "`Killed`"。

产物位置：

```bash
arch/arm/boot/zImage                 # 最终镜像
arch/arm/boot/Image                  # 未压缩的（调试用，很大）
arch/arm/boot/dts/*.dtb              # 设备树
vmlinux                              # 带符号的 ELF，oops 定位用
System.map                           # 符号地址表
```

用的源码包（供参考版本对齐）：`linux-imx-4.1.15-2.1.0-gad512fa-v1.7.tar.bz2`。

## 六、改用 menuconfig 调配置

```bash
make menuconfig
```

改完保存会重写 `.config`。注意：

- 改完 `Kconfig` 相关的东西，下次 `make` 会自动 `syncconfig`；
- 只想把当前配置"提纯"给同事，用 `make savedefconfig`，生成的 `defconfig` 只含非默认项。

## 七、给新板子配 IP（只为能 scp）

首次调试先临时配通，**永久配置见 [设置静态 IP](./../07-开发板操作与环境/BOARD-03-网络-设置静态IP.md)**。

宿主机（Ubuntu）：

```bash
sudo ifconfig ens33 192.168.55.72 netmask 255.255.255.0
sudo route add default gw 192.168.55.1
```

板子（串口里）：

```bash
ifconfig eth1 192.168.55.71 netmask 255.255.255.0
route add default gw 192.168.55.1
ping 192.168.55.72
```

两边能互 ping 才继续。**网线直连时不需要网关**，但加了也无害。

## 八、烧写镜像

```bash
# 1. 拷进 eMMC 的 boot 分区（i.MX6ULL 常见挂载点）
scp arch/arm/boot/zImage root@192.168.55.71:/run/media/mmcblk1p1/
scp arch/arm/boot/dts/imx6ull-14x14-emmc-4.3-480x272-c.dtb root@192.168.55.71:/run/media/mmcblk1p1/

# 2. 板子上确认落盘
sync
ls -l /run/media/mmcblk1p1/

# 3. 重启
reboot
```

重启后验证：

```bash
uname -a                             # 版本号里应带你的 commit
cat /proc/asound/cards               # 声卡注册没有
dmesg | grep -i "your probe string"  # 自己加的打印
```

## 九、怎么确认"板子跑的就是我刚编的"

三个层次，从弱到强：

```bash
# 弱：看时间戳
ls -l /run/media/mmcblk1p1/zImage

# 中：两端 MD5 对比
md5sum arch/arm/boot/zImage
ssh root@192.168.55.71 md5sum /run/media/mmcblk1p1/zImage

# 强：在镜像里搜一句只有你代码里才有的字符串
strings arch/arm/boot/zImage | grep "my dummy codec probe"
```

## 十、常见报错

| 报错 | 原因 | 修法 |
|---|---|---|
| `arm-linux-gnueabihf-gcc: command not found` | `CROSS_COMPILE` 没带路径且不在 PATH | 用绝对路径 |
| `arm-linux-gnueabihf-gcc: No such file` | 结尾的 `-` 丢了 | 补 `-` |
| `*** No rule to make target 'include/config/auto.conf'` | 没跑过 defconfig/`.config` | 先 `make xxx_defconfig` |
| `scripts/basic/fixdep: Permission denied` | 源码目录属主不是当前用户 | `sudo chown -R $USER .` 或 `chmod -R u+w` |
| `Killed` 出现在 `cc1` | `-j` 太大，内存不够 | 降 `-j`，加 swap |
| `Invalid module format`（insmod 时） | `vermagic` 与运行内核不符 | 用同一份已编译的源码树 |

## 十一、一句话总结

**defconfig 定基线、`make -jN` 出 `zImage` 与 `dtb`、`scp` 进 boot 分区、MD5 加 `strings` 双验证；`.config` 要从板子掏就用 `extract-ikconfig`，别用 `strings`。**
