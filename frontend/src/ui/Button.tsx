import React from 'react';
import { cx } from '../lib/cx';

type Variant = 'primary' | 'secondary' | 'ghost' | 'danger';
type Size = 'sm' | 'md' | 'lg';

const variants: Record<Variant, string> = {
  primary:
    'bg-clinical text-white shadow-lift hover:bg-clinical/90 active:bg-clinical dark:bg-accent dark:text-[#04121f] dark:hover:bg-accent/90',
  secondary:
    'border border-hairline bg-surface text-soft hover:border-hairline-strong hover:text-ink',
  ghost: 'text-soft hover:bg-sunken hover:text-ink',
  danger: 'border border-danger/25 bg-danger/10 text-danger hover:bg-danger/15',
};

const sizes: Record<Size, string> = {
  sm: 'h-8 gap-1.5 px-2.5 text-xs',
  md: 'h-9 gap-2 px-3.5 text-[13px]',
  lg: 'h-11 gap-2 px-5 text-sm',
};

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: Size;
  icon?: React.ReactNode;
  /** The keyboard hint chip on the right, as on "New assessment ⌥N". */
  kbd?: string;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ variant = 'secondary', size = 'md', icon, kbd, className, children, ...rest }, ref) => (
    <button
      ref={ref}
      type="button"
      className={cx(
        'inline-flex shrink-0 items-center justify-center rounded-[10px] font-medium whitespace-nowrap',
        'transition-colors duration-150 disabled:pointer-events-none disabled:opacity-45',
        variants[variant],
        sizes[size],
        className,
      )}
      {...rest}
    >
      {icon}
      {children}
      {kbd && (
        <kbd
          className={cx(
            'ml-1 rounded border px-1 font-sans text-[10px] leading-4 font-semibold',
            variant === 'primary'
              ? 'border-white/25 text-white/75 dark:border-black/20 dark:text-black/55'
              : 'border-hairline text-faint',
          )}
        >
          {kbd}
        </kbd>
      )}
    </button>
  ),
);
Button.displayName = 'Button';

/** A square icon-only control — the moon, the sync arrow, the sidebar collapse. */
export const IconButton = React.forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & { label: string }
>(({ label, className, children, ...rest }, ref) => (
  <button
    ref={ref}
    type="button"
    aria-label={label}
    title={label}
    className={cx(
      'grid h-9 w-9 shrink-0 place-items-center rounded-[10px] border border-hairline bg-surface',
      'text-mute transition-colors duration-150 hover:border-hairline-strong hover:text-ink',
      className,
    )}
    {...rest}
  >
    {children}
  </button>
));
IconButton.displayName = 'IconButton';
