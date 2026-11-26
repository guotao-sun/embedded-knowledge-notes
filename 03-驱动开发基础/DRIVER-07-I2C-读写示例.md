# Linux I2C 读写数据的示例

## 一、先说结论

用户态操作 I2C 有两种方式，本质区别是**"两次调用"还是"一次事务"**：

| 方式 | 本质 | 适用 |
|---|---|---|
| `ioctl(I2C_RDWR)` | 一次 ioctl 下发多条 msg，**中间不发 STOP（repeated start）** | "写寄存器地址 + 读数据"这类组合操作，绝大多数 sensor/EEPROM |
| `ioctl(I2C_SLAVE)` + `write`/`read` | 两次独立传输，中间总线释放 | 简单读写、调试 |

**读寄存器必须用第一种**。第二种在很多芯片上会读到错的值，因为"写地址"和"读数据"之间插了一个 STOP，芯片内部指针被复位。

## 二、示例一（标准方式：I2C_RDWR）

使用 `ioctl(fd, I2C_RDWR, &msgset)` 一次完成"写寄存器地址 + 读数据"的组合操作。

```c
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/i2c.h>
#include <linux/i2c-dev.h>

int main()
{
    int fd;
    fd = open("/dev/i2c-1", O_RDWR);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    unsigned char reg = 0x10;
    unsigned char data;
    struct i2c_msg msgs[2];
    struct i2c_rdwr_ioctl_data msgset;

    /* 第 1 条消息：写寄存器地址 */
    msgs[0].addr  = 0x50;
    msgs[0].flags = 0;
    msgs[0].len   = 1;
    msgs[0].buf   = &reg;

    /* 第 2 条消息：读数据 */
    msgs[1].addr  = 0x50;
    msgs[1].flags = I2C_M_RD;
    msgs[1].len   = 1;
    msgs[1].buf   = &data;

    msgset.msgs  = msgs;
    msgset.nmsgs = 2;

    if (ioctl(fd, I2C_RDWR, &msgset) < 0) {
        perror("ioctl I2C_RDWR");
        return -1;
    }

    printf("data = 0x%02x\n", data);
    close(fd);
    return 0;
}
```

`nmsgs = 2` 是关键：内核把这 2 条 msg 串成一次传输，**第 1 条结束后不发 STOP，直接 repeated start 进第 2 条**。这正是 I2C 读寄存器的标准时序。

## 三、示例二（普通方式：write + read）

先通过 `I2C_SLAVE` 设置从机地址，再用 `write` / `read` 单独操作。

### 写数据

```c
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/i2c-dev.h>

int main()
{
    int fd;
    fd = open("/dev/i2c-1", O_RDWR);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    /* 设置从机地址 */
    if (ioctl(fd, I2C_SLAVE, 0x50) < 0) {
        perror("ioctl");
        return -1;
    }

    unsigned char buf[2];
    buf[0] = 0x10;   /* 寄存器地址 */
    buf[1] = 0x55;   /* 数据 */

    if (write(fd, buf, 2) != 2) {
        perror("write");
        return -1;
    }

    close(fd);
    return 0;
}
```

### 读数据

```c
#include <stdio.h>
#include <fcntl.h>
#include <unistd.h>
#include <sys/ioctl.h>
#include <linux/i2c-dev.h>

int main()
{
    int fd;
    fd = open("/dev/i2c-1", O_RDWR);
    if (fd < 0) {
        perror("open");
        return -1;
    }

    if (ioctl(fd, I2C_SLAVE, 0x50) < 0) {
        perror("ioctl");
        return -1;
    }

    unsigned char reg = 0x10;
    unsigned char data;

    /* 先写寄存器地址 */
    if (write(fd, &reg, 1) != 1) {
        perror("write reg");
        return -1;
    }

    /* 再读数据 */
    if (read(fd, &data, 1) != 1) {
        perror("read");
        return -1;
    }

    printf("data = 0x%02x\n", data);
    close(fd);
    return 0;
}
```

## 四、两种方式对比

| 方式 | 优点 | 缺点 |
|------|------|------|
| `I2C_RDWR` | 一次 ioctl 完成组合事务，**原子性好**（不会被其他进程插队） | 代码稍复杂，要自己填 msg |
| `write` + `read` | 代码简单直观 | 两次调用之间可能被其他设备打断；**中间有 STOP，多数寄存器读会失败** |

> 还有个隐藏差异：`I2C_SLAVE` 设置的是"文件级的当前从机地址"，同一个 fd 被两个线程共用时会互相踩；`I2C_RDWR` 每条 msg 自带 `addr`，天生没有这个问题。多线程场景优先用 `I2C_RDWR`。

## 五、第三种：SMBus 接口（最省事）

内核对常见 SMBus 时序做了封装，不用自己拼 msg：

```c
#include <linux/i2c-dev.h>
#include <i2c/smbus.h>

int fd = open("/dev/i2c-1", O_RDWR);
ioctl(fd, I2C_SLAVE, 0x50);

int val  = i2c_smbus_read_byte_data(fd, 0x10);   /* 读 8 位寄存器 */
int val2 = i2c_smbus_read_word_data(fd, 0x20);  /* 读 16 位寄存器 */
i2c_smbus_write_byte_data(fd, 0x10, 0x55);      /* 写 8 位寄存器 */
```

注意 SMBus 的"字"是**小端**（低字节在前），很多 sensor 手册写的却是大端，读出来要自己交换字节。

## 六、内核侧的对应写法

用户态这套接口，内核里对应的是 `i2c_transfer()`：

```c
struct i2c_msg msgs[2] = {
    { .addr = client->addr, .flags = 0,       .len = 1, .buf = &reg  },
    { .addr = client->addr, .flags = I2C_M_RD, .len = 1, .buf = &data },
};
int ret = i2c_transfer(client->adapter, msgs, 2);   /* 返回成功条数，不是 0 */
```

驱动里更常用封装好的：

```c
int v = i2c_smbus_read_byte_data(client, reg);
int r = regmap_read(map, reg, &v);      /* 走 regmap，见 20/21 篇 */
```

## 七、常见错误

| 现象 | 原因 | 修法 |
|---|---|---|
| `Remote I/O error` | 从机没应答（地址错、没上拉、芯片没供电） | 用 `i2cdetect -y 1` 扫地址 |
| 地址怎么填都不对 | **手册给的是 8 位地址（含读写位），Linux 要 7 位** | `0xA0 >> 1 = 0x50` |
| `Device or resource busy` | 地址已被别的驱动 `i2c_new_device` 占用 | 用 `I2C_SLAVE_FORCE`，或先解绑原驱动 |
| 读出来全是 0xFF | 总线没上拉 / SDA 被拉低 / 时序太快 | 查硬件上拉电阻，降速 |
| 偶发读错 | 多线程共用一个 fd 的 `I2C_SLAVE` | 改 `I2C_RDWR`，或每线程独立 fd |

常用调试命令（比写测试程序快得多）：

```bash
i2cdetect -l                       # 列出所有 I2C 适配器，确认 bus 编号
i2cdetect -y 1                     # 扫描 bus 1 上挂了哪些地址
i2cget -y 1 0x50 0x10              # 直接读一个寄存器
i2cset -y 1 0x50 0x10 0x55         # 直接写一个寄存器
```

## 八、一句话总结

**读寄存器用 `I2C_RDWR` 一次下发两条 msg（中间 repeated start），别用 write+read 两步走；地址填 7 位，不是手册上的 8 位。**
