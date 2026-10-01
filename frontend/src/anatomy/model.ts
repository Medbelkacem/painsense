/**
 * The anatomical model, as a parametric specification.
 *
 * Every shape here was authored for this project from standing-adult proportions, so the
 * module carries no third-party mesh and no licence obligation beyond the repository's
 * own. It is schematic on purpose: its job is to let a clinician point at a structure and
 * have the record name that structure, not to be an anatomical atlas. A deployment that
 * holds a licensed atlas (BodyParts3D and its derivatives are CC BY-SA) can swap one in
 * behind `build.ts`, which is the only module that reads these shapes.
 *
 * Conventions, which the whole module depends on:
 *
 * - Metres, and the figure is 1.72 m tall with the soles at y = 0.
 * - +X is the patient's LEFT. With the camera in front of the model that puts the
 *   patient's left on the viewer's right, which is how a clinician faces a patient.
 * - +Z is anterior.
 * - `mirror` emits the part twice. The +X copy is the patient's left side and the -X copy
 *   the right, with rotations about Y and Z negated so the pair is a true reflection.
 * - `code` is a structure code from the ontology the API serves, and it may appear on
 *   several parts: a rib cage is many arcs and one structure.
 */

export type Vec3 = readonly [number, number, number]

export type Shape =
  /** Axis-aligned radii, so one primitive covers spheres, discs and long ovals. */
  | { readonly kind: 'ellipsoid'; readonly radii: Vec3 }
  /** A cylinder with domed ends, along Y before rotation. */
  | { readonly kind: 'capsule'; readonly radius: number; readonly length: number }
  | { readonly kind: 'box'; readonly size: Vec3 }
  /** A smooth tube through the given points, for nerves, vessels and ribs. */
  | { readonly kind: 'tube'; readonly radius: number; readonly path: readonly Vec3[] }

export interface Part {
  readonly code: string
  readonly shape: Shape
  /** Centre of the shape. Ignored by `tube`, which is placed by its path. */
  readonly at?: Vec3
  /** Euler angles in degrees, applied XYZ. */
  readonly rotate?: Vec3
  readonly mirror?: boolean
}

const ellipsoid = (radii: Vec3): Shape => ({ kind: 'ellipsoid', radii })
const capsule = (radius: number, length: number): Shape => ({ kind: 'capsule', radius, length })
const box = (size: Vec3): Shape => ({ kind: 'box', size })
const tube = (radius: number, path: readonly Vec3[]): Shape => ({ kind: 'tube', radius, path })

/** Levels the rib cage and its cartilages are drawn at, top to bottom. */
const RIB_LEVELS = [1.36, 1.315, 1.27, 1.225, 1.18, 1.135]
const CARTILAGE_LEVELS = [1.32, 1.24, 1.16]
const COSTOSTERNAL_LEVELS = [1.335, 1.27, 1.205]

const rib = (y: number): Part => ({
  code: 'BONE_RIB',
  shape: tube(0.008, [
    [0.012, y, -0.048],
    [0.105, y - 0.006, -0.032],
    [0.136, y - 0.014, 0.022],
    [0.074, y - 0.024, 0.073],
  ]),
  mirror: true,
})

const cartilage = (y: number): Part => ({
  code: 'BONE_COSTAL_CARTILAGE',
  shape: tube(0.006, [
    [0.062, y, 0.078],
    [0.042, y - 0.006, 0.086],
    [0.021, y - 0.01, 0.089],
  ]),
  mirror: true,
})

/**
 * The head and the abdomen as volumes, and the patches that lie on their surfaces.
 *
 * A patch is the visible cap of a sphere sunk into the body, given as how wide it should
 * read and how far it should stand proud. Sinking a sphere rather than flattening one
 * means no patch has to be turned to face the surface, and every patch keeps the curvature
 * of the body underneath it.
 */
const HEAD_AT: Vec3 = [0, 1.612, -0.005]
const HEAD_RADII: Vec3 = [0.088, 0.108, 0.098]
const ABDOMEN_AT: Vec3 = [0, 1.1, 0]
const ABDOMEN_RADII: Vec3 = [0.115, 0.095, 0.088]
const THORAX_AT: Vec3 = [0.055, 1.275, 0]
const THORAX_RADII: Vec3 = [0.1, 0.14, 0.098]

const PROUD = 0.008

function capOn(
  centre: Vec3,
  radii: Vec3,
  direction: Vec3,
  width: number,
  proud = PROUD,
): { shape: Shape; at: Vec3 } {
  const length = Math.hypot(...direction) || 1
  const surface: Vec3 = [
    centre[0] + (radii[0] * direction[0]) / length,
    centre[1] + (radii[1] * direction[1]) / length,
    centre[2] + (radii[2] * direction[2]) / length,
  ]
  const outward: Vec3 = [
    surface[0] - centre[0],
    surface[1] - centre[1],
    surface[2] - centre[2],
  ]
  const span = Math.hypot(...outward) || 1
  const radius = (width * width + proud * proud) / (2 * proud)
  const depth = radius - proud
  return {
    shape: { kind: 'ellipsoid', radii: [radius, radius, radius] },
    at: [
      surface[0] - (outward[0] / span) * depth,
      surface[1] - (outward[1] / span) * depth,
      surface[2] - (outward[2] / span) * depth,
    ],
  }
}

