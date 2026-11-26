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

### 信封层：哪个键必填、哪个能删（2026-11-26 实测）

先看清层级，后面才不容易混：

```json
"response_format": {          // ① 协议层：请求体上的字段名，固定
  "type": "json_schema",      // ② 类型标记：固定值
  "json_schema": {            // ③ 信封：固定键名，必填
    "name": "minutes",        // ④ 标识：必填，你起名
    "strict": true,           // ⑤ 开关：可选
    "schema": { ... }         // ⑥ 模板：必填，你自由设计
  }
}
```

**真正的“返回值定义”只存在于 ⑥**，前面五个都是把模板送去服务端的包装，模型输出里一个都不会出现。

逐个删字段实测的结果（`qwen3.8-flash`、`compatible-mode/v1`）：

| 键 | 性质 | 删/改之后 | 干什么用的 |
|---|---|---|---|
| `response_format` | 固定键名 | 不加就完全没有约束，模型自由发挥 | 声明“输出要受约束” |
| `"type": "json_schema"` | **固定值** | 写成 `"json"` → `HTTP 400`，`'response_format.type' Invalid value` | 区分三档：`text` / `json_object` / `json_schema` |
| `json_schema` | 固定键名 | 删掉、把 `schema` 提到同级 → `HTTP 400`，`'response_format.json_schema' is required` | 装 `name` / `strict` / `schema` 的容器，不能省 |
| `name` | **必填** | 删掉 → `HTTP 400`，`Field required: parameters.response_format.json_schema.name` | schema 的标识，用于报错定位、日志检索、多 schema 区分 |
| `strict` | **可选** | 删掉 → `HTTP 200`，但模型行为会变（见下） | 约束是“必须”还是“建议” |
| `schema` | **必填** | 没有模板就无约束可谈 | 空白表格本体 |
| `description`（信封内） | 可选 | 删掉 → 200，无影响 | 描述整份 schema 的用途 |
| 自己乱加的键（如 `"foo": 123`） | 非法 | 实测 200，**被静默忽略** | 没有作用，别加 |

所以信封层**一个都不能少的是这四个**：`type`、`json_schema`、`name`、`schema`。`strict` 不算协议要求，但算工程必备。

> 容易混淆的一点：`required` 和 `additionalProperties` **不在信封层**，它们在 `schema` 里，属于“模板内部规矩”，下一节讲。

`name` 的规矩，规范很严、服务端很松：

| 测试写法 | 结果 |
|---|---|
| `"name": "my schema"`（带空格） | 200（OpenAI 规范不允许空格） |
| `"name": "…80 个字符…"` | 200（规范上限 64） |
| `"name": "会议纪要"`（中文） | 200（规范只允许字母数字 `_` `-`） |

别拿这个宽松当福利：`name` 只影响日志和报错的可读性，写规范格式（`meeting_minutes` 这种）换平台时才不会突然 400。

`strict` 的三种状态，差距在“模型态度”而不在结构：

| 写法 | HTTP | 同一个“试着加个 note 字段”的提示词下的输出 |
|---|---|---|
| `strict: true` | 200 | `{"a": "明天开会"}`，干净，`note` 没出现 |
| 不写 `strict` | 200 | `{"a": "整理：明天开会。备注：受 JSON schema 限制，无法额外添加 note 字段…"}` |
| `strict: false` | 200 | `{"a": "明天开会（备注：待补充）"}` |

三种情况下结构都没被破坏，但 `strict` 关掉后，约束从“解码器不许”退化成“模型自己忍着”——它会把你多要的内容硬塞进现有字段，或者干脆道歉。**所以永远显式写 `strict: true`。**

删到最简、实测仍能跑的最小形态：

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "meeting_minutes",
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

**最小形态 = `type`（固定）+ `name`（必填）+ `schema`（模板）**，再补一个 `strict: true` 是工程建议。省掉 `strict` 换来的是字段内容被污染，不划算。

### 字段级定义：每对花括号，都是一个子 schema

最容易看漏的一点：`properties` 里字段名后面那对 `{}` 不是备注，而是**这个字段自己的完整定义**，相当于把一个小 schema 挂在字段名下。里面写几条，这个字段就同时受几条约束。

```json
"title": {
  "type": "string",
  "description": "一句话标题，不超过 15 个字"
}
```

也就是说，"这对花括号里的内容都是用来描述 `title` 的"——方向对，但**性质要分清**：里面混着两种东西。

