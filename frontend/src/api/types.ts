// Mirrors the Pydantic schemas in backend/app/api/schemas.py. Enum members are spelled
// exactly as the API serialises them, so a value that fails to match here is a real
// mismatch rather than a casing difference.

export type Availability = 'NOT_ATTEMPTED' | 'METADATA_ONLY' | 'AVAILABLE' | 'FAILED';

export type SourceAccess =
  | 'OPEN'
  | 'REGISTRATION_REQUIRED'
  | 'CREDENTIALED'
  | 'AGREEMENT_REQUIRED'
  | 'DOCUMENT_ONLY'
  | 'UNKNOWN';

export type LicenceVerdict =
  | 'PERMISSIVE'
  | 'RESEARCH_ONLY'
  | 'REVIEW_REQUIRED'
  | 'RESTRICTED'
  | 'UNKNOWN';

export type Granularity = 'SUBJECT_LEVEL' | 'AGGREGATE' | 'UNKNOWN';

export type QualityStatus = 'NOT_ASSESSED' | 'PASSED' | 'PASSED_WITH_WARNINGS' | 'FAILED';

export type SyncStage =
  | 'DISCOVER'
  | 'IDENTIFY_DISEASE'
  | 'ACQUIRE'
  | 'VALIDATE'
  | 'PREPROCESS'
  | 'SUITABILITY'
  | 'TRAIN';

export type SyncOutcome = 'OK' | 'SKIPPED' | 'FAILED';
export type RunStatus = 'RUNNING' | 'DONE' | 'FAILED';

export type Role =
  | 'SUPER_ADMIN'
  | 'CLINIC_ADMIN'
  | 'DOCTOR'
  | 'NURSE'
  | 'PATIENT'
  | 'RESEARCHER'
  | 'AUDITOR';

export interface User {
  id: string;
  email: string;
  display_name: string;
  clinic_name?: string | null;
  phone?: string | null;
  profession: 'DOCTOR' | 'NURSE' | 'RESIDENT' | 'OTHER';
  role: Role;
  /** Set on a patient account: the one record it may read. */
  patient_id?: string | null;
  patient_code?: string | null;
  registration_number?: string | null;
  speciality?: string | null;
  is_active: boolean;
  last_login_at?: string | null;
  preferred_language: string;
  locked_until?: string | null;
}

export interface TokenResponse {
  access_token: string;
  token_type: 'bearer';
  expires_in: number;
  csrf_token: string;
  user: User;
}

export interface SyncSource {
  code: string;
  label: string;
  organisation: string;
  homepage: string;
  enabled: boolean;
  poll_interval_minutes: number;
  config: Record<string, unknown>;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
  next_run_at: string | null;
  consecutive_failures: number;
  credentials_present: boolean;
  uses_credentials: boolean;
}

export interface DatasetVersion {
  id: string;
  version: string;
  acquired_at: string;
  source_url: string;
  licence: string | null;
  storage_backend: string;
  bytes: number;
  sha256: string;
  file_format: string;
  file_count: number;
  manifest: { name: string; bytes: number; sha256: string }[];
  records: number | null;
  columns: string[];
  missing_value_pct: number | null;
  quality_status: QualityStatus;
  quality_findings: { check: string; severity: string; message: string; rows: number }[];
  preprocessed_key: string | null;
  suitability: {
    task?: string;
    trainable?: boolean;
    clinically_usable?: boolean;
    conditions_met?: string[];
    reasons?: string[];
    note?: string;
  };
  trainable: boolean;
  training_job_id: string | null;
}

export interface ExternalDataset {
  id: string;
  source_code: string;
  external_id: string;
  name: string;
  description: string;
  source_url: string;
  download_url: string | null;
  download_mechanism: string;
  disease_code: string | null;
  disease_match: { code?: string | null; label?: string | null; basis?: string; created?: boolean };
  dataset_type: string;
  granularity: Granularity;
  modalities: string[];
  target_labels: string[];
  access_status: SourceAccess;
  access_procedure: string[];
  licence: string | null;
  licence_url: string | null;
  licence_verdict: LicenceVerdict;
  redistribution: string;
  publisher_version: string | null;
  publisher_updated_at: string | null;
  records_claimed: number | null;
  relevance: number;
  availability: Availability;
  first_seen_at: string;
  last_checked_at: string;
  changed_at: string | null;
  attempts: number;
  next_attempt_at: string | null;
  last_error: string | null;
  notes: string;
}

