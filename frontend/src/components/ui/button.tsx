import type { ButtonHTMLAttributes, ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { cn } from '@/utils/cn'

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger'
type Size = 'sm' | 'md'

const VARIANTS: Record<Variant, string> = {
  primary: 'bg-accent text-white hover:bg-accent-strong disabled:bg-accent/50',
  secondary: 'bg-surface text-ink border border-line hover:bg-canvas disabled:text-faint',
  ghost: 'text-body hover:bg-accent-soft hover:text-accent-strong',
  danger: 'bg-alert text-white hover:brightness-95',
}

const SIZES: Record<Size, string> = {
  sm: 'h-8 px-3 text-[0.8125rem] gap-1.5',
  md: 'h-10 px-4 text-sm gap-2',
}

const BASE =
  'inline-flex items-center justify-center rounded-md font-medium transition-colors ' +
  'disabled:cursor-not-allowed disabled:opacity-70 whitespace-nowrap'

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
  loading?: boolean
}

export function Button({
  variant = 'primary',
  size = 'md',
  loading = false,
  className,
  children,
  disabled,
  ...rest
}: Props) {
  return (
    <button
      className={cn(BASE, VARIANTS[variant], SIZES[size], className)}
      disabled={disabled ?? loading}
      {...rest}
    >
      {loading && (
        <span
          aria-hidden
          className="size-3.5 animate-spin rounded-full border-2 border-current border-t-transparent"
        />
      )}
      {children}
    </button>
  )
}

export function LinkButton({
  to,
  variant = 'secondary',
  size = 'md',
  className,
  children,
}: {
  to: string
  variant?: Variant
  size?: Size
  className?: string
  children: ReactNode
}) {
  return (
    <Link to={to} className={cn(BASE, VARIANTS[variant], SIZES[size], className)}>
      {children}
    </Link>
  )
}
