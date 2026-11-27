# Linux 开发板 SCP 传输文件

## 一、先说结论

`scp` 就是"走 SSH 通道的 cp"，语法是 **`scp 源 目标`**，哪一头写 `user@ip:路径`，哪一头就是远程：

```bash
scp 本地文件  root@192.168.55.71:/目标路径      # 推
scp root@192.168.55.71:/源文件  本地路径        # 拉
```

三个最常用的变体：

```bash
scp -r 目录 root@ip:/目标/       # 整个目录（递归）
scp -P 2222 文件 root@ip:/目标/  # 非默认端口（大写 P）
scp -p 文件 root@ip:/目标/       # 保留时间戳与权限位（小写 p）
```

## 二、一次完整的推送

```bash
# 宿主机：编好的内核
scp arch/arm/boot/zImage root@192.168.55.71:/run/media/mmcblk1p1/

# 板子：确认真的到了
ssh root@192.168.55.71 'ls -l /run/media/mmcblk1p1/zImage; sync'

# 两端比对
md5sum arch/arm/boot/zImage
ssh root@192.168.55.71 md5sum /run/media/mmcblk1p1/zImage
```

**`scp` 成功不代表文件完整**（网线松、板子存储满都可能截断），所以大文件一律 `md5sum` 对比。

## 三、拉回来

```bash
scp root@192.168.55.71:/home/root/log.txt ./          # 单个文件
scp -r root@192.168.55.71:/home/root/project ./       # 整个目录
```

`./` 结尾是当前目录；写成 `scp .../log.txt` 不带目标会报 `missing destination file operand`。

## 四、免密：不想每次都输密码

```bash
# 1. 生成密钥（一路回车，密码可留空）
ssh-keygen -t rsa -b 2048

# 2. 把公钥装到板子（自动追加到 ~/.ssh/authorized_keys）
ssh-copy-id root@192.168.55.71

# 3. 之后直接 scp，不再问密码
scp zImage root@192.168.55.71:/tmp/
```

板子上没有 `ssh-copy-id` 时手工做：

```bash
cat ~/.ssh/id_rsa.pub | ssh root@192.168.55.71 \
   'mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys'
```

免密对"频繁推 `zImage`、推 `.ko`"的调试节奏提升极大。

## 五、比 scp 更好用的 rsync

`scp` 每次都全量传；`rsync` 只传差异、支持断点续传，**推整个 SDK 或源码目录时差距巨大**：

```bash
rsync -avz --progress 本地目录/ root@192.168.55.71:/目标目录/
```

| 参数 | 作用 |
|---|---|
| `-a` | 归档模式（保留权限、时间、软链接） |
| `-v` | 显示过程 |
| `-z` | 传输压缩（网速慢、CPU 有余时有用） |
| `--progress` | 显示进度 |
| `--delete` | 目标端删掉源端已没有的文件（**危险，先不加**） |

注意源路径结尾的 `/`：`dir/` 表示"目录里的内容"，`dir` 表示"目录本身"。

## 六、板子上的 SCP 也能反向用

```bash
# 板子上把日志推回宿主机（需要宿主机开了 sshd）
scp /var/log/messages 192.168.55.72:/home/zhangxin/logs/
```

嵌入式 rootfs 的 `scp` 可能是 dropbear 提供的，参数支持更少（不一定有 `-p`），报错时先 `scp -h` 看它支持什么。

## 七、拷完常忘的两件事

### 1. 可执行位

`scp` 默认**不保留**权限位，推过去的程序没有 `+x`，板子上跑就是 `Permission denied`：

```bash
ssh root@192.168.55.71 'chmod +x /tmp/myapp'
# 或者推的时候加 -p（要求两边 scp 都支持）
```

### 2. 分区空间

推到 `/run/media/mmcblk1p1`（boot 分区）时，分区往往只有几十 MB。推大文件前先看：

```bash
ssh root@192.168.55.71 'df -h /run/media/mmcblk1p1'
```

## 八、常见报错

| 报错 | 原因 | 修法 |
|---|---|---|
| `Permission denied (publickey,password)` | 密码错 / 板子禁了密码登录 | 用免密，或改 `/etc/ssh/sshd_config` |
| `No such file or directory` | 目标路径不存在（**scp 不会自动建目录**） | 先 `ssh ... mkdir -p` |
| `lost connection` / 传到一半断 | 网线/供电/存储满 | 检查 `df -h`，改用 `rsync` 续传 |
| `Host key verification failed` | 板子重刷过，指纹变了 | `ssh-keygen -R 192.168.55.71` |
| `scp: not found`（板子侧） | rootfs 没装 scp | 用 `tftp`，或从宿主机 `ssh ... 'cat > 文件'` |
| `Connection refused` | sshd 没起来 / 端口不对 | `ps | grep sshd`、换 `-P` |

## 九、一句话总结

**`scp 源 目标`，带 `user@ip:` 的那一头就是远程；目录加 `-r`、端口加 `-P`、保权限加 `-p`；大文件和频繁同步用 `rsync -avz`，传完记得 `chmod +x` 和核对 MD5。**
