/**
 * Charts are hand-drawn SVG rather than a charting library. Every figure in this
 * product is one of six shapes, each wants a specific detail the generic components
 * fight you on — value labels sitting above bars, a shaded model range behind a line,
 * band colours that have to agree with the NRS scale — and the whole set costs less
 * than the library would.
 */
import React, { useMemo, useRef, useState } from 'react';
import { cx } from '../lib/cx';

export const BAND_COLOUR = ['none', 'mild', 'mild', 'mild', 'moderate', 'moderate', 'moderate', 'severe', 'severe', 'severe', 'severe'] as const;

export type Band = 'none' | 'mild' | 'moderate' | 'severe';

export const BAND_VAR: Record<Band, string> = {
  none: 'var(--band-none)',
  mild: 'var(--band-mild)',
  moderate: 'var(--band-moderate)',
  severe: 'var(--band-severe)',
};

export function bandOf(score: number): Band {
  return BAND_COLOUR[Math.max(0, Math.min(10, Math.round(score)))];
}

export const BAND_LABEL: Record<Band, string> = {
  none: 'No pain',
  mild: 'Mild',
  moderate: 'Moderate',
  severe: 'Severe',
};

/** Catmull-Rom through the points, converted to cubic béziers. Keeps trends readable
 *  without the overshoot a naive smoothing gives on a 0–10 scale. */
function curveThrough(points: readonly [number, number][]): string {
  const d: string[] = [];
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[i - 1] ?? points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] ?? p2;
    d.push(
      `C${p1[0] + (p2[0] - p0[0]) / 6},${p1[1] + (p2[1] - p0[1]) / 6} ` +
        `${p2[0] - (p3[0] - p1[0]) / 6},${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]},${p2[1]}`,
    );
  }
  return d.join(' ');
}

function smoothPath(points: readonly [number, number][]): string {
  if (points.length < 2) return '';
  return `M${points[0][0]},${points[0][1]} ${curveThrough(points)}`;
}

/* -------------------------------------------------------------------------- */

