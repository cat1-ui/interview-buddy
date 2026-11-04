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

性能设计（都是实测驱动的）：
    - 实测单批 32 段约 1.1s，且几乎全是模型推理时间，连接握手只占 7%
      => 优化重点不是"复用连接"，而是"减少总批数"和"让批次并行"
    - 磁盘缓存（data/embedding_cache.npz）：按 sha256(模型|文本) 缓存向量。
      进程重启、改代码触发 --reload、调 CHUNK_SIZE 做实验，只要片段文本没变就不重复花钱。
    - 并发（可配，默认 4）：14 批串行 15.6s -> 约 4 轮 4s。别开太高，会撞 429。
    - 失败重试 + 指数退避；但"额度不足(1113)"不重试 —— 重试也还是没额度，直接让用户去充值。
"""

import hashlib
import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import requests
from fastapi import HTTPException

from src.config import (
    ZHIPU_API_KEY,
    ZHIPU_EMBEDDING_URL,
    ZHIPU_EMBEDDING_MODEL,
    EMBED_BATCH_SIZE,
    EMBED_MAX_WORKERS,
    EMBED_CACHE_PATH,
    EMBED_MAX_RETRIES,
)

logger = logging.getLogger("uvicorn.error")

# 复用连接：单次只省 7%，但它是"顺手正确"的做法，没理由不做
_session = requests.Session()

# 智谱错误码：1113 = 余额不足 / 无可用资源包。这类错误重试没有意义
_ERROR_CODE_QUOTA = "1113"

# ---------------- 向量缓存 ----------------

_cache = {}            # cache_key -> np.ndarray(float32)
_cache_lock = threading.Lock()
_cache_loaded = False


def _cache_key(text):
    """缓存键 = 模型名 + 文本。换模型时旧缓存自然失效，不会串味。"""
    raw = f"{ZHIPU_EMBEDDING_MODEL}\x00{text}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _ensure_cache_loaded():
    """首次使用时从磁盘载入缓存（不在 import 阶段做 IO）。"""
    global _cache_loaded
    if _cache_loaded:
        return
    with _cache_lock:
        if _cache_loaded:
            return
        try:
            if EMBED_CACHE_PATH.exists():
                with np.load(EMBED_CACHE_PATH, allow_pickle=False) as data:
                    keys = data["keys"].tolist()
                    vectors = data["vectors"]
                _cache.update({k: vectors[i] for i, k in enumerate(keys)})
                logger.info(f"[embedding] 已载入缓存 {len(_cache)} 条向量")
        except Exception as exc:  # 缓存坏了不该影响主流程，重建即可
            logger.warning(f"[embedding] 缓存读取失败，将忽略：{exc}")
        _cache_loaded = True


def _save_cache():
    """
    把缓存写回磁盘。先写临时文件再原子替换，避免写一半崩掉留下坏文件。

    注意：先在锁内拍快照，再在锁外写盘 —— 2.7MB 的写盘不值得占着锁，
    也不该让另一个线程在迭代 dict 时改动它。
    """
    if not _cache:
        return
    with _cache_lock:
        items = list(_cache.items())
    keys = np.array([k for k, _ in items])
    vectors = np.array([v for _, v in items], dtype=np.float32)
    EMBED_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    # 注意临时文件名必须以 .npz 结尾：np.savez_compressed 发现后缀不符会自动补 .npz，
    # 否则写出来的文件名与这里不一致，os.replace 会找不到文件，缓存静默丢失。
    tmp_path = EMBED_CACHE_PATH.with_name(EMBED_CACHE_PATH.stem + ".tmp.npz")
    try:
        np.savez_compressed(tmp_path, keys=keys, vectors=vectors)
        os.replace(tmp_path, EMBED_CACHE_PATH)
    except Exception as exc:
        logger.warning(f"[embedding] 缓存写入失败（不影响本次结果）：{exc}")


# ---------------- 调用上游 ----------------

def _error_code(resp):
    """尽量从错误体里取出上游的业务错误码，取不到返回空串。"""
    try:
        return str(resp.json().get("error", {}).get("code", ""))
    except Exception:
        return ""


def _call_embedding(inputs, max_retries=None):
    """
    调智谱 embedding 接口，input 可以是一段文字，也可以是多段文字组成的列表。
    返回 [向量1, 向量2, ...]（顺序与输入一致）。
    """
    if not ZHIPU_API_KEY:
        raise HTTPException(status_code=503, detail="未配置 ZHIPU_API_KEY，请在 .env 中填入智谱 API key")

    retries = EMBED_MAX_RETRIES if max_retries is None else max_retries
    headers = {"Authorization": f"Bearer {ZHIPU_API_KEY}", "Content-Type": "application/json"}
    payload = {"model": ZHIPU_EMBEDDING_MODEL, "input": inputs}

    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            resp = _session.post(ZHIPU_EMBEDDING_URL, json=payload, headers=headers, timeout=30)
        except requests.RequestException as exc:
            last_error = f"网络异常：{exc}"
        else:
            if resp.status_code == 200:
                data = resp.json()
                return [item["embedding"] for item in data["data"]]
            # 额度类错误：重试无意义，直接给出可操作的提示
            if _error_code(resp) == _ERROR_CODE_QUOTA:
                raise HTTPException(
                    status_code=503,
                    detail="embedding 额度不足（智谱返回 1113），请充值或更换 key 后重试",
                )
            # 4xx（除 429 限流）说明请求本身有问题，重试也不会变
            if resp.status_code != 429 and resp.status_code < 500:
                raise HTTPException(
                    status_code=502,
                    detail=f"调用 embedding 服务失败：HTTP {resp.status_code} {resp.text[:200]}",
                )
            last_error = f"HTTP {resp.status_code}"

        if attempt < retries:
            wait = 2 ** (attempt - 1)  # 1s, 2s, 4s...
            logger.warning(f"[embedding] 第 {attempt} 次失败（{last_error}），{wait}s 后重试")
            time.sleep(wait)

    raise HTTPException(status_code=502, detail=f"调用 embedding 服务失败（已重试 {retries} 次）：{last_error}")


def embed_text(text):
    """
    把一段文字变成向量，返回一个数字列表（list of float）。
    """
    return embed_texts([text])[0]


def embed_texts(texts):
    """
    批量把多段文字变成向量，返回 [向量1, 向量2, ...]，顺序与输入严格一致。

    流程：算缓存键 -> 查缓存 -> 只对缺失的部分分批并发请求 -> 回填缓存 -> 按原顺序返回。
    """
    if not texts:
        return []

    _ensure_cache_loaded()
    keys = [_cache_key(t) for t in texts]

    # 只请求缓存里没有的；同一批里的重复文本也要去重，否则白花钱
    missing = []
    seen = set()
    for key, text in zip(keys, texts):
        if key in _cache or key in seen:
            continue
        seen.add(key)
        missing.append((key, text))

    if missing:
        batches = [
            missing[i:i + EMBED_BATCH_SIZE]
            for i in range(0, len(missing), EMBED_BATCH_SIZE)
        ]
        workers = max(1, min(EMBED_MAX_WORKERS, len(batches)))
        logger.info(
            f"[embedding] 缓存命中 {len(texts) - len(missing)}/{len(texts)}，"
            f"需请求 {len(missing)} 段（{len(batches)} 批，最多 {workers} 并发）"
        )

        with ThreadPoolExecutor(max_workers=workers) as pool:
            # pool.map 保证结果顺序与 batches 一致
            batch_vectors = list(pool.map(
                lambda batch: _call_embedding([text for _, text in batch]),
                batches,
            ))

        with _cache_lock:
            for batch, vectors in zip(batches, batch_vectors):
                for (key, _), vector in zip(batch, vectors):
                    _cache[key] = np.asarray(vector, dtype=np.float32)
        _save_cache()

    return [_cache[key].tolist() for key in keys]
