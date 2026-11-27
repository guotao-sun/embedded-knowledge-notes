# ALSA 学习路线

## 一、先说结论

学 ALSA 最忌一上来读 `snd_pcm_runtime`（几百个字段，读完也不知道它在干什么）。有效的路径是**追一条真实的数据通路**：

> 先让板子能放音 → 再问"aplay 这一下，内核做了什么" → 顺着 `snd_pcm_writei` 一路追到 DMA → 最后才回头看数据结构。

九个阶段，每个阶段只回答一个问题：

| 阶段 | 要回答的问题 | 关键函数 / 文件 |
|---|---|---|
| ① 整体架构 | Card、PCM、DAI、Component 各是什么 | `snd_soc_card`、`snd_pcm`、`snd_soc_dai` |
| ② 一次播放 | aplay 播放一首 WAV，内核发生了什么 | `snd_pcm_open` / `writei` / `trigger` |
| ③ PCM 的诞生 | PCM 设备是怎么创建出来的 | `soc_new_pcm()` |
| ④ 打开设备 | `snd_pcm_open()` 到底打开了什么 | `snd_pcm_open_substream()` |
| ⑤ 写数据 | `snd_pcm_writei()` 如何一路走到 DMA | `snd_pcm_lib_write()` → `copy_from_user` |
| ⑥ 通知机制 | DMA 如何告诉 ALSA"一个 period 完成了" | `snd_pcm_period_elapsed()` |
| ⑦ 三方协作 | CPU DAI、Codec DAI、Machine 怎么配合 | `snd_soc_dai_link` / `snd_soc_dapm` |
| ⑧ 从零写 Codec | 写一个基于 regmap 的 UART Codec 驱动 | `snd_soc_component_driver` + `regmap` |
| ⑨ 移植 | 换到 i.MX6ULL + WM8960 要改什么 | 设备树 + Machine 驱动 |

**这个顺序的好处**：每一步都能在板子上验证（`aplay`、`dmesg`、`/proc/asound`），不会出现"看懂了但不知道对不对"。

## 二、阶段 ①–②：先建立坐标系

- **Card**：一张声卡（一块板子的整套音频系统），对应 `/proc/asound/card0`
- **PCM**：一路数据流（播放或录音），对应 `/dev/snd/pcmC0D0p`
- **DAI**：数字音频接口（I2S/SAI 这一路串行总线）
- **Component**：可复用的音频部件（Codec、CPU DAI 都注册成 component）

阶段 ② 的目标很具体：**能用自己的话讲出**"aplay 打开 `/dev/snd/pcmC0D0p` → 设参数 → 把数据拷进环形缓冲 → 触发 DMA → DMA 播完一个 period 发中断 → 应用继续写"这条链。

## 三、阶段 ③–⑥：追数据通路

这一段是 ALSA 的核心，也是唯一需要读源码的部分。建议顺序：

```text
soc_new_pcm()                  ← PCM 设备在 ASoC 里怎么建（soc-pcm.c）
    ↓
snd_pcm_open()                 ← 打开时创建 runtime、选 hw_params
    ↓
snd_pcm_hw_params()            ← 分配 DMA buffer、确定 period/buffer
    ↓
snd_pcm_writei()               ← 用户数据 → 内核环形缓冲（appl_ptr）
    ↓
snd_pcm_trigger(START)         ← 启动 DMA
    ↓
snd_pcm_period_elapsed()       ← DMA 中断里被调用，推进 hw_ptr
```

读源码时只盯三个东西：**谁分配缓冲、谁推进指针、谁发中断**。其他字段一律先跳过。

## 四、阶段 ⑦–⑨：从看懂到能写

- **⑦ 三方协作**：`dai_link` 把 CPU DAI 和 Codec DAI 绑在一起，Machine 驱动只描述"怎么接"；DAPM 负责"信号从哪走到哪、什么时候上电"
- **⑧ 写 Codec**：先用 `simple-audio-card` + 一个 dummy codec 把链路跑通，再替换成真 Codec；寄存器访问统一走 regmap（见 [regmap 抽象框架](./../03-驱动开发基础/DRIVER-20-寄存器-regmap抽象框架.md)）
- **⑨ 移植**：换 SoC 主要改设备树（SAI 节点、pinmux、时钟），Machine 驱动往往可以直接复用厂商现成的

## 五、需要的前置知识

| 知识 | 为什么需要 |
|---|---|
| I2S 时序 | 分不清 BCLK / LRCLK / MCLK，就看不懂"为什么没声音" |
| DMA 与环形缓冲 | period / buffer / hw_ptr 全建立在这上面 |
| regmap | Codec 驱动 90% 的代码是读写寄存器 |
| 设备树 | `simple-audio-card`、`sound-dai`、`audio-routing` 都在 dts 里 |
| DAPM | "有寄存器配置但没声音"通常是路径没打开 |

I2S 最小知识：**MCLK 是 Codec 的主时钟（通常 256×fs），BCLK 是位时钟，LRCLK 是帧时钟（等于采样率）；谁是 master 谁产生这三根时钟**。

## 六、怎么验证每一阶段

```bash
cat /proc/asound/cards                 # 有没有 card
aplay -l                               # 有哪些 pcm 设备
aplay --dump-hw-params -D hw:0,0 x.wav # 硬件支持什么参数
cat /proc/asound/card0/pcm0p/sub0/status  # 当前状态（RUNNING/SETUP）
dmesg | grep -i asoc                   # ASoC 注册日志
```

**每改一次设备树或驱动，先看这五条命令**，比盲改代码快得多。

## 七、参考资料

- [Linux 音频驱动之 ASoC 框架](https://notes.z-dd.online/2021/03/07/Linux%E9%9F%B3%E9%A2%91%E9%A9%B1%E5%8A%A8%E4%B9%8BAsoc%E6%A1%86%E6%9E%B6/index.html)
- [博客园 - ALSA 相关](https://www.cnblogs.com/blogs-of-lxl/p/6538769.html)

## 八、一句话总结

**别从数据结构开始，从"一次 aplay"开始：先让板子响，再顺着 writei → DMA → period 中断往回追，数据结构是在追的过程中自然认识的。**
