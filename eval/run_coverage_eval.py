# -*- coding: utf-8 -*-
"""
出题覆盖度评测
=================================================
目的
    给"5 道题是不是真的落在不同考点上"一个可复现的数字，
    而不是靠跑一场看看、凭感觉说"好像不重复"。

评测口径
    1. 语料固定为 eval/corpus/ 的快照 —— 改线上 data/docs 不影响历史分数
    2. 切分 / 向量化 / 检索 / 选材**全部复用生产代码**
       （build_chunks / embedding.embed_texts / InterviewService._build_question_context）
    3. **不调用大模型**：覆盖度是"选材"的性质，跟模型生成的那句话无关。
       零成本、可复现；随机模式下有波动，多跑几场取平均。

指标
    coverage          本场用到的不同片段数 / (题数 × 每题片段数)，满分 1.0
    duplicates        被重复使用的片段次数（理想值 0）
    files             用到的不同文件数
    topic_hit         片段里含方向关键词的比例（关键词法，作为方向一致性的代理指标）
    fallback_questions 退化为"全库随机"的题数（应为 0）

同时跑三档对比，把每个修复的贡献分开
    原来    ：绝对阈值 0.48 + 不排除已用片段（b2aaabf 之前）
    +覆盖   ：排除已用片段，但仍用绝对阈值 0.48（b2aaabf）
    当前    ：排除已用片段 + 相对门槛（8cb02d4）
    这样能看出：coverage 主要由"覆盖"改动带来，而"退化题数 / 方向命中"主要由阈值改动带来。

用法
    python eval/run_coverage_eval.py                       # 默认方向 + 随机模式，各 1 场
    python eval/run_coverage_eval.py --runs 3              # 每档跑 3 场（随机模式建议）
    python eval/run_coverage_eval.py --topics RAG Agent    # 只测指定方向
    python eval/run_coverage_eval.py --corpus data/docs    # 换成线上语料（数字会变）
"""

import argparse
import json
import random
import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src.document_loader import build_chunks          # noqa: E402  复用生产切分
from src.vector_store import VectorStore              # noqa: E402  复用生产检索
from src import embedding                             # noqa: E402  复用生产向量化（带缓存）
from src.interview import InterviewService, MAX_QUESTIONS, CONTEXT_PICK  # noqa: E402

EVAL_DIR = Path(__file__).resolve().parent
DEFAULT_CORPUS = EVAL_DIR / "corpus"

# 修复前基线用的绝对阈值（当时写在 src/config.py 里的值）
LEGACY_SIMILARITY_THRESHOLD = 0.48

# 三档对比：名字 -> 内部 key
STRATEGIES = (("原来", "original"), ("+覆盖", "covered"), ("当前", "current"))

# 方向关键词：只用于"方向一致性"这个代理指标，不参与任何判定。
# 关键词法必然有误差（片段可能讲 RAG 却不出现这个词），所以只作参考，不作决策依据。
TOPIC_KEYWORDS = {
    "RAG": ["RAG", "检索", "召回", "向量", "Embedding", "chunk", "分块"],
    "Agent": ["Agent", "智能体", "工具调用", "Function Calling", "ReAct"],
    "向量数据库": ["向量", "Embedding", "索引", "Faiss", "Milvus", "pgvector"],
    "Prompt": ["Prompt", "提示词", "few-shot", "Zero-shot", "Few-shot"],
}


# ---------- 语料与索引 ----------

def load_store(corpus_dir):
    """读语料 -> 切分 -> 向量化 -> 建内存库（embedding 命中磁盘缓存时几乎不耗时）。"""
    chunks = build_chunks(corpus_dir)
    if not chunks:
        raise SystemExit(f"语料目录为空：{corpus_dir}")

    t = time.perf_counter()
    vectors = embedding.embed_texts([c["content"] for c in chunks])
    elapsed = time.perf_counter() - t

    store = VectorStore()
    store.add(
        texts=[c["content"] for c in chunks],
        metadatas=[{"filename": c["filename"]} for c in chunks],
        vectors=vectors,
    )
    print(f"语料：{corpus_dir}")
    print(f"  {len(chunks)} 个片段 / "
          f"{len({c['filename'] for c in chunks})} 篇文件 / 向量化耗时 {elapsed:.2f}s（含缓存）\n")
    return store


# ---------- 两种选材策略 ----------

def pick_current(svc, session):
    """
    当前实现：直接调用生产代码。
    返回 (picked_chunks, used_fallback)。
    """
    before = set(session.used_texts)
    was_fallback = session.topic_fallback
    svc._build_question_context(session)
    picked = session.used_texts - before

    # 降级判定：从"未降级"变成"已降级"的那一题算降级。
    # 之后各题候选只会更少，所以一旦降级，后续必然也是随机（单调性）。
    used_fallback = session.topic_fallback and not was_fallback
    return picked, used_fallback


