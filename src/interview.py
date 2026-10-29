# -*- coding: utf-8 -*-
"""
面试搭子 - 模拟面试模块
=================================================
面试官角色：出题 → 追问 → 打分。

设计：
    InterviewService 管理多场面试会话（内存字典）
    每个会话维护：对话历史、是否结束等状态

出题逻辑：
    知识库（RAG 检索）+ 通用知识，混合出题
"""

from fastapi import HTTPException
from openai import OpenAI

from src.config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, DEEPSEEK_MODEL
from src.rag import RagService


def _raise_llm_error(exc):
    """把调用上游大模型的异常，统一翻译成 502 错误。"""
    raise HTTPException(status_code=502, detail=f"调用大模型失败：{exc}")


# ============ 面试官 prompt ============

# 系统提示：面试官的人设和规则
INTERVIEWER_SYSTEM = """你是一位严谨但友好的技术面试官，正在面试一位应聘 AI 应用开发岗位的候选人。

你的职责：
1. 出题：围绕 AI 应用开发相关知识提问（如大模型、RAG、Agent、Prompt、Python 等）
2. 追问：如果候选人回答得比较浅、不完整，就追问细节，挖得更深
3. 过渡：回答得不错，就自然进入下一题

出题要求：
- 题目要具体、有深度，不要问太宽泛或太简单的问题
- 优先问候选人简历/项目相关的技术点（如果提供了相关资料）

追问要求：
- 候选人回答得浅（只说结论没说原理），就追问"为什么""底层是什么"
- 候选人回答得完整深入，就肯定并进入下一题

风格：
- 像真人面试官，自然、专业，不机械
- 一次只问一个问题，不要说太多
"""

# 出题的 prompt
GENERATE_QUESTION_PROMPT = """你是一位技术面试官，请出一道 AI 应用开发相关的面试题。

要求：
1. 题目要具体、有深度
2. 围绕以下方向之一：大模型原理、RAG、Agent/Function Calling、Prompt 工程、Python 后端
3. 只输出题目本身，不要解释，不要加"面试官说"之类的前缀

{extra_context}
"""

# 追问/评价的 prompt
EVALUATE_AND_RESPOND_PROMPT = """你是一位技术面试官。候选人刚才回答了你的问题，请根据下面的"指令"给出回应。

面试题：{question}
候选人回答：{answer}

本次回应的指令（mode）是：{mode}

各 mode 的含义和你的做法：
- followup：候选人回答得浅或不完整，请针对薄弱点追问一个更深入的问题（只问一个最关键的问题）。
- comfort：候选人明确表示不会/不知道，请给一句很简短的安抚（比如"没关系，我们看下一题"），不要点评、不要评判，也不要出下一题（下一题由系统另出）。
- advance：本题追问次数已用满，请给一句很简短的换题提示（比如"好的，我们进入下一题"），不要点评刚才的回答，也不要出下一题（下一题由系统另出）。
- farewell：面试已经问满题目、正常收尾，请给一句得体的告别话（比如"好的，今天的面试就到这里，感谢你的参与"），简短、温暖，不要点评、不要出下一题。

要求：
- 严格按照上面 mode 对应的做法来，不要做 mode 之外的事
- 输出要自然，像真人面试官说话，不要让候选人感到被刁难
- 不要输出分析过程，直接输出你要对候选人说的话
"""

# 最终打分的 prompt
SCORE_PROMPT = """你是一位技术面试官，面试已经结束。以下是完整的面试记录，请给候选人的表现打分。

面试记录：
{history}

请严格按照以下要求打分，只从这三个维度，不要增加其他维度：

1. 准确性：回答是否正确、有无明显错误
2. 深度：是否讲到了原理、底层，还是停留在表面
3. 表达清晰度：逻辑是否清晰、有条理

评分标准（每个维度都是 1-10 的整数）：
- 1-3 分：回答错误或基本没答出来
- 4-6 分：答对但浅显，停留在表面
- 7-8 分：答得较好，讲到了关键点
- 9-10 分：回答完整深入，能讲清原理和细节

请只输出以下 JSON 格式，不要输出任何其他内容，不要加代码块标记：
{{
  "准确性": 整数,
  "深度": 整数,
  "表达清晰度": 整数,
  "总评": "一段话的总体评价和改进建议"
}}
"""

