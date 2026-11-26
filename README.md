# 嵌入式 Linux 学习笔记

> 作为小菜鸡，本仓库记录了本人嵌入式 Linux 开发学习过程中的知识点、代码示例和调试经验，欢迎fork以及指正。

## 📑 目录

<!-- TOC START -->
### 01-基础概念与名词解释

- [Linux 名词解释](./01-基础概念与名词解释/BASE-01-概念-Linux名词解释.md)
- [嵌入式 Linux 常用命令](./01-基础概念与名词解释/BASE-02-命令-嵌入式Linux常用命令.md)
- [Git 使用方法](./01-基础概念与名词解释/BASE-03-工具-Git使用方法.md)

### 02-内核核心机制

- [linux 启动流程](./02-内核核心机制/KERNEL-01-启动-Linux启动流程.md)
- [LINUX 启动代码](./02-内核核心机制/KERNEL-02-启动-Linux启动代码.md)
- [LINUX 初始化的宏](./02-内核核心机制/KERNEL-03-启动-初始化宏.md)
- [LINUX 中断](./02-内核核心机制/KERNEL-04-中断-Linux中断.md)
- [imx6ull Linux 中断与 stm32 中断](./02-内核核心机制/KERNEL-05-中断-imx6ull与STM32中断对比.md)
- [linux 调度](./02-内核核心机制/KERNEL-06-调度-Linux调度.md)
- [STM32 与 LINUX 的任务调度方式](./02-内核核心机制/KERNEL-07-调度-STM32与Linux任务调度对比.md)
- [LINUX 并发与竞争](./02-内核核心机制/KERNEL-08-并发-并发与竞争.md)
- [LINUX 等待队列](./02-内核核心机制/KERNEL-09-同步-等待队列.md)
- [linux 定时器](./02-内核核心机制/KERNEL-10-时间-定时器.md)
- [页表](./02-内核核心机制/KERNEL-11-内存-页表.md)
- [linux 用户态内核态](./02-内核核心机制/KERNEL-12-权限-用户态与内核态.md)

### 03-驱动开发基础

- [Linux 驱动核心骨架（总线驱动模型）](./03-驱动开发基础/DRIVER-01-框架-驱动核心骨架.md)
- [Linux 驱动设备号](./03-驱动开发基础/DRIVER-02-字符设备-驱动设备号.md)
- [安装内核模块命令](./03-驱动开发基础/DRIVER-03-模块-安装内核模块命令.md)
- [注册设备与创建设备的区别](./03-驱动开发基础/DRIVER-04-字符设备-注册设备与创建设备.md)
- [Linux ioctl 操作](./03-驱动开发基础/DRIVER-05-字符设备-ioctl操作.md)
- [Linux 串口驱动](./03-驱动开发基础/DRIVER-06-字符设备-串口驱动.md)
- [Linux I2C 读写数据的示例](./03-驱动开发基础/DRIVER-07-I2C-读写示例.md)
- [Linux 总线驱动模型核心例程](./03-驱动开发基础/DRIVER-08-总线-总线驱动模型核心例程.md)
- [LINUX 总线注册时间](./03-驱动开发基础/DRIVER-09-总线-总线注册时间.md)
- [Linux 总线驱动模型设备创建顺序](./03-驱动开发基础/DRIVER-10-总线-设备创建顺序.md)
- [platform 总线](./03-驱动开发基础/DRIVER-11-总线-platform总线.md)
- [Platform 总线与其他总线的区别](./03-驱动开发基础/DRIVER-12-总线-Platform与其他总线区别.md)
- [设备树的概念](./03-驱动开发基础/DRIVER-13-设备树-设备树概念.md)
- [设备树解析流程](./03-驱动开发基础/DRIVER-14-设备树-解析流程.md)
- [Linux 设备树的节点 device_node](./03-驱动开发基础/DRIVER-15-设备树-device_node节点.md)
- [pinctrl 子系统与 GPIO 子系统](./03-驱动开发基础/DRIVER-16-子系统-pinctrl与GPIO.md)
- [GPIO 子系统描述](./03-驱动开发基础/DRIVER-17-子系统-GPIO子系统.md)
- [input 子系统](./03-驱动开发基础/DRIVER-18-子系统-input子系统.md)
- [Linux 时钟](./03-驱动开发基础/DRIVER-19-子系统-时钟.md)
- [regmap 寄存器访问抽象框架](./03-驱动开发基础/DRIVER-20-寄存器-regmap抽象框架.md)
- [regmap 示例](./03-驱动开发基础/DRIVER-21-寄存器-regmap示例.md)
- [static 关键字与 const 关键字](./03-驱动开发基础/DRIVER-22-C基础-static与const.md)

