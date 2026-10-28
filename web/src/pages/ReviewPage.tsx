import { useEffect, useState } from 'react'
import { useNavigate, useParams, useLocation } from 'react-router-dom'
import { cn } from '@/lib/utils'
import {
  getReview,
  collectQuestion,
  finishInterview,
  type ReviewResponse,
  type ScoreResult,
} from '@/lib/api'
import { toast } from '@/components/ui/toast'
import { Spinner } from '@/components/ui/spinner'

const DIMENSIONS = [
  { key: '准确性', label: '准确性' },
  { key: '深度', label: '深度' },
  { key: '表达清晰度', label: '表达清晰度' },
] as const

export default function ReviewPage() {
  const { sessionId } = useParams<{ sessionId: string }>()
  const location = useLocation()
  const navigate = useNavigate()

  // 从面试页跳转过来时，可能带了分数（finish 的返回值）
  const initialScore = (location.state as { score?: ScoreResult } | null)?.score

  const [score, setScore] = useState<ScoreResult | null>(initialScore ?? null)
  const [review, setReview] = useState<ReviewResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [collected, setCollected] = useState<Set<number>>(new Set())
  const [collecting, setCollecting] = useState<number | null>(null)

  useEffect(() => {
    if (!sessionId) return
    getReview(sessionId)
      .then(setReview)
      .catch((e) => toast((e as Error).message, 'error'))
      .finally(() => setLoading(false))

    // 如果从面试页跳转过来没带分数（比如刷新了页面），补调 finish 拿分数
    if (!score) {
      finishInterview(sessionId)
        .then((res) => setScore(res.score))
        .catch(() => {})
    }
  }, [sessionId])

  async function handleCollect(index: number) {
    if (!sessionId || collecting !== null) return
    setCollecting(index)
    try {
      await collectQuestion(sessionId, index)
      setCollected((prev) => new Set(prev).add(index))
      toast('已收藏到题库', 'success')
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setCollecting(null)
    }
  }

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Spinner className="text-primary" />
          <span>加载中…</span>
        </div>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-6 px-6 py-8">
        {/* 分数卡 */}
        {score && (
          <div className="rounded-lg bg-card p-7 border border-border">
            <div className="text-center">
              <p className="text-sm text-muted-foreground">本次面试得分</p>
              <p className="mt-2 text-5xl font-semibold tracking-tight text-primary">
                {score.总分 ?? '—'}
              </p>
              {score.不完整面试 && (
                <p className="mt-2 text-xs text-muted-foreground">（提前结束，按已答内容评分）</p>
              )}
            </div>
            <div className="mt-6 grid grid-cols-3 gap-3">
              {DIMENSIONS.map((d) => (
                <div key={d.key} className="rounded-lg bg-accent/50 p-4 text-center">
                  <p className="text-xs text-muted-foreground">{d.label}</p>
                  <p className="mt-1 text-2xl font-semibold text-foreground">
                    {score[d.key] ?? '—'}
                  </p>
                </div>
              ))}
            </div>
            {score.总评 && (
              <div className="mt-6 rounded-lg bg-accent p-4">
                <p className="text-sm leading-relaxed text-foreground">{score.总评}</p>
              </div>
            )}
          </div>
        )}

        {/* 复盘表 */}
        <div className="space-y-3">
          <div className="flex items-center justify-between px-1">
            <h2 className="text-base font-semibold">面试复盘</h2>
            <span className="text-xs text-muted-foreground">
              收藏值得记住的题，未收藏的将在 2 小时后清除
            </span>
          </div>

          {review?.questions.map((q) => (
            <div
              key={q.index}
              className="rounded-lg bg-card border border-border transition-colors hover:border-ring"
            >
              <button
                className="flex w-full items-start justify-between gap-3 px-5 py-4 text-left"
                onClick={() => setExpanded(expanded === q.index ? null : q.index)}
              >
                <div className="min-w-0">
                  <p className="flex items-center gap-2 text-sm font-medium">
                    <span className="shrink-0 rounded-md bg-accent px-2 py-0.5 text-xs text-primary">
                      第 {q.index} 题
                    </span>
                  </p>
                  <p className="mt-1.5 line-clamp-2 text-sm text-muted-foreground">
                    {q.question}
                  </p>
                </div>
                <span className="mt-1 shrink-0 text-xs text-muted-foreground">
                  {expanded === q.index ? '收起' : '展开'}
                </span>
              </button>

              {expanded === q.index && (
                <div className="space-y-2 border-t border-border px-5 py-4">
                  {q.dialogue.map((d, i) => (
                    <div
                      key={i}
                      className={cn('flex', d.role === 'candidate' ? 'justify-end' : 'justify-start')}
                    >
                      <div
                        className={cn(
                          'max-w-[85%] whitespace-pre-wrap rounded-lg px-3.5 py-2 text-sm leading-relaxed',
                          d.role === 'candidate'
                            ? 'bg-accent text-foreground'
                            : 'bg-accent text-foreground',
                        )}
                      >
                        {d.content}
                      </div>
                    </div>
                  ))}

                  {/* 收藏按钮 */}
                  <div className="flex justify-end pt-2">
                    {collected.has(q.index) ? (
                      <span className="flex items-center gap-1.5 rounded-lg bg-green-50 px-3.5 py-2 text-sm text-green-600">
                        <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5">
                          <path d="M20 6 9 17l-5-5" />
                        </svg>
                        已收藏
                      </span>
                    ) : (
                      <button
                        onClick={() => handleCollect(q.index)}
                        disabled={collecting !== null}
                        className="flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-white transition-all disabled:opacity-50"
                      >
                        <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M19 21 12 17 5 21V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
                        </svg>
                        {collecting === q.index ? '收藏中…' : '收藏到题库'}
                      </button>
                    )}
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* 底部操作 */}
        <div className="flex justify-center gap-3 pb-4">
          <button
            onClick={() => navigate('/bank')}
            className="rounded-lg bg-primary px-6 py-2.5 text-sm font-medium text-white transition-all hover:opacity-90"
          >
            查看题库
          </button>
          <button
            onClick={() => navigate('/interview')}
            className="rounded-lg border px-6 py-2.5 text-sm font-medium text-foreground transition-colors hover:bg-black/[0.03]"
          >
            再来一场
          </button>
        </div>
      </div>
    </div>
  )
}
