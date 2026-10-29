import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { cn } from '@/lib/utils'
import {
  startInterview,
  answerInterview,
  finishInterview,
  getSessionInfo,
  synthesizeSpeech,
} from '@/lib/api'
import { setRecentSessionId } from '@/lib/recentInterview'
import { toast } from '@/components/ui/toast'
import { Spinner } from '@/components/ui/spinner'

interface Message {
  role: 'interviewer' | 'candidate'
  content: string
}

const MAX_QUESTIONS = 5
const SESSION_KEY = 'interview_session_id'

// 模拟面试页：柔和、圆润、有温度的产品感设计
export default function InterviewPage() {
  const navigate = useNavigate()

  const [sessionId, setSessionId] = useState<string | null>(null)
  const [topic, setTopic] = useState('')
  const [messages, setMessages] = useState<Message[]>([])
  const [questionCount, setQuestionCount] = useState(0)
  const [followupCount, setFollowupCount] = useState(0)
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [finished, setFinished] = useState(false)
  const [restoring, setRestoring] = useState(false)

  // 语音播放相关状态
  const [speakingIndex, setSpeakingIndex] = useState<number | null>(null) // 正在合成/播放的消息下标
  const [playingIndex, setPlayingIndex] = useState<number | null>(null) // 正在播放中的消息下标
  const [paused, setPaused] = useState(false) // 当前语音是否被暂停
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, loading])

  // 组件卸载时停止语音播放，释放资源
  useEffect(() => {
    return () => {
      if (audioRef.current) {
        audioRef.current.pause()
        audioRef.current.src = ''
        audioRef.current = null
      }
    }
  }, [])

  // 页面加载时：尝试从 sessionStorage 恢复面试
  useEffect(() => {
    const savedId = sessionStorage.getItem(SESSION_KEY)
    if (!savedId) return

    setRestoring(true)
    getSessionInfo(savedId)
      .then((info) => {
        // 恢复状态（含已结束的面试：保留入口，让用户能回看复盘）
        setSessionId(savedId)
        setTopic(info.topic ?? '')
        setQuestionCount(info.question_count)
        setFollowupCount(info.followup_count)
        setFinished(info.finished)
        setMessages(
          info.history.map((h) => ({
            role: h.role as 'interviewer' | 'candidate',
            content: h.content,
          })),
        )
      })
      .catch(() => {
        // 会话过期或不存在，清掉失效的 id
        sessionStorage.removeItem(SESSION_KEY)
      })
      .finally(() => setRestoring(false))
  }, [navigate])

  async function handleStart() {
    setLoading(true)
    try {
      const res = await startInterview(topic.trim() || undefined)
      setSessionId(res.session_id)
      sessionStorage.setItem(SESSION_KEY, res.session_id)
      // 新面试：清掉上一场的分数缓存，重置结束态
      sessionStorage.removeItem('interview_last_score')
      setFinished(false)
      setQuestionCount(1)
      setFollowupCount(0)
      setMessages([{ role: 'interviewer', content: res.question }])
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }

  async function handleSend() {
    const text = input.trim()
    if (!text || !sessionId || loading || finished) return
    setInput('')
    setMessages((prev) => [...prev, { role: 'candidate', content: text }])
    setLoading(true)

    try {
      const res = await answerInterview(sessionId, text)
      setMessages((prev) => [...prev, { role: 'interviewer', content: res.reply }])
      setQuestionCount(res.question_count)
      setFollowupCount(res.followup_count)

      if (res.finished) {
        setFinished(true)
        // 面试结束：记录"最近一场"，供复盘页读取；不强制跳转、不清存储
        setRecentSessionId(sessionId)
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }

  async function handleFinish() {
    if (!sessionId || finished) return
    setLoading(true)
    try {
      const res = await finishInterview(sessionId)
      setFinished(true)
      // 记录"最近一场"，供复盘页读取
      setRecentSessionId(sessionId)
      // 把分数暂存到 sessionStorage，复盘页可直接读取，避免再次调 finish
      if (res.score) {
        sessionStorage.setItem('interview_last_score', JSON.stringify(res.score))
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }

  // 结束后面向"再来一场"：回到开始表单，让用户能重新选方向 / 留空随机
  function handleReset() {
    setSessionId(null)
    setFinished(false)
    setMessages([])
    setQuestionCount(0)
    setFollowupCount(0)
    setInput('')
    setTopic('')
    sessionStorage.removeItem(SESSION_KEY)
    sessionStorage.removeItem('interview_last_score')
    // 停止并清理语音
    stopSpeech()
  }

  // 停止当前语音播放（并释放音频资源）
  function stopSpeech() {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current.src = ''
      audioRef.current = null
    }
    setSpeakingIndex(null)
    setPlayingIndex(null)
    setPaused(false)
  }

  // 播放某条面试官消息的语音：点击才合成，合成完自动播放
  async function handleSpeak(index: number) {
    const msg = messages[index]
    if (!msg || msg.role !== 'interviewer') return

    // 如果点的是正在播放/已暂停的那条 -> 切换 暂停/继续
    if (playingIndex === index && audioRef.current) {
      if (audioRef.current.paused) {
        await audioRef.current.play()
        setPaused(false)
      } else {
        audioRef.current.pause()
        setPaused(true)
      }
      return
    }

    // 正在合成或播放别的，先停掉旧的
    stopSpeech()

    setSpeakingIndex(index)
    try {
      const blob = await synthesizeSpeech(msg.content)
      const url = URL.createObjectURL(blob)
      const audio = new Audio(url)
      audio.onended = () => {
        setPlayingIndex(null)
        setPaused(false)
        URL.revokeObjectURL(url)
      }
      audioRef.current = audio
      setSpeakingIndex(null)
      setPlayingIndex(index)
      setPaused(false)
      await audio.play()
    } catch {
      toast('播放失败，请稍后再试', 'error')
      setSpeakingIndex(null)
      setPlayingIndex(null)
      setPaused(false)
    }
  }

  // 恢复中：显示加载
  if (restoring) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner className="text-primary" />
          <span>正在恢复面试…</span>
        </div>
      </div>
    )
  }

  if (!sessionId) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="w-full max-w-md space-y-7 px-6">
          <div className="space-y-3 text-center">
            <div className="mx-auto flex size-14 items-center justify-center rounded-lg bg-primary text-primary-foreground">
              <svg className="size-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
              </svg>
            </div>
            <h1 className="text-2xl font-medium tracking-tight">模拟面试</h1>
            <p className="text-sm leading-relaxed text-muted-foreground">
              和 AI 面试官来一场真实的对练，每场 5 题，随时开始。
            </p>
          </div>
          <div className="space-y-3 rounded-lg border border-border bg-card p-5">
            <input
              placeholder="面试方向（可选），如：RAG、Python…"
              value={topic}
              onChange={(e) => setTopic(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleStart()}
              className="h-11 w-full rounded-md border border-input bg-background px-4 text-sm outline-none transition-all placeholder:text-muted-foreground focus:border-ring focus:ring-2 focus:ring-ring/20"
            />
            <button
              onClick={handleStart}
              disabled={loading}
              className="h-11 w-full rounded-md bg-primary text-[15px] font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:opacity-50"
            >
              {loading ? '正在准备…' : '开始面试'}
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {/* 状态条 */}
      <div className="shrink-0 px-6 pt-5">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <span className="text-sm font-medium">第 {questionCount} 题</span>
              <span className="text-xs text-muted-foreground">/ 共 {MAX_QUESTIONS} 题</span>
              <span className="text-xs text-muted-foreground">· 已追问 {followupCount} 次</span>
              {topic && (
                <span className="rounded-md bg-accent px-2.5 py-0.5 text-xs text-primary">
                  {topic}
                </span>
              )}
            </div>
            <button
              onClick={handleFinish}
              disabled={loading || finished}
              className="text-xs text-muted-foreground transition-colors hover:text-destructive"
            >
              结束面试
            </button>
            {finished && (
              <button
                onClick={() => sessionId && navigate('/review')}
                className="rounded-md bg-primary px-3.5 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:opacity-90"
              >
                查看本次复盘
              </button>
            )}
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-secondary">
            <div
              className="h-full rounded-full bg-primary transition-all duration-500 ease-out"
              style={{ width: `${(questionCount / MAX_QUESTIONS) * 100}%` }}
            />
          </div>
        </div>
      </div>

      {/* 对话区 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl space-y-4 px-6 py-6">
          {messages.map((msg, i) => (
            <div key={i} className={cn('flex', msg.role === 'candidate' ? 'justify-end' : 'justify-start')}>
              <div className={cn('flex max-w-[78%] items-start gap-2.5', msg.role === 'candidate' && 'flex-row-reverse')}>
                <div
                  className={cn(
                    'mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-md text-[11px] font-medium',
                    msg.role === 'candidate'
                      ? 'bg-primary text-primary-foreground'
                      : 'bg-card text-primary ring-1 ring-border',
                  )}
                >
                  {msg.role === 'candidate' ? '我' : '面'}
                </div>
                <div className="flex flex-col gap-1.5">
                  <div
                    className={cn(
                      'whitespace-pre-wrap rounded-lg px-4 py-2.5 text-sm leading-relaxed',
                      msg.role === 'candidate'
                        ? 'rounded-tr-sm bg-primary text-primary-foreground'
                        : 'rounded-tl-sm border border-border bg-card text-foreground',
                    )}
                  >
                    {msg.content}
                  </div>
                  {msg.role === 'interviewer' && (
                    <button
                      onClick={() => handleSpeak(i)}
                      disabled={speakingIndex !== null || (playingIndex !== null && playingIndex !== i)}
                      className={cn(
                        'flex items-center gap-1.5 self-start rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors',
                        speakingIndex === i
                          ? 'opacity-50'
                          : playingIndex === i
                            ? 'text-primary'
                            : 'hover:bg-secondary hover:text-foreground',
                        (speakingIndex !== null && speakingIndex !== i) || (playingIndex !== null && playingIndex !== i)
                          ? 'cursor-not-allowed opacity-40'
                          : '',
                      )}
                    >
                      {speakingIndex === i ? (
                        <>
                          <Spinner className="text-primary" />
                          <span>合成中…</span>
                        </>
                      ) : playingIndex === i ? (
                        paused ? (
                          <>
                            <svg className="size-3.5" viewBox="0 0 24 24" fill="currentColor">
                              <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86a1 1 0 0 0-1.5.86z" />
                            </svg>
                            <span>继续</span>
                          </>
                        ) : (
                          <>
                            <svg className="size-3.5" viewBox="0 0 24 24" fill="currentColor">
                              <rect x="6" y="5" width="4" height="14" rx="1" />
                              <rect x="14" y="5" width="4" height="14" rx="1" />
                            </svg>
                            <span>暂停</span>
                          </>
                        )
                      ) : (
                        <>
                          <svg className="size-3.5" viewBox="0 0 24 24" fill="currentColor">
                            <path d="M8 5.14v13.72a1 1 0 0 0 1.5.86l11-6.86a1 1 0 0 0 0-1.72l-11-6.86a1 1 0 0 0-1.5.86z" />
                          </svg>
                          <span>播放</span>
                        </>
                      )}
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}

          {loading && (
            <div className="flex justify-start">
              <div className="flex items-start gap-2.5">
                <div className="mt-0.5 flex size-7 items-center justify-center rounded-md bg-card text-[11px] font-medium text-primary ring-1 ring-border">
                  面
                </div>
                <div className="flex items-center gap-2 rounded-lg rounded-tl-sm border border-border bg-card px-4 py-3">
                  <Spinner className="text-primary" />
                  <span className="text-sm text-muted-foreground">面试官正在思考…</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* 输入区 / 结束态操作区 */}
      <div className="shrink-0 px-6 pb-5">
        {finished ? (
          <div className="mx-auto max-w-3xl rounded-lg border border-border bg-card p-5">
            <p className="text-center text-sm text-muted-foreground">
              本场面试已结束
            </p>
            <div className="mt-4 flex justify-center gap-3">
              <button
                onClick={() => navigate('/review')}
                className="rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90"
              >
                查看本次复盘
              </button>
              <button
                onClick={handleReset}
                className="rounded-lg border border-border px-6 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-secondary"
              >
                再来一场
              </button>
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-3xl items-end gap-3 rounded-lg border border-border bg-card p-2">
            <textarea
              placeholder="输入你的回答…（Enter 发送，Shift+Enter 换行）"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  handleSend()
                }
              }}
              disabled={loading}
              rows={1}
              className="max-h-32 min-h-12 flex-1 resize-none bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-muted-foreground"
            />
            <button
              onClick={handleSend}
              disabled={loading || !input.trim()}
              className="flex size-11 shrink-0 items-center justify-center rounded-md bg-primary text-primary-foreground transition-colors hover:opacity-90 disabled:opacity-40"
            >
              <svg className="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                <path d="m22 2-7 20-4-9-9-4z" />
              </svg>
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