const onHead = (direction: Vec3, width: number, proud?: number) =>
  capOn(HEAD_AT, HEAD_RADII, direction, width, proud)
const onAbdomen = (direction: Vec3, width: number) =>
  capOn(ABDOMEN_AT, ABDOMEN_RADII, direction, width)
const onThorax = (direction: Vec3, width: number) =>
  capOn(THORAX_AT, THORAX_RADII, direction, width)

/**
 * The body surface, which is also what a clinician picks when the exact structure is unknown.
 *
 * The trunk and the head are volumes; the named zones are patches on them. That way the
 * figure reads as one body from any angle, and a zone is a raised area of it rather than a
 * shape floating alongside.
 */
const SURFACE: readonly Part[] = [
  { code: 'REG_HEAD', shape: ellipsoid(HEAD_RADII), at: HEAD_AT },
  { code: 'REG_FOREHEAD', ...onHead([0, 0.8, 1], 0.042) },
  { code: 'REG_FACE', ...onHead([0, -0.3, 1], 0.038) },
  { code: 'REG_ORBIT', ...onHead([0.44, 0.2, 1], 0.014), mirror: true },
  { code: 'REG_TEMPLE', ...onHead([1, 0.28, 0.3], 0.026), mirror: true },
  { code: 'REG_EAR', ...onHead([1, -0.05, -0.15], 0.016, 0.014), mirror: true },
  { code: 'REG_JAW', ...onHead([0.6, -0.85, 0.5], 0.02), mirror: true },
  { code: 'REG_OCCIPUT', ...onHead([0, 0.3, -1], 0.04) },
  { code: 'REG_NECK_FRONT', shape: ellipsoid([0.044, 0.046, 0.03]), at: [0, 1.5, 0.02] },
  { code: 'REG_NECK_BACK', shape: ellipsoid([0.047, 0.048, 0.032]), at: [0, 1.503, -0.024] },

  // The two halves of the chest wall overlap at the midline and are the thorax.
  { code: 'REG_CHEST_WALL', shape: ellipsoid(THORAX_RADII), at: THORAX_AT, mirror: true },
  { code: 'REG_CHEST_CENTRAL', shape: ellipsoid([0.038, 0.105, 0.012]), at: [0, 1.285, 0.079] },
  { code: 'REG_BREAST', ...onThorax([0.1, -0.35, 1], 0.036), mirror: true },
  { code: 'REG_UPPER_BACK', shape: ellipsoid([0.1, 0.1, 0.012]), at: [0, 1.292, -0.079] },

  // The abdomen is a volume of its own, which is what "diffusely" means when a clinician
  // cannot put the pain in one quadrant. The nine zones are patches on its front.
  { code: 'REG_ABD_DIFFUSE', shape: ellipsoid(ABDOMEN_RADII), at: ABDOMEN_AT },
  { code: 'REG_EPIGASTRIUM', ...onAbdomen([0, 0.9, 1], 0.036) },
  { code: 'REG_ABD_LUQ', ...onAbdomen([0.85, 0.75, 1], 0.033) },
  { code: 'REG_ABD_RUQ', ...onAbdomen([-0.85, 0.75, 1], 0.033) },
  { code: 'REG_UMBILICAL', ...onAbdomen([0, 0, 1], 0.036) },
  { code: 'REG_ABD_LLQ', ...onAbdomen([0.85, -0.6, 1], 0.033) },
  { code: 'REG_ABD_RLQ', ...onAbdomen([-0.85, -0.6, 1], 0.033) },
  { code: 'REG_SUPRAPUBIC', ...onAbdomen([0, -0.95, 0.75], 0.038) },
  { code: 'REG_LOWER_BACK', shape: ellipsoid([0.082, 0.05, 0.012]), at: [0, 1.108, -0.08] },
  { code: 'REG_SACRAL', shape: ellipsoid([0.048, 0.034, 0.014]), at: [0, 1.006, -0.079] },

  { code: 'REG_PELVIS', shape: ellipsoid([0.122, 0.075, 0.09]), at: [0, 0.972, -0.004] },
  { code: 'REG_GENITAL', shape: ellipsoid([0.032, 0.028, 0.024]), at: [0, 0.906, 0.07] },
  { code: 'REG_BUTTOCK', shape: ellipsoid([0.058, 0.058, 0.044]), at: [0.06, 0.952, -0.074], mirror: true },

  { code: 'REG_SHOULDER', shape: ellipsoid([0.054, 0.05, 0.054]), at: [0.172, 1.398, 0], mirror: true },
  { code: 'REG_UPPER_ARM', shape: capsule(0.043, 0.19), at: [0.205, 1.288, 0], mirror: true },
  { code: 'REG_ELBOW', shape: ellipsoid([0.041, 0.038, 0.041]), at: [0.207, 1.175, 0], mirror: true },
  { code: 'REG_FOREARM', shape: capsule(0.036, 0.17), at: [0.212, 1.075, 0], mirror: true },
  { code: 'REG_WRIST', shape: ellipsoid([0.031, 0.028, 0.029]), at: [0.216, 0.975, 0], mirror: true },
  { code: 'REG_HAND', shape: ellipsoid([0.035, 0.048, 0.02]), at: [0.218, 0.92, 0], mirror: true },
  { code: 'REG_FINGERS', shape: ellipsoid([0.031, 0.03, 0.014]), at: [0.219, 0.86, 0], mirror: true },

  { code: 'REG_HIP', shape: ellipsoid([0.048, 0.054, 0.056]), at: [0.095, 0.912, 0.008], mirror: true },
  { code: 'REG_THIGH', shape: capsule(0.059, 0.26), at: [0.095, 0.72, 0], mirror: true },
  { code: 'REG_KNEE', shape: ellipsoid([0.052, 0.048, 0.052]), at: [0.097, 0.475, 0], mirror: true },
  { code: 'REG_LEG', shape: capsule(0.046, 0.25), at: [0.098, 0.315, 0], mirror: true },
  { code: 'REG_ANKLE', shape: ellipsoid([0.037, 0.034, 0.037]), at: [0.099, 0.095, 0], mirror: true },
  { code: 'REG_FOOT', shape: ellipsoid([0.037, 0.026, 0.092]), at: [0.1, 0.038, 0.045], mirror: true },
  { code: 'REG_TOES', shape: ellipsoid([0.035, 0.016, 0.026]), at: [0.1, 0.028, 0.14], mirror: true },
]

