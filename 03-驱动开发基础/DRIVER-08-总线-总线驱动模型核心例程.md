# Linux 总线驱动模型核心例程

> 参考野火 Linux 教程

## 一、先说结论

这一篇用一个自己造的 `xbus` 把总线驱动模型的最小闭环跑通，三件套：

```text
xbus.ko   ← 注册一种总线（只提供 match 规则）
xdrv.ko   ← 注册一个驱动（提供 probe / remove）
xdev.ko   ← 注册一个设备（提供 name，等匹配）
```

三者的关系就一句话：**bus 判断 device 和 driver 的名字是否相同，相同就调 driver 的 probe。**

- 名字必须对得上：驱动里 `.name = "xdev"`，设备叫 `"xdev"`，`xbus_match` 用 `strncmp` 比较
- 加载顺序无所谓（谁后到谁触发重新匹配），但**总线必须先注册**，否则 `driver_register` 找不到归属
- 每个 `device` 必须实现 `release`，否则卸载时报 `Device 'xxx' does not have a release() function, it is broken and must be fixed`

## 二、三个核心结构体

### struct bus_type

```c
struct bus_type {
    const char              *name;
    const struct attribute_group **bus_groups;
    const struct attribute_group **dev_groups;
    const struct attribute_group **drv_groups;

    int (*match)(struct device *dev, struct device_driver *drv);
    int (*uevent)(struct device *dev, struct kobj_uevent_env *env);
    int (*probe)(struct device *dev);
    int (*remove)(struct device *dev);

    int (*suspend)(struct device *dev, pm_message_t state);
    int (*resume)(struct device *dev);

    const struct dev_pm_ops *pm;

    struct subsys_private *p;
};
```

真正必填的只有 `name` 和 `match`。

### struct device

```c
struct device {
    struct device *parent;        /* 父设备 */
    struct bus_type *bus;         /* 所属总线（SPI / I2C / platform） */
    struct device_driver *driver; /* 绑定的驱动（匹配成功后才有） */
    void *driver_data;            /* 私有数据（你常用的） */
    struct kobject kobj;          /* 内核对象（sysfs） */
    ...
};
```

### struct device_driver

```c
struct device_driver {
    const char *name;
    struct bus_type *bus;         /* 这个驱动属于哪个总线 */
    int (*probe)(struct device *dev);
    int (*remove)(struct device *dev);
    ...
};
```

## 三、bus（总线）模块

```c
#include <linux/init.h>
#include <linux/module.h>
#include <linux/device.h>

/*
 * 负责总线下的设备与驱动匹配：
 * 用字符串比较，对比驱动名和设备名，相同返回 1，不同返回 0
 */
int xbus_match(struct device *dev, struct device_driver *drv)
{
    printk("%s-%s\n", __FILE__, __func__);
    if (!strncmp(dev_name(dev), drv->name, strlen(drv->name))) {
        printk("dev & drv match\n");
        return 1;
    }
    return 0;
}

/* 总线名字 */
static char *bus_name = "xbus";

/* 让用户能通过 cat 查询总线名 */
ssize_t xbus_test_show(struct bus_type *bus, char *buf)
{
    return sprintf(buf, "%s\n", bus_name);
}

/* 属性文件 xbus_test：仅文件拥有者可读 */
BUS_ATTR(xbus_test, S_IRUSR, xbus_test_show, NULL);

/* 定义一种新总线，最重要的成员是 match 回调 */
static struct bus_type xbus = {
    .name  = "xbus",
    .match = xbus_match,
};
EXPORT_SYMBOL(xbus);        /* 让 xdrv / xdev 能 extern 引用 */

static __init int xbus_init(void)
{
    printk("xbus init\n");
    bus_register(&xbus);
    bus_create_file(&xbus, &bus_attr_xbus_test);
    return 0;
}
module_init(xbus_init);

static __exit void xbus_exit(void)
{
    printk("xbus exit\n");
    bus_remove_file(&xbus, &bus_attr_xbus_test);
    bus_unregister(&xbus);
}
module_exit(xbus_exit);

MODULE_AUTHOR("embedfire");
MODULE_LICENSE("GPL");
```

## 四、driver（驱动）模块

```c
#include <linux/init.h>
#include <linux/module.h>
#include <linux/device.h>

extern struct bus_type xbus;

char *name = "xdrv";

/* 属性文件 drvname 的 show 回调 */
ssize_t drvname_show(struct device_driver *drv, char *buf)
{
    return sprintf(buf, "%s\n", name);
}
DRIVER_ATTR_RO(drvname);

int xdrv_probe(struct device *dev)
{
    printk("%s-%s\n", __FILE__, __func__);
    return 0;
}

int xdrv_remove(struct device *dev)
{
    printk("%s-%s\n", __FILE__, __func__);
    return 0;
}

/* 驱动名必须和设备名相同，否则匹配不上 */
static struct device_driver xdrv = {
    .name   = "xdev",
    .bus    = &xbus,      /* 挂到已注册的 xbus 下 */
    .probe  = xdrv_probe, /* 匹配成功后执行 */
    .remove = xdrv_remove,
};

static __init int xdrv_init(void)
{
    printk("xdrv init\n");
    driver_register(&xdrv);
    driver_create_file(&xdrv, &driver_attr_drvname);
    return 0;
}
module_init(xdrv_init);

static __exit void xdrv_exit(void)
{
    printk("xdrv exit\n");
    driver_remove_file(&xdrv, &driver_attr_drvname);
    driver_unregister(&xdrv);
}
module_exit(xdrv_exit);

MODULE_AUTHOR("embedfire");
MODULE_LICENSE("GPL");
```

