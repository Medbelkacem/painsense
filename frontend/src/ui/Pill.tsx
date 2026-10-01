import React from 'react';
import { cx } from '../lib/cx';

export type Tone = 'neutral' | 'accent' | 'teal' | 'violet' | 'ok' | 'warn' | 'danger';

/* Every tone is a 10%-ish wash of its own colour with a matching edge, so a row of
   mixed chips keeps one weight and no chip shouts over the others. */
const tones: Record<Tone, string> = {
  neutral: 'bg-sunken text-mute border-hairline',
  accent: 'bg-accent-wash text-accent-ink border-accent-edge',
  teal: 'bg-teal/12 text-teal-ink border-teal/25 dark:text-teal',
  violet: 'bg-violet/12 text-violet border-violet/25',
  ok: 'bg-ok/12 text-ok border-ok/25',
  warn: 'bg-warn/12 text-warn border-warn/25',
  danger: 'bg-danger/12 text-danger border-danger/25',
};

interface PillProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: Tone;
  icon?: React.ReactNode;
  /** A leading filled dot, as on the "Synthetic data" and status chips. */
  dot?: boolean;
  size?: 'xs' | 'sm';
}

export const Pill: React.FC<PillProps> = ({
  tone = 'neutral',
  icon,
  dot = false,
  size = 'sm',
  className,
  children,
  ...rest
}) => (
  <span
    className={cx(
      'inline-flex items-center gap-1.5 rounded-full border font-medium whitespace-nowrap',
      size === 'xs' ? 'px-1.5 py-px text-[10px]' : 'px-2 py-0.5 text-[11px]',
      tones[tone],
      className,
    )}
    {...rest}
  >
    {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
    {icon}
    {children}
  </span>
);

/** The square tinted avatar used in patient rows and audit entries. */
export const Tile: React.FC<{ tone?: Tone; className?: string; children: React.ReactNode }> = ({
  tone = 'neutral',
  className,
  children,
}) => (
  <span
    className={cx(
      'grid shrink-0 place-items-center rounded-[9px] border text-[11px] font-semibold',
      tones[tone],
      className ?? 'h-8 w-8',
    )}
  >
    {children}
  </span>
);

/** "+8 this week" / "−2 vs yesterday" under a stat. */
export const Delta: React.FC<{ value: number; unit?: string; invert?: boolean }> = ({
  value,
  unit = '',
  invert = false,
}) => {
  const good = invert ? value < 0 : value > 0;
  const tone: Tone = value === 0 ? 'neutral' : good ? 'ok' : 'warn';
  const sign = value > 0 ? '+' : value < 0 ? '−' : '±';
  return (
    <Pill tone={tone} size="xs">
      {sign}
      {Math.abs(value)}
      {unit && ` ${unit}`}
    </Pill>
  );
};