const BONES: readonly Part[] = [
  { code: 'BONE_CRANIUM', shape: ellipsoid([0.078, 0.092, 0.088]), at: [0, 1.635, -0.005] },
  {
    code: 'BONE_MANDIBLE',
    shape: tube(0.01, [
      [-0.052, 1.575, -0.012],
      [-0.046, 1.559, 0.03],
      [-0.02, 1.55, 0.052],
      [0.02, 1.55, 0.052],
      [0.046, 1.559, 0.03],
      [0.052, 1.575, -0.012],
    ]),
  },
  { code: 'BONE_MAXILLA', shape: box([0.03, 0.02, 0.03]), at: [0.022, 1.598, 0.062], mirror: true },
  { code: 'BONE_CERVICAL_SPINE', shape: capsule(0.017, 0.055), at: [0, 1.505, -0.015] },
  { code: 'BONE_THORACIC_SPINE', shape: capsule(0.019, 0.26), at: [0, 1.245, -0.055] },
  { code: 'BONE_LUMBAR_SPINE', shape: capsule(0.022, 0.13), at: [0, 1.085, -0.048] },
  { code: 'BONE_SACRUM', shape: box([0.075, 0.085, 0.035]), at: [0, 0.985, -0.05], rotate: [12, 0, 0] },
  { code: 'BONE_COCCYX', shape: capsule(0.01, 0.03), at: [0, 0.925, -0.048] },
  { code: 'BONE_STERNUM', shape: box([0.038, 0.15, 0.016]), at: [0, 1.285, 0.088] },
  ...RIB_LEVELS.map(rib),
  ...CARTILAGE_LEVELS.map(cartilage),
  {
    code: 'BONE_CLAVICLE',
    shape: tube(0.009, [
      [0.016, 1.415, 0.07],
      [0.075, 1.425, 0.055],
      [0.14, 1.42, 0.015],
    ]),
    mirror: true,
  },
  {
    code: 'BONE_SCAPULA',
    shape: box([0.085, 0.105, 0.014]),
    at: [0.095, 1.345, -0.068],
    rotate: [0, 0, -8],
    mirror: true,
  },
  {
    code: 'BONE_HIP_BONE',
    shape: ellipsoid([0.07, 0.07, 0.055]),
    at: [0.082, 0.965, -0.005],
    rotate: [0, 0, -12],
    mirror: true,
  },
  { code: 'BONE_HUMERUS', shape: capsule(0.019, 0.2), at: [0.203, 1.29, 0], mirror: true },
  { code: 'BONE_RADIUS', shape: capsule(0.012, 0.19), at: [0.196, 1.075, 0.01], mirror: true },
  { code: 'BONE_ULNA', shape: capsule(0.013, 0.2), at: [0.222, 1.072, -0.008], mirror: true },
  { code: 'BONE_CARPUS', shape: box([0.04, 0.022, 0.024]), at: [0.216, 0.968, 0], mirror: true },
  { code: 'BONE_METACARPUS', shape: box([0.046, 0.05, 0.016]), at: [0.218, 0.925, 0], mirror: true },
  { code: 'BONE_HAND_PHALANGES', shape: box([0.05, 0.052, 0.013]), at: [0.219, 0.865, 0], mirror: true },
  { code: 'BONE_FEMUR', shape: capsule(0.023, 0.3), at: [0.094, 0.715, 0], mirror: true },
  { code: 'BONE_PATELLA', shape: ellipsoid([0.024, 0.026, 0.012]), at: [0.097, 0.478, 0.045], mirror: true },
  { code: 'BONE_TIBIA', shape: capsule(0.017, 0.27), at: [0.088, 0.31, 0.003], mirror: true },
  { code: 'BONE_FIBULA', shape: capsule(0.009, 0.25), at: [0.118, 0.305, -0.004], mirror: true },
  { code: 'BONE_TARSUS', shape: box([0.055, 0.04, 0.055]), at: [0.1, 0.048, 0.005], mirror: true },
  { code: 'BONE_CALCANEUS', shape: box([0.04, 0.035, 0.055]), at: [0.1, 0.032, -0.032], mirror: true },
  { code: 'BONE_METATARSUS', shape: box([0.062, 0.02, 0.07]), at: [0.1, 0.03, 0.075], mirror: true },
  { code: 'BONE_FOOT_PHALANGES', shape: box([0.066, 0.016, 0.032]), at: [0.1, 0.026, 0.14], mirror: true },
]