### 04-ALSA音频驱动

- [ALSA 学习路线](./04-ALSA音频驱动/ALSA-01-入门-学习路线.md)
- [Linux 音频栈](./04-ALSA音频驱动/ALSA-02-架构-Linux音频栈.md)
- [Linux 声卡 ALSA](./04-ALSA音频驱动/ALSA-03-架构-Linux声卡与ALSA.md)
- [音频数据结构层次](./04-ALSA音频驱动/ALSA-04-数据-音频数据结构层次.md)
- [Machine 驱动（硬件板卡的音频系统配置文件）](./04-ALSA音频驱动/ALSA-05-驱动-Machine驱动.md)
- [ALSA 的设备树示例](./04-ALSA音频驱动/ALSA-06-设备树-ALSA设备树示例.md)
- [Linux 音频驱动编译调试流程（ALSA 编译调试）](./04-ALSA音频驱动/ALSA-07-调试-驱动编译调试流程.md)
- [LINUX 开发板录放指令](./04-ALSA音频驱动/ALSA-08-使用-开发板录放指令.md)

### 05-编译与构建系统

- [Linux 源码顶层结构](./05-编译与构建系统/BUILD-01-源码-Linux源码顶层结构.md)
- [Kconfig 讲解](./05-编译与构建系统/BUILD-02-配置-Kconfig讲解.md)
- [imx6ull 芯片内核编译](./05-编译与构建系统/BUILD-03-编译-imx6ull内核编译.md)
- [i.MX6ULL 编译 Linux 内核 / 驱动模块 / 应用](./05-编译与构建系统/BUILD-04-编译-iMX6ULL内核驱动应用.md)
- [RK3568 编译 Linux 内核 / 驱动模块 / 应用](./05-编译与构建系统/BUILD-05-编译-RK3568内核驱动应用.md)
- [Linux 驱动编译流程](./05-编译与构建系统/BUILD-06-编译-驱动编译流程.md)
- [imx6ull Linux 驱动 Makefile 模板](./05-编译与构建系统/BUILD-07-Makefile-驱动Makefile模板.md)
- [编译设备树](./05-编译与构建系统/BUILD-08-设备树-编译设备树.md)
- [编译 imx6ull Linux 应用 app](./05-编译与构建系统/BUILD-09-应用-编译imx6ull应用.md)
- [嵌入式 Linux 编译工具链的不同](./05-编译与构建系统/BUILD-10-工具链-编译工具链区别.md)
- [Source Insight 使用方法](./05-编译与构建系统/BUILD-11-工具-SourceInsight使用方法.md)

### 06-U-Boot与启动

- [U-Boot 启动 Linux 内核指令](./06-U-Boot与启动/BOOT-01-U-Boot-启动内核指令.md)
- [Secure Boot 的核心思想](./06-U-Boot与启动/BOOT-02-安全-SecureBoot核心思想.md)
- [RK3568 安全启动 + SO 库芯片绑定流程](./06-U-Boot与启动/BOOT-03-安全-RK3568安全启动与芯片绑定.md)

### 07-开发板操作与环境

