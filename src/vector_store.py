# -*- coding: utf-8 -*-
"""
面试搭子 - 向量存储与检索模块
=================================================
把「文本 + 它的向量」存起来，并在用户提问时检索最相关的文本。

关键概念：余弦相似度
    衡量两个向量"方向是否一致"的指标，范围 [-1, 1]。
    越接近 1，说明两个向量方向越一致 → 语义越相近。
    我们用 numpy 计算"问题向量"和每个"文档向量"的余弦相似度，
    取最相似的 TOP_K 个，就是检索结果。
"""

import logging
import numpy as np

from src.config import TOP_K

logger = logging.getLogger(__name__)


class VectorStore:
    """简单的内存向量库：存文本 + 向量，支持余弦相似度检索"""

    def __init__(self):
        self.texts = []        # 存所有 chunk 的文本
        self.metadatas = []    # 存每个 chunk 的来源信息（文件名等）
        self.vectors = None    # 存所有向量，是一个二维 numpy 数组
        self.building = False  # 是否正在全量重建索引（构建中禁止出题）

    def add(self, texts, metadatas, vectors):
        """批量添加文本、元数据、向量"""
        self.texts.extend(texts)
        self.metadatas.extend(metadatas)
        vec_array = np.array(vectors)
        if self.vectors is None:
            self.vectors = vec_array
        else:
            self.vectors = np.vstack([self.vectors, vec_array])

    def clear(self):
        """清空所有数据（重新构建知识库时用）。"""
        self.texts = []
        self.metadatas = []
        self.vectors = None

    @property
    def count(self):
        """当前存储的 chunk 数量"""
        return len(self.texts)

    def search(self, query_vector, top_k=TOP_K, exclude=None):
        """
        检索和 query_vector 最相似的 top_k 个 chunk。
        exclude: 可选，一组 chunk 文本；命中这些文本的片段会被跳过。
                 出题时用它避开"本场已经考过的片段"，实现考点覆盖。

        返回 [{content, filename, score}]
        """
        if self.vectors is None or len(self.texts) == 0:
            return []

        query_vec = np.array(query_vector)

        # 计算余弦相似度
        # 公式：cos = (A·B) / (|A| * |B|)
        # 先归一化，避免分母计算
        norms = np.linalg.norm(self.vectors, axis=1, keepdims=True)
        query_norm = np.linalg.norm(query_vec)
        # 归一化后的点积 = 余弦相似度
        if query_norm == 0 or (norms == 0).any():
            return []
        normalized_vectors = self.vectors / norms
        normalized_query = query_vec / query_norm
        similarities = normalized_vectors @ normalized_query  # 点积

        # 先按相似度整体排序，排除已用片段后再截取 top_k
        # （先截 top_k 再过滤会拿不满数量，已用片段多时尤其明显）
        order = np.argsort(similarities)[::-1]
        if exclude:
            order = [int(i) for i in order if self.texts[int(i)] not in exclude]
        top_indices = order[:top_k]

        # 记录 top-K 分数，用于以后观察"相关问题 vs 不相关问题"的分数分布，
        # 以便合理设定检索阈值（SIMILARITY_THRESHOLD）。
        if len(top_indices) > 0:
            scores = [round(float(similarities[i]), 4) for i in top_indices]
            logger.info(f"[检索] top-{len(scores)} 相似度 = {scores}")

        results = []
        for idx in top_indices:
            results.append({
                "content": self.texts[idx],
                "filename": self.metadatas[idx].get("filename", ""),
                "score": float(similarities[idx]),
            })
        return results

    def random_sample(self, n=3, exclude=None):
        """
        随机取 n 段内容（用于面试出题时，随机抽取知识点）。
        exclude: 可选，一组 chunk 文本；这些片段不会被抽中。
        返回 [{content, filename}]
        """
        import random
        if not self.texts:
            return []
        candidates = [
            i for i, text in enumerate(self.texts)
            if not exclude or text not in exclude
        ]
        if not candidates:
            return []
        n = min(n, len(candidates))
        indices = random.sample(candidates, n)
        return [
            {
                "content": self.texts[i],
                "filename": self.metadatas[i].get("filename", ""),
            }
            for i in indices
        ]

    def remove_by_filename(self, filename):
        """
        按文件名移除对应的所有 chunk（增量删除用）。
        返回移除的数量；未找到同名 chunk 则返回 0 且不改动数据。
        """
        if not self.texts:
            return 0
        keep = [i for i, m in enumerate(self.metadatas) if m.get("filename") != filename]
        removed = len(self.texts) - len(keep)
        if removed == 0:
            return 0
        self.texts = [self.texts[i] for i in keep]
        self.metadatas = [self.metadatas[i] for i in keep]
        if self.vectors is not None:
            self.vectors = self.vectors[keep] if keep else None
        return removed
