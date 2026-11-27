# Linux 开发板常用命令

## 一、先说结论

板子上的命令行**不是 Ubuntu 的命令行**，第一天上手要先认四件事：

| 差异 | 表现 | 应对 |
|---|---|---|
| 是 **busybox** 实现 | 很多参数不支持（`ls -la` 行，`ps aux` 可能不行） | 用"最小参数"，或 `busybox ls --help` 看它认什么 |
| 没有 `systemctl` | 老 rootfs 用 SysV/rc.local | 用 `/etc/init.d/xxx` 或改 `rc.local` |
| 往往没有 `sudo` | 你本来就是 root | 不用提权，注意别误删 |
| 根文件系统可能只读 | `touch` 报 `Read-only file system` | 先 `mount -o remount,rw /` |

完整的命令参考（20 个分类）在 [嵌入式 Linux 常用命令](./../01-基础概念与名词解释/BASE-02-命令-嵌入式Linux常用命令.md)；本篇只讲**在板子上调东西时最常按的那几条**。

## 二、最常用的十条（先记这些就够跑通）

```bash
ls -l                  # 看目录、看权限、看时间戳
cat /proc/cpuinfo      # 板子什么 CPU
dmesg | tail -20       # 刚发生了什么（驱动 probe/报错都在这）
cat /proc/asound/cards # 声卡有没有注册（换成你的子系统）
mount | grep mmcblk    # 分区挂在哪
df -h                  # 还剩多少空间
ifconfig eth0          # 网通了没
ps                     # 谁在跑
insmod xxx.ko          # 装驱动
sync && reboot         # 落盘再重启
```

## 三、文件操作

```bash
ls -la                    # 全部（含隐藏、含属性）
cp -r 源 目标              # 递归复制
mv 源 目标                 # 移动 / 改名（跨分区也是复制+删）
rm -rf 目录                # 强制递归删（**危险，先 ls 一遍**）
mkdir -p a/b/c             # 建多级目录
touch 文件名               # 建空文件 / 更新时间戳
ln -s 目标 链接名           # 软链接（`ln -s /usr/lib/libx.so.1 libx.so` 常用）
```

两个板子上的坑：

```bash
# ① 空间不够时 cp 报 "No space left on device"，先看谁占着
du -sh /* 2>/dev/null | sort -h | tail

# ② 只读根文件系统
mount | grep " / "         # 看 ro 还是 rw
mount -o remount,rw /      # 改成可写（改完记得 remount,ro 或重启）
```

## 四、看文件

```bash
cat 文件            # 全看（小文件）
head -n 20 文件     # 前 20 行
tail -n 20 文件     # 后 20 行
tail -f 文件        # 实时跟踪（busybox 支持）
less 文件           # 分页（没装就用 more）
grep "关键词" 文件   # 过滤
```

板子上经常没有 `less`，`more` 是 busybox 自带的最小替代；`tail -f` 看日志时按 `Ctrl+C` 退出。

## 五、查找

```bash
find / -name "*.ko"           # 按名字找（慢，尽量缩目录）
find /lib/modules -name "*.ko"
grep -rn "关键词" /etc/        # 递归搜内容（-r 递归，-n 行号）
which insmod                  # 命令在哪
```

`find /` 在板子上可能跑几十秒，**先想清楚在哪个目录**再搜。

## 六、网络

```bash
ifconfig                      # 所有网卡与 IP
ifconfig eth0 192.168.1.100 netmask 255.255.255.0   # 临时配 IP（重启失效）
route -n                      # 路由表（看默认网关）
ping -c 4 192.168.1.1         # 通不通（-c 限次数，别无限 ping）
netstat -tlnp                 # 谁在监听（没有 netstat 就看 /proc/net/tcp）
ssh root@192.168.1.100        # 从板子连别的机器
```

没有 `netstat` 时：

```bash
cat /proc/net/tcp             # 十六进制端口，0100 之类的要自己转
```

## 七、进程

```bash
ps                            # busybox 精简版，列出进程
ps -ef                        # 若支持，显示完整命令
top                           # 实时 CPU/内存（按 q 退出）
kill PID                      # 发 SIGTERM（让程序自己收尾）
kill -9 PID                   # 强杀（不给收尾机会，最后手段）
```

`kill -9` 之后 `dmesg` 里如果有 `BUG:`/`Call Trace`，说明那个进程正在内核里跑，强杀会留脏状态——宁可先 `kill` 等它退。

## 八、系统与模块

```bash
uname -a                  # 内核版本 + 架构 + 主机名
cat /etc/os-release       # 发行版信息（RK 的 buildroot 可能没有）
lsmod                     # 已加载模块
insmod /tmp/x.ko          # 加载（按路径）
rmmod x                   # 卸载（按名字，不带 .ko）
modprobe x                # 按名字加载（需先 depmod）
dmesg | tail              # 内核日志
free -h                   # 内存
uptime                    # 跑了多久、负载多少
reboot / poweroff         # 重启 / 关机
sync                      # 把缓存写盘（拔卡/断电前必做）
```

## 九、命令不存在怎么办

板子 rootfs 是裁剪过的，缺命令很常见：

| 缺什么 | 替代 |
|---|---|
| `less` | `more`，或 `cat 文件 | head -50` |
| `netstat` | `cat /proc/net/tcp`、`ss`（若有） |
| `ps aux` | `ps`、`ps -ef` |
| `sudo` | 直接执行（你已是 root） |
| `systemctl` | `/etc/init.d/<服务> restart` |
| `vim` | `vi`（busybox 版，功能少） |
| `wget`/`curl` | `tftp`、`scp` 从宿主机传 |

**判断是不是 busybox**：

```bash
ls -l /bin/ls          # 指向 busybox 就是
busybox --list | head  # 看它编进了哪些命令
```

## 十、一句话总结

**板子上是 busybox 的精简 shell：没有 sudo/systemctl、参数常缺、根文件系统可能只读；先记十条（ls/dmesg/mount/df/ifconfig/ps/insmod/sync/reboot），缺命令就用 `/proc`、`/sys` 里的文件替代。**
