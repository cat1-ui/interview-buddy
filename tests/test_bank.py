# -*- coding: utf-8 -*-
"""
bank 模块的单元测试。
用 tmp_path 注入 db_path，隔离真实题库文件，验证增删查、去重、分类。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import bank


def _dialogue(text):
    return [{"role": "interviewer", "content": text}]


def test_add_question_and_dedup(tmp_path):
    db = str(tmp_path / "bank.db")

    qid1, created1 = bank.add_question(
        "什么是 RAG？", _dialogue("什么是 RAG？"),
        category="RAG", topic="RAG", source_key="sess:1", db_path=db,
    )
    assert created1 is True
    assert qid1 is not None

    # 相同 source_key 再次收藏 -> 去重，返回已有 id，不新建
    qid2, created2 = bank.add_question(
        "什么是 RAG？", _dialogue("什么是 RAG？"),
        category="RAG", topic="RAG", source_key="sess:1", db_path=db,
    )
    assert created2 is False
    assert qid2 == qid1

    # 不同 source_key -> 正常插入
    qid3, created3 = bank.add_question(
        "什么是 RAG？", _dialogue("什么是 RAG？"),
        category="RAG", topic="RAG", source_key="sess:2", db_path=db,
    )
    assert created3 is True
    assert qid3 != qid1


def test_list_questions_filter_by_category(tmp_path):
    db = str(tmp_path / "bank.db")
    bank.add_question("A", _dialogue("A"), category="RAG", topic="RAG", source_key="sess:1", db_path=db)
    bank.add_question("B", _dialogue("B"), category="Agent", topic="Agent", source_key="sess:2", db_path=db)

    all_q = bank.list_questions(db_path=db)
    assert len(all_q) == 2

    rag_q = bank.list_questions(category="RAG", db_path=db)
    assert len(rag_q) == 1
    assert rag_q[0]["question"] == "A"


def test_delete_and_update_category_return_bool(tmp_path):
    db = str(tmp_path / "bank.db")
    qid, _ = bank.add_question("A", _dialogue("A"), category="RAG", topic="RAG", source_key="sess:1", db_path=db)

    assert bank.delete_question(qid, db_path=db) is True
    assert bank.delete_question(qid, db_path=db) is False  # 已删除，再删返回 False

    qid2, _ = bank.add_question("B", _dialogue("B"), category="RAG", topic="RAG", source_key="sess:2", db_path=db)
    assert bank.update_category(qid2, "Agent", db_path=db) is True
    assert bank.update_category(9999, "Agent", db_path=db) is False  # 不存在


def test_list_categories_dedup_and_sorted(tmp_path):
    db = str(tmp_path / "bank.db")
    bank.add_question("A", _dialogue("A"), category="RAG", topic="RAG", source_key="sess:1", db_path=db)
    bank.add_question("B", _dialogue("B"), category="RAG", topic="RAG", source_key="sess:2", db_path=db)
    bank.add_question("C", _dialogue("C"), category="Agent", topic="Agent", source_key="sess:3", db_path=db)

    cats = bank.list_categories(db_path=db)
    assert cats == ["Agent", "RAG"]  # 去重 + ORDER BY category 升序