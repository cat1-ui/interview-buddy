# -*- coding: utf-8 -*-
"""
面试搭子 - 题库模块
=================================================
把面试过程中"收藏"的题目持久化到本地 SQLite，供长期沉淀和回看。

关键概念：
    面试进行中的会话是"临时的"（内存里，丢了无所谓），
    而被收藏进题库的题目是"有价值的"（落盘，重启不丢）。
    本模块只负责后者——题库的增、删、查、分类。
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src.config import DATA_DIR

# 数据库文件路径
DB_PATH = DATA_DIR / "interview_bank.db"


def _connect(db_path=None):
    """建立数据库连接（自动建目录、建表）。

    db_path: 可选，指定数据库文件路径（测试可传 tmp_path 隔离）。
             为 None 时用默认的 DB_PATH。
    """
    if db_path is None:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path = DB_PATH
    else:
        path = Path(db_path)
        # :memory: 没有父目录，跳过 mkdir
        if str(db_path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row  # 让查询结果能按列名取值
    return conn


def _init_table(conn):
    """建表（如果不存在）。"""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,          -- 题目（面试官第一句）
            dialogue TEXT NOT NULL,          -- 这道题的完整一问一答（JSON 字符串）
            category TEXT NOT NULL DEFAULT '',   -- 分类（默认取 topic，用户可改）
            topic TEXT NOT NULL DEFAULT '',      -- 面试方向
            source_key TEXT NOT NULL DEFAULT '', -- 来源标识（session_id:index），用于去重
            created_at TEXT NOT NULL         -- 收藏时间
        )
        """
    )
    # 旧表可能没有 source_key 列，做兼容迁移
    cols = [row["name"] for row in conn.execute("PRAGMA table_info(questions)")]
    if "source_key" not in cols:
        conn.execute("ALTER TABLE questions ADD COLUMN source_key TEXT NOT NULL DEFAULT ''")
    conn.commit()


def add_question(question, dialogue, category="", topic="", source_key="", db_path=None):
    """
    收藏一道题。
    question: 题目文本
    dialogue: 这道题的完整一问一答，list of {"role","content"}
    category: 分类标签（默认同 topic）
    topic: 面试方向
    source_key: 来源标识（session_id:index），用于去重。相同 source_key 不会重复入库。
    db_path: 可选，指定数据库文件路径（测试用）。
    返回 (qid, created)：
        qid: 记录 id（若已存在，返回已有记录的 id）
        created: 是否真的新插入（False 表示已存在、本次被去重跳过）
    """
    if not category:
        category = topic  # 默认用面试方向当分类

    conn = _connect(db_path)
    try:
        _init_table(conn)

        # 去重：source_key 相同（同一场面试的同一道题）则不再插入
        if source_key:
            existing = conn.execute(
                "SELECT id FROM questions WHERE source_key = ?", (source_key,)
            ).fetchone()
            if existing:
                return existing["id"], False

        cur = conn.execute(
            "INSERT INTO questions (question, dialogue, category, topic, source_key, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                question,
                json.dumps(dialogue, ensure_ascii=False),
                category,
                topic,
                source_key,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        conn.commit()
        return cur.lastrowid, True
    finally:
        conn.close()


def list_questions(category=None, db_path=None):
    """
    列出题库（按收藏时间倒序）。
    category: 可选，只返回该分类下的题。
    db_path: 可选，指定数据库文件路径（测试用）。
    返回 list of dict。
    """
    conn = _connect(db_path)
    try:
        _init_table(conn)
        if category:
            rows = conn.execute(
                "SELECT * FROM questions WHERE category = ? ORDER BY id DESC",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM questions ORDER BY id DESC"
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r["id"],
                "question": r["question"],
                "dialogue": json.loads(r["dialogue"]),
                "category": r["category"],
                "topic": r["topic"],
                "created_at": r["created_at"],
            })
        return result
    finally:
        conn.close()


def delete_question(qid, db_path=None):
    """
    删除一道题。返回是否真的删掉了（True/False）。
    db_path: 可选，指定数据库文件路径（测试用）。
    """
    conn = _connect(db_path)
    try:
        _init_table(conn)
        cur = conn.execute("DELETE FROM questions WHERE id = ?", (qid,))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def update_category(qid, category, db_path=None):
    """
    修改一道题的分类。返回是否真的改到了（True/False）。
    db_path: 可选，指定数据库文件路径（测试用）。
    """
    conn = _connect(db_path)
    try:
        _init_table(conn)
        cur = conn.execute(
            "UPDATE questions SET category = ? WHERE id = ?",
            (category, qid),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def list_categories(db_path=None):
    """
    列出所有分类（去重）。
    db_path: 可选，指定数据库文件路径（测试用）。
    """
    conn = _connect(db_path)
    try:
        _init_table(conn)
        rows = conn.execute(
            "SELECT DISTINCT category FROM questions WHERE category != '' ORDER BY category"
        ).fetchall()
        return [r["category"] for r in rows]
    finally:
        conn.close()
