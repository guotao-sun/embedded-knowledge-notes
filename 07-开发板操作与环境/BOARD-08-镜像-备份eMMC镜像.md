# Linux 备份 eMMC 镜像

## 一、先说结论

eMMC 备份和 SD 卡备份**方法一样（都是 `dd`），但约束完全不同**：SD 卡是从 PC 上备份，eMMC 往往是**板子自己在用**。

所以先回答一个问题：**你要备份到哪？**

| 备份目标 | 可行 | 说明 |
|---|---|---|
| 同一块 eMMC 的另一个分区 | ❌ | 边读边写同一设备，镜像必然不一致，且空间通常不够 |
| 插上的 SD 卡 / U 盘 | ✅ | 最常用 |
| NFS 共享目录 | ✅ | 不占板子空间，但速度受网络限制 |
| PC（从 maskrom/loader 模式读） | ✅ | 板子起不来时的唯一办法 |

## 二、`dd` 到底叫什么

`dd` **不是缩写**。它来自 IBM 大型机 JCL 里的 "data definition" 语句，Unix 沿用了这个名字。运维圈戏称它为 **"data destroyer"**——因为参数写错就是不可逆的破坏。

```text
if=  input file    源
of=  output file   目标
bs=  block size    块大小
count= 复制多少块
conv=fsync         结束时刷盘
status=progress    进度
```

`if`/`of` 都可以是设备（`/dev/mmcblk1`）或普通文件（`mmc_image.img`）。

## 三、备份到外部存储（推荐）

```bash
# 0. 插一张够大的 SD 卡/U 盘，确认设备名
lsblk
# mmcblk0  29.7G  ← 板子自己的 eMMC（要备份的）
# mmcblk1  59.5G  ← 你插的 SD 卡（备份目的地）

# 1. 挂载目的地
mkdir -p /mnt/backup
mount -t vfat /dev/mmcblk1p1 /mnt/backup

# 2. 先卸载 eMMC 上要被备份的分区（能卸的都卸）
umount /run/media/mmcblk0p1 2>/dev/null
umount /run/media/mmcblk0p2 2>/dev/null

# 3. 备份（注意 of 是外部存储上的文件，不是设备）
dd if=/dev/mmcblk0 bs=4M conv=fsync | gzip -1 > /mnt/backup/emmc.img.gz

# 4. 落盘并确认大小
sync
ls -lh /mnt/backup/emmc.img.gz
```

**rootfs 分区卸不掉是正常的**（它正被使用）。这意味着：

> 备份出来的是"运行中系统的一致性快照"——文件系统元数据可能不一致。

要做到**完全干净**的备份，只有两条路：

1. 从 SD 卡启动另一个系统，再去 `dd` eMMC（eMMC 此时完全空闲）；
2. 进 maskrom/loader 模式，用 PC 侧工具读（见第六节）。

日常"复制一块板子做样机"用运行中备份足够，但恢复后第一次启动最好跑一次 `fsck`。

## 四、只备份 boot 类分区（最常用的小备份）

多数时候你只需要备份"启动相关的几个小分区"，几十 MB，秒级完成：

```bash
# 查看分区布局
cat /proc/partitions
#  mmcblk0        ...
#  mmcblk0p1      boot
#  mmcblk0p2      rootfs
```

```bash
dd if=/dev/mmcblk0p1 of=/mnt/backup/boot.img bs=1M conv=fsync
```

这类备份的意义：**刷坏了 boot 还能从备份恢复**，不用重烧整机。

## 五、恢复

前提：**目标分区不能被挂载**。恢复 rootfs 时，板子必须从别的介质启动（SD 卡）或用 maskrom。

```bash
# 压缩包 → 设备
gunzip -c /mnt/backup/emmc.img.gz | dd of=/dev/mmcblk0 bs=4M conv=fsync

# 未压缩
dd if=/mnt/backup/emmc.img of=/dev/mmcblk0 bs=4M conv=fsync

sync
reboot
```

⚠️ `of=/dev/mmcblk0` 是**整盘**，会把分区表一起覆盖——这正是"整机还原"想要的；如果只想还原某个分区，写 `of=/dev/mmcblk0p2`，但注意**镜像与分区大小必须匹配**（把整盘镜像写进单个分区会溢出）。

## 六、板子起不来时：从 PC 读

RK 平台：

```bash
# 板子进 maskrom（按住 recovery 键上电）
upgrade_tool rl 0 0x0 0x40000000 backup.bin    # 读一段
upgrade_tool pl                                 # 或整片读取，视工具版本
```

i.MX 平台用 `uuu`/`mfgtool` 的读命令，或用 `imx_usb` 系列工具。

这条路的优点是**绕过操作系统**，读到的是真正的物理内容；缺点是要按键进模式、速度慢。

## 七、比 dd 更聪明的两个选择

### 1. `partclone`（只备份"已用的块"）

`dd` 把 8G 分区里 6G 空白也读一遍；`partclone` 只读已分配块：

```bash
partclone.ext4 -c -s /dev/mmcblk0p2 -o rootfs.pcl.gz
partclone.ext4 -r -s rootfs.pcl.gz -o /dev/mmcblk0p2
```

要求文件系统类型已知（ext4/f2fs/ntfs 各有对应版本），且目标分区**不小于**源。

### 2. 文件级备份（`tar` / `rsync`）

只想保住"配置和程序"，不要块设备：

```bash
tar -czf rootfs_files.tar.gz -C / --exclude=proc --exclude=sys --exclude=dev \
    --exclude=run --exclude=tmp .
```

优点：体积小、能跨不同分区大小恢复；缺点：**不保留分区表、引导扇区、uboot 环境**，不能用来救砖。

## 八、常见问题

| 现象 | 原因 | 修法 |
|---|---|---|
| `dd: /dev/mmcblk0: Permission denied` | 没 root | `sudo` 或本来就是 root 时检查只读 |
| `No space left on device` | 备份文件写到了空间不足的分区 | 换目标分区，或先 `gzip` |
| 镜像比 eMMC 还大 | `bs`/`count` 用错、或读到了整盘含空洞 | 用 `lsblk` 核对容量；压缩后看实际大小 |
| 恢复后卡在启动 | 镜像不完整 / 分区表不对 | 校验 `gzip -t`；用整盘镜像恢复 |
| `dd` 极慢（几 MB/s） | SD 卡/U 盘本身慢，或 `bs` 太小 | `bs=4M`~`8M`，换 U3 卡 |

## 九、一句话总结

**`dd if=/dev/mmcblk0 of=外部存储/emmc.img.gz` 备份、反过来恢复；备份目标绝不能是同一块 eMMC，恢复时目标分区必须卸载，整机还原写整盘、分区还原写分区。**
