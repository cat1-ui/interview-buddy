# -*- coding: utf-8 -*-
"""
VectorStore 的单元测试。
用手工构造的向量验证余弦检索排序、random_sample、add/clear、空库兜底。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.vector_store import VectorStore


def test_search_returns_sorted_by_cosine():
    vs = VectorStore()
    vs.add(
        texts=["aaa", "bbb", "ccc"],
        metadatas=[{"filename": "a.md"}, {"filename": "b.md"}, {"filename": "c.md"}],
        vectors=[
            [1.0, 0.0],  # 与 query 同向，cos = 1
            [0.0, 1.0],  # 正交，cos = 0
            [0.6, 0.8],  # cos = 0.6
        ],
    )
    results = vs.search([1.0, 0.0], top_k=2)
    # 按相似度从高到低排：a.md(1.0) -> c.md(0.6)
    assert [r["filename"] for r in results] == ["a.md", "c.md"]
    assert abs(results[0]["score"] - 1.0) < 1e-6
    assert abs(results[1]["score"] - 0.6) < 1e-6
    # 每个结果都应带 content 字段
    assert results[0]["content"] == "aaa"


def test_search_empty_store_returns_empty_list():
    vs = VectorStore()
    assert vs.search([1.0, 0.0]) == []


def test_random_sample_count_and_over_request():
    vs = VectorStore()
    vs.add(
        texts=["a", "b", "c", "d", "e"],
        metadatas=[{"filename": f"{i}.md"} for i in range(5)],
        vectors=[[float(i), 0.0, 0.0] for i in range(5)],
    )
    assert len(vs.random_sample(10)) == 5  # 超过总量时只返回实际数量
    assert len(vs.random_sample(3)) == 3


def test_random_sample_empty_store():
    vs = VectorStore()
    assert vs.random_sample(3) == []


def test_add_and_clear():
    vs = VectorStore()
    vs.add(["a"], [{"filename": "a.md"}], [[1.0, 0.0]])
    assert vs.count == 1
    vs.add(["b"], [{"filename": "b.md"}], [[0.0, 1.0]])
    assert vs.count == 2
    vs.clear()
    assert vs.count == 0
    assert vs.vectors is None