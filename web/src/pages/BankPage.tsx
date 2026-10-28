import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import {
  listBank,
  listCategories,
  deleteBankItem,
  updateBankCategory,
  type BankItem,
} from '@/lib/api'
import { toast } from '@/components/ui/toast'
import { Spinner } from '@/components/ui/spinner'

export default function BankPage() {
  const [items, setItems] = useState<BankItem[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [activeCategory, setActiveCategory] = useState<string>('')
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [editValue, setEditValue] = useState('')

  async function load(category: string) {
    setLoading(true)
    try {
      const [list, cats] = await Promise.all([listBank(category || undefined), listCategories()])
      setItems(list)
      setCategories(cats)
    } catch (e) {
      toast((e as Error).message, 'error')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load('')
  }, [])

  function switchCategory(cat: string) {
    setActiveCategory(cat)
    load(cat)
  }

  async function handleDelete(id: number) {
    if (!confirm('确定删除这道题吗？')) return
    try {
      await deleteBankItem(id)
      load(activeCategory)
      toast('已删除', 'success')
    } catch (e) {
      toast((e as Error).message, 'error')
    }
  }

  async function handleSaveCategory(id: number) {
    const cat = editValue.trim()
    if (!cat) return
    try {
      await updateBankCategory(id, cat)
      setEditingId(null)
      load(activeCategory)
    } catch (e) {
      toast((e as Error).message, 'error')
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
      <div className="mx-auto max-w-3xl space-y-5 px-6 py-8">
        {/* 标题 */}
        <div className="flex items-center justify-between">
          <h1 className="text-xl font-semibold tracking-tight">我的题库</h1>
          <span className="text-sm text-muted-foreground">共 {items.length} 题</span>
        </div>

        {/* 分类筛选 */}
        {categories.length > 0 && (
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => switchCategory('')}
              className={cn(
                'rounded-md px-3.5 py-1.5 text-sm transition-all',
                activeCategory === ''
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-card text-muted-foreground border border-border hover:text-foreground',
              )}
            >
              全部
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => switchCategory(cat)}
                className={cn(
                  'rounded-md px-3.5 py-1.5 text-sm transition-all',
                  activeCategory === cat
                    ? 'bg-primary text-primary-foreground'
                    : 'bg-card text-muted-foreground border border-border hover:text-foreground',
                )}
              >
                {cat}
              </button>
            ))}
          </div>
        )}

        {/* 题目列表 */}
        {items.length === 0 ? (
          <div className="rounded-lg bg-card py-16 text-center border border-border">
            <p className="text-sm text-muted-foreground">
              {activeCategory ? '这个分类下还没有题' : '题库还是空的，去面试收藏几道值得记住的题吧'}
            </p>
          </div>
        ) : (
          <div className="space-y-3">
            {items.map((item) => (
              <div
                key={item.id}
                className="rounded-lg bg-card border border-border transition-colors hover:border-ring"
              >
                <div className="flex items-start justify-between gap-3 px-5 py-4">
                  <button
                    className="min-w-0 flex-1 text-left"
                    onClick={() => setExpanded(expanded === item.id ? null : item.id)}
                  >
                    <div className="flex items-center gap-2">
                      {editingId === item.id ? (
                        <input
                          value={editValue}
                          onChange={(e) => setEditValue(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') handleSaveCategory(item.id)
                            if (e.key === 'Escape') setEditingId(null)
                          }}
                          className="h-7 w-28 rounded-md border border-border px-2 text-xs outline-none focus:border-ring"
                          autoFocus
                        />
                      ) : (
                        <span className="rounded-md bg-accent px-2.5 py-0.5 text-xs text-primary">
                          {item.category || '未分类'}
                        </span>
                      )}
                      <span className="text-xs text-muted-foreground">{item.created_at}</span>
                    </div>
                    <p className="mt-2 line-clamp-2 text-sm font-medium text-foreground">
                      {item.question}
                    </p>
                  </button>

                  <div className="flex shrink-0 items-center gap-1">
                    <button
                      onClick={() => {
                        setEditingId(item.id)
                        setEditValue(item.category)
                      }}
                      className="rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-black/[0.03] hover:text-foreground"
                    >
                      改分类
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="rounded-lg px-2 py-1.5 text-xs text-muted-foreground transition-colors hover:bg-rose-50 hover:text-rose-500"
                    >
                      删除
                    </button>
                  </div>
                </div>

                {expanded === item.id && (
                  <div className="space-y-2 border-t border-border px-5 py-4">
                    {item.dialogue.map((d, i) => (
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
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
