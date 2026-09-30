import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import type { AnatomicalStructure, AnatomyOntology } from '@/api/types'
import { Input } from '@/components/ui/field'
import { cn } from '@/utils/cn'
import { TISSUE } from './palette'
import { matches } from './sites'

/**
 * The structure list: regions, then structure types, then structures.
 *
 * This is the path that works without a pointer and without WebGL, and the only way to
 * reach a structure the model draws no geometry for, such as "generalised, no single site".
 * It shows the same ontology the 3D model is built from, in the nesting the API serves.
 *
 * Searching matches the label, the Latin name and the clinical synonyms, and opens every
 * region that has a hit so a clinician typing "sciatica" is not asked where to look.
 */
export function StructureBrowser({
  ontology,
  offered,
  selectedCodes,
  onSelect,
}: {
  ontology: AnatomyOntology
  /** Structures this patient can have, already filtered for sex by the caller. */
  offered: readonly AnatomicalStructure[]
  selectedCodes: ReadonlySet<string>
  onSelect: (structure: AnatomicalStructure) => void
}) {
  const [query, setQuery] = useState('')
  const [open, setOpen] = useState<string | null>(null)

  const byCode = useMemo(
    () => new Map(offered.map((structure) => [structure.code, structure])),
    [offered],
  )
  const typeLabels = useMemo(
    () => new Map(ontology.structure_types.map((entry) => [entry.code, entry.label])),
    [ontology.structure_types],
  )

  const regions = useMemo(
    () =>
      ontology.tree
        .map((region) => ({
          ...region,
          types: region.types
            .map((group) => ({
              ...group,
              label: typeLabels.get(group.type) ?? group.label,
              entries: group.structures
                .map((code) => byCode.get(code))
                .filter((structure): structure is AnatomicalStructure => Boolean(structure))
                .filter((structure) => matches(structure, query)),
            }))
            .filter((group) => group.entries.length),
        }))
        .filter((region) => region.types.length),
    [ontology.tree, byCode, typeLabels, query],
  )

  const searching = query.trim().length > 0
  const total = regions.reduce(
    (count, region) => count + region.types.reduce((sum, group) => sum + group.entries.length, 0),
    0,
  )

  return (
    <div className="space-y-2">
      <div className="relative">
        <Search
          aria-hidden
          className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint"
        />
        <Input
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search a structure, Latin name or synonym"
          aria-label="Search the anatomy"
          className="pl-9"
        />
      </div>

      {searching && (
        <p className="text-xs text-muted" role="status">
          {total === 0
            ? 'Nothing in the ontology matches that.'
            : `${total} ${total === 1 ? 'structure matches' : 'structures match'}.`}
        </p>
      )}

      <div className="max-h-[26rem] space-y-1 overflow-y-auto pr-1">
        {regions.map((region) => {
          const expanded = searching || open === region.region
          return (
            <section key={region.region}>
              <h4>
                <button
                  type="button"
                  aria-expanded={expanded}
                  onClick={() => setOpen(open === region.region ? null : region.region)}
                  className="flex w-full items-center justify-between rounded px-2 py-1.5 text-left text-[0.8125rem] font-medium text-ink hover:bg-canvas"
                >
                  {region.label}
                  <span aria-hidden className="text-faint">
                    {expanded ? '−' : '+'}
                  </span>
                </button>
              </h4>
              {expanded && (
                <div className="space-y-2 pb-2 pl-2">
                  {region.types.map((group) => (
                    <div key={group.type}>
                      <p className="mb-1 flex items-center gap-1.5 text-xs tracking-wide text-muted uppercase">
                        <span
                          aria-hidden
                          className="size-2 rounded-full border border-line-strong"
                          style={{ background: TISSUE[group.type] }}
                        />
                        {group.label}
                      </p>
                      <div className="flex flex-wrap gap-1.5">
                        {group.entries.map((structure) => {
                          const selected = selectedCodes.has(structure.code)
                          return (
                            <button
                              key={structure.code}
                              type="button"
                              aria-pressed={selected}
                              title={structure.latin || undefined}
                              onClick={() => onSelect(structure)}
                              className={cn(
                                'rounded-full border px-2.5 py-1 text-xs transition-colors',
                                selected
                                  ? 'border-accent bg-accent-soft font-medium text-accent-strong'
                                  : 'border-line bg-surface text-body hover:border-line-strong hover:bg-canvas',
                              )}
                            >
                              {structure.label}
                            </button>
                          )
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </section>
          )
        })}
      </div>
    </div>
  )
}
