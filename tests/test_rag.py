# -*- coding: utf-8 -*-
"""
RagService.ask 的单元测试。
用 fake embedding + fake client，验证 prompt 拼接与返回、空库分支。
"""

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import embedding as embedding_mod
from src.vector_store import VectorStore
from src.rag import RagService


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
    def __init__(self, content="这是模型生成的回答"):
        self._content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _Response(self._content)


class FakeChat:
    def __init__(self, completions):
        self.completions = completions


class FakeClient:
    def __init__(self, content="这是模型生成的回答"):
        self.chat = FakeChat(FakeCompletions(content))


def test_ask_builds_prompt_and_returns(monkeypatch):
    vs = VectorStore()
    vs.add(
        texts=["RAG 是检索增强生成，结合检索与大模型生成"],
        metadatas=[{"filename": "rag.md"}],
        vectors=[[1.0, 0.0]],
    )
    client = FakeClient()
    svc = RagService(vs, client=client)

    # fake embedding：问题向量与文档同向，保证检索命中
    monkeypatch.setattr(embedding_mod, "embed_text", lambda text: [1.0, 0.0])

    answer, sources = svc.ask("什么是 RAG？")

    assert answer == "这是模型生成的回答"
    # sources 只带 filename + score，不带整段 content
    assert sources == [{"filename": "rag.md", "score": 1.0}]

    # 生成的 prompt 里应同时包含上下文和用户问题
    prompt = client.chat.completions.calls[0]["messages"][0]["content"]
    assert "RAG 是检索增强生成" in prompt
    assert "什么是 RAG？" in prompt


def test_ask_empty_store_returns_hint_and_skips_model(monkeypatch):
    vs = VectorStore()
    client = FakeClient()
    svc = RagService(vs, client=client)

    monkeypatch.setattr(embedding_mod, "embed_text", lambda text: [1.0, 0.0])

    answer, sources = svc.ask("你好")

    assert answer == "知识库为空，请先导入资料。"
    assert sources == []
    assert client.chat.completions.calls == []  # 空库不调模型


def test_empty_store_skips_embedding_call(monkeypatch):
    """空库连 embedding 都不该调：既省钱，也让"没资料"这个错误早点暴露。"""
    vs = VectorStore()
    svc = RagService(vs, client=FakeClient())

    def boom(text):
        raise AssertionError("空库不该调用 embedding")

    monkeypatch.setattr(embedding_mod, "embed_text", boom)
    answer, sources = svc.ask("你好")
    assert answer == RagService.EMPTY_STORE_HINT
    assert sources == []


def test_ask_filters_out_low_similarity_sources(monkeypatch):
    """低于阈值的片段不能进 prompt / sources —— 阈值必须真正生效在问答路径。"""
    vs = VectorStore()
    vs.add(
        texts=["RAG 是检索增强生成，结合检索与大模型生成", "今天天气不错，适合出门散步"],
        metadatas=[{"filename": "rag.md"}, {"filename": "chat.md"}],
        vectors=[[1.0, 0.0], [0.0, 1.0]],
    )
    client = FakeClient()
    svc = RagService(vs, client=client)

    # 问题向量只与第一段同向，第二段相似度为 0
    monkeypatch.setattr(embedding_mod, "embed_text", lambda text: [1.0, 0.0])

    answer, sources = svc.ask("什么是 RAG？")

    assert sources == [{"filename": "rag.md", "score": 1.0}]
    prompt = client.chat.completions.calls[0]["messages"][0]["content"]
    assert "RAG 是检索增强生成" in prompt
    assert "适合出门散步" not in prompt  # 无关片段被挡在 prompt 之外


def test_ask_keeps_all_chunks_above_relative_cutoff(monkeypatch):
    """回归：0.48 这种绝对值会让正常问题只喂 1 段（实测「什么是 RAG？」top1=0.480）。

    分层之后：top1 高于低水位 0.30，相对门槛 0.480×0.75=0.36，四段都该保留。
    """

    def _vec(cos):
        return [cos, math.sqrt(max(0.0, 1 - cos * cos))]

    vs = VectorStore()
    scores = [0.48, 0.41, 0.41, 0.40]
    vs.add(
        texts=[f"片段{i}" for i in range(4)],
        metadatas=[{"filename": "kb.md"} for _ in range(4)],
        vectors=[_vec(s) for s in scores],
    )
    svc = RagService(vs, client=FakeClient())
    monkeypatch.setattr(embedding_mod, "embed_text", lambda text: [1.0, 0.0])

    _, sources = svc.ask("什么是 RAG？")

    assert len(sources) == 4


def test_ask_returns_hint_when_nothing_passes_threshold(monkeypatch):
    """库里有内容但都不相关：不调模型，直接说没找到，避免模型对着噪声硬编答案。"""
    vs = VectorStore()
    vs.add(
        texts=["今天天气不错，适合出门散步"],
        metadatas=[{"filename": "chat.md"}],
        vectors=[[0.0, 1.0]],
    )
    client = FakeClient()
    svc = RagService(vs, client=client)
    monkeypatch.setattr(embedding_mod, "embed_text", lambda text: [1.0, 0.0])

    answer, sources = svc.ask("什么是 RAG？")

    assert answer == RagService.NO_RELEVANT_HINT
    assert sources == []
    assert client.chat.completions.calls == []


def test_ask_stream_uses_same_threshold(monkeypatch):
    """流式版必须与非流式同口径：同样过滤、同样提示、不发无关 sources。"""
    vs = VectorStore()
    vs.add(
        texts=["今天天气不错，适合出门散步"],
        metadatas=[{"filename": "chat.md"}],
        vectors=[[0.0, 1.0]],
    )
    client = FakeClient()
    svc = RagService(vs, client=client)
    monkeypatch.setattr(embedding_mod, "embed_text", lambda text: [1.0, 0.0])

    events = list(svc.ask_stream("什么是 RAG？"))

    assert any('"type": "meta"' in e and '"sources": []' in e for e in events)
    assert any(RagService.NO_RELEVANT_HINT in e for e in events)
    assert any('"type": "done"' in e for e in events)
    assert client.chat.completions.calls == []  # 没有可用片段就不调模型