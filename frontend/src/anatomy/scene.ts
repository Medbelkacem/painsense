import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

import type { AnatomicalStructure, Side } from '../api/types';
import { buildModel, disposeModel, siteKey, type BuiltModel, type Target } from './build';
import { FIGURE_CENTRE, FIGURE_HEIGHT, FIGURE_WIDTH } from './model';
import { HIGHLIGHT } from './palette';

export type ViewName = 'front' | 'back' | 'left' | 'right';

export interface PickedSite {
  code: string;
  side: Side;
}

/**
 * Camera positions for the four named views, as offsets from the point being looked at.
 *
 * +X is the patient's left, so the "left" view puts the camera on +X and the patient's
 * left side faces us. The views are named by the patient's side and not the viewer's,
 * which is how a clinician talks about a body.
 */
const VIEWS: Record<ViewName, [number, number, number]> = {
  front: [0, 0, 1],
  back: [0, 0, -1],
  left: [1, 0, 0],
  right: [-1, 0, 0],
};

const FIELD_OF_VIEW = 34;
const MIN_DISTANCE = 0.3;
const MAX_DISTANCE = FIGURE_HEIGHT * 4;
/** A little room around the figure, so it is not pressed against the edges of the canvas. */
const MARGIN = 1.1;
/** Farther than this and a pointer press counts as a drag rather than a pick. */
const CLICK_SLOP = 6;
/**
 * What is left of the skin once something under it is shown. Low, because the skin is
 * several overlapping volumes and each one blends again over the same organ.
 */
const SHELL_OPACITY = 0.1;

export interface SceneOptions {
  canvas: HTMLCanvasElement;
  structures: readonly AnatomicalStructure[];
  onPick: (site: PickedSite) => void;
  onHover: (site: PickedSite | null) => void;
}

/**
 * The 3D viewer.
 *
 * An imperative object rather than a component tree: the scene lives for as long as the
 * canvas does, and React drives it through the few setters below. It is told which layers
 * to show and which structure is picked, and reports what was pointed at.
 *
 * "Outside" and "inside" are not modes it knows about. Showing any layer under the skin
 * turns the skin into a shell the camera sees through, and that shell stops taking clicks
 * so the organs under it can.
 */
export class AnatomyScene {
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera: THREE.PerspectiveCamera;
  private readonly controls: OrbitControls;
  private readonly raycaster = new THREE.Raycaster();
  private readonly pointer = new THREE.Vector2();
  private readonly model: BuiltModel;
  private readonly target = new THREE.Vector3(...FIGURE_CENTRE);
  private readonly highlight = new THREE.Color(HIGHLIGHT);

  private readonly onPick: (site: PickedSite) => void;
  private readonly onHover: (site: PickedSite | null) => void;

  private visible = new Set<string>();
  private selected: PickedSite | null = null;
  private hovered: PickedSite | null = null;
  private marker: THREE.Mesh | null = null;
  private pressedAt: { x: number; y: number } | null = null;
  private frame = 0;
  private disposed = false;

  constructor(options: SceneOptions) {
    this.onPick = options.onPick;
    this.onHover = options.onHover;

    this.renderer = new THREE.WebGLRenderer({
      canvas: options.canvas,
      antialias: true,
      alpha: true,
    });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    this.camera = new THREE.PerspectiveCamera(FIELD_OF_VIEW, 1, 0.05, 20);
    this.camera.position.set(0, this.target.y, this.fitDistance());

    this.controls = new OrbitControls(this.camera, options.canvas);
    this.controls.target.copy(this.target);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.09;
    this.controls.enablePan = false;
    this.controls.minDistance = MIN_DISTANCE;
    this.controls.maxDistance = MAX_DISTANCE;
    this.controls.zoomSpeed = 0.8;
    this.controls.rotateSpeed = 0.85;

    this.scene.add(new THREE.HemisphereLight(0xffffff, 0x3b4a63, 1.4));
    const front = new THREE.DirectionalLight(0xffffff, 1.2);
    front.position.set(0.6, 1.4, 1.2);
    const back = new THREE.DirectionalLight(0xbcd0ff, 0.6);
    back.position.set(-0.8, 0.9, -1.1);
    this.scene.add(front, back);

    this.model = buildModel(options.structures);
    this.scene.add(this.model.root);

    const canvas = options.canvas;
    canvas.addEventListener('pointerdown', this.handlePointerDown);
    canvas.addEventListener('pointerup', this.handlePointerUp);
    canvas.addEventListener('pointermove', this.handlePointerMove);
    canvas.addEventListener('pointerleave', this.handlePointerLeave);

    this.loop();
  }

