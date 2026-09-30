import * as THREE from 'three'

import type { AnatomicalStructure, Side } from '@/api/types'
import { PARTS, type Part, type Shape, type Vec3 } from './model'
import { TISSUE } from './palette'

/** One pickable mesh and the site selecting it would record. */
export interface Target {
  readonly mesh: THREE.Mesh
  /**
   * The mesh's own material, and the tissue colour to put back on it.
   *
   * Every mesh gets its own instance. Sharing one per structure type would be cheaper, but
   * highlighting a selected knee would then repaint every joint in the body.
   */
  readonly material: THREE.MeshStandardMaterial
  readonly tissue: THREE.Color
  readonly code: string
  readonly side: Side
  readonly type: string
}

export interface BuiltModel {
  readonly root: THREE.Group
  /** One group per structure type, so a layer is shown or hidden in a single assignment. */
  readonly layers: Map<string, THREE.Group>
  readonly targets: readonly Target[]
  /** Centre of each (code, side), for placing a marker on a selected site. */
  readonly anchors: Map<string, THREE.Vector3>
  /** Ontology codes with no geometry. They stay selectable from the structure list. */
  readonly withoutGeometry: readonly string[]
}

export const siteKey = (code: string, side: Side | string) => `${code}|${side}`

const TO_RADIANS = Math.PI / 180

function geometryFor(shape: Shape): THREE.BufferGeometry {
  switch (shape.kind) {
    case 'ellipsoid': {
      const geometry = new THREE.SphereGeometry(1, 20, 14)
      geometry.scale(...shape.radii)
      return geometry
    }
    case 'capsule':
      return new THREE.CapsuleGeometry(shape.radius, shape.length, 4, 14)
    case 'box':
      return new THREE.BoxGeometry(...shape.size)
    case 'tube': {
      const curve = new THREE.CatmullRomCurve3(
        shape.path.map((point) => new THREE.Vector3(...point)),
      )
      return new THREE.TubeGeometry(curve, shape.path.length * 8, shape.radius, 8, false)
    }
  }
}

/** The part reflected across the midline, which is a numeric change and not a scale of -1. */
function reflected(part: Part): Part {
  const shape: Shape =
    part.shape.kind === 'tube'
      ? {
          ...part.shape,
          path: part.shape.path.map(([x, y, z]) => [-x, y, z] as Vec3),
        }
      : part.shape
  const [x, y, z] = part.at ?? [0, 0, 0]
  const [rx, ry, rz] = part.rotate ?? [0, 0, 0]
  return { ...part, shape, at: [-x, y, z], rotate: [rx, -ry, -rz] }
}

const tissueColour = (type: string) => new THREE.Color(TISSUE[type] ?? '#9aa7b2')

/**
 * Builds the model for one ontology.
 *
 * The ontology decides which side a mesh records: a mirrored part is a paired structure,
 * whose +X copy is the patient's left, and everything else takes the single side its
 * laterality allows. Geometry that names a structure the ontology does not have is
 * dropped, so an older bundle cannot record a code the server would reject.
 */
export function buildModel(structures: readonly AnatomicalStructure[]): BuiltModel {
  const byCode = new Map(structures.map((structure) => [structure.code, structure]))
  const root = new THREE.Group()
  const layers = new Map<string, THREE.Group>()
  const targets: Target[] = []
  const anchors = new Map<string, THREE.Vector3>()
  const withGeometry = new Set<string>()

  const layerFor = (type: string) => {
    const existing = layers.get(type)
    if (existing) return existing
    const group = new THREE.Group()
    group.name = type
    layers.set(type, group)
    root.add(group)
    return group
  }

  const place = (part: Part, side: Side) => {
    const structure = byCode.get(part.code)
    if (!structure) return
    withGeometry.add(part.code)

    const tissue = tissueColour(structure.structure_type)
    const material = new THREE.MeshStandardMaterial({
      color: tissue.clone(),
      // The body surface is matte, so the seams where its volumes meet stay quiet and the
      // figure reads as one shape. Everything under it keeps a little sheen.
      roughness: structure.structure_type === 'REGION' ? 0.95 : 0.6,
      metalness: 0,
      transparent: true,
      opacity: 1,
    })
    const mesh = new THREE.Mesh(geometryFor(part.shape), material)
    if (part.shape.kind !== 'tube' && part.at) mesh.position.set(...part.at)
    if (part.rotate) {
      const [x, y, z] = part.rotate
      mesh.rotation.set(x * TO_RADIANS, y * TO_RADIANS, z * TO_RADIANS)
    }
    mesh.userData = { code: part.code, side }
    layerFor(structure.structure_type).add(mesh)
    targets.push({ mesh, material, tissue, code: part.code, side, type: structure.structure_type })

    // A structure drawn as several meshes gets one anchor: the centre of the first, which
    // is close enough to hang a marker on. Taken through the mesh's own matrix rather than
    // localToWorld, which would read a world matrix nothing has computed yet.
    const key = siteKey(part.code, side)
    if (!anchors.has(key)) {
      mesh.updateMatrix()
      mesh.geometry.computeBoundingSphere()
      const centre = (mesh.geometry.boundingSphere?.center ?? new THREE.Vector3()).clone()
      anchors.set(key, centre.applyMatrix4(mesh.matrix))
    }
  }

  for (const part of PARTS) {
    const structure = byCode.get(part.code)
    if (!structure) continue
    if (part.mirror) {
      place(part, 'LEFT')
      place(reflected(part), 'RIGHT')
    } else {
      place(part, structure.sides[0] ?? 'MIDLINE')
    }
  }

  return {
    root,
    layers,
    targets,
    anchors,
    withoutGeometry: structures
      .map((structure) => structure.code)
      .filter((code) => !withGeometry.has(code)),
  }
}

export function disposeModel(model: BuiltModel): void {
  for (const target of model.targets) {
    target.mesh.geometry.dispose()
    target.material.dispose()
  }
  model.root.clear()
}