| 关键字 | 谁来读 | 性质 |
|---|---|---|
| `description` | 模型读，当成提示词 | **软约束**，不参与校验 |
| `type` | 解码器读 | 硬约束 |
| `enum` | 解码器读 | 硬约束 |
| `items` | 解码器读（仅 `array`） | 硬约束 |
| `properties` / `required` / `additionalProperties` | 解码器读（仅 `object`） | 硬约束 |

只有 `description` 是"描述"，其余都是"约束"。

### `description` 到底是什么

它是最容易被当成注释的关键字，但它不是注释：

1. **JSON 本身没有注释**。`//`、`#` 都是非法字符，写了就解析失败，`description` 是唯一合法的"说明区"
2. **它会被原样序列化进请求体，真的送到模型面前**。模型会读这段话，当成这一栏的填写要求——它其实就是"藏在 schema 里的提示词"
3. **它计入输入 token，也就是计入费用**。整份 schema 一次 200~400 token，其中相当一部分就是这些说明文字
4. **它不参与校验**。写"不超过 15 字"，模型照样可能写 50 字（实测见第五节）

同一件事，两种写法的强度差得很远：

```json
// 软：靠模型自觉，可能不守
"priority": { "type": "string", "description": "只能是 高/中/低 三选一" }

// 硬：解码器直接不给别的可能
"priority": { "type": "string", "enum": ["高", "中", "低"] }
```

实测提示词要求"填成紧急或 P0"时，带 `enum` 的那个只能输出 `"高"`——这就是硬约束和软约束的差别。

### 还能往里加别的吗

能，可以叠加，多条同时生效：

```json
"priority": {
  "type": "string",
  "description": "任务紧急程度",
  "enum": ["高", "中", "低"]
},
"tags": {
  "type": "array",
  "description": "标签，最多 3 个",
  "items": { "type": "string" },
  "maxItems": 3
},
"owner": {
  "type": "object",
  "description": "负责人",
  "properties": {
    "name": { "type": "string" },
    "dept": { "type": "string" }
  },
  "required": ["name", "dept"],
  "additionalProperties": false
}
```

三个字段各自把"类型 + 说明 + 约束"叠在一起，互不冲突；嵌套对象用的是同一套规矩。

需要注意的只有两类：一是别写 `uniqueItems`、`contains`、`minContains`、`maxContains`（会直接 400 打死请求）；二是别指望 `maxLength`、`minLength` 生效——这两类在第五节都有实测记录。

工程上的经验是**`description` 和硬约束一起写最稳**：硬约束兜住结构，`description` 补语义。像"这个字段填会议主题，不要写成一句话摘要"这种要求，只能靠文字说，`enum` 表达不了。

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

> 这段代码里到底哪一行在网络上发数据、请求报文长什么样、回来后又发生了什么，见 [一次 API 请求的完整旅程](./LLM-02-接口-一次请求的完整旅程.md)。

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

## 五、Schema 子集：哪些真约束、哪些被忽略（2026-11-26 实测）

厂商文档只写"支持 JSON Schema 子集"，但**"接受"和"生效"是两件完全不同的事**：有的关键字写进去照常 200，却一点都不约束；有的直接把请求打死。

下面这张表是实测出来的，不是文档摘抄。

测试条件：`qwen3.8-flash`、`compatible-mode/v1`、`strict: true`、非流式、`temperature: 0.3`。

| 关键字 | 写在哪 | 结果 | 怎么验证的 |
|---|---|---|---|
| `enum` | string 字段 | **强制生效** | 提示词要求填"紧急"/"P0"，输出只能是 `"高"` |
| `pattern` | string 字段 | **强制生效** | 写 `^[0-9]{1,3}$`，输出 `"202"`，中文标题被拦下 |
| `format`（如 `date`） | string 字段 | **强制生效** | 提示词明说"用中文写法、不要横杠"，仍输出 `2026-11-26` |
| `minimum` / `maximum` | number 字段 | **强制生效** | 限定 1~5，用户说"我觉得 90 分"，输出被夹成 `1` |
| `maxItems` | array 字段 | **强制生效** | 要求列 5 条待办、限 2 条，输出只有 2 条 |
| `additionalProperties: false` | object | **强制生效** | 提示词要求"额外加一个 note 字段"，结果没加 |
| `type` | 任意 | **强制生效** | 类型不符的 token 直接被解码器排除 |
| `minLength` / `maxLength` | string 字段 | **静默忽略** | `maxLength: 5` 实际输出 53 字；`minLength: 30` 实际输出 21 字，全程 200 |
| `uniqueItems` / `contains` / `minContains` / `maxContains` | array 字段 | **直接 400** | 见下方原始报错 |

