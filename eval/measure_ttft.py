# -*- coding: utf-8 -*-
"""
首字延迟（TTFT）测量
=================================================
目的
    证明"流式"不是一个说法，而是一个可量化的时间差。

测什么
    同一条问题，分别走流式接口与非流式接口，记录三个时间点：
        t_meta        : 收到 meta 事件（检索已完成，来源已确定）
        t_first_delta : 收到第一个 delta（**用户看到第一个字**）
        t_total       : 收到 done 事件（整段说完）
    非流式接口只能测 t_total —— 用户要等整段生成完才看到东西。

    所以对外能讲的那句话是：
        "首字 X 秒，整段 Y 秒" —— 而不是含糊的"响应更快"。

用法
    先起服务： uvicorn main:app --port 8000
    再跑：     python eval/measure_ttft.py
"""

import json
import statistics
import sys
import time
from pathlib import Path

import requests

BASE = "http://127.0.0.1:8000"
OUT = Path(__file__).resolve().parent / "ttft_results.json"

# 同一批问题，流式与非流式各跑一遍，保证可比
QUESTIONS = [
    "长期记忆是怎么提取和使用的？",
    "Function Calling 的原理是什么？",
    "让模型稳定输出 JSON 有哪些防线？",
    "流式输出是怎么实现的？",
    "不同任务为什么要用不同的 temperature？",
]

REPEAT = 2  # 每个问题跑几轮，取中位数，避免单次网络抖动


def measure_stream(question):
    """流式：返回 (t_meta, t_first_delta, t_total, 字符数)。"""
    t0 = time.perf_counter()
    t_meta = t_first = None
    chars = 0

    with requests.post(f"{BASE}/ask/stream", json={"question": question},
                       stream=True, timeout=120) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data: "):
                continue
            payload = json.loads(line[6:])
            now = time.perf_counter() - t0
            etype = payload.get("type")
            if etype == "meta" and t_meta is None:
                t_meta = now
            elif etype == "delta":
                if t_first is None:
                    t_first = now
                chars += len(payload.get("content", ""))
            elif etype == "done":
                return t_meta, t_first, now, chars
    raise RuntimeError("流式响应未收到 done 事件")


def measure_nonstream(question):
    """非流式：只能拿到整段耗时。"""
    t0 = time.perf_counter()
    r = requests.post(f"{BASE}/ask", json={"question": question}, timeout=180)
    r.raise_for_status()
    elapsed = time.perf_counter() - t0
    data = r.json()
    return elapsed, len(data.get("answer", ""))


def pct(vals, q):
    vals = sorted(vals)
    if not vals:
        return 0.0
    idx = min(len(vals) - 1, int(round((len(vals) - 1) * q)))
    return vals[idx]


def main():
    health = requests.get(f"{BASE}/health", timeout=10).json()
    if not health.get("chunk_count"):
        print("知识库为空，请先 POST /build")
        sys.exit(1)
    print(f"知识库：{health['chunk_count']} 个 chunk")

    stream_rows, nonstream_rows = [], []
    for q in QUESTIONS:
        for _ in range(REPEAT):
            t_meta, t_first, t_total, chars = measure_stream(q)
            stream_rows.append({
                "question": q, "t_meta": t_meta,
                "t_first_delta": t_first, "t_total": t_total, "chars": chars,
            })
            print(f"  [流式] meta {t_meta:5.2f}s  首字 {t_first:5.2f}s  "
                  f"整段 {t_total:5.2f}s  {chars:4d} 字")
            t_all, nchars = measure_nonstream(q)
            nonstream_rows.append({"question": q, "t_total": t_all, "chars": nchars})
            print(f"  [阻塞] 整段 {t_all:5.2f}s  {nchars:4d} 字（无首字，需等全文）")

    firsts = [r["t_first_delta"] for r in stream_rows]
    totals_stream = [r["t_total"] for r in stream_rows]
    totals_block = [r["t_total"] for r in nonstream_rows]
    metas = [r["t_meta"] for r in stream_rows]

    med_first = statistics.median(firsts)
    med_stream_total = statistics.median(totals_stream)
    med_block_total = statistics.median(totals_block)
    med_meta = statistics.median(metas)

    lines = [
        "# 首字延迟（TTFT）测量\n",
        f"- 样本：{len(QUESTIONS)} 个问题 × {REPEAT} 轮 = {len(stream_rows)} 次流式 / "
        f"{len(nonstream_rows)} 次非流式",
        "- 环境：本机 uvicorn + localhost 回环，网络耗时可忽略",
        "- 计时起点：发出 HTTP 请求之前；终点：收到对应事件\n",
        "| 指标 | 中位数 | P90 | 最大 |",
        "|---|---|---|---|",
        f"| 检索完成（meta） | {med_meta:.2f}s | {pct(metas, 0.9):.2f}s | {max(metas):.2f}s |",
        f"| **首字到达（首个 delta）** | **{med_first:.2f}s** | {pct(firsts, 0.9):.2f}s | {max(firsts):.2f}s |",
        f"| 全文完成（流式） | {med_stream_total:.2f}s | {pct(totals_stream, 0.9):.2f}s | {max(totals_stream):.2f}s |",
        f"| 全文完成（非流式） | {med_block_total:.2f}s | {pct(totals_block, 0.9):.2f}s | {max(totals_block):.2f}s |",
        "",
        f"用户感知等待：非流式需等 {med_block_total:.2f}s 才能看到第一个字；"
        f"流式 {med_first:.2f}s 就开始出字，"
        f"感知等待缩短 {med_block_total - med_first:.2f}s（约 {(1 - med_first / med_block_total) * 100:.0f}%）。",
        "",
        f"拆解：检索占首字时间中的 {med_meta:.2f}s，模型首个 token 占 {med_first - med_meta:.2f}s。",
    ]
    report = "\n".join(lines) + "\n"
    print("\n" + report)

    OUT.write_text(json.dumps({
        "summary": {
            "meta_median": med_meta,
            "first_delta_median": med_first,
            "stream_total_median": med_stream_total,
            "block_total_median": med_block_total,
            "perceived_wait_cut_pct": round((1 - med_first / med_block_total) * 100, 1),
        },
        "stream": stream_rows,
        "nonstream": nonstream_rows,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT.parent / "ttft_results.md").write_text(report, encoding="utf-8")
    print(f"结果已写入 {OUT} 与 ttft_results.md")


if __name__ == "__main__":
    main()
