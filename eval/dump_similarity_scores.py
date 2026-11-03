# -*- coding: utf-8 -*-
"""
相似度分数分布探查：为「资料内主题 / 资料外主题」两组查询 dump 检索 top-K 分数，
用于据此设定 SIMILARITY_THRESHOLD（相关度门槛）。

用法：
    python eval/dump_similarity_scores.py
"""
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from src import embedding                 # noqa: E402
from src.document_loader import build_chunks   # noqa: E402
from src.vector_store import VectorStore       # noqa: E402

# 正例：资料里确实有的主题（命中时应得高分）
POSITIVE = [
    "RAG", "向量数据库", "Embedding", "工具调用", "Function Calling",
    "记忆", "Redis", "提示词工程", "智能体", "微调", "ReAct", "余弦相似度",
]

# 负例：资料里没有的主题（应得低分被过滤掉）
NEGATIVE = [
    "红烧肉", "股票K线", "React前端", "健身增肌", "唐诗宋词",
    "MySQL索引", "糖醋排骨", "羽毛球技巧", "基金定投", "钢琴考级",
]


def dump(store, label, queries):
    qvecs = embedding.embed_texts(queries)
    print(f"\n===== {label} =====")
    top1_list = []
    for q, qv in zip(queries, qvecs):
        results = store.search(qv, top_k=5)
        scores = [round(r["score"], 4) for r in results]
        top1_list.append(scores[0])
        print(f"  {q:<14} top5 = {scores}")
    print(f"  >> top1 范围 {min(top1_list):.4f} ~ {max(top1_list):.4f}，"
          f"均值 {sum(top1_list) / len(top1_list):.4f}")
    return top1_list


def main():
    print("构建知识库（data/docs）…")
    chunks = build_chunks()
    texts = [c["content"] for c in chunks]
    metadatas = [{"filename": c["filename"]} for c in chunks]
    vectors = embedding.embed_texts(texts)
    store = VectorStore()
    store.add(texts, metadatas, vectors)
    print(f"知识库：{len(chunks)} 段\n")

    pos = dump(store, "正例（资料内主题，期望高分）", POSITIVE)
    neg = dump(store, "负例（资料外主题，期望低分）", NEGATIVE)

    print(f"\n===== 汇总 =====")
    print(f"正例 top1 均值 {sum(pos) / len(pos):.4f}  (最小 {min(pos):.4f})")
    print(f"负例 top1 均值 {sum(neg) / len(neg):.4f}  (最大 {max(neg):.4f})")


if __name__ == "__main__":
    main()