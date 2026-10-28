// 最近一场面试的持久化读写。
// 用 localStorage（而非 sessionStorage）：
//  - 跨页面切换、关闭标签页后依然保留
//  - 后端会话本身有 2 小时 TTL，超时后前端读不到会自然清理
// 这只是一个"最近一场入口"的指针，真正的面试数据仍在后端内存里。

const RECENT_KEY = 'interview_recent_session_id'

export function getRecentSessionId(): string | null {
  try {
    return localStorage.getItem(RECENT_KEY)
  } catch {
    return null
  }
}

export function setRecentSessionId(sessionId: string): void {
  try {
    localStorage.setItem(RECENT_KEY, sessionId)
  } catch {
    // 隐私模式等场景写入失败，静默忽略
  }
}

export function clearRecentSessionId(): void {
  try {
    localStorage.removeItem(RECENT_KEY)
  } catch {
    // ignore
  }
}
