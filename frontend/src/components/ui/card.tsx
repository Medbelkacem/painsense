import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <section className={cn('rounded-lg border border-line bg-surface', className)}>
      {children}
    </section>
  )
}

export function CardHeader({
  title,
  description,
  actions,
  className,
}: {
  title: ReactNode
  description?: ReactNode
  actions?: ReactNode
  className?: string
}) {
  return (
    <header
      className={cn(
        'flex flex-wrap items-start justify-between gap-3 border-b border-line px-4 py-3',
        className,
      )}
    >
      <div className="min-w-0">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {description && <p className="mt-0.5 text-[0.8125rem] text-muted">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </header>
  )
}

export function CardBody({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn('p-4', className)}>{children}</div>
}

export function DescriptionList({ children }: { children: ReactNode }) {
  return <dl className="divide-y divide-line text-sm">{children}</dl>
}

export function DescriptionRow({ term, children }: { term: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1 py-2.5 sm:grid-cols-[minmax(9rem,14rem)_1fr] sm:gap-4">
      <dt className="text-[0.8125rem] font-medium text-muted">{term}</dt>
      <dd className="text-ink">{children}</dd>
    </div>
  )
}
