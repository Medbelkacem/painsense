import { describe, expect, it } from 'vitest'

import type { AnatomicalSite } from '@/api/types'
import { KIDNEY, KNEE, LIVER, SCIATIC, STRUCTURES, UTERUS } from './fixtures'
import {
  combineSides,
  defaultSide,
  matches,
  offeredFor,
  recordedLocations,
  setMainSite,
  setSide,
  toggle,
  update,
} from './sites'

const site = (code: string, side: AnatomicalSite['side'], extra: Partial<AnatomicalSite> = {}) => ({
  structure_code: code,
  side,
  intensity: null,
  is_primary: false,
  note: null,
  ...extra,
})

describe('the selection model', () => {
  it('records a structure and makes the first one the main site', () => {
    const first = toggle([], 'JOINT_KNEE', 'LEFT')
    expect(first).toEqual([site('JOINT_KNEE', 'LEFT', { is_primary: true })])

    const second = toggle(first, 'NRV_SCIATIC', 'LEFT')
    expect(second.map((entry) => entry.is_primary)).toEqual([true, false])
  })

  it('keeps the two sides of one structure as two sites', () => {
    const both = toggle(toggle([], 'JOINT_KNEE', 'LEFT'), 'JOINT_KNEE', 'RIGHT')
    expect(both).toHaveLength(2)
    expect(both.map((entry) => entry.side)).toEqual(['LEFT', 'RIGHT'])
  })

  it('passes the main site on when the main site is removed', () => {
    const both = toggle(toggle([], 'JOINT_KNEE', 'LEFT'), 'NRV_SCIATIC', 'LEFT')
    const left = toggle(both, 'JOINT_KNEE', 'LEFT')
    expect(left).toHaveLength(1)
    expect(left[0]).toMatchObject({ structure_code: 'NRV_SCIATIC', is_primary: true })
  })

  it('merges rather than duplicates when a site moves onto a side already recorded', () => {
    const both = [
      site('JOINT_KNEE', 'LEFT', { intensity: 7, is_primary: true }),
      site('JOINT_KNEE', 'RIGHT', { intensity: 3 }),
    ]
    const merged = setSide(both, 'JOINT_KNEE', 'RIGHT', 'LEFT')
    expect(merged).toHaveLength(1)
    expect(merged[0]).toMatchObject({ side: 'LEFT', intensity: 3, is_primary: true })
  })

  it('leaves the list alone when a side is set to what it already is', () => {
    const one = toggle([], 'JOINT_KNEE', 'LEFT')
    expect(setSide(one, 'JOINT_KNEE', 'LEFT', 'LEFT')).toEqual(one)
  })

  it('changes only the site that was edited', () => {
    const both = toggle(toggle([], 'JOINT_KNEE', 'LEFT'), 'JOINT_KNEE', 'RIGHT')
    const edited = update(both, 'JOINT_KNEE', 'RIGHT', { intensity: 8 })
    expect(edited.map((entry) => entry.intensity)).toEqual([null, 8])
  })

  it('moves the main site without creating a second one', () => {
    const both = toggle(toggle([], 'JOINT_KNEE', 'LEFT'), 'NRV_SCIATIC', 'LEFT')
    const moved = setMainSite(both, 'NRV_SCIATIC', 'LEFT')
    expect(moved.filter((entry) => entry.is_primary)).toHaveLength(1)
    expect(moved[1].is_primary).toBe(true)
  })

  it('starts a structure on a side its laterality allows', () => {
    expect(defaultSide(KNEE)).toBe('LEFT')
    expect(defaultSide(LIVER)).toBe('RIGHT')
    expect(defaultSide(UTERUS)).toBe('MIDLINE')
  })
})

describe('the pain locations a selection records', () => {
  const structures = new Map(STRUCTURES.map((entry) => [entry.code, entry]))

  it('projects a structure onto the pain-location taxonomy', () => {
    expect(recordedLocations([site('JOINT_KNEE', 'LEFT')], structures)).toEqual([
      { code: 'KNEE', side: 'LEFT' },
    ])
    expect(recordedLocations([site('ORG_LIVER', 'RIGHT')], structures)).toEqual([
      { code: 'ABD_RUQ', side: 'RIGHT' },
    ])
  })

  it('splits a structure recorded on both sides when the taxonomy names them apart', () => {
    expect(recordedLocations([site('ORG_KIDNEY', 'BILATERAL')], structures)).toEqual([
      { code: 'ABD_LUQ', side: 'LEFT' },
      { code: 'ABD_RUQ', side: 'RIGHT' },
    ])
  })

  it('combines the sides of two sites that land on one location', () => {
    const both = [site('JOINT_KNEE', 'LEFT'), site('JOINT_KNEE', 'RIGHT')]
    expect(recordedLocations(both, structures)).toEqual([{ code: 'KNEE', side: 'BILATERAL' }])
  })

  it('ignores a structure the ontology does not have', () => {
    expect(recordedLocations([site('NOT_A_STRUCTURE', 'LEFT')], structures)).toEqual([])
  })

  it('combines sides the way the server does', () => {
    expect(combineSides('LEFT', 'RIGHT')).toBe('BILATERAL')
    expect(combineSides('MIDLINE', 'LEFT')).toBe('LEFT')
    expect(combineSides('LEFT', 'LEFT')).toBe('LEFT')
  })
})

describe('searching and offering structures', () => {
  it('matches a label, a Latin name or a clinical synonym', () => {
    expect(matches(SCIATIC, 'sciatic nerve')).toBe(true)
    expect(matches(SCIATIC, 'ischiadicus')).toBe(true)
    expect(matches(SCIATIC, 'sciatica')).toBe(true)
    expect(matches(SCIATIC, 'femoral')).toBe(false)
    expect(matches(SCIATIC, '  ')).toBe(true)
  })

  it('offers a sex-specific organ only where it applies', () => {
    expect(offeredFor(STRUCTURES, 'F')).toContain(UTERUS)
    expect(offeredFor(STRUCTURES, 'M')).not.toContain(UTERUS)
    // Undisclosed or other: the model offers everything rather than deciding for the patient.
    expect(offeredFor(STRUCTURES, 'UNDISCLOSED')).toContain(UTERUS)
    expect(offeredFor(STRUCTURES, null)).toContain(KIDNEY)
  })
})
