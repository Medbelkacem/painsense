import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

type Tone = 'neutral' | 'accent' | 'positive' | 'caution' | 'alert'

const TONES: Record<Tone, string> = {
  neutral: 'bg-canvas text-muted border-line',
  accent: 'bg-accent-soft text-accent-strong border-accent/25',
  positive: 'bg-positive-soft text-positive border-positive/25',
  caution: 'bg-caution-soft text-caution border-caution/25',
  alert: 'bg-alert-soft text-alert border-alert/25',
}

export function Badge({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: Tone
  className?: string
  children: ReactNode
}) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium',
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  )
}
