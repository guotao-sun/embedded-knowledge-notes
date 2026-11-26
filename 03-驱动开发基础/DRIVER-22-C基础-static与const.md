# static 关键字与 const 关键字

## 一、先说结论

- `static` 在**文件作用域**是"私有"（只有本 .c 能用），在**函数内**是"活得久"（只初始化一次，生命周期到程序结束）
- `static` 不改变"存在哪里"：全局变量、`static` 全局变量、函数内 `static` 变量**都在 `.data` / `.bss`**，不在栈上
- `const` 是"我承诺不改"，让编译器把数据放进**只读段 `.rodata`**，还能在接口层面拦住误改
- 两者是 Linux 内核、DSP 算法库、ALSA 驱动里的通用习惯：**能加 const 就加 const，能加 static 就加 static**

## 二、static 的三种身份

```c
static int file_var;                  /* 1. 文件级全局：只有本文件可见 */

static int helper(void) { ... }       /* 2. 文件级函数：只有本文件能调 */

void foo(void)
{
    static int call_count = 0;        /* 3. 函数内静态：只初始化一次，跨调用保持 */
    call_count++;
}
```

### 从内存和符号表看，三者是同一类东西

| 类型 | 作用域 | 生命周期 | 所在段 | 符号属性 |
|---|---|---|---|---|
| 全局变量 `int g;` | 整个工程 | 程序运行期间 | `.data` / `.bss` | GLOBAL |
| `static` 全局变量 | 当前文件 | 程序运行期间 | `.data` / `.bss` | LOCAL |
| 函数内 `static` 变量 | 当前函数 | 程序运行期间 | `.data` / `.bss` | LOCAL（编译器改名，如 `call_count.0`） |

**关键结论：`static` 一旦出现，生命周期 = 整个程序运行期间，因此一定在 `.data` 或 `.bss`，而不是栈。**

这也解释了为什么函数内 `static` 变量的符号在 `.map` 文件里能看到一个奇怪的名字（`xxx.1234`）——编译器必须给它一个全局唯一的符号，但它原始名字又不能泄漏到别的文件，所以加了编号。

### 三个实际影响

1. **函数内 `static` 不是线程安全的**：两个线程同时进 `foo()`，操作的是同一份 `call_count`
2. **中断和主循环共享变量必须 `volatile`**：`static` 不解决"编译器优化掉读"，`volatile` 才解决
3. **大数组别放函数内 `static`**：它进 `.bss` 而不是栈，在 RAM 紧张的 MCU 上要心里有数

## 三、const 修饰的是"什么不能改"

### 函数参数中的 const

```c
short check_frameData_changed(const short *data, short len)
```

意思是：**我承诺不会修改调用者的数据。** 调用方看到这个签名就能放心把只读缓冲传进来，不用怕被偷偷改掉。

### const 修饰指针指向的数据

```c
const int *p;
/* 或者 */
int const *p;
```

两者完全一样。意思：

- 可以修改 `p`（指针本身）
- 不能修改 `*p`（指向的数据）

```c
int a = 10;
int b = 20;
const int *p = &a;

p = &b;      /* √ 可以：改指针 */
*p = 100;    /* × 错误：改数据 */
```

### const short *data 的含义

函数不能修改 `data` 指向的数据，但可以移动 `data` 指针本身（`data++` 遍历是允许的）。

### const 修饰指针本身

```c
int *const p = &a;
```

意思：

- 不能修改 `p`（指针本身）
- 可以修改 `*p`（指向的数据）

## 四、四写法对照表（记住这一张就够）

| 写法 | 指针本身 | 指向的数据 | 记忆口诀 |
|------|---------|-----------|---------|
| `int *p` | 可修改 | 可修改 | 都能改 |
| `const int *p` / `int const *p` | 可修改 | 不可修改 | `const` 在 `*` 左边 → 管数据 |
| `int *const p` | 不可修改 | 可修改 | `const` 在 `*` 右边 → 管指针 |
| `const int *const p` | 不可修改 | 不可修改 | 两个都有 |

读法从右往左："`p` is a const pointer to const int"。

## 五、const 变量放在哪：`.rodata`

```c
const char version[] = "1.0.0";     /* 进 .rodata，只读段 */
```

- 编译器把它放进 `.rodata`（只读数据段），运行时被 MMU/MPU 保护，写它会段错误
- 在 MCU 上 `.rodata` 通常在 Flash，**不占 RAM**——所以大常量表（字体、波形、查找表）一定要加 `const`
- 字符串字面量 `"abc"` 本身就是 `const char[]`，用 `char *p = "abc"` 在现代编译器上会告警（`-Wwrite-strings`），正确写法是 `const char *p = "abc"`

## 六、内核里的惯用法

```c
/* 1. 匹配表必须是 const，且以空项结尾 */
static const struct of_device_id my_of_match[] = {
    { .compatible = "vendor,chip" },
    { }
};

/* 2. file_operations 几乎总是 const */
static const struct file_operations my_fops = {
    .owner          = THIS_MODULE,
    .open           = my_open,
    .unlocked_ioctl = my_ioctl,
};

/* 3. 只读的寄存器表 / 时序表 */
static const u8 init_seq[] = { 0x01, 0x80, 0x00, ... };
```

为什么内核里全是 `const`：

- 这些表**运行时不该被改**，放进 `.rodata` 后，一旦有野指针写进去立刻 oops，问题暴露得早
- `const struct file_operations` 还能让编译器把整个结构体塞进只读页，减少被恶意篡改的面
- 驱动作者看到 `const` 参数就知道"这个函数不会改我的数据"，读代码成本降低

## 七、两个常见误区

| 误区 | 事实 |
|---|---|
| "`const` 变量就是编译期常量，可以用来定数组大小" | C 里不是。`const int n = 10; int a[n];` 是变长数组（VLA）。真正的编译期常量用 `#define` 或 `enum` |
| "`static` 让变量变快" | 不会。它改变的是作用域/生命周期，不是访问速度；反而函数内 `static` 多了线程安全问题 |

## 八、一句话总结

**`static` 管"谁能看见、活多久"（文件私有 / 全程存活，但都在 .data/.bss）；`const` 管"能不能改"（进 .rodata，接口上挡误改）——两者一个管可见性、一个管可变性，别混。**
