import { AlertTriangle, Info, TriangleAlert } from 'lucide-react'
import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

type Tone = 'info' | 'caution' | 'alert'

const TONES: Record<Tone, { box: string; icon: typeof Info }> = {
  info: { box: 'border-accent/25 bg-accent-soft text-accent-strong', icon: Info },
  caution: { box: 'border-caution/30 bg-caution-soft text-caution', icon: AlertTriangle },
  alert: { box: 'border-alert/30 bg-alert-soft text-alert', icon: TriangleAlert },
}

export function Notice({
  tone = 'info',
  title,
  children,
  className,
}: {
  tone?: Tone
  title?: ReactNode
  children?: ReactNode
  className?: string
}) {
  const { box, icon: Icon } = TONES[tone]
  return (
    <div
      role={tone === 'alert' ? 'alert' : undefined}
      className={cn('flex gap-2.5 rounded-md border px-3.5 py-3 text-[0.8125rem]', box, className)}
    >
      <Icon aria-hidden className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 space-y-1">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className="leading-relaxed">{children}</div>}
      </div>
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 py-8 text-sm text-muted" role="status">
      <span
        aria-hidden
        className="size-4 animate-spin rounded-full border-2 border-line-strong border-t-accent"
      />
      {label}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="flex flex-col items-center gap-2 px-4 py-12 text-center">
      <p className="text-sm font-medium text-ink">{title}</p>
      {description && <p className="max-w-md text-[0.8125rem] text-muted">{description}</p>}
      {action && <div className="mt-2">{action}</div>}
    </div>
  )
}

export function QueryState({
  isPending,
  error,
  isEmpty,
  empty,
  children,
}: {
  isPending: boolean
  error: unknown
  isEmpty?: boolean
  empty?: ReactNode
  children: ReactNode
}) {
  if (isPending) return <Spinner />
  if (error) {
    return (
      <Notice tone="alert" title="Could not load this">
        {error instanceof Error ? error.message : 'Unexpected error'}
      </Notice>
    )
  }
  if (isEmpty) return <>{empty ?? <EmptyState title="Nothing to show yet" />}</>
  return <>{children}</>
}
