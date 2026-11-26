# Linux 驱动设备号

## 一、先说结论

- **设备号 = `dev_t` = 主设备号 + 次设备号**，VFS 认字符设备的唯一索引就是它
- **主号认"驱动"，次号认"实例"**；同一份 `file_operations` 可以配多个设备号
- **`register_chrdev()` 是个合集**：申请设备号 + `cdev_init` + `cdev_add`，一步顶三步
- **`device_create()` 之前必须有 `class`**，因为它在设备模型里要有"归属"

> 一句话记：**dev_t 是路由入口，cdev 是能力绑定，class/device 是给用户空间看的门牌。**

## 二、dev_t 与主次号

```c
dev_t dev;                 /* 32 位整数 */
MAJOR(dev);                /* 取主设备号 */
MINOR(dev);                /* 取次设备号 */
MKDEV(major, minor);       /* 拼成 dev_t */

unsigned int major = 0;    /* 传 0 = 让内核动态分配 */
alloc_chrdev_region(&devid, 0, count, "mychrdev");   /* 动态 */
register_chrdev_region(devid, count, "mychrdev");    /* 静态，需自己指定主号 */
```

现代内核里 `dev_t` 是 12 位主号 + 20 位次号，所以主号最大 4095、次号可到 100 万级。查哪些主号已被占用：

```bash
cat /proc/devices
```

## 三、行为是"驱动级"，设备是"实例级"

原文最重要的一句：

> **行为（ops）是"驱动级"**，**设备（cdev）是"实例级"**。

```
driver（一份代码）
   └── file_operations ops        ← 驱动级：所有实例共用
          ↑
    cdev（每个设备号一个）
          ↑
    dev_t（主:次）
```

多个设备号 → 可以映射到同一个 cdev → 这个 cdev 绑定一份 ops。反过来，同一个驱动要管两个设备，就是两个 `cdev`、两段次号、共用一份 `ops`（如 `icm20608_ops` 同时服务 ICM20608 和 ICM20608G）。

## 四、register_chrdev 到底等于什么

```text
register_chrdev()
    ↓
__register_chrdev()
    ├── alloc_chrdev_region() / register_chrdev_region()
    │       ↓
    │   申请设备号
    │
    ├── cdev_init()
    │       ↓
    │   初始化 cdev（把 ops 填进去）
    │
    └── cdev_add()
            ↓
        注册 cdev（挂进字符设备子系统）
```

老接口的问题是：**它一次占掉整个主设备号下的 256 个次号**，还拿不到 `cdev` 指针，不便做多实例和 sysfs。所以现代驱动都拆开写，见下一节。

## 五、现代注册流程（推荐写法）

```c
/* 1. 申请设备号（动态） */
alloc_chrdev_region(&devid, 0, DEV_CNT, DEV_NAME);

/* 2. 绑定 cdev 与 ops */
cdev_init(&mydev.cdev, &mydev_ops);
mydev.cdev.owner = THIS_MODULE;
cdev_add(&mydev.cdev, devid, DEV_CNT);

/* 3. 建设备类（sysfs 容器） */
mydev.class = class_create(THIS_MODULE, DEV_NAME);

/* 4. 创建设备（触发 udev 生成 /dev/xxx） */
device_create(mydev.class, NULL, devid, NULL, DEV_NAME);
```

卸载严格按反序，一步都不能漏：

```c
device_destroy(mydev.class, devid);
class_destroy(mydev.class);
cdev_del(&mydev.cdev);
unregister_chrdev_region(devid, DEV_CNT);
```

> 顺序错了会报 `BUG: unable to handle kernel paging request` 或 `kobject` 相关警告——因为 sysfs 里的目录还在，而它引用的对象已经被释放。

## 六、为什么必须创建类才能 device_create

`device_create()` 创建的并不只是你看到的 `/dev/led` 这个文件。它本质上是在 Linux **设备模型（driver model）**里创建一个 `struct device`，而 `class` 是这个 device 在设备模型中的归属层级/容器：

```text
/sys/class/led/led0        ← class 是目录，device 是里面的条目
```

`device_create()` 是设备模型的操作，要把新建的 `struct device` 挂到某个 class 下，所以必须先有 `struct class`。（当然也可以绕开设备模型手工 `mknod`，但那样就失去了热插拔和权限管理。）

## 七、设备号不是必需品

判断标准只有一条：

> **这个驱动需不需要"用户空间访问入口"？**

- 需要 → 必须有 dev_t + cdev + 设备节点（LED、按键、ADC、字符型 sensor）
- 不需要 → 可以完全没有设备号（被别的驱动调用的"helper 驱动"，比如 pinctrl、clk、regulator）

反过来，**只申请了设备号、没 `cdev_add`** 会怎样？模块加载阶段一般不报错——内核不会因为你少写 `cdev_add()` 或 `class_create()` 就拒绝加载。但用户打开 `/dev/xxx` 时 VFS 查不到对应的 `cdev`，`open()` 直接返回 `ENODEV`。

## 八、为什么要设置私有数据

`open()` 时把设备结构体挂到 `filp->private_data`，后面的 `read/write/ioctl/close` 直接从 `file` 里取：

```c
/* open 中设置 */
filp->private_data = &testdev;

/* read/write 中获取 */
struct test_dev *dev = filp->private_data;
```

好处有两个：**不用全局变量**（同一驱动多实例时不会串），**不用每次重算**（`container_of` 只做一次）。

## 九、踩坑清单

| 现象 | 原因 | 修法 |
|---|---|---|
| `open: No such device` | 只申请号，没 `cdev_add` | 补 `cdev_add` |
| `/dev/xxx` 不存在 | 没 `class_create` / `device_create`，或 udev 没跑 | 补建类建设备；嵌入式可 `mknod` 兜底 |
| `insmod` 报 `Device or resource busy` | 主号被别人占了 | 改用 `alloc_chrdev_region` 动态分配 |
| 卸载后 `rmmod` 卡住 | 还有进程开着设备节点 | 先 `close`，`rmmod` 前 `fuser -k /dev/xxx` |
| 权限不够打不开 | 设备节点默认 0600 | udev 规则改权限，或 `chmod` |

## 十、一句话总结

**主号认驱动、次号认实例；ops 一份共享，cdev 一号一个；号是内核路由，节点是用户门牌——class 就是挂门牌的那面墙。**
