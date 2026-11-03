# Echo 情感陪伴智能体 · 完整项目讲解（面试复盘版）

> 这份文档的目标：让你**彻底看懂自己的项目**，能对着面试官讲清楚每一个技术细节。
> 每一节都分「大白话」和「对应真实代码」两部分，代码就是你项目里实际写的。

---

## 0. 一句话说清楚这个项目

> **Echo 是一个基于 DeepSeek 大模型的情感陪伴聊天应用，能记住用户、识别情绪、调用工具（查天气/算数/查时间），用 Streamlit 做网页界面。**

技术栈：Python + DeepSeek API（openai 库）+ SQLite + Streamlit

---

## 1. 最核心的思想（先记住这个，其他都好懂）

**大模型是"失忆的、无状态的"。**

它不记得你是谁、不知道现在几点、不会查天气、不会算数。它只会一件事：**你喂给它一段文字，它生成一段文字。**

所以整个项目的本质就是一句话：

> **每次对话前，把该给它的信息（人设、记忆、时间、历史），全部打包塞进提示词，再让它回答。**

理解了这句话，你就能理解项目里所有功能为什么这么设计。

---

## 2. 一次对话的完整流程（面试必问，务必背下来）

这是**最重要的一个问题**。面试官几乎一定会问："用户发一句话，到收到回复，中间发生了什么？"

**大白话版（7 步）：**

1. 用户发消息 → 先把这句话存进数据库（messages 表）
2. 从数据库取出三样东西：长期记忆、对话摘要、最近 10 条聊天记录
3. 把这三样 + 人设 + 当前时间，拼成一段"提示词"
4. 带着"工具说明书"调用大模型，问它"要不要用工具？"
5. 如果模型"举手"要用工具 → 我的代码真正执行工具（算数/查天气），把结果喂回给模型
6. 模型基于所有信息，流式生成最终回复（一个字一个字蹦出来）
7. 后台线程悄悄做杂活：提取新记忆、识别情绪、可能做摘要

**对应真实代码（`chat_service.py` 的 `stream_message`）：**

```python
def stream_message(self, user_text):
    # 第1步：存用户消息
    db.save_message(self.conversation_id, "user", user_text)

    # 第2步：取记忆 + 摘要 + 历史
    memories = db.get_memories()
    summary = db.get_latest_summary(self.conversation_id)
    history = db.get_recent_messages(self.conversation_id, limit=10)

    # 第3步：拼 system prompt
    system_prompt = build_system_prompt(memories, summary)
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        messages.append({"role": msg["role"], "content": msg["content"]})

    # 第4步：第一次调用，判断要不要用工具
    first = self.client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.8,
        tools=tools.TOOLS,  # 工具说明书
    )
    first_msg = first.choices[0].message

    # 第5步：模型举手了？执行工具
    if first_msg.tool_calls:
        tool_call = first_msg.tool_calls[0]
        func_name = tool_call.function.name
        func_args = json.loads(tool_call.function.arguments or "{}")
        tool_result = tools.run_tool(func_name, func_args)
        # 把"举手 + 工具结果"加回消息
        messages.append(first_msg)
        messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": tool_result})

    # 第6步：第二次调用，流式生成最终回复
    response = self.client.chat.completions.create(
        model="deepseek-chat",
        messages=messages,
        temperature=0.8,
        stream=True,  # 流式
    )
    for chunk in response:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta  # 一个字一个字吐出来
```

**注意：你的项目【没有】分词、向量化、embedding、RAG 检索！** 你用的是"把历史消息原文塞进提示词"，不是向量检索。这个一定要分清楚，面试说错了会被追问到卡壳。

---

## 3. 多轮对话是怎么实现的？

**大白话：** 模型没有记忆，你每次问它都当第一次见你。怎么办？**把"最近 10 条聊天记录"重新发给它**，它就"接得上话"了。

**为什么只发最近 10 条，不是全部？**
- 发太多 → 费钱（token 要花钱）、可能超过模型的长度上限
- 发 10 条 → 成本和效果之间取个平衡

**对应代码（`db.py` 的 `get_recent_messages`）：**

```python
def get_recent_messages(conversation_id, limit=10):
    cursor.execute(
        "SELECT role, content FROM messages "
        "WHERE conversation_id=? ORDER BY id DESC LIMIT ?",
        (conversation_id, limit),
    )
    rows = cursor.fetchall()
    rows = list(rows)[::-1]  # 倒过来，变成"旧→新"
    return [{"role": r["role"], "content": r["content"]} for r in rows]
```

---

## 4. 长期记忆是怎么提取和使用的？（面试必问）

这是你之前说"不记得了"的部分，现在彻底讲清楚。

### 4.1 记忆是怎么"提取"的？

**大白话：** 让大模型自己干"提取"这件事。

用户说"我叫小袁，喜欢打篮球" → 你**再额外调一次模型**，给它一个专门的提示词："请从这句话里提取值得记住的信息，只输出 JSON" → 模型返回：

