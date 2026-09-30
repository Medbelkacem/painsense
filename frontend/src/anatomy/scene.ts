import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

import type { AnatomicalSite, AnatomicalStructure, Side } from '@/api/types'
import { buildModel, disposeModel, siteKey, type BuiltModel, type Target } from './build'
import { FIGURE_CENTRE, FIGURE_HEIGHT, FIGURE_WIDTH } from './model'
import { siteColour } from './palette'

export type ViewName = 'front' | 'back' | 'left' | 'right'

export interface PickedSite {
  code: string
  side: Side
}

/**
 * Camera positions for the four named views, as offsets from the point being looked at.
 *
 * +X is the patient's left, so the "left" view puts the camera on +X and the patient's
 * left side faces us. Labelling the views by the patient's side and not the viewer's is
 * the same convention the flat diagram uses.
 */
const VIEWS: Record<ViewName, [number, number, number]> = {
  front: [0, 0, 1],
  back: [0, 0, -1],
  left: [1, 0, 0],
  right: [-1, 0, 0],
}

const FIELD_OF_VIEW = 34
const MIN_DISTANCE = 0.3
const MAX_DISTANCE = FIGURE_HEIGHT * 4
/** A little room around the figure, so it is not pressed against the edges of the canvas. */
const MARGIN = 1.2
/** Farther than this and a pointer press counts as a drag rather than a selection. */
const CLICK_SLOP = 6

export interface SceneOptions {
  canvas: HTMLCanvasElement
  structures: readonly AnatomicalStructure[]
  onPick: (site: PickedSite) => void
  onHover: (site: PickedSite | null) => void
}

/**
 * The 3D viewer.
 *
 * An imperative object rather than a component tree: the scene lives for as long as the
 * canvas does, and React drives it through the few setters below. Nothing in here reads
 * the assessment; it is told which sites are selected and reports what was pointed at.
 */
export class AnatomyScene {
  private readonly renderer: THREE.WebGLRenderer
  private readonly scene = new THREE.Scene()
  private readonly camera: THREE.PerspectiveCamera
  private readonly controls: OrbitControls
  private readonly raycaster = new THREE.Raycaster()
  private readonly pointer = new THREE.Vector2()
  private readonly model: BuiltModel
  private readonly markers = new THREE.Group()
  private readonly target = new THREE.Vector3(...FIGURE_CENTRE)

  private readonly onPick: (site: PickedSite) => void
  private readonly onHover: (site: PickedSite | null) => void

  private visible = new Set<string>()
  private selected: readonly AnatomicalSite[] = []
  private hovered: PickedSite | null = null
  private pressedAt: { x: number; y: number } | null = null
  private frame = 0
  private disposed = false