export interface ExternalDatasetDetail extends ExternalDataset {
  versions: DatasetVersion[];
}

export interface DiseaseSummary {
  code: string;
  label: string;
  category: string;
  pain_relevant: boolean;
  curated: boolean;
  origin: string;
  discovered_at: string | null;
  datasets: number;
  available: number;
  metadata_only: number;
  records_held: number;
  sources: string[];
  last_acquired_at: string | null;
}

export interface SyncRun {
  id: string;
  source_code: string;
  trigger: string;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  counts: Record<string, unknown>;
  error: string | null;
  job_id: string | null;
}

export interface SyncEvent {
  id: string;
  run_id: string | null;
  dataset_id: string | null;
  at: string;
  source_code: string;
  external_id: string;
  stage: SyncStage;
  outcome: SyncOutcome;
  message: string;
  detail: Record<string, unknown>;
}

export interface SyncOverview {
  sources: SyncSource[];
  diseases: DiseaseSummary[];
  totals: {
    sources: number;
    datasets: number;
    available: number;
    metadata_only: number;
    versions: number;
    trainable_versions: number;
    bytes_held: number;
    datasets_without_disease: number;
  };
  recent_runs: SyncRun[];
  recent_events: SyncEvent[];
  notice: string;
}

export interface Job {
  id: string;
  kind: string;
  status: 'QUEUED' | 'RUNNING' | 'DONE' | 'FAILED';
  progress: number;
  result: Record<string, unknown>;
  error: string | null;
}

// --- EEG & EMG analysis ---------------------------------------------------------------

export type SignalSource = 'HARDWARE' | 'SIMULATION';

export type RecordingState =
  | 'RECORDING'
  | 'PROCESSING'
  | 'SAVED'
  | 'ANALYSED'
  | 'DISCARDED'
  | 'FAILED';

export type QualityVerdict = 'GOOD' | 'ADEQUATE' | 'POOR' | 'UNUSABLE';

export interface SignalChannel {
  code: string;
  label: string;
  modality: 'EEG' | 'EMG' | 'ECG' | 'RESPIRATION';
  unit: string;
  saturation: number;
  minimum_rate_hz: number;
  primary: boolean;
  note: string;
}

export interface SignalReference {
  channels: SignalChannel[];
  eeg_bands: { name: string; low_hz: number; high_hz: number }[];
  emg_band: number[];
  default_sample_rate_hz: number;
  minimum_duration_seconds: number;
  feature_schema_version: string;
  simulation_faults: string[];
  model_available: boolean;
  model_message: string;
  notice: string;
}

export interface ChannelQuality {
  channel: string;
  verdict: QualityVerdict;
  findings: string[];
  sd: number;
  saturated_share: number;
  mains_share: number;
  missing_share: number;
}

export interface QualityReport {
  verdict: QualityVerdict;
  sample_rate_hz: number;
  duration_seconds: number;
  usable_channels: string[];
  supporting_channels: Record<string, QualityVerdict>;
  channels: ChannelQuality[];
  findings: string[];
}

export interface SignalAnalysis {
  id: string;
  recording_id: string;
  analysed_at: string;
  feature_schema_version: string;
  feature_count: number;
  summary: {
    eeg: Record<string, number | null>;
    emg: Record<string, number | null>;
    heart_rate_bpm: number | null;
    hrv_rmssd_ms: number | null;
    skin_conductance_us: number | null;
    respiration_per_min: number | null;
  };
  derived_from: string[];
  skipped_channels: Record<string, string>;
  heart_rate_bpm: number | null;
  hrv_rmssd_ms: number | null;
  skin_conductance_us: number | null;
  respiration_per_min: number | null;
  estimate_available: boolean;
  unavailable_reason: string | null;
  model_version: string | null;
  pain_score: number | null;
  pain_category: string | null;
  scale: string | null;
  uncertainty: number | null;
  interval_low: number | null;
  interval_high: number | null;
  reported_nrs: number | null;
  notes: string[];
}

export interface AcquisitionAdapter {
  code: string;
  label: string;
  protocol: string;
  transport: string;
}

export interface AcquisitionDevice {
  adapter: string;
  identifier: string;
  label: string;
  native_channels: string[];
  sample_rate_hz: number;
  unit: string;
  confirmed: boolean;
  detail: Record<string, unknown>;
}

export interface DeviceScan {
  adapters: AcquisitionAdapter[];
  devices: AcquisitionDevice[];
  connected: boolean;
  notice: string;
}

