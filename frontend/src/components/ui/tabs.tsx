import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

export function Tabs<T extends string>({
  value,
  onChange,
  tabs,
  label,
}: {
  value: T
  onChange: (next: T) => void
  tabs: { value: T; label: string; badge?: ReactNode }[]
  label: string
}) {
  return (
    <div role="tablist" aria-label={label} className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((tab) => (
        <button
          key={tab.value}
          role="tab"
          aria-selected={value === tab.value}
          onClick={() => onChange(tab.value)}
          className={cn(
            '-mb-px flex items-center gap-1.5 border-b-2 px-3 py-2 text-sm whitespace-nowrap transition-colors',
            value === tab.value
              ? 'border-accent font-medium text-accent-strong'
              : 'border-transparent text-muted hover:text-ink',
          )}
        >
          {tab.label}
          {tab.badge}
        </button>
      ))}
    </div>
  )
}
