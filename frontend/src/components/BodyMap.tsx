import { useState } from 'react'

import type { Side } from '@/api/types'
import { SegmentedControl } from '@/components/ui/choice'
import { cn } from '@/utils/cn'

interface Zone {
  code: string
  side: Side
  label: string
  shape: { x: number; y: number; width: number; height: number; rx?: number } | null
  ellipse?: { cx: number; cy: number; rx: number; ry: number }
}

/**
 * Left and right are the patient's, not the viewer's, which is why the zone on the left of
 * the drawing carries side RIGHT on the anterior view and swaps on the posterior one.
 */
const LIMBS_FRONT: Zone[] = [
  { code: 'SHOULDER', side: 'RIGHT', label: 'Right shoulder', shape: { x: 42, y: 62, width: 26, height: 20, rx: 10 } },
  { code: 'SHOULDER', side: 'LEFT', label: 'Left shoulder', shape: { x: 132, y: 62, width: 26, height: 20, rx: 10 } },
  { code: 'ARM', side: 'RIGHT', label: 'Right arm', shape: { x: 40, y: 85, width: 19, height: 44, rx: 9 } },
  { code: 'ARM', side: 'LEFT', label: 'Left arm', shape: { x: 141, y: 85, width: 19, height: 44, rx: 9 } },
  { code: 'ELBOW', side: 'RIGHT', label: 'Right elbow', shape: { x: 40, y: 131, width: 19, height: 16, rx: 7 } },
  { code: 'ELBOW', side: 'LEFT', label: 'Left elbow', shape: { x: 141, y: 131, width: 19, height: 16, rx: 7 } },
  { code: 'FOREARM', side: 'RIGHT', label: 'Right forearm', shape: { x: 40, y: 149, width: 19, height: 40, rx: 9 } },
  { code: 'FOREARM', side: 'LEFT', label: 'Left forearm', shape: { x: 141, y: 149, width: 19, height: 40, rx: 9 } },
  { code: 'HAND', side: 'RIGHT', label: 'Right hand', shape: { x: 37, y: 191, width: 25, height: 25, rx: 10 } },
  { code: 'HAND', side: 'LEFT', label: 'Left hand', shape: { x: 138, y: 191, width: 25, height: 25, rx: 10 } },
  { code: 'HIP', side: 'RIGHT', label: 'Right hip', shape: { x: 66, y: 176, width: 31, height: 20, rx: 9 } },
  { code: 'HIP', side: 'LEFT', label: 'Left hip', shape: { x: 103, y: 176, width: 31, height: 20, rx: 9 } },
  { code: 'THIGH', side: 'RIGHT', label: 'Right thigh', shape: { x: 69, y: 198, width: 28, height: 58, rx: 13 } },
  { code: 'THIGH', side: 'LEFT', label: 'Left thigh', shape: { x: 103, y: 198, width: 28, height: 58, rx: 13 } },
  { code: 'KNEE', side: 'RIGHT', label: 'Right knee', shape: { x: 71, y: 258, width: 24, height: 19, rx: 9 } },
  { code: 'KNEE', side: 'LEFT', label: 'Left knee', shape: { x: 105, y: 258, width: 24, height: 19, rx: 9 } },
  { code: 'LEG', side: 'RIGHT', label: 'Right leg', shape: { x: 71, y: 279, width: 24, height: 54, rx: 11 } },
  { code: 'LEG', side: 'LEFT', label: 'Left leg', shape: { x: 105, y: 279, width: 24, height: 54, rx: 11 } },
  { code: 'ANKLE', side: 'RIGHT', label: 'Right ankle', shape: { x: 71, y: 335, width: 24, height: 14, rx: 6 } },
  { code: 'ANKLE', side: 'LEFT', label: 'Left ankle', shape: { x: 105, y: 335, width: 24, height: 14, rx: 6 } },
  { code: 'FOOT', side: 'RIGHT', label: 'Right foot', shape: { x: 67, y: 351, width: 28, height: 21, rx: 9 } },
  { code: 'FOOT', side: 'LEFT', label: 'Left foot', shape: { x: 105, y: 351, width: 28, height: 21, rx: 9 } },
]

