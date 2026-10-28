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
CHUNK_SIZE = 500
# 相邻段重叠字符数（防止一句话被切断导致信息丢失）
CHUNK_OVERLAP = 50
# 检索时返回最相关的几段
TOP_K = 3
# embedding 批量请求时，每批最多多少段
EMBED_BATCH_SIZE = 32
# 检索相似度阈值：top1 分数低于此值的，视为"没有相关资料"。
# 默认 0 表示不启用（先观察分数分布再定值）。
SIMILARITY_THRESHOLD = float(os.getenv("SIMILARITY_THRESHOLD", "0"))