```json
[
  {"key": "名字", "value": "小袁", "category": "基本信息", "confidence": 0.9},
  {"key": "爱好", "value": "打篮球", "category": "喜好", "confidence": 0.8}
]
```

然后把这个 JSON 存进 `memories` 表。

**为什么不让代码写规则提取（比如 if "叫" in 句子）？** 因为规则又蠢又漏，而大模型擅长理解语言，提取又快又准。

**对应代码（`memory_service.py`）：**

```python
def extract_memories(self, user_text, assistant_text):
    prompt = EXTRACT_PROMPT.format(user_text=user_text, assistant_text=assistant_text)
    response = self.client.chat.completions.create(
        model="deepseek-chat",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,  # 提取要稳定
    )
    raw = response.choices[0].message.content
    return self._parse_json(raw)  # 解析成列表
```

### 4.2 记忆是怎么"使用"的？

**大白话：** 下次对话时，把记忆拼进提示词，模型就"记得"你了。

**对应代码（`prompt_builder.py` 的 `build_system_prompt`）：**

```python
if memories:
    memory_lines = []
    for m in memories:
        memory_lines.append(f"- {m['key']}：{m['value']}（{m['category']}）")
    memory_text = "\n".join(memory_lines)
    parts.append(f"\n以下是关于用户的长期记忆，请自然运用：\n{memory_text}")
```

### 4.3 记忆 vs 聊天记录（一定要分清楚）

| 类型 | 存哪张表 | 特点 |
|------|---------|------|
| 长期记忆 | memories | 稳定信息（我叫小袁），永久保存，跨会话 |
| 聊天记录 | messages | 临时上下文（上一句说啥），用完就忘 |

---

## 5. 对话摘要是怎么做的？

**大白话：** 聊太长了，把旧内容"压缩"成 100 字摘要，之后只发"摘要 + 最近 10 条"，省钱又不丢早期信息。

**关键设计：增量摘要** —— 每满 20 条，只总结"上次摘要之后新增的那批"，不重复总结旧内容。

**对应代码（`summary_service.py` 的 `maybe_summarize`）：**

```python
def maybe_summarize(conversation_id, summary_service):
    total = db.count_messages(conversation_id)          # 当前总共几条
    latest = db.get_latest_summary_info(conversation_id) # 上次摘要到哪了
    last_pos = latest["last_message_id"] if latest else 0

    if total - last_pos < SUMMARY_INTERVAL:  # 没满20条，不做
        return
    # 只取"上次之后新增的"消息来总结
    new_messages = db.get_messages_range(conversation_id, last_pos, 999999999)
    summary_text = summary_service.generate_summary(new_messages)
    db.save_summary_with_pos(conversation_id, summary_text, max_id)
```

---

## 6. Function Calling 是什么？原理？（面试必问）

这是你的一个亮点，要讲透。

### 6.1 大白话原理

模型只会"说话"，不会"做事"。Function Calling 就是给模型一份**"工具说明书"**，让它遇到该用工具的事时，**不瞎编答案，而是"举手"返回一段 JSON，告诉你"我想调用 XX 函数，参数是 YY"**。然后**你的代码**真正去执行这个函数，把结果喂回模型，模型再组织成自然语言回答。

一句话：**模型是"大脑"（判断+说话），工具函数是"手"（你的代码真正干活）。**

### 6.2 举个完整例子

用户问："帮我算 12345 × 67890"

1. 模型看到问题，发现这是算数（它不擅长），于是"举手"返回 JSON：
   ```json
   {"name": "calculate", "arguments": {"expr": "12345*67890"}}
   ```
2. 你的代码 `run_tool("calculate", {"expr": "12345*67890"})` 真正执行 `eval("12345*67890")`，得到结果
3. 把结果喂回模型，模型说："12345 乘以 67890 等于 838102050"

### 6.3 对应代码（`tools.py`）

```python
TOOLS = [  # 工具说明书
    {
        "type": "function",
        "function": {
            "name": "calculate",
            "description": "计算数学表达式",
            "parameters": {
                "type": "object",
                "properties": {"expr": {"type": "string", "description": "表达式"}},
                "required": ["expr"],
            },
        },
    },
    # ... 还有 get_time、get_weather
]

def run_tool(func_name, func_args):
    if func_name == "calculate":
        return calculate(func_args.get("expr", ""))
    if func_name == "get_time":
        return get_time()
    if func_name == "get_weather":
        return get_weather(func_args.get("city", ""))
```

### 6.4 一个安全亮点：计算器防代码注入

`calculate` 里用了 `eval`，而 `eval` 很危险（能执行任意代码）。你的防护是**白名单正则**：

```python
_SAFE_PATTERN = re.compile(r"^[\d\s+\-*/().]+$")

if not _SAFE_PATTERN.match(expr):
    return "表达式包含非法字符，已拒绝执行"  # 不是纯算式，直接拒
```

