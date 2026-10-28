// 后端 API 封装：统一管理所有接口的类型和调用。

const BASE = '/api'

// 从后端返回的错误体里，提取出人类可读的错误信息。
// FastAPI 的校验错误，detail 是数组（[{loc, msg, type}...]），
// 其他错误 detail 通常是字符串。这里统一处理，避免显示成 [object Object]。
function extractErrorDetail(body: unknown, status: number): string {
  if (!body || typeof body !== 'object') {
    return `请求失败（${status}）`
  }
  const detail = (body as { detail?: unknown }).detail
  if (typeof detail === 'string' && detail) {
    return detail
  }
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string }
    if (first && typeof first.msg === 'string') {
      return first.msg
    }
  }
  return `请求失败（${status}）`
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(extractErrorDetail(body, res.status))
  }
  return res.json() as Promise<T>
}

// ============ SSE 流式读取 ============

type StreamHandler = {
  onMeta?: (meta: Record<string, unknown>) => void
  onDelta?: (content: string) => void
  onDone?: () => void
  onError?: (message: string) => void
}

// 打字机速度：每多少毫秒输出一个字（让流式输出看起来匀速、平滑）
const TYPEWRITER_INTERVAL = 30

/**
 * 打字机缓冲器：把模型不均匀吐出的文字，攒起来后按固定节奏匀速吐出。
 * 设计要点：
 *   - 收到的字先完整存入 pending 字符串（绝不丢字）
 *   - 一个持续的 interval 每 30ms 从 pending 取一个字符吐给 onDelta
 *   - 收到 done 后不停止 interval，等 pending 全部吐完才回调 onDone
 */
function createTypewriter(onDelta: (chunk: string) => void) {
  let pending = '' // 待输出的完整字符串（按字符）
  let timer: ReturnType<typeof setInterval> | null = null
  let ended = false // 是否已收到 done
  let onDoneCallback: () => void = () => {}

  function tick() {
    if (pending.length === 0) {
      if (ended) {
        // 队列已清空且已结束，停止并回调
        stop()
        onDoneCallback()
      }
      return
    }
    // 每次吐一个字符（用 Array.from 保证中文一个字、英文一个字母都算一个字符）
    const chars = Array.from(pending)
    const ch = chars[0]
    pending = chars.slice(1).join('')
    onDelta(ch)
  }

  function start() {
    if (timer) return
    timer = setInterval(tick, TYPEWRITER_INTERVAL)
  }

  function stop() {
    if (timer) {
      clearInterval(timer)
      timer = null
    }
  }

  return {
    push(text: string) {
      pending += text
      start()
    },
    finish(cb: () => void) {
      if (ended) return
      ended = true
      onDoneCallback = cb
      // 如果已经吐完了，直接结束
      if (pending.length === 0) {
        stop()
        cb()
      }
    },
    stop,
  }
}

/**
 * 发起一个 SSE 流式请求，逐事件回调。
 * 事件格式：data: {"type":"meta"/"delta"/"done"/"error", ...}
 * delta 文字会经过打字机缓冲，匀速吐出（而非模型吐多快就显示多快）。
 */
async function streamRequest(path: string, body: unknown, handler: StreamHandler): Promise<void> {
  const res = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok || !res.body) {
    throw new Error(`请求失败（${res.status}）`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  // 只有提供了 onDelta 时才启用打字机缓冲
  const typewriter = handler.onDelta
    ? createTypewriter(handler.onDelta)
    : null

  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })

      const lines = buffer.split('\n\n')
      buffer = lines.pop() ?? ''

      for (const block of lines) {
        for (const line of block.split('\n')) {
          if (!line.startsWith('data:')) continue
          const dataStr = line.slice(5).trim()
          if (!dataStr) continue
          try {
            const event = JSON.parse(dataStr)
            switch (event.type) {
              case 'meta':
                handler.onMeta?.(event)
                break
              case 'delta':
                if (typewriter) {
                  typewriter.push(event.content ?? '')
                } else {
                  handler.onDelta?.(event.content ?? '')
                }
                break
              case 'done':
                if (typewriter) {
                  typewriter.finish(() => handler.onDone?.())
                } else {
                  handler.onDone?.()
                }
                break
              case 'error':
                typewriter?.stop()
                handler.onError?.(event.message ?? '出错了')
                break
            }
          } catch {
            // 忽略无法解析的事件
          }
        }
      }
    }
  } finally {
    // 读取结束后，确保缓冲里的字吐完
    if (typewriter) {
      typewriter.finish(() => handler.onDone?.())
    }
  }
}

// ============ 类型定义（对应后端返回结构） ============

export interface InterviewStartResponse {
  session_id: string
  question: string
}

export interface InterviewAnswerResponse {
  reply: string
  finished: boolean
  question_count: number
  followup_count: number
}

