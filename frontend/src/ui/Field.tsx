import React, { useId } from 'react';
import { cx } from '../lib/cx';

interface TextFieldProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: string;
  error?: string | null;
  icon?: React.ReactNode;
  /** The eye toggle on the password field, or a unit suffix like "mmHg". */
  trailing?: React.ReactNode;
}

export const TextField: React.FC<TextFieldProps> = ({
  label,
  hint,
  error,
  icon,
  trailing,
  className,
  id,
  ...rest
}) => {
  const generated = useId();
  const fieldId = id ?? generated;
  return (
    <div className={cx('space-y-1.5', className)}>
      {label && (
        <label htmlFor={fieldId} className="block text-xs font-medium text-soft">
          {label}
        </label>
      )}
      <div
        className={cx(
          'flex h-11 items-center gap-2.5 rounded-[10px] border bg-surface px-3',
          'transition-colors duration-150 focus-within:border-accent',
          error ? 'border-danger/50' : 'border-hairline hover:border-hairline-strong',
        )}
      >
        {icon && <span className="shrink-0 text-faint">{icon}</span>}
        <input
          id={fieldId}
          className="h-full w-full bg-transparent text-sm text-ink outline-none placeholder:text-faint"
          {...rest}
        />
        {trailing}
      </div>
      {(error || hint) && (
        <p className={cx('text-[11px]', error ? 'text-danger' : 'text-faint')}>{error ?? hint}</p>
      )}
    </div>
  );
};

/** The inline search box used inside filter bars and table headers. */
export const SearchField: React.FC<
  React.InputHTMLAttributes<HTMLInputElement> & { icon: React.ReactNode; kbd?: string }
> = ({ icon, kbd, className, ...rest }) => (
  <div
    className={cx(
      'flex h-9 items-center gap-2 rounded-[10px] border border-hairline bg-surface px-3',
      'transition-colors duration-150 focus-within:border-accent',
      className,
    )}
  >
    <span className="shrink-0 text-faint">{icon}</span>
    <input
      type="search"
      className="h-full w-full bg-transparent text-[13px] text-ink outline-none placeholder:text-faint [&::-webkit-search-cancel-button]:hidden"
      {...rest}
    />
    {kbd && (
      <kbd className="hidden shrink-0 rounded border border-hairline px-1 font-sans text-[10px] leading-4 text-faint sm:block">
        {kbd}
      </kbd>
    )}
  </div>
);

export const Toggle: React.FC<{
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  /** Hidden visually when the row already carries its own label text. */
  hideLabel?: boolean;
}> = ({ checked, onChange, label, hideLabel = false }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    onClick={() => onChange(!checked)}
    className="inline-flex items-center gap-2 text-[13px] text-soft"
  >
    <span
      className={cx(
        'inline-flex h-5 w-9 shrink-0 items-center rounded-full border p-0.5 transition-colors duration-200',
        checked ? 'border-accent bg-accent' : 'border-hairline-strong bg-sunken',
      )}
    >
      <span
        className={cx(
          'h-3.5 w-3.5 rounded-full bg-white shadow-sm transition-transform duration-200',
          checked ? 'translate-x-4' : 'translate-x-0',
        )}
      />
    </span>
    {!hideLabel && <span>{label}</span>}
  </button>
);

/** A labelled switch row, the shape the whole Settings page is built from. */
export const ToggleRow: React.FC<{
  title: string;
  sub?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}> = ({ title, sub, checked, onChange }) => (
  <div className="flex items-center justify-between gap-6 py-3">
    <div className="min-w-0">
      <p className="text-[13px] font-medium text-ink">{title}</p>
      {sub && <p className="mt-0.5 text-xs text-mute">{sub}</p>}
    </div>
    <Toggle checked={checked} onChange={onChange} label={title} hideLabel />
  </div>
);

/** Radio/checkbox answer chips — the pain-quality and symptom pickers. */
export const Choice: React.FC<{
  kind: 'radio' | 'check';
  checked: boolean;
  onClick: () => void;
  children: React.ReactNode;
}> = ({ kind, checked, onClick, children }) => (
  <button
    type="button"
    role={kind === 'radio' ? 'radio' : 'checkbox'}
    aria-checked={checked}
    onClick={onClick}
    className={cx(
      'inline-flex h-10 items-center gap-2.5 rounded-[10px] border px-3 text-[13px] transition-colors duration-150',
      checked
        ? 'border-teal/50 bg-teal/10 font-medium text-ink'
        : 'border-hairline bg-surface text-soft hover:border-hairline-strong',
    )}
  >
    <span
      className={cx(
        'grid h-4 w-4 shrink-0 place-items-center border transition-colors',
        kind === 'radio' ? 'rounded-full' : 'rounded-[5px]',
        checked ? 'border-teal-ink bg-teal-ink text-white dark:bg-teal dark:border-teal' : 'border-hairline-strong',
      )}
    >
      {checked &&
        (kind === 'radio' ? (
          <span className="h-1.5 w-1.5 rounded-full bg-white" />
        ) : (
          <svg viewBox="0 0 12 12" className="h-2.5 w-2.5" fill="none" stroke="currentColor" strokeWidth={2.5}>
            <path d="M2 6.5 4.6 9 10 3.4" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        ))}
    </span>
    {children}
  </button>
);