只允许数字、空格、`+-*/()`，其他任何字符（字母、引号等）都拒绝。这样就算模型返回了恶意内容，也执行不了。**这是很多新手不会想到的安全意识，面试讲出来很加分。**

---

## 7. 流式输出 + 异步（体验优化）

### 7.1 流式输出（打字机效果）

**大白话：** 普通方式是"等模型生成完一整段，一次性显示"。流式是"模型边生成，你边收到，边显示"，像打字机。

**关键：`stream=True` + 生成器 `yield`**

```python
response = self.client.chat.completions.create(..., stream=True)
for chunk in response:
    delta = chunk.choices[0].delta.content  # 这次新增的一小段
    if delta:
        yield delta  # 吐出去一小段
```

`yield` 让函数变成"挤牙膏"——每收到一小段就吐一小段，不是一次全给。

### 7.2 异步（后台线程）

**大白话：** 记忆提取、情绪识别这些"杂活"，放到后台线程做，不耽误你看到回复。

```python
threading.Thread(
    target=self._handle_post_tasks,
    args=(user_text, full_reply),
    daemon=True,  # 守护线程，主程序退出自动结束
).start()
```

---

## 8. 情绪识别 + 情绪洞察

### 8.1 情绪识别

**大白话：** 每次你发消息，额外调一次模型，判断你是"开心/平静/难过/焦虑"里的哪种，存进 `emotions` 表。

### 8.2 情绪洞察（让数据活起来）

把情绪记录画成图 + 让模型总结：
- **趋势图**：把情绪映射成分值（开心=2、平静=0、难过=-2、焦虑=-1），按天聚合画折线
- **饼图**：四种情绪各占多少
- **文字洞察**：让模型说一句"你最近焦虑有点多，是不是压力大？"

---

## 9. 安全兜底（体现责任感）

**大白话：** 检测到用户说"不想活了"这种极端信号，在回复末尾追加一段安全引导（"我很担心你，可以联系信任的人或心理热线……"）。

**关键设计：只识别极端风险**，不把"好烦、压力大"误判成危险——避免过度干预，把握陪伴的分寸。

---

## 10. 温度 temperature 梯度（体现你懂参数）

| 任务 | 温度 | 为什么 |
|------|------|--------|
| 聊天 | 0.8 | 要活泼、像真人 |
| 情绪洞察 | 0.6 | 有温度但不啰嗦 |
| 摘要 | 0.3 | 要稳定 |
| 记忆/情绪提取 | 0.2 | 要精确 |
| 风险判断 | 0.1 | 要最保守，别乱触发 |

**一句话：温度越低，模型越"老实、稳定"；越高越"活泼、随机"。不同任务用不同温度。**

---

## 11. 让模型稳定输出 JSON 的三层防线

模型输出 JSON 时经常加废话、格式乱。你的防护：

1. **prompt 里强调**："只输出 JSON，别的别说"
2. **解析时清洗**：去掉 ```json 代码块包裹
3. **兜底**：解析失败就返回空列表，宁可不存，不让程序崩

---

## 12. 你可能被追问的"为什么"（提前准备）

面试官会顺着项目问，这里帮你准备好答案：

| 追问 | 你的答案 |
|------|---------|
| 为什么用 SQLite 不用 MySQL？ | 单用户、轻量，SQLite 是个文件、零部署；MySQL 要装服务器，杀鸡用牛刀 |
| 记忆为什么全局共享、历史按会话隔离？ | 记忆是"你是谁"（跨会话稳定），历史是"这次聊了啥"（每个会话独立） |
| 为什么副任务要异步？ | 记忆、情绪这些杂活不阻塞主回复，用户体验更好 |
| 为什么每个副功能包 try/except？ | 非核心功能出错，不能影响用户正常收到回复 |
| 流式和普通调用区别？ | 普通=等全部生成完再返回；流式=边生成边返回，用 stream=True + yield |

---

## 13. 你现在必须纠正的一个认知

你之前把"一次对话"说成了"分词→向量化→embedding→RAG检索"，这是**错的**。

**你的项目【没有】RAG、没有向量化、没有 embedding。**

你用的是最直接的"把历史消息原文塞进提示词"。这个技术叫"上下文窗口内管理"，不是"向量检索"。

如果面试被问"你用了 RAG 吗"，要诚实说"没有，我目前是把历史消息直接放进上下文，RAG 是我下一步想做的方向"。**诚实 + 说出下一步规划，反而加分。**

---

## 14. 给自己打分（验收标准）

你要能**不翻文档、流畅讲出来**这 5 个问题，才算真正懂了：

1. 一次对话从发消息到回复，经历了哪几步？
2. 长期记忆是怎么提取、怎么使用的？
3. Function Calling 的原理是什么？模型怎么"举手"？
4. 多轮对话是怎么实现的？为什么只发最近 10 条？
5. 流式输出是怎么做的？yield 是什么？

**任何一个卡壳，就回到对应章节再看一遍。**

---

*文档生成时间：2026-10-22*
