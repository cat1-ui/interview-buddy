import { useNavigate } from 'react-router-dom'
import BackgroundDecor from '@/components/BackgroundDecor'

// 功能入口配置。中间的「模拟面试」为核心，会在 Hero 区放大突出。
interface Entry {
  key: string
  label: string
  desc: string
  icon: React.ReactNode
  to: string
  featured?: boolean
}

// 图标统一用描边风格，克制、有信息含义
const icons = {
  interview: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
      <path d="M8 9h8M8 13h5" />
    </svg>
  ),
  knowledge: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20" />
      <path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z" />
    </svg>
  ),
  bank: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" />
      <rect x="7" y="10" width="3" height="7" rx="0.5" />
      <rect x="12" y="6" width="3" height="11" rx="0.5" />
      <rect x="17" y="13" width="3" height="4" rx="0.5" />
    </svg>
  ),
  review: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 3H5a2 2 0 0 0-2 2v4m6-6h10a2 2 0 0 1 2 2v4M9 3v18M15 21h4a2 2 0 0 0 2-2v-4m-6 6H5a2 2 0 0 1-2-2v-4m9-6h2m-2 8h2" />
    </svg>
  ),
}

const entries: Entry[] = [
  {
    key: 'knowledge',
    label: '知识库问答',
    desc: '上传资料，基于你的知识库精准答疑',
    icon: icons.knowledge,
    to: '/knowledge',
  },
  {
    key: 'interview',
    label: '模拟面试',
    desc: '和 AI 面试官来一场真实对练，出题、追问、打分',
    icon: icons.interview,
    to: '/interview',
    featured: true,
  },
  {
    key: 'bank',
    label: '面试题库',
    desc: '收藏值得回看的题，随时温习',
    icon: icons.bank,
    to: '/bank',
  },
  {
    key: 'review',
    label: '复盘回顾',
    desc: '回看最近一场面试的完整记录与评分',
    icon: icons.review,
    to: '/review',
  },
]

export default function HomePage() {
  const navigate = useNavigate()

  const featured = entries.find((e) => e.featured)!
  const others = entries.filter((e) => !e.featured)

  return (
    <div className="app-backdrop relative flex h-full flex-col overflow-hidden">
      <BackgroundDecor />
      {/* 漂浮光点氛围层 */}
      <div aria-hidden className="pointer-events-none absolute inset-0 z-0">
        <div className="animate-float absolute left-[12%] top-[18%] size-2 rounded-full bg-primary/25" />
        <div className="animate-float-delay absolute right-[16%] top-[28%] size-1.5 rounded-full bg-primary/20" />
        <div className="animate-float absolute left-[22%] bottom-[22%] size-1.5 rounded-full bg-primary/15" style={{ animationDelay: '-5s' }} />
        <div className="animate-float-delay absolute right-[24%] bottom-[30%] size-2 rounded-full bg-primary/18" />
      </div>

      <div className="relative z-10 mx-auto w-full max-w-5xl flex-1 overflow-y-auto px-6 py-10">
        <div className="mx-auto flex max-w-3xl flex-col">
        {/* 顶部品牌名 */}
        <header className="animate-fade-up mb-8 text-center" style={{ animationDelay: '0ms' }}>
          <div className="inline-flex items-center gap-2.5 rounded-full border border-border/70 bg-card/60 px-4 py-1.5 backdrop-blur-md">
            <span className="flex size-5 items-center justify-center rounded-md bg-primary text-[10px] font-semibold text-primary-foreground">
              面
            </span>
            <span className="text-sm font-medium tracking-wide text-foreground">
              你的专属面试助手
            </span>
          </div>
        </header>

        {/* Hero 区 */}
        <section className="animate-fade-up mb-8 text-center" style={{ animationDelay: '80ms' }}>
          <h1 className="text-3xl font-semibold leading-tight tracking-tight text-foreground sm:text-4xl md:text-5xl">
            每一次面试，都有备而来
          </h1>
          <p className="mx-auto mt-4 max-w-xl text-base leading-relaxed text-muted-foreground">
            一个懂你的 AI 面试搭子，陪你练题、追问、复盘，把每一次对练变成下一次面试的底气。
          </p>
        </section>

        {/* 功能入口区 */}
        <section className="animate-fade-up" style={{ animationDelay: '160ms' }}>
          {/* 中间核心入口：模拟面试，放大突出 */}
          <div className="animate-breathe mx-auto mb-5 max-w-md rounded-2xl">
            <button
              onClick={() => navigate(featured.to)}
              className="group relative flex w-full flex-col items-center gap-3 overflow-hidden rounded-2xl border border-primary/20 bg-card/70 px-8 py-8 text-center backdrop-blur-md transition-all duration-300 hover:-translate-y-1 hover:border-primary/40 hover:shadow-[0_16px_48px_-12px_color-mix(in_oklch,var(--primary)_35%,transparent)]"
            >
              <span className="flex size-16 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-[0_8px_24px_-4px_color-mix(in_oklch,var(--primary)_55%,transparent)] transition-transform duration-300 group-hover:scale-105">
                <span className="[&>svg]:size-8">{featured.icon}</span>
              </span>
              <span className="space-y-1.5">
                <span className="block text-xl font-semibold text-foreground">{featured.label}</span>
                <span className="block text-sm leading-relaxed text-muted-foreground">{featured.desc}</span>
              </span>
              <span className="inline-flex items-center gap-1 rounded-full bg-primary px-5 py-1.5 text-sm font-medium text-primary-foreground transition-transform duration-200 group-hover:scale-105">
                立即开始
                <svg className="size-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M5 12h14M13 6l6 6-6 6" />
                </svg>
              </span>
            </button>
          </div>

          {/* 其余三个入口，一行横排 */}
          <div className="grid gap-5 sm:grid-cols-3">
            {others.map((e) => (
              <EntryCard key={e.key} entry={e} onClick={() => navigate(e.to)} />
            ))}
          </div>
        </section>

        {/* 底部 */}
        <footer className="animate-fade-up mt-10 text-center" style={{ animationDelay: '240ms' }}>
          <p className="text-xs text-muted-foreground/70">
            面试搭子 · 练出你的底气
          </p>
        </footer>
        </div>
      </div>
    </div>
  )
}

// 普通入口卡片
function EntryCard({ entry, onClick }: { entry: Entry; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="group flex items-start gap-4 rounded-2xl border border-border bg-card/60 px-6 py-6 text-left backdrop-blur-md transition-all duration-200 hover:-translate-y-0.5 hover:border-primary/30 hover:bg-card hover:shadow-[0_8px_24px_-8px_color-mix(in_oklch,var(--primary)_25%,transparent)]"
    >
      <span className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-accent text-primary transition-colors duration-200 group-hover:bg-primary group-hover:text-primary-foreground">
        <span className="[&>svg]:size-5">{entry.icon}</span>
      </span>
      <span className="space-y-1">
        <span className="block text-[15px] font-medium text-foreground">{entry.label}</span>
        <span className="block text-sm leading-relaxed text-muted-foreground">{entry.desc}</span>
      </span>
    </button>
  )
}
