# Linux 开发板查看系统信息

## 一、先说结论

"看系统信息"就三组，按用途选：

| 想知道的事 | 一条命令 |
|---|---|
| 这板子什么硬件、跑什么内核 | `cat /proc/cpuinfo` + `uname -a` |
| 内存/存储还剩多少 | `free -h` + `df -h` |
| 现在谁在忙、哪个中断在打 | `top` + `cat /proc/interrupts` |

底层全都是读 `/proc` 和 `/sys` 里的文件——`free`、`lsblk`、`ps` 只是把这些文件排版成人话。

## 二、CPU：`/proc/cpuinfo`

```bash
cat /proc/cpuinfo
```

ARM 板子上要看的字段：

| 字段 | 含义 | 例子 |
|---|---|---|
| `processor` | 逻辑核编号（0 起） | `processor : 0` |
| `model name` | 型号（ARM 上经常没有） | — |
| `BogoMIPS` | 标称性能估算值（不是真性能） | `48.00` |
| `Features` | 指令集扩展 | `fp asimd evtstrm aes pmull sha1 sha2 crc32` |
| `CPU implementer/architecture/variant` | 厂商/架构代号 | `0x41`（ARM）/`7`（ARMv7） |
| `Hardware` | 板级名字（i.MX 常见） | `Freescale i.MX6ULL` |
| `Revision` | 芯片版本 | `0000` |

`Features` 里有两个值得注意的：

- `fp`/`asimd`：有硬浮点/NEON → 工具链要用 `gnueabihf`；
- 缺 `fp`：软浮点内核/CPU，用 `hf` 工具链编出的程序会 `Illegal instruction`。

核数快速看：

```bash
grep -c ^processor /proc/cpuinfo
nproc                        # 有 coreutils 的话
```

## 三、内存：`/proc/meminfo` 与 `free -h`

```bash
free -h
#              total        used        free      shared  buff/cache   available
# Mem:          989Mi       180Mi        95Mi       5.0Mi       713Mi       760Mi
```

三个容易误读的列：

| 列 | 含义 |
|---|---|
| `free` | **完全没被用**的内存（很小是正常的） |
| `buff/cache` | 被内核拿去做缓存的内存（**随时可回收**，不算"用掉"） |
| `available` | 应用真正还能拿到的量（≈ free + 可回收的 cache） |

所以"free 只剩 95M 是不是要 OOM 了"——不是，看 `available`。

细节字段：

```bash
grep -E "MemTotal|MemFree|MemAvailable|Cached|SwapTotal" /proc/meminfo
```

## 四、存储：`df -h` 与 `lsblk`

```bash
df -h
# Filesystem      Size  Used Avail Use% Mounted on
# /dev/mmcblk1p2  6.8G  2.1G  4.4G  33% /
# tmpfs           100M   12K  100M   1% /run

lsblk
# mmcblk1      7.3G disk
# ├─mmcblk1p1  64M part  /run/media/mmcblk1p1
# └─mmcblk1p2   7G part  /
```

区别：

| 命令 | 看的是 | 用途 |
|---|---|---|
| `df -h` | 文件系统层（已挂载的） | 还剩多少空间 |
| `lsblk` | 块设备层（含未挂载的） | 有哪些盘、分区多大 |
| `du -sh /目录` | 目录实际占多少 | 找出谁把空间吃完了 |

排查"空间没了"：

```bash
df -h                                  # 先看哪个分区满
du -sh /* 2>/dev/null | sort -h | tail # 再看哪个目录大
```

## 五、内核与系统版本

```bash
uname -a
# Linux alientek 4.1.15-g3dc0a4b #1 SMP PREEMPT Tue ... armv7l GNU/Linux
```

逐段拆：

| 段 | 值 | 含义 |
|---|---|---|
| 主机名 | `alientek` | `/etc/hostname` |
| 内核版本 | `4.1.15-g3dc0a4b` | 后面的 hash 是编译时的 git commit |
| `#1 SMP PREEMPT` | 编译次数 / 对称多处理 / 可抢占 | — |
| 架构 | `armv7l` | 32 位 ARM；`aarch64` 是 64 位 |
| 平台 | `GNU/Linux` | — |

```bash
uname -r        # 只要版本号（编模块、找 /lib/modules 用这个）
uname -m        # 只要架构
```

发行版信息：

```bash
cat /etc/os-release       # 标准格式（ID、VERSION）
cat /etc/issue            # 登录横幅（busybox 系统常见）
```

RK 的 buildroot 系统往往没有 `/etc/os-release`，看 `cat /etc/issue` 或 `/etc/buildroot-version`。

## 六、运行时间与负载

```bash
uptime
#  10:22:31 up 3 days,  2:11,  1 user,  load average: 0.15, 0.08, 0.05
```

`load average` 三个数是 **1 / 5 / 15 分钟**的平均"可运行 + 不可中断"任务数。经验判据：

| 负载 vs 核数 | 说明 |
|---|---|
| < 核数 | 有余量 |
| ≈ 核数 | 刚跑满 |
| > 核数 × 2 | 明显拥塞，看谁在占 CPU |

直接读文件（没有 `uptime` 时）：

```bash
cat /proc/loadavg
```

## 七、进程：`top` 与 `ps`

```bash
top            # 动态；看 CPU%、MEM%、哪个进程在吃
ps             # 静态快照（busybox 精简版）
ps -ef         # 若支持，含完整命令行
```

`top` 里第一行的时间、负载、进程数，第二行的 `Tasks`、第三行的 CPU 占用（`us`/`sy`/`id`/`wa`）都值得看。`wa`（IO 等待）高说明瓶颈在存储不在 CPU。

## 八、中断：`/proc/interrupts`

```bash
cat /proc/interrupts
#            CPU0       CPU1
#  16:     123456          0     GICv3  30  arch_timer
#  32:          0     987654     GICv3  33  mmc0
# 215:       1234          0     GPIO   12  my_button
```

五列分别是：**中断号 : 每个 CPU 的计数 → 中断控制器 → 硬件号 → 注册的名字**。

用途：

- 某个外设"没反应"，看它的计数**有没有增加**——不增加说明中断没进来（查 pinctrl/时钟/设备树）；
- 计数疯狂增长，说明中断风暴（查驱动里有没有关中断源）。

只关心某个设备：

```bash
grep mmc /proc/interrupts
watch -n1 'grep mmc /proc/interrupts'     # 每秒刷新看增长
```

## 九、一句话总结

**CPU 看 `/proc/cpuinfo` 的 `Features`、内存看 `free -h` 的 `available`（不是 `free`）、存储看 `df -h` 与 `lsblk`、内核看 `uname -r`、负载看 `uptime`、中断看 `/proc/interrupts` 的计数有没有增长。**