export interface LiveView {
  recording_id: string;
  source: SignalSource;
  state: RecordingState;
  channels: Record<string, (number | null)[]> | null;
  decimation: number | null;
  rates: Record<string, number>;
  device: {
    connected?: boolean;
    invalid_packets?: number;
    dropped_samples?: number;
    reconnects?: number;
    last_error?: string | null;
  };
  progress: {
    samples: number;
    rows_written: number;
    dropped_samples: number;
    invalid_packets: number;
    reconnects: number;
    elapsed_seconds: number;
    stalled_for_seconds: number | null;
    error: string | null;
    finished: boolean;
  };
  notice: string;
}

export interface SignalRecording {
  id: string;
  patient_id: string;
  source: SignalSource;
  state: RecordingState;
  device_label: string | null;
  adapter: string | null;
  device_identifier: string | null;
  sample_rate_hz: number;
  channel_rates: Record<string, number>;
  channels: string[];
  sensor_status: Record<string, string>;
  participant_ref: string | null;
  dropped_samples: number;
  invalid_packets: number;
  reconnects: number;
  validated_at: string | null;
  started_at: string;
  stopped_at: string | null;
  duration_seconds: number | null;
  samples: number;
  bytes: number;
  sha256: string | null;
  quality_verdict: QualityVerdict | null;
  note: string | null;
  error: string | null;
}

export interface SignalRecordingDetail extends SignalRecording {
  quality: QualityReport | Record<string, never>;
  validation: {
    intact?: boolean;
    findings?: string[];
    channels_present?: string[];
    samples_per_channel?: Record<string, number>;
    rates?: Record<string, number>;
    gaps?: Record<string, number>;
  };
  files: { name: string; bytes: number; sha256: string }[];
  analyses: SignalAnalysis[];
}

export interface SignalWaveform {
  recording_id: string;
  source: SignalSource;
  sample_rate_hz: number;
  points_per_channel: number;
  decimation: number;
  channels: Record<string, (number | null)[]>;
  notice: string;
}

export type Side = 'LEFT' | 'RIGHT' | 'BILATERAL' | 'MIDLINE' | 'NOT_APPLICABLE';
export type Laterality = 'PAIRED' | 'MIDLINE' | 'LEFT' | 'RIGHT';
export type StructureType =
  | 'REGION'
  | 'MUSCLE'
  | 'TENDON'
  | 'LIGAMENT'
  | 'BONE'
  | 'JOINT'
  | 'ORGAN'
  | 'NERVE'
  | 'VESSEL';

export interface AnatomicalRegion {
  code: string;
  label: string;
  display_order: number;
}

export interface AnatomicalStructureTypeInfo {
  code: StructureType;
  label: string;
  description: string;
  display_order: number;
}

export interface AnatomicalStructure {
  code: string;
  label: string;
  latin: string;
  structure_type: StructureType;
  region: string;
  location_code: string;
  location_left: string | null;
  location_right: string | null;
  laterality: Laterality;
  /** The sides this structure can be recorded on, decided by its laterality. */
  sides: Side[];
  synonyms: string[];
  sex: 'F' | 'M' | null;
  parent_code: string | null;
  subregion: string | null;
  system: string | null;
  /** Whether the 3D model draws it. Everything else is reachable from the list only. */
  has_mesh: boolean;
  pain_selectable: boolean;
  description: string;
  note: string;
}

export interface AnatomicalRelation {
  relation: string;
  code: string;
  label: string;
  structure_type: StructureType;
}

export interface AnatomicalStructureDetail extends AnatomicalStructure {
  breadcrumb: { code: string; label: string }[];
  related: AnatomicalRelation[];
  children: string[];
}

export interface AnatomyOntology {
  notice: string;
  regions: AnatomicalRegion[];
  structure_types: AnatomicalStructureTypeInfo[];
  systems: { code: string; label: string }[];
  structures: AnatomicalStructure[];
  tree: {
    region: string;
    label: string;
    types: { type: StructureType; label: string; structures: string[] }[];
  }[];
  counts: Record<string, number>;
}

// --- behavioural observation: what a camera and a microphone measure --------------------

export type BehaviourModality = 'EYE' | 'FACE' | 'VOICE';

export interface BehaviourMeasure {
  code: string;
  label: string;
  modality: BehaviourModality;
  unit: string;
  /** What the number is, and what else moves it. Shown beside the figure. */
  note: string;
  plausible: [number, number] | null;
  /** True where the measure means nothing without a resting observation to subtract. */
  baseline_relative: boolean;
}

