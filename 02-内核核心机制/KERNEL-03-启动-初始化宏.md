# 初始化的宏：initcall 是怎么排队的

## 一、先说结论

驱动里那个 `xxx_init()`，**不是被谁主动调用的**，而是编译时被塞进一张按等级分好段的表，内核在启动末期按等级从小到大、逐段遍历调用。

等级数字不是装饰：它决定"谁先初始化"，也就是**谁能先用上谁**。

## 二、问题：为什么非要分级

一个 SPI 控制器驱动初始化时，要申请 GPIO、开时钟、注册总线设备——这些都依赖 pinctrl 子系统和时钟子系统已经就绪。如果驱动抢先跑，结果是拿不到资源、probe 失败，甚至直接崩。

内核里的驱动成千上万，依赖关系还成环地交叉，靠人工维护一张"谁先谁后"的调用表不可能。于是换成另一种思路：

> **让链接器帮我排序**——把函数指针按声明的等级丢进不同名字的 ELF 段，启动时按段名顺序挨个调。

好处是驱动作者只需在自己的 `init` 上加一个宏，声明"我属于哪一级"，顺序自动成立，新增驱动也不用改启动代码。

## 三、实现机制

```c
#define __define_initcall(fn, id) \
    static initcall_t __initcall_##fn##id __used \
    __attribute__((__section__(".initcall" #id ".init"))) = fn;
```

拆开看：

- `initcall_t` 是函数指针类型（`int (*)(void)`），所以存进去的是**函数地址**，不是函数体
- `__attribute__((__section__(...)))` 把变量强制放到指定段，段名末尾拼上等级号：`.initcall2.init`
- `__used` 防止编译器认为"没人用"把它优化掉

启动时 `do_initcalls()` 按 `initcall_levels[]` 里登记的顺序，逐段遍历、逐个调用：

```c
/* 简化示意 */
for (level = 0; level < ARRAY_SIZE(initcall_levels) - 1; level++)
    do_initcall_level(level);
```

所以：

- `postcore_initcall` → `.initcall2.init` 段
- `subsys_initcall` → `.initcall4.init` 段
- 启动时先执行 2 段，再执行 4 段

**同一段内的顺序不归你管**：它由链接顺序决定，也就是 Makefile 里 `obj-y += xxx.o` 的先后。这就是为什么同一等级的驱动，谁先 probe 有时看起来"没规律"。

## 四、等级定义（内核原文）

```c
/* initcalls are now grouped by functionality into separate
 * subsections. Ordering inside the subsections is determined
 * by link order.
 * For backwards compatibility, initcall() puts the call in
 * the device init subsection.
 */
#define __define_initcall(fn, id) \
    static initcall_t __initcall_##fn##id __used \
    __attribute__((__section__(".initcall" #id ".init"))) = fn;

#define early_initcall(fn)        __define_initcall(fn, early)
#define pure_initcall(fn)         __define_initcall(fn, 0)
#define core_initcall(fn)         __define_initcall(fn, 1)
#define core_initcall_sync(fn)    __define_initcall(fn, 1s)
#define postcore_initcall(fn)     __define_initcall(fn, 2)
#define postcore_initcall_sync(fn) __define_initcall(fn, 2s)
#define arch_initcall(fn)         __define_initcall(fn, 3)
#define arch_initcall_sync(fn)    __define_initcall(fn, 3s)
#define subsys_initcall(fn)       __define_initcall(fn, 4)
#define subsys_initcall_sync(fn)  __define_initcall(fn, 4s)
#define fs_initcall(fn)           __define_initcall(fn, 5)
#define fs_initcall_sync(fn)      __define_initcall(fn, 5s)
#define rootfs_initcall(fn)       __define_initcall(fn, rootfs)
#define device_initcall(fn)       __define_initcall(fn, 6)
#define device_initcall_sync(fn)  __define_initcall(fn, 6s)
#define late_initcall(fn)         __define_initcall(fn, 7)
#define late_initcall_sync(fn)    __define_initcall(fn, 7s)

#define __initcall(fn) device_initcall(fn)
```

## 五、等级顺序与典型用途

| 等级 | 宏 | 段名 | 典型用途 |
|---|---|---|---|
| early | `early_initcall` | `.initcallearly.init` | 最早期，SMP 起来之前 |
| 0 | `pure_initcall` | `.initcall0.init` | 纯计算，无任何依赖 |
| 1 | `core_initcall` | `.initcall1.init` | 核心子系统（如 debugfs） |
| 2 | `postcore_initcall` | `.initcall2.init` | 核心之后（如 bus 注册） |
| 3 | `arch_initcall` | `.initcall3.init` | 架构相关（如 pinctrl、clock） |
| 4 | `subsys_initcall` | `.initcall4.init` | 子系统（如 SPI、I2C 总线） |
| 5 | `fs_initcall` | `.initcall5.init` | 文件系统 |
| rootfs | `rootfs_initcall` | `.initcallrootfs.init` | 根文件系统相关 |
| 6 | `device_initcall` | `.initcall6.init` | 设备驱动（**最常用**） |
| 7 | `late_initcall` | `.initcall7.init` | 收尾补锅 |

`module_init` 就是 `device_initcall` 的马甲：驱动编进内核（`=y`）时按等级 6 排队；编成模块（`=m`）时变成模块的加载入口，由 `insmod` 触发，跟启动顺序无关。

## 六、带 `_sync` 的版本在等什么

`do_initcalls` 在每一级里是**先跑普通段、再跑 `_sync` 段**：

```text
initcall1.init  →  initcall1s.init  →  initcall2.init  →  initcall2s.init  → ...
```

`_sync` 的语义很朴素：**本等级普通段全部跑完，才轮到同级的 `_sync` 段**。所以它表达的是"在同一等级里，我比别人晚一点"，而不是"我比下一级早一点"。

## 七、几个容易踩的坑

| 坑 | 说明 |
|---|---|
| 以为等级数字就是执行序号 | 数字只是段名；同段内按链接顺序，`early` 和 `rootfs` 是字母段名，不是 0/8 |
| `__init` 函数被跨阶段调用 | `.init` 段在 `free_initmem()` 之后被释放，启动后再调用就是野指针 |
| 以为 initcall 顺序等于 probe 顺序 | initcall 里通常只是**注册**驱动；真正 probe 在总线匹配时，可能延后、可能异步 |
| 随手改等级"让它先跑" | 改了可能抢在依赖之前，故障表现为随机 panic 或资源申请失败，极难查 |
| 找不到谁初始化了某个设备 | 打开 `initcall_debug` 内核参数，`dmesg` 里会打出每个 initcall 的名字和耗时 |

`initcall_debug` 是排查启动慢最省事的开关：

```bash
# 内核命令行加 initcall_debug，启动后
dmesg | grep -i initcall | sort -t: -k2 -n | tail
```

## 八、一句话总结

initcall 的本质是**用链接器段做排序**：宏负责把函数指针塞进带等级号的段，启动代码负责按等级顺序遍历调用；你声明的是"我属于哪一级"，而不是"我第几个跑"。