const FRONT: Zone[] = [
  { code: 'HEAD', side: 'MIDLINE', label: 'Head', shape: null, ellipse: { cx: 100, cy: 28, rx: 22, ry: 27 } },
  { code: 'NECK', side: 'MIDLINE', label: 'Neck', shape: { x: 90, y: 52, width: 20, height: 15, rx: 6 } },
  { code: 'CHEST_RIGHT', side: 'RIGHT', label: 'Right chest', shape: { x: 68, y: 70, width: 20, height: 37, rx: 6 } },
  { code: 'CHEST_CENTRAL', side: 'MIDLINE', label: 'Central chest', shape: { x: 89, y: 70, width: 22, height: 37, rx: 4 } },
  { code: 'CHEST_LEFT', side: 'LEFT', label: 'Left chest', shape: { x: 112, y: 70, width: 20, height: 37, rx: 6 } },
  { code: 'ABD_RUQ', side: 'RIGHT', label: 'Right upper quadrant', shape: { x: 68, y: 109, width: 20, height: 22, rx: 4 } },
  { code: 'ABD_EPIGASTRIC', side: 'MIDLINE', label: 'Epigastric', shape: { x: 89, y: 109, width: 22, height: 22, rx: 4 } },
  { code: 'ABD_LUQ', side: 'LEFT', label: 'Left upper quadrant', shape: { x: 112, y: 109, width: 20, height: 22, rx: 4 } },
  { code: 'ABD_RLQ', side: 'RIGHT', label: 'Right lower quadrant', shape: { x: 68, y: 133, width: 20, height: 22, rx: 4 } },
  { code: 'ABD_PERIUMBILICAL', side: 'MIDLINE', label: 'Periumbilical', shape: { x: 89, y: 133, width: 22, height: 22, rx: 4 } },
  { code: 'ABD_LLQ', side: 'LEFT', label: 'Left lower quadrant', shape: { x: 112, y: 133, width: 20, height: 22, rx: 4 } },
  { code: 'ABD_SUPRAPUBIC', side: 'MIDLINE', label: 'Suprapubic', shape: { x: 82, y: 157, width: 36, height: 17, rx: 5 } },
  ...LIMBS_FRONT,
]

const BACK: Zone[] = [
  { code: 'OCCIPUT', side: 'MIDLINE', label: 'Occipital region', shape: null, ellipse: { cx: 100, cy: 28, rx: 22, ry: 27 } },
  { code: 'BACK_CERVICAL', side: 'MIDLINE', label: 'Cervical spine', shape: { x: 86, y: 52, width: 28, height: 20, rx: 6 } },
  { code: 'BACK_THORACIC', side: 'MIDLINE', label: 'Thoracic spine', shape: { x: 68, y: 74, width: 64, height: 48, rx: 7 } },
  { code: 'BACK_LUMBAR', side: 'MIDLINE', label: 'Lumbar spine', shape: { x: 73, y: 124, width: 54, height: 32, rx: 7 } },
  { code: 'BACK_SACRAL', side: 'MIDLINE', label: 'Sacral region', shape: { x: 81, y: 158, width: 38, height: 16, rx: 6 } },
  ...LIMBS_FRONT.map(mirrored),
]

/** The same shape seen from behind: the patient's left limb is now on the viewer's left. */
function mirrored(zone: Zone): Zone {
  if (zone.side !== 'LEFT' && zone.side !== 'RIGHT') return zone
  const side: Side = zone.side === 'LEFT' ? 'RIGHT' : 'LEFT'
  const part = zone.label.replace(/^(Left|Right) /, '')
  return { ...zone, side, label: `${side === 'LEFT' ? 'Left' : 'Right'} ${part}` }
}

export interface SelectedSite {
  code: string
  side: Side
}

export function BodyMap({
  selected,
  onToggle,
}: {
  selected: SelectedSite[]
  onToggle: (site: SelectedSite) => void
}) {
  const [view, setView] = useState<'front' | 'back'>('front')
  const zones = view === 'front' ? FRONT : BACK
  const isSelected = (zone: Zone) =>
    selected.some((site) => site.code === zone.code && site.side === zone.side)

  return (
    <div className="space-y-3">
      <SegmentedControl
        label="Body view"
        value={view}
        onChange={setView}
        options={[
          { value: 'front', label: 'Front' },
          { value: 'back', label: 'Back' },
        ]}
      />
      <svg
        viewBox="0 0 200 380"
        className="mx-auto h-auto w-full max-w-[17rem]"
        role="group"
        aria-label={`Body diagram, ${view} view`}
      >
        {zones.map((zone) => {
          const active = isSelected(zone)
          const className = cn(
            'cursor-pointer transition-colors',
            active
              ? 'fill-accent stroke-accent-strong'
              : 'fill-[#e8eff4] stroke-[#c3d2de] hover:fill-accent-soft',
          )
          const common = {
            className,
            strokeWidth: 1,
            role: 'checkbox' as const,
            'aria-checked': active,
            'aria-label': zone.label,
            tabIndex: 0,
            onClick: () => onToggle({ code: zone.code, side: zone.side }),
            onKeyDown: (event: React.KeyboardEvent<SVGElement>) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onToggle({ code: zone.code, side: zone.side })
              }
            },
          }
          return zone.ellipse ? (
            <ellipse key={`${zone.code}-${zone.side}`} {...zone.ellipse} {...common} />
          ) : (
            <rect key={`${zone.code}-${zone.side}`} {...zone.shape!} {...common} />
          )
        })}
      </svg>
      <p className="text-center text-xs text-muted">
        Left and right are the patient&rsquo;s. Selecting a site here is the same as ticking it in
        the list.
      </p>
    </div>
  )
}
