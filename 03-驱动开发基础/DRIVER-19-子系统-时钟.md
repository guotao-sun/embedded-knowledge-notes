# Linux 时钟

> 参考：https://developer.aliyun.com/article/1324307

## 一、先说结论

- **时钟不是"一个数字"，是一棵树**：PLL → 分频 → 多路选择（MUX）→ 门控（gate）→ 外设
- 谁**提供**时钟（注册 `clk` + 实现 `clk_ops` + 在树上占一个节点）= **provider**
- 谁**使用**时钟（只管 `clk_get` / `clk_prepare_enable`）= **consumer**
- 设备树里只给"**去哪个控制器、取第几号时钟**"，真正的时钟树由 clock 驱动在 probe 时交给 CCF（Common Clock Framework）建起来
- 外设驱动调 `clk_prepare_enable()` 之前，**必须先 `clk_get` 拿到一个非错误指针**——拿不到就是设备树写错或 provider 还没注册

## 二、基本判断

- **分频器 / 倍频器**：通常是 **clock provider**
- **时钟树末端外设（UART/SPI/I2C）**：通常是 **clock consumer**

判断规则：

- 谁"注册 clk + 提供 clk_ops + 在 clk tree 中有节点"，谁就是 provider
- 谁"只通过 clk API 获取并使用 clk"，谁就是 consumer

同一颗芯片里往往有多个 provider：外部晶振是根节点、PLL 是一个 provider、CCM（时钟控制器）又是一个 provider——**它们串成一棵树，不是平级的一堆时钟**。

## 三、IMX6UL_CLK_UART1_IPG 是不是"已经展开过的"？

是的，但要分清"展开"的含义：

它不是在 DTS 里展开，而是：

> 在 **clock controller driver 初始化时（probe 阶段）已经被 CCF 构建成 clock tree 节点**

也就是说：

- DTS 只给"名字/ID 引用"
- 真正的展开发生在 **clock driver + CCF**

具体过程：

```text
clock 控制器节点匹配 compatible
    ↓
clock driver probe：clk_hw_register() / devm_clk_hw_register() 逐个注册 clk
    ↓
of_clk_add_provider(node, of_clk_src_onecell_get, data)
    ↓
CCF 把 clk 的 parent 指针连起来 → 形成 clock tree
    ↓
consumer 用 <&clks ID> 时，通过 provider 的 get 回调取到 clk
```

## 四、只要 DTS 声明就可以用了吗？

基本是，但前提是必须同时满足：

1. clock provider driver 已注册（CCF 已建树）
2. clks 节点 driver probe 完成
3. `of_clk_add_provider()` 已执行

否则：DTS 写了也拿不到 clk——`clk_get()` 返回 `-EPROBE_DEFER` 或 `-ENOENT`。

> 看到 `-EPROBE_DEFER` 不要慌，原样返回，内核会在 provider 就绪后重新 probe 你的设备（详见 [GPIO 子系统](./DRIVER-17-子系统-GPIO子系统.md) 里的返回码表）。

## 五、DTS 时钟引用示例

```dts
<&clks IMX6UL_CLK_UART1_IPG>
```

合起来意思是：

> "去 clks 这个 clock controller 里，取第 IMX6UL_CLK_UART1_IPG 号 clock"

### clock controller 节点示例

```dts
clock-controller@... {
    compatible = "vendor,clock-mux";
    clocks = <&pll1>, <&pll2>, <&osc>;
    clock-names = "pll1", "pll2", "osc";
    #clock-cells = <1>;
};

clock-controller@... {
    compatible = "vendor,clock-divider";
    clocks = <&pll1>;
    clock-names = "parent";
    #clock-cells = <0>;
};
```

- `#clock-cells = <1>`：引用时需要一个参数（时钟 ID）
- `#clock-cells = <0>`：引用时不需要参数（该控制器只输出一个时钟）

**`clocks` 与 `clock-names` 一一对应**，consumer 可以用名字而不是序号去取：

```c
clk = devm_clk_get(dev, "ipg");       /* 找 clock-names 里的 "ipg" */
clk = devm_clk_get(dev, NULL);        /* 只有一路时钟时可以省名字 */
```

## 六、外设驱动里怎么用

```c
struct clk *ipg, *per;

/* 1. 取时钟：per 用于算波特率，ipg 用于访问寄存器 */
ipg = devm_clk_get(&pdev->dev, "ipg");
if (IS_ERR(ipg))
    return PTR_ERR(ipg);

per = devm_clk_get(&pdev->dev, "per");

/* 2. 使能（prepare + enable 两步，对应 clk_ops 里的 prepare/enable 回调） */
clk_prepare_enable(ipg);
clk_prepare_enable(per);

/* 3. 拿真实频率（不要用 DTS 里写死的数） */
rate = clk_get_rate(per);
```

**为什么必须 `clk_get_rate()` 而不是用宏里的常数**：时钟树的实际频率由 PLL 配置、分频值共同决定，板上可能改过；用错频率算出来的波特率会偏，现象是"通信乱码"。

卸载/出错时要 `clk_disable_unprepare()` 关掉——门控时钟开着会白耗电，也会让芯片该休眠时睡不着。

## 七、调试：看整棵时钟树

```bash
cat /sys/kernel/debug/clk/clk_summary
```

输出能看到每个时钟的：

```text
   clock        enable_cnt  prepare_cnt  rate        accuracy  phase
 osc              1           1           24000000    0         0
    pll1          1           1           528000000   0         0
       pll1_bypass ...
          uart1_ipg  1        1           66000000    0         0
```

- `enable_cnt` 非 0 说明有人开着它——**排查"为什么睡不着/功耗高"第一站**
- `rate` 是 CCF 算出来的实际频率，跟 `clk_get_rate()` 返回值一致
- 某一路是 `0` 且没人 enable，通常是驱动忘了调 `clk_prepare_enable`

## 八、常见坑

| 现象 | 原因 | 修法 |
|---|---|---|
| `clk_get` 返回 `-ENOENT` | `clock-names` 拼错，或设备树没写 `clocks` | 对照驱动里的名字逐个改 |
| `clk_get` 返回 `-EPROBE_DEFER` | provider 还没 probe | 原样返回，别当错误 |
| 外设不工作但寄存器能读写 | 门控时钟没开 | `clk_prepare_enable()` |
| 波特率总差一点 | 用了错的时钟源/写死的频率 | `clk_get_rate()` 现取 |
| `clk_set_rate` 没效果 | 该时钟只读、或父时钟不支持分频 | 查 provider 的 `clk_ops`，可能需要从父节点设 |

## 九、一句话总结

**时钟是一棵树：provider 在 probe 时把树建好并 `of_clk_add_provider`，consumer 用 `<&clks ID>` + `clock-names` 取到 clk，`clk_prepare_enable` 开门、`clk_get_rate` 拿真实频率。**
