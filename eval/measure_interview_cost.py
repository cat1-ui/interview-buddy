# -*- coding: utf-8 -*-
"""
单场模拟面试的调用次数与 token 成本
=================================================
为什么要测
    "AI 应用"和"能跑通的 demo"之间差一件事：你知不知道它每次跑起来要花多少钱。
    面试官问"你这个东西上线一个月要多少钱"，答不出来基本就废了。

怎么测
    给 InterviewService 注入一个"会记账"的客户端（包装真实 OpenAI 客户端），
    跑完一整场 5 题面试 + 打分，逐次记录 prompt / completion token 与缓存命中情况。

    不注入假数据、不估算：所有 token 数都来自上游返回的 usage 字段。

用法
    python eval/measure_interview_cost.py
"""

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from openai import OpenAI                                          # noqa: E402

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL  # noqa: E402
from src.document_loader import build_chunks                        # noqa: E402
from src import embedding                                           # noqa: E402
from src.vector_store import VectorStore                             # noqa: E402
from src.rag import RagService                                      # noqa: E402
from src.interview import InterviewService                           # noqa: E402

# DeepSeek 官方定价（元 / 百万 token）
PRICE_INPUT_MISS = 1.0
PRICE_INPUT_HIT = 0.02
PRICE_OUTPUT = 2.0

# 模拟候选人的回答（长度接近真实作答，避免"不知道"触发换题分支）
ANSWERS = [
    "RAG 是检索增强生成，先把文档切块做向量化，提问时把问题也向量化，算余弦相似度取最相关的几块拼进 prompt，让模型基于这些内容回答，这样能减少幻觉。",
    "因为纯向量检索靠语义相似度，遇到工单号这种精确编号，字符层面没有语义，向量空间里距离不近，所以召回很差，通常要加 BM25 关键词通道做混合检索。",
    "长期记忆是再调一次模型，让它从对话里抽取值得记住的信息，输出结构化 JSON，比如姓名、爱好、职业这些字段，然后落库，下次对话按分类拼进 system prompt。",
    "流式输出是模型边生成边返回，服务端用 SSE 把每个增量推给前端，前端逐段渲染，这样首字很快就出来了，不用等整段生成完。",
    "追问是因为一次回答往往停留在表面，需要顺着薄弱点再挖一层，比如只说了结论没讲原理，就追问底层机制，追问满两次再换题，避免一直卡在一道题上。",
]


class RecordingCompletions:
    """转发到真实客户端，同时把每次调用的 usage 记下来。"""

    def __init__(self, real):
        self._real = real
        self.calls = []

    def create(self, **kwargs):
        started = time.perf_counter()
        resp = self._real.chat.completions.create(**kwargs)
        elapsed = time.perf_counter() - started

        usage = getattr(resp, "usage", None)
        hit = getattr(usage, "prompt_cache_hit_tokens", 0) or 0
        miss = getattr(usage, "prompt_cache_miss_tokens", 0) or 0
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        # 没返回缓存明细时，按"全部未命中"保守估算
        if hit == 0 and miss == 0:
            miss = prompt_tokens

        self.calls.append({
            "model": getattr(resp, "model", ""),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "cache_hit": hit,
            "cache_miss": miss,
            "elapsed": round(elapsed, 2),
            "stream": bool(kwargs.get("stream")),
        })
        return resp


class RecordingChat:
    def __init__(self, completions):
        self.completions = completions


class RecordingClient:
    def __init__(self, real):
        self.completions = RecordingCompletions(real)
        self.chat = RecordingChat(self.completions)


def cost_of(calls):
    hit = sum(c["cache_hit"] for c in calls)
    miss = sum(c["cache_miss"] for c in calls)
    out = sum(c["completion_tokens"] for c in calls)
    yuan = (miss / 1e6 * PRICE_INPUT_MISS
            + hit / 1e6 * PRICE_INPUT_HIT
            + out / 1e6 * PRICE_OUTPUT)
    return {"hit": hit, "miss": miss, "out": out, "yuan": yuan}


