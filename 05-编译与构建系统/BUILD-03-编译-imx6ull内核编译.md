# imx6ull 内核增量编译

## 一、先说结论

改了一行代码，**不要再"全量编译"**，按改动范围选最小代价的那一档：

| 改了什么 | 用什么命令 | 耗时量级 |
|---|---|---|
| 某个 `.c` 的语法/逻辑 | `make 目录/`（只编该目录） | 秒级 |
| 某个目录的代码，且要更新 `zImage` | `make zImage -j16`（增量链接） | 十几秒到 1 分钟 |
| 设备树 `.dts/.dtsi` | `make dtbs` | 秒级 |
| 改 `Kconfig` / 加新文件 | 先 `make olddefconfig`，再上面某一条 | 分钟级（会全量重编受影响部分） |

## 二、先设环境（每个新终端都要设）

```bash
export CROSS_COMPILE=/usr/local/arm/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-
export ARCH=arm
```

建议写进 `~/.bashrc`，否则每开一个终端忘一次，报的是"`arm-linux-gnueabihf-gcc: command not found`"或更隐蔽的 "`as: unrecognized option`"。

## 三、只编一个目录

在内核根目录下，把目录当目标：

```bash
make sound/soc/codecs/ -j16        # 只编这个目录（含它的子目录）
make drivers/i2c/busses/ -j16
```

产物是**该目录的 `built-in.o`**，不会生成 `zImage`——目录级编译只是"把 `.o` 和 `built-in.o` 更新掉"，链接是顶层的事。

## 四、单文件：最快的一次"编译是否通过"检查

```bash
make sound/soc/codecs/wm8960.o -j4
```

kbuild 支持直接指定 `.o` 目标，它只编这一个文件并输出真实的 gcc 命令行（失败时能直接看到缺哪个头文件）。

## 五、要更新镜像，回根目录做增量链接

```bash
cd workspace_imx6ull/kernel
make zImage -j16
```

虽然是 `make zImage`，但 kbuild 会检查时间戳，**只重编改过的文件、其余复用 `.o`**，所以这是"增量"的。真正慢的只有第一次。

产物：

```bash
ls -l arch/arm/boot/zImage
ls -l arch/arm/boot/dts/*.dtb
```

## 六、一个常见误解：在子目录里 `make -C ../../../`

很多人（包括很多教程）这样写：

```bash
cd workspace_imx6ull/kernel/sound/soc/generic/
make -C ../../../ -j16
```

看起来"我只编译了 generic 目录"，**其实 `-C ../../../` 是让 make 先 `cd` 回内核根目录，然后执行根 Makefile 的默认目标（`all`）——也就是整棵树做了一次增量构建。**

所以：

| 写法 | 实际行为 |
|---|---|
| `cd 子目录 && make -C ../../..` | 回根目录，走默认目标 = **整树增量构建** |
| `cd 根目录 && make 子目录/` | **只**构建那个目录 |
| `cd 根目录 && make zImage` | 整树增量构建 + 链接出镜像 |

它没错、也能出正确结果，只是"比你以为的干得多"。知道这点后：只想快速查错就用 `make 目录/`，想更新镜像就直接在根目录 `make zImage`，别在子目录里绕。

## 七、想看真实编译命令

```bash
make V=1 sound/soc/codecs/ -j4     # 打印完整 gcc 命令行
make V=1 zImage 2>&1 | grep wm8960 # 只看某个文件的编译命令
```

排查"头文件路径不对""宏没定义"时，`V=1` 是唯一可靠的手段——不要凭猜。

## 八、把产物拷到板子

```bash
# 内核（i.MX6ULL 板子上 eMMC 的 boot 分区挂在 /run/media/mmcblk1p1）
scp arch/arm/boot/zImage root@192.168.55.71:/run/media/mmcblk1p1/

# 设备树
scp arch/arm/boot/dts/imx6ull-14x14-emmc-4.3-480x272-c.dtb root@192.168.55.71:/run/media/mmcblk1p1/
```

拷完必须确认板子真的换了镜像：

```bash
ssh root@192.168.55.71 md5sum /run/media/mmcblk1p1/zImage
md5sum arch/arm/boot/zImage
```

两个 MD5 不一致，说明没传完或传错了分区，别急着 reboot 排查驱动。

## 九、在源码里搜字符串

```bash
grep -rn "bitclock-master" ./                    # 全树搜（慢）
grep -rn "bitclock-master" arch/arm/boot/dts/    # 缩到 dts（快）
grep -rn "snd_soc_dai_set_sysclk" sound/ include/ | head -20
```

`-r` 递归、`-n` 带行号；大仓库里**先缩目录再搜**，比全树扫快一个数量级。

## 十、一句话总结

**查错用 `make 目录/` 或 `make 文件.o`，出镜像用根目录 `make zImage`；子目录里的 `make -C ../../..` 是整树构建，别把它当"只编这个目录"。**
