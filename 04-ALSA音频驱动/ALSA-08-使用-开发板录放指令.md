# Linux 开发板录放指令

## 一、先说结论

- **`hw:0,0` 是直通**：参数必须硬件完全支持，不支持就直接失败
- **`plughw:0,0` 带插件层**：自动做格式/采样率/声道转换，怎么填都能出声，代价是多一次内存拷贝
- 排障顺序：**先 `plughw` 确认通路有声 → 再用 `--dump-hw-params` 看真实能力 → 最后用 `hw` 精确复现问题**

> 只用 `plughw` 会永远发现不了"硬件其实不支持 16kHz 双声道"这类问题——它替你转掉了。

## 二、录音

```bash
# 直通方式：16kHz / 16bit / 双声道 / 10 秒
arecord -D hw:0,0 -f S16_LE -r 16000 -c 2 -d 10 record.wav

# 插件方式：单声道也能录（自动混成 1 声道）
arecord -D plughw:0,0 -f S16_LE -r 16000 -c 1 -d 10 record.wav
```

## 三、播放

```bash
aplay record.wav                    # 用默认设备
aplay -D hw:0,0 record.wav          # 指定 card0 device0
aplay -D plughw:0,0 record.wav      # 走插件层
```

裸 PCM 数据（没有 WAV 头）必须手工给全参数，否则 `aplay` 会按默认值猜：

```bash
aplay -D hw:0,0 -r 16000 -f S16_LE -c 2 -t raw record.pcm
```

## 四、参数说明

| 参数 | 含义 | 示例 |
|------|------|------|
| `-D` | 指定声卡设备 | `hw:0,0`（card0 device0）、`plughw:0,0`、`default` |
| `-f` | 采样格式 | `S16_LE`（16bit 小端）、`S24_LE`、`U8` |
| `-r` | 采样率 | `16000`（16kHz） |
| `-c` | 声道数 | `2`（双声道）、`1`（单声道） |
| `-d` | 录制时长（秒） | `10`（录 10 秒） |
| `-t` | 文件类型 | `wav`（默认）、`raw`（裸数据） |
| `--period-size` | 周期大小（帧） | `1024`，越小延迟越低、越易 xrun |
| `--buffer-size` | 缓冲大小（帧） | `16384` |
| `-v` | 显示详细参数 | 排查时打开，能看到实际协商结果 |

例：低延迟录音（周期 256 帧）：

```bash
arecord -D hw:0,0 -f S16_LE -r 48000 -c 1 --period-size=256 --buffer-size=1024 -d 5 low_lat.wav
```

## 五、音量与路由

```bash
alsamixer                # 图形化调音量、开关、路由（F6 选声卡）
alsamixer -c 0           # 直接指定 card0
amixer -c 0 controls     # 列出所有 control 项（脚本里用这个）
amixer -c 0 sset 'Headphone' 80%
amixer -c 0 sset 'Capture' 70% cap
```

保存与恢复（**必须做，否则重启后音量回到默认，很容易误判成"驱动有问题"**）：

```bash
alsactl store            # 保存到 /var/lib/alsa/asound.state
alsactl restore          # 恢复
```

嵌入式 rootfs 若没有 `/var/lib/alsa`，先 `mkdir -p`，否则 `store` 会报错。

## 六、常用组合

```bash
# 录 10 秒立刻回放，验证整条链路
arecord -D plughw:0,0 -f S16_LE -r 16000 -c 2 -d 10 /tmp/t.wav && aplay -D plughw:0,0 /tmp/t.wav

# 长时间压力测试（循环录放，观察 xrun）
for i in $(seq 1 50); do
    arecord -D hw:0,0 -f S16_LE -r 48000 -c 2 -d 2 /tmp/s.wav && aplay -D hw:0,0 /tmp/s.wav
done

# 只测播放不看录音（用系统自带测试音）
speaker-test -D hw:0,0 -c 2 -t sine -l 1
```

`speaker-test` 的好处是不依赖 WAV 文件，能直接判断"左右声道是不是反了、有没有一路不响"。

## 七、常见报错

| 报错 | 原因 | 修法 |
|---|---|---|
| `Device or resource busy` | 设备被别的进程占着 | `fuser -v /dev/snd/*` 找出来杀掉 |
| `Invalid argument` | `hw:` 参数硬件不支持 | 改 `plughw:` 或按 `--dump-hw-params` 调整 |
| `-EPIPE` / `Broken pipe` | underrun/overrun | 增大 period/buffer，或降低采样率 |
| `No such file or directory`（打开 wav） | 路径错 / 文件没生成 | 先 `ls` 确认录音真的写成功了 |
| 录出来是静音 | Capture 通道没开、MIC 没偏置 | `alsamixer` 里打开 Capture、调 MIC Boost |
| 播放有杂音/断续 | 时钟不匹配 或 CPU 负载过高 | 核对 MCLK、提高进程优先级 |
| `alsactl: save_state No such file` | 缺 `/var/lib/alsa` | `mkdir -p /var/lib/alsa` |

## 八、一句话总结

**先 `plughw` 证明能响，再 `hw` 证明参数，最后 `alsactl store` 把音量固化；录放都只是"打开→设参→搬数据"，出错时按这三步定位。**