`uniqueItems` 的原始报错值得原样抄下来——是**主动拒绝**，不是忽略：

```
HTTP 400  invalid_parameter_error
When the schema contains the fields "uniqueItems", "contains", "minContains",
or "maxContains", the type should not be "array".
```

还有一条常被当成铁律的说法，实测被推翻：**根节点不必是 `object`**。

把 schema 写成 `{"type":"array","items":{"type":"string"}}`，服务端正常返回：

```json
["测试完成", "上线评审通过", "文档补齐"]
```

`json.loads` 出来直接是 list，没有任何问题。

不过工程上仍建议根节点用 `object` 包一层（`{"items":[...]}` 而不是裸数组）：将来要加 `title`、`updated_at` 这类元信息时不用改协议，兼容成本更低。

### 这张表怎么用

1. **能用硬约束就别靠提示词**：`enum`、`pattern`、`format`、`minimum`、`maxItems` 都是真的，比在 `description` 里写"不超过 15 字"强得多
2. **长度类约束只能靠 `description`**：`maxLength` 是空头承诺，写了也只是给模型看的建议
3. **别写 `uniqueItems`**：一个关键字就能让整个请求 400
4. **换模型或换平台后重新测一遍**：这张表是 `qwen3.8-flash` 的口径，不同模型背后的约束解码器实现不一样

复现方法很简单：同一个提示词、只改 schema 里的一个关键字，跑两遍对比输出。比如想验 `maxLength`，就故意让模型写长一点，看它敢不敢超。

> 本机还留着一个无界面的最小示例 `llm_structured_demo.py`（`--dry-run` 只打印请求体、不出网），专门用来做这类对照实验。

### 顺便：HTTP 200 和 400 差在哪

调 schema 时会频繁撞见这两个码，含义完全不同：

| | 200 OK | 400 Bad Request |
|---|---|---|
| 谁出的问题 | 没有，一切正常 | **请求本身不合法**，在你这一侧就错了 |
| 模型跑了吗 | 跑了 | **完全没跑**，服务端校验阶段就退了回来 |
| 响应体长什么样 | `{"choices":[...],"usage":{...}}` | `{"error":{"message":"...","code":"..."}}`，**没有 `choices`** |
| 该做什么 | 解析 `choices[0].message.content` | 读 `error.message` 改请求，**不要解析 `choices`** |

一句话：**200 是“模型答完了”，400 是“你的请求没通过体检”。**

`400` 是 schema 类问题最常见的出口，报错通常精确到字段：

```
Field required: parameters.response_format.json_schema.name
'response_format.json_schema' is required when 'response_format.type' is 'json_schema'
'response_format.type' Invalid value: 'json'
Format error : the specific reason is as follows: When the schema contains the
fields "uniqueItems", ...
```

这四句前面都实测拿到过，它们直接点名哪一层缺了什么，比猜测快得多。

另外两个容易混的码：

- **401**：key 不对（实测过，返回 `invalid_api_key`）。跟 schema 无关，是身份问题
- **429**：限流或额度问题。唯一值得等待重试的 4xx

工程上的判断顺序固定：**先看 `status`，不是 200 就直接打印 `error.message` 退出；只有 200 才去动 `choices`。** 反过来写（先 `json.loads` 再取 `choices`）在 400 时会抛 `KeyError`，把真正的原因盖掉。

## 六、两个容易搞混的问题

### schema 是用户自定义的吗？

是。schema 完全由你自己定义，但受上面那几条子集限制。做法上不要每次请求都现写，而是在代码里定义成常量复用——因为 **schema 本身计入输入 token**，一次 200~400 token，反复手拼既费钱又容易写错。

### 每次 POST 都要重新传一遍吗？

要。Chat Completions 是无状态接口，服务端不记得你上次传了什么，所以每次请求体都必须带上完整 schema。

好消息是**固定内容可以吃缓存折扣**：把 schema 和 system prompt 放在请求最前面，命中前缀缓存后这部分几乎不花钱（详见《Token 计费与缓存》）。

## 七、最后的保险

即使 schema 保证了格式合法，也**不等于内容合法**。返回的 `todos` 可能是空数组、日期可能是 `"明天"` 这种字符串。

所以本地仍然要做一次业务校验（Pydantic、手写校验、正则都行）。schema 负责"形状对不对"，你的代码负责"内容能不能用"，这两件事永远不能合并。