export interface BehaviourReference {
  measures: BehaviourMeasure[];
  modalities: BehaviourModality[];
  feature_schema_version: string;
  minimum_seconds: number;
  minimum_frame_rate: number;
  iris_diameter_mm: number;
  accepted_media: string[];
  max_clip_bytes: number;
  consent_scope: string;
  instruction: string;
  notice: string;
  voice_model_available: boolean;
  voice_model_message: string;
  voice_levels: string[];
}

export interface BehaviourModalityQuality {
  modality: BehaviourModality;
  verdict: QualityVerdict;
  usable: boolean;
  findings: string[];
  evidence: Record<string, number>;
}

export interface BehaviourVoiceEstimate {
  available: boolean;
  message: string;
  model_version: string | null;
  /** A position on the four-level scale below, never a score out of ten. */
  level: number | null;
  label: string | null;
  level_error: number | null;
  scale: string[];
  limitations: string[];
}

export interface BehaviourObservation {
  id: string;
  patient_id: string;
  assessment_id: string | null;
  recorded_at: string;
  at_rest: boolean;

  duration_seconds: number | null;
  frame_rate: number | null;
  frames_decoded: number;
  frames_analysed: number;
  frame_width: number | null;
  frame_height: number | null;
  has_video: boolean;
  has_audio: boolean;
  /** True where the eye windows were fitted to this patient rather than assumed. */
  eyes_calibrated: boolean;

  quality_verdict: QualityVerdict | null;
  usable_modalities: BehaviourModality[];
  modalities: BehaviourModalityQuality[];

  feature_schema_version: string;
  measures: Record<string, number>;
  deltas: Record<string, number>;
  /** Per measure: CALIBRATION where a resting observation existed, else WITHIN_WINDOW. */
  reference: Record<string, string>;
  absent: Record<string, string>;
  support: Record<string, number>;
  summary: {
    eye: Record<string, number | null>;
    face: Record<string, number | null>;
    voice: Record<string, number | null>;
    reference: Record<string, string>;
    deltas: Record<string, number>;
  };

  media_retained: boolean;
  media_bytes: number;
  media_sha256: string | null;

  voice_estimate: BehaviourVoiceEstimate | null;
  notes: string[];
}

export interface BehaviourObservationSummary {
  id: string;
  assessment_id: string | null;
  recorded_at: string;
  at_rest: boolean;
  duration_seconds: number | null;
  quality_verdict: QualityVerdict | null;
  usable_modalities: BehaviourModality[];
  has_video: boolean;
  has_audio: boolean;
  media_retained: boolean;
  voice_pain_level: number | null;
  voice_pain_label: string | null;
}

export interface RestingBehaviour {
  recorded_at: string | null;
  measures: Record<string, number>;
}

// --- clinical records -------------------------------------------------------------------

export type Sex = 'F' | 'M' | 'OTHER' | 'UNDISCLOSED';
export type SmokingStatus = 'NEVER' | 'FORMER' | 'CURRENT' | 'UNKNOWN';
export type Trend = 'RISING' | 'FALLING' | 'STABLE' | 'UNKNOWN';
export type AssessmentStatus = 'DRAFT' | 'ESTIMATED' | 'VALIDATED';
export type Onset = 'SUDDEN' | 'GRADUAL' | 'UNKNOWN';
export type OnsetSpeed = 'SECONDS' | 'MINUTES' | 'HOURS' | 'DAYS' | 'WEEKS_OR_MORE' | 'UNKNOWN';
export type Pattern = 'CONSTANT' | 'INTERMITTENT' | 'EPISODIC' | 'UNKNOWN';
export type Course = 'IMPROVING' | 'STABLE' | 'WORSENING' | 'PROGRESSIVE' | 'UNKNOWN';
export type PainSiteRole = 'PRIMARY' | 'SECONDARY' | 'RADIATING' | 'REFERRED';
export type ReviewAgreement = 'AGREE' | 'PARTLY' | 'DISAGREE';
export type DataQuality = 'GOOD' | 'ADEQUATE' | 'LIMITED' | 'INSUFFICIENT';
export type PainBandCode = 'NONE' | 'MILD' | 'MODERATE' | 'SEVERE' | 'EXTREME';
export type DoseCategory = 'LOW' | 'STANDARD' | 'HIGH' | 'UNKNOWN';
export type DoseFrequency =
  | 'SINGLE'
  | 'DAILY'
  | 'TWICE_DAILY'
  | 'THREE_TIMES_DAILY'
  | 'FOUR_TIMES_DAILY'
  | 'AS_NEEDED'
  | 'CONTINUOUS'
  | 'UNKNOWN';