const JOINTS: readonly Part[] = [
  { code: 'JOINT_TMJ', shape: ellipsoid([0.014, 0.014, 0.014]), at: [0.07, 1.592, 0.022], mirror: true },
  { code: 'JOINT_CERVICAL_FACET', shape: ellipsoid([0.011, 0.03, 0.011]), at: [0.021, 1.505, -0.025], mirror: true },
  { code: 'JOINT_CERVICAL_DISC', shape: ellipsoid([0.017, 0.006, 0.015]), at: [0, 1.492, -0.013] },
  { code: 'JOINT_THORACIC_FACET', shape: ellipsoid([0.011, 0.1, 0.011]), at: [0.023, 1.245, -0.063], mirror: true },
  { code: 'JOINT_LUMBAR_FACET', shape: ellipsoid([0.013, 0.055, 0.013]), at: [0.027, 1.085, -0.057], mirror: true },
  { code: 'JOINT_LUMBAR_DISC', shape: ellipsoid([0.023, 0.007, 0.02]), at: [0, 1.03, -0.046] },
  { code: 'JOINT_SACROILIAC', shape: ellipsoid([0.01, 0.035, 0.028]), at: [0.038, 1.0, -0.05], mirror: true },
  ...COSTOSTERNAL_LEVELS.map(
    (y): Part => ({
      code: 'JOINT_COSTOSTERNAL',
      shape: ellipsoid([0.01, 0.01, 0.01]),
      at: [0.024, y, 0.088],
      mirror: true,
    }),
  ),
  { code: 'JOINT_PUBIC_SYMPHYSIS', shape: ellipsoid([0.008, 0.018, 0.014]), at: [0, 0.93, 0.055] },
  { code: 'JOINT_SHOULDER', shape: ellipsoid([0.028, 0.028, 0.028]), at: [0.172, 1.398, 0], mirror: true },
  { code: 'JOINT_ACROMIOCLAVICULAR', shape: ellipsoid([0.012, 0.01, 0.012]), at: [0.145, 1.425, 0.01], mirror: true },
  { code: 'JOINT_ELBOW', shape: ellipsoid([0.025, 0.022, 0.025]), at: [0.206, 1.18, 0], mirror: true },
  { code: 'JOINT_WRIST', shape: ellipsoid([0.022, 0.012, 0.022]), at: [0.216, 0.982, 0], mirror: true },
  { code: 'JOINT_HAND_SMALL', shape: box([0.048, 0.012, 0.014]), at: [0.218, 0.893, 0], mirror: true },
  { code: 'JOINT_HIP', shape: ellipsoid([0.026, 0.026, 0.026]), at: [0.092, 0.9, 0], mirror: true },
  { code: 'JOINT_KNEE', shape: ellipsoid([0.032, 0.018, 0.032]), at: [0.096, 0.47, 0], mirror: true },
  { code: 'JOINT_ANKLE', shape: ellipsoid([0.026, 0.014, 0.026]), at: [0.099, 0.088, 0], mirror: true },
  { code: 'JOINT_FOOT_SMALL', shape: box([0.064, 0.012, 0.014]), at: [0.1, 0.026, 0.118], mirror: true },
]

