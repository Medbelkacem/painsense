import React from 'react';
import { cx } from '../lib/cx';

interface TabsProps<T extends string> {
  tabs: readonly { value: T; label: string; count?: number }[];
  value: T;
  onChange: (value: T) => void;
  className?: string;
}

/** Underlined tabs — the Overview / Assessments / Pain history row on a patient. */
export function Tabs<T extends string>({ tabs, value, onChange, className }: TabsProps<T>) {
  return (
    <div className={cx('flex gap-1 overflow-x-auto border-b border-hairline', className)}>
      {tabs.map((tab) => {
        const active = tab.value === value;
        return (
          <button
            key={tab.value}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(tab.value)}
            className={cx(
              'relative shrink-0 px-3 pb-2.5 text-[13px] font-medium transition-colors',
              active ? 'text-ink' : 'text-mute hover:text-soft',
            )}
          >
            {tab.label}
            {tab.count !== undefined && (
              <span className="ml-1.5 text-[11px] text-faint tabular-nums">{tab.count}</span>
            )}
            <span
              className={cx(
                'absolute inset-x-2 -bottom-px h-0.5 rounded-full transition-opacity',
                active ? 'bg-accent opacity-100' : 'opacity-0',
              )}
            />
          </button>
        );
      })}
    </div>
  );
}

export interface Step {
  label: string;
  /** Hidden on narrow rails; the number stays. */
  hint?: string;
}

/** The rail across the top of a new assessment. */
export const Stepper: React.FC<{
  steps: readonly Step[];
  current: number;
  onJump?: (index: number) => void;
  /** The furthest step that can be jumped to. Defaults to the current one, so a wizard
   *  that gates its steps stays gated; a wizard whose steps are all optional passes the
   *  last index and lets the clinician move around freely. */
  reach?: number;
}> = ({ steps, current, onJump, reach }) => (
  <ol className="flex items-center gap-1 overflow-x-auto">
    {steps.map((step, index) => {
      const done = index < current;
      const active = index === current;
      const reachable = index <= (reach ?? current);
      return (
        <li key={step.label} className="flex min-w-0 shrink-0 items-center gap-1">
          <button
            type="button"
            disabled={!onJump || !reachable}
            onClick={() => onJump?.(index)}
            className={cx(
              'flex items-center gap-2 rounded-lg px-1.5 py-1 transition-colors',
              onJump && reachable && 'hover:bg-sunken',
            )}
          >
            <span
              className={cx(
                'grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11px] font-semibold transition-colors',
                done && 'border-clinical bg-clinical text-white dark:border-accent dark:bg-accent dark:text-[#04121f]',
                active && 'border-clinical text-clinical dark:border-accent dark:text-accent-ink',
                !done && !active && 'border-hairline-strong text-faint',
              )}
            >
              {done ? (
                <svg viewBox="0 0 12 12" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth={2.2}>
                  <path d="M2 6.3 4.6 9 10 3.3" strokeLinecap="round" strokeLinejoin="round" />
                </svg>
              ) : (
                index + 1
              )}
            </span>
            <span
              className={cx(
                'hidden text-[13px] whitespace-nowrap sm:block',
                active ? 'font-medium text-ink' : 'text-mute',
              )}
            >
              {step.label}
            </span>
          </button>
          {index < steps.length - 1 && (
            <span
              className={cx(
                'h-px w-5 shrink-0 sm:w-8',
                done ? 'bg-clinical dark:bg-accent' : 'bg-hairline',
              )}
            />
          )}
        </li>
      );
    })}
  </ol>
);
