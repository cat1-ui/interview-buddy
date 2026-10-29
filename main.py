# -*- coding: utf-8 -*-
"""
面试搭子 - FastAPI 后端入口
=================================================
提供接口：
    POST /build   构建知识库（读文档 → 切分 → 向量化 → 存入内存）
    POST /ask     知识库问答（RAG）
    GET  /health  健康检查

运行方式：
    uvicorn main:app --reload
    然后访问 http://localhost:8000/docs 查看接口文档并测试
"""

from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from src.config import CORS_ORIGINS, DEEPSEEK_API_KEY, ZHIPU_API_KEY, DOCS_DIR
from src.document_loader import build_chunks
from src import embedding
from src import bank
from src import tts
from src.vector_store import VectorStore
from src.rag import RagService
from src.interview import InterviewService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时校验 API key，关闭时可做清理。"""
    import logging
    logger = logging.getLogger("uvicorn.error")
    if not DEEPSEEK_API_KEY:
        logger.warning("警告：未配置 DEEPSEEK_API_KEY，问答/面试将无法工作，请在 .env 中填入")
    if not ZHIPU_API_KEY:
        logger.warning("警告：未配置 ZHIPU_API_KEY，构建知识库将无法工作，请在 .env 中填入")
    yield
    # 这里可以写"服务关闭时要做的事"（暂时用不到）


app = FastAPI(title="面试搭子 interview-buddy", lifespan=lifespan)

# 跨域：允许前端（Vite 开发服务器）访问后端接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in CORS_ORIGINS.split(",") if o.strip()],
    allow_methods=["*"],
    allow_headers=["*"],
)


# 全局的向量库和 RAG 服务（进程内存中）
vector_store = VectorStore()
rag_service = RagService(vector_store)
interview_service = InterviewService(rag_service)


class BuildResponse(BaseModel):
    status: str
    chunk_count: int


class AskRequest(BaseModel):
    question: str


class AskResponse(BaseModel):
    answer: str
    sources: list


@app.get("/health")
def health():
    return {"status": "ok", "chunk_count": vector_store.count}


@app.post("/build", response_model=BuildResponse)
def build_knowledge_base():
    """
    构建知识库：扫描 data/docs 目录，读文档、切分、向量化、存入内存。
    """
    # 1. 读文档 + 切分
    chunks = build_chunks()
    if not chunks:
        return BuildResponse(status="empty", chunk_count=0)

    # 2. 提取文本和元数据
    texts = [c["content"] for c in chunks]
    metadatas = [{"filename": c["filename"]} for c in chunks]

    # 3. 向量化
    vectors = embedding.embed_texts(texts)

    # 4. 存入向量库（先清空旧的，再写入新的）
    #    全程复用同一个 vector_store 实例，rag_service / interview_service 持有的是它的引用，
    #    清空再写入后，它们看到的也是新数据，无需重建引用。
    vector_store.clear()
    vector_store.add(texts, metadatas, vectors)

    return BuildResponse(status="success", chunk_count=vector_store.count)


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    """
    知识库问答：走完整 RAG 流程。
    """
    answer, sources = rag_service.ask(req.question)
    return AskResponse(answer=answer, sources=sources)


@app.post("/ask/stream")
def ask_stream(req: AskRequest):
    """
    知识库问答（流式）：返回 SSE 流，事件格式 meta/delta/done。
    """
    return StreamingResponse(
        rag_service.ask_stream(req.question),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ============ 模拟面试相关接口 ============

class NewInterviewRequest(BaseModel):
    topic: str = None  # 面试方向（可选），如"RAG"


class NewInterviewResponse(BaseModel):
    session_id: str
    question: str


class AnswerRequest(BaseModel):
    session_id: str
    answer: str


class AnswerResponse(BaseModel):
    reply: str
    finished: bool = False  # 是否已结束（前端据此过渡到打分）
    question_count: int = 0  # 当前已出到第几题
    followup_count: int = 0  # 当前题已追问的次数


class FinishRequest(BaseModel):
    session_id: str


class FinishResponse(BaseModel):
    score: dict


@app.post("/interview/new", response_model=NewInterviewResponse)
def interview_new(req: NewInterviewRequest = None):
    """
    开始一场新的模拟面试：创建会话，并出第一道题。
    可选传入 topic（面试方向），让面试官围绕该方向出题。
    """
    topic = req.topic if req else None
    session_id = interview_service.new_session(topic=topic)
    question = interview_service.start_question(session_id)
    return NewInterviewResponse(session_id=session_id, question=question)


@app.post("/interview/answer", response_model=AnswerResponse)
def interview_answer(req: AnswerRequest):
    """
    候选人回答问题，面试官评估后回应（追问或过渡）。
    返回 reply、finished、以及当前进度（question_count / followup_count）。
    """
    result = interview_service.answer(req.session_id, req.answer)
    return AnswerResponse(
        reply=result["reply"],
        finished=result["finished"],
        question_count=result["question_count"],
        followup_count=result["followup_count"],
    )


@app.post("/interview/answer/stream")
def interview_answer_stream(req: AnswerRequest):
    """
    候选人回答问题（流式）：返回 SSE 流，事件格式 meta/delta/done。
    meta 里带 finished / question_count / followup_count。
    """
    return StreamingResponse(
        interview_service.answer_stream(req.session_id, req.answer),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/interview/finish", response_model=FinishResponse)
def interview_finish(req: FinishRequest):
    """
    结束面试，生成打分报告。
    """
    score = interview_service.finish(req.session_id)
    return FinishResponse(score=score)


@app.get("/interview/{session_id}")
def interview_get(session_id: str):
    """
    找回一场面试的当前状态（前端刷新页面后，用保存的 session_id 恢复进度）。
    """
    return interview_service.get_session_info(session_id)


@app.get("/interview/{session_id}/review")
def interview_review(session_id: str):
    """
    复盘：返回整场面试的按题分组记录（题目 + 完整一问一答），供前端做复盘表。
    """
    return interview_service.get_review(session_id)


class TtsRequest(BaseModel):
    text: str


@app.post("/interview/tts")
async def interview_tts(req: TtsRequest):
    """
    把一段面试官回复文字合成成语音（MP3）。

    设计：
        - 前端点击播放按钮时才调用（不预合成），省去无谓合成
        - 带内存缓存：同一段文字反复点播放只合成一次
        - 音频全程在内存中，不落盘，播完即弃
    返回 audio/mpeg 二进制；失败返回 502（前端提示"播放失败，请稍后再试"）。
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="文本为空")

    # 命中缓存，直接返回
    cached = tts.tts_cache.get(text)
    if cached is not None:
        return Response(content=cached, media_type="audio/mpeg")

    try:
        audio = await tts.synthesize(text)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"语音合成失败：{exc}")

    if not audio:
        raise HTTPException(status_code=502, detail="语音合成失败：返回空音频")

    tts.tts_cache.set(text, audio)
    return Response(content=audio, media_type="audio/mpeg")