注意 `.name` 写的是 `"xdev"` 而不是 `"xdrv"`——因为匹配是**拿驱动名去比设备名**，所以驱动名实际充当"我能驱动谁"的声明。

## 五、device（设备）模块

```c
#include <linux/init.h>
#include <linux/module.h>
#include <linux/device.h>

extern struct bus_type xbus;

void xdev_release(struct device *dev)
{
    printk("%s-%s\n", __FILE__, __func__);
}

unsigned long id = 0;

ssize_t xdev_id_show(struct device *dev, struct device_attribute *attr, char *buf)
{
    return sprintf(buf, "%d\n", id);
}

/*
 * 通过 sysfs 写这个文件，就能改驱动里的 id：
 * kstrtoul 第三个参数 10 表示按十进制解析
 */
ssize_t xdev_id_store(struct device *dev, struct device_attribute *attr,
                      const char *buf, size_t count)
{
    kstrtoul(buf, 10, &id);
    return count;
}

DEVICE_ATTR(xdev_id, S_IRUSR | S_IWUSR, xdev_id_show, xdev_id_store);

static struct device xdev = {
    .bus     = &xbus,
    .release = xdev_release,      /* 必须实现，否则卸载时内核报错 */
};

static __init int xdev_init(void)
{
    printk("xdev init\n");
    dev_set_name(&xdev, "xdev");   /* 4.x 后期 .init_name 字段已移除，改用 dev_set_name */
    device_register(&xdev);
    device_create_file(&xdev, &dev_attr_xdev_id);
    return 0;
}
module_init(xdev_init);

static __exit void xdev_exit(void)
{
    printk("xdev exit\n");
    device_remove_file(&xdev, &dev_attr_xdev_id);
    device_unregister(&xdev);
}
module_exit(xdev_exit);            /* 原示例这里误写成 module_init，会导致卸载不生效 */

MODULE_AUTHOR("embedfire");
MODULE_LICENSE("GPL");
```

两处修正说明：

1. **`.init_name` 换成 `dev_set_name()`**：`init_name` 在 4.13 之后被移除，新版内核编译不过。
2. **`module_exit(xdev_exit)`**：原示例结尾重复写了 `module_init(xdev_init);`，导致 `rmmod` 时 `xdev_exit` 根本不注册，模块卸不掉。

## 六、Makefile

```makefile
KERNEL_DIR = ../ebf-buster-linux/build_image/build
ARCH = arm
CROSS_COMPILE = arm-linux-gnueabihf-
export ARCH CROSS_COMPILE

obj-m := xdev.o xbus.o xdrv.o

all:
	$(MAKE) -C $(KERNEL_DIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KERNEL_DIR) M=$(CURDIR) clean
```

> 原示例把 `clean` 写成了 `modules clean:` 两个目标，Make 会报 "No rule to make target"，也一并修正。

## 七、加载与验证

```bash
insmod xbus.ko    # 先注册总线
insmod xdrv.ko    # 再注册驱动
insmod xdev.ko    # 最后注册设备 → 触发 match → probe
```

加载完看 dmesg，期望顺序是：

```text
xbus init
xdrv init
xdev init
xdev-xdrv match        ← xbus_match 打印
drivers/base/dd.c-xdrv_probe   ← probe 被调用
```

sysfs 里的对应产物：

```bash
ls /sys/bus/xbus/                    # devices/  drivers/
cat /sys/bus/xbus/xbus_test          # 属性文件，输出 xbus
cat /sys/bus/xbus/drivers/xdev/drvname
cat /sys/bus/xbus/devices/xdev/xdev_id
echo 5 > /sys/bus/xbus/devices/xdev/xdev_id   # 写进驱动的 id 变量
```

反序卸载：`rmmod xdev` → `xdrv` → `xbus`。

> 驱动和设备的注册顺序不影响匹配结果，driver core 会在任一方注册时重新遍历匹配——先装驱动也没问题。

## 八、几个坑

| 现象 | 原因 | 修法 |
|---|---|---|
| 加载了但 probe 不执行 | 驱动 `.name` 设备名不一致，或 `strncmp` 长度算错 | 两边打印 `dev_name(dev)` / `drv->name` 对比 |
| `xdrv.ko` 加载报 `Unknown symbol xbus` | 没先 `insmod xbus.ko`，或没 `EXPORT_SYMBOL` | 先装总线；导出符号 |
| `rmmod xdev` 报 `does not have a release()` | `struct device` 没填 `release` | 补一个空实现的 `release` |
| 卸载后 `/sys/bus/xbus/devices/xdev` 还在 | `module_exit` 写成了 `module_init` | 改成 `module_exit` |
| `bus_register` 失败返回 `-EEXIST` | 同名总线已注册 | 换名字，或先卸载旧的 |

## 九、一句话总结

**自己造一条总线，只要 `name` + `match`；驱动 `.name` 声明"我能驱动谁"，设备给同名，driver core 就会在任一方注册时重新遍历并回调 probe。**
