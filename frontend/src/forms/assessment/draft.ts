import { recordedLocations } from '@/anatomy/sites'
import type {
  AnatomicalSite,
  AnatomicalStructure,
  Course,
  Measurement,
  Onset,
  Pattern,
  Side,
} from '@/api/types'

export interface DraftSite {
  code: string
  side: Side
  is_primary: boolean
}

export interface Draft {
  locations: DraftSite[]
  /** Structures localised on the 3D model. Each one also records a pain location. */
  anatomical_sites: AnatomicalSite[]
  quality_codes: string[]
  symptom_codes: string[]
  factor_codes: string[]
  confounder_codes: string[]
  onset: Onset
  duration_hours: number | null
  pattern: Pattern
  course: Course
  episodes_per_day: number | null
  episode_minutes: number | null
  night_pain: boolean
  morning_pain: boolean
  pain_after_activity: boolean
  pain_at_rest: boolean
  radiates: boolean
  radiation_description: string
  radiation_numbness: boolean
  radiation_tingling: boolean
  radiation_weakness: boolean
  recent_trauma: boolean
  recent_surgery: boolean
  answers: Record<string, unknown>
  measurement: Measurement
  self_report_nrs: number | null
  self_report_note: string
}

export const emptyDraft: Draft = {
  locations: [],
  anatomical_sites: [],
  quality_codes: [],
  symptom_codes: [],
  factor_codes: [],
  confounder_codes: [],
  onset: 'UNKNOWN',
  duration_hours: null,
  pattern: 'UNKNOWN',
  course: 'UNKNOWN',
  episodes_per_day: null,
  episode_minutes: null,
  night_pain: false,
  morning_pain: false,
  pain_after_activity: false,
  pain_at_rest: false,
  radiates: false,
  radiation_description: '',
  radiation_numbness: false,
  radiation_tingling: false,
  radiation_weakness: false,
  recent_trauma: false,
  recent_surgery: false,
  answers: {},
  measurement: {},
  self_report_nrs: null,
  self_report_note: '',
}

/**
 * Every pain location this draft records, whichever surface recorded it.
 *
 * The server works this out for itself when the draft is saved, but the questionnaire is
 * asked for before then: without this, a site localised on the 3D model would not narrow
 * the questions, and a chest structure would be followed by no chest questions.
 */
export function locationCodes(
  draft: Draft,
  structures: readonly AnatomicalStructure[],
): string[] {
  const codes = new Set(draft.locations.map((site) => site.code))
  const byCode = new Map(structures.map((structure) => [structure.code, structure]))
  for (const { code } of recordedLocations(draft.anatomical_sites, byCode)) codes.add(code)
  return [...codes]
}

/** The assessment body the API expects, with the empty strings and nulls stripped out. */
export function toBody(draft: Draft) {
  const measurement = Object.fromEntries(
    Object.entries(draft.measurement).filter(([, value]) => value !== null && value !== undefined),
  )
  const answers = Object.fromEntries(
    Object.entries(draft.answers).filter(([, value]) => value !== undefined && value !== ''),
  )

  return {
    locations: draft.locations.map((site) => ({
      code: site.code,
      side: site.side,
      is_primary: site.is_primary,
    })),
    anatomical_sites: draft.anatomical_sites,
    quality_codes: draft.quality_codes,
    symptom_codes: draft.symptom_codes,
    factor_codes: draft.factor_codes,
    confounder_codes: draft.confounder_codes,
    onset: draft.onset,
    duration_hours: draft.duration_hours,
    pattern: draft.pattern,
    course: draft.course,
    episodes_per_day: draft.episodes_per_day,
    episode_minutes: draft.episode_minutes,
    night_pain: draft.night_pain,
    morning_pain: draft.morning_pain,
    pain_after_activity: draft.pain_after_activity,
    pain_at_rest: draft.pain_at_rest,
    radiates: draft.radiates,
    radiation_description: draft.radiation_description || null,
    radiation_numbness: draft.radiation_numbness,
    radiation_tingling: draft.radiation_tingling,
    radiation_weakness: draft.radiation_weakness,
    recent_trauma: draft.recent_trauma,
    recent_surgery: draft.recent_surgery,
    answers,
    measurement: Object.keys(measurement).length ? measurement : null,
    self_report:
      draft.self_report_nrs === null
        ? null
        : { nrs: draft.self_report_nrs, note: draft.self_report_note || null },
  }
}


/** The same body with the patient attached, which only the create call needs. */
export function toPayload(draft: Draft, patientId: string) {
  return { patient_id: patientId, ...toBody(draft) }
}
