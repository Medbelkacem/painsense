export type Role = 'DOCTOR' | 'ADMIN'
export type Profession = 'DOCTOR' | 'NURSE' | 'RESIDENT' | 'OTHER'
export type Sex = 'F' | 'M' | 'OTHER' | 'UNDISCLOSED'
export type SmokingStatus = 'NEVER' | 'FORMER' | 'CURRENT' | 'UNKNOWN'
export type AssessmentStatus = 'DRAFT' | 'ESTIMATED' | 'VALIDATED'
export type Onset = 'SUDDEN' | 'GRADUAL' | 'UNKNOWN'
export type Pattern = 'CONSTANT' | 'INTERMITTENT' | 'EPISODIC' | 'UNKNOWN'
export type Course = 'IMPROVING' | 'STABLE' | 'WORSENING' | 'PROGRESSIVE' | 'UNKNOWN'
export type DataQuality = 'GOOD' | 'ADEQUATE' | 'LIMITED' | 'INSUFFICIENT'
export type BandCode = 'NONE' | 'MILD' | 'MODERATE' | 'SEVERE' | 'EXTREME'
export type Trend = 'RISING' | 'FALLING' | 'STABLE' | 'UNKNOWN'
export type Side = 'LEFT' | 'RIGHT' | 'BILATERAL' | 'MIDLINE' | 'NOT_APPLICABLE'
export type Laterality = 'PAIRED' | 'MIDLINE' | 'LEFT' | 'RIGHT'
export type StructureType =
  | 'REGION'
  | 'MUSCLE'
  | 'TENDON'
  | 'BONE'
  | 'JOINT'
  | 'ORGAN'
  | 'NERVE'
  | 'VESSEL'
export type DocumentKind =
  | 'XRAY'
  | 'CT'
  | 'MRI'
  | 'ULTRASOUND'
  | 'ECG'
  | 'LABORATORY'
  | 'REPORT'
  | 'PRESCRIPTION'
  | 'OTHER'

export interface User {
  id: string
  email: string
  display_name: string
  clinic_name: string | null
  phone: string | null
  profession: Profession
  role: Role
  registration_number: string | null
  speciality: string | null
  is_active: boolean
  last_login_at: string | null
}

export interface TokenResponse {
  access_token: string
  token_type: 'bearer'
  expires_in: number
  csrf_token: string
  user: User
}

export interface PatientIdentity {
  given_name: string
  family_name: string
  phone?: string | null
  emergency_contact_name?: string | null
  emergency_contact_phone?: string | null
}

export interface Medication {
  id?: string
  name: string
  dose?: string | null
  frequency?: string | null
  started_on?: string | null
  is_analgesic?: boolean
  note?: string | null
}

export interface PatientCondition {
  disease_code: string
  diagnosed_year: number | null
  note: string | null
}

export interface PatientSummary {
  id: string
  code: string
  display_name: string
  sex: Sex
  age: number | null
  ward: string | null
  is_synthetic: boolean
  archived: boolean
  assessment_count: number
  latest_assessment_at: string | null
  latest_estimated_pain: number | null
  latest_self_report: number | null
  trend: Trend
}

export interface PatientDetail extends PatientSummary {
  identity: PatientIdentity | null
  birth_date: string | null
  smoking_status: SmokingStatus
  medical_history: string | null
  previous_surgeries: string | null
  allergies: string | null
  family_history: string | null
  lifestyle_notes: string | null
  conditions: PatientCondition[]
  medications: Medication[]
  created_at: string
}

export interface Page<T> {
  items: T[]
  total: number
  limit: number
  offset: number
}

export interface AssessmentLocation {
  code: string
  side: Side
  is_primary: boolean
}

/** A structure localised on the 3D model. `intensity` is never a model input. */
export interface AnatomicalSite {
  structure_code: string
  side: Side
  intensity: number | null
  is_primary: boolean
  note: string | null
}

export interface AnatomicalSiteDetail extends AnatomicalSite {
  label: string
  latin: string
  structure_type: StructureType
  region: string
  location_code: string
}

export interface Measurement {
  recorded_at?: string
  hr?: number | null
  resp_rate?: number | null
  sbp?: number | null
  dbp?: number | null
  spo2?: number | null
  temperature_c?: number | null
  glucose_mmol?: number | null
  weight_kg?: number | null
  height_cm?: number | null
  bmi?: number | null
}