def build_rag(client):
    chunks = build_chunks()
    store = VectorStore()
    texts = [c["content"] for c in chunks]
    store.add(texts, [{"filename": c["filename"]} for c in chunks],
              embedding.embed_texts(texts))
    return RagService(store, client=client), store.count


def main():
    if not DEEPSEEK_API_KEY:
        sys.exit("缺少 DEEPSEEK_API_KEY")

    real = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL, timeout=120)
    client = RecordingClient(real)

    print("构建知识库（真实调用 embedding）…")
    rag, chunk_count = build_rag(client)
    print(f"知识库 {chunk_count} 个 chunk\n")

    svc = InterviewService(rag, client=client)
    sid = svc.new_session(topic=None)
    q = svc.start_question(sid)
    print(f"第 1 题: {q[:50]}…\n")

    idx = 0
    rounds = 0
    while not svc.sessions[sid].finished and rounds < 25:
        ans = ANSWERS[idx % len(ANSWERS)]
        before = len(client.completions.calls)
        result = svc.answer(sid, ans)
        rounds += 1
        idx += 1
        s = svc.sessions[sid]
        print(f"  第 {rounds:2d} 次作答 → 题 {result['question_count']} / 追问 {result['followup_count']}"
              f"{'  [结束]' if result['finished'] else ''}"
              f"  本轮 {len(client.completions.calls) - before} 次模型调用")
        if result["finished"]:
            break

    score = svc.finish(sid)
    print(f"\n打分: {score.get('总分')} 分，维度 {score.get('准确性')}/{score.get('深度')}/{score.get('表达清晰度')}")

    calls = client.completions.calls
    total = cost_of(calls)
    models = sorted({c["model"] for c in calls if c["model"]})

    line = "=" * 56
    print(f"\n{line}\n单场面试（5 题 + 打分）实测\n{line}")
    print(f"模型调用次数      : {len(calls)} 次")
    print(f"输入 token（未命中）: {total['miss']:,}")
    print(f"输入 token（缓存命中）: {total['hit']:,}")
    print(f"输出 token        : {total['out']:,}")
    print(f"合计 token        : {total['miss'] + total['hit'] + total['out']:,}")
    print(f"单场成本          : ¥{total['yuan']:.4f}")
    print(f"实际模型标识      : {', '.join(models) or '(未返回)'}")
    cache_rate = total["hit"] / (total["hit"] + total["miss"]) if (total["hit"] + total["miss"]) else 0
    print(f"缓存命中率        : {cache_rate:.0%}")
    print(f"平均每次调用耗时  : {sum(c['elapsed'] for c in calls) / len(calls):.2f}s")
    print(line)
    print(f"换算：1000 场面试 ≈ ¥{total['yuan'] * 1000:.1f}")

    out = Path(__file__).resolve().parent / "interview_cost.md"
    rows = [
        "# 单场模拟面试的调用与成本（实测）\n",
        f"- 场景：5 题封顶 + 每题最多 2 次追问 + 结束时打分，共 {rounds} 次作答",
        f"- 知识库：{chunk_count} 个 chunk",
        f"- 模型标识：{', '.join(models) or '(未返回)'}",
        f"- 定价口径：输入未命中 ¥{PRICE_INPUT_MISS}/M、缓存命中 ¥{PRICE_INPUT_HIT}/M、输出 ¥{PRICE_OUTPUT}/M\n",
        "| 项 | 数值 |",
        "|---|---|",
        f"| 模型调用次数 | {len(calls)} |",
        f"| 输入 token（未命中 / 命中） | {total['miss']:,} / {total['hit']:,} |",
        f"| 输出 token | {total['out']:,} |",
        f"| 缓存命中率 | {cache_rate:.0%} |",
        f"| **单场成本** | **¥{total['yuan']:.4f}** |",
        f"| 平均单次调用耗时 | {sum(c['elapsed'] for c in calls) / len(calls):.2f}s |",
    ]
    out.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"\n已写入 {out}")


if __name__ == "__main__":
    main()
