import React from 'react';
import { bandOf, BAND_VAR } from './charts';
import { cx } from '../lib/cx';

/**
 * The 0–10 numeric rating scale. Each number carries its band colour as an underline,
 * so the clinician reads severity from the strip itself rather than from a legend.
 */
export const NrsScale: React.FC<{
  value: number | null;
  onChange?: (value: number) => void;
  /** A second, lighter marker — the model's estimate against the patient's answer. */
  ghost?: number | null;
  size?: 'sm' | 'md';
}> = ({ value, onChange, ghost = null, size = 'md' }) => {
  const scores = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10];
  const readOnly = onChange === undefined;

  return (
    <div>
      <div className="flex gap-1" role={readOnly ? undefined : 'radiogroup'} aria-label="Pain intensity">
        {scores.map((score) => {
          const selected = value === score;
          const isGhost = ghost !== null && Math.round(ghost) === score && !selected;
          return (
            <button
              key={score}
              type="button"
              role={readOnly ? undefined : 'radio'}
              aria-checked={readOnly ? undefined : selected}
              disabled={readOnly}
              onClick={() => onChange?.(score)}
              className={cx(
                'group relative flex-1 rounded-lg border font-medium transition-all duration-150',
                size === 'sm' ? 'h-8 text-[12px]' : 'h-10 text-[14px]',
                selected
                  ? 'border-transparent text-white shadow-lift'
                  : isGhost
                    ? 'border-violet/50 bg-violet/10 text-violet'
                    : 'border-hairline bg-surface text-soft',
                !readOnly && !selected && 'hover:border-hairline-strong hover:-translate-y-px',
              )}
              style={selected ? { background: BAND_VAR[bandOf(score)] } : undefined}
            >
              {score}
              <span
                aria-hidden
                className={cx(
                  'absolute inset-x-1.5 bottom-[3px] h-[2px] rounded-full transition-opacity',
                  selected ? 'opacity-0' : 'opacity-70',
                )}
                style={{ background: BAND_VAR[bandOf(score)] }}
              />
            </button>
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-[10px] text-faint">
        <span>0 · No pain</span>
        <span className="hidden sm:inline">5 · Moderate</span>
        <span>10 · Worst imaginable</span>
      </div>
    </div>
  );
};
