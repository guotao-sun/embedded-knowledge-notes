# 大模型 API 调用基础

## 一、先搞清楚：大模型到底能干什么

### 问题

很多人第一次接触大模型 API 会有个困惑：大模型不是只能聊天、处理自然语言吗？那手机 App、嵌入式设备是怎么"用上"它的？

### 本质

大模型 API 只做一件事：**吃一串 token，吐一串 token**。

```
你的程序  ──token──▶  模型  ──token──▶  你的程序
                                    ↓
                            由你的程序去执行真正的动作
```

关键在于最后一步。模型自己不能读文件、不能发请求、不能点按钮，它只会说话。真正的动作全部由调用它的 App 完成。

所以"App 怎么和大模型关联起来"的答案是三条路：

| 路径 | 模型干什么 | App 干什么 |
|---|---|---|
| 纯文本 | 生成一段话 | 展示出来 |
| 结构化输出 | 吐一个 JSON | 解析字段，按字段执行 |
| Function Calling / Agent | 吐"我要调用 xxx 工具" | 真正执行工具，把结果再喂回去 |

第三条就是所有"智能体"的底层，本质是**模型提需求 + App 干活**。执行权必须留在 App 侧，否则把任何输入都当指令执行，就是提示词注入漏洞。

### 三个常见误解

- **误解 1**：API key 放在 App 里没关系。→ 错。key 只能放服务端，客户端里的 key 一定会被抓包扒出来。
- **误解 2**：多模态模型能"看懂"图片。→ 不是。图片、音频都被编码成 token 序列再送进去，模型处理的始终是数字。
- **误解 3**：一次请求就是一次对话。→ Chat Completions 是**无状态**的，每次请求都得把完整历史重新发一遍。

## 二、OpenAI 兼容接口（"O 系"）

### 问题

模型厂商各家接口写法都不一样，接入两三家就要写两套代码，很痛苦。

### 解决

OpenAI 的 `/chat/completions` 事实上成了行业标准，几乎所有厂商都提供一层"兼容模式"，把它自己的服务伪装成 OpenAI 的样子。所以你的代码可以用 `openai` 官方 SDK，只改 `base_url` 和 `api_key` 就能切厂商。

### 阿里百炼的入口

```
https://dashscope.aliyuncs.com / compatible-mode / v1 / chat/completions
        └─ 哪个地域 ─┘          └─ 协议翻译层 ┘   └版本┘  └─ 功能 ┘
```

`dashscope` 是阿里模型服务平台的英文名（中文叫"灵积"），`bailian.console.aliyun.com` 是它的网页后台，两者是同一个东西的两张面孔：一个发请求，一个点鼠标。

`compatible-mode` 这一段才是关键——它是那层"翻译器"：

```
你的代码（OpenAI 写法）
    ↓
/compatible-mode   ← 把 OpenAI 字段翻译成 DashScope 内部格式
    ↓
DashScope 推理集群
```

去掉它、直接打 `/api/v1/services/aigc/text-generation/generation`，走的就是 DashScope 原生协议，字段名字全变了。

**地域影响额度**：`dashscope.aliyuncs.com` 是华北2（北京），`dashscope-intl.aliyuncs.com` 是新加坡国际站。免费额度只在中国内地（北京）生效，国际站没有。

## 三、最小请求与响应

### 请求

```python
import os, json
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)

resp = client.chat.completions.create(
    model="qwen3.8-flash",
    messages=[
        {"role": "user", "content": "整理：B 负责测试，周五前给结论"}
    ],
)

print(resp.choices[0].message.content)
```

### 响应（原始 JSON 长这样）

```json
{
  "id": "chatcmpl-...",
  "model": "qwen3.8-flash",
  "choices": [
    {
      "index": 0,
      "message": { "role": "assistant", "content": "好的，B 负责测试，周五前给结论。" },
      "finish_reason": "stop"
    }
  ],
  "usage": { "prompt_tokens": 20, "completion_tokens": 15, "total_tokens": 35 }
}
```

### 逐层拆解

| 字段 | 含义 |
|---|---|
| `choices[0].message.content` | 模型说的话（字符串） |
| `choices[0].finish_reason` | `stop` 正常结束 / `length` 撞到 max_tokens / `tool_calls` 要求调工具 |
| `usage.prompt_tokens` | 输入（含 system prompt、历史、schema）计费量 |
| `usage.completion_tokens` | 输出计费量 |

`usage` 是唯一能核对费用的地方，调试时务必打印出来。

## 四、token 是怎么算的

### 文本

中文大致 1 个字 ≈ 1 个 token（各家分词器略有差异），英文 1 个词 ≈ 0.7~1.3 个 token。不要拿"字数"估费用，拿 `usage` 的实际数字。

### 多模态

音视图不是"免费附属物"，全都要折算成 token：

| 类型 | 折算规则（以百炼为例） |
|---|---|
| 音频 | **每秒 25 token，不足 1 秒按 1 秒算** |
| 图片 | 按分辨率切块，高分辨率图可能几百到上千 token |
| 视频 | 抽帧 + 每帧按图片算 |

一条 1 小时的会议录音，光输入就是 `3600 × 25 = 90,000` token。这就是本地转写和云端转写的成本差别的来源。

## 五、流式输出

长文本一次性返回体验很差（要等十几秒）。流式用 SSE 或 WebSocket，边生成边吐：

```python
stream = client.chat.completions.create(
    model="qwen3.8-flash",
    messages=[{"role": "user", "content": "写一段 200 字的介绍"}],
    stream=True,
)
for chunk in stream:
    delta = chunk.choices[0].delta.content
    if delta:
        print(delta, end="", flush=True)
```

注意：流式下 `usage` 通常只在最后一个 chunk 里出现（需要请求时显式开启 `stream_options={"include_usage": true}`），中途拿不到完整计费信息。

## 六、踩坑清单

1. **key 泄露**——客户端硬编码 key，抓包即得。key 只放服务端环境变量。
2. **无状态误判**——以为模型记得上一轮，实际每轮都要自己拼历史，历史越长越贵。
3. **`content` 当对象用**——结构化输出场景下 `content` 仍是字符串，必须 `json.loads`。
4. **`finish_reason` 不看**——被 `length` 截断却当成正常结果用，输出字段缺失还查不出原因。
5. **地域搞混**——以为有免费额度，实际打到了国际站域名。
6. **长音频不切**——单次音频时长有上限（部分模型 5 分钟），超了直接报错或截断。
