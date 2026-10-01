import React from 'react';
import { cx } from '../lib/cx';

export const Card: React.FC<React.HTMLAttributes<HTMLDivElement>> = ({
  className,
  children,
  ...rest
}) => (
  <div
    className={cx(
      'rounded-[14px] border border-hairline bg-surface shadow-card',
      className,
    )}
    {...rest}
  >
    {children}
  </div>
);

interface CardHeadProps {
  title: React.ReactNode;
  sub?: React.ReactNode;
  /** Segmented control, dropdown or button group pinned to the right of the title. */
  action?: React.ReactNode;
  className?: string;
}

export const CardHead: React.FC<CardHeadProps> = ({ title, sub, action, className }) => (
  <div className={cx('flex flex-wrap items-start justify-between gap-3', className)}>
    <div className="min-w-0">
      <h2 className="text-[15px] font-semibold text-ink">{title}</h2>
      {sub && <p className="mt-0.5 text-xs text-mute">{sub}</p>}
    </div>
    {action && <div className="flex shrink-0 items-center gap-2">{action}</div>}
  </div>
);

export const PageHead: React.FC<{
  title: React.ReactNode;
  sub?: React.ReactNode;
  eyebrow?: React.ReactNode;
  action?: React.ReactNode;
}> = ({ title, sub, eyebrow, action }) => (
  <div className="flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0">
      {eyebrow && <div className="mb-1 text-xs text-mute">{eyebrow}</div>}
      <h1 className="text-[26px] leading-tight font-semibold text-ink">{title}</h1>
      {sub && <p className="mt-1 text-[13px] text-mute">{sub}</p>}
    </div>
    {action && <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div>}
  </div>
);

export const EmptyState: React.FC<{
  icon?: React.ReactNode;
  title: string;
  sub?: string;
  action?: React.ReactNode;
}> = ({ icon, title, sub, action }) => (
  <div className="flex flex-col items-center gap-3 px-6 py-16 text-center">
    {icon && (
      <span className="grid h-11 w-11 place-items-center rounded-xl bg-sunken text-faint">
        {icon}
      </span>
    )}
    <div>
      <p className="text-sm font-medium text-ink">{title}</p>
      {sub && <p className="mt-1 max-w-sm text-xs text-mute">{sub}</p>}
    </div>
    {action}
  </div>
);
