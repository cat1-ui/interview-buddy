# -*- coding: utf-8 -*-
"""
面试搭子 - 文档加载与切分模块
=================================================
把 data/docs 目录下的 md/txt 文件读进来，
切成小段（chunk），为向量化做准备。

关键概念：为什么切分？
    大模型和 embedding 接口一次能处理的文字长度有限，
    而且"整篇文档"颗粒度太粗，检索不准。
    切成小段后，每段是一个"知识单元"，检索更精准。
"""

import re
from pathlib import Path

from src.config import DOCS_DIR, CHUNK_SIZE, CHUNK_OVERLAP


def load_documents(docs_dir=None):
    """
    扫描目录，读取所有 md 和 txt 文件，返回 [{filename, content}]
    """
    docs_dir = docs_dir or DOCS_DIR
    if not docs_dir.exists():
        return []

    documents = []
    for file in sorted(docs_dir.iterdir()):
        # 只处理 md 和 txt
        if file.suffix.lower() not in [".md", ".txt"]:
            continue
        try:
            content = file.read_text(encoding="utf-8")
            documents.append({"filename": file.name, "content": content})
        except Exception:
            # 读取失败的文件跳过，不影响其他文件
            continue

    return documents


def split_text(text, chunk_size=CHUNK_SIZE, overlap=CHUNK_OVERLAP):
    """
    把一段长文本切成多个 chunk。
    采用"滑动窗口 + 重叠"：每段 chunk_size 字，相邻段重叠 overlap 字。
    重叠的作用：防止一句话正好被切在边界上，导致语义断裂。
    """
    text = text.strip()
    if not text:
        return []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= len(text):
            break
        # 下一段从"去掉重叠部分"的位置开始
        start = end - overlap

    return chunks


def build_chunks(docs_dir=None):
    """
    完整流程：读文件 → 切分 → 返回所有 chunk。
    每个 chunk 记录它来自哪个文件。
    """
    documents = load_documents(docs_dir)
    all_chunks = []
    for doc in documents:
        chunks = split_text(doc["content"])
        for chunk in chunks:
            all_chunks.append({
                "filename": doc["filename"],
                "content": chunk,
            })
    return all_chunks