const MUSCLES: readonly Part[] = [
  { code: 'MUS_TEMPORALIS', shape: ellipsoid([0.015, 0.03, 0.028]), at: [0.083, 1.648, 0.02], mirror: true },
  { code: 'MUS_MASSETER', shape: ellipsoid([0.014, 0.026, 0.018]), at: [0.072, 1.578, 0.03], mirror: true },
  {
    code: 'MUS_STERNOCLEIDOMASTOID',
    shape: capsule(0.013, 0.07),
    at: [0.04, 1.5, 0.03],
    rotate: [10, 0, 18],
    mirror: true,
  },
  { code: 'MUS_SCALENE', shape: capsule(0.01, 0.06), at: [0.038, 1.48, 0], rotate: [0, 0, 10], mirror: true },
  {
    code: 'MUS_LEVATOR_SCAPULAE',
    shape: capsule(0.01, 0.075),
    at: [0.045, 1.47, -0.04],
    rotate: [0, 0, 14],
    mirror: true,
  },
  {
    code: 'MUS_TRAPEZIUS',
    shape: box([0.115, 0.14, 0.03]),
    at: [0.07, 1.375, -0.06],
    rotate: [0, 0, -6],
    mirror: true,
  },
  { code: 'MUS_ERECTOR_SPINAE_THORACIC', shape: capsule(0.022, 0.21), at: [0.04, 1.25, -0.062], mirror: true },
  { code: 'MUS_ERECTOR_SPINAE_LUMBAR', shape: capsule(0.026, 0.115), at: [0.042, 1.085, -0.058], mirror: true },
  { code: 'MUS_QUADRATUS_LUMBORUM', shape: box([0.035, 0.1, 0.035]), at: [0.072, 1.085, -0.04], mirror: true },
  { code: 'MUS_LATISSIMUS_DORSI', shape: box([0.105, 0.18, 0.028]), at: [0.085, 1.23, -0.07], mirror: true },
  { code: 'MUS_PECTORALIS_MAJOR', shape: box([0.095, 0.1, 0.03]), at: [0.07, 1.295, 0.08], mirror: true },
  { code: 'MUS_INTERCOSTAL', shape: box([0.028, 0.14, 0.1]), at: [0.135, 1.265, 0.005], mirror: true },
  { code: 'MUS_SERRATUS_ANTERIOR', shape: box([0.02, 0.085, 0.075]), at: [0.138, 1.215, 0.03], mirror: true },
  { code: 'MUS_DIAPHRAGM', shape: ellipsoid([0.135, 0.03, 0.09]), at: [0, 1.185, 0.01] },
  { code: 'MUS_RECTUS_ABDOMINIS', shape: capsule(0.03, 0.12), at: [0.035, 1.105, 0.08], mirror: true },
  { code: 'MUS_ABDOMINAL_OBLIQUE', shape: box([0.045, 0.14, 0.085]), at: [0.115, 1.1, 0.03], mirror: true },
  { code: 'MUS_DELTOID', shape: ellipsoid([0.048, 0.058, 0.048]), at: [0.183, 1.385, 0], mirror: true },
  {
    code: 'MUS_SUPRASPINATUS',
    shape: capsule(0.013, 0.055),
    at: [0.12, 1.408, -0.04],
    rotate: [0, 0, 90],
    mirror: true,
  },
  { code: 'MUS_BICEPS_BRACHII', shape: capsule(0.026, 0.13), at: [0.198, 1.3, 0.026], mirror: true },
  { code: 'MUS_TRICEPS_BRACHII', shape: capsule(0.026, 0.14), at: [0.208, 1.295, -0.026], mirror: true },
  { code: 'MUS_FOREARM_FLEXORS', shape: capsule(0.024, 0.12), at: [0.207, 1.095, 0.022], mirror: true },
  { code: 'MUS_FOREARM_EXTENSORS', shape: capsule(0.023, 0.12), at: [0.215, 1.09, -0.024], mirror: true },
  { code: 'MUS_GLUTEUS_MAXIMUS', shape: ellipsoid([0.068, 0.062, 0.05]), at: [0.072, 0.94, -0.08], mirror: true },
  { code: 'MUS_GLUTEUS_MEDIUS', shape: ellipsoid([0.042, 0.045, 0.038]), at: [0.098, 0.985, -0.03], mirror: true },
  {
    code: 'MUS_PIRIFORMIS',
    shape: capsule(0.013, 0.055),
    at: [0.062, 0.955, -0.058],
    rotate: [0, 0, 72],
    mirror: true,
  },
  {
    code: 'MUS_ILIOPSOAS',
    shape: capsule(0.018, 0.13),
    at: [0.058, 1.01, 0.02],
    rotate: [0, 0, -8],
    mirror: true,
  },
  { code: 'MUS_QUADRICEPS', shape: capsule(0.05, 0.22), at: [0.092, 0.73, 0.03], mirror: true },
  { code: 'MUS_HAMSTRINGS', shape: capsule(0.042, 0.22), at: [0.096, 0.72, -0.035], mirror: true },
  {
    code: 'MUS_THIGH_ADDUCTORS',
    shape: capsule(0.03, 0.19),
    at: [0.048, 0.75, 0],
    rotate: [0, 0, 7],
    mirror: true,
  },
  { code: 'MUS_GASTROCNEMIUS', shape: capsule(0.04, 0.14), at: [0.098, 0.36, -0.022], mirror: true },
  { code: 'MUS_SOLEUS', shape: capsule(0.03, 0.14), at: [0.098, 0.29, -0.018], mirror: true },
  { code: 'MUS_TIBIALIS_ANTERIOR', shape: capsule(0.02, 0.19), at: [0.086, 0.31, 0.03], mirror: true },
]

