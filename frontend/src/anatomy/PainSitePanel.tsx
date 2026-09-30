import { Crosshair, X } from 'lucide-react'

import type { AnatomicalSite, AnatomicalStructure, Location, Side } from '@/api/types'
import { Badge } from '@/components/ui/badge'
import { Select, Textarea } from '@/components/ui/field'
import { Notice } from '@/components/ui/feedback'
import { cn } from '@/utils/cn'
import { bandOf } from './palette'
import { recordedLocations } from './sites'

const SCORES = Array.from({ length: 11 }, (_, index) => index)

const SIDE_LABEL: Record<Side, string> = {
  LEFT: 'Left',
  RIGHT: 'Right',
  BILATERAL: 'Both sides',
  MIDLINE: 'Midline',
  NOT_APPLICABLE: 'Not applicable',
}

const BAND_TEXT = {
  NONE: 'text-band-none',
  MILD: 'text-band-mild',
  MODERATE: 'text-band-moderate',
  SEVERE: 'text-band-severe',
  EXTREME: 'text-band-extreme',
} as const

export interface SiteActions {
  setSide: (code: string, from: Side, to: Side) => void
  setIntensity: (code: string, side: Side, intensity: number | null) => void
  setNote: (code: string, side: Side, note: string) => void
  setMainSite: (code: string, side: Side) => void
  remove: (code: string, side: Side) => void
  locate: (code: string, side: Side) => void
}

/**
 * The pain assessment for the structures that have been localised.
 *
 * Opens on the site that was just selected and stays open for every site, so a record with
 * several painful structures is filled in without changing screens. The intensity here is
 * per site: it is kept with the record and printed on the report, and it is not one of the
 * values the estimate is built from.
 */
export function PainSitePanel({
  sites,
  structures,
  locations,
  focused,
  actions,
}: {
  sites: readonly AnatomicalSite[]
  structures: Map<string, AnatomicalStructure>
  locations: readonly Location[]
  /** The site the clinician just picked, which is the one scrolled into view and outlined. */
  focused: string | null
  actions: SiteActions
}) {
  if (!sites.length) {
    return (
      <Notice tone="caution" title="No structure recorded yet">
        Click a structure on the model, or choose one from the list. Where the examination does
        not identify a structure, pick the region instead: the record then says what was
        actually found.
      </Notice>
    )
  }

  const projected = recordedLocations(sites, structures)
  const labelFor = (code: string) =>
    locations.find((entry) => entry.code === code)?.label ?? code

  return (
    <div className="space-y-3">
      {sites.map((site) => {
        const structure = structures.get(site.structure_code)
        const key = `${site.structure_code}|${site.side}`
        const band = site.intensity === null ? null : bandOf(site.intensity)
        const name = structure?.label ?? site.structure_code
        // The same structure can be recorded on both sides, so every control names the
        // side too. Without it the left and the right knee would be one control to a
        // screen reader, and to a test.
        const named =
          site.side === 'MIDLINE' || site.side === 'NOT_APPLICABLE'
            ? name
            : `${name}, ${site.side.toLowerCase()}`
        return (
          <article
            key={key}
            aria-label={named}
            className={cn(
              'space-y-3 rounded-md border bg-surface p-3',
              key === focused ? 'border-accent ring-1 ring-accent' : 'border-line',
            )}
          >
            <header className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0">
                <p className="flex flex-wrap items-center gap-1.5 text-sm font-semibold text-ink">
                  {name}
                  {site.is_primary && <Badge tone="accent">Main site</Badge>}
                </p>
                <p className="text-xs text-muted">
                  {structure?.latin && <em>{structure.latin} · </em>}
                  <span className="tabular">{site.structure_code}</span>
                </p>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  aria-label={`Show ${named} on the model`}
                  onClick={() => actions.locate(site.structure_code, site.side)}
                  className="inline-flex size-7 items-center justify-center rounded text-muted hover:bg-canvas hover:text-ink"
                >
                  <Crosshair aria-hidden className="size-4" />
                </button>
                <button
                  type="button"
                  aria-label={`Remove ${named}`}
                  onClick={() => actions.remove(site.structure_code, site.side)}
                  className="inline-flex size-7 items-center justify-center rounded text-muted hover:bg-alert-soft hover:text-alert"
                >
                  <X aria-hidden className="size-4" />
                </button>
              </div>
            </header>

            <div className="flex flex-wrap items-end gap-3">
              <label className="text-xs text-muted">
                Side
                <Select
                  value={site.side}
                  aria-label={`Side for ${named}`}
                  onChange={(event) =>
                    actions.setSide(site.structure_code, site.side, event.target.value as Side)
                  }
                  disabled={(structure?.sides.length ?? 1) < 2}
                  className="mt-1 w-40 py-1.5 text-xs"
                >
                  {(structure?.sides ?? [site.side]).map((option) => (
                    <option key={option} value={option}>
                      {SIDE_LABEL[option]}
                    </option>
                  ))}
                </Select>
              </label>
              {!site.is_primary && (
                <button
                  type="button"
                  onClick={() => actions.setMainSite(site.structure_code, site.side)}
                  className="rounded-full px-2 py-1 text-xs text-muted hover:text-ink"
                >
                  Set as main site
                </button>
              )}
            </div>

            <fieldset>
              <legend className="mb-1.5 text-xs text-muted">
                Pain at this site, 0 to 10
                {band && (
                  <span className={cn('ml-1.5 font-medium', BAND_TEXT[band])}>
                    {band.toLowerCase()}
                  </span>
                )}
              </legend>
              <div className="flex flex-wrap gap-1">
                {SCORES.map((score) => (
                  <button
                    key={score}
                    type="button"
                    aria-pressed={site.intensity === score}
                    aria-label={`${score} at ${named}`}
                    onClick={() =>
                      actions.setIntensity(
                        site.structure_code,
                        site.side,
                        site.intensity === score ? null : score,
                      )
                    }
                    className={cn(
                      'size-8 rounded border text-xs font-medium transition-colors tabular',
                      site.intensity === score
                        ? 'border-accent bg-accent text-white'
                        : 'border-line bg-surface text-body hover:border-line-strong hover:bg-canvas',
                    )}
                  >
                    {score}
                  </button>
                ))}
              </div>
            </fieldset>

            <label className="block text-xs text-muted">
              Note on this site
              <Textarea
                rows={2}
                value={site.note ?? ''}
                aria-label={`Note for ${named}`}
                onChange={(event) =>
                  actions.setNote(site.structure_code, site.side, event.target.value)
                }
                placeholder="Tender on palpation, swelling, scar"
                className="mt-1 text-sm"
              />
            </label>
          </article>
        )
      })}

      <div className="rounded-md border border-line bg-raised p-3">
        <p className="text-xs font-medium tracking-wide text-muted uppercase">
          Recorded as pain sites
        </p>
        <p className="mt-1 text-[0.8125rem] text-body">
          {projected
            .map(
              ({ code, side }) =>
                `${labelFor(code)}${
                  side === 'MIDLINE' || side === 'NOT_APPLICABLE' ? '' : ` (${side.toLowerCase()})`
                }`,
            )
            .join(', ')}
        </p>
        <p className="mt-1.5 text-xs text-muted">
          Each structure also records a site in the platform&rsquo;s pain-location taxonomy. That
          is what the questionnaire, the alerts and the estimate read; the structure itself is
          kept alongside it.
        </p>
      </div>
    </div>
  )
}