# 面试提前结束时的简评分 prompt
SHORT_SCORE_PROMPT = """你是一位技术面试官。候选人在面试中途提前结束了（最后一道追问没有回答）。以下是已有的面试记录：

面试记录：
{history}

请基于候选人已经回答的内容，给一个简短的评分。

请严格按照以下要求，只从三个维度打分，不要增加其他维度：
1. 准确性：回答是否正确
2. 深度：是否讲到了原理
3. 表达清晰度：逻辑是否清晰

评分标准（每个维度都是 1-10 的整数）：
- 1-3 分：回答错误或基本没答出来
- 4-6 分：答对但浅显
- 7-8 分：答得较好
- 9-10 分：回答完整深入

请只输出以下 JSON 格式，不要输出任何其他内容，不要加代码块标记：
{{
  "准确性": 整数,
  "深度": 整数,
  "表达清晰度": 整数,
  "总评": "一段话的简短评价，并说明这是不完整面试的评分"
}}
"""


class InterviewSession:
    """一场面试的会话状态"""

    def __init__(self):
        self.history = []      # 对话历史（扁平的，打分时拼全文用）[{"role", "content"}]
        self.questions = []    # 按题分组：[{"question": str, "dialogue": [{"role","content"}...]}]
        self.question_count = 0  # 已出题数
        self.finished = False    # 是否已结束
        self.completed = False   # 是否"答满 5 题自然结束"（区别于提前结束）
        self.current_question = None  # 当前正在问的题（题目文本）
        self.followup_count = 0  # 当前题目已追问的次数
        self.topic = None      # 面试方向（如"RAG"），None 表示不指定
        self.last_active = None  # 最近一次活动时间（用于过期清理）

    def touch(self):
        """更新最近活动时间。"""
        import time
        self.last_active = time.time()

    @property
    def current_q(self):
        """当前这道题的分组（questions 的最后一个），若没有则 None。"""
        return self.questions[-1] if self.questions else None


# 面试参数
MAX_QUESTIONS = 5      # 一场面试最多几道题
MAX_FOLLOWUPS = 2      # 同一道题最多追问几次（候选人一题最多答 1 + 2 = 3 次）
SESSION_TTL = 2 * 60 * 60  # 会话过期时间（秒）：2 小时无活动视为僵尸会话