const TENDONS: readonly Part[] = [
  { code: 'TEN_ROTATOR_CUFF', shape: ellipsoid([0.03, 0.02, 0.03]), at: [0.16, 1.418, -0.012], mirror: true },
  { code: 'TEN_LONG_HEAD_BICEPS', shape: capsule(0.007, 0.055), at: [0.18, 1.385, 0.036], mirror: true },
  {
    code: 'TEN_COMMON_EXTENSOR_ORIGIN',
    shape: ellipsoid([0.014, 0.014, 0.014]),
    at: [0.226, 1.188, -0.008],
    mirror: true,
  },
  {
    code: 'TEN_COMMON_FLEXOR_ORIGIN',
    shape: ellipsoid([0.014, 0.014, 0.014]),
    at: [0.186, 1.188, -0.008],
    mirror: true,
  },
  { code: 'TEN_WRIST_EXTENSOR', shape: capsule(0.008, 0.06), at: [0.218, 0.995, -0.02], mirror: true },
  { code: 'TEN_ILIOTIBIAL_TRACT', shape: box([0.012, 0.28, 0.045]), at: [0.14, 0.715, 0], mirror: true },
  { code: 'TEN_PATELLAR', shape: capsule(0.01, 0.04), at: [0.097, 0.443, 0.046], mirror: true },
  { code: 'TEN_ACL', shape: capsule(0.008, 0.03), at: [0.096, 0.47, 0.002], rotate: [28, 0, 0], mirror: true },
  { code: 'TEN_KNEE_MENISCUS', shape: ellipsoid([0.032, 0.006, 0.03]), at: [0.096, 0.463, 0], mirror: true },
  { code: 'TEN_ACHILLES', shape: capsule(0.011, 0.11), at: [0.099, 0.16, -0.038], mirror: true },
  {
    code: 'TEN_ANKLE_LATERAL_LIGAMENT',
    shape: capsule(0.006, 0.035),
    at: [0.126, 0.085, 0.01],
    rotate: [0, 0, 35],
    mirror: true,
  },
  { code: 'TEN_PLANTAR_FASCIA', shape: box([0.05, 0.008, 0.14]), at: [0.1, 0.012, 0.06], mirror: true },
]