export interface ScoreResult {
  准确性?: number
  深度?: number
  表达清晰度?: number
  总分?: number
  总评?: string
  不完整面试?: boolean
  [key: string]: unknown
}

export interface ReviewQuestion {
  index: number
  question: string
  dialogue: { role: string; content: string }[]
}

export interface ReviewResponse {
  session_id: string
  topic: string | null
  finished: boolean
  questions: ReviewQuestion[]
}

export interface BankItem {
  id: number
  question: string
  dialogue: { role: string; content: string }[]
  category: string
  topic: string
  created_at: string
}

export interface AskResponse {
  answer: string
  sources: { filename: string; score: number }[]
}

// ============ 面试相关 ============

export function startInterview(topic?: string) {
  return request<InterviewStartResponse>('/interview/new', {
    method: 'POST',
    // 没填方向时，不传 topic 字段（而不是传 null，后端会拒绝 null）
    body: JSON.stringify(topic ? { topic } : {}),
  })
}

export function answerInterview(sessionId: string, answer: string) {
  return request<InterviewAnswerResponse>('/interview/answer', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, answer }),
  })
}

export function finishInterview(sessionId: string) {
  return request<{ score: ScoreResult }>('/interview/finish', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  })
}

export function getReview(sessionId: string) {
  return request<ReviewResponse>(`/interview/${sessionId}/review`)
}

export interface SessionInfo {
  question_count: number
  followup_count: number
  current_question: string | null
  history: { role: string; content: string }[]
  finished: boolean
  topic: string | null
}

export function getSessionInfo(sessionId: string) {
  return request<SessionInfo>(`/interview/${sessionId}`)
}

// ============ 知识库问答 ============

export function askKnowledge(question: string) {
  return request<AskResponse>('/ask', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })
}

export function buildKnowledge() {
  return request<{ status: string; chunk_count: number }>('/build', {
    method: 'POST',
  })
}

// ============ 资料管理（上传/列表/删除） ============

export interface DocItem {
  filename: string
  size: number
  modified: number
}

export async function uploadDocs(files: File[]) {
  const formData = new FormData()
  files.forEach((f) => formData.append('files', f))
  let res: Response
  try {
    res = await fetch(`${BASE}/upload`, { method: 'POST', body: formData })
  } catch {
    throw new Error('无法连接服务器，请确认后端已启动（8000 端口）')
  }
  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new Error(body?.detail || `上传失败（${res.status}）`)
  }
  return res.json() as Promise<{ status: string; saved: string[]; chunk_count: number }>
}

export function listDocs() {
  return request<DocItem[]>('/files')
}

export function deleteDoc(filename: string) {
  return request<{ status: string; filename: string; chunk_count: number }>(
    `/files/${encodeURIComponent(filename)}`,
    { method: 'DELETE' },
  )
}

// ============ 题库 ============

export function collectQuestion(sessionId: string, index?: number, category?: string) {
  return request<{ id: number }>('/bank/collect', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, index: index ?? null, category: category || '' }),
  })
}

export function listBank(category?: string) {
  const q = category ? `?category=${encodeURIComponent(category)}` : ''
  return request<BankItem[]>(`/bank/list${q}`)
}

export function listCategories() {
  return request<string[]>('/bank/categories')
}

export function deleteBankItem(id: number) {
  return request<{ status: string; id: number }>(`/bank/${id}`, { method: 'DELETE' })
}

export function updateBankCategory(id: number, category: string) {
  return request<{ status: string; id: number; category: string }>(`/bank/${id}/category`, {
    method: 'PUT',
    body: JSON.stringify({ category }),
  })
}

// ============ 流式接口 ============

export function askKnowledgeStream(
  question: string,
  handlers: {
    onMeta?: (sources: { filename: string; score: number }[]) => void
    onDelta?: (content: string) => void
    onDone?: () => void
    onError?: (message: string) => void
  },
) {
  return streamRequest('/ask/stream', { question }, {
    onMeta: (meta) => handlers.onMeta?.((meta.sources as { filename: string; score: number }[]) ?? []),
    onDelta: handlers.onDelta,
    onDone: handlers.onDone,
    onError: handlers.onError,
  })
}

export function answerInterviewStream(
  sessionId: string,
  answer: string,
  handlers: {
    onMeta?: (meta: { finished: boolean; question_count: number; followup_count: number }) => void
    onDelta?: (content: string) => void
    onDone?: () => void
    onError?: (message: string) => void
  },
) {
  return streamRequest('/interview/answer/stream', { session_id: sessionId, answer }, {
    onMeta: (meta) =>
      handlers.onMeta?.({
        finished: Boolean(meta.finished),
        question_count: Number(meta.question_count ?? 0),
        followup_count: Number(meta.followup_count ?? 0),
      }),
    onDelta: handlers.onDelta,
    onDone: handlers.onDone,
    onError: handlers.onError,
  })
}
