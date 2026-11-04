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
import threading
import asyncio

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, Response
from pydantic import BaseModel

from src.config import CORS_ORIGINS, DEEPSEEK_API_KEY, ZHIPU_API_KEY, DOCS_DIR
from src.document_loader import build_chunks, split_text, safe_doc_filename, ALLOWED_SUFFIXES
from src import embedding
from src import bank
from src import tts
from src.vector_store import VectorStore
from src.streaming import guard_events
from src.rag import RagService
from src.interview import InterviewService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期：启动时校验 API key，并自动构建知识库。"""
    import logging
    logger = logging.getLogger("uvicorn.error")
    if not DEEPSEEK_API_KEY:
        logger.warning("警告：未配置 DEEPSEEK_API_KEY，问答/面试将无法工作，请在 .env 中填入")
    if not ZHIPU_API_KEY:
        logger.warning("警告：未配置 ZHIPU_API_KEY，构建知识库将无法工作，请在 .env 中填入")

    # 向量库存在内存里，每次重启都是空的。
    # 这里在后台线程里自动重建一次，避免阻塞服务启动（向量化要多次网络请求）。
    threading.Thread(target=_auto_build_on_startup, daemon=True).start()

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
    return {
        "status": "ok",
        "chunk_count": vector_store.count,
        # 构建中（启动时自动重建 / 手动 /build）：前端可据此提前提示，而不是等用户撞 503
        "building": vector_store.building,
    }


@app.post("/build", response_model=BuildResponse)
def build_knowledge_base():
    """
    构建知识库：扫描 data/docs 目录，读文档、切分、向量化、存入内存。

    统一走 _rebuild_knowledge_base()，不要在这里再内联一份：
    内联版会漏掉 building 标志（重建期间出题拦不住），
    而且和上传的增量写入抢同一份 list —— clear 与 add 之间进来的数据会被静默清掉。
    """
    chunk_count = _rebuild_knowledge_base()
    return BuildResponse(
        status="success" if chunk_count else "empty",
        chunk_count=chunk_count,
    )


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
        guard_events(rag_service.ask_stream(req.question)),
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
    # 会话不存在 / 已结束这类校验必须在开始推流之前做完：
    # 一旦 SSE 开始发送，就只能给 200，状态码改不了了。
    interview_service.ensure_can_answer(req.session_id)
    return StreamingResponse(
        guard_events(interview_service.answer_stream(req.session_id, req.answer)),
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
# 允许的格式白名单在 src.document_loader.ALLOWED_SUFFIXES（与文件名校验放在一起）


def _rebuild_knowledge_base():
    """全量重建知识库（读 data/docs → 切分 → 向量化 → 存入内存）。"""
    global vector_store
    vector_store.building = True
    try:
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
    finally:
        vector_store.building = False


def _auto_build_on_startup():
    """
    服务启动时自动构建知识库。

    为什么需要：向量库存在内存里，每次重启服务都会清空。
    以前靠前端「重新构建」按钮手动重建，容易误点、也容易被遗忘，
    现在改成启动时自动做一次，用户无需关心"索引"这回事。

    在后台线程执行，不阻塞服务启动；失败只记日志，不影响其他功能。
    """
    import logging
    logger = logging.getLogger("uvicorn.error")
    try:
        if vector_store.count > 0:
            return
        # data/docs 里没有资料就不必构建
        if not DOCS_DIR.exists():
            return
        has_docs = any(
            f.is_file() and f.name.endswith((".md", ".txt"))
            for f in DOCS_DIR.iterdir()
        )
        if not has_docs:
            return
        if not ZHIPU_API_KEY:
            logger.warning("检测到资料但未配置 ZHIPU_API_KEY，跳过自动构建知识库")
            return

        logger.info("正在自动构建知识库…")
        count = _rebuild_knowledge_base()
        logger.info(f"知识库自动构建完成：{count} 个片段")
    except Exception as exc:
        logger.warning(f"知识库自动构建失败：{exc}（上传资料时会自动重试）")


@app.post("/upload")
async def upload_docs(files: list[UploadFile] = File(...)):
    """
    上传资料文件（.md / .txt），存到 data/docs，并增量写入向量库（不全量重建）。
    限制：一次最多 3 个，单文件 5MB，只允许 .md/.txt，同名拒绝。
    语义：全成功或全失败 —— 任一文件校验或向量化失败，本次一个文件都不落盘。
    """
    # 1. 数量校验
    if len(files) > MAX_UPLOAD_COUNT:
        raise HTTPException(status_code=400, detail=f"一次最多上传 {MAX_UPLOAD_COUNT} 个文件")

    # 上传是"全成功或全失败"：
    #   先把所有文件校验完、再全部向量化、最后才统一落盘入库。
    #   这样任何一个文件不合法（格式/超限/为空），都不会留下"传了一半"的残局
    #   ——以前是边校验边写盘，第 2 个文件报错时第 1 个已经写进去了，
    #     用户看到失败、重传又撞 409，只能手动去删。
    DOCS_DIR.mkdir(parents=True, exist_ok=True)

    # ---- 阶段一：校验文件名（格式 / 路径穿越 / 重名 / 本次请求内重名）----
    seen = set()
    names = []
    for f in files:
        # 格式 + 路径穿越校验，与删除接口共用同一套规则
        try:
            filename = safe_doc_filename(f.filename)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        # 重名校验：已存在，或本次请求里重复
        if (DOCS_DIR / filename).exists() or filename in seen:
            raise HTTPException(status_code=409, detail=f"已存在同名文件：{filename}")
        seen.add(filename)
        names.append(filename)

    # ---- 阶段二：读取 + 大小校验 + 切分（全程不落盘）----
    payloads = []  # [(filename, content(bytes), chunks(list[str]))]
    for f, filename in zip(files, names):
        size = 0
        chunks_bytes = []
        while True:
            chunk = await f.read(1024 * 64)  # 每次读 64KB，边收边计数
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_UPLOAD_SIZE:
                await f.close()
                raise HTTPException(status_code=413, detail=f"文件 {filename} 超过 5MB 限制")
            chunks_bytes.append(chunk)
        await f.close()

        content = b"".join(chunks_bytes)
        chunks = split_text(content.decode("utf-8", errors="ignore"))
        if not chunks:
            raise HTTPException(status_code=400, detail=f"文件 {filename} 内容为空")
        payloads.append((filename, content, chunks))

    # ---- 阶段三：全部向量化（任一失败 -> 整体失败，此时磁盘上还没有任何新文件）----
    vectorized = []
    for filename, content, chunks in payloads:
        # 放线程池：embedding 是同步 HTTP 请求，直接在事件循环里跑会卡住所有请求
        vectors = await asyncio.to_thread(embedding.embed_texts, chunks)
        vectorized.append((filename, content, chunks, vectors))

    # ---- 阶段四：落盘 + 增量入库 ----
    saved = []
    for filename, content, chunks, vectors in vectorized:
        (DOCS_DIR / filename).write_bytes(content)
        vector_store.add(chunks, [{"filename": filename}] * len(chunks), vectors)
        saved.append(filename)

    return {"status": "success", "saved": saved, "chunk_count": vector_store.count}


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
    # 安全校验：与上传共用同一套规则（纯文件名、无 ..、后缀白名单）
    try:
        filename = safe_doc_filename(filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    dest = DOCS_DIR / filename
    if not dest.exists() or not dest.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    dest.unlink()  # 删除文件
    vector_store.remove_by_filename(filename)  # 增量：只移除对应向量，不全量重建

    return {"status": "deleted", "filename": filename, "chunk_count": vector_store.count}
