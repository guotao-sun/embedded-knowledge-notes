# 编译 imx6ull Linux 应用 app

## 一、先说结论

应用交叉编译只有三句话：

```text
用目标架构的 gcc（不是 gcc）
头文件用目标板的（-I 或 sysroot）
库用目标板的（-L 或 sysroot + -l）
```

三条里错任何一条，症状都不一样，但都很典型：

| 错哪条 | 症状 |
|---|---|
| 用错 gcc | 板子上跑报 `Exec format error` 或 `cannot execute binary file` |
| 头文件用了宿主机 | 编得过去，运行时段错误 / 结构体大小对不上 |
| 库用了宿主机 | `cannot find -lxxx: File format not recognized` |

## 二、装工具链

```bash
# 1. 下载（Linaro 官网，选 x86_64 宿主 + arm-linux-gnueabihf 目标）
#    gcc-linaro-7.5.0-2019.12-x86_64_arm-linux-gnueabihf.tar.xz

# 2. 解压到固定位置
sudo mkdir -p /usr/local/arm
sudo tar -xvf gcc-linaro-7.5.0-2019.12-x86_64_arm-linux-gnueabihf.tar.xz -C /usr/local/arm/

# 3. 加进 PATH（当前终端）
export PATH=$PATH:/usr/local/arm/gcc-linaro-7.5.0-2019.12-x86_64_arm-linux-gnueabihf/bin

# 4. 验证
arm-linux-gnueabihf-gcc -v
```

`gnueabihf` 里的 `hf` = hard float（硬件浮点）。i.MX6ULL 的 Cortex-A7 有 FPU，所以用 `hf` 版本；用软浮点版本编出来的库和系统里的 `.so` ABI 不兼容，运行时会报 `Illegal instruction` 或直接找不到库。

## 三、环境变量写在哪

| 文件 | 作用域 | 执行时机 | 适合放什么 |
|---|---|---|---|
| `~/.bashrc` | 当前用户 | 每次开新终端 | PATH、别名（**推荐**） |
| `~/.profile` / `~/.bash_profile` | 当前用户 | 登录时一次 | 用户级登录环境 |
| `/etc/profile` | 所有用户 | 登录时一次 | 系统级 PATH |
| `/etc/environment` | 所有用户 | 登录前 | 纯 `KEY=VALUE`，**不支持变量展开** |

推荐做法：

```bash
echo 'export PATH=$PATH:/usr/local/arm/gcc-linaro-7.5.0-2019.12-x86_64_arm-linux-gnueabihf/bin' >> ~/.bashrc
source ~/.bashrc
```

别动 `/etc/environment` 写 `PATH=$PATH:...`——它不展开变量，会把字面量 `$PATH:` 塞进 PATH，之后所有命令都找不到。

## 四、编译命令的结构

```bash
${CC} -o 输出 源文件 -I头文件目录 -L库目录 -l库名
```

| 选项 | 含义 | 例子 |
|---|---|---|
| `-o` | 输出文件名 | `-o hello` |
| `-I` | 头文件搜索路径（大写 i） | `-I/opt/sysroot/usr/include` |
| `-L` | 库搜索路径 | `-L/opt/sysroot/usr/lib` |
| `-l` | 链接哪个库（小写 L，写 `libxxx.so` 中间的 `xxx`） | `-lasound` → `libasound.so` |
| `-static` | 静态链接（把库编进可执行文件） | 板子上缺库时救急 |
| `-g` | 带调试信息 | gdb 调试 |
| `-std=gnu99` | C 标准 | 用 `//` 注释、声明后定义变量时常用 |

`-I`/`-L` 是**路径**，`-l` 是**名字**，这是最容易混的一处。

## 五、两个真实例子

### 最简单的

```bash
arm-linux-gnueabihf-gcc hello.c -o hello
```

不依赖第三方库时，工具链自带的 libc 就够，直接编。

### 带 ALSA + 线程（需要 sysroot）

```bash
arm-linux-gnueabihf-gcc -std=gnu99 \
    --sysroot=/opt/fsl-imx-x11/4.1.15-2.1.0/sysroots/cortexa7hf-neon-poky-linux-gnueabi \
    -o playAndRecord playAndRecord.c -lpthread -lasound
```

`--sysroot=<目标根文件系统>` 一次性解决"头文件 + 库 + 启动文件（crt1.o）"三件事——它让编译器把 `<目标根>/usr/include`、`<目标根>/usr/lib` 当成默认路径，所以你**不用**再写 `-I`/`-L`。

> sysroot 里必须有 `usr/lib/libasound.so` 这类**目标架构**的库。把宿主机的 `/usr/lib` 指进 sysroot 是最常见的错误，会得到 `skipping incompatible ...` 或 `File format not recognized`。

## 六、编完先自检，再拷

```bash
file hello
# 期望：ELF 32-bit LSB executable, ARM, EABI5, dynamically linked

readelf -h hello | grep -E "Class|Machine"
# Class: ELF32    Machine: ARM

arm-linux-gnueabihf-readelf -d hello | grep NEEDED
# 看它依赖哪些 .so（板子上必须有对应的）
```

`file` 说 `x86-64` → 工具链用错了。`file` 说 `ARM` 但板子上 `cannot execute` → 多半是 ABI/浮点不匹配（软浮点 vs 硬浮点）。

## 七、拷到板子并运行

```bash
scp hello root@192.168.55.71:/home/root/
ssh root@192.168.55.71 'chmod +x /home/root/hello && /home/root/hello'
```

`scp` **不保留可执行位**（除非 `-p`），所以 `chmod +x` 不能省，否则报 `Permission denied`。

## 八、板子上跑不起来的四种典型症状

| 症状 | 真实原因 | 修法 |
|---|---|---|
| `Permission denied` | 没有执行权限 | `chmod +x` |
| `Exec format error` | 架构不对（编成 x86 了） | 重编，检查 `ARCH` / `${CC}` |
| `No such file or directory`（文件明明存在） | **动态加载器** `/lib/ld-linux-armhf.so.3` 不存在 | 用 `-static`，或补板子上的 ld-linux |
| `error while loading shared libraries: libasound.so.2` | 板子缺库 | 把库拷到板子 `/usr/lib` 或设 `LD_LIBRARY_PATH` |

第三条最反直觉：`ls` 能看见文件、`file` 说是 ARM，却报"没有那个文件或目录"——内核其实是在找 ELF 里记录的**解释器路径**（`readelf -l hello | grep interpreter`），那个路径不存在时报的就是这个错。

## 九、常用补充

```bash
# 减小体积（发布时用）
arm-linux-gnueabihf-strip hello

# 查依赖的库在板子上有没有
arm-linux-gnueabihf-objdump -p hello | grep NEEDED

# 静态链接（板子上库不全时救急，体积会变大）
arm-linux-gnueabihf-gcc -static hello.c -o hello

# 在板子上查动态库依赖是否满足
ldd /home/root/hello
```

## 十、一句话总结

**`${CC}` 编、`--sysroot` 指目标根、`-I`/`-L`/`-l` 分别管头/库路径/库名；编完先 `file` 确认 ARM，再 `readelf -d` 确认依赖，最后 `chmod +x`——四个检查点，缺一个就在板子上报莫名其妙的错。**
