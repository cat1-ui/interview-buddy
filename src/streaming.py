# -*- coding: utf-8 -*-
"""
面试搭子 - SSE 流式输出辅助模块
=================================================
统一封装 SSE（Server-Sent Events）的事件格式，供流式接口复用。

事件格式：每个事件一行 "data: <json>\n\n"
事件类型（type）：
    meta   -> 元数据（先发，带结构化字段，如 finished / sources）
    delta  -> 一段文字（模型的流式输出片段）
    done   -> 结束标记
    error  -> 出错信息
"""

import json


def sse_event(event_type: str, **kwargs) -> str:
    """构造一个 SSE 事件字符串。"""
    payload = {"type": event_type, **kwargs}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def meta_event(**kwargs) -> str:
    """构造 meta 事件。"""
    return sse_event("meta", **kwargs)


def delta_event(content: str) -> str:
    """构造 delta 事件（一段文字）。"""
    return sse_event("delta", content=content)


def done_event() -> str:
    """构造 done 事件。"""
    return sse_event("done")


def error_event(message: str) -> str:
    """构造 error 事件。"""
    return sse_event("error", message=message)
