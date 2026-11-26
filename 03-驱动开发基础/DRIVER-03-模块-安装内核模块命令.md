# 安装内核模块命令

## 一、先说结论

- `insmod` 只认**路径**，不做依赖解析；`modprobe` 只认**模块名**，会先读 `modules.dep` 把依赖全加载上
- `depmod` 的职责只有一件事：**扫描 `/lib/modules/<版本>/` 下的 `.ko`，生成 `modules.dep` 依赖数据库**
- 新编的 `.ko` 拷进系统后，**必须先 `depmod` 再 `modprobe`**，否则报 `module not found`
- 开发调试用 `insmod`，量产/开机加载用 `modprobe`

## 二、命令对比

| 命令 | 作用 | 场景 |
|------|------|------|
| `insmod` | 原始加载器，只加载指定的 `.ko` 文件 | 开发调试，单模块 |
| `depmod` | 构建依赖数据库（`modules.dep`） | 模块安装后执行一次 |
| `modprobe` | 生产级加载器，按模块名自动解析依赖 | 正常加载、开机加载 |
| `rmmod` | 卸载模块（模块名，不带 `.ko`） | 移除已加载模块 |
| `lsmod` | 列出已加载模块及其被引用次数 | 排查是否加载成功 |
| `modinfo` | 查看模块信息（vermagic、依赖、参数、作者） | 排查版本不匹配 |

## 三、depmod 到底在做什么

`depmod` 默认不是固定更新 `/lib/modules` 下某一个目录，而是更新**当前运行内核**对应的模块目录：

```bash
depmod $(uname -r)      # 等价于直接 depmod
ls /lib/modules/$(uname -r)/modules.dep
```

生成的 `modules.dep` 长这样，冒号前是模块，冒号后是它依赖的模块：

```text
kernel/drivers/net/phy/libphy.ko: kernel/drivers/net/phy/mdio-board.ko
```

`modprobe` 就是靠它做拓扑排序，先加载依赖再加载自己。

## 四、没有 depmod 会怎样

```text
modprobe → 找不到 modules.dep（或里面没有你的模块） → module not found in directory
```

所以标准动作是：**拷 `.ko` → `depmod` → `modprobe`**。只 `insmod /path/to/xxx.ko` 是可以的，但它不会帮你加载依赖，缺依赖时直接报 `Unknown symbol in module`。

## 五、典型流程

```bash
# 1. 拷贝模块（注意要放到当前内核的目录下）
scp chrdevbase.ko root@192.168.55.71:/lib/modules/4.19.232/

# 2. 构建依赖数据库
depmod

# 3. 加载（自动处理依赖）
modprobe chrdevbase

# 4. 确认
lsmod | grep chrdevbase
dmesg | tail -20

# 5. 卸载
modprobe -r chrdevbase
```

开发阶段更常用的是"不落地"的方式，改一次编一次直接压进去：

```bash
insmod ./chrdevbase.ko     # 必须带路径
rmmod chrdevbase           # 卸载用模块名，不带 .ko
```

## 六、几个必须知道的细节

- **`insmod` 一定要全路径**：`insmod chrdevbase.ko` 会去 `/lib/modules` 里找，找不到就报错
- **`rmmod` 不能带 `.ko`**：带后缀会被当成文件名
- **模块被引用时卸不掉**：`lsmod` 第三列是引用计数，非 0 就 `rmmod` 失败（`Module xxx is in use`）
- **开机自动加载**：写进 `/etc/modules-load.d/xxx.conf`（Debian 系）或 `/etc/modules`，不要写进 `rc.local`
- **黑名单**：`/etc/modprobe.d/blacklist.conf` 里 `blacklist xxx`，防止 `modprobe -a` 或 udev 自动拉起

## 七、常见报错对照

| 报错 | 原因 | 修法 |
|---|---|---|
| `Invalid module format` | 模块的 `vermagic` 与内核不匹配（内核版本/编译选项不同） | 用目标内核的源码树重新编译 |
| `Unknown symbol in module` | 依赖模块没加载，或符号没 `EXPORT_SYMBOL` | 先 `modprobe` 依赖；导出符号 |
| `module not found in directory /lib/modules/...` | 没 `depmod`，或 `.ko` 放错版本目录 | `depmod` 后重试 |
| `Operation not permitted` | 内核 `CONFIG_MODULE_SIG` 强制签名 | 关签名或用对应 key 签名 |
| `File exists` | 模块已经加载 | 先 `rmmod` |

## 八、一句话总结

**`insmod` 按路径、`modprobe` 按名字；名字能查到靠 `depmod` 生成的 `modules.dep`——所以顺序永远是 拷文件 → depmod → modprobe。**
