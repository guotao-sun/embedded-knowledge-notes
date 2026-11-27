# Machine 驱动（硬件板卡的音频系统配置文件）

## 一、先说结论

Machine 驱动是 ASoC 里的"**接线员**"：

- **不碰任何 Codec / SAI 寄存器**
- 只做三件事：**定义 `dai_link`（谁接谁）、注册 `snd_soc_card`、提供板级小配置（`init` / `ops`）**
- 引脚复用、时钟使能、Codec 上电，分别归 pinctrl、clock、Codec 驱动管

所以同一个 Codec 换到不同板子，**只需要换 Machine 驱动和设备树**，Codec 驱动一行不用改——这就是 ASoC 分层的收益。

## 二、三件套里的位置

```text
        Machine 驱动（本文件）
        └── snd_soc_card
              └── dai_link[]
                    ├── cpu_dai_name    → CPU DAI 驱动（SAI/I2S）
                    ├── codec_dai_name  → Codec 驱动
                    └── platform_name   → DMA 引擎
                                ↓
                       数据：内存 → DMA → CPU DAI → I2S → Codec → 喇叭
```

三条名字都是**字符串匹配**：Machine 说"我要 `wm8960-aif1`"，ASoC core 就去已注册的 component 链表里找，找不到就 `-EPROBE_DEFER`（等 Codec 起来再试）。

## 三、dai_link 逐字段

```c
static struct snd_soc_dai_link smdk_dai[] = {
    {
        .name = "WM8994 AIF1",              /* 链路名称，内部用 */
        .stream_name = "Pri_Dai",           /* 用户空间可见的 PCM 名字 */
        .cpu_dai_name = "samsung-i2s.0",    /* CPU DAI：指定哪一路 I2S/SAI */
        .codec_dai_name = "wm8994-aif1",    /* Codec 里的哪个数字音频接口 */
        .platform_name = "samsung-audio",   /* Platform：DMA 引擎名字 */
        .codec_name = "wm8994-codec",       /* Codec 设备名（老接口，DT 上一般不用） */
        .init = smdk_wm8994_init_paiftx,    /* 板级初始化：加 control、改寄存器 */
        .ops = &smdk_ops,                   /* 板级 ops：startup/shutdown/hw_params 钩子 */
    },
    /* ... 可能还会有其他链路 ... */
};
```

| 字段 | 作用 | 写错会怎样 |
|---|---|---|
| `name` | 链路名 | 重复会警告，不影响功能 |
| `stream_name` | `/proc/asound/pcm` 里显示的名字 | 只是显示名 |
| `cpu_dai_name` | CPU DAI 的 `snd_soc_dai.name` | 匹配失败 → 该 PCM 建不出来 |
| `codec_dai_name` | Codec 里 `snd_soc_dai_driver.name` | 同上 |
| `platform_name` | DMA 平台名 | 匹配失败 → 无法分配 DMA |
| `init` | 链路实例化后调用，**Codec 已 probe** | 适合写板级 control、HP 检测 |
| `ops` | 运行时钩子 | `startup` 里可改时钟/增益 |

**`init` 与 `ops` 的分工**：`init` 只在注册时跑一次；`ops->startup/hw_params` 每次 `open`/设参都会跑。

## 四、定义并注册 snd_soc_card

```c
static struct snd_soc_card smdk = {
    .name = "SMDK-I2S",                     /* 声卡最终名称，出现在 /proc/asound/cards */
    .owner = THIS_MODULE,
    .dai_link = smdk_dai,                   /* 关联上面定义的 DAI Link */
    .num_links = ARRAY_SIZE(smdk_dai),      /* DAI Link 数量，必须写对 */
};

/* 平台驱动 probe 里注册 */
static int smdk_probe(struct platform_device *pdev)
{
    smdk.dev = &pdev->dev;
    return devm_snd_soc_register_card(&pdev->dev, &smdk);
}
```

`num_links` 写小了会漏掉后面的链路（少一路 PCM）；写大了会读到越界内存——**一律用 `ARRAY_SIZE`**。

## 五、codec_dai_name 怎么对上

Codec 驱动里通常定义多个 `snd_soc_dai_driver`，`.name` 就是被匹配的值：

```c
static struct snd_soc_dai_driver wm8994_dai[] = {
    {
        .name = "wm8994-aif1",  /* 这就是 codec_dai_name 要匹配的值 */
        .playback = {
            .stream_name = "AIF1 Playback",
            .channels_min = 1,
            .channels_max = 2,
            .rates = SNDRV_PCM_RATE_8000_48000,
            .formats = SNDRV_PCM_FMTBIT_S16_LE,
        },
        .ops = &wm8994_aif1_ops,
    },
    {
        .name = "wm8994-aif2",
        ...
    },
};
```

排查匹配失败最快的办法：