def pick_original(store, topic, embed_fn):
    """
    最早那版（提交 b2aaabf 之前）：绝对阈值 0.48，且**不排除已用片段**。
    用于对比"只修覆盖"和"再修阈值"各自贡献了什么。
    """
    if topic:
        candidates = store.search(embed_fn(topic), top_k=CONTEXT_PICK)
        related = [r for r in candidates if r["score"] >= LEGACY_SIMILARITY_THRESHOLD][:CONTEXT_PICK]
        if related:
            return {r["content"] for r in related}, False
    samples = store.random_sample(CONTEXT_PICK, exclude=None)
    return {s["content"] for s in samples}, bool(topic)


def pick_legacy(store, topic, used, embed_fn):
    """
    加了覆盖（b2aaabf）但仍用绝对阈值 0.48 的版本。
    返回 (picked_chunks, used_fallback)。
    """
    if topic:
        topic_vector = embed_fn(topic)
        candidates = store.search(topic_vector, top_k=CONTEXT_PICK * 3 + len(used), exclude=used)
        related = [r for r in candidates if r["score"] >= LEGACY_SIMILARITY_THRESHOLD][:CONTEXT_PICK]
        if related:
            return {r["content"] for r in related}, False
    samples = store.random_sample(CONTEXT_PICK, exclude=used) or store.random_sample(CONTEXT_PICK)
    return {s["content"] for s in samples}, bool(topic)


# ---------- 指标 ----------

def score_run(picked_per_question, fallback_flags, topic, filename_of):
    """把一场面试的选材结果算成指标。"""
    picked_all = [text for group in picked_per_question for text in group]
    distinct = set(picked_all)
    capacity = MAX_QUESTIONS * CONTEXT_PICK

    keywords = TOPIC_KEYWORDS.get(topic or "", [])
    if keywords:
        hit = sum(1 for t in picked_all if any(k in t for k in keywords))
        topic_hit = hit / len(picked_all) if picked_all else 0.0
    else:
        topic_hit = None

    return {
        "capacity": capacity,
        "distinct": len(distinct),
        "coverage": len(distinct) / capacity if capacity else 0.0,
        "duplicates": len(picked_all) - len(distinct),
        "files": len({filename_of.get(t, "?") for t in distinct}),
        "topic_hit": topic_hit,
        "fallback_questions": sum(1 for f in fallback_flags if f),
    }


def run_session(svc, store, topic, strategy, embed_fn):
    """跑一场（只选材，不出题），返回 (每题的片段集合, 每题的降级标记)。"""
    session_id = svc.new_session(topic=topic)
    session = svc.sessions[session_id]
    picked_per_question, fallback_flags = [], []

    try:
        if strategy == "current":
            flipped = False
            for _ in range(MAX_QUESTIONS):
                picked, fell_back_now = pick_current(svc, session)
                flipped = flipped or fell_back_now
                picked_per_question.append(picked)
                fallback_flags.append(flipped)
        elif strategy == "covered":
            used = set()
            for _ in range(MAX_QUESTIONS):
                picked, fell_back = pick_legacy(store, topic, used, embed_fn)
                used |= picked
                picked_per_question.append(picked)
                fallback_flags.append(fell_back)
        else:  # original
            for _ in range(MAX_QUESTIONS):
                picked, fell_back = pick_original(store, topic, embed_fn)
                picked_per_question.append(picked)
                fallback_flags.append(fell_back)
    finally:
        # 场次用完即弃，避免影响后续统计
        svc.sessions.pop(session_id, None)

    return picked_per_question, fallback_flags


def average(runs):
    """多场取平均（随机模式下必须）。"""
    keys = ["coverage", "duplicates", "files", "fallback_questions"]
    out = {k: sum(r[k] for r in runs) / len(runs) for k in keys}
    hits = [r["topic_hit"] for r in runs if r["topic_hit"] is not None]
    out["topic_hit"] = sum(hits) / len(hits) if hits else None
    out["capacity"] = runs[0]["capacity"]
    out["distinct"] = sum(r["distinct"] for r in runs) / len(runs)
    out["sessions"] = len(runs)
    return out


