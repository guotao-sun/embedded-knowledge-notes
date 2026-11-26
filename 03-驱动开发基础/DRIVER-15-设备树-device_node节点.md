# Linux 设备树的节点 device_node

## 一、先说结论

内核里的设备树不是"树形对象"，而是**用三个指针手工串起来的链表森林**：

- `parent` **向上**一指
- `child` 指向**第一个**子节点
- `sibling` 在同一个 parent 下**横向**串成链

所以遍历写法永远是"先下到 child，再顺着 sibling 走一圈"，`for_each_child_of_node` 宏干的就是这件事。

## 二、节点关系指针

| 指针 | 含义 |
|------|------|
| `N.parent` | 指向父节点 |
| `N.child` | 指向"第一个子节点" |
| `N.sibling` | 指向"同级下一个节点" |

> `struct device_node *sibling;` 表示的是：当前节点在同一层级（同一个 parent 下）的下一个兄弟节点。

**注意没有"上一个兄弟"指针**——设备树只支持"从父到第一个子再往后走"，不能反向。这也是为什么"找父节点容易、找前一个兄弟难"。

## 三、device_node 结构体

```c
struct device_node {
    const char *name;              /* 节点名，如 "serial" */
    const char *type;              /* device_type，老式属性 */
    phandle phandle;               /* 被别的节点引用时的编号 */
    const char *full_name;         /* 完整路径名，如 "serial@02020000" */
    struct fwnode_handle fwnode;   /* 通用固件节点接口（DT/ACPI 统一） */

    struct property *properties;   /* 属性链表（单向） */
    struct property *deadprops;    /* removed properties */

    struct device_node *parent;    /* 父 */
    struct device_node *child;     /* 第一个子 */
    struct device_node *sibling;   /* 下一个兄弟 */

    struct kobject kobj;           /* /sys/firmware/devicetree 里的目录 */
    unsigned long _flags;
    void *data;

#if defined(CONFIG_SPARC)
    const char *path_component_name;
    unsigned int unique_id;
    struct of_irq_controller *irq_trans;
#endif
};
```

两个容易忽略的点：

- **`full_name` 就是节点名 + 地址**：`serial@02020000`。`of_node_full_name()` 返回的就是它，日志里打印的也是它
- **`properties` 是链表**，不是数组：每个 `struct property { char *name; int length; void *value; }`，靠 `next` 串起来，所以"读属性"本质是"链表线性查找"

## 四、节点树结构示意

```text
        root (/)
         │
    ┌────┴────┐
    │         │
  node A    node B
    │
 ┌──┴──┐
 │     │
 A1    A2
```

- `root.child` → node A
- `node A.sibling` → node B
- `node A.child` → A1
- `A1.sibling` → A2
- `A1.parent` → node A

用代码走一遍就是这个样子：

```c
/* 遍历 root 的所有子节点 */
for_each_child_of_node(root, child) {
    pr_info("%s\n", child->full_name);
}

/* 等价的手写版 —— 看清 child 和 sibling 的分工 */
for (child = root->child; child; child = child->sibling) {
    pr_info("%s\n", child->full_name);
}
```

**"下钻用 child，横走用 sibling"** 是这段代码唯一需要记的东西。

## 五、节点是怎么被找到的

| 方式 | API | 说明 |
|---|---|---|
| 按路径 | `of_find_node_by_path("/soc/uart1")` | 路径必须与 `full_name` 一致 |
| 按 phandle | `of_find_node_by_phandle(ph)` | 解析 `&label` 编译出的编号 |
| 按名字 | `of_find_node_by_name(NULL, "uart1")` | 全局搜，慎用 |
| 从当前节点 | `of_get_child_by_name(np, "port")` | 只在子节点里找 |
| 从设备 | `dev->of_node` | 驱动最常用，probe 时已填好 |

`&uart1` 这种引用在编译后变成 `phandle = <0x1f>`，内核解析时通过 `of_find_node_by_phandle()` 换回节点指针。**所以 label 只是编译期的糖，运行期只有 phandle。**

## 六、引用计数：别忘 of_node_get / put

`device_node` 是带 `kobject` 的，有引用计数：

```c
struct device_node *np = of_find_node_by_path("/soc/uart1");   /* 计数 +1 */
...
of_node_put(np);                                                /* 计数 -1 */
```

- `of_find_*` 系列**返回时已加引用**，用完必须 `of_node_put`
- `dev->of_node` 是设备持有的，**不要 put**
- `for_each_child_of_node` 内部会管计数，但**循环里 `break` 提前退出时要自己 put 当前节点**

漏 `of_node_put` 的后果不是立刻崩，而是 `rmmod` 时节点释放不掉、下次 `of_find` 还能拿到"幽灵节点"——很难查。

## 七、跟 /proc/device-tree 的关系

```bash
ls /proc/device-tree/soc/
```

这些目录和文件就是 `device_node` 树的"投影"：每个节点的 `kobj` 在 `/sys/firmware/devicetree/base` 下有个同名目录，每个 `property` 是一个文件，文件内容就是 `value` 的原始字节。

所以"cat 一个属性看到乱码"很正常——它是二进制，不是文本。用 `hexdump -C` 才看得清。

## 八、一句话总结

**device_node 就是"parent 向上、child 下钻、sibling 横走"的三指针树，属性是单向链表；`&label` 编译成 phandle、运行期靠查表换回指针，用完记得 `of_node_put`。**
