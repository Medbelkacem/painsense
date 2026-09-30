import { Suspense, lazy, useMemo, useRef, useState } from 'react'

import { useAnatomy, useLocations } from '@/api/queries'
import type { AnatomicalSite, AnatomicalStructure, Sex, Side } from '@/api/types'
import { Notice, QueryState } from '@/components/ui/feedback'
import type { AnatomyViewerHandle } from './AnatomyViewer'
import { PainSitePanel, type SiteActions } from './PainSitePanel'
import { StructureBrowser } from './StructureBrowser'
import {
  defaultSide,
  isSelected,
  key,
  offeredFor,
  setMainSite,
  setSide,
  toggle,
  update,
} from './sites'

/**
 * Loaded on demand because it pulls in the 3D library.
 *
 * The rest of the step is usable while it arrives: the structure list and the flat diagram
 * record the same site, so a clinician on a slow connection is never left waiting for a
 * renderer before they can say where the pain is.
 */
const AnatomyViewer = lazy(() =>
  import('./AnatomyViewer').then((module) => ({ default: module.AnatomyViewer })),
)

/**
 * The anatomical pain-mapping module: the model, the structure list and the per-site pain
 * assessment, wired to one list of selected sites.
 *
 * The three surfaces are interchangeable on purpose. Clicking a structure on the model,
 * choosing it from the list and editing it in the panel all move the same state, so a
 * clinician working with a mouse, a keyboard or a device without WebGL records the same
 * thing.
 */
export function AnatomyMapper({
  sites,
  onChange,
  sex,
}: {
  sites: AnatomicalSite[]
  onChange: (sites: AnatomicalSite[]) => void
  /** Sex-specific organs are offered only where they apply. */
  sex?: Sex | null
}) {
  const anatomy = useAnatomy()
  const locations = useLocations()
  const viewer = useRef<AnatomyViewerHandle | null>(null)
  const [focused, setFocused] = useState<string | null>(null)

  const ontology = anatomy.data
  const offered = useMemo(
    () => offeredFor(ontology?.structures ?? [], sex),
    [ontology?.structures, sex],
  )
  const byCode = useMemo(
    () => new Map(offered.map((structure) => [structure.code, structure])),
    [offered],
  )
  const selectedCodes = useMemo(
    () => new Set(sites.map((site) => site.structure_code)),
    [sites],
  )

  const focus = (code: string, side: Side) => {
    setFocused(key({ structure_code: code, side }))
    viewer.current?.focus(code, side)
  }

  /** A click on the model. The mesh knows its own side, so nothing has to be guessed. */
  const pick = (picked: { code: string; side: Side }) => {
    const next = toggle(sites, picked.code, picked.side)
    onChange(next)
    setFocused(next.length > sites.length ? key({ structure_code: picked.code, side: picked.side }) : null)
  }

  /**
   * A choice from the list, where there is no mesh to say which side.
   *
   * A structure already recorded is removed on whichever sides it was recorded on, which
   * is what a second click on the same entry should mean. A new one starts on the side its
   * laterality gives first, and the panel offers the change.
   */
  const choose = (structure: AnatomicalStructure) => {
    if (isSelected(sites, structure.code)) {
      onChange(sites.filter((site) => site.structure_code !== structure.code))
      setFocused(null)
      return
    }
    const side = defaultSide(structure)
    onChange(toggle(sites, structure.code, side))
    focus(structure.code, side)
  }

  const actions: SiteActions = {
    setSide: (code, from, to) => {
      onChange(setSide(sites, code, from, to))
      setFocused(key({ structure_code: code, side: to }))
    },
    setIntensity: (code, side, intensity) => onChange(update(sites, code, side, { intensity })),
    setNote: (code, side, note) => onChange(update(sites, code, side, { note: note || null })),
    setMainSite: (code, side) => onChange(setMainSite(sites, code, side)),
    remove: (code, side) => {
      onChange(toggle(sites, code, side))
      setFocused(null)
    },
    locate: focus,
  }

  return (
    <QueryState isPending={anatomy.isPending || locations.isPending} error={anatomy.error}>
      {ontology && (
        <div className="space-y-4">
          <Notice tone="info" title="What this model is for">
            {ontology.notice}
          </Notice>

          <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,24rem)]">
            <div className="space-y-4">
              <Suspense
                fallback={
                  <div
                    role="status"
                    className="flex aspect-[3/4] w-full items-center justify-center rounded-md border border-line bg-canvas text-sm text-muted"
                  >
                    Loading the model
                  </div>
                }
              >
                <AnatomyViewer
                  structures={offered}
                  layers={ontology.structure_types.map((entry) => ({
                    code: entry.code,
                    label: entry.label,
                  }))}
                  sites={sites}
                  onPick={pick}
                  handleRef={viewer}
                />
              </Suspense>
              <StructureBrowser
                ontology={ontology}
                offered={offered}
                selectedCodes={selectedCodes}
                onSelect={choose}
              />
            </div>

            <div>
              <h3 className="mb-2 text-sm font-semibold text-ink">
                Pain at each site{sites.length > 0 && ` (${sites.length})`}
              </h3>
              <PainSitePanel
                sites={sites}
                structures={byCode}
                locations={locations.data ?? []}
                focused={focused}
                actions={actions}
              />
            </div>
          </div>
        </div>
      )}
    </QueryState>
  )
}