const ORGANS: readonly Part[] = [
  { code: 'ORG_BRAIN', shape: ellipsoid([0.065, 0.072, 0.078]), at: [0, 1.645, -0.005] },
  { code: 'ORG_MENINGES', shape: ellipsoid([0.072, 0.08, 0.085]), at: [0, 1.643, -0.005] },
  { code: 'ORG_EYE', shape: ellipsoid([0.0115, 0.0115, 0.0115]), at: [0.033, 1.63, 0.082], mirror: true },
  { code: 'ORG_PARANASAL_SINUS', shape: ellipsoid([0.016, 0.015, 0.012]), at: [0.024, 1.612, 0.07], mirror: true },
  {
    code: 'ORG_TEETH',
    shape: tube(0.006, [
      [-0.044, 1.573, -0.006],
      [-0.038, 1.568, 0.03],
      [-0.016, 1.564, 0.048],
      [0.016, 1.564, 0.048],
      [0.038, 1.568, 0.03],
      [0.044, 1.573, -0.006],
    ]),
  },
  { code: 'ORG_THYROID', shape: ellipsoid([0.028, 0.018, 0.014]), at: [0, 1.47, 0.032] },
  { code: 'ORG_PHARYNX', shape: capsule(0.014, 0.045), at: [0, 1.505, 0.008] },
  { code: 'ORG_HEART', shape: ellipsoid([0.053, 0.06, 0.045]), at: [0.018, 1.265, 0.03], rotate: [0, 0, -18] },
  {
    code: 'ORG_PERICARDIUM',
    shape: ellipsoid([0.062, 0.068, 0.053]),
    at: [0.018, 1.263, 0.03],
    rotate: [0, 0, -18],
  },
  { code: 'ORG_LUNG', shape: ellipsoid([0.058, 0.105, 0.06]), at: [0.075, 1.29, 0.005], mirror: true },
  { code: 'ORG_PLEURA', shape: ellipsoid([0.066, 0.113, 0.068]), at: [0.075, 1.288, 0.005], mirror: true },
  { code: 'ORG_OESOPHAGUS', shape: capsule(0.01, 0.22), at: [0, 1.29, -0.02] },
  { code: 'ORG_STOMACH', shape: ellipsoid([0.055, 0.042, 0.035]), at: [0.035, 1.16, 0.022], rotate: [0, 0, 16] },
  {
    code: 'ORG_DUODENUM',
    shape: tube(0.01, [
      [0.008, 1.152, 0.01],
      [-0.024, 1.14, 0.02],
      [-0.03, 1.112, 0.012],
      [0.004, 1.106, 0.004],
    ]),
  },
  { code: 'ORG_LIVER', shape: ellipsoid([0.078, 0.048, 0.058]), at: [-0.045, 1.168, 0.02], rotate: [0, 0, 8] },
  { code: 'ORG_GALLBLADDER', shape: ellipsoid([0.014, 0.024, 0.014]), at: [-0.055, 1.14, 0.05] },
  {
    code: 'ORG_BILE_DUCT',
    shape: capsule(0.006, 0.045),
    at: [-0.03, 1.13, 0.035],
    rotate: [0, 0, -25],
  },
  { code: 'ORG_PANCREAS', shape: capsule(0.014, 0.085), at: [0.01, 1.135, -0.01], rotate: [0, 0, 80] },
  { code: 'ORG_SPLEEN', shape: ellipsoid([0.028, 0.036, 0.024]), at: [0.095, 1.175, -0.022] },
  // No mesh for the peritoneum: it lines the cavity rather than filling a place in it, and
  // a solid shape for it would sit in front of every abdominal organ and take their clicks.
  // It is selected from the structure list, which is where diffuse findings belong anyway.
  { code: 'ORG_SMALL_INTESTINE', shape: ellipsoid([0.08, 0.055, 0.048]), at: [0, 1.075, 0.03] },
  { code: 'ORG_APPENDIX', shape: capsule(0.007, 0.038), at: [-0.055, 1.01, 0.042], rotate: [0, 0, -30] },
  { code: 'ORG_CAECUM', shape: ellipsoid([0.028, 0.03, 0.025]), at: [-0.068, 1.035, 0.035] },
  { code: 'ORG_COLON', shape: capsule(0.017, 0.13), at: [-0.082, 1.095, 0.01] },
  { code: 'ORG_COLON', shape: capsule(0.017, 0.16), at: [0, 1.165, 0.038], rotate: [0, 0, 90] },
  { code: 'ORG_COLON', shape: capsule(0.016, 0.13), at: [0.082, 1.095, 0.01] },
  {
    code: 'ORG_SIGMOID_COLON',
    shape: tube(0.014, [
      [0.075, 1.03, 0.015],
      [0.05, 0.995, 0.03],
      [0.01, 0.985, 0.01],
    ]),
  },
  { code: 'ORG_RECTUM', shape: capsule(0.015, 0.055), at: [0, 0.95, -0.02] },
  { code: 'ORG_KIDNEY', shape: ellipsoid([0.02, 0.036, 0.026]), at: [0.07, 1.14, -0.05], mirror: true },
  {
    code: 'ORG_URETER',
    shape: tube(0.005, [
      [0.068, 1.105, -0.048],
      [0.058, 1.045, -0.02],
      [0.03, 0.985, 0.01],
    ]),
    mirror: true,
  },
  { code: 'ORG_BLADDER', shape: ellipsoid([0.036, 0.03, 0.03]), at: [0, 0.945, 0.04] },
  { code: 'ORG_UTERUS', shape: ellipsoid([0.026, 0.024, 0.02]), at: [0, 0.972, 0.018] },
  { code: 'ORG_OVARY', shape: ellipsoid([0.011, 0.009, 0.009]), at: [0.045, 0.975, 0.01], mirror: true },
  { code: 'ORG_PROSTATE', shape: ellipsoid([0.018, 0.014, 0.016]), at: [0, 0.918, 0.01] },
  { code: 'ORG_TESTIS', shape: ellipsoid([0.014, 0.018, 0.014]), at: [0.018, 0.88, 0.06], mirror: true },
]

