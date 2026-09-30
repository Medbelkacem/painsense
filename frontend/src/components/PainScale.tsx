import type { BandCode } from '@/api/types'
import { cn } from '@/utils/cn'

const BAND_FILL: Record<BandCode, string> = {
  NONE: 'bg-band-none',
  MILD: 'bg-band-mild',
  MODERATE: 'bg-band-moderate',
  SEVERE: 'bg-band-severe',
  EXTREME: 'bg-band-extreme',
}

const SEGMENTS: BandCode[] = [
  'NONE',
  'MILD',
  'MILD',
  'MILD',
  'MODERATE',
  'MODERATE',
  'MODERATE',
  'SEVERE',
  'SEVERE',
  'SEVERE',
  'EXTREME',
]

const clamp = (value: number) => Math.min(Math.max(value, 0), 10)

/**
 * The 0-10 scale with both numbers on it.
 *
 * The estimate and the patient's own score are drawn as separate markers on the same
 * track, never averaged into one. Where they disagree, the distance between them is the
 * point.
 */
export function PainScale({
  estimate,
  selfReport,
  intervalLow,
  intervalHigh,
  compact = false,
}: {
  estimate?: number | null
  selfReport?: number | null
  intervalLow?: number | null
  intervalHigh?: number | null
  compact?: boolean
}) {
  const hasInterval = intervalLow !== null && intervalLow !== undefined && intervalHigh != null

  return (
    <div className={cn('w-full', compact ? 'pt-5 pb-1' : 'pt-6 pb-1')}>
      <div className="relative">
        {hasInterval && (
          <div
            className="absolute -top-1 h-[calc(100%+0.5rem)] rounded bg-accent/12"
            style={{
              left: `${clamp(intervalLow) * 10}%`,
              width: `${(clamp(intervalHigh) - clamp(intervalLow)) * 10}%`,
            }}
            aria-hidden
          />
        )}

        <div className="relative flex h-2.5 gap-px overflow-hidden rounded">
          {SEGMENTS.map((band, index) => (
            <span
              key={index}
              className={cn('flex-1 opacity-30', BAND_FILL[band])}
              aria-hidden
            />
          ))}
        </div>

        {estimate !== null && estimate !== undefined && (
          <Marker value={estimate} tone="accent" label={`Estimate ${estimate.toFixed(1)}`} above />
        )}
        {selfReport !== null && selfReport !== undefined && (
          <Marker value={selfReport} tone="ink" label={`Self-report ${selfReport.toFixed(0)}`} />
        )}
      </div>

      <div className="mt-7 flex justify-between text-[0.625rem] text-faint tabular">
        {Array.from({ length: 11 }, (_, index) => (
          <span key={index}>{index}</span>
        ))}
      </div>
    </div>
  )
}

function Marker({
  value,
  tone,
  label,
  above = false,
}: {
  value: number
  tone: 'accent' | 'ink'
  label: string
  above?: boolean
}) {
  return (
    <div
      className="pointer-events-none absolute top-0 flex -translate-x-1/2 flex-col items-center"
      style={{ left: `${clamp(value) * 10}%` }}
    >
      <span
        className={cn(
          'absolute text-[0.6875rem] font-semibold whitespace-nowrap',
          above ? '-top-5' : 'top-3.5',
          tone === 'accent' ? 'text-accent-strong' : 'text-ink',
        )}
      >
        {label}
      </span>
      <span
        className={cn('h-2.5 w-0.5 rounded', tone === 'accent' ? 'bg-accent' : 'bg-ink')}
        aria-hidden
      />
    </div>
  )
}