# ============ 题库相关接口 ============

class CollectRequest(BaseModel):
    session_id: str
    index: int = None  # 第几题（1 开始）；不传则收藏"当前题"
    category: str = ""  # 可选，自定义分类；为空则默认用面试方向


class CollectResponse(BaseModel):
    id: int


class UpdateCategoryRequest(BaseModel):
    category: str


@app.post("/bank/collect", response_model=CollectResponse)
def bank_collect(req: CollectRequest):
    """
    收藏某一道题到题库（可按题序号指定，默认收藏当前题）。
    """
    qid = interview_service.collect_question(req.session_id, index=req.index, category=req.category)
    if qid is None:
        # 当前没有可收藏的题
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="当前没有可收藏的题目")
    return CollectResponse(id=qid)


@app.get("/bank/list")
def bank_list(category: str = None):
    """
    列出题库（可按分类筛选）。
    """
    return bank.list_questions(category=category)


@app.get("/bank/categories")
def bank_categories():
    """
    列出题库里已有的所有分类。
    """
    return bank.list_categories()


@app.delete("/bank/{qid}")
def bank_delete(qid: int):
    """
    删除一道题。
    """
    from fastapi import HTTPException
    if not bank.delete_question(qid):
        raise HTTPException(status_code=404, detail="题目不存在")
    return {"status": "deleted", "id": qid}


