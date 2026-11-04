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
import logging

from fastapi import HTTPException

logger = logging.getLogger("uvicorn.error")


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


def guard_events(source):
    """
    把生成器抛出的异常翻译成 error 事件，而不是让它掀掉整条连接。

    为什么必须有：SSE 一旦开始发送（200 + 第一段数据），状态码就改不了了。
    如果生成器里抛 HTTPException，客户端只会看到"连接被掐断"——
    404 变成"空响应"、502 变成"网络错误"，前端连提示都没法给。

    所以约定：**流式接口内部不要指望 raise 变成状态码**。
    真正需要状态码的校验（会话不存在、已结束、知识库构建中）要在
    构造 StreamingResponse 之前就做完；已经开始推流之后出的问题，
    一律走这里转成 error 事件。

    用法：
        StreamingResponse(guard_events(svc.answer_stream(...)), ...)
    """
    try:
        yield from source
    except HTTPException as exc:
        # 业务错误（404 会话不存在 / 409 已结束 / 502 上游失败）：直接给前端可读文案
        logger.warning(f"[SSE] 流式过程中断（HTTPException {exc.status_code}）：{exc.detail}")
        yield error_event(str(exc.detail))
    except Exception as exc:  # noqa: BLE001 - 流式接口不能把异常漏给 ASGI 层
        logger.exception("[SSE] 流式过程中出现未预期异常")
        yield error_event(f"服务异常：{exc}")