```bash
cat /sys/kernel/debug/asoc/components      # 已注册的 component 及其 dai 名
cat /sys/kernel/debug/asoc/dais            # 所有 dai 名字
```

这些名字都是运行时可查的，不用猜。

## 六、设备树示例（imx6ul + wm8960）

这是厂商提供的专用 Machine 驱动（`sound/soc/fsl/imx-wm8960.c`）对应的设备树：

```dts
sound {
    compatible = "fsl,imx6ul-evk-wm8960", "fsl,imx-audio-wm8960";
    model = "wm8960-audio";
    cpu-dai = <&sai2>;
    audio-codec = <&codec1 &codec2>;
    asrc-controller = <&asrc>;
    codec-master;                       /* Codec 提供 BCLK/LRCLK */
    gpr = <&gpr4 0x10000 0x10000>;

    /*
     * hp-det = <hp-det-pin hp-det-polarity>;
     * hp-det-pin: JD1 JD2 or JD3
     * hp-det-polarity = 0: hp detect high for headphone
     * hp-det-polarity = 1: hp detect high for speaker
     */
    hp-det = <3 0>;

    /* hp-det-gpios = <&gpio5 4 0>;
       mic-det-gpios = <&gpio5 4 0>; */

    audio-routing =
        "Headphone Jack", "HP_L",
        "Headphone Jack", "HP_R",
        "Ext Spk", "SPK_LP",
        "Ext Spk", "SPK_LN",
        "Ext Spk", "SPK_RP",
        "Ext Spk", "SPK_RN",
        "LINPUT2", "Mic Jack",
        "LINPUT3", "Mic Jack",
        "RINPUT1", "Main MIC",
        "RINPUT2", "Main MIC",
        "Mic Jack", "MICB",
        "Main MIC", "MICB",
        "CPU-Playback", "ASRC-Playback",
        "Playback", "CPU-Playback",
        "ASRC-Capture", "CPU-Capture",
        "CPU-Capture", "Capture";
};
```

几个字段的实际作用：

- **`cpu-dai = <&sai2>`**：相当于 `dai_link.cpu_dai_name`，指向 SAI2 控制器
- **`audio-codec`**：指向 Codec 节点（可多个）
- **`codec-master`**：谁做 I2S 的时钟主设备。有它 = Codec 出 BCLK/LRCLK；没有 = CPU 出
- **`model`**：声卡名，`/proc/asound/cards` 里显示
- **`asrc-controller`**：i.MX 的异步采样率转换器，跨采样率播放时才需要

## 七、audio-routing 规则（最容易搞反的一条）

`audio-routing` 由多个"句子"组成，每个句子是一对字符串：

```dts
"Headphone Jack", "HP_L"
```

- 第一个字符串是 **终点（Sink）**，即信号的接收者
- 第二个字符串是 **起点（Source）**，即信号的发出者

即：**把 Source 连到 Sink**。上面这句就是"把 `HP_L` 接到 `Headphone Jack`"。

三条铁律：

1. **方向别反**：写成 `"HP_L", "Headphone Jack"` 会得到 `-EINVAL` 或路径连不上
2. **名字必须与 Codec 驱动里 `snd_soc_dapm_widget` 的 `name` 完全一致**（大小写、下划线都算），比如 WM8960 的是 `HP_L` / `HP_R` / `SPK_LP`
3. **中间节点也要写全**：ASRC 这类中间件要两边都接（`"Playback", "CPU-Playback"` 和 `"CPU-Playback", "ASRC-Playback"`），断一节整条路就不通

排查路由问题：

```bash
cat /sys/kernel/debug/asoc/card0/dapm             # 所有 widget 状态
cat /sys/kernel/debug/asoc/card0/dapm/paths      # 路径连接
```

## 八、常见错误

| 现象 | 原因 | 定位 |
|---|---|---|
| 卡注册失败 `-517`（EPROBE_DEFER） | Codec/CPU DAI 还没注册 | 正常，等重试；若一直重试失败，查名字拼写 |
| 卡有、PCM 没有 | `dai_link` 某个 name 匹配失败 | `dmesg \| grep -i asoc` 会打印失败的链路名 |
| 播放无声但状态 RUNNING | `audio-routing` 断了或名字错 | 看 `dapm` 目录，widget 是否 `On` |
| `init` 里调 Codec 寄存器无效 | `init` 早于 Codec probe | 确认用的是 `dai_link->init` 而不是 card probe 里的代码 |
| 每次 open 都有"pop"声 | 上下电顺序问题 | 用 DAPM 的 `seq` 控制，别手工开关 |

## 九、一句话总结

**Machine 驱动 = 一张接线表：`dai_link` 说"这条 CPU DAI 接这条 Codec DAI、用这个 DMA"，`audio-routing` 说"信号从哪个口走到哪个口"；寄存器一律不碰，换板子只换这张表。**
