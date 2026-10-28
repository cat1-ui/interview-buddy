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

    def search(self, query_vector, top_k=TOP_K):
        """
        检索和 query_vector 最相似的 top_k 个 chunk。
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

        # 取相似度最高的 top_k 个下标
        top_indices = np.argsort(similarities)[::-1][:top_k]

        # 记录 top1 分数，用于以后观察"相关问题 vs 不相关问题"的分数分布，
        # 以便合理设定检索阈值（SIMILARITY_THRESHOLD）。
        if len(top_indices) > 0:
            logger.info(f"[检索] top1 相似度 = {float(similarities[top_indices[0]]):.4f}")

        results = []
        for idx in top_indices:
            results.append({
                "content": self.texts[idx],
                "filename": self.metadatas[idx].get("filename", ""),
                "score": float(similarities[idx]),
            })
        return results

    def random_sample(self, n=3):
        """
        随机取 n 段内容（用于面试出题时，随机抽取知识点）。
        返回 [{content, filename}]
        """
        import random
        if not self.texts:
            return []
        n = min(n, len(self.texts))
        indices = random.sample(range(len(self.texts)), n)
        return [
            {
                "content": self.texts[i],
                "filename": self.metadatas[i].get("filename", ""),
            }
            for i in indices
        ]
