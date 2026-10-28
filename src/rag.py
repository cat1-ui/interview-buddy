# -*- coding: utf-8 -*-
"""
面试搭子 - RAG 生成模块
=================================================
把「检索 + 生成」串起来，完成一次完整的 RAG 问答。

流程：
    用户提问 → 问题变向量 → 向量检索 → 拿到相关段落
    → 把段落 + 问题拼成 prompt → 调 DeepSeek 生成回答
"""

from fastapi import HTTPException
from openai import OpenAI

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from src import embedding
from src.vector_store import VectorStore

# 生成回答用的 prompt 模板
RAG_PROMPT = """请根据以下资料回答用户的问题。

要求：
1. 只根据下面提供的资料回答，不要编造资料里没有的内容
2. 如果资料里没有相关信息，就诚实说"资料里没有找到相关内容"
3. 回答要清晰、有条理
4. 直接输出答案，不要添加注音、音译、括号补充、自我解释等多余内容

相关资料：
{context}

用户问题：{question}
"""


class RagService:
    def __init__(self, vector_store: VectorStore):
        self.vector_store = vector_store
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=60.0,  # 请求超时，防止上游挂起导致请求卡死
        )

    def ask(self, question):
        """
        完整 RAG 流程：检索 + 生成。
        返回 (answer_text, sources)：
            answer_text: 生成的回答
            sources: 检索到的来源列表 [{"filename", "score", "content"}]
        """
        # 1. 问题变向量
        query_vector = embedding.embed_text(question)

        # 2. 检索最相关的段落
        results = self.vector_store.search(query_vector)

        if not results:
            return "知识库为空或没有相关内容，请先导入资料。", []

        # 3. 把检索到的段落拼成"上下文"
        context = "\n\n".join(
            f"[来自 {r['filename']}]\n{r['content']}" for r in results
        )

        # 4. 拼 prompt
        prompt = RAG_PROMPT.format(context=context, question=question)

        # 5. 调 DeepSeek 生成回答
        try:
            response = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # 回答要基于资料，温度低一些更稳定
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"调用大模型失败：{exc}")

        # sources 只返回前端需要的字段（filename、score），不把整段 content 重复带出去
        sources = [
            {"filename": r["filename"], "score": r["score"]}
            for r in results
        ]
        return response.choices[0].message.content, sources

    def ask_stream(self, question):
        """
        完整 RAG 流程的流式版本。
        这是一个生成器，逐段 yield SSE 事件字符串：
            meta（带 sources）-> 多个 delta -> done
        检索部分仍然一次完成（embedding + search），只有"生成"是流式的。
        """
        from src.streaming import meta_event, delta_event, done_event, error_event

        # 1. 问题变向量 + 检索（这部分不是流式，先一次做完）
        query_vector = embedding.embed_text(question)
        results = self.vector_store.search(query_vector)

        sources = [
            {"filename": r["filename"], "score": r["score"]}
            for r in results
        ]

        if not results:
            # 知识库为空：直接发 meta + 一句提示 + done，不调模型
            yield meta_event(sources=[])
            yield delta_event("知识库为空或没有相关内容，请先导入资料。")
            yield done_event()
            return

        # 先发 meta（带 sources）
        yield meta_event(sources=sources)

        # 2. 拼 prompt
        context = "\n\n".join(
            f"[来自 {r['filename']}]\n{r['content']}" for r in results
        )
        prompt = RAG_PROMPT.format(context=context, question=question)

        # 3. 流式调 DeepSeek，逐段 yield
        try:
            stream = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta_event(delta)
        except Exception as exc:
            yield error_event(f"调用大模型失败：{exc}")
            return

        yield done_event()