export const Sparkline: React.FC<{
  values: readonly number[];
  tone?: string;
  filled?: boolean;
  className?: string;
}> = ({ values, tone = 'var(--accent)', filled = true, className }) => {
  const w = 100;
  const h = 32;
  const low = Math.min(...values);
  const span = Math.max(...values) - low || 1;
  const points = values.map(
    (value, i) =>
      [(i / (values.length - 1)) * w, h - 3 - ((value - low) / span) * (h - 8)] as [number, number],
  );
  const line = smoothPath(points);

  return (
    <svg viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" className={cx('h-8 w-full', className)}>
      {filled && (
        <path d={`${line} L${w},${h} L0,${h} Z`} fill={tone} opacity={0.1} />
      )}
      <path d={line} fill="none" stroke={tone} strokeWidth={1.8} strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
};

/* -------------------------------------------------------------------------- */

/** NRS distribution: eleven bars, one per score, coloured by band. */
export const BandBars: React.FC<{
  counts: readonly number[];
  className?: string;
  showLabels?: boolean;
}> = ({ counts, className, showLabels = true }) => {
  const peak = Math.max(...counts, 1);
  return (
    <div className={cx('flex items-end gap-[3px]', className)}>
      {counts.map((count, score) => {
        const band = bandOf(score);
        return (
          <div key={score} className="group flex min-w-0 flex-1 flex-col items-center gap-1">
            {showLabels && (
              <span className="text-[10px] font-medium text-mute tabular-nums">{count}</span>
            )}
            <div className="flex w-full items-end" style={{ height: 150 }}>
              <div
                className="w-full rounded-t-[3px] transition-[height,opacity] duration-500 ease-out group-hover:opacity-80"
                style={{
                  height: `${Math.max(3, (count / peak) * 100)}%`,
                  background: BAND_VAR[band],
                }}
                title={`NRS ${score} · ${count} assessments`}
              />
            </div>
            <span className="text-[10px] text-faint tabular-nums">{score}</span>
          </div>
        );
      })}
    </div>
  );
};

/* -------------------------------------------------------------------------- */

export interface TrendPoint {
  label: string;
  reported: number;
  estimate: number;
  /** Half-width of the model's interval, drawn as the shaded ribbon. */
  spread?: number;
}

/**
 * Patient NRS against the model estimate. The ribbon is the point of the chart: a
 * clinician needs to see at a glance whether the two lines disagree by more than the
 * model's own uncertainty.
 */
export const TrendChart: React.FC<{ points: readonly TrendPoint[]; height?: number }> = ({
  points,
  height = 230,
}) => {
  const box = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const w = 600;
  const h = height;
  const pad = { top: 14, right: 16, bottom: 26, left: 26 };
  const plotW = w - pad.left - pad.right;
  const plotH = h - pad.top - pad.bottom;

  const x = (i: number) => pad.left + (points.length === 1 ? plotW / 2 : (i / (points.length - 1)) * plotW);
  const y = (value: number) => pad.top + plotH - (value / 10) * plotH;

  const reported = smoothPath(points.map((point, i) => [x(i), y(point.reported)]));
  const estimate = smoothPath(points.map((point, i) => [x(i), y(point.estimate)]));
  // Upper edge left-to-right, lower edge back again — one closed shape, so the fill
  // never leaks when two consecutive estimates sit on top of each other.
  const ribbon = useMemo(() => {
    const edge = (sign: 1 | -1) =>
      points.map(
        (point, i) =>
          [x(i), y(Math.max(0, Math.min(10, point.estimate + sign * (point.spread ?? 0.6))))] as [
            number,
            number,
          ],
      );
    const lower = edge(-1).reverse();
    return `${smoothPath(edge(1))} L${lower[0][0]},${lower[0][1]} ${curveThrough(lower)} Z`;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [points, height]);

  function track(event: React.PointerEvent) {
    const rect = box.current?.getBoundingClientRect();
    if (!rect) return;
    const ratio = ((event.clientX - rect.left) / rect.width) * w;
    const nearest = Math.round(((ratio - pad.left) / plotW) * (points.length - 1));
    setHover(Math.max(0, Math.min(points.length - 1, nearest)));
  }

  const active = hover === null ? null : points[hover];

  return (
    <div ref={box} className="relative" onPointerMove={track} onPointerLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full" style={{ height }}>
        {/* Severe zone, so a line crossing 7 is obvious without reading the axis. */}
        <rect x={pad.left} y={y(10)} width={plotW} height={y(7) - y(10)} fill="var(--band-severe)" opacity={0.05} />
        <text x={w - pad.right - 4} y={y(10) + 11} textAnchor="end" className="fill-[var(--band-severe)] text-[8px] font-semibold tracking-wider opacity-70">
          SEVERE
        </text>

        {[0, 2, 4, 6, 8, 10].map((tick) => (
          <g key={tick}>
            <line x1={pad.left} x2={w - pad.right} y1={y(tick)} y2={y(tick)} stroke="var(--hairline)" strokeWidth={1} />
            <text x={pad.left - 6} y={y(tick) + 3} textAnchor="end" className="fill-[var(--text-faint)] text-[9px]">
              {tick}
            </text>
          </g>
        ))}

        <path d={ribbon} fill="var(--brand-violet)" opacity={0.14} />
        <path d={estimate} fill="none" stroke="var(--brand-violet)" strokeWidth={2} strokeDasharray="5 4" strokeLinecap="round" />
        <path d={reported} fill="none" stroke="var(--accent)" strokeWidth={2.4} strokeLinecap="round" />

        {points.map((point, i) => (
          <circle
            key={point.label}
            cx={x(i)}
            cy={y(point.reported)}
            r={hover === i ? 5 : 3.5}
            fill="var(--surface)"
            stroke="var(--accent)"
            strokeWidth={2}
            className="transition-[r] duration-150"
          />
        ))}

        {hover !== null && (
          <line x1={x(hover)} x2={x(hover)} y1={pad.top} y2={pad.top + plotH} stroke="var(--hairline-strong)" strokeWidth={1} strokeDasharray="3 3" />
        )}

        {points.map((point, i) =>
          i % Math.ceil(points.length / 6) === 0 || i === points.length - 1 ? (
            <text key={point.label} x={x(i)} y={h - 8} textAnchor="middle" className="fill-[var(--text-faint)] text-[9px]">
              {point.label}
            </text>
          ) : null,
        )}
      </svg>

      {active && hover !== null && (
        <div
          className="pointer-events-none absolute -top-1 z-10 w-max rounded-lg border border-hairline bg-surface px-2.5 py-1.5 text-[11px] shadow-pop"
          style={{ left: `${(x(hover) / w) * 100}%`, transform: 'translateX(-50%)' }}
        >
          <div className="font-medium text-ink">{active.label}</div>
          <div className="mt-0.5 text-mute">
            NRS <span className="font-semibold text-accent-ink">{active.reported}</span> · AI{' '}
            <span className="font-semibold text-violet">{active.estimate.toFixed(1)}</span>
          </div>
        </div>
      )}
    </div>
  );
};

/* -------------------------------------------------------------------------- */

export const Gauge: React.FC<{
  value: number;
  max?: number;
  size?: number;
  caption?: string;
}> = ({ value, max = 10, size = 168, caption }) => {
  const stroke = 12;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  // A 270° sweep: the gap at the bottom carries the caption without a second element.
  const arc = circumference * 0.75;
  const filled = (value / max) * arc;
  const band = bandOf((value / max) * 10);

  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg width={size} height={size} className="-rotate-[225deg]">
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke="var(--hairline)"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${arc} ${circumference}`}
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={r}
          fill="none"
          stroke={BAND_VAR[band]}
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={`${filled} ${circumference}`}
          style={{ transition: 'stroke-dasharray 700ms cubic-bezier(.22,1,.36,1)' }}
        />
      </svg>
      <div className="absolute flex flex-col items-center">
        <span className="text-[34px] leading-none font-semibold text-ink tabular-nums">
          {value.toFixed(1)}
        </span>
        <span className="mt-1 text-[11px] text-mute">{caption ?? `of ${max}`}</span>
      </div>
    </div>
  );
};

/* -------------------------------------------------------------------------- */

export const Donut: React.FC<{
  slices: readonly { label: string; value: number; colour: string }[];
  size?: number;
}> = ({ slices, size = 132 }) => {
  const total = slices.reduce((sum, slice) => sum + slice.value, 0) || 1;
  const stroke = 18;
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  let offset = 0;

  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90 shrink-0">
      {slices.map((slice) => {
        const length = (slice.value / total) * circumference;
        const dash = `${Math.max(0, length - 2)} ${circumference}`;
        const node = (
          <circle
            key={slice.label}
            cx={size / 2}
            cy={size / 2}
            r={r}
            fill="none"
            stroke={slice.colour}
            strokeWidth={stroke}
            strokeDasharray={dash}
            strokeDashoffset={-offset}
          >
            <title>{`${slice.label}: ${Math.round((slice.value / total) * 100)}%`}</title>
          </circle>
        );
        offset += length;
        return node;
      })}
    </svg>
  );
};

/* -------------------------------------------------------------------------- */

/** Horizontal ranked bars — pain by location, model feature importance. */
export const BarRows: React.FC<{
  rows: readonly { label: string; value: number; note?: string }[];
  colour?: string;
  format?: (value: number) => string;
}> = ({ rows, colour = 'var(--accent)', format = (value) => String(value) }) => {
  const peak = Math.max(...rows.map((row) => row.value), 1);
  return (
    <div className="space-y-2">
      {rows.map((row) => (
        <div key={row.label} className="flex items-center gap-3 text-[12px]">
          <span className="w-28 shrink-0 truncate text-mute">{row.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-sunken">
            <div
              className="h-full rounded-full transition-[width] duration-700 ease-out"
              style={{ width: `${(row.value / peak) * 100}%`, background: colour }}
            />
          </div>
          <span className="w-12 shrink-0 text-right font-medium text-ink tabular-nums">
            {format(row.value)}
          </span>
          {row.note && <span className="w-10 shrink-0 text-right text-faint">{row.note}</span>}
        </div>
      ))}
    </div>
  );
};

/* -------------------------------------------------------------------------- */

/** AI estimate against self-reported NRS, with the perfect-agreement diagonal. */
export const AgreementPlot: React.FC<{
  points: readonly { reported: number; estimate: number }[];
  height?: number;
}> = ({ points, height = 190 }) => {
  const size = 180;
  const pad = 20;
  const to = (value: number) => pad + (value / 10) * (size - 2 * pad);

  return (
    <svg viewBox={`0 0 ${size} ${size}`} style={{ height }} className="w-full">
      <line x1={pad} y1={size - pad} x2={size - pad} y2={pad} stroke="var(--hairline-strong)" strokeWidth={1} strokeDasharray="4 3" />
      {[0, 5, 10].map((tick) => (
        <g key={tick}>
          <text x={to(tick)} y={size - 4} textAnchor="middle" className="fill-[var(--text-faint)] text-[7px]">{tick}</text>
          <text x={6} y={size - to(tick) + 2} className="fill-[var(--text-faint)] text-[7px]">{tick}</text>
        </g>
      ))}
      {points.map((point, i) => (
        <circle
          key={i}
          cx={to(point.reported)}
          cy={size - to(point.estimate)}
          r={2.6}
          fill={BAND_VAR[bandOf(point.reported)]}
          opacity={0.55}
        />
      ))}
    </svg>
  );
};

/* -------------------------------------------------------------------------- */

/** The teal signal trace on the sign-in panel. Deterministic, so it does not
 *  shimmer differently on every render. */
export const Waveform: React.FC<{ className?: string; seed?: number }> = ({ className, seed = 7 }) => {
  const path = useMemo(() => {
    let state = seed * 9301 + 49297;
    const next = () => {
      state = (state * 9301 + 49297) % 233280;
      return state / 233280;
    };
    const points: [number, number][] = [];
    for (let i = 0; i <= 64; i += 1) {
      const base = Math.sin(i / 5) * 12 + Math.sin(i / 2.1) * 5;
      points.push([(i / 64) * 600, 50 + base + (next() - 0.5) * 9]);
    }
    return smoothPath(points);
  }, [seed]);

  return (
    <svg viewBox="0 0 600 100" preserveAspectRatio="none" className={cx('w-full', className)}>
      <path
        d={path}
        fill="none"
        stroke="var(--brand-teal)"
        strokeWidth={1.6}
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
};
