# -*- coding: utf-8 -*-
"""
SSE 流式辅助的单元测试。
重点验证：生成器里抛异常时，不能让连接悄悄断掉，而要变成结构化的 error 事件。
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import HTTPException

from src.streaming import delta_event, guard_events, meta_event


def _parse(events):
    """把 SSE 文本事件解析成 dict，顺带校验事件格式。"""
    parsed = []
    for event in events:
        assert event.startswith("data: ")
        assert event.endswith("\n\n")
        parsed.append(json.loads(event[len("data: "):].strip()))
    return parsed


def test_normal_stream_passes_through():
    def gen():
        yield meta_event(finished=False)
        yield delta_event("你好")
        yield delta_event("，世界")

    events = _parse(list(guard_events(gen())))

    assert [e["type"] for e in events] == ["meta", "delta", "delta"]
    assert events[1]["content"] == "你好"


def test_http_exception_becomes_error_event():
    """会话不存在（404）：流已经开始，状态码改不了，只能发 error 事件。"""

    def gen():
        raise HTTPException(status_code=404, detail="面试会话不存在")
        yield  # 让函数成为生成器

    events = _parse(list(guard_events(gen())))

    assert len(events) == 1
    assert events[0]["type"] == "error"
    assert events[0]["message"] == "面试会话不存在"


def test_partial_output_is_kept_before_error():
    """上游中途断掉：已经吐出去的字要保留，后面补一个 error，而不是整条丢弃。"""

    def gen():
        yield delta_event("前半句")
        raise RuntimeError("上游连接被重置")

    events = _parse(list(guard_events(gen())))

    assert [e["type"] for e in events] == ["delta", "error"]
    assert events[0]["content"] == "前半句"
    assert "上游连接被重置" in events[1]["message"]


def test_no_spurious_error_on_clean_finish():
    """正常结束时不能凭空多出 error 事件。"""

    def gen():
        yield delta_event("完")

    events = _parse(list(guard_events(gen())))

    assert all(e["type"] != "error" for e in events)