const NERVES: readonly Part[] = [
  {
    code: 'NRV_TRIGEMINAL',
    shape: tube(0.004, [
      [0.03, 1.62, 0.03],
      [0.048, 1.61, 0.06],
      [0.06, 1.588, 0.062],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_OCCIPITAL',
    shape: tube(0.004, [
      [0.018, 1.53, -0.04],
      [0.03, 1.585, -0.075],
      [0.035, 1.65, -0.078],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_CERVICAL_ROOT',
    shape: tube(0.005, [
      [0.012, 1.52, -0.02],
      [0.045, 1.505, -0.01],
      [0.075, 1.48, 0],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_BRACHIAL_PLEXUS',
    shape: tube(0.006, [
      [0.03, 1.48, -0.01],
      [0.09, 1.45, 0.01],
      [0.15, 1.4, 0.01],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_MEDIAN',
    shape: tube(0.005, [
      [0.19, 1.18, 0.02],
      [0.205, 1.06, 0.025],
      [0.214, 0.975, 0.01],
      [0.216, 0.905, 0.005],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_ULNAR',
    shape: tube(0.005, [
      [0.198, 1.29, -0.02],
      [0.222, 1.185, -0.014],
      [0.226, 1.06, 0.005],
      [0.222, 0.965, 0.005],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_RADIAL',
    shape: tube(0.005, [
      [0.212, 1.28, -0.03],
      [0.226, 1.17, -0.015],
      [0.222, 1.06, -0.02],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_DIGITAL_HAND',
    shape: tube(0.003, [
      [0.2, 0.888, 0.004],
      [0.206, 0.855, 0.008],
      [0.21, 0.834, 0.008],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_INTERCOSTAL',
    shape: tube(0.004, [
      [0.014, 1.29, -0.048],
      [0.1, 1.282, -0.035],
      [0.13, 1.272, 0.02],
      [0.072, 1.26, 0.07],
    ]),
    mirror: true,
  },
  { code: 'NRV_SPINAL_CORD', shape: capsule(0.01, 0.4), at: [0, 1.29, -0.048] },
  {
    code: 'NRV_LUMBAR_ROOT',
    shape: tube(0.005, [
      [0.012, 1.07, -0.045],
      [0.04, 1.055, -0.03],
      [0.062, 1.03, -0.02],
    ]),
    mirror: true,
  },
  { code: 'NRV_CAUDA_EQUINA', shape: capsule(0.012, 0.1), at: [0, 1.02, -0.045] },
  {
    code: 'NRV_SCIATIC',
    shape: tube(0.007, [
      [0.045, 0.985, -0.05],
      [0.07, 0.93, -0.06],
      [0.085, 0.8, -0.045],
      [0.092, 0.64, -0.035],
      [0.095, 0.5, -0.025],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_FEMORAL',
    shape: tube(0.006, [
      [0.048, 1.0, 0.02],
      [0.07, 0.92, 0.04],
      [0.086, 0.8, 0.045],
      [0.09, 0.64, 0.04],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_COMMON_FIBULAR',
    shape: tube(0.005, [
      [0.1, 0.48, -0.025],
      [0.12, 0.43, -0.01],
      [0.118, 0.33, 0.005],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_TIBIAL',
    shape: tube(0.005, [
      [0.096, 0.47, -0.03],
      [0.098, 0.35, -0.028],
      [0.1, 0.18, -0.03],
      [0.102, 0.1, -0.02],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_PLANTAR',
    shape: tube(0.004, [
      [0.1, 0.06, -0.01],
      [0.1, 0.022, 0.06],
      [0.1, 0.02, 0.12],
    ]),
    mirror: true,
  },
  {
    code: 'NRV_PUDENDAL',
    shape: tube(0.004, [
      [0.035, 0.95, -0.04],
      [0.025, 0.915, -0.01],
      [0.014, 0.898, 0.03],
    ]),
    mirror: true,
  },
]

const VESSELS: readonly Part[] = [
  {
    code: 'VES_TEMPORAL_ARTERY',
    shape: tube(0.003, [
      [0.075, 1.575, 0.035],
      [0.088, 1.625, 0.03],
      [0.085, 1.672, 0.018],
    ]),
    mirror: true,
  },
  {
    code: 'VES_THORACIC_AORTA',
    shape: tube(0.01, [
      [0.006, 1.3, 0.006],
      [0.02, 1.335, -0.008],
      [0.01, 1.32, -0.03],
      [0, 1.24, -0.035],
      [0, 1.19, -0.035],
    ]),
  },
  {
    code: 'VES_CORONARY',
    shape: tube(0.004, [
      [0.014, 1.295, 0.05],
      [0.045, 1.275, 0.05],
      [0.052, 1.24, 0.038],
    ]),
  },
  {
    code: 'VES_PULMONARY_ARTERY',
    shape: tube(0.008, [
      [0.005, 1.305, 0.01],
      [0.04, 1.31, -0.005],
      [0.07, 1.3, -0.01],
    ]),
  },
  { code: 'VES_ABDOMINAL_AORTA', shape: capsule(0.009, 0.16), at: [0, 1.085, -0.03] },
  {
    code: 'VES_LEG_ARTERY',
    shape: tube(0.005, [
      [0.085, 0.9, 0.02],
      [0.092, 0.72, 0.01],
      [0.096, 0.48, -0.005],
      [0.1, 0.3, -0.01],
      [0.1, 0.12, 0],
    ]),
    mirror: true,
  },
  {
    code: 'VES_LEG_DEEP_VEIN',
    shape: tube(0.006, [
      [0.078, 0.9, -0.005],
      [0.088, 0.7, -0.015],
      [0.094, 0.47, -0.018],
      [0.098, 0.28, -0.02],
      [0.1, 0.11, -0.012],
    ]),
    mirror: true,
  },
]

export const PARTS: readonly Part[] = [
  ...SURFACE,
  ...MUSCLES,
  ...TENDONS,
  ...BONES,
  ...JOINTS,
  ...ORGANS,
  ...NERVES,
  ...VESSELS,
]

/** What the camera has to fit: the figure's height, its width across the arms, and its centre. */
export const FIGURE_HEIGHT = 1.72
export const FIGURE_WIDTH = 0.52
export const FIGURE_CENTRE: Vec3 = [0, 0.88, 0]
