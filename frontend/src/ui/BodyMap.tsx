import React from 'react';
import { cx } from '../lib/cx';

export type BodyView = 'front' | 'back';

interface Region {
  id: string;
  label: string;
  /** Mirrored automatically for the paired limbs, so each pair is written once. */
  shape: { kind: 'rect'; x: number; y: number; w: number; h: number; r: number }
    | { kind: 'ellipse'; cx: number; cy: number; rx: number; ry: number };
}

const MID = 100;

function mirror(region: Region, id: string, label: string): Region {
  const { shape } = region;
  return {
    id,
    label,
    shape:
      shape.kind === 'rect'
        ? { ...shape, x: 2 * MID - shape.x - shape.w }
        : { ...shape, cx: 2 * MID - shape.cx },
  };
}

const rect = (x: number, y: number, w: number, h: number, r: number) =>
  ({ kind: 'rect', x, y, w, h, r }) as const;
const ellipse = (cx: number, cy: number, rx: number, ry: number) =>
  ({ kind: 'ellipse', cx, cy, rx, ry }) as const;

/* Limbs are shared by both views; only the torso regions differ. */
const limbs: Region[] = (() => {
  const left: Region[] = [
    { id: 'shoulder-l', label: 'Left shoulder', shape: ellipse(61, 85, 14, 13) },
    { id: 'upper-arm-l', label: 'Left upper arm', shape: rect(48, 94, 22, 56, 11) },
    { id: 'forearm-l', label: 'Left forearm', shape: rect(44, 153, 20, 52, 10) },
    { id: 'hand-l', label: 'Left hand', shape: ellipse(54, 218, 11, 14) },
    { id: 'thigh-l', label: 'Left thigh', shape: rect(74, 212, 24, 72, 12) },
    { id: 'knee-l', label: 'Left knee', shape: ellipse(86, 291, 12, 11) },
    { id: 'shin-l', label: 'Left lower leg', shape: rect(76, 300, 20, 66, 10) },
    { id: 'foot-l', label: 'Left foot', shape: rect(72, 369, 24, 18, 8) },
  ];
  return [
    ...left,
    ...left.map((region) =>
      mirror(region, region.id.replace(/-l$/, '-r'), region.label.replace('Left', 'Right')),
    ),
  ];
})();

const torso: Record<BodyView, Region[]> = {
  front: [
    { id: 'head', label: 'Head', shape: ellipse(100, 35, 21, 26) },
    { id: 'neck', label: 'Neck', shape: rect(90, 55, 20, 16, 7) },
    { id: 'chest', label: 'Chest', shape: rect(68, 70, 64, 52, 14) },
    { id: 'abdomen', label: 'Abdomen', shape: rect(70, 125, 60, 46, 12) },
    { id: 'pelvis', label: 'Pelvis', shape: rect(72, 174, 56, 34, 14) },
  ],
  back: [
    { id: 'head-back', label: 'Head (posterior)', shape: ellipse(100, 35, 21, 26) },
    { id: 'nape', label: 'Nape', shape: rect(90, 55, 20, 16, 7) },
    { id: 'upper-back', label: 'Upper back', shape: rect(68, 70, 64, 50, 14) },
    { id: 'lower-back', label: 'Lower back', shape: rect(70, 123, 60, 48, 12) },
    { id: 'buttocks', label: 'Buttocks', shape: rect(72, 174, 56, 34, 14) },
  ],
};

export function regionsFor(view: BodyView): Region[] {
  return [...torso[view], ...limbs];
}

export function regionLabel(id: string | null): string | null {
  if (id === null) return null;
  for (const view of ['front', 'back'] as const) {
    const match = regionsFor(view).find((region) => region.id === id);
    if (match) return match.label;
  }
  return null;
}

interface BodyMapProps {
  view: BodyView;
  selected: string | null;
  onSelect: (id: string) => void;
  /** Heat per region id, 0–10 — paints a history of where this patient hurts. */
  intensity?: Record<string, number>;
  className?: string;
}

export const BodyMap: React.FC<BodyMapProps> = ({
  view,
  selected,
  onSelect,
  intensity,
  className,
}) => (
  <svg viewBox="0 0 200 400" className={cx('w-full', className)} role="group" aria-label={`Body map, ${view} view`}>
    {regionsFor(view).map((region) => {
      const active = selected === region.id;
      const heat = intensity?.[region.id];
      const common = {
        className: cx(
          'cursor-pointer transition-[fill,stroke] duration-200 outline-none',
          'focus-visible:stroke-[var(--accent)]',
        ),
        stroke: active ? 'var(--brand-teal-ink)' : 'var(--hairline-strong)',
        strokeWidth: active ? 1.8 : 1,
        fill: active
          ? 'var(--brand-teal)'
          : heat
            ? `color-mix(in srgb, var(--band-severe) ${Math.round(heat * 8)}%, var(--surface-sunken))`
            : 'var(--surface-sunken)',
        fillOpacity: active ? 0.55 : 1,
        tabIndex: 0,
        role: 'button' as const,
        'aria-pressed': active,
        onClick: () => onSelect(region.id),
        onKeyDown: (event: React.KeyboardEvent) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.preventDefault();
            onSelect(region.id);
          }
        },
      };

      return (
        <g key={region.id}>
          {region.shape.kind === 'rect' ? (
            <rect
              x={region.shape.x}
              y={region.shape.y}
              width={region.shape.w}
              height={region.shape.h}
              rx={region.shape.r}
              {...common}
            >
              <title>{region.label}</title>
            </rect>
          ) : (
            <ellipse
              cx={region.shape.cx}
              cy={region.shape.cy}
              rx={region.shape.rx}
              ry={region.shape.ry}
              {...common}
            >
              <title>{region.label}</title>
            </ellipse>
          )}
        </g>
      );
    })}
  </svg>
);
