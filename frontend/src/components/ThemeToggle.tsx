import { Monitor, Moon, Sun } from 'lucide-react'

import { useTheme, type ThemePreference } from '@/theme/ThemeProvider'
import { cn } from '@/utils/cn'

const OPTIONS: { value: ThemePreference; label: string; icon: typeof Sun }[] = [
  { value: 'light', label: 'Light', icon: Sun },
  { value: 'dark', label: 'Dark', icon: Moon },
  { value: 'system', label: 'System', icon: Monitor },
]

/** The compact form for the top bar: one button that steps through the three settings. */
export function ThemeToggle({ className }: { className?: string }) {
  const { preference, resolved, setPreference } = useTheme()
  const next = OPTIONS[(OPTIONS.findIndex((o) => o.value === preference) + 1) % OPTIONS.length]
  const Icon = resolved === 'dark' ? Moon : Sun

  return (
    <button
      type="button"
      onClick={() => setPreference(next.value)}
      title={`Theme: ${preference}. Switch to ${next.label.toLowerCase()}.`}
      aria-label={`Theme: ${preference}. Switch to ${next.label.toLowerCase()}.`}
      className={cn('rounded-md p-2 text-muted transition-colors hover:bg-canvas hover:text-ink', className)}
    >
      <Icon aria-hidden className="size-4" />
    </button>
  )
}

/** The three-way form for Settings, which shows what is actually selected. */
export function ThemeChoice() {
  const { preference, setPreference } = useTheme()
  return (
    <div role="radiogroup" aria-label="Appearance" className="flex flex-wrap gap-2">
      {OPTIONS.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={preference === option.value}
          onClick={() => setPreference(option.value)}
          className={cn(
            'flex items-center gap-2 rounded-lg border px-3.5 py-2 text-sm transition-colors',
            preference === option.value
              ? 'border-accent bg-accent-soft font-medium text-accent'
              : 'border-line bg-surface text-body hover:border-line-strong',
          )}
        >
          <option.icon aria-hidden className="size-4" />
          {option.label}
        </button>
      ))}
    </div>
  )
}
