import type { AnatomicalSite, AnatomicalStructure, Side } from '@/api/types'

/**
 * The selection model for the 3D module, as pure functions.
 *
 * Kept out of the viewer so that adding a site, changing its side and moving the main site
 * can be reasoned about and tested without a WebGL context.
 */

export const key = (site: { structure_code: string; side: Side }) =>
  `${site.structure_code}|${site.side}`

export const find = (sites: readonly AnatomicalSite[], code: string, side: Side) =>
  sites.find((site) => site.structure_code === code && site.side === side)

/** Whether a structure is recorded at all, on any side. */
export const isSelected = (sites: readonly AnatomicalSite[], code: string) =>
  sites.some((site) => site.structure_code === code)

/**
 * Adds the site if it is not there and removes it if it is.
 *
 * The first site recorded becomes the main one, and removing the main site passes that to
 * whatever is left, so a record with sites always has exactly one main site.
 */
export function toggle(
  sites: readonly AnatomicalSite[],
  code: string,
  side: Side,
): AnatomicalSite[] {
  const existing = find(sites, code, side)
  if (existing) {
    return withOneMainSite(sites.filter((site) => site !== existing))
  }
  return withOneMainSite([
    ...sites,
    { structure_code: code, side, intensity: null, is_primary: false, note: null },
  ])
}

/**
 * Moves a site to another side.
 *
 * Recording the same structure twice is how both sides are expressed, so moving onto a
 * side that is already recorded merges the two rather than creating a duplicate the server
 * would reject.
 */
export function setSide(
  sites: readonly AnatomicalSite[],
  code: string,
  from: Side,
  to: Side,
): AnatomicalSite[] {
  if (from === to) return [...sites]
  const moving = find(sites, code, from)
  if (!moving) return [...sites]
  const target = find(sites, code, to)
  const next = sites
    .filter((site) => site !== target)
    .map((site) =>
      site === moving
        ? {
            ...site,
            side: to,
            intensity: site.intensity ?? target?.intensity ?? null,
            is_primary: site.is_primary || Boolean(target?.is_primary),
          }
        : site,
    )
  return withOneMainSite(next)
}

export function update(
  sites: readonly AnatomicalSite[],
  code: string,
  side: Side,
  patch: Partial<AnatomicalSite>,
): AnatomicalSite[] {
  return sites.map((site) =>
    site.structure_code === code && site.side === side ? { ...site, ...patch } : site,
  )
}

export function setMainSite(
  sites: readonly AnatomicalSite[],
  code: string,
  side: Side,
): AnatomicalSite[] {
  return sites.map((site) => ({
    ...site,
    is_primary: site.structure_code === code && site.side === side,
  }))
}

function withOneMainSite(sites: readonly AnatomicalSite[]): AnatomicalSite[] {
  if (!sites.length) return []
  const main = sites.findIndex((site) => site.is_primary)
  const chosen = main === -1 ? 0 : main
  return sites.map((site, index) => ({ ...site, is_primary: index === chosen }))
}

/**
 * The side to record when a structure is chosen from the list rather than clicked.
 *
 * A structure with only one possible side takes it. A paired one has to be told, so it
 * starts on the left and the panel offers the change; a clinician who clicked the model
 * instead never sees this, because the mesh knows which side it is.
 */
export const defaultSide = (structure: AnatomicalStructure): Side => structure.sides[0] ?? 'MIDLINE'

/**
 * The pain locations a set of sites records, mirroring what the server stores.
 *
 * Shown in the interface so a clinician can see that pointing at a structure also records
 * a site in the taxonomy the rest of the assessment uses.
 */
export function recordedLocations(
  sites: readonly AnatomicalSite[],
  structures: Map<string, AnatomicalStructure>,
): { code: string; side: Side }[] {
  const recorded = new Map<string, Side>()
  for (const site of sites) {
    const structure = structures.get(site.structure_code)
    if (!structure) continue
    for (const [code, side] of projected(structure, site.side)) {
      const previous = recorded.get(code)
      recorded.set(code, previous ? combineSides(previous, side) : side)
    }
  }
  return [...recorded].map(([code, side]) => ({ code, side }))
}

function projected(structure: AnatomicalStructure, side: Side): [string, Side][] {
  if (side === 'BILATERAL' && (structure.location_left || structure.location_right)) {
    return [
      [structure.location_left || structure.location_code, 'LEFT'],
      [structure.location_right || structure.location_code, 'RIGHT'],
    ]
  }
  if (side === 'LEFT' && structure.location_left) return [[structure.location_left, side]]
  if (side === 'RIGHT' && structure.location_right) return [[structure.location_right, side]]
  return [[structure.location_code, side]]
}

export function combineSides(first: Side, second: Side): Side {
  if (first === second) return first
  if (first === 'MIDLINE' || first === 'NOT_APPLICABLE') return second
  if (second === 'MIDLINE' || second === 'NOT_APPLICABLE') return first
  return 'BILATERAL'
}

/** Matches a structure against what was typed, on label, Latin name or synonym. */
export function matches(structure: AnatomicalStructure, query: string): boolean {
  const needle = query.trim().toLowerCase()
  if (!needle) return true
  return [structure.label, structure.latin, ...structure.synonyms].some((text) =>
    text.toLowerCase().includes(needle),
  )
}

/** Structures a patient of this sex can have. */
export function offeredFor(
  structures: readonly AnatomicalStructure[],
  sex: string | null | undefined,
): AnatomicalStructure[] {
  if (sex !== 'F' && sex !== 'M') return [...structures]
  return structures.filter((structure) => structure.sex === null || structure.sex === sex)
}
