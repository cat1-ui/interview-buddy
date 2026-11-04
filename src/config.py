# -*- coding: utf-8 -*-
"""
面试搭子 - 配置模块
=================================================
统一管理 API key、模型名、路径等配置。
"""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ============ 路径 ============
# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent
# 文档目录：把 md/txt 文件放这里，程序自动读取
DOCS_DIR = BASE_DIR / "data" / "docs"
# 数据目录
DATA_DIR = BASE_DIR / "data"

# ============ API 配置 ============
# DeepSeek（生成回答用）
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 智谱 AI（向量化 embedding 用）
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
ZHIPU_EMBEDDING_URL = "https://open.bigmodel.cn/api/paas/v4/embeddings"
ZHIPU_EMBEDDING_MODEL = "embedding-3"

# ============ CORS 跨域配置 ============
# 允许哪些前端地址访问后端（逗号分隔）。开发默认放行 Vite 默认端口。
# 上线后改成正式前端域名，例如 https://your-frontend.com
CORS_ORIGINS = os.getenv(
    "CORS_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173",
)

# ============ RAG 参数 ============
# 文档切分：每段最大字符数
# 300 是实测值，依据见 eval/results.md 与 eval/results_holdout.md：
#   用 30 题评测集（20 题调参 + 10 题留出集）对比 300/500/800 三档，
#   Recall@4 随粒度变细单调上升 —— 300 命中 30/30、500 为 29/30、800 为 28/30，故取 300。
# 注意：Recall@1 的差异不稳健（主集 300 更好，留出集 500 更好），属样本噪声，未作为决策依据。
CHUNK_SIZE = 300
# 相邻段重叠字符数（防止一句话被切断导致信息丢失），取切分粒度的 10%
CHUNK_OVERLAP = 30
# 检索时返回最相关的几段
TOP_K = 4
# embedding 批量请求时，每批最多多少段
EMBED_BATCH_SIZE = 32
# 并发请求几批（实测单批约 1.1s，主要是模型推理时间；串行 14 批 = 15.6s）
# 别开太高：智谱对并发有限制，撞 429 反而更慢
EMBED_MAX_WORKERS = int(os.getenv("EMBED_MAX_WORKERS", "4"))
# 失败重试次数（指数退避 1s / 2s / 4s）。额度不足(1113)不重试，直接报错
EMBED_MAX_RETRIES = int(os.getenv("EMBED_MAX_RETRIES", "3"))
# 向量磁盘缓存：按 sha256(模型|文本) 复用已算过的向量，
# 重启 / --reload / 调参实验都不会重复调用 embedding
EMBED_CACHE_PATH = DATA_DIR / "embedding_cache.npz"
# ============ 检索门槛 ============
# 问答路径（rag.ask）用两层，不再用 0.48 这种绝对阈值。
#
# 实测依据（现语料 5 篇 / 350 段）：
#   「什么是 RAG？」top1 = 0.480      「今天天气怎么样？」top1 = 0.470
#   「RAG 分块粒度怎么定？」 top1 = 0.492
#   「红烧肉怎么做？」   top1 = 0.236  「明天股市会涨吗？」 top1 = 0.240
# 相关与无关在 0.47 附近完全重叠 —— 任何绝对阈值要么误伤相关问题，
# 要么放过无关问题。原 0.48 的实际后果是：正常问题只喂 1 段上下文（设计是 4 段），
# 而「今天天气」差 0.01 就能溜进来。
#
# 所以：低水位只挡"明显无关"，具体喂几段由相对水位决定，
# "资料里到底有没有答案"交给模型判断（RAG_PROMPT 已要求它诚实说没有）。
RAG_MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.30"))
RAG_SCORE_RATIO = float(os.getenv("RAG_SCORE_RATIO", "0.75"))

# 出题方向检索的门槛（相对门槛，不是绝对值）。
# 踩过的坑：原来直接用 0.48 这种绝对阈值当方向内过滤条件，
# 那个值是对旧语料（7 篇 / 640 段）测出来的；删掉两篇资料后「RAG」方向
# top1 只有 0.525、top2 就掉到 0.457，于是每次只放出 1 个片段，
# 第 2 题起候选全被滤空，只能静默退化成"全库随机出题" —— 方向形同虚设。
# 现在分成两层：
#   TOPIC_MIN_SCORE   : 绝对下限。低于它才判定"这个方向没资料"，才算降级
#   TOPIC_SCORE_RATIO : 相对门槛。方向内取 top1 分数的这个比例当及格线，
#                       跟着当前语料的实际分布走，换语料不需要重新调参
TOPIC_MIN_SCORE = float(os.getenv("TOPIC_MIN_SCORE", "0.30"))
TOPIC_SCORE_RATIO = float(os.getenv("TOPIC_SCORE_RATIO", "0.7"))
