/**
 * The demonstration cohort.
 *
 * Every screen in the product is labelled "Synthetic data" because this is exactly
 * that: a deterministic, seeded cohort with no relation to a real person. It is
 * generated rather than checked in as a fixture so the shape of it (how many patients,
 * how long the history runs) stays adjustable, and seeded so a screenshot taken today
 * matches the one taken last week.
 *
 * When the API is reachable the clinical pages prefer it; this is what they fall back
 * to, and what the offline demo runs on.
 */

/** mulberry32 — small, fast, and stable across engines. */
function rng(seed: number): () => number {
  let state = seed >>> 0;
  return () => {
    state = (state + 0x6d2b79f5) >>> 0;
    let t = Math.imul(state ^ (state >>> 15), 1 | state);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function pick<T>(random: () => number, items: readonly T[]): T {
  return items[Math.floor(random() * items.length)];
}

/** Weighted draw — the cohort should look like a clinic, not a uniform histogram. */
function weighted<T>(random: () => number, pairs: readonly (readonly [T, number])[]): T {
  const total = pairs.reduce((sum, [, weight]) => sum + weight, 0);
  let roll = random() * total;
  for (const [value, weight] of pairs) {
    roll -= weight;
    if (roll <= 0) return value;
  }
  return pairs[pairs.length - 1][0];
}

export const PAIN_SITES = [
  'Chest', 'Lower back', 'Abdomen', 'Head', 'Knee', 'Shoulder',
  'Neck', 'Hip', 'Foot', 'Pelvis', 'Upper back', 'Hand',
] as const;

export const PAIN_TYPES = [
  'Nociceptive · visceral',
  'Nociceptive · somatic',
  'Neuropathic',
  'Postoperative',
  'Chronic · mixed',
  'Cancer-related',
  'Inflammatory',
] as const;

export const PAIN_QUALITIES = [
  'Pressure', 'Burning', 'Sharp', 'Tightness', 'Throbbing', 'Aching', 'Shooting', 'Cramping',
] as const;

export const SYMPTOMS = [
  'Dyspnoea', 'Palpitations', 'Sweating', 'Nausea', 'Dizziness', 'Fever', 'Numbness', 'Weakness',
] as const;

export const UNITS = [
  'Emergency department', 'Internal medicine', 'Surgery · post-op', 'Oncology', 'Rheumatology', 'Neurology',
] as const;

export type Priority = 'High' | 'Moderate' | 'Low';
export type PatientStatus = 'Active' | 'Needs review' | 'Discharged';

export interface Patient {
  code: string;
  age: number;
  sex: 'M' | 'F';
  site: string;
  painType: string;
  /** Patient-reported numeric rating, 0–10. */
  nrs: number;
  /** Model output on the same scale, with its own interval. */
  estimate: number;
  spread: number;
  priority: Priority;
  status: PatientStatus;
  unit: string;
  clinician: string;
  lastAt: Date;
  admittedDaysAgo: number;
  assessments: number;
  vitals: { hr: number; rr: number; sys: number; dia: number; spo2: number; temp: number };
}

export interface Assessment {
  id: string;
  patient: string;
  site: string;
  painType: string;
  nrs: number;
  estimate: number;
  at: Date;
  clinician: string;
  status: 'Signed' | 'Needs review' | 'In progress' | 'Open';
  modality: 'Self-report' | 'Observed' | 'Signal-assisted';
}

const CLINICIANS = ['Dr. Ahmed B.', 'Dr. Leila M.', 'Dr. Samir K.', 'Dr. Nadia R.', 'Dr. Yacine T.'];

const NOW = new Date('2026-09-30T14:32:00');

export function now(): Date {
  return NOW;
}

/**
 * NRS is drawn from a clinic-shaped curve (most people report mild-to-moderate), and
 * the model estimate is that value plus a small error whose size grows with the score —
 * which is also what the AI analysis screen is reporting on.
 */
function drawScore(random: () => number): { nrs: number; estimate: number; spread: number } {
  const nrs = weighted(random, [
    [0, 7], [1, 11], [2, 13], [3, 16], [4, 14], [5, 12],
    [6, 10], [7, 8], [8, 6], [9, 4], [10, 2],
  ] as const);
  const spread = 0.4 + (nrs / 10) * 0.9;
  const estimate = Math.max(0, Math.min(10, nrs + (random() - 0.48) * spread * 2.6));
  return { nrs, estimate: Number(estimate.toFixed(1)), spread: Number(spread.toFixed(1)) };
}

export const patients: Patient[] = (() => {
  const random = rng(20260930);
  return Array.from({ length: 128 }, (_, index) => {
    const { nrs, estimate, spread } = drawScore(random);
    const priority: Priority = nrs >= 7 ? 'High' : nrs >= 4 ? 'Moderate' : 'Low';
    const minutesAgo = Math.floor(random() ** 2 * 20160); // squared: most seen recently
    return {
      code: `PT-2026-${String(10 + index * 3).padStart(5, '0')}`,
      age: 19 + Math.floor(random() * 62),
      sex: random() < 0.52 ? 'F' : 'M',
      site: pick(random, PAIN_SITES),
      painType: pick(random, PAIN_TYPES),
      nrs,
      estimate,
      spread,
      priority,
      status:
        minutesAgo > 20160 * 0.8 ? 'Discharged' : Math.abs(estimate - nrs) > 1.8 ? 'Needs review' : 'Active',
      unit: pick(random, UNITS),
      clinician: pick(random, CLINICIANS),
      lastAt: new Date(NOW.getTime() - minutesAgo * 60_000),
      admittedDaysAgo: 1 + Math.floor(random() * 90),
      assessments: 1 + Math.floor(random() * 14),
      vitals: {
        hr: 58 + Math.floor(random() * 46),
        rr: 12 + Math.floor(random() * 10),
        sys: 104 + Math.floor(random() * 42),
        dia: 62 + Math.floor(random() * 26),
        spo2: 93 + Math.floor(random() * 7),
        temp: Number((36.2 + random() * 1.6).toFixed(1)),
      },
    } satisfies Patient;
  }).sort((a, b) => b.lastAt.getTime() - a.lastAt.getTime());
})();

export const assessments: Assessment[] = (() => {
  const random = rng(77003);
  return Array.from({ length: 137 }, (_, index) => {
    const patient = patients[Math.floor(random() * patients.length)];
    const { nrs, estimate } = drawScore(random);
    const minutesAgo = Math.floor(random() * 43200);
    const drift = Math.abs(estimate - nrs);
    return {
      id: `A-2026-${String(4480 - index).padStart(4, '0')}`,
      patient: patient.code,
      site: patient.site,
      painType: patient.painType,
      nrs,
      estimate,
      at: new Date(NOW.getTime() - minutesAgo * 60_000),
      clinician: pick(random, CLINICIANS),
      status: drift > 2 ? 'Needs review' : minutesAgo < 120 ? 'In progress' : random() < 0.72 ? 'Signed' : 'Open',
      modality: weighted(random, [
        ['Self-report', 6], ['Observed', 3], ['Signal-assisted', 2],
      ] as const),
    } satisfies Assessment;
  }).sort((a, b) => b.at.getTime() - a.at.getTime());
})();

/** Eleven buckets, one per NRS value — what the dashboard histogram draws. */
export function nrsDistribution(source: readonly { nrs: number }[] = assessments): number[] {
  const counts = Array.from({ length: 11 }, () => 0);
  for (const item of source) counts[item.nrs] += 1;
  return counts;
}

export function countBy<T extends string>(
  source: readonly Record<string, unknown>[],
  key: string,
): { label: T; value: number }[] {
  const tally = new Map<string, number>();
  for (const row of source) {
    const value = String(row[key]);
    tally.set(value, (tally.get(value) ?? 0) + 1);
  }
  return [...tally.entries()]
    .map(([label, value]) => ({ label: label as T, value }))
    .sort((a, b) => b.value - a.value);
}

/** A patient's visit history, used by the profile chart and timeline. */
export function historyFor(patient: Patient): {
  label: string;
  reported: number;
  estimate: number;
  spread: number;
  at: Date;
  note: string;
}[] {
  const random = rng(patient.code.split('-').join('').length * 991 + patient.age);
  const notes = [
    'Initial consultation · aching, morning stiffness',
    'Follow-up · sleep disturbance reported',
    'Follow-up · radiation to left leg',
    'After physiotherapy · improved mobility',
    'Medication review · dose adjusted',
    'Post-procedure check',
    'Routine review',
    'Flare reported overnight',
  ];
  const visits = Math.max(4, Math.min(12, patient.assessments));
  let score = Math.max(0, Math.min(10, patient.nrs + Math.round((random() - 0.5) * 5)));

  return Array.from({ length: visits }, (_, index) => {
    const at = new Date(NOW.getTime() - (visits - 1 - index) * 3 * 86_400_000);
    if (index === visits - 1) score = patient.nrs;
    else score = Math.max(0, Math.min(10, score + Math.round((random() - 0.45) * 3)));
    const spread = 0.4 + (score / 10) * 0.9;
    return {
      label: at.toLocaleDateString('en-GB', { day: '2-digit', month: 'short' }),
      reported: score,
      estimate: Number(Math.max(0, Math.min(10, score + (random() - 0.5) * spread * 2)).toFixed(1)),
      spread: Number(spread.toFixed(1)),
      at,
      note: notes[index % notes.length],
    };
  });
}

/* -------------------------------------------------------------------------- */
/* Model, dataset and governance fixtures                                      */
/* -------------------------------------------------------------------------- */

export const modelVersions = [
  { version: 'v2.1', trainedOn: '12 Sep 2026', records: 10_000, mae: 0.62, rmse: 0.84, r2: 0.91, coverage: 0.87, state: 'Serving' },
  { version: 'v2.0', trainedOn: '02 Aug 2026', records: 8_400, mae: 0.71, rmse: 0.95, r2: 0.88, coverage: 0.84, state: 'Archived' },
  { version: 'v1.8', trainedOn: '19 Jun 2026', records: 7_100, mae: 0.83, rmse: 1.08, r2: 0.84, coverage: 0.81, state: 'Archived' },
  { version: 'v1.5', trainedOn: '04 May 2026', records: 5_600, mae: 0.97, rmse: 1.24, r2: 0.78, coverage: 0.76, state: 'Archived' },
] as const;

export const featureImportance = [
  { label: 'Self-reported NRS', value: 0.31 },
  { label: 'Pain quality', value: 0.18 },
  { label: 'Site · region', value: 0.13 },
  { label: 'Heart rate', value: 0.09 },
  { label: 'Respiratory rate', value: 0.08 },
  { label: 'Analgesic class', value: 0.07 },
  { label: 'Duration', value: 0.06 },
  { label: 'Age band', value: 0.05 },
  { label: 'Associated symptoms', value: 0.03 },
] as const;

export const datasetSplit = { total: 10_000, train: 7_000, validation: 1_500, test: 1_500 } as const;

export const documents = [
  { name: 'ECG_1452.pdf', kind: 'Cardiology', size: '1.2 MB', patient: 'PT-2026-00388', at: '30 Sep · 14:12', verified: true },
  { name: 'MRI_lumbar_spine.pdf', kind: 'Imaging', size: '8.4 MB', patient: 'PT-2026-00421', at: '30 Sep · 11:02', verified: true },
  { name: 'CBC_CRP_results.pdf', kind: 'Laboratory', size: '340 KB', patient: 'PT-2026-00417', at: '29 Sep · 16:48', verified: true },
  { name: 'Knee_AP_lateral.dcm', kind: 'Imaging', size: '12.1 MB', patient: 'PT-2026-00402', at: '29 Sep · 09:30', verified: true },
  { name: 'Abdomen_US.pdf', kind: 'Imaging', size: '2.8 MB', patient: 'PT-2026-00395', at: '28 Sep · 15:21', verified: false },
  { name: 'Discharge_letter.pdf', kind: 'Medical record', size: '96 KB', patient: 'PT-2026-00379', at: '28 Sep · 10:04', verified: true },
] as const;

export const auditEvents = (() => {
  const random = rng(5150);
  const actions = [
    ['Sign-in', 'auth'], ['Patient viewed', 'read'], ['Assessment created', 'write'],
    ['Prediction issued', 'model'], ['Report generated', 'export'], ['Document uploaded', 'write'],
    ['Chain verified', 'integrity'], ['Sign-in attempt blocked', 'auth'], ['Dataset exported', 'export'],
  ] as const;
  return Array.from({ length: 48 }, (_, index) => {
    const [action, category] = pick(random, actions);
    const at = new Date(NOW.getTime() - index * (13 + Math.floor(random() * 50)) * 60_000);
    return {
      id: `EV-${String(1284 - index).padStart(5, '0')}`,
      action,
      category,
      actor: category === 'model' ? 'PainSense model' : pick(random, CLINICIANS),
      subject: random() < 0.7 ? patients[Math.floor(random() * 40)].code : '—',
      at,
      ip: `10.4.${Math.floor(random() * 6)}.${20 + Math.floor(random() * 200)}`,
      outcome: action.includes('blocked') ? 'Denied' : 'Allowed',
    };
  });
})();

export const ledgerBlocks = Array.from({ length: 8 }, (_, index) => ({
  height: 1248 - index,
  kind: ['Assessment created', 'Prediction issued', 'Report generated', 'Document uploaded'][index % 4],
  hash: `${['4f7a', '91c0', 'bb3e', '0d52', 'a71f', '38c9', 'e204', '6b8d'][index]}…${['e19c', '7a44', '2f08', 'c3b1', '55de', '90a7', 'd6f2', '1e73'][index]}`,
  at: new Date(NOW.getTime() - (index * 37 + 6) * 60_000),
  verified: true,
}));
