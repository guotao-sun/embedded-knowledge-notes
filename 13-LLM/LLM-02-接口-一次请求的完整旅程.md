# 一次 API 请求的完整旅程

> 拿一段最典型的 `json_schema` 调用代码，逐块拆开，看清哪一行真的在网络上传数据。

## 一、结论先放前面

```python
resp = client.chat.completions.create(   # ← 唯一会走网络的语句
    ...
)
```

这段代码里，**真正"上网"的只有这一行**。其余全是本地动作：拼参数、拼请求体、以及收到结果后的解析。

一个容易被忽略的点：`OpenAI(...)` 那一行**本身不连网**。它只是把 base_url、key、超时、重试策略存进一个对象里，真正的 TCP/TLS 连接是在第一次调用 `create()` 时才建立的。换句话说，构造客户端是纯本地操作。

## 二、完整代码

```python
# 最小示例：让模型只返回 {title, todos} 两个字段
import os, json
from openai import OpenAI

client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],   # 百炼的 key
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",  # O系兼容入口
)

resp = client.chat.completions.create(
    model="qwen3.8-flash",
    messages=[
        {"role": "user", "content": "帮我整理：今天和 A 讨论下周上线，B 负责测试，周五前给结论。"}
    ],
    response_format={
        "type": "json_schema",
        "json_schema": {
            "name": "minutes",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "todos": {"type": "array", "items": {"type": "string"}}
                },
                "required": ["title", "todos"],
                "additionalProperties": False
            }
        }
    },
)

print(resp.choices[0].message.content)   # 注意：这是一段字符串，不是 dict
data = json.loads(resp.choices[0].message.content)
print(data["title"], data["todos"])
```

## 三、逐块拆解

### 第 1 块：客户端配置（本地）

```python
client = OpenAI(
    api_key=os.environ["DASHSCOPE_API_KEY"],
    base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
)
```

- `os.environ[...]` 从环境变量读 key，本机读取，不联网
- `base_url` 决定请求发往哪个地址。SDK 内部拼路径的规则是 `base_url + "/chat/completions"`，所以最终实际打的是 `.../compatible-mode/v1/chat/completions`
- key 不硬编码在代码里是工程规范，不是技术必需

### 第 2 块：要说什么（本地）

```python
messages=[
    {"role": "user", "content": "帮我整理：今天和 A 讨论下周上线，B 负责测试，周五前给结论。"}
]
```

就是一个 Python 列表。`role` 常见取值只有 user / assistant / system。注意这里**没有历史消息**——Chat Completions 是无状态的，想让模型"记得"上一轮，必须自己把上一轮塞进来。

> `messages` 的完整规则（四种 role、多模态 content、上一轮历史的回填写法、历史管理与成本），见 [messages 与多轮对话](./LLM-03-对话-messages与多轮对话.md)。

### 第 3 块：要求什么格式（本地）

```python
response_format={
    "type": "json_schema",
    "json_schema": {
        "name": "minutes",
        "strict": True,          # 严格模式：字段不多不少
        "schema": {...}          # 真正的字段定义
    }
}
```

这整块也只是个字典，在本机拼好。它的作用是**随请求一起发给服务端**，让服务端的解码器按这个结构限制输出。所以它不是"提示词"，而是解码约束——这也是为什么这里不用写"请返回 JSON"。

### 第 4 块：真正发生的事（网络）

`create()` 内部做了三件事：

1. 把上面所有参数**序列化成 JSON 字符串**
2. 带上 `Authorization: Bearer <key>` 头，向 base_url 发 **HTTP POST**
3. 等响应回来，把 JSON **反序列化**成 `ChatCompletion` 对象，赋给 `resp`

同步客户端在这一步是阻塞的，程序卡在这儿等网。

## 四、那一次请求的原始样子

```http
POST /compatible-mode/v1/chat/completions HTTP/1.1
Host: dashscope.aliyuncs.com
Authorization: Bearer sk-xxxxxxxx
Content-Type: application/json

{
  "model": "qwen3.8-flash",
  "messages": [{"role":"user","content":"帮我整理：今天和 A 讨论下周上线，B 负责测试，周五前给结论。"}],
  "response_format": {
    "type": "json_schema",
    "json_schema": {"name":"minutes","strict":true,"schema":{...}}
  }
}
```

**你的数据就是在这个 body 里离开本机的**——用户那句话、schema、model 名，全部装进这一个 JSON 一起走。这也顺带解释了两件事：

- 隐私上云传的其实就是这个 body
- schema 之所以要算钱，是因为它确实作为输入内容被发出去了

## 五、回来之后（本地）

```python
print(resp.choices[0].message.content)
```

这一步**不联网**。`resp` 已经是本机内存里的对象，`.choices[0].message.content` 只是属性访问。

```python
data = json.loads(resp.choices[0].message.content)
```

`content` 的类型是 **str**，内容长这样：

```
'{"title":"下周上线讨论","todos":["B 负责测试","周五前给结论"]}'
```

它长得像 JSON，但只是文本。`json.loads` 把这个字符串**解析**成 Python 字典，纯本地 CPU 运算。不做这一步，`data["title"]` 就无从谈起——这是最容易漏的一步。

## 六、想亲眼看到"什么时候发的"

| 办法 | 做法 | 能看到什么 |
|---|---|---|
| 打日志 | 给底层 httpx 客户端挂钩子，打印 `r.url` 和 `r.content` | 完整 URL 和请求体 |
| 看响应头 | `resp._response.headers` 里的 `x-request-id` 与耗时 | 证明是一次真实往返 |
| 抓包 | Wireshark / Fiddler 过滤 `dashscope.aliyuncs.com:443` | 只能看到 TLS 密文流量 |

最省事的判断标准：**把网线拔了，只有 `create()` 那行会报错**，其余照跑不误。

## 七、这段代码里三个隐性成本

1. **`messages` 是全新的**，没复用任何前缀，所以这次 100% 缓存未命中
2. **schema 那 200 多 token 每次都要重发**，量大了就是纯浪费——固定内容应放最前以命中缓存
3. **没设 `max_tokens`**，模型可以一直说到上限才停，超长输出按输出价计费

## 八、语法细节提醒

```python
print(data["title"], data["todos"])   # 少一个右括号会直接 SyntaxError
```

括号成对、`json.loads` 的返回值才可用，这两个都是调试时最常见的低级错误来源。