export type PainEffect = 'NONE' | 'PARTIAL' | 'GOOD' | 'UNKNOWN';
export type SedationEffect = 'NONE' | 'MILD' | 'MARKED' | 'UNKNOWN';

export type DocumentKind =
  | 'XRAY'
  | 'WOUND_PHOTO'
  | 'CT'
  | 'MRI'
  | 'ULTRASOUND'
  | 'ECG'
  | 'LABORATORY'
  | 'REPORT'
  | 'PRESCRIPTION'
  | 'OTHER';

export interface PatientIdentity {
  given_name: string;
  family_name: string;
  phone?: string | null;
  emergency_contact_name?: string | null;
  emergency_contact_phone?: string | null;
}

export type Ward =
  | 'Emergency'
  | 'Surgery'
  | 'Medicine'
  | 'Intensive care'
  | 'Oncology'
  | 'Rheumatology'
  | 'Paediatrics'
  | 'Other';

export const WARDS: readonly Ward[] = [
  'Emergency',
  'Surgery',
  'Medicine',
  'Intensive care',
  'Oncology',
  'Rheumatology',
  'Paediatrics',
  'Other',
];

/** A cross-check the server raised over the record. Never blocks a save. */
export interface Finding {
  code: string;
  level: 'WARNING' | 'URGENT';
  message: string;
}

export interface PatientSummary {
  id: string;
  code: string;
  display_name: string;
  sex: Sex;
  age: number | null;
  ward: Ward | null;
  is_synthetic: boolean;
  archived: boolean;
  assessment_count: number;
  latest_assessment_at: string | null;
  latest_estimated_pain: number | null;
  latest_self_report: number | null;
  trend: Trend;
}

export interface PatientMedication {
  id: string;
  name: string;
  dose: string | null;
  frequency: string | null;
  started_on: string | null;
  is_analgesic: boolean;
  note: string | null;
}

export interface PatientCondition {
  disease_code: string;
  diagnosed_year: number | null;
  note: string | null;
}

