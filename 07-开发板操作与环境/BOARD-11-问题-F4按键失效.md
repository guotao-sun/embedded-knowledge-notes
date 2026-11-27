# Linux 开发板中 F4 或其他按键失效

## 一、先说结论

F1~F12、方向键、`Home`/`End` 在终端里"按了没反应或出乱码"，**99% 不是键盘坏了，是 `TERM` 环境变量的值不对**。

```bash
echo $TERM
# 常见错误值：vt100、linux、dumb、空
```

修复只要一行：

```bash
export TERM=xterm-256color
```

要永久生效写进 `~/.bashrc`：

```bash
echo 'export TERM=xterm-256color' >> ~/.bashrc
source ~/.bashrc
```

## 二、为什么一个环境变量能决定 F 键

终端里的按键**不是直接给你按下的是什么键**，而是变成一串转义序列（escape sequence）交给程序。程序怎么把这串字节翻译成"F4"，靠的是一张表——**terminfo 数据库**：

```text
你按 F4 → 终端发一串字节（如 ESC O S 或 ESC [ 14~）
        → 程序查 terminfo[$TERM] 里的 kf4 条目
        → 匹配上才知道"这是 F4"
```

所以：

| 环节 | 出错表现 |
|---|---|
| `TERM` 指向的条目不存在 | 程序报 `unknown terminal type` 或干脆按键全无反应 |
| 条目里没有 `kf4`（如 `vt100`） | F 键无效，但普通字符正常 |
| 终端实际发的序列与条目不符 | 按键变成乱码字符（如 `^[[14~`） |

`vt100` 是 1978 年的终端，**它根本没有 F1~F12**——所以 `TERM=vt100` 时 F 键当然无效。嵌入式 rootfs 的默认 `TERM` 常常就设成了这种"最保守"的值。

## 三、确认问题在哪一环

```bash
# 1. 看当前 TERM
echo $TERM

# 2. 看这个 TERM 在数据库里有没有
infocmp $TERM | head
# 报 "infocmp: couldn't open terminfo database" 就是没有

# 3. 看它有没有定义 F4
infocmp $TERM | grep -o "kf4=[^,]*"
# 有输出（如 kf4=\E[14~）说明定义了；没输出说明这个 TERM 不支持 F 键

# 4. 直接看按键发了什么字节（最可靠）
cat -v
# 然后按 F4，看屏幕上出现什么；Ctrl+C 退出
```

第 4 步是关键：如果 `cat -v` 能看到 `^[[14~`，说明**键盘和串口都是好的**，纯粹是软件没认出来。

## 四、`TERM` 该设成什么

| 场景 | 建议值 | 说明 |
|---|---|---|
| SSH（Xshell/PuTTY/secureCRT） | `xterm-256color` | 绝大多数情况都对 |
| 串口终端（minicom/secureCRT serial） | `xterm` 或 `vt100` | 串口本身不传"终端类型"，靠程序声明 |
| 只有最基本功能、terminfo 缺失 | `vt100` | 能显示，但 F 键/颜色没有 |
| 颜色/光标异常 | `xterm-256color` | 带 256 色 |

板子上如果没有 `xterm-256color` 的 terminfo 条目（`/usr/share/terminfo/x/xterm-256color` 不存在），可以用 `xterm`。

检查：

```bash
ls /usr/share/terminfo/x/ 2>/dev/null
ls /lib/terminfo/ 2>/dev/null
```

## 五、`source` 与 `./` 的区别（顺手说明）

改完 `.bashrc` 要让它生效：

| 命令 | 做了什么 | 结果 |
|---|---|---|
| `source ~/.bashrc` | 在**当前 shell** 里逐行执行 | 环境变量立即生效 |
| `. ~/.bashrc` | 同上（`.` 是 `source` 的简写） | 同上 |
| `~/.bashrc` 或 `./x.sh` | **新开一个子 shell** 执行 | 子 shell 里的变量不影响你当前这个 |
| `bash ~/.bashrc` | 新开 bash 执行 | 同上，退出就丢 |

这就是"我明明 export 了却没生效"的常见原因：脚本是在子 shell 里跑的。

## 六、其它可能原因（按概率）

| 现象 | 原因 | 验证 |
|---|---|---|
| 只有 F 键无效，字母正常 | `TERM` 条目缺 `kf*` | `infocmp $TERM | grep kf` |
| 方向键变成 `^[[A` 之类 | `TERM` 与终端不匹配 | 换 `xterm` 试 |
| 所有按键都无反应 | 串口流控（RTS/CTS）或波特率不对 | 关流控、核对波特率 |
| 在 `vi` 里 F 键无效 | vi 自己读 terminfo，与 `TERM` 同因 | 同上 |
| `Ctrl+C` 也没反应 | 程序把终端设成了 raw 模式 | `stty sane` 恢复 |
| 只有某个程序里无效 | 该程序没读 terminfo（自己硬编码） | 查程序文档/换替代程序 |

`stty sane` 是"终端乱了"的万能复位（比如程序崩溃后回车不换行）：

```bash
stty sane
```

## 七、一句话总结

**F 键靠 `TERM` 指向的 terminfo 条目里的 `kf4` 定义来识别；`vt100` 这种老条目没有 F 键，所以失效——`export TERM=xterm-256color` 写进 `.bashrc` 并 `source` 即可，改完记得 `source` 是在当前 shell 生效、`./` 不是。**