  setLayers(types: Iterable<string>): void {
    this.visible = new Set(types);
    for (const [type, group] of this.model.layers) {
      group.visible = this.visible.has(type);
    }
    this.applyMaterials();
    this.drawMarker();
  }

  setSelected(site: PickedSite | null): void {
    this.selected = site;
    this.applyMaterials();
    this.drawMarker();
  }

  setView(view: ViewName): void {
    const [x, y, z] = VIEWS[view];
    const distance = this.camera.position.distanceTo(this.controls.target);
    this.camera.position.set(
      this.target.x + x * distance,
      this.target.y + y * distance,
      this.target.z + z * distance,
    );
    this.controls.target.copy(this.target);
    this.controls.update();
  }

  /** A factor above 1 moves the camera away and below 1 brings it closer. */
  zoomBy(factor: number): void {
    const direction = this.camera.position.clone().sub(this.controls.target);
    const distance = THREE.MathUtils.clamp(direction.length() * factor, MIN_DISTANCE, MAX_DISTANCE);
    this.camera.position.copy(this.controls.target).add(direction.setLength(distance));
    this.controls.update();
  }

  resetView(): void {
    this.target.set(...FIGURE_CENTRE);
    this.controls.target.copy(this.target);
    this.camera.position.set(0, this.target.y, this.fitDistance());
    this.controls.update();
  }

  /**
   * How far back the camera has to be for the whole figure to be in frame.
   *
   * Computed from the field of view and the shape of the canvas rather than fixed, because
   * a wide short panel needs a different distance from a tall narrow one and nobody should
   * have to zoom out to find the feet.
   */
  private fitDistance(): number {
    const vertical = 2 * Math.tan((this.camera.fov * Math.PI) / 360);
    const horizontal = vertical * Math.max(this.camera.aspect, 0.2);
    return THREE.MathUtils.clamp(
      Math.max((FIGURE_HEIGHT * MARGIN) / vertical, (FIGURE_WIDTH * MARGIN) / horizontal),
      MIN_DISTANCE,
      MAX_DISTANCE,
    );
  }

  /**
   * Turns the model to show a structure, for when it was chosen from the list and not
   * clicked.
   *
   * It turns rather than flies in: someone who has just named a structure wants to see
   * where on the body it is, and diving to within a few centimetres of it takes away the
   * only thing that answers that. The view it settled on is returned so the toolbar can
   * say which one it is.
   */
  focus(code: string, side: Side): ViewName | null {
    const anchor = this.model.anchors.get(siteKey(code, side));
    if (!anchor) return null;
    const offset = anchor.clone().sub(new THREE.Vector3(...FIGURE_CENTRE));
    // Sideways only when the structure is clearly off the midline, so a deep midline organ
    // is shown from the front or the back rather than edge on.
    const view: ViewName =
      Math.abs(offset.x) > Math.abs(offset.z) + 0.05
        ? offset.x > 0
          ? 'left'
          : 'right'
        : offset.z >= 0
          ? 'front'
          : 'back';
    this.resetView();
    this.setView(view);
    return view;
  }

  resize(width: number, height: number): void {
    if (width === 0 || height === 0) return;
    const first = this.camera.aspect === 1;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    // The first measurement is the one that decides the framing. Later ones leave the
    // camera where the user put it.
    if (first) this.resetView();
  }

  dispose(): void {
    this.disposed = true;
    cancelAnimationFrame(this.frame);
    const canvas = this.renderer.domElement;
    canvas.removeEventListener('pointerdown', this.handlePointerDown);
    canvas.removeEventListener('pointerup', this.handlePointerUp);
    canvas.removeEventListener('pointermove', this.handlePointerMove);
    canvas.removeEventListener('pointerleave', this.handlePointerLeave);
    this.controls.dispose();
    this.clearMarker();
    disposeModel(this.model);
    this.renderer.dispose();
  }

  // --- rendering -------------------------------------------------------------------

