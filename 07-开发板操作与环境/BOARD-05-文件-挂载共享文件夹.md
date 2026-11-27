# Linux 开发板挂载共享文件夹

## 一、先说结论

板子访问宿主机文件，两条路：

| 方式 | 谁做服务端 | 板子上的命令 | 适合 |
|---|---|---|---|
| **NFS** | Linux（Ubuntu） | `mount -t nfs 服务器IP:/共享路径 /mnt/nfs` | Linux 宿主为主，最常见 |
| **CIFS/SMB** | Windows 或 Samba | `mount -t cifs //服务器IP/共享名 /mnt/smb -o username=...` | Windows 宿主 |

两条路都要求：**板子内核里编了对应文件系统**（NFS 要 `CONFIG_NFS_FS`，CIFS 要 `CONFIG_CIFS`），否则 `mount` 直接报 `unknown filesystem type`。

## 二、NFS：服务端（Ubuntu）

```bash
# 1. 装服务
sudo apt-get install nfs-kernel-server

# 2. 建共享目录并放权
mkdir -p /home/zhangxin/share
chmod 777 /home/zhangxin/share

# 3. 写导出规则
sudo vi /etc/exports
# 追加一行：
# /home/zhangxin/share 192.168.55.0/24(rw,sync,no_subtree_check,no_root_squash)

# 4. 重载并启用
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server
sudo systemctl enable nfs-kernel-server

# 5. 自检（本机先挂一次，能挂上再谈板子）
showmount -e localhost
```

`/etc/exports` 的选项：

| 选项 | 含义 |
|---|---|
| `rw` | 可读写（`ro` 只读） |
| `sync` | 写操作落盘后才返回（安全，慢一点） |
| `no_subtree_check` | 不检查子目录层级（提速，常规建议） |
| `no_root_squash` | 客户端的 root 保留 root 权限（**板子调试常用，生产别开**） |
| `192.168.55.0/24` | 允许的网段（也可写单个 IP） |

## 三、NFS：板子端（客户端）

```bash
mkdir -p /mnt/nfs
mount -t nfs -o nolock,vers=3 192.168.55.72:/home/zhangxin/share /mnt/nfs
```

三个参数都是"嵌入式专用"：

| 参数 | 为什么需要 |
|---|---|
| `-o nolock` | 板子常没起 `rpc.statd`/`rpcbind`，不加会卡在 `mount` 上不动或 `Permission denied` |
| `vers=3` | 老内核（4.1.15）对 NFSv4 支持不全，锁死 v3 最稳 |
| `-t nfs` | 显式指定类型（内核没编 NFS 时错误更明确） |

验证与使用：

```bash
mount | grep nfs          # 挂上了没
ls /mnt/nfs               # 能看到宿主机文件
echo hi > /mnt/nfs/a.txt  # 能写（宿主机上也能看到，这就是"共享"）
umount /mnt/nfs
```

## 四、开机自动挂载（`/etc/fstab`）

```bash
vi /etc/fstab
```

```text
192.168.55.72:/home/zhangxin/share  /mnt/nfs  nfs  nolock,vers=3,soft,retrans=3  0 0
```

两个关键选项：

- `soft`：服务器没响应时超时返回错误，**不会把板子卡死**（默认 `hard` 会一直等）；
- `retrans=3`：重试 3 次就放弃。

> ⚠️ 自动挂 NFS 有个坑：**板子先开机、服务器还没起**时，`mount` 失败会让启动流程变慢甚至卡在 `rc.local`。稳妥做法是在 `rc.local` 里"先 ping 通再挂"，或干脆手动挂。

## 五、CIFS/SMB：挂 Windows 共享

```bash
mkdir -p /mnt/smb
mount -t cifs //192.168.55.72/share /mnt/smb \
      -o username=zhangxin,password=123456,vers=3.0,iocharset=utf8
```

| 选项 | 作用 |
|---|---|
| `username/password` | 认证（密码含逗号等特殊字符要转义） |
| `vers=3.0` | 协议版本，Windows 10/11 建议 3.0，老 NAS 用 1.0/2.0 |
| `iocharset=utf8` | 中文文件名不乱码 |
| `uid=0,gid=0` | 挂载后文件属主（不然板子上可能没权限写） |

Windows 侧要做的：**右键文件夹 → 属性 → 共享 → 高级共享**，勾"共享此文件夹"，并确认"网络和共享中心"里启用了"文件和打印机共享"。

更安全的做法是把账号密码放单独文件：

```bash
echo 'username=zhangxin' > /etc/cifs.cred
echo 'password=123456'   >> /etc/cifs.cred
chmod 600 /etc/cifs.cred
mount -t cifs //192.168.55.72/share /mnt/smb -o credentials=/etc/cifs.cred,vers=3.0
```

## 六、卸载

```bash
umount /mnt/nfs
```

报 `device is busy` 时：

```bash
fuser -vm /mnt/nfs        # 谁在用它（有 fuser 的话）
# 或
cd / && umount /mnt/nfs   # 你自己就在那个目录里，先 cd 出来
```

`umount -l`（lazy）能强制摘掉，但**数据可能还在缓存里**，之后容易看到"文件写了一半"。

## 七、常见报错

| 报错 | 原因 | 修法 |
|---|---|---|
| `unknown filesystem type 'nfs'` | 内核没编 NFS | 重编内核开 `CONFIG_NFS_FS`/`CONFIG_NFS_V3` |
| `mount: RPC failed` / 卡住不动 | rpcbind 不通 / 没加 `nolock` | 加 `-o nolock,vers=3`；确认服务器 nfs 服务在跑 |
| `Permission denied`（NFS 挂上了但写不了） | 服务端目录权限 / `root_squash` | `chmod 777`，或加 `no_root_squash` |
| `mount error(13): Permission denied`（cifs） | 账号密码错 / 共享权限 | 核对账号；Windows 上给"完全控制" |
| 中文文件名乱码 | 没设 `iocharset` | 加 `iocharset=utf8` |
| 挂载点里看不到新文件 | NFS 客户端属性缓存 | `mount -o remount` 或稍等（缓存有超时） |

## 八、一句话总结

**NFS 要在 Ubuntu 上装 `nfs-kernel-server` 并写 `/etc/exports`，板子上 `mount -t nfs -o nolock,vers=3`；Windows 共享用 `-t cifs` 带账号密码与 `vers=3.0`；两边都要求板子内核编了对应文件系统。**
