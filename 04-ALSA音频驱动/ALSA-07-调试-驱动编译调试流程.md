# Linux 音频驱动编译调试流程

## 一、先说结论

音频驱动不出声，99% 能归到三层，**按顺序排，不要跳**：

```text
第一层：设备树生效了吗？   → 节点在不在、compatible 对不对、镜像是不是新的
第二层：card / pcm 建了吗？ → /proc/asound/cards、aplay -l、dmesg
第三层：pcm 能跑吗？        → hw_params 能不能设、status 是不是 RUNNING、有没有声音
```

**顺序不能反**：card 都没建起来，去改 Codec 寄存器是白费；`status` 都 RUNNING 了还没声音，就不要再怀疑 ALSA 代码，去查时钟、pinmux、Codec 上电。

## 二、第一层：设备树与镜像

```bash
# 设备树里到底有没有这个 sound 节点（运行时视图）
ls /proc/device-tree/sound/
cat /proc/device-tree/sound/compatible
cat /proc/device-tree/sound/simple-audio-card,name
cat /proc/device-tree/model

# 板子上跑的镜像是不是你刚编的那个
md5sum /run/media/mmcblk1p1/zImage
ls -l /run/media/mmcblk1p1/          # 看时间戳，确认真的换了文件
```

**为什么要 `strings` 查 zImage**：`scp` 成功不代表内核真的换了——可能拷到了错误分区、可能启动的是另一份镜像。直接在自己编的镜像里搜一句只有你代码里才有的字符串，是确认"镜像真的生效"最硬的证据：

```bash
strings arch/arm/boot/zImage | grep "my dummy codec probe"
grep -a "my dummy codec probe" arch/arm/boot/zImage
```

`strings` 对 zImage 有效，是因为压缩后字符串仍可能被保留；若被压缩掉，改用 `grep -a` 直接扫二进制。两者都没有，说明镜像没换或字符串被优化掉。

## 三、第二层：声卡与 PCM 是否注册

```bash
cat /proc/asound/cards        # 有几张卡
aplay -l                      # 每张卡下有哪些 pcm 设备
cat /proc/asound/pcm          # 所有 pcm 的名字与方向
```

dmesg 按"注册顺序"过滤，一条条往后看：

```bash
dmesg | grep -i sound
dmesg | grep -i asoc
dmesg | grep "my-codec"
dmesg | grep "asoc-simple-card"
```

期望看到的顺序：

```text
asoc-simple-card sound: my-codec <-> sai2 mapping ok
asoc-simple-card sound: ASoC: CPU DAI sai2 registered
my-codec: probe success
```

**没有 `mapping ok` 这一行，就是 dai_link 没绑上**——名字拼错、Codec 没 probe、`#sound-dai-cells` 缺失，都卡在这里。

## 四、第三层：PCM 能不能跑

```bash
# 硬件到底支持什么参数（最有用的一条）
aplay --dump-hw-params -D hw:0,0 test.wav
arecord --dump-hw-params -D hw:0,0

# 打开后的状态
cat /proc/asound/card0/pcm0p/sub0/status
cat /proc/asound/card0/pcm0p/sub0/hw_params
```

`status` 的四种值决定下一步：

| status | 含义 | 下一步 |
|---|---|---|
| `closed` | 没人打开 | 检查 aplay 是不是在跑、`-D` 对不对 |
| `SETUP` | 参数设好了但没启动 | 数据没喂进去，或 trigger 没发 |
| `RUNNING` | DMA 在跑 | 没声音 → 查时钟/pinmux/Codec 上电 |
| `XRUN` | 缓冲越界 | 应用喂数据太慢，或 period 太小 |

## 五、播放与录音自测

```bash
# 播放 WAV（让 alsa-lib 自动协商参数）
aplay MIX1.wav
aplay -D hw:0,0 MIX1.wav

# 播放裸 PCM：必须自己给全参数
aplay -D hw:0,0 -r 8000 -f S16_LE -c 2 -t raw test.pcm

# 录音 5 秒
arecord -D hw:0,0 -r 8000 -f S16_LE -c 2 -d 5 test.wav
```

