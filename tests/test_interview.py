# -*- coding: utf-8 -*-
"""
InterviewService 的单元测试。
用 fake client + fake embed_fn 验证面试状态机，不触网、不真实调用模型。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vector_store import VectorStore
from src.interview import InterviewService, MAX_QUESTIONS, MAX_FOLLOWUPS


SCORE_JSON = '{"准确性": 8, "深度": 7, "表达清晰度": 9, "总评": "表现不错"}'


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class FakeCompletions:
    def __init__(self, question="请解释什么是 RAG？", reply="很好，我们继续。"):
        self._question = question
        self._reply = reply
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = " ".join(m.get("content", "") for m in kwargs.get("messages", []))
        # 出题 prompt 里带"请出一道"；打分 prompt 里带"JSON 格式"；其余是回应
        if "请出一道" in text:
            return _Response(self._question)
        if "JSON 格式" in text:
            return _Response(SCORE_JSON)
        return _Response(self._reply)


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, question="请解释什么是 RAG？", reply="很好，我们继续。"):
        self.chat = FakeChat(FakeCompletions(question, reply))


class _FakeRag:
    """只提供 vector_store 属性的最小替身，避免构造真实 OpenAI 客户端。"""

    def __init__(self, vector_store):
        self.vector_store = vector_store


def _make_service():
    client = FakeClient()
    vs = VectorStore()
    svc = InterviewService(
        _FakeRag(vs),
        client=client,
        embed_fn=lambda text: [1.0, 0.0],  # fake embedding，不触网
    )
    return svc, client


def test_new_session_and_start_question():
    svc, _ = _make_service()
    sid = svc.new_session()
    assert sid in svc.sessions

    q = svc.start_question(sid)
    assert q == "请解释什么是 RAG？"

    session = svc.sessions[sid]
    assert session.question_count == 1
    assert session.followup_count == 0
    assert session.current_question == q
    assert session.finished is False


def test_followup_twice_then_advance_to_next_question():
    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)

    r1 = svc.answer(sid, "我大概知道一点")
    assert r1["finished"] is False
    assert r1["followup_count"] == 1

    r2 = svc.answer(sid, "还有更深的理解")
    assert r2["followup_count"] == 2  # 追问满 MAX_FOLLOWUPS 次

    r3 = svc.answer(sid, "就这些了")
    assert r3["finished"] is False
    assert r3["question_count"] == 2  # 换题，进入第 2 题
    assert r3["followup_count"] == 0  # 新题追问计数归零


def test_give_up_comfort_and_next_question():
    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)

    r = svc.answer(sid, "我不知道")
    assert r["finished"] is False
    assert r["question_count"] == 2  # 安抚后换题
    assert "请解释什么是 RAG？" in r["reply"]  # 回复里带出了下一题


def test_last_question_farewell():
    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)

    # 用 4 次"不知道"把题目推进到第 5 题
    for _ in range(4):
        r = svc.answer(sid, "不知道")
        assert r["finished"] is False

    session = svc.sessions[sid]
    assert session.question_count == MAX_QUESTIONS

    # 第 5 题认真回答 -> farewell 正常收尾
    r = svc.answer(sid, "RAG 是检索增强生成，结合检索与生成")
    assert r["finished"] is True
    assert r["question_count"] == MAX_QUESTIONS
    session = svc.sessions[sid]
    assert session.finished is True
    assert session.completed is True


def test_looks_like_give_up():
    svc, _ = _make_service()
    assert svc._looks_like_give_up("我不知道") is True
    assert svc._looks_like_give_up("这个真没学过") is True
    assert svc._looks_like_give_up("RAG 是检索增强生成") is False


def test_finish_parses_score_json():
    svc, _ = _make_service()
    sid = svc.new_session()
    # 没答满就结束 -> 走不完整面试的简评分
    score = svc.finish(sid)

    assert score["准确性"] == 8
    assert score["深度"] == 7
    assert score["表达清晰度"] == 9
    assert score["总分"] == 8.0  # (8+7+9)/3
    assert score["不完整面试"] is True


def test_collect_question_uses_stable_source_key(monkeypatch):
    from src import bank as bank_mod

    calls = []

    def fake_add(question, dialogue, category="", topic="", source_key="", db_path=None):
        calls.append(source_key)
        return 42, True

    monkeypatch.setattr(bank_mod, "add_question", fake_add)

    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)

    qid = svc.collect_question(sid)
    assert qid == 42
    # 默认收藏当前题，source_key 用当前题序号，供题库去重
    assert calls == [f"{sid}:1"]