export interface SelfReport {
  nrs: number
  reported_at?: string
  note?: string | null
}

export interface Contribution {
  feature: string
  label: string
  contribution: number
  rank: number
}

export interface Category {
  cause_code: string
  label: string
  group: string
  score: number
  matched: string[]
  missing: string[]
  pain_types: string[]
  note: string
}

export interface Alert {
  rule_code: string
  severity: 'HIGH' | 'MODERATE'
  label: string
  advice: string
  context_notes: string[]
}

export interface ConfounderNote {
  code: string
  label: string
  explanation: string
  affected_vitals: string[]
  vitals_deranged: string[]
}

export interface Prediction {
  created_at: string
  model_version: string | null
  dataset_version: string | null
  refused: boolean
  refusal_reason: string | null
  estimated_pain: number | null
  interval_low: number | null
  interval_high: number | null
  band: BandCode | null
  band_label: string | null
  interval_nominal_level: number | null
  interval_observed_coverage: number | null
  priority_score: number | null
  priority_factors: { label: string; points: number }[]
  data_quality: DataQuality
  quality_issues: string[]
  missing_fields: string[]
  confounder_notes: ConfounderNote[]
  features: Record<string, number | null>
  contributions: Contribution[]
  categories: Category[]
  alerts: Alert[]
}

export interface AssessmentSummary {
  id: string
  patient_id: string
  patient_code: string
  status: AssessmentStatus
  created_at: string
  patient_age_years: number | null
  location_labels: string[]
  estimated_pain: number | null
  band: BandCode | null
  priority_score: number | null
  self_report: number | null
  alert_count: number
  is_synthetic: boolean
}

export interface AssessmentDetail extends AssessmentSummary {
  doctor_id: string
  updated_at: string
  validated_at: string | null
  onset: Onset
  started_at: string | null
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
  radiation_description: string | null
  radiation_numbness: boolean
  radiation_tingling: boolean
  radiation_weakness: boolean
  recent_trauma: boolean
  recent_surgery: boolean
  locations: AssessmentLocation[]
  anatomical_sites: AnatomicalSiteDetail[]
  quality_codes: string[]
  symptom_codes: string[]
  factor_codes: string[]
  confounder_codes: string[]
  answers: Record<string, unknown>
  measurement: Measurement | null
  self_report_detail: (SelfReport & { reported_at: string }) | null
  prediction: Prediction | null
  notes: { id: string; body: string; created_at: string; author_id: string }[]
  document_count: number
}

export interface HistoryPoint {
  assessment_id: string
  created_at: string
  estimated_pain: number | null
  self_report: number | null
  priority_score: number | null
  band: BandCode | null
  hr: number | null
  resp_rate: number | null
  sbp: number | null
  dbp: number | null
  spo2: number | null
  temperature_c: number | null
}

export interface History {
  patient_id: string
  patient_code: string
  points: HistoryPoint[]
  trend: Trend
  change_from_previous: number | null
}

export interface ComparisonField {
  field: string
  label: string
  previous: number | null
  current: number | null
  change: number | null
}

export interface Comparison {
  previous_id: string
  current_id: string
  previous_at: string
  current_at: string
  fields: ComparisonField[]
  symptoms_added: string[]
  symptoms_resolved: string[]
}

export interface Location {
  code: string
  label: string
  region: string
  parent_code: string | null
}

export interface AnatomicalRegion {
  code: string
  label: string
  display_order: number
}

export interface AnatomicalStructureTypeInfo {
  code: StructureType
  label: string
  description: string
  display_order: number
}

export interface AnatomicalStructure {
  code: string
  label: string
  latin: string
  structure_type: StructureType
  region: string
  location_code: string
  location_left: string | null
  location_right: string | null
  laterality: Laterality
  /** The sides this structure can be recorded on, decided by its laterality. */
  sides: Side[]
  synonyms: string[]
  sex: 'F' | 'M' | null
  note: string
}

export interface AnatomyOntology {
  notice: string
  regions: AnatomicalRegion[]
  structure_types: AnatomicalStructureTypeInfo[]
  structures: AnatomicalStructure[]
  /** The same structures nested the way the ontology describes them. */
  tree: {
    region: string
    label: string
    types: { type: StructureType; label: string; structures: string[] }[]
  }[]
}

export interface Quality {
  code: string
  label: string
  neuropathic_hint: boolean
}