  private loop = (): void => {
    if (this.disposed) return;
    this.frame = requestAnimationFrame(this.loop);
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

  /** Whether anything under the skin is on show. */
  private seeThrough(): boolean {
    for (const type of this.visible) if (type !== 'REGION') return true;
    return false;
  }

  /**
   * Paints the model for the current layers, pick and hover.
   *
   * Inner meshes stay opaque and the skin alone goes transparent, so the organs are drawn
   * first and the shell is blended over them: the body reads as glass with its contents
   * in place, not as organs pasted on top of a ghost.
   */
  private applyMaterials(): void {
    const shell = this.seeThrough();
    const selectedKey = this.selected ? siteKey(this.selected.code, this.selected.side) : null;
    const hoveredKey = this.hovered ? siteKey(this.hovered.code, this.hovered.side) : null;

    for (const target of this.model.targets) {
      const key = siteKey(target.code, target.side);
      const { material } = target;
      const skin = target.type === 'REGION';

      if (key === selectedKey) {
        material.color.copy(this.highlight);
        material.emissive.copy(this.highlight);
        material.emissiveIntensity = key === hoveredKey ? 0.8 : 0.5;
        material.opacity = 1;
      } else {
        material.color.copy(target.tissue);
        material.emissive.copy(target.tissue);
        material.emissiveIntensity = key === hoveredKey ? 0.4 : 0;
        material.opacity = skin && shell ? SHELL_OPACITY : 1;
      }
      // Whether a material is opaque is compiled into its shader, so flipping the flag
      // without asking for a rebuild leaves the skin solid whatever its opacity says.
      const transparent = material.opacity < 1;
      if (material.transparent !== transparent) {
        material.transparent = transparent;
        material.needsUpdate = true;
      }
      material.depthWrite = !transparent;
    }
  }

  /**
   * A dot on the picked structure, drawn through whatever is in front of it. Only when its
   * own layer is hidden: a structure chosen from the list while its layer is off would
   * otherwise be nowhere on screen.
   */
  private drawMarker(): void {
    this.clearMarker();
    if (!this.selected) return;
    const target = this.model.targets.find(
      (item) => item.code === this.selected?.code && item.side === this.selected.side,
    );
    if (!target || this.visible.has(target.type)) return;
    const anchor = this.model.anchors.get(siteKey(target.code, target.side));
    if (!anchor) return;
    this.marker = new THREE.Mesh(
      new THREE.SphereGeometry(0.018, 16, 12),
      new THREE.MeshBasicMaterial({
        color: this.highlight,
        depthTest: false,
        transparent: true,
        opacity: 0.9,
      }),
    );
    this.marker.position.copy(anchor);
    this.marker.renderOrder = 2;
    this.scene.add(this.marker);
  }

  private clearMarker(): void {
    if (!this.marker) return;
    this.marker.geometry.dispose();
    (this.marker.material as THREE.Material).dispose();
    this.scene.remove(this.marker);
    this.marker = null;
  }

  // --- pointer ---------------------------------------------------------------------

  /** The skin stops taking the pointer as soon as the camera can see through it. */
  private pickable(): Target[] {
    const shell = this.seeThrough();
    return this.model.targets.filter(
      (target) => this.visible.has(target.type) && !(shell && target.type === 'REGION'),
    );
  }

  private hit(event: PointerEvent): PickedSite | null {
    const bounds = this.renderer.domElement.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return null;
    this.pointer.set(
      ((event.clientX - bounds.left) / bounds.width) * 2 - 1,
      -((event.clientY - bounds.top) / bounds.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const meshes = this.pickable().map((target) => target.mesh);
    const [first] = this.raycaster.intersectObjects(meshes, false);
    if (!first) return null;
    const { code, side } = first.object.userData as PickedSite;
    return { code, side };
  }

  private handlePointerDown = (event: PointerEvent): void => {
    this.pressedAt = { x: event.clientX, y: event.clientY };
  };

  private handlePointerUp = (event: PointerEvent): void => {
    const pressed = this.pressedAt;
    this.pressedAt = null;
    if (!pressed) return;
    const moved = Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y);
    if (moved > CLICK_SLOP) return;
    const site = this.hit(event);
    if (site) this.onPick(site);
  };

  private handlePointerMove = (event: PointerEvent): void => {
    if (this.pressedAt) return;
    const site = this.hit(event);
    const same = site?.code === this.hovered?.code && site?.side === this.hovered?.side;
    if (same) return;
    this.hovered = site;
    this.onHover(site);
    this.applyMaterials();
  };

  private handlePointerLeave = (): void => {
    this.pressedAt = null;
    if (!this.hovered) return;
    this.hovered = null;
    this.onHover(null);
    this.applyMaterials();
  };
}

/** Whether this browser can give us a WebGL context at all. */
export function webglAvailable(): boolean {
  try {
    const canvas = document.createElement('canvas');
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'));
  } catch {
    return false;
  }
}