  constructor(options: SceneOptions) {
    this.onPick = options.onPick
    this.onHover = options.onHover

    this.renderer = new THREE.WebGLRenderer({
      canvas: options.canvas,
      antialias: true,
      alpha: true,
    })
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))

    this.camera = new THREE.PerspectiveCamera(FIELD_OF_VIEW, 1, 0.05, 20)
    this.camera.position.set(0, this.target.y, this.fitDistance())

    this.controls = new OrbitControls(this.camera, options.canvas)
    this.controls.target.copy(this.target)
    this.controls.enableDamping = true
    this.controls.dampingFactor = 0.09
    this.controls.enablePan = false
    this.controls.minDistance = MIN_DISTANCE
    this.controls.maxDistance = MAX_DISTANCE
    this.controls.zoomSpeed = 0.8
    this.controls.rotateSpeed = 0.85

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x9aa7b2, 1.5))
    const front = new THREE.DirectionalLight(0xffffff, 1.1)
    front.position.set(0.6, 1.4, 1.2)
    const back = new THREE.DirectionalLight(0xffffff, 0.55)
    back.position.set(-0.8, 0.9, -1.1)
    this.scene.add(front, back)

    this.model = buildModel(options.structures)
    this.scene.add(this.model.root)
    this.markers.renderOrder = 2
    this.scene.add(this.markers)

    const canvas = options.canvas
    canvas.addEventListener('pointerdown', this.handlePointerDown)
    canvas.addEventListener('pointerup', this.handlePointerUp)
    canvas.addEventListener('pointermove', this.handlePointerMove)
    canvas.addEventListener('pointerleave', this.handlePointerLeave)

    this.loop()
  }

  /** Codes the model has no geometry for, which the caller offers in the list instead. */
  get withoutGeometry(): readonly string[] {
    return this.model.withoutGeometry
  }

  setLayers(types: Iterable<string>): void {
    this.visible = new Set(types)
    for (const [type, group] of this.model.layers) {
      group.visible = this.visible.has(type)
    }
    this.applyMaterials()
  }

  setSelection(sites: readonly AnatomicalSite[]): void {
    this.selected = sites
    this.drawMarkers()
    this.applyMaterials()
  }

  setView(view: ViewName): void {
    const [x, y, z] = VIEWS[view]
    const distance = this.camera.position.distanceTo(this.controls.target)
    this.camera.position.set(
      this.target.x + x * distance,
      this.target.y + y * distance,
      this.target.z + z * distance,
    )
    this.controls.target.copy(this.target)
    this.controls.update()
  }

  /** A factor above 1 moves the camera away and below 1 brings it closer. */
  zoomBy(factor: number): void {
    const direction = this.camera.position.clone().sub(this.controls.target)
    const distance = THREE.MathUtils.clamp(direction.length() * factor, MIN_DISTANCE, MAX_DISTANCE)
    this.camera.position.copy(this.controls.target).add(direction.setLength(distance))
    this.controls.update()
  }

  resetView(): void {
    this.target.set(...FIGURE_CENTRE)
    this.controls.target.copy(this.target)
    this.camera.position.set(0, this.target.y, this.fitDistance())
    this.controls.update()
  }

  /**
   * How far back the camera has to be for the whole figure to be in frame.
   *
   * Computed from the field of view and the shape of the canvas rather than fixed, because
   * a wide short panel needs a different distance from a tall narrow one and a clinician
   * should not have to zoom out to find the feet.
   */
  private fitDistance(): number {
    const vertical = 2 * Math.tan((this.camera.fov * Math.PI) / 360)
    const horizontal = vertical * Math.max(this.camera.aspect, 0.2)
    return THREE.MathUtils.clamp(
      Math.max((FIGURE_HEIGHT * MARGIN) / vertical, (FIGURE_WIDTH * MARGIN) / horizontal),
      MIN_DISTANCE,
      MAX_DISTANCE,
    )
  }

  /** Brings a structure into view, for when it was chosen from the list and not clicked. */
  focus(code: string, side: Side): boolean {
    const anchor = this.model.anchors.get(siteKey(code, side))
    if (!anchor) return false
    const direction = this.camera.position.clone().sub(this.controls.target)
    this.target.copy(anchor)
    this.controls.target.copy(anchor)
    this.camera.position.copy(anchor).add(direction.setLength(Math.max(MIN_DISTANCE, 0.55)))
    this.controls.update()
    return true
  }

  resize(width: number, height: number): void {
    if (width === 0 || height === 0) return
    const first = this.camera.aspect === 1
    this.renderer.setSize(width, height, false)
    this.camera.aspect = width / height
    this.camera.updateProjectionMatrix()
    // The first measurement is the one that decides the framing. Later ones leave the
    // camera where the clinician put it.
    if (first) this.resetView()
  }

  dispose(): void {
    this.disposed = true
    cancelAnimationFrame(this.frame)
    const canvas = this.renderer.domElement
    canvas.removeEventListener('pointerdown', this.handlePointerDown)
    canvas.removeEventListener('pointerup', this.handlePointerUp)
    canvas.removeEventListener('pointermove', this.handlePointerMove)
    canvas.removeEventListener('pointerleave', this.handlePointerLeave)
    this.controls.dispose()
    this.clearMarkers()
    disposeModel(this.model)
    this.renderer.dispose()
  }

  // --- rendering -------------------------------------------------------------------

  private loop = (): void => {
    if (this.disposed) return
    this.frame = requestAnimationFrame(this.loop)
    this.controls.update()
    this.renderer.render(this.scene, this.camera)
  }

  /**
   * Paints the model for the current selection and hover.
   *
   * The surface turns translucent as soon as a deeper layer is shown, otherwise the
   * clinician would be looking at a solid body with the organs hidden inside it.
   */
  private applyMaterials(): void {
    const colours = new Map(
      this.selected.map((site) => [
        siteKey(site.structure_code, site.side),
        new THREE.Color(siteColour(site.intensity)),
      ]),
    )
    const deeperShown = [...this.visible].some((type) => type !== 'REGION')
    const hoveredKey = this.hovered ? siteKey(this.hovered.code, this.hovered.side) : null

    for (const target of this.model.targets) {
      const key = siteKey(target.code, target.side)
      const { material } = target
      const surface = target.type === 'REGION'
      const highlight = colours.get(key)

      if (highlight) {
        material.color.copy(highlight)
        material.emissive.copy(highlight)
        material.emissiveIntensity = key === hoveredKey ? 0.9 : 0.5
        material.opacity = 1
      } else {
        material.color.copy(target.tissue)
        material.emissive.copy(target.tissue)
        material.emissiveIntensity = key === hoveredKey ? 0.45 : 0
        material.opacity = surface && deeperShown ? 0.22 : 1
      }
      material.depthWrite = material.opacity > 0.9
      target.mesh.renderOrder = surface ? 0 : 1
    }
  }

  private drawMarkers(): void {
    this.clearMarkers()
    for (const site of this.selected) {
      const anchor = this.model.anchors.get(siteKey(site.structure_code, site.side))
      if (!anchor) continue
      const marker = new THREE.Mesh(
        new THREE.SphereGeometry(site.is_primary ? 0.026 : 0.019, 16, 12),
        new THREE.MeshBasicMaterial({
          color: new THREE.Color(siteColour(site.intensity)),
          // Drawn through whatever is in front of it: a selected site has to stay visible
          // when its layer is hidden or buried under the body surface.
          depthTest: false,
          transparent: true,
          opacity: 0.92,
        }),
      )
      marker.position.copy(anchor)
      this.markers.add(marker)
    }
  }

  private clearMarkers(): void {
    for (const child of this.markers.children as THREE.Mesh[]) {
      child.geometry.dispose()
      ;(child.material as THREE.Material).dispose()
    }
    this.markers.clear()
  }

  // --- pointer ---------------------------------------------------------------------

  private pickable(): Target[] {
    return this.model.targets.filter((target) => this.visible.has(target.type))
  }

  private hit(event: PointerEvent): PickedSite | null {
    const bounds = this.renderer.domElement.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return null
    this.pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    )
    this.raycaster.setFromCamera(this.pointer, this.camera)
    const meshes = this.pickable().map((target) => target.mesh)
    const [first] = this.raycaster.intersectObjects(meshes, false)
    if (!first) return null
    const { code, side } = first.object.userData as PickedSite
    return { code, side }
  }

  private handlePointerDown = (event: PointerEvent): void => {
    this.pressedAt = { x: event.clientX, y: event.clientY }
  }

  private handlePointerUp = (event: PointerEvent): void => {
    const pressed = this.pressedAt
    this.pressedAt = null
    if (!pressed) return
    const moved = Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y)
    if (moved > CLICK_SLOP) return
    const site = this.hit(event)
    if (site) this.onPick(site)
  }

  private handlePointerMove = (event: PointerEvent): void => {
    if (this.pressedAt) return
    const site = this.hit(event)
    const same = site?.code === this.hovered?.code && site?.side === this.hovered?.side
    if (same) return
    this.hovered = site
    this.onHover(site)
    this.applyMaterials()
  }

  private handlePointerLeave = (): void => {
    this.pressedAt = null
    if (!this.hovered) return
    this.hovered = null
    this.onHover(null)
    this.applyMaterials()
  }
}

/** Whether this browser can give us a WebGL context at all. */
export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas')
    return Boolean(
      canvas.getContext('webgl2') ??
        canvas.getContext('webgl') ??
        canvas.getContext('experimental-webgl'),
    )
  } catch {
    return false
  }
}