参数逐项：

| 参数 | 含义 | 示例 |
|---|---|---|
| `-D hw:0,0` | card0 device0 | `hw:0,0` |
| `-r 8000` | 采样率 | `8000` |
| `-f S16_LE` | 16bit 小端 | `S16_LE` |
| `-c 2` | 声道数 | `2` |
| `-t raw` | 裸 PCM（WAV 用 `-t wav`） | `raw` |
| `-d 5` | 时长（秒），录音常用 | `5` |

> 用 `hw:` 时参数必须完全在硬件支持范围内，否则直接 `open` 失败（`Invalid argument`）。不确定就先 `plughw:` 或 `--dump-hw-params`。

## 六、内核配置：让 simple-card 编进去

```bash
make menuconfig
# Device Drivers
#   -> Sound card support
#      -> Advanced Linux Sound Architecture
#         -> ALSA for SoC audio support
#            -> ASoC Simple sound card support     ← 必须选上（Y 或 M）
```

只有 `ALSA for SoC audio support` 打开而 `Simple sound card` 没打开，设备树写了 `simple-audio-card` 也没人认——`compatible` 匹配不到任何驱动，声卡根本不会出现。

## 七、单独编译某个目录

改完 Codec 驱动或 simple-card，不必要全量编内核，可以只重编那个目录再打包：

```bash
export CROSS_COMPILE=/usr/local/arm/gcc-linaro-4.9.4-2017.01-x86_64_arm-linux-gnueabihf/bin/arm-linux-gnueabihf-
export ARCH=arm

# 编 simple-card
cd workspace_imx6ull/kernel/sound/soc/generic/
make -C ../../../ -j16

# 编 codec 驱动
cd workspace_imx6ull/kernel/sound/soc/codecs/
make -C ../../../ -j16

# 产物在
ls ../../../arch/arm/boot/zImage
```

`make -C ../../../` 的意思：回到内核根目录执行顶层 Makefile，靠 `M=` 机制其实不需要，但顶层会处理依赖与链接——比在子目录裸 `make` 稳。

## 八、更新镜像并校验

```bash
# 1. 拷进板子的启动分区
scp arch/arm/boot/zImage root@192.168.55.71:/run/media/mmcblk1p1/

# 2. 两端对比 MD5（Ubuntu 端一条命令搞定）
md5sum arch/arm/boot/zImage
ssh root@192.168.55.71 md5sum /run/media/mmcblk1p1/zImage

# 3. 重启后确认版本
uname -a
cat /proc/asound/cards
```

**MD5 不一致 = 传输没完成或写到了别的分区**，别急着重启排查驱动。

## 九、常见报错对照

| 现象 / 报错 | 原因 | 修法 |
|---|---|---|
| `aplay: device_list: ... No such file` | 没有 `/dev/snd` | 内核没编 ALSA core，或没挂 devtmpfs |
| `audio open error: No such device` | card 在但 pcm 没建 | 查 dai_link 名字匹配、`num_links` |
| `Invalid argument`（open 就失败） | `hw:` 参数超范围 | 用 `plughw:` 或按 dump 出来的范围改 |
| `status` 一直 `SETUP` | 没 trigger START | 数据没写够 `start_threshold` |
| `RUNNING` 但无声 | 时钟 / pinmux / Codec 上电 | 示波器量 BCLK/LRCLK；查 `dapm` 状态 |
| `-EPIPE` | underrun | 加大 period/buffer，或提高喂数据优先级 |
| `snd_soc_register_card failed (-517)` | 依赖未就绪 | 正常 defer；持续失败查名字 |
| 编译报 `undefined reference to snd_soc_...` | 依赖的模块没选 | 打开对应 Kconfig（如 `SND_SOC_IMX_SAI`） |

## 十、一句话总结

**先证镜像与设备树（strings/MD5），再证 card 与 pcm（cards + dmesg 的 mapping ok），最后证 PCM 能跑（hw_params + status）；status=RUNNING 还无声，问题就已经不在 ALSA 里了。**
