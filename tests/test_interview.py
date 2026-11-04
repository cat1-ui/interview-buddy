# -*- coding: utf-8 -*-
"""
InterviewService 的单元测试。
用 fake client + fake embed_fn 验证面试状态机，不触网、不真实调用模型。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vector_store import VectorStore
from src.interview import InterviewService, MAX_QUESTIONS, MAX_FOLLOWUPS, SESSION_TTL


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

    def _extract_answer(self, text):
        """从 V2 判断 prompt 里抠出"候选人回答"部分，用于模拟放弃判断。"""
        marker = "候选人回答："
        idx = text.find(marker)
        if idx == -1:
            return text
        rest = text[idx + len(marker):]
        end = rest.find("判断规则")
        if end != -1:
            rest = rest[:end]
        return rest

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = " ".join(m.get("content", "") for m in kwargs.get("messages", []))
        # 出题 prompt 里带"请出一道"；放弃判断带"give_up"；打分 prompt 带"JSON 格式"；其余是回应
        if "请出一道" in text:
            return _Response(self._question)
        if "give_up" in text:
            answer = self._extract_answer(text)
            give_up = any(k in answer for k in ("不知道", "不会", "没学过", "想不起来", "不清楚", "不了解"))
            if give_up:
                return _Response('{"give_up": true, "reply": "没关系，我们看下一题"}')
            return _Response('{"give_up": false, "reply": "那你展开说说原理？"}')
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
    vs.add(
        texts=["RAG 是检索增强生成", "Agent 可自主调用工具", "Prompt 工程优化提示词"],
        metadatas=[
            {"filename": "kb.md"},
            {"filename": "kb.md"},
            {"filename": "kb.md"},
        ],
        vectors=[[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
    )
    svc = InterviewService(
        _FakeRag(vs),
        client=client,
        embed_fn=lambda text: [1.0, 0.0, 0.0],  # fake embedding，不触网
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


def test_last_question_follows_up_then_farewell():
    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)

    # 用 4 次"不知道"把题目推进到第 5 题
    for _ in range(4):
        r = svc.answer(sid, "不知道")
        assert r["finished"] is False

    session = svc.sessions[sid]
    assert session.question_count == MAX_QUESTIONS

    # 第 5 题不再直接结束，而是像前 4 题一样追问
    r = svc.answer(sid, "RAG 是检索增强生成")
    assert r["finished"] is False
    assert r["question_count"] == MAX_QUESTIONS  # 没换题
    assert r["followup_count"] == 1              # 第 1 次追问

    r = svc.answer(sid, "它结合了检索和生成两部分")
    assert r["finished"] is False
    assert r["followup_count"] == 2              # 第 2 次追问

    # 追问满 2 次后再答 -> 告别收尾
    r = svc.answer(sid, "总的来说就是这样")
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
    # 含否定词但仍在尝试作答 -> 不算放弃
    assert svc._looks_like_give_up("这个我不太清楚，但是我觉得应该是向量相似度") is False
    assert svc._looks_like_give_up("不太懂，我猜是先把文本转成向量再检索") is False


def test_uncertain_answer_not_give_up():
    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)
    # 含否定词但仍在尝试作答 -> 应判定为"未放弃"，走追问而非换题
    r = svc.answer(sid, "我不太清楚，但是我觉得应该是向量检索")
    assert r["finished"] is False
    assert r["question_count"] == 1  # 没换题
    assert r["followup_count"] == 1  # 走追问


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


def test_question_generation_requires_knowledge_base():
    from fastapi import HTTPException

    client = FakeClient()
    vs = VectorStore()  # 知识库为空
    svc = InterviewService(
        _FakeRag(vs),
        client=client,
        embed_fn=lambda text: [1.0, 0.0, 0.0],
    )
    sid = svc.new_session()

    try:
        svc.start_question(sid)
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "知识库为空" in exc.detail
    else:
        raise AssertionError("空库时应抛出 400 错误")


def test_ensure_can_answer_guards_stream_before_it_starts():
    """流式接口靠它在推流前把 404/409 变成真实状态码（而不是 200 + 断流）。"""
    from fastapi import HTTPException

    svc, _ = _make_service()

    try:
        svc.ensure_can_answer("不存在的会话")
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("不存在的会话应抛 404")

    sid = svc.new_session()
    svc.start_question(sid)
    svc.finish(sid)
    try:
        svc.ensure_can_answer(sid)
    except HTTPException as exc:
        assert exc.status_code == 409
    else:
        raise AssertionError("已结束的面试应抛 409")

    # 正常会话：返回同一个 session 对象
    sid2 = svc.new_session()
    svc.start_question(sid2)
    assert svc.ensure_can_answer(sid2) is svc.sessions[sid2]


# ============ 出题覆盖 ============
# 5 道题必须落在不同片段上，否则"换题"只是换个说法。

def _make_service_with_chunks(n=30, topic=None):
    vs = VectorStore()
    vs.add(
        texts=[f"知识点{i}" for i in range(n)],
        metadatas=[{"filename": "kb.md"} for _ in range(n)],
        vectors=[[1.0, i * 0.01] for i in range(n)],
    )
    client = FakeClient()
    svc = InterviewService(_FakeRag(vs), client=client, embed_fn=lambda text: [1.0, 0.0])
    sid = svc.new_session(topic=topic)
    return svc, client, svc.sessions[sid]


def test_topic_context_does_not_repeat_chunks():
    """指定方向时：检索条件一样，但每次必须排除已用片段。"""
    svc, _, session = _make_service_with_chunks(30, topic="RAG")

    picked = []
    for _ in range(MAX_QUESTIONS):
        _, points = svc._build_question_context(session)
        group = [line for line in points.split("\n\n") if line]
        assert len(group) == 3
        picked.extend(group)

    assert len(picked) == MAX_QUESTIONS * 3
    assert len(set(picked)) == MAX_QUESTIONS * 3  # 15 段互不重复
    assert len(session.used_texts) == MAX_QUESTIONS * 3


def test_random_context_does_not_repeat_chunks():
    """不指定方向时：随机抽取同样要排除已用片段。"""
    svc, _, session = _make_service_with_chunks(30)

    picked = []
    for _ in range(MAX_QUESTIONS):
        _, points = svc._build_question_context(session)
        picked.extend(line for line in points.split("\n\n") if line)

    assert len(picked) == MAX_QUESTIONS * 3
    assert len(set(picked)) == MAX_QUESTIONS * 3


def test_context_falls_back_when_corpus_exhausted():
    """小语料全考过之后不能返回空素材，否则最后几题会脱开资料（面试得能继续）。"""
    svc, _, session = _make_service_with_chunks(3)

    for _ in range(2):
        extra_context, points_text = svc._build_question_context(session)
        assert extra_context
        assert points_text


def test_generate_prompt_lists_asked_questions():
    """第二题起，prompt 里必须带着"已问过的题"，否则同一个知识点会被换个说法再问一遍。"""
    svc, client = _make_service()
    session = svc.sessions[svc.new_session()]

    q1 = svc._generate_question(session)
    svc._generate_question(session)

    gen_prompts = []
    for call in client.chat.completions.calls:
        text = " ".join(m["content"] for m in call["messages"])
        if "请出一道" in text:
            gen_prompts.append(text)

    assert len(gen_prompts) == 2
    assert q1 not in gen_prompts[0]  # 第一题时还没有"已问过"
    assert q1 in gen_prompts[1]      # 第二题必须知道自己问过什么


# ============ 会话回收 ============
# 已结束的面试是"用户还要回来读"的数据，不能按业务状态回收，只能按时间回收。


def test_finished_session_survives_new_session(monkeypatch):
    """开下一场面试时，上一场的复盘不能被顺手删掉。

    回归的是这个 bug：_cleanup_expired 里写了 `if s.finished`，
    导致"点再来一场 -> 上一场复盘/收藏立刻 404"。
    """
    from src import bank as bank_mod

    monkeypatch.setattr(bank_mod, "add_question", lambda **kwargs: (1, True))

    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)
    svc.answer(sid, "RAG 是检索增强生成")
    svc.finish(sid)

    # 用户点"再来一场"
    sid2 = svc.new_session()
    assert sid2 != sid

    # 旧会话必须还能被读到
    assert sid in svc.sessions
    review = svc.get_review(sid)
    assert review["finished"] is True
    assert len(review["questions"]) == 1
    # 也还能收藏（否则用户"看完复盘再收藏"的路径永远走不通）
    assert svc.collect_question(sid, index=1) == 1


def test_expired_session_is_still_cleaned_up():
    """按时间回收仍然要生效：超过 SESSION_TTL 无活动的会话必须被清掉。"""
    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)
    svc.sessions[sid].last_active -= SESSION_TTL + 1

    svc.new_session()
    assert sid not in svc.sessions


def test_reading_review_keeps_session_alive():
    """读复盘本身也算活动：正在回看的人不该被判成僵尸。"""
    svc, _ = _make_service()
    sid = svc.new_session()
    svc.start_question(sid)

    # 模拟"隔了很久才回来点开复盘"：此刻已经超过 TTL
    svc.sessions[sid].last_active -= SESSION_TTL + 1
    svc.get_review(sid)  # 回看一次，应该续命

    svc.new_session()
    assert sid in svc.sessions
