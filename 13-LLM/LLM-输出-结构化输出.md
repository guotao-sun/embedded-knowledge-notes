# 大模型结构化输出（JSON）

## 一、为什么需要结构化输出

### 问题

让模型"返回一段 JSON"，然后在程序里 `json.loads` ——这是最常见的做法，也是最容易崩的做法。

原因有两个：

1. 模型可能给你包一层 ```json 代码块，或者前面加一句"好的，结果如下："
2. 字段名可能这次叫 `title`，下次叫 `标题`

程序解析失败率通常在 1%~5%，量一上来就是天天报警。

### 解决思路：把约束从"提示词"搬到"接口参数"

分两档约束强度：

| 模式 | 做法 | 保证什么 | 失败方式 |
|---|---|---|---|
| 软约束（提示词） | 在 prompt 里写"只输出 JSON" | 大概率的 JSON | 偶尔多话、字段名漂移 |
| 硬约束（Schema） | 把 JSON Schema 传给 API | 100% 合法、字段齐全 | 模型不支持则直接报错 |

硬约束的原理是**受约束解码（constrained decoding）**：服务端在每一步采样时，把不符合 schema 的候选 token 直接置为不可选，逐步把输出"逼"进合法结构里。不是模型更听话了，是解码器不让它乱写。

## 二、`response_format` 的三种档位

OpenAI 生态里的写法：

```json
"response_format": { "type": "text" }          // 不管，默认
"response_format": { "type": "json_object" }   // 给合法 JSON，不管字段
"response_format": { "type": "json_schema", "json_schema": { ... } }  // 给指定字段
```

### `json_object` 的坑

这一档有个硬性要求：**提示词里必须出现 "JSON" 这个词**，否则直接 400：

```
'messages' must contain the word 'json' in some form
```

而且它只保证"是能解析的 JSON"，不保证字段名、不保证必填项。等于把结构约定仍交给了提示词，只是帮你挡住了格式错误。

### `json_schema` 的结构

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "minutes",
    "strict": true,
    "schema": {
      "type": "object",
      "properties": {
        "title": { "type": "string" },
        "todos": { "type": "array", "items": { "type": "string" } }
      },
      "required": ["title", "todos"],
      "additionalProperties": false
    }
  }
}
```

三个必须理解的点：

- `name`：schema 的名字，随便起，仅用于标识
- `strict: true`：字段一个不多一个不少
- `additionalProperties: false`：禁止模型自由发挥加字段——**这条不写，模型经常给你加一个 `notes`**

## 三、完整可跑示例

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

# 关键：content 是一段字符串，不是 dict
print(resp.choices[0].message.content)
data = json.loads(resp.choices[0].message.content)
print(data["title"], data["todos"])
```

返回体里的 content 实际是：

```json
"content": "{\"title\":\"下周上线讨论\",\"todos\":[\"B 负责测试\",\"周五前给结论\"]}"
```

注意那些转义的反斜杠——它只是一串文本，长得像 JSON 而已。

> 这段代码里到底哪一行在网络上发数据、请求报文长什么样、回来后又发生了什么，见 [一次 API 请求的完整旅程](./LLM-接口-一次请求的完整旅程.md)。

## 四、各家写法对照

同样是"给个 schema"，四家的写法完全不同：

| 平台 / 引擎 | 写法 | 备注 |
|---|---|---|
| OpenAI | `response_format={"type":"json_schema",...}` | 行业标准 |
| 阿里百炼（Qwen） | 兼容 OpenAI 写法，部分参数走 `extra_body` | 用官方 SDK 时字段位置会变 |
| 阿里 DashScope 原生 API | `response_format` 放在 `parameters` 对象里 | schema 要手写，部分语言 SDK 不支持 |
| 阿里 Responses API | 改叫 `text.format` | 字段名又不一样了 |
| vLLM 本地部署 | `guided_json=<schema>` | 走后端 sampler |
| llama.cpp | GBNF 语法文件 | 完全另一套，要先把 schema 翻译成语法 |
| Anthropic | 没有原生 JSON Schema | 通常用 tool 定义来"冒充" |

所以换平台前只需查四件事：

1. 参数放在哪一层（顶层 / `parameters` / `extra_body`）
2. 支持哪些 schema 子集
3. 是否支持流式
4. 失败时返回什么错误码

建议把"schema 能否被接受"做成启动自检，别等线上第一批请求才发现模型不支持。

## 五、Schema 的边界与限制

JSON Schema 标准很大，但模型厂商只实现了子集，实际可用范围通常限制在：

- 根节点必须是 `object`
- 每个 `properties` 里的字段都建议列进 `required`
- **不支持递归结构**
- `pattern`、`format`、`minimum` 之类常常被忽略（写了也不校验，只是不报错）
- 嵌套层级过深容易触发服务端错误

所以工程上的经验是：**schema 越扁平越稳**。深嵌套不如拆成两次调用。

## 六、两个容易搞混的问题

### schema 是用户自定义的吗？

是。schema 完全由你自己定义，但受上面那几条子集限制。做法上不要每次请求都现写，而是在代码里定义成常量复用——因为 **schema 本身计入输入 token**，一次 200~400 token，反复手拼既费钱又容易写错。

### 每次 POST 都要重新传一遍吗？

要。Chat Completions 是无状态接口，服务端不记得你上次传了什么，所以每次请求体都必须带上完整 schema。

好消息是**固定内容可以吃缓存折扣**：把 schema 和 system prompt 放在请求最前面，命中前缀缓存后这部分几乎不花钱（详见《Token 计费与缓存》）。

## 七、最后的保险

即使 schema 保证了格式合法，也**不等于内容合法**。返回的 `todos` 可能是空数组、日期可能是 `"明天"` 这种字符串。

所以本地仍然要做一次业务校验（Pydantic、手写校验、正则都行）。schema 负责"形状对不对"，你的代码负责"内容能不能用"，这两件事永远不能合并。
