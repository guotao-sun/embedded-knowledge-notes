# 注册设备与创建设备的区别

## 一、先说结论

这两件事经常被混为一谈，其实是两个层面：

| 操作 | 面向谁 | 干了什么 |
|---|---|---|
| `cdev_add()` | **内核** | 把 "dev_t → file_operations" 的路由表登记进字符设备子系统 |
| `device_create()` | **用户空间** | 在 sysfs 建目录、发 uevent，让 udev 生成 `/dev/xxx` |

**前者决定"能不能 open"，后者决定"有没有那个文件"。** 少了前者 open 报 `ENODEV`，少了后者只是 `/dev` 下没节点。

## 二、设备号（dev_t）是唯一路由入口

在 Linux 字符设备体系中，设备节点（`/dev/xxx`）最终一定对应一个 `dev_t`（主设备号 + 次设备号）。

**VFS 识别字符设备的唯一索引就是 dev_t，没有 dev_t，就没有路由入口。**

> 反过来说：很多"被别的驱动调用的驱动"本来就不应该有设备节点，也不需要设备号（dev_t）——比如 pinctrl、clk、regulator。

### 判断标准（非常重要）

Linux 里驱动是否需要 dev_t，本质只看一件事：

> **是否需要"用户空间访问入口"**

需要就建节点，不需要就别申请号，不要为了"看起来完整"硬加一套。

### 个人理解

- 理论上系统设计不使用 dev_t 也可以，但是使用 dev_t 可以解耦得更完全且更准确——用户态只跟"字符设备接口"打交道，不关心背后是哪颗芯片。
- 只构建设备号以及创建设备节点，不 `cdev_add`、不建类，加载模块时会报错吗？**模块"加载阶段"一般不会报错。** 内核不会因为你少写 `cdev_add()` 或 `class_create()` 就拒绝加载模块——错误只会在真正 `open()` 的时候暴露。

## 三、cdev_add()：注册"字符设备能力"

```c
cdev_init(&icm20608dev.cdev, &icm20608_ops);
cdev_add(&icm20608dev.cdev, icm20608dev.devid, ICM20608_CNT);
```

它做的事情是：**把"驱动能力"注册进内核字符设备子系统。**

核心作用：

- 告诉内核："这个 major:minor 对应的设备，有这些 file_operations"
- 建立映射关系：

```text
设备号（dev_t） ──→ file_operations（open/read/write/ioctl）
```

注意 `cdev_add` 一次可以挂一段连续次号（`ICM20608_CNT`），这些次号共用同一份 ops——这就是"行为是驱动级、设备是实例级"的落地方式。

## 四、device_create()：创建设备"节点 + 设备模型对象"

> 创建 `/dev/` 设备节点不是必须创建类，但是创建类以后可以通过设备模型自动创建节点，更方便。

```c
device_create(icm20608dev.class, NULL, icm20608dev.devid, NULL, ICM20608_NAME);
```

它做的事情是：**向 Linux 设备模型 + sysfs + udev 提供信息。** 具体三件：

### 1. 创建 sysfs 设备对象

```text
/sys/class/icm20608/icm20608
```

里面有 `dev`（记录主次号）、`uevent`、以及驱动自己加的属性文件。

### 2. 通知 udev（用户态守护进程）

```text
kernel → netlink(uevent) → udev
```

### 3. 最终生成

```text
/dev/icm20608
```

udev 收到 uevent 后按规则建节点、设权限、设属主。没有 udev 的精简系统（busybox mdev 或纯静态 rootfs）就得自己 `mknod`：

```bash
mknod /dev/icm20608 c 200 0
```

## 五、四步对比总结

| 操作 | 作用层级 | 核心作用 |
|------|---------|---------|
| `register_chrdev_region()` | 设备号 | 申请/保留 dev_t 范围 |
| `cdev_init()` + `cdev_add()` | 内核字符设备子系统 | 绑定 dev_t 与 file_operations |
| `class_create()` | 设备模型 | 创建设备类（sysfs 容器） |
| `device_create()` | 设备模型 + udev | 创建设备对象，触发 udev 生成 `/dev/xxx` |

## 六、完整配对写法

```c
static int __init xxx_init(void)
{
    int ret;

    ret = alloc_chrdev_region(&devid, 0, 1, "xxx");
    if (ret) return ret;

    cdev_init(&xxxdev.cdev, &xxx_ops);
    xxxdev.cdev.owner = THIS_MODULE;
    ret = cdev_add(&xxxdev.cdev, devid, 1);
    if (ret) goto err_cdev;

    xxxdev.class = class_create(THIS_MODULE, "xxx");
    if (IS_ERR(xxxdev.class)) {
        ret = PTR_ERR(xxxdev.class);
        goto err_region;
    }

    device_create(xxxdev.class, NULL, devid, NULL, "xxx%d", 0);
    return 0;

err_region:
    cdev_del(&xxxdev.cdev);
err_cdev:
    unregister_chrdev_region(devid, 1);
    return ret;
}
```

卸载严格逆序：`device_destroy` → `class_destroy` → `cdev_del` → `unregister_chrdev_region`。

> `device_create` 的 `drvdata` 参数（第 4 个）可以传设备结构体指针，之后在 sysfs 属性回调里用 `dev_get_drvdata()` 取回来——这是 sysfs 属性访问私有数据的标准通道。

## 七、一句话总结

**`cdev_add` 是给内核看的路由表，`device_create` 是给用户看的门牌；路由表没有 → `ENODEV`，门牌没有 → `/dev` 里找不到文件。**