# ---------- 主流程 ----------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topics", nargs="+", default=["RAG", "Agent", "none"],
                        help='面试方向，用 none 表示不指定方向（随机模式）')
    parser.add_argument("--runs", type=int, default=1, help="每个方向跑几场（随机模式建议 3）")
    parser.add_argument("--corpus", default=str(DEFAULT_CORPUS),
                        help="语料目录，默认 eval/corpus 快照；可传 data/docs 用线上语料")
    args = parser.parse_args()

    # 固定随机种子：随机抽样（含兜底随机）那几档也能跨机器复现，
    # 否则同一份代码两次跑出来的数字会不一样，没法比较。
    random.seed(0)

    store = load_store(Path(args.corpus))
    svc = InterviewService(type("RagLike", (), {"vector_store": store})())

    embed_fn = embedding.embed_text
    filename_of = {c["content"]: c["filename"] for c in build_chunks(Path(args.corpus))}

    results = []
    for raw_topic in args.topics:
        topic = None if raw_topic.lower() == "none" else raw_topic
        label = topic or "（不指定）"
        print(f"=== 方向：{label} × {args.runs} 场 ===")

        per_strategy = {}
        for strategy in [key for _, key in STRATEGIES]:
            runs = []
            for _ in range(args.runs):
                picked, flags = run_session(svc, store, topic, strategy, embed_fn)
                runs.append(score_run(picked, flags, topic, filename_of))
            per_strategy[strategy] = average(runs)

        for name, key in STRATEGIES:
            m = per_strategy[key]
            hit = "—" if m["topic_hit"] is None else f"{m['topic_hit']:.0%}"
            print(f"  {name:6s} coverage={m['distinct']:.1f}/{m['capacity']}"
                  f" ({m['coverage']:.0%})  重复={m['duplicates']:.1f}"
                  f"  文件数={m['files']:.1f}  方向命中={hit}"
                  f"  退化题数={m['fallback_questions']:.1f}/{MAX_QUESTIONS}")

        results.append({"topic": topic, **per_strategy})
        print()

    # ---- 报告 ----
    # 语料路径写成相对仓库根的路径，别把本机绝对路径带进仓库
    try:
        corpus_shown = Path(args.corpus).resolve().relative_to(BASE_DIR).as_posix()
    except ValueError:
        corpus_shown = str(args.corpus)

    lines = ["# 出题覆盖度评测\n",
             f"- 语料：`{corpus_shown}`",
             f"- 每档场次：{args.runs}（1 场 = {MAX_QUESTIONS} 题 × 每题 {CONTEXT_PICK} 段 = {MAX_QUESTIONS * CONTEXT_PICK} 段容量）",
             "- 判定方式：只统计**选中的片段**，不调用大模型；口径可复现，与模型输出无关\n",
             "| 方向 | 策略 | coverage | 重复片段 | 用到文件数 | 方向命中 | 退化题数 |",
             "|---|---|---|---|---|---|---|"]
    for r in results:
        label = r["topic"] or "（不指定）"
        for name, key in STRATEGIES:
            m = r[key]
            hit = "—" if m["topic_hit"] is None else f"{m['topic_hit']:.0%}"
            lines.append(
                f"| {label} | {name} | {m['distinct']:.1f}/{m['capacity']} ({m['coverage']:.0%}) | "
                f"{m['duplicates']:.1f} | {m['files']:.1f} | {hit} | {m['fallback_questions']:.1f} |"
            )

    lines.append("\n## 指标说明\n")
    lines.append("- **coverage**：本场用到的不同片段数 ÷ 容量。1.0 表示 15 段互不重复。")
    lines.append("- **退化题数**：本场有多少题因为方向内没有素材、退化为全库随机（理想 0）。")
    lines.append("- **方向命中**：选中片段里含方向关键词的比例。关键词法只是代理指标，仅供参考。")

    lines.append("\n## 怎么读这张表（重要）\n")
    # 结论里的数字直接从结果里取，避免报告文字和表格打架（随机模式下每次跑都不完全一样）
    agent = next((r for r in results if r["topic"] and r["topic"].lower() == "agent"), None)
    rag = next((r for r in results if r["topic"] and r["topic"].upper() == "RAG"), None)

    def _hit(m):
        return "—" if m["topic_hit"] is None else f"{m['topic_hit']:.0%}"

    if agent:
        a0, a1, a2 = agent["original"], agent["covered"], agent["current"]
        lines.append(
            f"- **coverage 只在「方向内检索真的被用上」时才有区分度。** 看 {agent['topic']} 方向："
            f"原来 {a0['distinct']:.0f}/{a0['capacity']}（重复片段 {a0['duplicates']:.0f} 次）"
            f"→ +覆盖 {a1['distinct']:.0f}/{a1['capacity']}"
            f"→ 当前 {a2['distinct']:.0f}/{a2['capacity']}，这是「排除已用片段」的贡献。"
        )
    if rag:
        r1, r2 = rag["covered"], rag["current"]
        lines.append(
            f"- **旧版取不到方向素材时会全程走随机**，此时 coverage 是「随机凑出来的」，"
            f"不能说明覆盖做得好。{rag['topic']} 方向的病征是"
            f"「退化 {r1['fallback_questions']:.0f}/{MAX_QUESTIONS} 题」与「方向命中 {_hit(r1)}」，"
            f"当前为「退化 {r2['fallback_questions']:.0f}/{MAX_QUESTIONS} 题」与「方向命中 {_hit(r2)}」"
            f" —— 这是「相对门槛」的贡献。"
        )
    lines.append("- 三个指标要一起看：coverage 看题目是否重复，退化题数看方向是否被静默放弃，"
                 "方向命中看题目是否真的落在方向内。")

    report = "\n".join(lines) + "\n"
    (EVAL_DIR / "coverage_results.md").write_text(report, encoding="utf-8")
    (EVAL_DIR / "coverage_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(report)
    print("报告已写入 eval/coverage_results.md 与 eval/coverage_results.json")


if __name__ == "__main__":
    main()
