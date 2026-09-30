import { describe, expect, it } from 'vitest'

import { buildModel, siteKey } from './build'
import { KNEE, LIVER, STRUCTURES, UTERUS } from './fixtures'
import { PARTS } from './model'

describe('building the model', () => {
  it('draws a paired structure twice, once on each side of the midline', () => {
    const model = buildModel([KNEE])
    const knees = model.targets.filter((target) => target.code === 'JOINT_KNEE')
    expect(knees.map((target) => target.side).sort()).toEqual(['LEFT', 'RIGHT'])

    const left = model.anchors.get(siteKey('JOINT_KNEE', 'LEFT'))
    const right = model.anchors.get(siteKey('JOINT_KNEE', 'RIGHT'))
    // +X is the patient's left, so the pair is a reflection and nothing else moved.
    expect(left?.x).toBeGreaterThan(0)
    expect(right?.x).toBeCloseTo(-(left?.x ?? 0), 6)
    expect(right?.y).toBeCloseTo(left?.y ?? 0, 6)
    expect(right?.z).toBeCloseTo(left?.z ?? 0, 6)
  })

  it('gives an unpaired structure the one side its laterality allows', () => {
    const model = buildModel([LIVER])
    const sides = new Set(model.targets.map((target) => target.side))
    expect([...sides]).toEqual(['RIGHT'])
  })

  it('groups the meshes into one layer per structure type', () => {
    const model = buildModel(STRUCTURES)
    expect([...model.layers.keys()].sort()).toEqual(['JOINT', 'NERVE', 'ORGAN', 'REGION'])
    for (const [type, group] of model.layers) {
      expect(group.children.length).toBeGreaterThan(0)
      expect(group.name).toBe(type)
    }
  })

  it('draws nothing for a structure the ontology does not offer', () => {
    // The uterus is in this ontology but the caller filtered it out for a male patient.
    const model = buildModel(STRUCTURES.filter((structure) => structure !== UTERUS))
    expect(model.targets.some((target) => target.code === 'ORG_UTERUS')).toBe(false)
  })

  it('reports the structures it has no geometry for', () => {
    const model = buildModel(STRUCTURES)
    // Every fixture is drawn, so nothing should be reported; the real check is that a code
    // with no part is listed rather than silently missing.
    expect(model.withoutGeometry).toEqual([])

    const withExtra = buildModel([
      ...STRUCTURES,
      { ...KNEE, code: 'REG_GENERALIZED', label: 'Generalised' },
    ])
    expect(withExtra.withoutGeometry).toEqual(['REG_GENERALIZED'])
  })

  it('gives every mesh its own material so one highlight cannot repaint another', () => {
    const model = buildModel(STRUCTURES)
    const materials = new Set(model.targets.map((target) => target.material))
    expect(materials.size).toBe(model.targets.length)
  })
})

describe('the model specification', () => {
  it('names a structure on every part', () => {
    expect(PARTS.every((part) => /^[A-Z]+_[A-Z_]+$/.test(part.code))).toBe(true)
  })

  it('mirrors only parts that sit off the midline', () => {
    for (const part of PARTS) {
      if (!part.mirror) continue
      const offset =
        part.shape.kind === 'tube'
          ? Math.max(...part.shape.path.map(([x]) => Math.abs(x)))
          : Math.abs(part.at?.[0] ?? 0)
      expect(offset, part.code).toBeGreaterThan(0)
    }
  })

  it('keeps every part inside the figure', () => {
    for (const part of PARTS) {
      const points = part.shape.kind === 'tube' ? part.shape.path : [part.at ?? [0, 0, 0]]
      for (const [x, y, z] of points) {
        expect(Math.abs(x), part.code).toBeLessThan(0.4)
        expect(y, part.code).toBeGreaterThanOrEqual(0)
        expect(y, part.code).toBeLessThan(1.72)
        expect(Math.abs(z), part.code).toBeLessThan(0.3)
      }
    }
  })
})
