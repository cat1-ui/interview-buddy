# -*- coding: utf-8 -*-
"""
RagService.ask 的单元测试。
用 fake embedding + fake client，验证 prompt 拼接与返回、空库分支。
"""

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

    assert answer == "知识库为空或没有相关内容，请先导入资料。"
    assert sources == []
    assert client.chat.completions.calls == []  # 空库不调模型