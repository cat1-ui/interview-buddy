# -*- coding: utf-8 -*-
"""
检索质量评测：Recall@K / Top-1 / MRR
=================================================
目的
    给 RAG 的检索环节一个可复现、可比较的数字，而不是靠"感觉检索挺准的"。

评测口径
    1. 语料固定为 eval/corpus/ 下的快照（评测集与线上资料解耦，避免改资料就改分数）
    2. 切分和检索**复用生产代码**（src.document_loader.split_text / src.vector_store.VectorStore），
       保证测的是线上真正跑的那条链路，而不是另写一套"评测专用"实现
    3. 每道题标注一段原文片段（gold_snippet）。Top-K 结果里任意一段包含该片段即算命中
    4. 判定不看人、不看模型输出，只看字符串是否出现 —— 换个时间换台机器跑，结果一致

指标
    Recall@K : 前 K 段里命中黄金片段的题目占比
    Top-1    : 第 1 段就命中的题目占比
    MRR@6    : 命中排名倒数的平均值，越接近 1 说明命中位置越靠前

用法
    python eval/run_recall_eval.py                 # 默认扫描三档切分粒度
    python eval/run_recall_eval.py --chunk-sizes 300 500
"""

import argparse
import json
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src import embedding                      # noqa: E402
from src.document_loader import split_text     # noqa: E402  复用生产切分逻辑
from src.vector_store import VectorStore       # noqa: E402  复用生产检索逻辑

EVAL_DIR = Path(__file__).resolve().parent
CORPUS_DIR = EVAL_DIR / "corpus"
EVAL_SET = EVAL_DIR / "eval_set.json"

KS = [1, 2, 4, 6]


# ---------- 索引构建 ----------

def _window_starts(text_len, chunk_size, overlap):
    """复现 split_text 的滑动窗口起点序列（用于把字符位置映射回 chunk）。"""
    starts = []
    start = 0
    while start < text_len:
        starts.append(start)
        if start + chunk_size >= text_len:
            break
        start = start + chunk_size - overlap
    return starts


def build_chunks_with_offsets(docs_dir, chunk_size, overlap):
    """
    读语料 → 切分，同时记录每个 chunk 在原文中的起始偏移。

    偏移的用途：把 gold_snippet 在原文里的位置，映射到"它落在第几个 chunk 里"，
    这样标注就不受切分边界影响（片段正好被切开也不会算错）。
    """
    chunks = []
    for path in sorted(Path(docs_dir).iterdir()):
        if path.suffix.lower() not in (".md", ".txt"):
            continue
        text = path.read_text(encoding="utf-8").strip()

        # 用生产代码切分，保证 chunk 内容与线上完全一致
        prod_chunks = split_text(text, chunk_size=chunk_size, overlap=overlap)
        starts = _window_starts(len(text), chunk_size, overlap)

        # 自检：自己算的窗口必须和生产切分结果逐一对齐，否则偏移映射不可信
        assert len(prod_chunks) == len(starts), (
            f"切分窗口数不一致：{len(prod_chunks)} vs {len(starts)}"
        )
        for i, (chunk_text, st) in enumerate(zip(prod_chunks, starts)):
            assert chunk_text == text[st:st + chunk_size], "窗口切片与生产切分不一致"

        for st in starts:
            chunks.append({
                "doc": path.name,
                "text": text[st:st + chunk_size],
                "start": st,
            })
    return chunks


def locate_gold(chunks, item, corpus_texts):
    """
    定位一道题的黄金 chunk 下标集合。
    取 gold_snippet 的中间位置，落在哪个窗口就认哪个（重叠区域内可能命中 2 个，都算对）。
    """
    text = corpus_texts[item["doc"]]
    pos = text.find(item["gold_snippet"])
    if pos == -1:
        raise ValueError(f"第 {item['id']} 题的 gold_snippet 在语料中找不到：{item['gold_snippet']!r}")

    mid = pos + len(item["gold_snippet"]) // 2
    gold = [
        i for i, c in enumerate(chunks)
        if c["doc"] == item["doc"] and c["start"] <= mid < c["start"] + len(c["text"])
    ]
    if not gold:
        raise ValueError(f"第 {item['id']} 题定位不到黄金 chunk（mid={mid}）")
    return gold


# ---------- 指标 ----------

def compute_metrics(ranks, ks=KS):
    """ranks: 每道题命中 chunk 的最高排名（1-based），未命中记 None。"""
    total = len(ranks)
    out = {}
    for k in ks:
        hit = sum(1 for r in ranks if r is not None and r <= k)
        out[f"recall@{k}"] = hit / total
    out["mrr@6"] = sum(
        (1.0 / r) for r in ranks if r is not None and r <= 6
    ) / total
    out["miss"] = sum(1 for r in ranks if r is None or r > 6)
    return out


# ---------- 主流程 ----------

