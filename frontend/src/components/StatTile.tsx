import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

export function StatTile({
  label,
  value,
  hint,
  tone = 'default',
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'default' | 'caution' | 'alert'
}) {
  return (
    <div className="rounded-lg border border-line bg-surface px-4 py-3">
      <p className="text-xs font-medium tracking-wide text-muted uppercase">{label}</p>
      <p
        className={cn(
          'mt-1 text-2xl font-semibold tabular',
          tone === 'alert' ? 'text-alert' : tone === 'caution' ? 'text-caution' : 'text-ink',
        )}
      >
        {value}
      </p>
      {hint && <p className="mt-0.5 text-xs text-muted">{hint}</p>}
    </div>
  )
}
