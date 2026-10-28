import { useEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import {
  askKnowledge,
  buildKnowledge,
  uploadDocs,
  listDocs,
  deleteDoc,
  type DocItem,
} from '@/lib/api'
import { toast } from '@/components/ui/toast'
import { Spinner } from '@/components/ui/spinner'

interface ChatItem {
  role: 'user' | 'assistant'
  content: string
  sources?: { filename: string; score: number }[]
  question?: string // 该条 assistant 回答对应的用户问题（用于"重新生成"）
}

const MAX_UPLOAD_COUNT = 3
const MAX_UPLOAD_SIZE = 5 * 1024 * 1024

export default function KnowledgePage() {
  const [chats, setChats] = useState<ChatItem[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [building, setBuilding] = useState(false)
  const [chunkCount, setChunkCount] = useState<number | null>(null)
  const [docs, setDocs] = useState<DocItem[]>([])
  const [uploading, setUploading] = useState(false)
  const [showDocs, setShowDocs] = useState(false)

  const scrollRef = useRef<HTMLDivElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [chats, loading])

  useEffect(() => {
    // 启动时查一次知识库状态和资料列表
    fetch('/api/health')
      .then((r) => r.json())
      .then((d) => setChunkCount(d.chunk_count))
      .catch(() => {})
    loadDocs()
  }, [])

  async function loadDocs() {
    try {
      setDocs(await listDocs())
    } catch {
      // 忽略
    }
  }

  async function handleBuild() {
    setBuilding(true)
    try {
      const res = await buildKnowledge()
      setChunkCount(res.chunk_count)
      if (res.status === 'empty') {
        toast('知识库里还没有资料，请先上传 md/txt 文件', 'info')
      }
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setBuilding(false)
    }
  }

  async function handleUpload(files: FileList | null) {
    if (!files || files.length === 0) return

    const list = Array.from(files)

    // 前端校验：数量
    if (list.length > MAX_UPLOAD_COUNT) {
      toast(`一次最多上传 ${MAX_UPLOAD_COUNT} 个文件`, 'error')
      return
    }
    // 前端校验：格式 + 大小
    for (const f of list) {
      if (!f.name.endsWith('.md') && !f.name.endsWith('.txt')) {
        toast(`文件「${f.name}」格式不支持，只允许 .md 和 .txt`, 'error')
        return
      }
      if (f.size > MAX_UPLOAD_SIZE) {
        toast(`文件「${f.name}」超过 5MB 限制`, 'error')
        return
      }
    }

    setUploading(true)
    try {
      const res = await uploadDocs(list)
      setChunkCount(res.chunk_count)
      await loadDocs()
      toast(`已上传 ${res.saved.length} 个文件`, 'success')
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setUploading(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  async function handleDelete(filename: string) {
    if (!confirm(`确定删除「${filename}」吗？`)) return
    try {
      const res = await deleteDoc(filename)
      setChunkCount(res.chunk_count)
      await loadDocs()
      toast(`已删除「${filename}」`, 'success')
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function handleAsk() {
    const q = input.trim()
    if (!q || loading) return
    setInput('')
    setChats((prev) => [...prev, { role: 'user', content: q }])
    await doAsk(q)
  }

  // 发问并追加答案（handleAsk 和"重新生成"共用）
  async function doAsk(question: string) {
    setLoading(true)
    try {
      const res = await askKnowledge(question)
      setChats((prev) => [
        ...prev,
        { role: 'assistant', content: res.answer, sources: res.sources, question },
      ])
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }

  // 重新生成：对同一问题再答一次（追加新答案，不覆盖旧的）
  async function handleRegenerate(question: string) {
    if (loading) return
    await doAsk(question)
  }

  // 复制答案
  async function handleCopy(content: string) {
    try {
      await navigator.clipboard.writeText(content)
      toast('已复制到剪贴板', 'success')
    } catch {
      toast('复制失败', 'error')
    }
  }

  // 清空对话
  function handleClear() {
    if (chats.length === 0) return
    if (!confirm('确定清空所有对话吗？')) return
    setChats([])
  }

  function formatSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部：知识库状态 + 资料管理 */}
      <div className="shrink-0 border-b border-border bg-card/70 px-6 py-3 backdrop-blur-sm">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <div className="flex items-center gap-2 text-sm">
            <span className="text-muted-foreground">知识库</span>
            <span
              className={cn(
                'rounded-md px-2.5 py-0.5 text-xs',
                (chunkCount ?? 0) > 0 ? 'bg-green-50 text-green-600' : 'bg-amber-50 text-amber-600',
              )}
            >
              {chunkCount === null ? '读取中…' : `${chunkCount} 个知识片段`}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt"
              multiple
              className="hidden"
              onChange={(e) => handleUpload(e.target.files)}
            />
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
              className="rounded-lg border border-border bg-card px-3.5 py-1.5 text-sm font-medium text-primary transition-colors hover:bg-accent disabled:opacity-50"
            >
              {uploading ? '上传中…' : '上传资料'}
            </button>
            <button
              onClick={() => setShowDocs((v) => !v)}
              className="rounded-lg border border-border bg-card px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
            >
              资料（{docs.length}）
            </button>
            <button
              onClick={handleBuild}
              disabled={building}
              className="rounded-lg bg-primary px-3.5 py-1.5 text-sm font-medium text-white transition-all disabled:opacity-50"
            >
              {building ? '构建中…' : '重新构建'}
            </button>
          </div>
        </div>

        {/* 资料列表（展开时显示） */}
        {showDocs && (
          <div className="mx-auto mt-3 max-w-3xl rounded-lg border border-border bg-card p-2">
            {docs.length === 0 ? (
              <p className="px-3 py-4 text-center text-sm text-muted-foreground">
                还没有资料，点「上传资料」添加 .md 或 .txt 文件
              </p>
            ) : (
              <div className="divide-y divide-black/[0.04]">
                {docs.map((doc) => (
                  <div key={doc.filename} className="flex items-center justify-between px-3 py-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <svg className="size-4 shrink-0 text-muted-foreground" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" />
                        <path d="M14 2v6h6" />
                      </svg>
                      <span className="truncate text-sm">{doc.filename}</span>
                      <span className="shrink-0 text-xs text-muted-foreground">{formatSize(doc.size)}</span>
                    </div>
                    <button
                      onClick={() => handleDelete(doc.filename)}
                      className="shrink-0 rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-rose-50 hover:text-rose-500"
                    >
                      删除
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* 对话区 */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto">
        {chats.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <div className="max-w-md space-y-3 text-center">
              <div className="mx-auto flex size-12 items-center justify-center rounded-lg bg-primary text-white ">
                <svg className="size-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
                </svg>
              </div>
              <h2 className="text-lg font-semibold tracking-tight">向知识库提问</h2>
              <p className="text-sm leading-relaxed text-muted-foreground">
                先往 data/docs 放资料，再点「重新构建知识库」，就能基于你自己的资料问答了。
              </p>
            </div>
          </div>
        ) : (
          <div className="mx-auto max-w-3xl space-y-5 px-6 py-6">
            {chats.map((chat, i) => (
              <div
                key={i}
                className={cn('flex', chat.role === 'user' ? 'justify-end' : 'justify-start')}
              >
                <div
                  className={cn(
                    'max-w-[85%] whitespace-pre-wrap rounded-lg px-4 py-2.5 text-sm leading-relaxed',
                    chat.role === 'user'
                      ? 'rounded-tr-sm bg-primary text-primary-foreground'
                      : 'rounded-tl-md bg-card text-foreground border border-border',
                  )}
                >
                  {chat.content}
                  {chat.sources && chat.sources.length > 0 && (
                    <div className="mt-2 space-y-1 border-t border-border pt-2">
                      <p className="text-xs text-muted-foreground">参考来源：</p>
                      {chat.sources.map((s, j) => (
                        <p key={j} className="text-xs text-muted-foreground">
                          · {s.filename}（相关度 {(s.score * 100).toFixed(0)}%）
                        </p>
                      ))}
                    </div>
                  )}

                  {/* 助手回答的操作按钮：复制 / 重新生成 */}
                  {chat.role === 'assistant' && chat.content && (
                    <div className="mt-2 flex items-center gap-1 border-t border-border pt-2">
                      <button
                        onClick={() => handleCopy(chat.content)}
                        className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-black/[0.04] hover:text-foreground"
                      >
                        复制
                      </button>
                      {chat.question && (
                        <button
                          onClick={() => handleRegenerate(chat.question!)}
                          disabled={loading}
                          className="rounded-md px-2 py-1 text-xs text-muted-foreground transition-colors hover:bg-black/[0.04] hover:text-foreground disabled:opacity-50"
                        >
                          重新生成
                        </button>
                      )}
                    </div>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="flex items-center gap-2 rounded-lg rounded-tl-md bg-card px-4 py-3 border border-border">
                  <Spinner className="text-primary" />
                  <span className="text-sm text-muted-foreground">正在生成回答…</span>
                </div>
              </div>
            )}

            {/* 清空对话 */}
            {chats.length > 0 && (
              <div className="flex justify-center pt-2">
                <button
                  onClick={handleClear}
                  className="rounded-lg px-3.5 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-black/[0.04] hover:text-foreground"
                >
                  清空对话
                </button>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 输入区 */}
      <div className="shrink-0 px-6 pb-5">
        <div className="mx-auto flex max-w-3xl items-end gap-3 rounded-lg border border-border bg-card p-2">
          <textarea
            placeholder="输入你的问题…（Enter 发送，Shift+Enter 换行）"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                handleAsk()
              }
            }}
            disabled={loading}
            rows={1}
            className="max-h-32 min-h-12 flex-1 resize-none bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-muted-foreground"
          />
          <button
            onClick={handleAsk}
            disabled={loading || !input.trim()}
            className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-primary text-white transition-all disabled:opacity-40"
          >
            <svg className="size-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="m22 2-7 20-4-9-9-4z" />
            </svg>
          </button>
        </div>
      </div>
    </div>
  )
}
