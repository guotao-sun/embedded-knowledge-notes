# Linux 开发板设置静态 IP

## 一、先说结论

三种改法，按"要不要重启还在"来选：

| 方式 | 命令/文件 | 重启后 | 适合 |
|---|---|---|---|
| 临时 | `ifconfig eth1 192.168.55.71 ...` | 失效 | 试通网线、临时调试 |
| 规范永久 | `/etc/network/interfaces` | 保留 | 要长期用的板子 |
| 偷懒永久 | `/etc/rc.local` | 保留 | rootfs 没装 networking 服务时（老 BSP 常用） |

**先 `ifconfig` 试通，再写进配置文件**——顺序反了，配置文件写错会导致板子起不来网、你只能上串口。

## 二、临时设置（重启失效）

```bash
ifconfig eth1 192.168.55.71 netmask 255.255.255.0 up
route add default gw 192.168.55.1
```

两条分开的原因：`ifconfig` 只管"网卡地址"，**路由要单独加**。很多新手只配了 IP，ping 不通外网，就是缺默认网关。

验证：

```bash
ifconfig eth1        # 地址有没有、up 没 up
route -n             # 默认网关在不在（Destination 0.0.0.0 那一行）
ping -c 3 192.168.55.72
```

## 三、永久设置：`/etc/network/interfaces`

```bash
vi /etc/network/interfaces
```

```text
auto lo
iface lo inet loopback

# 双网卡：eth0 用 DHCP 连外网，eth1 静态连调试网
auto eth0
iface eth0 inet dhcp

auto eth1
iface eth1 inet static
    address 192.168.55.71
    netmask 255.255.255.0
    gateway 192.168.55.1
    dns-nameservers 8.8.8.8 114.114.114.114
```

字段含义：

| 字段 | 作用 | 写错的后果 |
|---|---|---|
| `auto eth1` | 开机自动 `ifup eth1` | 不写：开机网卡是 down 的 |
| `iface eth1 inet static` | 这网卡用静态 IP | 拼错：整段被忽略 |
| `address` | IP | 与别的设备冲突 → 时通时不通 |
| `netmask` | 子网掩码 | 写错 → 能 ping 网关、ping 不到同网段设备 |
| `gateway` | 默认网关 | 不写 → 只能同网段通信 |
| `dns-nameservers` | DNS | 不写 → `ping 域名` 失败，`ping IP` 正常 |

### 让配置生效

```bash
ifdown eth1 && ifup eth1          # 只重配这一张
# 或整体重启网络
/etc/init.d/networking restart
```

> `ifdown eth1` 报 `ifdown: interface eth1 not configured` 多半是名字写错（`eth0`/`eth1` 还是 `enp0s3`）。先用 `ip link` 或 `ifconfig -a` 确认**真实的接口名**。

## 四、偷懒做法：写进 `/etc/rc.local`

很多嵌入式 rootfs 没装 `ifupdown`，`interfaces` 写了也没人读——那就直接写进开机脚本：

```bash
vi /etc/rc.local
```

```sh
#!/bin/sh -e
echo 30000 > /proc/sys/vm/min_free_kbytes
source /etc/profile
/opt/QDesktop >/dev/null 2>&1 &

# set eth1 ip
/sbin/ifconfig eth1 192.168.55.71 netmask 255.255.255.0 up
/sbin/route add default gw 192.168.55.1 dev eth1

exit 0
```

三个要点：

1. 用**绝对路径**（`/sbin/ifconfig`），因为 `rc.local` 执行时 PATH 可能还没设好；
2. 必须 `exit 0` 结尾，否则可能挡住后续启动；
3. `chmod +x /etc/rc.local`（有些 rootfs 默认没有执行位）。

## 五、验证与自检

```bash
ifconfig eth1                  # 有 IP、有 UP 标志
route -n                       # 有默认网关
cat /etc/resolv.conf           # 有 nameserver
ping -c 3 192.168.55.72        # 通宿主机
ping -c 3 8.8.8.8              # 通外网（说明网关对）
ping -c 3 www.baidu.com        # 通 DNS（说明 DNS 对）
```

四条 ping 是**递进**的：

| 哪条不通 | 说明 |
|---|---|
| 第一条不通 | IP/网段/网线/防火墙 |
| 第二条不通 | 网关错 |
| 第三条不通 | DNS 没配 |

## 六、常见问题

| 现象 | 原因 | 修法 |
|---|---|---|
| `ifconfig: eth1: error fetching interface information` | 没这张网卡 / 驱动没加载 | `ifconfig -a`、`dmesg | grep eth` |
| 配了 IP 但 `route -n` 没有默认网关 | 只配了 IP | 补 `route add default gw` |
| 能 ping 别人，别人 ping 不到你 | 掩码不一致 / 对端 ARP 缓存 | 核对 netmask，`arp -d` 清缓存 |
| 重启后 IP 回到旧的 | 只做了临时配置 | 写 `interfaces` 或 `rc.local` |
| `ping 域名` 失败、`ping IP` 正常 | 没 DNS | 加 `dns-nameservers` 或写 `/etc/resolv.conf` |
| 双网卡只能通一张 | 默认网关冲突 | 只给一张设 gateway，或加静态路由 |

## 七、一句话总结

**先 `ifconfig` + `route` 临时试通，再落到 `/etc/network/interfaces`（有 ifupdown）或 `/etc/rc.local`（没有）；IP、掩码、网关、DNS 四样缺一个，就有一类 ping 不通。**
