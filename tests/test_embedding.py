# -*- coding: utf-8 -*-
"""
embedding 模块的单元测试：磁盘缓存、增量请求、并发下的顺序、错误处理。

全部用假 session，不触网；缓存写到 pytest 的 tmp_path，不污染项目 data/。
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import embedding


class _Resp:
    def __init__(self, status, body=None):
        self.status_code = status
        self._body = body if body is not None else {}
        self.text = json.dumps(self._body, ensure_ascii=False)

    def json(self):
        return self._body


class _FakeSession:
    """按顺序返回预设响应，并记录每次请求的 input。"""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(json["input"])
        return self.responses.pop(0)


def _ok(vectors):
    return _Resp(200, {"data": [{"embedding": v} for v in vectors]})


@pytest.fixture
def clean_cache(monkeypatch, tmp_path):
    """每个用例都在空白缓存上跑，缓存文件落在临时目录。"""
    monkeypatch.setattr(embedding, "EMBED_CACHE_PATH", tmp_path / "embedding_cache.npz")
    monkeypatch.setattr(embedding, "_cache", {})
    monkeypatch.setattr(embedding, "_cache_loaded", False)
    monkeypatch.setattr(embedding, "ZHIPU_API_KEY", "test-key")
    return tmp_path


def _stub_call(monkeypatch, record):
    """假的 _call_embedding：记录请求内容，返回可预测的向量（长度, 批次号）。"""

    def fake(inputs, max_retries=None):
        record.append(list(inputs))
        return [[float(len(t)), float(len(record))] for t in inputs]

    monkeypatch.setattr(embedding, "_call_embedding", fake)


def test_empty_input_returns_empty():
    assert embedding.embed_texts([]) == []


def test_vectors_preserve_input_order(clean_cache, monkeypatch):
    record = []
    _stub_call(monkeypatch, record)

    vectors = embedding.embed_texts(["a", "bb", "ccc"])

    assert vectors == [[1.0, 1.0], [2.0, 1.0], [3.0, 1.0]]
    assert record == [["a", "bb", "ccc"]]


def test_second_call_hits_cache(clean_cache, monkeypatch):
    record = []
    _stub_call(monkeypatch, record)

    first = embedding.embed_texts(["a", "bb"])
    second = embedding.embed_texts(["a", "bb"])

    assert first == second
    assert len(record) == 1  # 第二次一次请求都没发


def test_only_missing_texts_are_requested(clean_cache, monkeypatch):
    record = []
    _stub_call(monkeypatch, record)

    embedding.embed_texts(["a", "bb"])
    embedding.embed_texts(["a", "bb", "ccc"])

    assert record == [["a", "bb"], ["ccc"]]  # 只补新增的那一段


def test_duplicate_texts_in_one_call_are_deduped(clean_cache, monkeypatch):
    record = []
    _stub_call(monkeypatch, record)

    vectors = embedding.embed_texts(["same", "same", "same"])

    assert record == [["same"]]
    assert vectors[0] == vectors[1] == vectors[2]


def test_cache_survives_process_restart(clean_cache, monkeypatch):
    record = []
    _stub_call(monkeypatch, record)
    embedding.embed_texts(["a", "bb"])

    # 模拟进程重启：内存清空，但磁盘上的缓存文件还在
    embedding._cache.clear()
    embedding._cache_loaded = False

    embedding.embed_texts(["a", "bb"])

    assert record == [["a", "bb"]]  # 重启后没有重新请求


def test_batches_are_split_by_batch_size(clean_cache, monkeypatch):
    monkeypatch.setattr(embedding, "EMBED_BATCH_SIZE", 2)
    record = []
    _stub_call(monkeypatch, record)

    embedding.embed_texts(["a", "b", "c", "d", "e"])

    assert [len(batch) for batch in record] == [2, 2, 1]
    assert [t for batch in record for t in batch] == ["a", "b", "c", "d", "e"]


def test_rate_limit_is_retried_then_succeeds(clean_cache, monkeypatch):
    monkeypatch.setattr(embedding, "time", SimpleNamespace(sleep=lambda _s: None))
    fake = _FakeSession([
        _Resp(429, {"error": {"code": "1302", "message": "并发超限"}}),
        _ok([[1.0, 2.0]]),
    ])
    monkeypatch.setattr(embedding, "_session", fake)

    assert embedding._call_embedding(["x"]) == [[1.0, 2.0]]
    assert len(fake.calls) == 2


def test_quota_error_fails_fast_without_retry(clean_cache, monkeypatch):
    sleeps = []
    monkeypatch.setattr(embedding, "time", SimpleNamespace(sleep=lambda s: sleeps.append(s)))
    fake = _FakeSession([_Resp(429, {"error": {"code": "1113", "message": "余额不足或无可用资源包,请充值。"}})])
    monkeypatch.setattr(embedding, "_session", fake)

    with pytest.raises(HTTPException) as exc:
        embedding._call_embedding(["x"])

    assert exc.value.status_code == 503
    assert "额度不足" in exc.value.detail
    assert len(fake.calls) == 1  # 没重试
    assert sleeps == []          # 也没等待


def test_server_error_gives_up_after_retries(clean_cache, monkeypatch):
    monkeypatch.setattr(embedding, "time", SimpleNamespace(sleep=lambda _s: None))
    fake = _FakeSession([_Resp(500, {}), _Resp(500, {}), _Resp(500, {})])
    monkeypatch.setattr(embedding, "_session", fake)

    with pytest.raises(HTTPException) as exc:
        embedding._call_embedding(["x"], max_retries=3)

    assert exc.value.status_code == 502
    assert len(fake.calls) == 3
