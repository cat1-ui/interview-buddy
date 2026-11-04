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

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL, SIMILARITY_THRESHOLD
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
    # 两种"没内容"要分开说：用户才知道该去上传资料，还是该换个问法
    EMPTY_STORE_HINT = "知识库为空，请先导入资料。"
    NO_RELEVANT_HINT = "资料里没有找到相关内容。"

    def __init__(self, vector_store: VectorStore, client=None):
        self.vector_store = vector_store
        # client 可注入（测试传 fake）；未注入时才真正创建 OpenAI 客户端
        self.client = client or OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=60.0,  # 请求超时，防止上游挂起导致请求卡死
        )

    def _retrieve(self, question):
        """
        检索 + 相关度过滤。返回 (results, notice)：
            results: 通过相似度阈值的片段（按相似度降序）
            notice:  非空字符串表示没有可用内容，调用方直接把它返回给用户

        为什么抽成一个方法：ask 与 ask_stream 必须用同一套检索口径。
        之前阈值只加在了出题路径（interview.py），问答路径漏了 ——
        同一份检索、两套标准，是最容易漏改的地方。
        """
        if self.vector_store.count == 0:
            # 空库不必浪费一次 embedding 调用
            return [], self.EMPTY_STORE_HINT

        query_vector = embedding.embed_text(question)
        results = [
            r for r in self.vector_store.search(query_vector)
            if r["score"] >= SIMILARITY_THRESHOLD
        ]
        if not results:
            return [], self.NO_RELEVANT_HINT
        return results, ""

    def ask(self, question):
        """
        完整 RAG 流程：检索 + 生成。
        返回 (answer_text, sources)：
            answer_text: 生成的回答
            sources: 检索到的来源列表 [{"filename", "score", "content"}]
        """
        # 1-2. 检索 + 相关度过滤（与流式版共用同一口径，避免两套标准）
        results, notice = self._retrieve(question)
        if notice:
            return notice, []

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

        # 1-2. 检索 + 相关度过滤（这部分不是流式，先一次做完）
        # 注意：这里已是生成器，抛异常会变成"200 + 断流"，所以把错误转成 error 事件发出去
        try:
            results, notice = self._retrieve(question)
        except HTTPException as exc:
            yield error_event(str(exc.detail))
            return

        if notice:
            # 空库 / 没有相关内容：发 meta + 一句提示 + done，不调模型
            yield meta_event(sources=[])
            yield delta_event(notice)
            yield done_event()
            return

        sources = [
            {"filename": r["filename"], "score": r["score"]}
            for r in results
        ]

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
