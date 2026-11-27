# Linux 驱动编译流程

## 一、先说结论

一个外置驱动从"改代码"到"跑起来"，是**六步闭环**，每次都一样：

```text
设环境 → make（出 .ko）→ scp 到板子 → insmod → 看 dmesg → 测功能 → rmmod
```

任何一步失败，**先看它上一步的产物对不对**（.ko 有没有生成？架构对不对？vermagic 匹配吗？），不要跳到后面猜。

## 二、第一步：设环境

```bash
export ARCH=arm
export CROSS_COMPILE=/usr/local/arm/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-
```

RK3568（64 位）则是：

```bash
export ARCH=arm64
export CROSS_COMPILE=<SDK>/prebuilts/gcc/linux-x86/aarch64/.../bin/aarch64-linux-gnu-
```

**环境变量只对当前终端有效**。开新终端忘了设，`make` 会用宿主机 gcc，编出 x86 的 `.ko`，然后板子上 `insmod` 报：

```text
insmod: ERROR: could not insert module led.ko: Invalid module format
```

## 三、第二步：编译

```bash
make
```

产物：

```bash
ls -l *.ko
file led.ko        # 必须是 "ELF 32-bit LSB relocatable, ARM"（或 AArch64）
```

`file` 这一步很值：一眼就能看出"是不是用错工具链编的"。x86 的 `.ko` 也是 ELF，但 `file` 会明确写 `x86-64`。

## 四、第三步：拷到板子

```bash
scp led.ko root@192.168.55.71:/lib/modules/$(uname -r)/   # 正式放法（配合 modprobe）
scp led.ko root@192.168.55.71:/tmp/                        # 临时调试放法
```

`/tmp` 是 tmpfs，重启就没了——调试期正合适，不会污染板子。正式部署再放 `/lib/modules/`。

## 五、第四步：加载

```bash
insmod /tmp/led.ko        # 按路径加载，不解析依赖
modprobe led              # 按模块名加载，会先查 modules.dep
```

- `insmod` 适合"就一个文件、马上要看结果"的场景；
- `modprobe` 需要先 `depmod` 生成索引，适合正式部署与有依赖的模块。

加载成功时**屏幕上不会有任何输出**——这是正常的。`insmod` 只在失败时打印原因。

## 六、第五步：看内核说了什么

```bash
dmesg | tail -n 20        # 环形缓冲区的最后 20 条
dmesg -w                  # 实时跟踪（等价 tail -f）
```

驱动里 `printk` 的级别决定它出现在哪：

| 写法 | 级别 | 默认是否打到串口 |
|---|---|---|
| `printk(KERN_ERR "...")` / `pr_err` | 3 | 是 |
| `printk(KERN_INFO "...")` / `pr_info` | 6 | **否**（要 `dmesg` 才看得到） |
| `pr_debug` / `dev_dbg` | 7 | 否（需开 `DYNAMIC_DEBUG` 或 `#define DEBUG`） |

新手最常见的困惑："我在 probe 里加了打印，串口没反应"——多半用了 `pr_info`，去 `dmesg` 里就能看到。

## 七、第六步：测功能、看状态

```bash
lsmod | grep led                    # 模块是否在
ls /dev/led*                        # 字符设备节点有没有自动创建
cat /proc/devices | grep led        # 主设备号有没有注册
ls /sys/class/leds/                 # LED 类设备
```

改 LED 触发方式（点灯驱动常用）：

```bash
echo none > /sys/class/leds/sys-led/trigger    # 关掉内核自带的闪烁，交给你的驱动控制
echo 1 > /sys/class/leds/sys-led/brightness
```

如果 `/dev/led` 没出现，但 `/proc/devices` 里有主设备号，说明**驱动注册成功了但没创建节点**——手工补一个：

```bash
mknod /dev/led c <major> 0
```

这正好印证了"注册设备"与"创建设备节点"是两件事（见 [注册设备与创建设备的区别](./../03-驱动开发基础/DRIVER-04-字符设备-注册设备与创建设备.md)）。

## 八、第七步：卸载

```bash
rmmod led          # 按模块名
# 或 modprobe -r led
```

卸载会调用驱动的 `__exit` 函数。如果卸载后 `dmesg` 里出现 `BUG: unable to handle kernel`，说明 `exit` 里释放了不该释放的东西，或释放顺序错了（先 `device_destroy` 再 `cdev_del` 再 `unregister_chrdev_region`）。

## 九、设备树相关的临时确认

改驱动之前，先确认设备树节点在不在、`compatible` 对不对：

```bash
ls /proc/device-tree/beep/
cat /proc/device-tree/beep/compatible | tr '\0' '\n'
```

这一步不做，`probe` 根本不进——`insmod` 会成功、`lsmod` 也能看到，但什么打印都没有，因为**驱动加载 ≠ 设备匹配**。

## 十、一个完整的排查顺序

| 现象 | 先查什么 |
|---|---|
| `make` 报找不到头文件 | `KERNELDIR` 路径对不对、是不是编译过的树 |
| `make` 编出 x86 的 .ko | `ARCH` / `CROSS_COMPILE` 没设 |
| `insmod` 报 `Invalid module format` | vermagic 与运行内核不一致（源码版本/配置不同） |
| `insmod` 报 `File exists` | 同名模块已加载，先 `rmmod` |
| `insmod` 成功但没打印 | 用了 `pr_info`，去 `dmesg`；或 `probe` 没进（设备树不匹配） |
| `probe` 没进 | `/proc/device-tree/<node>` 在不在、`compatible` 与 `of_match_table` 是否逐字一致 |
| 有 `/proc/devices` 没 `/dev/xxx` | 只注册没建节点，检查 `device_create` 返回值 |

## 十一、一句话总结

**环境变量决定编出什么架构、`make` 出 `.ko`、`insmod` 加载、`dmesg` 看结果；`insmod` 成功不等于 `probe` 执行——设备树不匹配时它静默成功。**
