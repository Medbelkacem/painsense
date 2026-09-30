import { ArrowDownRight, ArrowRight, ArrowUpRight, FlaskConical } from 'lucide-react'

import type { BandCode, DataQuality, Trend } from '@/api/types'
import { Badge } from '@/components/ui/badge'

const BAND_TONE = {
  NONE: 'positive',
  MILD: 'positive',
  MODERATE: 'caution',
  SEVERE: 'alert',
  EXTREME: 'alert',
} as const

export function BandBadge({ band, label }: { band?: BandCode | null; label?: string | null }) {
  if (!band) return <Badge>No estimate</Badge>
  return <Badge tone={BAND_TONE[band]}>{label ?? band.toLowerCase()}</Badge>
}

const QUALITY_TONE = {
  GOOD: 'positive',
  ADEQUATE: 'accent',
  LIMITED: 'caution',
  INSUFFICIENT: 'alert',
} as const

export function QualityBadge({ quality }: { quality: DataQuality }) {
  return <Badge tone={QUALITY_TONE[quality]}>Data {quality.toLowerCase()}</Badge>
}

export function TrendTag({ trend, change }: { trend: Trend; change?: number | null }) {
  if (trend === 'UNKNOWN') return <span className="text-xs text-faint">Not enough history</span>
  const Icon = trend === 'RISING' ? ArrowUpRight : trend === 'FALLING' ? ArrowDownRight : ArrowRight
  const tone =
    trend === 'RISING' ? 'text-alert' : trend === 'FALLING' ? 'text-positive' : 'text-muted'
  return (
    <span className={`inline-flex items-center gap-1 text-xs font-medium ${tone}`}>
      <Icon aria-hidden className="size-3.5" />
      {trend.toLowerCase()}
      {change !== null && change !== undefined && (
        <span className="tabular">
          {change > 0 ? '+' : ''}
          {change.toFixed(1)}
        </span>
      )}
    </span>
  )
}

export function SyntheticTag({ compact = false }: { compact?: boolean }) {
  return (
    <Badge tone="caution">
      <FlaskConical aria-hidden className="size-3" />
      {compact ? 'Synthetic' : 'Synthetic record'}
    </Badge>
  )
}
