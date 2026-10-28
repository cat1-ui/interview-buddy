# -*- coding: utf-8 -*-
"""
面试搭子 - 向量化（Embedding）模块
=================================================
调用智谱 AI 的 embedding 接口，把文字变成向量。

关键概念：什么是 embedding？
    把一段文字变成一个"数字列表"（向量），
    这个向量代表了这段文字的"语义"。
    语义相近的文字，向量也相近（在空间里距离近）。
    这样就能用数学方法（算距离）来做"语义检索"。
"""

import requests
from fastapi import HTTPException

from src.config import ZHIPU_API_KEY, ZHIPU_EMBEDDING_URL, ZHIPU_EMBEDDING_MODEL, EMBED_BATCH_SIZE


def _call_embedding(inputs):
    """
    调智谱 embedding 接口，input 可以是一段文字，也可以是多段文字组成的列表。
    返回 [向量1, 向量2, ...]。
    """
    if not ZHIPU_API_KEY:
        raise HTTPException(status_code=503, detail="未配置 ZHIPU_API_KEY，请在 .env 中填入智谱 API key")

    headers = {
        "Authorization": f"Bearer {ZHIPU_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ZHIPU_EMBEDDING_MODEL,
        "input": inputs,
    }

    try:
        resp = requests.post(ZHIPU_EMBEDDING_URL, json=payload, headers=headers, timeout=30)
        resp.raise_for_status()  # 如果请求失败，抛出异常
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"调用 embedding 服务失败：{exc}")

    data = resp.json()
    # 返回的向量按顺序在 data[i].embedding 里
    return [item["embedding"] for item in data["data"]]


def embed_text(text):
    """
    把一段文字变成向量，返回一个数字列表（list of float）。
    """
    return _call_embedding(text)[0]


def embed_texts(texts):
    """
    批量把多段文字变成向量，返回 [向量1, 向量2, ...]。
    分批调用（每批 BATCH_SIZE 段），避免一次请求过大。
    """
    vectors = []
    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i:i + EMBED_BATCH_SIZE]
        vectors.extend(_call_embedding(batch))
    return vectors