@app.put("/bank/{qid}/category")
def bank_update_category(qid: int, req: UpdateCategoryRequest):
    """
    修改一道题的分类。
    """
    from fastapi import HTTPException
    if not bank.update_category(qid, req.category):
        raise HTTPException(status_code=404, detail="题目不存在")
    return {"status": "updated", "id": qid, "category": req.category}


# ============ 资料管理接口 ============

# 上传限制
MAX_UPLOAD_COUNT = 3       # 一次最多上传几个文件
MAX_UPLOAD_SIZE = 5 * 1024 * 1024  # 单文件最大 5MB
ALLOWED_SUFFIXES = (".md", ".txt")  # 只允许这两个后缀（严格小写）


def _rebuild_knowledge_base():
    """重新构建知识库（读 data/docs → 切分 → 向量化 → 存入内存）。"""
    global vector_store
    chunks = build_chunks()
    if not chunks:
        vector_store.clear()
        return 0
    texts = [c["content"] for c in chunks]
    metadatas = [{"filename": c["filename"]} for c in chunks]
    vectors = embedding.embed_texts(texts)
    vector_store.clear()
    vector_store.add(texts, metadatas, vectors)
    return vector_store.count


@app.post("/upload")
async def upload_docs(files: list[UploadFile] = File(...)):
    """
    上传资料文件（.md / .txt），存到 data/docs，并自动重新构建知识库。
    限制：一次最多 3 个，单文件 5MB，只允许 .md/.txt，同名拒绝。
    """
    # 1. 数量校验
    if len(files) > MAX_UPLOAD_COUNT:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_UPLOAD_COUNT} 个文件")

    # 2. 逐个校验并保存
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    saved = []
    for f in files:
        filename = f.filename or ""
        # 格式校验（严格小写后缀）
        if not filename.endswith(ALLOWED_SUFFIXES):
            raise HTTPException(status_code=400, detail=f"文件 {filename} 格式不支持，只允许 .md 和 .txt")
        # 重名校验
        dest = DOCS_DIR / filename
        if dest.exists():
            raise HTTPException(status_code=409, detail=f"已存在同名文件：{filename}")

        # 边接收边计数，超过 5MB 立即中断
        size = 0
        chunks_bytes = []
        while True:
            chunk = await f.read(1024 * 64)  # 每次读 64KB
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                await f.close()
                raise HTTPException(status_code=413, detail=f"文件 {filename} 超过 5MB 限制")
            chunks_bytes.append(chunk)

        dest.write_bytes(b"".join(chunks_bytes))
        await f.close()
        saved.append(filename)

    # 3. 自动重新构建
    chunk_count = _rebuild_knowledge_base()

    return {"status": "success", "saved": saved, "chunk_count": chunk_count}


@app.get("/files")
def list_docs():
    """
    列出 data/docs 里的资料文件（文件名、大小、修改时间）。
    （注：不用 /docs，因为那是 FastAPI 的 Swagger 文档页保留路径）
    """
    if not DOCS_DIR.exists():
        return []
    result = []
    for f in sorted(DOCS_DIR.iterdir()):
        if f.is_file() and f.name.endswith(ALLOWED_SUFFIXES):
            stat = f.stat()
            result.append({
                "filename": f.name,
                "size": stat.st_size,
                "modified": stat.st_mtime,
            })
    return result


@app.delete("/files/{filename}")
def delete_doc(filename: str):
    """
    删除一个资料文件，并自动重新构建知识库。
    """
    # 安全校验：只允许纯文件名，防路径穿越
    if filename != Path(filename).name or ".." in filename:
        raise HTTPException(status_code=400, detail="非法的文件名")

    dest = DOCS_DIR / filename
    if not dest.exists() or not dest.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    dest.unlink()  # 删除文件
    chunk_count = _rebuild_knowledge_base()

    return {"status": "deleted", "filename": filename, "chunk_count": chunk_count}
