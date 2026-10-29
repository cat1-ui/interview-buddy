# -*- coding: utf-8 -*-
"""
面试搭子 - 语音合成（TTS）模块
=================================================
用 Edge-TTS（微软 Edge 浏览器的免费在线语音）把文字合成语音。

设计要点：
    - 音频全程在内存中，不落盘（合成结果直接以字节返回，播完即弃）
    - 内存缓存：只缓存"当前这场面试"已合成过的文字，避免重复调用
      （缓存由 InterviewService 在开新面试时清空，见 interview.py）

关键概念：为什么用 Edge-TTS？
    免费、无需 API key、中文音色自然。代价是它是"借用"微软 Edge
    的公开接口，非官方承诺，适合个人自用，不适合商业化高频调用。
"""

import asyncio
import io

import edge_tts

# 中文女声，自然度较好。可替换为其他音色，如：
#   zh-CN-XiaoxiaoNeural（晓晓，女声）
#   zh-CN-YunxiNeural   （云希，男声）
#   zh-CN-YunyangNeural （云扬，男声，新闻感）
VOICE = "zh-CN-XiaoxiaoNeural"


async def synthesize(text: str) -> bytes:
    """
    把一段文字合成成 MP3 音频字节。

    返回 MP3 的二进制内容（bytes）。失败时抛异常，由调用方兜底。
    """
    communicate = edge_tts.Communicate(text, VOICE)
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


class TtsCache:
    """
    内存缓存：文字 -> 音频字节。

    目的：同一段面试官回复，用户反复点播放，只合成一次。
    生命周期：跟着"当前这场面试"走，开新面试时 clear()。
    """

    def __init__(self, max_entries: int = 200):
        self._cache: dict[str, bytes] = {}
        self._max_entries = max_entries

    def get(self, text: str) -> bytes | None:
        return self._cache.get(text)

    def set(self, text: str, audio: bytes) -> None:
        # 简单淘汰：超过上限就清空（面试场景文本量很小，几乎不会触发）
        if len(self._cache) >= self._max_entries:
            self._cache.clear()
        self._cache[text] = audio

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


# 全局 TTS 缓存实例（由 InterviewService 在开新面试时清空）
tts_cache = TtsCache()