class InterviewService:
    def __init__(self, rag_service: RagService):
        self.client = OpenAI(
            api_key=DEEPSEEK_API_KEY,
            base_url=DEEPSEEK_BASE_URL,
            timeout=60.0,  # 请求超时，防止上游挂起导致请求卡死
        )
        self.rag_service = rag_service
        self.vector_store = rag_service.vector_store  # 拿到向量库，用于随机取知识点
        self.sessions = {}  # session_id -> InterviewSession

    def _cleanup_expired(self):
        """
        惰性清理过期会话（新建会话时调用）。
        清理规则：
            - 已结束的会话 -> 直接移除（它的价值要么已进题库，要么本就不该留）
            - 超过 SESSION_TTL 秒无活动的进行中会话 -> 视为僵尸，移除
        """
        import time
        now = time.time()
        expired_ids = [
            sid for sid, s in self.sessions.items()
            if s.finished
            or (s.last_active is not None and now - s.last_active > SESSION_TTL)
        ]
        for sid in expired_ids:
            self.sessions.pop(sid, None)

    def new_session(self, topic=None):
        """新建一场面试，返回 session_id。topic 为面试方向（可选）。"""
        import uuid
        self._cleanup_expired()  # 顺便清理过期的旧会话
        # 开新面试，清空上一场的 TTS 缓存（语音缓存随"当前这场"走）
        from src import tts
        tts.tts_cache.clear()
        session_id = str(uuid.uuid4())
        session = InterviewSession()
        session.topic = topic
        session.touch()
        self.sessions[session_id] = session
        return session_id

    def _build_question_context(self, session):
        """
        构造"出题素材"：有方向就用方向检索知识库，否则随机取知识库内容。
        返回一段 extra_context 文本，供出题 prompt 使用。
        """
        if session.topic:
            # 指定了方向：用方向去检索知识库，取最相关的内容
            try:
                from src import embedding
                topic_vector = embedding.embed_text(session.topic)
                related = self.vector_store.search(topic_vector, top_k=3)
                if related:
                    context_lines = [f"【知识点片段】{r['content']}" for r in related]
                    return (
                        f"面试方向是「{session.topic}」，请严格围绕这个方向出题。"
                        "以下是知识库里与该方向最相关的内容，请基于这些内容出题：\n"
                        + "\n\n".join(context_lines)
                    )
                else:
                    return f"面试方向是「{session.topic}」，请围绕这个方向出题（知识库中没有相关内容，请用你的通用知识）。"
            except Exception:
                # 检索失败，退化为"只用方向词出题"
                return f"面试方向是「{session.topic}」，请围绕这个方向出题。"

        # 没指定方向：随机取知识库内容
        samples = self.vector_store.random_sample(3)
        if samples:
            context_lines = [f"【知识点片段】{s['content']}" for s in samples]
            return (
                "以下是候选人知识库里的一些内容，请围绕这些内容出题（考察候选人对这些知识的掌握）：\n"
                + "\n\n".join(context_lines)
            )
        return ""

    def _generate_question(self, session):
        """
        出一道题：构造素材 → 调模型 → 更新计数器与历史。
        返回题目文本。
        """
        extra_context = self._build_question_context(session)
        prompt = GENERATE_QUESTION_PROMPT.format(extra_context=extra_context)
        try:
            response = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": INTERVIEWER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
            )
        except Exception as exc:
            _raise_llm_error(exc)
        question = response.choices[0].message.content.strip()

        session.current_question = question
        session.question_count += 1
        session.followup_count = 0  # 新题，追问计数归零
        # 记录到扁平历史（打分拼全文用）
        session.history.append({"role": "interviewer", "content": question})
        # 新建一道题的"分组"，后续的追问/回答都记在这个分组里
        session.questions.append({
            "question": question,
            "dialogue": [{"role": "interviewer", "content": question}],
        })

        return question

    def start_question(self, session_id):
        """出第一道题"""
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")
        return self._generate_question(session)

    def _looks_like_give_up(self, answer_text):
        """
        判断候选人是否"明确表示不知道/不会"。
        命中这些词，就认为这道题答不下去了，停止追问、直接换题。
        """
        keywords = [
            "不知道", "不清楚", "不会", "不懂", "不了解",
            "没学过", "没接触过", "没听说过", "想不起来", "没有接触",
        ]
        answer = answer_text.strip()
        for kw in keywords:
            if kw in answer:
                return True
        return False

    def _respond(self, session, question, answer, mode):
        """
        调模型生成面试官的一句话回应。
        mode 决定模型该说什么：
            "followup"  -> 追问（候选人答得浅，挖深一层）
            "comfort"   -> 安抚一句后换题（候选人说不知道）
            "advance"   -> 换题提示（追问满 2 次，不再点评，直接带出下一题）
            "farewell"  -> 告别话（面试正常收尾）
        返回回应文本。
        """
        prompt = EVALUATE_AND_RESPOND_PROMPT.format(
            question=question,
            answer=answer,
            mode=mode,
        )
        try:
            response = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": INTERVIEWER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
            )
        except Exception as exc:
            _raise_llm_error(exc)
        return response.choices[0].message.content.strip()

    def _respond_stream(self, session, question, answer, mode):
        """
        _respond 的流式版本：逐段 yield 面试官的回应文本。
        """
        prompt = EVALUATE_AND_RESPOND_PROMPT.format(
            question=question,
            answer=answer,
            mode=mode,
        )
        try:
            stream = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": INTERVIEWER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                stream=True,
            )
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as exc:
            _raise_llm_error(exc)

    def _generate_question_stream(self, session):
        """
        _generate_question 的流式版本：逐段 yield 新题的文本。
        注意：计数器更新、历史记录这些"确定性"操作在 yield 之前就完成，
        保证 meta 里的 question_count 是正确的。
        """
        extra_context = self._build_question_context(session)
        prompt = GENERATE_QUESTION_PROMPT.format(extra_context=extra_context)
        try:
            stream = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[
                    {"role": "system", "content": INTERVIEWER_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.8,
                stream=True,
            )
            parts = []
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    parts.append(delta)
                    yield delta
            question = "".join(parts).strip()
        except Exception as exc:
            _raise_llm_error(exc)

        # 更新计数器与历史（在流式吐完之后，再更新状态，保证 meta 正确）
        session.current_question = question
        session.question_count += 1
        session.followup_count = 0
        session.history.append({"role": "interviewer", "content": question})
        session.questions.append({
            "question": question,
            "dialogue": [{"role": "interviewer", "content": question}],
        })

    def _append(self, session, role, content):
        """同时把一句话记到「扁平历史」和「当前题的分组对话」里。"""
        session.history.append({"role": role, "content": content})
        q = session.current_q
        if q is not None:
            q["dialogue"].append({"role": role, "content": content})

    @staticmethod
    def _answer_result(session, reply, finished):
        """统一构造 answer 的返回，带上当前进度计数，供前端状态条精确展示。"""
        return {
            "reply": reply,
            "finished": finished,
            "question_count": session.question_count,
            "followup_count": session.followup_count,
        }

    def answer(self, session_id, answer_text):
        """
        候选人回答问题。按优先级判断：
            判断1：是否说"不知道" -> 是则安抚后换题
            判断2：本题是否已追问满 MAX_FOLLOWUPS 次 -> 是则换题提示
            判断3：是否已满 MAX_QUESTIONS 题 -> 是则自动结束（告别话）
        返回 {"reply": 回应文本, "finished": 是否已结束}
        """
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")
        if session.finished:
            raise HTTPException(status_code=409, detail="面试已结束，无法继续回答")

        session.touch()
        # 记录候选人的回答
        self._append(session, "candidate", answer_text)

        # 是否已经是最后一道题（答完这道就该结束）
        is_last_question = session.question_count >= MAX_QUESTIONS

        # ---- 判断1：说"不知道" -> 安抚（+换题或结束） ----
        if self._looks_like_give_up(answer_text):
            reply = self._respond(session, session.current_question, answer_text, "comfort")
            self._append(session, "interviewer", reply)
            # 已经是最后一题 -> 直接结束，不再换题
            if is_last_question:
                session.finished = True
                session.completed = True
                return self._answer_result(session, reply, True)
            # 未满则出一道新题，和安抚语一起返回
            next_question = self._generate_question(session)
            return self._answer_result(session, reply + "\n\n" + next_question, False)

        # ---- 判断2：追问满 2 次 -> 换题提示（+换题或结束） ----
        if session.followup_count >= MAX_FOLLOWUPS:
            reply = self._respond(session, session.current_question, answer_text, "advance")
            self._append(session, "interviewer", reply)
            if is_last_question:
                session.finished = True
                session.completed = True
                return self._answer_result(session, reply, True)
            next_question = self._generate_question(session)
            return self._answer_result(session, reply + "\n\n" + next_question, False)

        # ---- 判断3：不是最后一题，还能追问 -> 追问 ----
        # （最后一题不会走到"追问"：若既没说不知道、追问也还没满，但已到最后一题，
        #   则用告别话正常收尾结束，不再追问。）
        if is_last_question:
            reply = self._respond(session, session.current_question, answer_text, "farewell")
            session.finished = True
            session.completed = True
            self._append(session, "interviewer", reply)
            return self._answer_result(session, reply, True)

        reply = self._respond(session, session.current_question, answer_text, "followup")
        session.followup_count += 1
        self._append(session, "interviewer", reply)
        return self._answer_result(session, reply, False)

    def answer_stream(self, session_id, answer_text):
        """
        answer 的流式版本。逐段 yield SSE 事件字符串：
            meta（先发，带 finished / question_count / followup_count）
            -> 多个 delta（面试官回应文本，逐段）
            -> done

        逻辑与 answer() 完全一致，只是"生成"这一步用流式。
        关键：meta 里的计数在发 meta 前就提前算好，保证前端状态条立即准确。
        """
        from src.streaming import meta_event, delta_event, done_event

        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")
        if session.finished:
            raise HTTPException(status_code=409, detail="面试已结束，无法继续回答")

        session.touch()
        self._append(session, "candidate", answer_text)

        is_last_question = session.question_count >= MAX_QUESTIONS

        # ---- 判断1：说"不知道" ----
        if self._looks_like_give_up(answer_text):
            if is_last_question:
                # 结束
                finished = True
                session.finished = True
                session.completed = True
                meta = {"finished": True, "question_count": session.question_count, "followup_count": session.followup_count}
                yield meta_event(**meta)
                reply_parts = []
                for d in self._respond_stream(session, session.current_question, answer_text, "comfort"):
                    reply_parts.append(d)
                    yield delta_event(d)
                self._append(session, "interviewer", "".join(reply_parts).strip())
            else:
                # 安抚 + 换题
                session.followup_count = 0  # 换题，追问归零
                new_qc = session.question_count + 1
                meta = {"finished": False, "question_count": new_qc, "followup_count": 0}
                yield meta_event(**meta)
                reply_parts = []
                for d in self._respond_stream(session, session.current_question, answer_text, "comfort"):
                    reply_parts.append(d)
                    yield delta_event(d)
                comfort_text = "".join(reply_parts).strip()
                self._append(session, "interviewer", comfort_text)
                yield delta_event("\n\n")
                for d in self._generate_question_stream(session):
                    yield delta_event(d)
            yield done_event()
            return

        # ---- 判断2：追问满 2 次 ----
        if session.followup_count >= MAX_FOLLOWUPS:
            if is_last_question:
                session.finished = True
                session.completed = True
                meta = {"finished": True, "question_count": session.question_count, "followup_count": session.followup_count}
                yield meta_event(**meta)
                reply_parts = []
                for d in self._respond_stream(session, session.current_question, answer_text, "advance"):
                    reply_parts.append(d)
                    yield delta_event(d)
                self._append(session, "interviewer", "".join(reply_parts).strip())
            else:
                session.followup_count = 0
                new_qc = session.question_count + 1
                meta = {"finished": False, "question_count": new_qc, "followup_count": 0}
                yield meta_event(**meta)
                reply_parts = []
                for d in self._respond_stream(session, session.current_question, answer_text, "advance"):
                    reply_parts.append(d)
                    yield delta_event(d)
                advance_text = "".join(reply_parts).strip()
                self._append(session, "interviewer", advance_text)
                yield delta_event("\n\n")
                for d in self._generate_question_stream(session):
                    yield delta_event(d)
            yield done_event()
            return

        # ---- 判断3：最后一题 -> 告别；否则追问 ----
        if is_last_question:
            session.finished = True
            session.completed = True
            meta = {"finished": True, "question_count": session.question_count, "followup_count": session.followup_count}
            yield meta_event(**meta)
            reply_parts = []
            for d in self._respond_stream(session, session.current_question, answer_text, "farewell"):
                reply_parts.append(d)
                yield delta_event(d)
            self._append(session, "interviewer", "".join(reply_parts).strip())
            yield done_event()
            return

        # 追问
        new_fc = session.followup_count + 1
        meta = {"finished": False, "question_count": session.question_count, "followup_count": new_fc}
        yield meta_event(**meta)
        reply_parts = []
        for d in self._respond_stream(session, session.current_question, answer_text, "followup"):
            reply_parts.append(d)
            yield delta_event(d)
        session.followup_count = new_fc
        self._append(session, "interviewer", "".join(reply_parts).strip())
        yield done_event()

    def collect_question(self, session_id, index=None, category=""):
        """
        收藏某一道题到题库。
        index: 第几题（1 开始）。不传则默认收藏"当前这道题"（向后兼容）。
        返回新题目的 id；若指定题不存在，抛 404。
        同一道题（同一 session 的同一 index）重复收藏会去重，返回已有记录的 id。
        """
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")

        if index is None:
            q = session.current_q
            # 没有指定 index 时，用当前题的下标作为去重标识
            idx = session.question_count
        else:
            # index 从 1 开始，转成列表下标
            if index < 1 or index > len(session.questions):
                raise HTTPException(status_code=404, detail="题目不存在")
            q = session.questions[index - 1]
            idx = index

        if q is None:
            return None

        from src import bank
        source_key = f"{session_id}:{idx}"
        qid, _ = bank.add_question(
            question=q["question"],
            dialogue=q["dialogue"],
            category=category,
            topic=session.topic or "",
            source_key=source_key,
        )
        return qid

    def get_review(self, session_id):
        """
        复盘：返回整场面试的按题分组记录，供前端做复盘表。
        返回 {"session_id", "topic", "finished", "questions": [{"index", "question", "dialogue"}]}
        """
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")

        questions = [
            {
                "index": i + 1,
                "question": q["question"],
                "dialogue": q["dialogue"],
            }
            for i, q in enumerate(session.questions)
        ]
        return {
            "session_id": session_id,
            "topic": session.topic,
            "finished": session.finished,
            "questions": questions,
        }

    def finish(self, session_id):
        """结束面试，生成打分报告"""
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")

        session.finished = True

        # 把历史拼成文本
        history_text = "\n".join(
            f"{'面试官' if h['role'] == 'interviewer' else '候选人'}：{h['content']}"
            for h in session.history
        )

        # 判断是否"提前结束"：没答满 5 题就结束的，视为不完整面试
        is_incomplete = not session.completed

        # 选择对应的打分 prompt
        score_prompt = SHORT_SCORE_PROMPT if is_incomplete else SCORE_PROMPT
        prompt = score_prompt.format(history=history_text)
        try:
            response = self.client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,  # 打分要稳定
                response_format={"type": "json_object"},  # 强制只输出合法 JSON，避免解析失败
            )
        except Exception as exc:
            _raise_llm_error(exc)
        raw = response.choices[0].message.content.strip()

        # 解析 JSON（正常情况下 response_format 已保证是纯 JSON，这里的手撕只是兜底）
        import json
        try:
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.strip("`")
                if raw.startswith("json"):
                    raw = raw[4:]
            score = json.loads(raw)

            # 由代码计算总分（不依赖大模型算，保证准确）
            dims = ["准确性", "深度", "表达清晰度"]
            try:
                values = [int(score.get(d, 0)) for d in dims]
                total = round(sum(values) / len(values), 1)
                score["总分"] = total
            except Exception:
                pass  # 算不出总分就跳过，不影响其他字段

            # 标记是否不完整面试
            if is_incomplete:
                score["不完整面试"] = True

            return score
        except Exception:
            return {"总评": raw}

    def stop(self, session_id):
        """主动停止面试（不评分）"""
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")
        session.finished = True
        return "面试已结束"

    def get_session_info(self, session_id):
        """
        找回一场面试的当前状态（前端刷新页面后用）。
        返回 {"question_count", "followup_count", "current_question", "history", "finished", "topic"}
        若会话不存在，抛 404。
        """
        session = self.sessions.get(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="面试会话不存在")
        return {
            "question_count": session.question_count,
            "followup_count": session.followup_count,
            "current_question": session.current_question,
            "history": session.history,
            "finished": session.finished,
            "topic": session.topic,
        }
