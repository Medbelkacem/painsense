import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react'
import { forwardRef, useId } from 'react'

import { cn } from '@/utils/cn'

const CONTROL =
  'w-full rounded-md border border-line bg-surface px-3 py-2 text-sm text-ink ' +
  'placeholder:text-faint focus:border-accent focus:outline-none focus:ring-1 ' +
  'focus:ring-accent disabled:bg-canvas disabled:text-muted'

export function Field({
  label,
  hint,
  error,
  required,
  children,
  className,
}: {
  label: ReactNode
  hint?: ReactNode
  error?: string
  required?: boolean
  children: (props: { id: string; 'aria-describedby'?: string }) => ReactNode
  className?: string
}) {
  const id = useId()
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className={cn('space-y-1.5', className)}>
      <label htmlFor={id} className="block text-[0.8125rem] font-medium text-body">
        {label}
        {required && <span className="ml-0.5 text-alert">*</span>}
      </label>
      {children({ id, 'aria-describedby': describedBy })}
      {hint && !error && (
        <p id={`${id}-hint`} className="text-xs text-muted">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-xs text-alert">
          {error}
        </p>
      )}
    </div>
  )
}

// Refs are forwarded because react-hook-form registers a field through one: without it the
// form holds no value for the control.
export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return <input ref={ref} className={cn(CONTROL, className)} {...rest} />
  },
)

export const Textarea = forwardRef<
  HTMLTextAreaElement,
  TextareaHTMLAttributes<HTMLTextAreaElement>
>(function Textarea({ className, ...rest }, ref) {
  return <textarea ref={ref} className={cn(CONTROL, 'min-h-20 resize-y', className)} {...rest} />
})

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select ref={ref} className={cn(CONTROL, 'appearance-none pr-8', className)} {...rest}>
        {children}
      </select>
    )
  },
)

export function Fieldset({
  legend,
  description,
  children,
  className,
}: {
  legend: ReactNode
  description?: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <fieldset className={cn('space-y-3', className)}>
      <legend className="text-sm font-semibold text-ink">{legend}</legend>
      {description && <p className="-mt-1 text-[0.8125rem] text-muted">{description}</p>}
      {children}
    </fieldset>
  )
}
