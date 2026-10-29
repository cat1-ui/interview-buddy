// 背景科技装饰元素：电路走线、数据节点网络、芯片纹路。
// 首页与功能页共用，保证背景风格统一。元素全部为半透明、pointer-events-none，
// 营造"现代、科技感、有工作主题"的氛围，同时不抢内容。

export default function BackgroundDecor() {
  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 z-0">
      {/* 动态流动光斑：缓慢漂移 + 呼吸，营造"活"的背景 */}
      <div
        className="drift-blob drift-blob-1"
        style={{ left: '-10%', top: '-15%', width: '50%', height: '50%', background: 'color-mix(in oklch, var(--primary) 20%, transparent)' }}
      />
      <div
        className="drift-blob drift-blob-2"
        style={{ right: '-8%', top: '30%', width: '45%', height: '45%', background: 'color-mix(in oklch, var(--primary) 15%, transparent)' }}
      />
      <div
        className="drift-blob drift-blob-3"
        style={{ left: '20%', bottom: '-20%', width: '55%', height: '50%', background: 'color-mix(in oklch, var(--primary) 12%, transparent)' }}
      />

      {/* 左上：电路走线 + 节点圆点 */}
      <svg
        className="absolute left-[-60px] top-[-40px] size-[280px] text-primary/16"
        viewBox="0 0 200 200" fill="none"
      >
        {/* 电路走线 */}
        <path d="M20 60 H80 V100 H140 V150" stroke="currentColor" strokeWidth="1.5" />
        <path d="M20 60 V20 H140" stroke="currentColor" strokeWidth="1.5" />
        <path d="M80 100 H180" stroke="currentColor" strokeWidth="1.2" />
        {/* 节点圆点 */}
        <circle cx="20" cy="60" r="4" fill="currentColor" />
        <circle cx="80" cy="100" r="3.5" fill="currentColor" />
        <circle cx="140" cy="150" r="3" fill="currentColor" />
        <circle cx="140" cy="20" r="3" fill="currentColor" />
        <circle cx="180" cy="100" r="3" fill="currentColor" />
      </svg>

      {/* 右上：数据节点网络（点 + 连线） */}
      <svg
        className="absolute right-[-50px] top-[18%] size-[240px] text-primary/10"
        viewBox="0 0 200 200" fill="none"
      >
        <path d="M40 40 L120 70 M40 40 L70 150 M40 40 L170 110" stroke="currentColor" strokeWidth="1" />
        <path d="M120 70 L170 110 M120 70 L70 150 M70 150 L170 110" stroke="currentColor" strokeWidth="1" opacity="0.6" />
        <circle cx="40" cy="40" r="5" fill="currentColor" />
        <circle cx="120" cy="70" r="4" fill="currentColor" />
        <circle cx="70" cy="150" r="4" fill="currentColor" />
        <circle cx="170" cy="110" r="3.5" fill="currentColor" />
        {/* 外圈虚线环 */}
        <circle cx="40" cy="40" r="22" stroke="currentColor" strokeWidth="1" strokeDasharray="3 5" />
      </svg>

      {/* 左下：芯片纹路 + 引脚 */}
      <svg
        className="absolute bottom-[-50px] left-[16%] size-[240px] text-primary/12"
        viewBox="0 0 200 200" fill="none"
      >
        {/* 芯片主体 */}
        <rect x="60" y="60" width="80" height="80" rx="10" stroke="currentColor" strokeWidth="1.5" />
        <rect x="80" y="80" width="40" height="40" rx="6" stroke="currentColor" strokeWidth="1" strokeDasharray="3 4" />
        {/* 引脚 */}
        <path d="M60 80 H40 M60 100 H40 M60 120 H40" stroke="currentColor" strokeWidth="1.5" />
        <path d="M140 80 H160 M140 100 H160 M140 120 H160" stroke="currentColor" strokeWidth="1.5" />
        <path d="M80 60 V40 M100 60 V40 M120 60 V40" stroke="currentColor" strokeWidth="1.5" />
        <path d="M80 140 V160 M100 140 V160 M120 140 V160" stroke="currentColor" strokeWidth="1.5" />
        {/* 引脚端点 */}
        <circle cx="40" cy="80" r="2.5" fill="currentColor" />
        <circle cx="40" cy="100" r="2.5" fill="currentColor" />
        <circle cx="40" cy="120" r="2.5" fill="currentColor" />
        <circle cx="160" cy="80" r="2.5" fill="currentColor" />
        <circle cx="160" cy="100" r="2.5" fill="currentColor" />
        <circle cx="160" cy="120" r="2.5" fill="currentColor" />
      </svg>

      {/* 右侧中部：芯片（更显眼） */}
      <svg
        className="absolute right-[3%] top-[55%] size-[160px] text-primary/12"
        viewBox="0 0 100 100" fill="none"
      >
        <rect x="30" y="30" width="40" height="40" rx="8" stroke="currentColor" strokeWidth="1.5" />
        <rect x="40" y="40" width="20" height="20" rx="4" stroke="currentColor" strokeWidth="1" />
        <path d="M30 42 H20 M30 50 H20 M30 58 H20 M70 42 H80 M70 50 H80 M70 58 H80" stroke="currentColor" strokeWidth="1.5" />
        <path d="M42 30 V20 M50 30 V20 M58 30 V20 M42 70 V80 M50 70 V80 M58 70 V80" stroke="currentColor" strokeWidth="1.5" />
      </svg>

      {/* 右下：电路折线 + 节点 */}
      <svg
        className="absolute right-[10%] bottom-[6%] size-[180px] text-primary/10"
        viewBox="0 0 200 200" fill="none"
      >
        <path d="M20 180 H80 V120 H140 V60 H180" stroke="currentColor" strokeWidth="1.5" />
        <path d="M80 120 H140" stroke="currentColor" strokeWidth="1" strokeDasharray="3 5" />
        <circle cx="20" cy="180" r="4" fill="currentColor" />
        <circle cx="80" cy="120" r="3.5" fill="currentColor" />
        <circle cx="140" cy="60" r="3" fill="currentColor" />
        <circle cx="180" cy="60" r="3" fill="currentColor" />
        {/* 装饰小方块 */}
        <rect x="150" y="140" width="16" height="16" rx="3" stroke="currentColor" strokeWidth="1" />
      </svg>

      {/* 下方：数据流箭头连线 */}
      <svg
        className="absolute bottom-[4%] left-[40%] size-[160px] text-primary/8"
        viewBox="0 0 200 200" fill="none"
      >
        <path d="M20 100 H140" stroke="currentColor" strokeWidth="1.5" />
        <path d="M130 90 L150 100 L130 110" stroke="currentColor" strokeWidth="1.5" />
        <circle cx="20" cy="100" r="4" fill="currentColor" />
        <circle cx="80" cy="100" r="3" fill="currentColor" />
        <circle cx="140" cy="100" r="3" fill="currentColor" />
      </svg>
    </div>
  )
}
