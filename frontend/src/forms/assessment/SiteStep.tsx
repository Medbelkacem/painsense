import { AnatomyMapper } from '@/anatomy/AnatomyMapper'
import { useLocations } from '@/api/queries'
import type { PatientDetail, Side } from '@/api/types'
import { BodyMap } from '@/components/BodyMap'
import { Chip, ChipGroup } from '@/components/ui/choice'
import { Notice, Spinner } from '@/components/ui/feedback'
import type { Draft, DraftSite } from './draft'

const SIDES: { value: Side; label: string }[] = [
  { value: 'NOT_APPLICABLE', label: 'Not applicable' },
  { value: 'LEFT', label: 'Left' },
  { value: 'RIGHT', label: 'Right' },
  { value: 'BILATERAL', label: 'Both' },
  { value: 'MIDLINE', label: 'Midline' },
]

/**
 * Where the pain is, recorded either way round.
 *
 * The 3D model names a structure and the flat diagram names a region. Both are kept: the
 * structure is the finer record and the region is what a clinician falls back on, and every
 * structure also records a region so nothing downstream has to know which was used.
 */
export function SiteStep({
  draft,
  update,
  patient,
}: {
  draft: Draft
  update: (patch: Partial<Draft>) => void
  patient: PatientDetail
}) {
  const locations = useLocations()

  const toggle = (site: { code: string; side: Side }) => {
    const existing = draft.locations.find(
      (entry) => entry.code === site.code && entry.side === site.side,
    )
    const next = existing
      ? draft.locations.filter((entry) => entry !== existing)
      : [...draft.locations, { ...site, is_primary: draft.locations.length === 0 }]
    update({ locations: ensureOnePrimary(next) })
  }

  const setSide = (target: DraftSite, side: Side) =>
    update({
      locations: draft.locations.map((entry) => (entry === target ? { ...entry, side } : entry)),
    })

  const setPrimary = (target: DraftSite) =>
    update({
      locations: draft.locations.map((entry) => ({ ...entry, is_primary: entry === target })),
    })

  if (locations.isPending) return <Spinner />

  const byRegion = new Map<string, typeof locations.data>()
  for (const entry of locations.data ?? []) {
    const list = byRegion.get(entry.region) ?? []
    list.push(entry)
    byRegion.set(entry.region, list)
  }

  const nothingYet = draft.locations.length === 0 && draft.anatomical_sites.length === 0

  return (
    <div className="space-y-8">
      <AnatomyMapper
        sites={draft.anatomical_sites}
        onChange={(anatomical_sites) => update({ anatomical_sites })}
        sex={patient.sex}
      />

      {nothingYet && (
        <Notice tone="caution">
          Record at least one site. Nothing else in the assessment can be interpreted without
          one.
        </Notice>
      )}

      <section className="space-y-4 border-t border-line pt-6">
        <div>
          <h3 className="text-sm font-semibold text-ink">Regions</h3>
          <p className="text-[0.8125rem] text-muted">
            The flat diagram and the region list record a site without naming a structure. Use
            them when the examination did not localise the pain any further.
          </p>
        </div>

        <div className="grid gap-6 lg:grid-cols-[minmax(0,18rem)_1fr]">
          <BodyMap
            selected={draft.locations.map((site) => ({ code: site.code, side: site.side }))}
            onToggle={toggle}
          />

          <div className="space-y-5">
            {draft.locations.length > 0 && (
              <div className="space-y-2 rounded-md border border-line bg-raised p-3">
                <p className="text-sm font-semibold text-ink">Selected regions</p>
                {draft.locations.map((site) => (
                  <div
                    key={`${site.code}-${site.side}`}
                    className="flex flex-wrap items-center justify-between gap-2 border-t border-line pt-2 first:border-0 first:pt-0"
                  >
                    <span className="text-sm text-ink">
                      {locations.data?.find((entry) => entry.code === site.code)?.label ??
                        site.code}
                    </span>
                    <div className="flex flex-wrap items-center gap-2">
                      <select
                        value={site.side}
                        onChange={(event) => setSide(site, event.target.value as Side)}
                        aria-label="Side"
                        className="rounded border border-line bg-surface px-2 py-1 text-xs text-body"
                      >
                        {SIDES.map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      <button
                        type="button"
                        onClick={() => setPrimary(site)}
                        className={
                          site.is_primary
                            ? 'rounded-full bg-accent-soft px-2 py-1 text-xs font-medium text-accent-strong'
                            : 'rounded-full px-2 py-1 text-xs text-muted hover:text-ink'
                        }
                      >
                        {site.is_primary ? 'Main region' : 'Set as main'}
                      </button>
                      <button
                        type="button"
                        onClick={() => toggle(site)}
                        aria-label={`Remove ${site.code}`}
                        className="text-xs text-muted hover:text-alert"
                      >
                        Remove
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}

            <div className="space-y-4">
              {[...byRegion.entries()].map(([region, entries]) => (
                <div key={region}>
                  <p className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">
                    {region.toLowerCase().replaceAll('_', ' ')}
                  </p>
                  <ChipGroup>
                    {entries?.map((entry) => (
                      <Chip
                        key={entry.code}
                        selected={draft.locations.some((site) => site.code === entry.code)}
                        onClick={() =>
                          toggle({
                            code: entry.code,
                            side:
                              draft.locations.find((site) => site.code === entry.code)?.side ??
                              'NOT_APPLICABLE',
                          })
                        }
                      >
                        {entry.label}
                      </Chip>
                    ))}
                  </ChipGroup>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}

function ensureOnePrimary(sites: DraftSite[]): DraftSite[] {
  if (!sites.length || sites.some((site) => site.is_primary)) return sites
  return sites.map((site, index) => ({ ...site, is_primary: index === 0 }))
}
