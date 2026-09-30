import type { ReactNode } from 'react'

import { cn } from '@/utils/cn'

export function Checkbox({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean
  onChange: (next: boolean) => void
  label: ReactNode
  hint?: ReactNode
  disabled?: boolean
}) {
  return (
    <label
      className={cn(
        'flex cursor-pointer items-start gap-2.5 text-sm',
        disabled && 'cursor-not-allowed opacity-60',
      )}
    >
      <input
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
        className="mt-0.5 size-4 shrink-0 rounded border-line-strong text-accent focus:ring-accent"
      />
      <span className="min-w-0">
        <span className="text-ink">{label}</span>
        {hint && <span className="block text-xs text-muted">{hint}</span>}
      </span>
    </label>
  )
}

export function Chip({
  selected,
  onClick,
  children,
  tone = 'neutral',
}: {
  selected: boolean
  onClick: () => void
  children: ReactNode
  tone?: 'neutral' | 'alert'
}) {
  return (
    <button
      type="button"
      aria-pressed={selected}
      onClick={onClick}
      className={cn(
        'rounded-full border px-3 py-1.5 text-[0.8125rem] transition-colors',
        selected
          ? 'border-accent bg-accent-soft font-medium text-accent-strong'
          : 'border-line bg-surface text-body hover:border-line-strong hover:bg-canvas',
        tone === 'alert' && !selected && 'border-caution/40 text-caution',
        tone === 'alert' && selected && 'border-alert bg-alert-soft text-alert',
      )}
    >
      {children}
    </button>
  )
}

export function ChipGroup({ children }: { children: ReactNode }) {
  return <div className="flex flex-wrap gap-1.5">{children}</div>
}

export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  label,
}: {
  value: T
  onChange: (next: T) => void
  options: { value: T; label: string }[]
  label: string
}) {
  return (
    <div role="radiogroup" aria-label={label} className="inline-flex rounded-md border border-line p-0.5">
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={value === option.value}
          onClick={() => onChange(option.value)}
          className={cn(
            'rounded px-3 py-1.5 text-[0.8125rem] transition-colors',
            value === option.value
              ? 'bg-accent text-white'
              : 'text-body hover:bg-canvas hover:text-ink',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  )
}