export interface PatientDetail extends PatientSummary {
  identity: PatientIdentity | null;
  age_years: number | null;
  birth_date: string | null;
  smoking_status: SmokingStatus;
  medical_history: string | null;
  previous_surgeries: string | null;
  allergies: string | null;
  family_history: string | null;
  lifestyle_notes: string | null;
  conditions: PatientCondition[];
  medications: PatientMedication[];
  warnings: Finding[];
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface PainLocationRef {
  code: string;
  side: Side;
  is_primary: boolean;
}

/** One site of pain, as the assessment form sends it. */
export interface AnatomicalSiteIn {
  structure_code: string;
  side: Side;
  role: PainSiteRole;
  sequence: number;
  radiation_from_code?: string | null;
  radiation_from_side?: Side | null;
  quality_codes: string[];
  onset: Onset;
  pattern: Pattern;
  course: Course;
  intensity?: number | null;
  is_primary: boolean;
  note?: string | null;
}

export interface AnatomicalSiteOut extends AnatomicalSiteIn {
  label: string;
  latin: string;
  structure_type: string;
  region: string;
  subregion: string | null;
  location_code: string;
  breadcrumb: string[];
}

/** Vital signs and body measurements taken during the examination. */
export interface Measurement {
  recorded_at?: string | null;
  hr?: number | null;
  resp_rate?: number | null;
  sbp?: number | null;
  dbp?: number | null;
  spo2?: number | null;
  temperature_c?: number | null;
  glucose_mmol?: number | null;
  weight_kg?: number | null;
  height_cm?: number | null;
}

export interface MeasurementOut extends Measurement {
  recorded_at: string;
  bmi: number | null;
}

export interface FunctionalImpact {
  mobility?: number | null;
  sleep?: number | null;
  work?: number | null;
  daily_activity?: number | null;
  self_care?: number | null;
}

export interface MedicationUse {
  class_code: string;
  name?: string | null;
  dose_category: DoseCategory;
  frequency: DoseFrequency;
  hours_since_last_dose?: number | null;
  pain_effect: PainEffect;
  sedation_effect: SedationEffect;
}

export interface MedicationUseOut extends MedicationUse {
  class_label: string;
  analgesic: boolean;
  sedating: boolean;
}

export interface SelfReportIn {
  nrs?: number | null;
  scale_code: string;
  raw_score?: number | null;
  items?: Record<string, number>;
  observed?: boolean | null;
  reported_at?: string | null;
  note?: string | null;
}

export interface SelfReportOut {
  nrs: number;
  scale_code: string;
  raw_score: number | null;
  raw_max: number | null;
  items: Record<string, number>;
  observed: boolean;
  reported_at: string;
  note: string | null;
}

export interface Contribution {
  feature: string;
  label: string;
  contribution: number;
  rank: number;
}

export interface Category {
  cause_code: string;
  label: string;
  group: string;
  score: number;
  matched: string[];
  missing: string[];
  pain_types: string[];
  note: string;
}

export interface Alert {
  rule_code: string;
  severity: string;
  label: string;
  advice: string;
  context_notes: string[];
}

export interface Prediction {
  created_at: string;
  model_name: string | null;
  model_version: string | null;
  dataset_version: string | null;
  feature_schema_version: string | null;
  inference_ms: number | null;
  refused: boolean;
  refusal_reason: string | null;
  estimated_pain: number | null;
  interval_low: number | null;
  interval_high: number | null;
  band: string | null;
  band_label: string | null;
  interval_nominal_level: number | null;
  interval_observed_coverage: number | null;
  priority_score: number | null;
  priority_level: string | null;
  priority_label: string | null;
  priority_disclaimer: string;
  priority_factors: Record<string, unknown>[];
  trajectory: string;
  baseline: Record<string, unknown>;
  population: Record<string, unknown>;
  profile_code: string | null;
  reference_scale: string | null;
  can_self_report: boolean;
  profile_penalty: number;
  data_quality: DataQuality;
  data_quality_score: number | null;
  quality_issues: string[];
  missing_fields: string[];
  confounder_notes: Record<string, unknown>[];
  features: Record<string, number | null>;
  contributions: Contribution[];
  categories: Category[];
  alerts: Alert[];
}

export interface AssessmentSummary {
  id: string;
  patient_id: string;
  patient_code: string;
  status: AssessmentStatus;
  created_at: string;
  patient_age_years: number | null;
  location_labels: string[];
  estimated_pain: number | null;
  band: string | null;
  priority_score: number | null;
  priority_level: string | null;
  trajectory: string | null;
  self_report: number | null;
  alert_count: number;
  is_synthetic: boolean;
}

export interface AssessmentNote {
  id: string;
  body: string;
  created_at: string;
  author_id: string;
}

/** The timing, pattern and history fields an assessment carries in its own right. */
export type DurationUnit = 'minutes' | 'hours' | 'days' | 'months' | 'years';

export interface AssessmentBody {
  onset: Onset;
  onset_speed: OnsetSpeed;
  started_at: string | null;
  duration_value: number | null;
  duration_unit: DurationUnit | null;
  pattern: Pattern;
  course: Course;
  recurrent: boolean;
  episodes_per_day: number | null;
  episode_minutes: number | null;
  night_pain: boolean;
  morning_pain: boolean;
  afternoon_pain: boolean;
  evening_pain: boolean;
  variable_timing: boolean;
  pain_after_activity: boolean;
  pain_at_rest: boolean;
  functional_impact: FunctionalImpact;
  radiates: boolean;
  radiation_description: string | null;
  radiation_numbness: boolean;
  radiation_tingling: boolean;
  radiation_weakness: boolean;
  recent_trauma: boolean;
  recent_surgery: boolean;
  symptoms_note: string | null;
  aggravating_note: string | null;
  relieving_note: string | null;
}

export interface AssessmentCreate extends Partial<AssessmentBody> {
  patient_id: string;
  locations?: PainLocationRef[];
  anatomical_sites?: AnatomicalSiteIn[];
  quality_codes?: string[];
  symptom_codes?: string[];
  factor_codes?: string[];
  confounder_codes?: string[];
  medications?: MedicationUse[];
  answers?: Record<string, unknown>;
  measurement?: Measurement | null;
  self_report?: SelfReportIn | null;
  profile_code?: string | null;
  profile_modifiers?: string[];
  pregnancy_trimester?: number | null;
  expected_pain?: boolean;
}

export interface Clinician {
  display_name: string;
  speciality?: string | null;
  registration_number?: string | null;
}

export interface AssessmentDetail extends AssessmentSummary, AssessmentBody {
  doctor_id: string;
  recorded_by: Clinician | null;
  validated_by_name: string | null;
  updated_at: string;
  validated_at: string | null;
  review_agreement: ReviewAgreement | null;
  review_comment: string | null;
  duration_hours: number | null;
  duration_label: string;
  locations: PainLocationRef[];
  anatomical_sites: AnatomicalSiteOut[];
  quality_codes: string[];
  symptom_codes: string[];
  factor_codes: string[];
  confounder_codes: string[];
  medications: MedicationUseOut[];
  answers: Record<string, unknown>;
  measurement: MeasurementOut | null;
  self_report_detail: SelfReportOut | null;
  prediction: Prediction | null;
  notes: AssessmentNote[];
  document_count: number;
  warnings: Finding[];
  urgent_review: boolean;
  completeness: number;
  missing_fields: string[];
}

export interface HistoryPoint {
  assessment_id: string;
  created_at: string;
  estimated_pain: number | null;
  self_report: number | null;
  priority_score: number | null;
  band: string | null;
  hr: number | null;
  resp_rate: number | null;
  sbp: number | null;
  dbp: number | null;
  spo2: number | null;
  temperature_c: number | null;
}

export interface PatientHistory {
  patient_id: string;
  patient_code: string;
  points: HistoryPoint[];
  trend: Trend;
  change_from_previous: number | null;
}

export interface TimelineEvent {
  at: string;
  kind:
    | 'ASSESSMENT'
    | 'PREDICTION'
    | 'SELF_REPORT'
    | 'MEASUREMENT'
    | 'MEDICATION'
    | 'DOCUMENT'
    | 'REPORT'
    | 'REVIEW'
    | 'NOTE';
  title: string;
  detail: string | null;
  assessment_id: string | null;
  value?: number | null;
  level?: string | null;
}

export interface PatientTimeline {
  patient_id: string;
  patient_code: string;
  events: TimelineEvent[];
}

export interface BaselineVital {
  field: string;
  label: string;
  baseline: number;
  current: number | null;
  delta: number | null;
  readings: number;
  departed: boolean;
}

export interface PatientBaseline {
  patient_id: string;
  assessments_used: number;
  vitals: BaselineVital[];
  previous_pain: number | null;
  current_pain: number | null;
  trajectory: string;
  pain_change: number | null;
}

// --- reference catalogue ----------------------------------------------------------------

export interface PainLocationEntry {
  code: string;
  label: string;
  region: string;
  parent_code: string | null;
}

export interface PainQuality {
  code: string;
  label: string;
  neuropathic_hint: boolean;
}

export interface PainType {
  code: string;
  label: string;
  group: string;
  parent_code: string | null;
  description: string;
}

export interface Symptom {
  code: string;
  label: string;
  group: string;
  systemic: boolean;
  alarm: boolean;
}

export interface Disease {
  code: string;
  label: string;
  category: string;
  pain_relevant: boolean;
}

export interface PainFactor {
  code: string;
  label: string;
  kind: string;
}

export interface Confounder {
  code: string;
  label: string;
  affects: string[];
  note: string;
}

export interface MedicationClass {
  code: string;
  label: string;
  analgesic: boolean;
  sedating: boolean;
  affects: string[];
  note: string;
}

export interface ClinicalQuestion {
  code: string;
  prompt: string;
  kind: string;
  group: string;
  group_label: string;
  options: { value: string; label: string }[];
  unit: string | null;
  minimum: number | null;
  maximum: number | null;
  help_text: string;
  order: number;
}

export interface PainBand {
  code: string;
  label: string;
  upper_bound: number;
  advice: string;
}

export interface ScaleItem {
  code: string;
  label: string;
  minimum: number;
  maximum: number;
  anchors: string[];
}

export interface PainScale {
  code: string;
  label: string;
  kind: string;
  minimum: number;
  maximum: number;
  steps: number[];
  population: string;
  note: string;
  items: ScaleItem[];
}

export interface PatientProfile {
  code: string;
  label: string;
  kind: string;
  min_age: number | null;
  max_age: number | null;
  can_self_report: boolean;
  reference_scale: string | null;
  alternative_scales: string[];
  priority_signals: string[];
  signals_not_available: string[];
  confounders: string[];
  confidence_penalty: number;
  requires_trimester: boolean;
  prefers_own_history: boolean;
  interpretation: string;
  note: string;
}

/** The physiological band a reading is compared against, for one population. */
export interface ReferenceBand {
  code: string;
  label: string;
  min_age: number | null;
  max_age: number | null;
  source: string;
  normal: Record<string, number[]>;
  unverified: string[];
  note: string;
}

export interface ProfileCatalogue {
  primary: PatientProfile[];
  modifiers: PatientProfile[];
  scales: PainScale[];
  bands: ReferenceBand[];
  notice: string;
}

// --- governance and operations ----------------------------------------------------------

export interface Analytics {
  patients_total: number;
  assessments_total: number;
  assessments_today: number;
  assessments_awaiting_validation: number;
  high_pain_count: number;
  alerts_open: number;
  mean_estimated_pain: number | null;
  mean_self_report: number | null;
  estimate_vs_self_report_mae: number | null;
  band_distribution: Record<string, number>;
  region_distribution: Record<string, number>;
  daily_mean_pain: { date: string; mean_pain: number; count: number }[];
  recent_assessments: AssessmentSummary[];
}

export interface ClinicalDocument {
  id: string;
  patient_id: string;
  assessment_id: string | null;
  kind: DocumentKind;
  original_filename: string;
  media_type: string;
  size_bytes: number;
  sha256: string;
  findings: string | null;
  extracted_text: string | null;
  uploaded_at: string;
  uploaded_by: string;
}

export interface AuditEntry {
  seq: number;
  timestamp: string;
  actor_label: string | null;
  event_type: string;
  resource: string | null;
  resource_id: string | null;
  client_ip: string | null;
  meta: Record<string, unknown>;
  entry_hash: string;
}

export interface IntegrityProblem {
  height: number;
  kind: string;
  detail: string;
}

export interface IntegrityStatus {
  ledger_valid: boolean;
  blocks: number;
  signature_scheme: string | null;
  key_fingerprint: string | null;
  audit_valid: boolean;
  audit_entries: number;
  problems: IntegrityProblem[];
  verified_at: string;
}

export interface AlgorithmStatus {
  name: string;
  purpose: string;
  status: string;
  detail: string;
}

export interface KeyVersion {
  label: string;
  purpose: string;
  version: number;
  algorithm: string;
  fingerprint: string;
  is_current: boolean;
  created_at: string;
  rotated_at: string | null;
  retired_at: string | null;
}

export interface SecurityStatus {
  algorithms: AlgorithmStatus[];
  keys: KeyVersion[];
  pqc_kem_level: string;
  pqc_sign_level: string;
  integrity: IntegrityStatus;
  recent_events: Record<string, unknown>[];
  session_count: number;
  failed_logins_24h: number;
  locked_accounts: number;
  documents_encrypted: number;
  patients_sealed: number;
  master_key_versions_in_ring: number;
}

export interface TrainedModel {
  version: string;
  model_name: string;
  algorithm: string;
  trained_at: string;
  dataset_version: string;
  feature_schema_version: string;
  n_train: number;
  n_validation: number;
  n_test: number;
  mae: number;
  rmse: number;
  r2: number;
  pearson: number;
  f1_band: number | null;
  inference_ms: number | null;
  cv_folds: number;
  cv_mae_mean: number;
  cv_mae_sd: number;
  residual_sd: number;
  features: string[];
  feature_importance: { feature: string; label?: string; importance: number }[];
  comparison: Record<string, unknown>[];
  training_profile: Record<string, unknown>;
  is_active: boolean;
  notes: string;
}

export interface ModelStatus {
  trained: boolean;
  active: TrainedModel | null;
  versions: TrainedModel[];
  feature_count: number;
  feature_schema_version: string;
  excluded_from_features: string[];
  limitations: string[];
  prediction_count: number;
}

export interface Drift {
  level: string;
  sample_size: number;
  warnings: string[];
  features: Record<string, unknown>[];
  prediction_shift: Record<string, unknown>;
}

export interface GeneratedDataset {
  version: string;
  generated_at: string;
  generator_version: string;
  seed: number;
  n_rows: number;
  n_patients: number;
  is_synthetic: boolean;
  storage_format: string;
  parameters: Record<string, unknown>;
  scenario_versions: Record<string, unknown>;
  split: Record<string, number>;
  distribution: Record<string, Record<string, number>>;
  path: string;
}

export interface DatasetExplorer {
  latest: GeneratedDataset | null;
  versions: GeneratedDataset[];
  anatomy: Record<string, number>;
  pain_types: number;
  pain_qualities: number;
  symptoms: number;
  diseases: number;
  medication_classes: number;
  confounders: number;
  questions: number;
  rules: number;
}