- [Linux 开发板常用命令](./07-开发板操作与环境/BOARD-01-操作-常用命令.md)
- [Linux 文件目录](./07-开发板操作与环境/BOARD-02-操作-文件目录结构.md)
- [Linux 开发板设置静态 IP](./07-开发板操作与环境/BOARD-03-网络-设置静态IP.md)
- [Linux 开发板 SCP 传输文件](./07-开发板操作与环境/BOARD-04-网络-SCP传输文件.md)
- [Linux 开发板挂载共享文件夹](./07-开发板操作与环境/BOARD-05-文件-挂载共享文件夹.md)
- [挂载 U 盘](./07-开发板操作与环境/BOARD-06-文件-挂载U盘.md)
- [Linux 对内存卡做镜像](./07-开发板操作与环境/BOARD-07-镜像-内存卡做镜像.md)
- [Linux 备份 eMMC 镜像](./07-开发板操作与环境/BOARD-08-镜像-备份eMMC镜像.md)
- [Linux 开发板查看系统信息](./07-开发板操作与环境/BOARD-09-调试-查看系统信息.md)
- [Linux 开发板查看 CPU 温度](./07-开发板操作与环境/BOARD-10-调试-查看CPU温度.md)
- [LINUX 开发板中 F4 或其他按键失效](./07-开发板操作与环境/BOARD-11-问题-F4按键失效.md)
- [RK3568 源码结构](./07-开发板操作与环境/BOARD-12-源码-RK3568源码结构.md)

### 08-C语言与软件设计

- [C 语言常见问题](./08-C语言与软件设计/C-01-语言-C语言常见问题.md)
- [低性能 MCU 软件设计分层](./08-C语言与软件设计/C-02-设计-MCU软件设计分层.md)

### 09-图形系统

- [LINUX 图形系统本质](./09-图形系统/GUI-01-架构-Linux图形系统本质.md)
- [图形界面 QT 等](./09-图形系统/GUI-02-应用-图形界面与QT.md)

### 10-计算机组成原理

- [CPU Cache、VIPT 与 Cache Miss 工作机制](./10-计算机组成原理/CO-01-缓存-CPU-Cache与VIPT.md)

### 11-网络通信

- [数字通信基础：香农公式、数字调制与眼图](./11-网络通信/NET-01-物理层-数字通信基础.md)
- [TCP 三次握手与四次挥手 笔记](./11-网络通信/NET-02-传输层-TCP三次握手与四次挥手.md)
- [滑动窗口协议（Sliding Window Protocol）学习笔记](./11-网络通信/NET-03-传输层-滑动窗口与GBN.md)

### 12-Python

- [Python print函数讲解](./12-Python/Python-01-基础-print与输入输出.md)
- [Python 对象模型笔记：名字是标签，对象是实物](./12-Python/Python-02-对象-名字与对象模型.md)
- [Python 入门学习问答合集](./12-Python/Python-03-基础-入门问答合集.md)
- [Python 异常处理与文件读写问答](./12-Python/Python-04-文件-异常处理与文件读写.md)
- [Python 模块与包问答](./12-Python/Python-05-模块-模块与包.md)
- [Python 网络请求问答](./12-Python/Python-06-网络-HTTP请求与urllib.md)
- [Python subprocess 模块讲解](./12-Python/Python-07-进程-subprocess与子进程.md)

### 13-LLM

- [大模型 API 调用基础](./13-LLM/LLM-01-接口-API调用基础.md)
- [一次 API 请求的完整旅程](./13-LLM/LLM-02-接口-一次请求的完整旅程.md)
- [messages 与多轮对话：上一轮的数据是怎么发出去的](./13-LLM/LLM-03-对话-messages与多轮对话.md)
- [大模型结构化输出（JSON）](./13-LLM/LLM-04-输出-结构化输出.md)
- [上下文窗口（Context Window）](./13-LLM/LLM-05-上下文-窗口与上限.md)
- [长会话的上下文管理](./13-LLM/LLM-06-上下文-长会话管理.md)
- [长期记忆的三层设计](./13-LLM/LLM-07-记忆-长期记忆三层设计.md)
- [Token 计费与缓存](./13-LLM/LLM-08-计费-Token计费与缓存.md)
- [大模型服务的数据留存与隐私边界](./13-LLM/LLM-09-安全-数据留存与隐私边界.md)
- [智能体运行方式](./13-LLM/LLM-10-智能体-运行方式与工具调用.md)

### 14-其他

- [YML 文件讲解](./14-其他/MISC-01-配置-YML文件讲解.md)
- [非对称加密 · 加密 / 解密 / 签名 / 验签 流程参考](./14-其他/MISC-02-安全-非对称加密流程参考.md)
<!-- TOC END -->

---

## 📝 说明

- 本笔记基于学习过程整理，内容可能存在不准确之处，欢迎指正
- 代码示例主要基于 Linux Kernel 4.19，适用于 ARM 架构嵌入式平台
- 图片资源存放在 `images/` 目录下
