# Linux 对内存卡做镜像

## 一、先说结论

"给 SD 卡做镜像"就是**把整块块设备按字节抄出来**，核心只有两条：

```bash
# 备份：设备 → 文件
sudo dd if=/dev/sdb of=sdcard.img bs=4M status=progress conv=fsync

# 恢复：文件 → 设备
sudo dd if=sdcard.img of=/dev/sdb bs=4M status=progress conv=fsync
```

**做这件事之前，先记住一个可能毁掉你笔记本数据的点**：`of=` 写的是**块设备名**，不是分区名。写成 `of=/dev/sda` 就把你的系统盘整个覆盖了。

## 二、第一步：确认哪个才是你的卡

```bash
lsblk
# sda      931.5G  disk        ← 你的硬盘（千万别碰）
# └─sda1   931.5G  part
# sdb       29.7G  disk        ← SD 卡（29.7G 对得上卡容量）
# ├─sdb1    29.7G  part
# └─sdb2
```

三个确认：

1. **容量对得上**（卡是 32G，就找 29.7G 那个）；
2. **可移动标志**（`lsblk` 的 `RM` 列为 1 表示可插拔，更保险）；
3. **插拔前后 diff**：

```bash
lsblk > /tmp/before.txt     # 插卡前
lsblk > /tmp/after.txt      # 插卡后
diff /tmp/before.txt /tmp/after.txt    # 多出来的那一行就是它
```

`diff` 这个办法最稳，尤其在有多块盘的时候。

## 三、第二步：卸载所有分区

```bash
umount /dev/sdb1
umount /dev/sdb2
```

**不卸载直接 `dd` 会得到"边写边被内核改"的不一致镜像**，恢复后文件系统报错。

漏了哪个分区，让系统告诉你：

```bash
lsblk /dev/sdb          # MOUNTPOINT 列有值的就是还挂着的
```

## 四、第三步：备份

### 不压缩（快，占空间大）

```bash
sudo dd if=/dev/sdb of=sdcard_backup.img bs=4M status=progress conv=fsync
```

| 参数 | 作用 |
|---|---|
| `if=` | 输入（源设备） |
| `of=` | 输出（镜像文件） |
| `bs=4M` | 块大小，比默认 512 字节快很多 |
| `status=progress` | 显示进度（coreutils ≥ 8.24；busybox 不一定支持） |
| `conv=fsync` | 结束时把缓存刷盘（不写会在断电时丢尾部数据） |

### 压缩（体积小很多，空扇区会压成几乎 0）

```bash
sudo dd if=/dev/sdb bs=4M | gzip -1 > sdcard.img.gz
```

`gzip -1` 比默认 `-6` 快，镜像这种内容压缩率差别不大。

### 压缩 + 进度

```bash
sudo apt-get install pv
sudo dd if=/dev/sdb bs=4M | pv -s 32G | gzip -1 > sdcard.img.gz
```

`pv -s` 只是"预计总大小"，用来算百分比；写不准也无所谓，进度条会提前满。

## 五、第四步：校验

```bash
# 未压缩：直接比对 md5
md5sum sdcard_backup.img
# 与原始设备比对（要再读一遍卡，慢但可靠）
sudo dd if=/dev/sdb bs=4M status=none | md5sum
```

**压缩过的镜像不能对 `.gz` 取 md5 来校验"卡是否一致"**——压缩流里的时间戳/元数据会让 md5 每次不同。正确做法：

```bash
# 校验压缩包本身完整（能解压完不报错）
gzip -t sdcard.img.gz && echo "gz ok"

# 要验证内容一致，解压后比对（比较慢）
gunzip -c sdcard.img.gz | md5sum
```

## 六、第五步：恢复

```bash
# 压缩包
gunzip -c sdcard.img.gz | sudo dd of=/dev/sdb bs=4M status=progress conv=fsync

# 未压缩
sudo dd if=sdcard_backup.img of=/dev/sdb bs=4M status=progress conv=fsync

sync
```

恢复完**别急着拔**：`sync` 后再 `lsblk` 确认，或直接 `eject /dev/sdb`。

## 七、两个实用技巧

### 1. 把 32G 卡备份成"只有实际数据大小"的镜像

`dd` 整卡备份会把空洞也拷进去。已知根分区只用了 2G 时，可以只读前 N MB：

```bash
# 先看最后分区的结束位置（单位：扇区）
sudo fdisk -l /dev/sdb
# 假设结束在 0x00F00000 扇区，加 10% 余量后：
sudo dd if=/dev/sdb of=part.img bs=1M count=$(( (0x00F00000 * 512 / 1048576) + 100 ))
```

或先备份成完整 img，再 `truncate` 掉尾部空白（有风险，只适合 FAT/ext 这类能自洽的文件系统）。

### 2. 恢复到更大的卡后扩容分区

镜像只有 8G 分区，恢复到 32G 卡上，剩下 24G 用不到：

```bash
# 扩分区（growpart 只改分区表，不动文件）
sudo growpart /dev/sdb 2

# 再扩文件系统
sudo resize2fs /dev/sdb2          # ext4
sudo resize.f2fs /dev/sdb2        # f2fs
```

`growpart` 来自 `cloud-utils-growpart` 包；没有就手工 `fdisk` 删分区重建（起始扇区保持不变）。

## 八、风险清单

| 风险 | 后果 | 防法 |
|---|---|---|
| `of=` 写错成系统盘 | 笔记本系统被覆盖 | 插拔 diff 确认、看容量、看 `RM` 列 |
| 没卸载就 dd | 镜像不一致，恢复后 fs 报错 | `lsblk` 确认 `MOUNTPOINT` 为空 |
| 恢复时写错卡 | 覆盖别的卡 | 同上 |
| 不 `sync` 就拔 | 尾部数据丢失 | `conv=fsync` + `sync` |
| 用 `dd` 备份正在使用的根分区 | 得到的镜像不可挂 | 从另一张卡/另一台机器上备份 |

## 九、一句话总结

**`dd if=设备 of=文件` 是备份、反过来是恢复；动手前用插拔 diff 确认设备名、`lsblk` 确认无挂载、`conv=fsync` 保证落盘——`dd` 没有"撤销"，只有"重来"。**