export interface PainType {
  code: string
  label: string
  group: string
  parent_code: string | null
  description: string
}

export interface Symptom {
  code: string
  label: string
  group: string
  systemic: boolean
  alarm: boolean
}

export interface Disease {
  code: string
  label: string
  category: string
  pain_relevant: boolean
}

export interface Factor {
  code: string
  label: string
  kind: 'AGGRAVATING' | 'RELIEVING'
}

export interface Confounder {
  code: string
  label: string
  affects: string[]
  note: string
}

export interface Question {
  code: string
  prompt: string
  kind: 'BOOL' | 'SINGLE' | 'MULTI' | 'NUMBER' | 'TEXT'
  group: string
  group_label: string
  options: { value: string; label: string }[]
  unit: string | null
  minimum: number | null
  maximum: number | null
  help_text: string
  order: number
}

export interface QuestionContext {
  patient_id?: string
  age?: number | null
  sex?: Sex | null
  locations?: string[]
  quality_codes?: string[]
  symptom_codes?: string[]
  condition_codes?: string[]
  factor_codes?: string[]
  confounder_codes?: string[]
  onset?: Onset | null
  pattern?: Pattern | null
  course?: Course | null
  duration_hours?: number | null
  radiates?: boolean | null
  recent_trauma?: boolean
  recent_surgery?: boolean
  answers?: Record<string, unknown>
}

export interface VitalRange {
  field: string
  label: string
  unit: string
  accepted_min: number
  accepted_max: number
  reference_min: number | null
  reference_max: number | null
}

export interface MedicalDocument {
  id: string
  patient_id: string
  assessment_id: string | null
  kind: DocumentKind
  original_filename: string
  media_type: string
  size_bytes: number
  sha256: string
  findings: string | null
  extracted_text: string | null
  uploaded_at: string
  uploaded_by: string
}

export interface Analytics {
  patients_total: number
  patients_synthetic: number
  assessments_total: number
  assessments_today: number
  assessments_awaiting_validation: number
  high_pain_count: number
  alerts_open: number
  mean_estimated_pain: number | null
  mean_self_report: number | null
  estimate_vs_self_report_mae: number | null
  band_distribution: Record<string, number>
  region_distribution: Record<string, number>
  daily_mean_pain: { date: string; mean_pain: number; count: number }[]
  recent_assessments: AssessmentSummary[]
}

export interface IntegrityStatus {
  ledger_valid: boolean
  blocks: number
  signature_scheme: string | null
  key_fingerprint: string | null
  audit_valid: boolean
  audit_entries: number
  problems: { height: number; kind: string; detail: string }[]
  verified_at: string
}

export interface SecurityStatus {
  algorithms: { name: string; purpose: string; status: string; detail: string }[]
  keys: {
    label: string
    purpose: string
    algorithm: string
    fingerprint: string
    public_key_bytes: number
  }[]
  keystore_path: string
  integrity: IntegrityStatus
  recent_events: Record<string, unknown>[]
  session_count: number
}

export interface AuditEntry {
  seq: number
  timestamp: string
  actor_label: string | null
  event_type: string
  resource: string | null
  resource_id: string | null
  client_ip: string | null
  meta: Record<string, unknown>
  entry_hash: string
}

export interface DatasetVersion {
  version: string
  generated_at: string
  seed: number
  n_rows: number
  is_synthetic: boolean
  distribution: {
    archetypes?: Record<string, number>
    regions?: Record<string, number>
    sex?: Record<string, number>
    age_bands?: Record<string, number>
    self_report_histogram?: Record<string, number>
    self_report_mean?: number
    self_report_sd?: number
    vitals_recorded?: Record<string, number>
    conditions_recorded?: Record<string, number>
  }
  path: string
}

export interface ModelVersion {
  version: string
  algorithm: string
  trained_at: string
  dataset_version: string
  n_train: number
  n_test: number
  mae: number
  rmse: number
  r2: number
  pearson: number
  cv_folds: number
  cv_mae_mean: number
  cv_mae_sd: number
  residual_sd: number
  features: string[]
  is_active: boolean
  notes: string
}

export interface ModelStatus {
  trained: boolean
  active: ModelVersion | null
  versions: ModelVersion[]
  feature_count: number
  excluded_from_features: string[]
  limitations: string[]
}


export interface Band {
  code: BandCode
  label: string
  upper_bound: number
}
