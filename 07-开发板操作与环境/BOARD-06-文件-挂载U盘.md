# 挂载 U 盘

## 一、先说结论

U 盘在 Linux 上就是**一个块设备**，插上后内核会自动认出来，你要做三步：

```text
认设备（lsblk / dmesg）→ 建挂载点 → mount 分区 → 用完 umount + sync
```

两个高频坑：

- 挂的是**分区**（`/dev/sda1`）而不是整盘（`/dev/sda`）——盘上可能有分区表，直接挂整盘会失败；
- **拔之前不 `sync`/`umount`**，FAT 的写缓存没落盘，下次插上就是"文件损坏/变 0 字节"。

## 二、认设备

```bash
lsblk
# NAME   MAJ:MIN RM  SIZE RO TYPE MOUNTPOINT
# sda      8:0    1  14.9G  0 disk
# └─sda1   8:1    1  14.9G  0 part

dmesg | tail -10
# [ 1234.5] sd 0:0:0:0: [sda] 31129600 512-byte logical blocks: (15.9 GB/14.8 GiB)
# [ 1234.6]  sda: sda1
```

`sda` 是盘、`sda1` 是它的第一个分区。多插几个 U 盘就是 `sdb`、`sdc`。

没有 `lsblk` 的板子用：

```bash
cat /proc/partitions
fdisk -l /dev/sda 2>/dev/null | head -20     # 看分区表
```

**插上没反应**（`dmesg` 里一条 `usb` 都没有），是 USB Host 驱动没编或供电不足，先解决这个再谈挂载。

## 三、挂载

```bash
mkdir -p /mnt/usb

# FAT32（绝大多数 U 盘）
mount -t vfat /dev/sda1 /mnt/usb

# 需要中文文件名不乱码、且允许普通用户读写
mount -t vfat -o iocharset=utf8,uid=0,gid=0 /dev/sda1 /mnt/usb

# NTFS（只读最稳；要写需要 ntfs-3g）
mount -t ntfs-3g /dev/sda1 /mnt/usb

# exFAT（大文件>4G 常用，需要 CONFIG_EXFAT_FS）
mount -t exfat /dev/sda1 /mnt/usb

# 只读挂载（怕手滑改坏 U 盘里的资料）
mount -o ro /dev/sda1 /mnt/usb
```

不写 `-t` 也可以，`mount` 会自己探测；但**嵌入式内核常常只编了 vfat**，探测失败时报 `unknown filesystem type`，显式写 `-t vfat` 能让错误更清楚。

## 四、用完之后

```bash
cp somefile.txt /mnt/usb/        # 拷进去
sync                             # 强制落盘（关键！）
umount /mnt/usb                  # 卸载
# 或 umount /dev/sda1
```

顺序不能反：**先 `sync` 再 `umount`**。`umount` 本身也会 flush，但如果 U 盘质量差、写入慢，先 `sync` 更保险。

`umount` 报 `device is busy` 的三种情况：

```bash
cd /                            # ① 你的 shell 在 /mnt/usb 里
fuser -vm /mnt/usb              # ② 有进程打开了里面的文件
umount -l /mnt/usb              # ③ 实在摘不掉，lazy 卸载（数据风险自负）
```

## 五、让它自动挂载（可选）

板子每次插 U 盘都手敲三条命令太麻烦。`mdev`（busybox 的设备管理器）可以按规则自动挂：

```bash
# /etc/mdev.conf
sda[0-9]*   root:root 660  *   /etc/mdev/usb.sh
```

```sh
#!/bin/sh
# /etc/mdev/usb.sh
case "$ACTION" in
  add)  mkdir -p /mnt/usb && mount -t vfat /dev/$MDEV /mnt/usb ;;
  remove) umount /mnt/usb ;;
esac
```

用 udev 的系统则写 `/etc/udev/rules.d/99-usb.rules`。自动挂载的风险是"拔盘前忘了 umount"，调试期建议还是手工挂。

## 六、常见问题

| 现象 | 原因 | 修法 |
|---|---|---|
| `lsblk` 看不到 sda | USB Host 驱动没编 / 供电不足 | 查 `dmesg | grep usb`，换口或换带供电的 HUB |
| `mount: /dev/sda: can't read superblock` | 挂的是整盘不是分区 | 改 `/dev/sda1` |
| `unknown filesystem type 'ntfs'` | 内核没编 ntfs | `-t ntfs-3g`（用户态）或重编内核 |
| `mount: wrong fs type, bad option, bad superblock` | U 盘是 exFAT/其它格式 | `-t exfat` 或 `blkid` 看真实类型 |
| 挂上后文件列表乱码 | 缺 `iocharset` | 加 `iocharset=utf8` |
| 拷进去的文件变 0 字节 | 没 `sync` 就拔 | 重新拷，以后先 sync |

`blkid` 能直接告诉你分区是什么文件系统：

```bash
blkid /dev/sda1
# /dev/sda1: LABEL="USB" UUID="..." TYPE="vfat"
```

## 七、一句话总结

**`lsblk` 认盘 → `mkdir` 建点 → `mount -t vfat /dev/sda1 /mnt/usb` → 用完 `sync` + `umount`；挂分区不挂整盘，拔之前必须同步。**
