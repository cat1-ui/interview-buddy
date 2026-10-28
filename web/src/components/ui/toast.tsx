import { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'

interface ToastItem {
  id: number
  type: 'error' | 'success' | 'info'
  message: string
}

// 全局的 toast 队列（模块级，跨组件共享）
let listeners: ((toasts: ToastItem[]) => void)[] = []
let currentToasts: ToastItem[] = []
let nextId = 1

function notify(listener: (toasts: ToastItem[]) => void) {
  listeners.push(listener)
  listener(currentToasts)
  return () => {
    listeners = listeners.filter((l) => l !== listener)
  }
}

function emit(toasts: ToastItem[]) {
  currentToasts = toasts
  listeners.forEach((l) => l(toasts))
}

export function toast(message: string, type: ToastItem['type'] = 'error') {
  const id = nextId++
  emit([...currentToasts, { id, type, message }])
  // 3 秒后自动移除
  setTimeout(() => {
    emit(currentToasts.filter((t) => t.id !== id))
  }, 3000)
}

export function ToastContainer() {
  const [toasts, setToasts] = useState<ToastItem[]>([])

  useEffect(() => {
    return notify(setToasts)
  }, [])

  if (toasts.length === 0) return null

  return (
    <div className="pointer-events-none fixed inset-x-0 top-16 z-50 flex flex-col items-center gap-2 px-4">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={cn(
            'pointer-events-auto flex max-w-md items-center gap-2 rounded-xl px-4 py-2.5 text-sm shadow-lg animate-in fade-in slide-in-from-top-2',
            t.type === 'error' && 'bg-rose-50 text-rose-600 ring-1 ring-rose-200',
            t.type === 'success' && 'bg-green-50 text-green-600 ring-1 ring-green-200',
            t.type === 'info' && 'bg-indigo-50 text-indigo-600 ring-1 ring-indigo-200',
          )}
        >
          <span className="shrink-0 text-base leading-none">
            {t.type === 'error' ? '✕' : t.type === 'success' ? '✓' : 'ℹ'}
          </span>
          <span className="min-w-0 break-words">{t.message}</span>
        </div>
      ))}
    </div>
  )
}
