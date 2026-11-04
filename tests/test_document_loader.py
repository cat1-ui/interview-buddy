# -*- coding: utf-8 -*-
"""
document_loader.split_text 的单元测试。
用小的 chunk_size / overlap 便于手算验证边界，不依赖默认的 500。
"""

import sys
from pathlib import Path

import pytest

# 让测试能 import src 包
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.document_loader import safe_doc_filename, split_text


def test_empty_text_returns_empty_list():
    assert split_text("") == []
    assert split_text("   ") == []


def test_short_text_not_split():
    # 长度小于 chunk_size 时，返回 1 个完整 chunk
    result = split_text("abc", chunk_size=5, overlap=1)
    assert result == ["abc"]


def test_exact_chunk_size_is_single_chunk():
    # 刚好等于 chunk_size，返回 1 个 chunk，不多切
    result = split_text("abcde", chunk_size=5, overlap=1)
    assert result == ["abcde"]


def test_long_text_splits_with_overlap():
    # chunk_size=5, overlap=2：相邻 chunk 之间应有 overlap 个字符重叠
    text = "abcdefghij"
    chunks = split_text(text, chunk_size=5, overlap=2)
    # 手算：
    # 第1段 abcde（0-5）
    # 下一段起点 = 5 - 2 = 3 -> defgh（3-8）
    # 下一段起点 = 8 - 2 = 6 -> ghij（6-10，结尾）
    assert chunks[0] == "abcde"
    assert chunks[1] == "defgh"
    assert chunks[2] == "ghij"


def test_overlap_preserves_boundary_content():
    # 验证重叠确实让"边界文字"出现在两段里
    text = "一二三四五六七八"
    chunks = split_text(text, chunk_size=4, overlap=2)
    # 第1段：一二三四（0-4）
    # 第2段：三四五六（2-6）
    # 第3段：五六七八（4-8）
    assert "四" in chunks[0] and "四" in chunks[1]  # 边界字在相邻两段都出现
    assert "六" in chunks[1] and "六" in chunks[2]


def test_chinese_text_splits_by_character():
    # 中文按字符数切分，一个字算一个字符
    text = "你好世界"
    chunks = split_text(text, chunk_size=2, overlap=0)
    assert chunks == ["你好", "世界"]


def test_no_overlap_clean_split():
    # overlap=0 时，相邻段不重叠
    text = "abcdefgh"
    chunks = split_text(text, chunk_size=3, overlap=0)
    assert chunks == ["abc", "def", "gh"]


# ============ 文件名校验（上传 / 删除共用） ============

def test_safe_filename_accepts_plain_names():
    assert safe_doc_filename("a.md") == "a.md"
    assert safe_doc_filename("RAG 笔记.txt") == "RAG 笔记.txt"
    assert safe_doc_filename("  a.md  ") == "a.md"  # 前后空白被裁掉


def test_safe_filename_rejects_path_traversal():
    for bad in ["../a.md", "../../evil.md", "sub/a.md", "sub\\a.md", "..\\evil.md", "a/../../b.md"]:
        with pytest.raises(ValueError):
            safe_doc_filename(bad)


def test_safe_filename_rejects_bad_suffix():
    # .MD 也算不合法：大小写不同会在 Windows 上绕开重名校验（a.md / a.MD 互相覆盖）
    for bad in ["a.exe", "a.md.exe", "a", "a.MD", ".md", ""]:
        with pytest.raises(ValueError):
            safe_doc_filename(bad)
