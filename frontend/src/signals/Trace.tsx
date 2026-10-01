import React, { useMemo } from 'react';

/**
 * A single acquisition channel drawn as a trace.
 *
 * The samples arrive already decimated by the API, so this draws them as-is and reports
 * the range it found rather than rescaling silently — a flat line should look flat, not
 * be stretched to fill the box.
 */
export const Trace: React.FC<{
  /** `null` marks a dropout; the trace breaks there rather than bridging it. */
  values: readonly (number | null)[];
  label: string;
  unit: string;
  tone: string;
  height?: number;
}> = ({ values, label, unit, tone, height = 72 }) => {
  const { path, low, high } = useMemo(() => {
    const present = values.filter((value): value is number => value !== null);
    if (present.length < 2) return { path: '', low: 0, high: 0 };
    const min = Math.min(...present);
    const max = Math.max(...present);
    const span = max - min || 1;

    let open = false;
    const segments: string[] = [];
    values.forEach((value, index) => {
      if (value === null) {
        open = false;
        return;
      }
      const x = (index / (values.length - 1)) * 1000;
      const y = 100 - ((value - min) / span) * 92 - 4;
      segments.push(`${open ? 'L' : 'M'}${x},${y}`);
      open = true;
    });

    return { path: segments.join(' '), low: min, high: max };
  }, [values]);

  return (
    <div className="rounded-[10px] border border-hairline bg-sunken p-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-[11px] font-medium text-soft">{label}</span>
        <span className="shrink-0 text-[11px] text-mute tabular-nums">
          {low.toFixed(1)} – {high.toFixed(1)} {unit}
        </span>
      </div>
      <svg
        viewBox="0 0 1000 100"
        preserveAspectRatio="none"
        style={{ height }}
        className="mt-1 w-full"
      >
        <line
          x1="0"
          x2="1000"
          y1="50"
          y2="50"
          stroke="var(--hairline)"
          strokeWidth={1}
          vectorEffect="non-scaling-stroke"
        />
        {path && (
          <path
            d={path}
            fill="none"
            stroke={tone}
            strokeWidth={1.3}
            strokeLinejoin="round"
            vectorEffect="non-scaling-stroke"
          />
        )}
      </svg>
    </div>
  );
};
