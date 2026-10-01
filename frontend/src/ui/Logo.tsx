import React from 'react';
import { cx } from '../lib/cx';

/**
 * The identity mark: a clinician glyph whose chest carries the signal trace. The head
 * dot is the one place Neural Violet appears in the logo — per the brand sheet it is a
 * "tiny accent only" colour.
 */
export const Mark: React.FC<{ className?: string; mono?: boolean }> = ({ className, mono = false }) => (
  <svg viewBox="0 0 32 32" className={cx('shrink-0', className ?? 'h-7 w-7')} aria-hidden>
    <circle
      cx="16"
      cy="8.2"
      r="4.6"
      fill="none"
      stroke={mono ? 'currentColor' : 'var(--brand-clinical)'}
      strokeWidth="2.4"
      className={mono ? '' : 'dark:stroke-[var(--accent-ink)]'}
    />
    <circle cx="16" cy="8.2" r="1.6" fill={mono ? 'currentColor' : 'var(--brand-violet)'} />
    <path
      d="M4.6 27.4a11.4 11.4 0 0 1 22.8 0"
      fill="none"
      stroke={mono ? 'currentColor' : 'var(--brand-clinical)'}
      strokeWidth="2.4"
      strokeLinecap="round"
      className={mono ? '' : 'dark:stroke-[var(--accent-ink)]'}
    />
    <path
      d="M7.8 24.6h3.6l2-4.4 2.9 8 2.3-5.1 1.4 1.5h4.2"
      fill="none"
      stroke={mono ? 'currentColor' : 'var(--brand-teal)'}
      strokeWidth="2.1"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

interface LogoProps {
  className?: string;
  /** "light" inverts the wordmark for the navy sign-in panel. */
  variant?: 'default' | 'light';
  size?: 'sm' | 'md' | 'lg';
  showAi?: boolean;
}

const wordSize = { sm: 'text-[15px]', md: 'text-[18px]', lg: 'text-[26px]' };
const markSize = { sm: 'h-6 w-6', md: 'h-7 w-7', lg: 'h-10 w-10' };

export const Logo: React.FC<LogoProps> = ({
  className,
  variant = 'default',
  size = 'md',
  showAi = true,
}) => (
  <span className={cx('inline-flex items-center gap-2.5 select-none', className)}>
    <Mark className={markSize[size]} mono={variant === 'light'} />
    <span
      className={cx(
        'font-semibold tracking-[-0.035em]',
        wordSize[size],
        variant === 'light' ? 'text-white' : 'text-clinical dark:text-ink',
      )}
    >
      PainSense
      {showAi && (
        <span
          className={cx(
            'ml-[0.3em] font-medium',
            variant === 'light' ? 'text-teal' : 'text-teal-ink dark:text-teal',
          )}
        >
          AI
        </span>
      )}
    </span>
  </span>
);
