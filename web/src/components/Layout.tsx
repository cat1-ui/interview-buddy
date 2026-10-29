import { NavLink, Link } from 'react-router-dom'
import { cn } from '@/lib/utils'
import { ToastContainer } from '@/components/ui/toast'
import BackgroundDecor from '@/components/BackgroundDecor'

const navItems = [
  { to: '/knowledge', label: '知识库问答' },
  { to: '/interview', label: '模拟面试' },
  { to: '/bank', label: '题库' },
]

export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen flex-col bg-background">
      <header className="relative z-10 flex h-14 shrink-0 items-center justify-between border-b border-border/70 bg-background/70 px-6 backdrop-blur-md">
        <Link to="/" className="flex items-center gap-2.5" aria-label="返回首页">
          <span className="flex size-7 items-center justify-center rounded-md bg-primary text-xs font-semibold text-primary-foreground">
            面
          </span>
          <span className="text-[15px] font-medium tracking-tight text-foreground">
            你的专属面试助手
          </span>
        </Link>
        <nav className="flex items-center gap-0.5">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                cn(
                  'rounded-md px-3.5 py-1.5 text-sm transition-colors duration-150',
                  isActive
                    ? 'bg-accent font-medium text-primary'
                    : 'text-muted-foreground hover:bg-secondary hover:text-foreground',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="app-backdrop relative flex-1 overflow-hidden">
        <BackgroundDecor />
        {children}
      </main>
      <ToastContainer />
    </div>
  )
}
