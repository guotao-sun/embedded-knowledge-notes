# imx6ull Linux 驱动 Makefile 模板

## 一、先说结论

外置模块的 Makefile 只有**一个必须写对的公式**：

```makefile
$(MAKE) -C $(KERNELDIR) M=$(PWD) modules
```

`-C` 进内核树、`M=` 指回你的目录、`modules` 是 kbuild 的外部模块目标。其余全是这三项的包装。

## 二、可以直接抄的模板

```makefile
# ─── 1. 路径与工具链 ─────────────────────────────
KERNELDIR    := /home/zhangxin/workspace_imx6ull/kernel   # 必须是"已编译过"的内核树
CURRENT_PATH := $(shell pwd)                              # 当前驱动目录（绝对路径）
ARCH         := arm
CROSS_COMPILE := arm-linux-gnueabihf-                    # 可写全路径；结尾 '-' 必须有

# ─── 2. 要编成哪些模块 ───────────────────────────
obj-m := led.o                # led.c → led.ko

# ─── 3. 目标 ─────────────────────────────────────
all:
	$(MAKE) -C $(KERNELDIR) M=$(CURRENT_PATH) ARCH=$(ARCH) \
	        CROSS_COMPILE=$(CROSS_COMPILE) modules

clean:
	$(MAKE) -C $(KERNELDIR) M=$(CURRENT_PATH) ARCH=$(ARCH) \
	        CROSS_COMPILE=$(CROSS_COMPILE) clean

.PHONY: all clean
```

`all` 必须是第一个目标（第一个目标就是默认目标），否则 `make` 什么都不做。

## 三、逐行解释

| 行 | 含义 | 注意 |
|---|---|---|
| `KERNELDIR := ...` | 内核源码根目录 | **必须编译过**（有 `include/config/auto.conf`、`scripts/`） |
| `CURRENT_PATH := $(shell pwd)` | 在 make 执行时抓当前目录 | 不能用 `:=.`，`M=` 要绝对路径 |
| `ARCH := arm` | 目标架构 | RK3568 是 `arm64` |
| `CROSS_COMPILE := arm-linux-gnueabihf-` | 编译器前缀 | 结尾 `-` 不能少，否则拼成 `arm-linux-gnueabihfgcc` |
| `obj-m := led.o` | 编译成模块 | 写 `obj-y` 就不是模块了（见第五节） |
| `$(MAKE) -C ...` | 用同一个 make 进内核树 | 用 `$(MAKE)` 而不是 `make`，才能传递 `-j` 等参数 |
| `M=$(CURRENT_PATH)` | 告诉 kbuild"外部模块在这" | kbuild 会去那读我们的 Makefile |
| `modules` | kbuild 的外部模块目标 | 不能改成 `all` 或 `default` |

## 四、`-C` / `M=` / `modules` 各自在干什么

```text
make
  └─ 进了你目录，读到上面这个 Makefile
       └─ 执行 $(MAKE) -C $(KERNELDIR)     ← 切到内核树，读内核顶层 Makefile
            └─ M=$(CURRENT_PATH)          ← 内核 Makefile 说"这次只处理这个外部目录"
                 └─ modules               ← 只做"编译模块"这一件事，不编内核本体
```

内核顶层 Makefile 收到 `M=` 后，会：

1. 读 `$(M)/Makefile`（就是你这份）；
2. 用内核的编译规则去编 `obj-m` 里列的 `.o`；
3. 链接成 `.ko`，输出到 `$(M)/`；
4. 顺手生成 `.led.ko.cmd`、`led.mod.c`、`Module.symvers` 等中间文件。

所以 `.ko` 就在**当前目录**里，不会跑到内核树里。

## 五、`obj-m` 与 `obj-y` 的区别

| 写在哪 | 写什么 | 结果 |
|---|---|---|
| 你的外部模块 Makefile | `obj-m := led.o` | `led.ko`，可 `insmod`/`rmmod` |
| 内核树里的 Makefile | `obj-y += led.o` | 编进 `vmlinux`，**没有 .ko，不能卸载** |
| 内核树里的 Makefile | `obj-$(CONFIG_X) += led.o` | 由 `.config` 决定 y/m/不编 |

外部模块**只能** `obj-m`。写 `obj-y` 会报：

```text
make: *** No rule to make target 'modules'.  Stop.
```

（因为 `obj-y` 的目标不是外部模块。）

## 六、多文件编成一个模块

一个模块由多个 `.c` 组成时，用 `<模块名>-objs`：

```makefile
obj-m := myled.o
myled-objs := led_core.o led_ops.o led_sysfs.o
```

产物是 `myled.ko`，由三个 `.o` 链接而成。**注意 `myled-objs` 里的名字不能带 `.ko`**。

反过来，一个 `.c` 编成两个模块（少见）用：

```makefile
obj-m := a.o b.o
a-objs := common.o part1.o
b-objs := common.o part2.o
```

## 七、常见报错对照

| 报错 | 原因 | 修法 |
|---|---|---|
| `scripts/basic/fixdep: not found` | `KERNELDIR` 指向的树没编译过 | 先在树里 `make modules_prepare` 或完整编译 |
| `No such file or directory: include/config/auto.conf` | 同上（没 `.config`） | `make xxx_defconfig` |
| `arm-linux-gnueabihfgcc: command not found` | 前缀少了结尾 `-` | 补 `-` |
| `*** No rule to make target 'led.o'` | `obj-m` 里的名字与源文件名不一致 | 文件名必须对得上（`led.c` ↔ `led.o`） |
| `WARNING: Symbol version dump "Module.symvers" is missing` | 内核树只做了 `modules_prepare` | 完整编译一次内核树 |
| 编出来的 `.ko` 板子上 `Invalid module format` | vermagic 不匹配 | 用与板子**同一份**源码树编译 |
| `make: Nothing to be done for 'all'` | `.ko` 已是最新 | 正常；改代码或 `make clean` |

## 八、clean 为什么要传 `clean` 给 kbuild

```bash
make clean
```

走的是 `$(MAKE) -C $(KERNELDIR) M=$(PWD) clean`。为什么不能直接 `rm -f *.o *.ko`？因为 kbuild 还会生成 `.xxx.cmd`、`.tmp_versions/`、`modules.order`、`Module.symvers` 等隐藏文件，手工删容易漏，而残留的 `.cmd` 会让下次编译"以为不用重编"。

## 九、一句话总结

**`obj-m` 指明要编什么，`-C KERNELDIR` 借内核的规则，`M=PWD` 指回源码目录，`modules` 只要模块——四项写对，模板就能复用一辈子；`KERNELDIR` 必须是编译过、且和板子同版本的那棵树。**
