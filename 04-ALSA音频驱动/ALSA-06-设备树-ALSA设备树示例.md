# ALSA 的设备树示例

## 一、先说结论

音频设备树有两条路，选错了会白折腾一天：

| 写法 | 驱动 | 适合 |
|---|---|---|
| **`simple-audio-card`** | `sound/soc/generic/simple-card.c` | 通用链路：一个 CPU DAI + 一个 Codec DAI，无需写代码 |
| **厂商专用 Machine** | 如 `fsl,imx-audio-wm8960` | 有耳机检测、多 Codec、ASRC、复杂板级逻辑 |

**建议顺序**：先用 `simple-audio-card` 把链路和时钟跑通（能出声），再决定要不要换专用驱动。一上来就上厂商驱动，出问题时很难判断是设备树写错还是驱动不匹配。

## 二、simple-audio-card 示例

```dts
my_codec: my-codec {
    compatible = "my,dummy-codec";
    #sound-dai-cells = <0>;        /* Codec 只有一个 DAI，引用时不需要参数 */
};

sound {
    compatible = "simple-audio-card";
    simple-audio-card,name = "imx6ull-dummy-test";
    simple-audio-card,format = "i2s";

    /* CPU 作为 master：由 SAI 产生 BCLK/LRCLK */
    simple-audio-card,bitclock-master = <&cpu_dai>;
    simple-audio-card,frame-master = <&cpu_dai>;

    cpu_dai: simple-audio-card,cpu {
        sound-dai = <&sai2>;
        dai-tdm-slot-num = <2>;
        dai-tdm-slot-width = <16>;
        system-clock-frequency = <12288000>;   /* 送给 Codec 的 MCLK */
    };

    codec_dai: simple-audio-card,codec {
        sound-dai = <&my_codec>;
        dai-tdm-slot-num = <2>;
        dai-tdm-slot-width = <16>;
    };
};
```

这段设备树等价于在代码里写：

```c
dai_link->cpu_dai_name   = "sai2";          /* 由 sound-dai 自动解析 */
dai_link->codec_dai_name = "my-codec";
dai_link->dai_fmt        = SND_SOC_DAIFMT_I2S | SND_SOC_DAIFMT_CBS_CFS;
```

也就是说 **simple-card 就是一个"设备树版的 Machine 驱动"**，不用你写 C。

## 三、SAI 控制器配置

```dts
&sai2 {
    pinctrl-names = "default";
    pinctrl-0 = <&pinctrl_sai2>;
    #sound-dai-cells = <0>;

    assigned-clocks = <&clks IMX6UL_CLK_SAI2_SEL>,
                      <&clks IMX6UL_CLK_SAI2>;
    assigned-clock-parents = <&clks IMX6UL_CLK_PLL4_AUDIO_DIV>;
    /* assigned-clock-rates = <0>, <11289600>; */   /* 44.1k 家族 */
    assigned-clock-rates = <0>, <12288000>;         /* 48k 家族 */
    /* assigned-clock-rates = <0>, <4096000>; */    /* 最低档 MCLK */

    status = "okay";
};
```

`assigned-clocks` / `assigned-clock-parents` / `assigned-clock-rates` 是**通用时钟绑定**，不是音频专用：在 probe 时由 clock 框架自动把 SAI 的时钟源和分频配好。

**为什么必须配对写**：`assigned-clocks` 里第一个是 SAI 的时钟选择器（SEL），第二个是 SAI 根时钟。只给 SEL 指定父时钟不设频率，实际出来的 MCLK 可能不是你要的 12.288 MHz，现象就是"能播但音调不对/全是杂音"。

## 四、关键字段

| 字段 | 作用 | 备注 |
|------|------|------|
| `simple-audio-card,name` | 声卡名称，用户空间可见 | 出现在 `/proc/asound/cards` |
| `simple-audio-card,format` | 音频格式（`i2s` / `dsp_a` / `left_j` / `right_j`） | 与 Codec 手册的格式对齐 |
| `simple-audio-card,bitclock-master` | 指定位时钟主设备 | 填 **CPU/Codec 子节点的 phandle**，不是 SAI 节点 |
| `simple-audio-card,frame-master` | 指定帧时钟主设备 | 同上；两者通常指向同一个 |
| `simple-audio-card,mclk-fs` | MCLK 与 fs 的倍数 | 例如 `<256>`，由 simple-card 自动算 MCLK |
| `sound-dai` | 引用 CPU DAI 或 Codec DAI | 必须指向带 `#sound-dai-cells` 的节点 |
| `dai-tdm-slot-num` | TDM 时隙数量 | I2S 双声道写 2 |
| `dai-tdm-slot-width` | 时隙宽度（bit） | 一般等于采样位宽，如 16 |
| `system-clock-frequency` | 系统时钟（MCLK）频率 | 单位 Hz，必须能被采样率整除 |

### MCLK 怎么算

```text
MCLK = 256 × fs
48kHz  → 12288000
44.1kHz → 11289600
```

`256` 是最常见的 `mclk-fs` 倍数（WM8960 要求 256/384 等固定倍数）。**如果 48k 和 44.1k 都要支持，MCLK 必须可切换**——固定成 12.288 MHz 时，44.1k 会因为除不尽而音调偏低。

## 五、两种写法怎么选

| 维度 | simple-audio-card | 厂商 Machine 驱动 |
|---|---|---|
| 要不要写 C 代码 | 不用 | 要（但厂商已写好） |
| 耳机/麦克风检测 | 不支持（需自己加） | 支持（`hp-det`、`mic-det`） |
| 多 Codec / ASRC | 不支持 | 支持 |
| 板级小配置（改寄存器） | 无法做 | `dai_link->init` 里做 |
| 调试难度 | 低（通用代码，日志清晰） | 高（要读厂商驱动） |

**判断标准**：板子上只有"一颗 Codec + 一路 I2S + 一对喇叭/耳机"，用 simple-card；一旦涉及检测脚、双 Codec、ASRC、特殊上电时序，就得用厂商驱动。

## 六、常见错误

| 现象 | 原因 | 修法 |
|---|---|---|
| `sound-dai: invalid phandle` | 被引用节点没有 `#sound-dai-cells` | 给 SAI/Codec 节点补 `#sound-dai-cells = <0>;` |
| 声卡没出现，`dmesg` 报 `asoc: no dai link` | `sound` 节点没被 platform 设备化（缺 `compatible` 或不在 `simple-bus` 下） | 检查节点层级与 `compatible` |
| 能 open 但没声音 | master 配反：两方都在等对方出时钟 | 用 `bitclock-master` 明确指定一方 |
| 音调偏低 / 有杂响 | MCLK 与 fs 不匹配 | 核对 `system-clock-frequency` 或 `mclk-fs` |
| 只有一边声道 | `dai-tdm-slot-num` / `dai-tdm-slot-width` 与 Codec 期望不符 | 按 Codec 手册的 TDM/I2S 格式改 |
| `-EPROBE_DEFER` 一直重试 | Codec 节点 `status = "disabled"` 或驱动没编进内核 | 打开 status、确认 config |

## 七、一句话总结

**先用 `simple-audio-card` 把"CPU DAI + Codec DAI + MCLK"三件事配对，能出声再考虑厂商 Machine 驱动；master 用子节点 phandle 指定，MCLK 必须能被 fs 整除。**