def embed_with_retry(texts, retries=3):
    """embedding 调用加个重试，避免偶发网络抖动让整轮评测白跑。"""
    for attempt in range(1, retries + 1):
        try:
            return embedding.embed_texts(texts)
        except Exception as exc:
            if attempt == retries:
                raise
            wait = 2 * attempt
            print(f"    embedding 失败（{exc}），{wait}s 后重试 {attempt}/{retries - 1}")
            time.sleep(wait)


def run_one_config(chunk_size, overlap, items, corpus_texts, query_vectors):
    chunks = build_chunks_with_offsets(CORPUS_DIR, chunk_size, overlap)

    store = VectorStore()
    store.add(
        texts=[c["text"] for c in chunks],
        metadatas=[{"filename": c["doc"]} for c in chunks],
        vectors=embed_with_retry([c["text"] for c in chunks]),
    )

    max_k = max(KS)
    ranks = []
    details = []
    for item, qvec in zip(items, query_vectors):
        gold = set(locate_gold(chunks, item, corpus_texts))
        results = store.search(qvec, top_k=max_k)

        rank = None
        for i, r in enumerate(results, start=1):
            # 命中判定：返回片段的原文里包含黄金片段
            if item["gold_snippet"] in r["content"]:
                rank = i
                break
        ranks.append(rank)
        details.append({
            "id": item["id"],
            "question": item["question"],
            "rank": rank,
            "gold_chunks": sorted(gold),
            "top1_preview": (results[0]["content"][:60] if results else ""),
        })

    metrics = compute_metrics(ranks)
    metrics.update({
        "chunk_size": chunk_size,
        "overlap": overlap,
        "chunk_count": len(chunks),
    })
    return metrics, details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--chunk-sizes", nargs="+", type=int, default=[300, 500, 800])
    parser.add_argument("--overlap-ratio", type=float, default=0.1,
                        help="重叠比例，默认 0.1（与线上 500/50 一致）")
    args = parser.parse_args()

    data = json.loads(EVAL_SET.read_text(encoding="utf-8"))
    items = data["items"]
    corpus_texts = {
        p.name: p.read_text(encoding="utf-8").strip()
        for p in CORPUS_DIR.iterdir()
        if p.suffix.lower() in (".md", ".txt")
    }

    print(f"语料：{len(corpus_texts)} 篇，共 {sum(len(t) for t in corpus_texts.values())} 字")
    print(f"评测集：{len(items)} 题\n")

    # 问题向量与切分粒度无关，只算一次，省调用也省时间
    print("向量化 20 个问题…")
    query_vectors = embed_with_retry([it["question"] for it in items])

    all_metrics = []
    all_details = {}
    for size in args.chunk_sizes:
        overlap = max(1, int(size * args.overlap_ratio))
        print(f"\n=== chunk_size={size} / overlap={overlap} ===")
        m, d = run_one_config(size, overlap, items, corpus_texts, query_vectors)
        print(
            f"  chunks={m['chunk_count']}  "
            f"Recall@1={m['recall@1']:.0%}  Recall@4={m['recall@4']:.0%}  "
            f"Recall@6={m['recall@6']:.0%}  MRR@6={m['mrr@6']:.3f}  未命中={m['miss']}"
        )
        all_metrics.append(m)
        all_details[size] = d

    # ---- 输出报告 ----
    lines = []
    lines.append("# 检索质量评测报告\n")
    lines.append(f"- 语料：{len(corpus_texts)} 篇 / "
                 f"{sum(len(t) for t in corpus_texts.values())} 字")
    lines.append(f"- 评测集：{len(items)} 题（标注原文片段，字符串匹配判定）")
    lines.append(f"- 判定方式：Top-K 中任意片段包含黄金原文即为命中\n")
    lines.append("| chunk_size | overlap | chunks | Recall@1 | Recall@2 | Recall@4 | Recall@6 | MRR@6 |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for m in all_metrics:
        lines.append(
            f"| {m['chunk_size']} | {m['overlap']} | {m['chunk_count']} | "
            f"{m['recall@1']:.0%} | {m['recall@2']:.0%} | {m['recall@4']:.0%} | "
            f"{m['recall@6']:.0%} | {m['mrr@6']:.3f} |"
        )

    lines.append("\n## 未命中明细（chunk_size=%d）\n" % all_metrics[0]["chunk_size"])
    for d in all_details[all_metrics[0]["chunk_size"]]:
        if d["rank"] is None:
            lines.append(f"- Q{d['id']} 未进前 6：{d['question']}")

    report = "\n".join(lines) + "\n"
    (EVAL_DIR / "results.md").write_text(report, encoding="utf-8")
    (EVAL_DIR / "results.json").write_text(
        json.dumps({"metrics": all_metrics, "details": all_details},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n" + report)
    print("报告已写入 eval/results.md 与 eval/results.json")


if __name__ == "__main__":
    main()
