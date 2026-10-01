import { useId } from 'react';
import { cx } from '../lib/cx';

interface SegmentedProps<T extends string> {
  options: readonly { value: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  size?: 'sm' | 'md';
  className?: string;
}

/**
 * The 7 days / 30 days / 3 months control. The selected pill is a sliding element
 * rather than a per-option background, so the movement reads as one object.
 */
export function Segmented<T extends string>({
  options,
  value,
  onChange,
  size = 'sm',
  className,
}: SegmentedProps<T>) {
  const name = useId();
  const current = Math.max(0, options.findIndex((option) => option.value === value));

  return (
    <div
      role="radiogroup"
      className={cx(
        'relative inline-flex rounded-[10px] border border-hairline bg-sunken p-0.5',
        className,
      )}
    >
      <span
        aria-hidden
        className="absolute top-0.5 bottom-0.5 rounded-lg bg-surface shadow-card transition-[left] duration-200 ease-out"
        style={{
          width: `calc((100% - 4px) / ${options.length})`,
          left: `calc(2px + ${current} * (100% - 4px) / ${options.length})`,
        }}
      />
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          name={name}
          aria-checked={option.value === value}
          onClick={() => onChange(option.value)}
          className={cx(
            'relative z-10 flex-1 rounded-lg font-medium whitespace-nowrap transition-colors',
            size === 'sm' ? 'h-7 px-2.5 text-[12px]' : 'h-8 px-3 text-[13px]',
            option.value === value ? 'text-ink' : 'text-mute hover:text-soft',
          )}
        >
          {option.label}
        </button>
      ))}
    </div>
  );
}
