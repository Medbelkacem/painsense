import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import {
  Activity, ArrowLeft, ArrowRight, Check, CloudCheck, FileDown, Plus, Save, Trash2,
  TriangleAlert, Video,
} from 'lucide-react';

import { ApiError, download, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type {
  AnatomicalSiteIn, AssessmentDetail, Confounder, Course, Disease, DurationUnit,
  FunctionalImpact, MedicationClass, Onset, Page, PainFactor, PainQuality, PatientDetail,
  PatientSummary, Pattern, Symptom,
} from '../api/types';
import { useSession } from '../auth/session';
import { SitePicker } from '../anatomy/SitePicker';
import { BehaviourPanel } from '../capture/BehaviourPanel';
import { SignalPanel } from '../signals/SignalPanel';
import { Button } from '../ui/Button';
import { Card, CardHead } from '../ui/Card';
import { Select } from '../ui/Dropdown';
import { Choice, TextField, Toggle } from '../ui/Field';
import { Stepper } from '../ui/Nav';
import { NrsScale } from '../ui/NrsScale';
import { Pill, Tile } from '../ui/Pill';
import { Segmented } from '../ui/Segmented';
import { bandOf, BAND_LABEL, BAND_VAR } from '../ui/charts';
import { cx } from '../lib/cx';
import {
  COURSE_OPTIONS, DURATION_UNITS, durationLabel, ONSET_OPTIONS, PATTERN_OPTIONS,
} from '../lib/clinical';
import {
  EMPTY_PATIENT, PatientFields, patientFormFrom, patientPayload, validatePatient,
  type PatientFormErrors, type PatientFormValues,
} from '../components/PatientForm';
import { AssessmentSummary, useCatalogLabels, WarningList } from '../components/AssessmentSummary';
import { EstimatePanel } from '../components/EstimatePanel';

const STEPS = [
  { label: 'Patient' },
  { label: 'Site' },
  { label: 'Pain' },
  { label: 'Symptoms and context' },
  { label: 'Self-report' },
  { label: 'Physiology' },
  { label: 'Camera and voice' },
  { label: 'EEG and EMG' },
  { label: 'AI analysis' },
  { label: 'Review' },
];
const SITE_STEP = 1;
const CAMERA_STEP = 6;
const SIGNAL_STEP = 7;
const ANALYSIS_STEP = 8;
const REVIEW_STEP = 9;
const WIDE_STEPS = new Set([SITE_STEP, CAMERA_STEP, SIGNAL_STEP, REVIEW_STEP]);

const FUNCTIONAL_DOMAINS: { key: keyof FunctionalImpact; label: string }[] = [
  { key: 'mobility', label: 'Mobility' },
  { key: 'sleep', label: 'Sleep' },
  { key: 'work', label: 'Work' },
  { key: 'daily_activity', label: 'Daily activities' },
  { key: 'self_care', label: 'Self-care' },
];
const IMPACT_WORD = ['None', 'Slight', 'Moderate', 'Severe', 'Unable'];

const VITALS = [
  { key: 'hr', label: 'Heart rate', unit: 'bpm' },
  { key: 'resp_rate', label: 'Respiratory rate', unit: '/min' },
  { key: 'sbp', label: 'Systolic pressure', unit: 'mmHg' },
  { key: 'dbp', label: 'Diastolic pressure', unit: 'mmHg' },
  { key: 'spo2', label: 'Oxygen saturation', unit: '%' },
  { key: 'temperature_c', label: 'Temperature', unit: '°C' },
  { key: 'glucose_mmol', label: 'Blood glucose', unit: 'mmol/L' },
  { key: 'weight_kg', label: 'Weight', unit: 'kg' },
  { key: 'height_cm', label: 'Height', unit: 'cm' },
] as const;
type VitalKey = (typeof VITALS)[number]['key'];

const TIMINGS = [
  { key: 'morning_pain', label: 'Morning' },
  { key: 'afternoon_pain', label: 'Afternoon' },
  { key: 'evening_pain', label: 'Evening' },
  { key: 'night_pain', label: 'Night' },
  { key: 'variable_timing', label: 'No fixed time' },
  { key: 'pain_at_rest', label: 'At rest' },
  { key: 'pain_after_activity', label: 'After activity' },
] as const;
type TimingKey = (typeof TIMINGS)[number]['key'];

interface GivenMedication {
  class_code: string;
  name: string;
  hours_since_last_dose: string;
}

interface Draft {
  anatomical_sites: AnatomicalSiteIn[];
  quality_codes: string[];
  onset: Onset;
  duration_value: string;
  duration_unit: DurationUnit;
  pattern: Pattern;
  course: Course;
  radiates: boolean;
  radiation_description: string;
  timing: Record<TimingKey, boolean>;
  recent_trauma: boolean;
  recent_surgery: boolean;
  symptom_codes: string[];
  symptoms_note: string;
  factor_codes: string[];
  aggravating_note: string;
  relieving_note: string;
  confounder_codes: string[];
  given: GivenMedication[];
  functional_impact: FunctionalImpact;
  vitals: Record<VitalKey, string>;
  nrs: number | null;
  self_report_note: string;
}

const EMPTY_TIMING = Object.fromEntries(TIMINGS.map((entry) => [entry.key, false])) as Record<TimingKey, boolean>;
const EMPTY_VITALS = Object.fromEntries(VITALS.map((entry) => [entry.key, ''])) as Record<VitalKey, string>;

const EMPTY: Draft = {
  anatomical_sites: [],
  quality_codes: [],
  onset: 'UNKNOWN',
  duration_value: '',
  duration_unit: 'hours',
  pattern: 'UNKNOWN',
  course: 'UNKNOWN',
  radiates: false,
  radiation_description: '',
  timing: EMPTY_TIMING,
  recent_trauma: false,
  recent_surgery: false,
  symptom_codes: [],
  symptoms_note: '',
  factor_codes: [],
  aggravating_note: '',
  relieving_note: '',
  confounder_codes: [],
  given: [],
  functional_impact: {},
  vitals: EMPTY_VITALS,
  nrs: null,
  self_report_note: '',
};

interface StandingMedication {
  name: string;
  dose: string;
  frequency: string;
  is_analgesic: boolean;
}

/** The patient-level facts this form amends: the record, not this visit. */
interface RecordDraft {
  fields: PatientFormValues;
  condition_codes: string[];
  medications: StandingMedication[];
  allergies: string;
  medical_history: string;
  previous_surgeries: string;
}

const EMPTY_RECORD: RecordDraft = {
  fields: EMPTY_PATIENT,
  condition_codes: [],
  medications: [],
  allergies: '',
  medical_history: '',
  previous_surgeries: '',
};

function recordFrom(patient: PatientDetail): RecordDraft {
  return {
    fields: patientFormFrom(patient),
    condition_codes: patient.conditions.map((entry) => entry.disease_code),
    medications: patient.medications.map((entry) => ({
      name: entry.name,
      dose: entry.dose ?? '',
      frequency: entry.frequency ?? '',
      is_analgesic: entry.is_analgesic,
    })),
    allergies: patient.allergies ?? '',
    medical_history: patient.medical_history ?? '',
    previous_surgeries: patient.previous_surgeries ?? '',
  };
}

function draftFrom(saved: AssessmentDetail): Draft {
  return {
    anatomical_sites: saved.anatomical_sites.map((site) => ({
      structure_code: site.structure_code,
      side: site.side,
      role: site.role,
      sequence: site.sequence,
      radiation_from_code: site.radiation_from_code ?? null,
      radiation_from_side: site.radiation_from_side ?? null,
      quality_codes: site.quality_codes,
      onset: site.onset,
      pattern: site.pattern,
      course: site.course,
      intensity: site.intensity ?? null,
      is_primary: site.is_primary,
      note: site.note ?? null,
    })),
    quality_codes: saved.quality_codes,
    onset: saved.onset,
    duration_value: saved.duration_value !== null ? String(saved.duration_value) : '',
    duration_unit: saved.duration_unit ?? 'hours',
    pattern: saved.pattern,
    course: saved.course,
    radiates: saved.radiates,
    radiation_description: saved.radiation_description ?? '',
    timing: Object.fromEntries(TIMINGS.map((entry) => [entry.key, saved[entry.key]])) as Record<TimingKey, boolean>,
    recent_trauma: saved.recent_trauma,
    recent_surgery: saved.recent_surgery,
    symptom_codes: saved.symptom_codes,
    symptoms_note: saved.symptoms_note ?? '',
    factor_codes: saved.factor_codes,
    aggravating_note: saved.aggravating_note ?? '',
    relieving_note: saved.relieving_note ?? '',
    confounder_codes: saved.confounder_codes,
    given: saved.medications.map((use) => ({
      class_code: use.class_code,
      name: use.name ?? '',
      hours_since_last_dose: use.hours_since_last_dose != null ? String(use.hours_since_last_dose) : '',
    })),
    functional_impact: Object.fromEntries(
      Object.entries(saved.functional_impact).filter(([, score]) => score !== null && score !== undefined),
    ) as FunctionalImpact,
    vitals: Object.fromEntries(
      VITALS.map((vital) => {
        const value = saved.measurement?.[vital.key];
        return [vital.key, value === null || value === undefined ? '' : String(value)];
      }),
    ) as Record<VitalKey, string>,
    nrs: saved.self_report,
    self_report_note: saved.self_report_detail?.note ?? '',
  };
}

const number = (value: string): number | null => {
  const trimmed = value.trim();
  if (trimmed === '') return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
};

const toggle = (list: string[], value: string): string[] =>
  list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];

export const AssessmentForm: React.FC = () => {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { id: editId } = useParams<{ id: string }>();
  const { user } = useSession();
  const labels = useCatalogLabels();

  const [step, setStep] = useState(0);
  const [patientId, setPatientId] = useState<string | null>(params.get('patient'));
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [record, setRecord] = useState<RecordDraft>(EMPTY_RECORD);
  const [recordErrors, setRecordErrors] = useState<PatientFormErrors>({});
  const [recordDirty, setRecordDirty] = useState(false);
  const [assessment, setAssessment] = useState<AssessmentDetail | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [seeded, setSeeded] = useState(false);

  const existing = useQuery<AssessmentDetail>(editId ? `/api/assessments/${editId}` : null);
  const patients = useQuery<Page<PatientSummary>>(editId ? null : '/api/patients?limit=100');
  const patient = useQuery<PatientDetail>(patientId ? `/api/patients/${patientId}` : null);
  const qualities = useQuery<PainQuality[]>('/api/pain-qualities');
  const symptoms = useQuery<Symptom[]>('/api/symptoms');
  const factors = useQuery<PainFactor[]>('/api/pain-factors');
  const confounders = useQuery<Confounder[]>('/api/confounders');
  const medicationClasses = useQuery<MedicationClass[]>('/api/medication-classes');
  const diseases = useQuery<Disease[]>('/api/diseases');

  // Editing: the saved assessment seeds the draft once, then the form owns it.
  useEffect(() => {
    const saved = existing.data;
    if (!saved || seeded) return;
    if (saved.status === 'VALIDATED') {
      navigate(`/assessments/${saved.id}`, { replace: true });
      return;
    }
    setAssessment(saved);
    setPatientId(saved.patient_id);
    setDraft(draftFrom(saved));
    setSeeded(true);
  }, [existing.data, seeded, navigate]);

  useEffect(() => {
    if (patient.data) {
      setRecord(recordFrom(patient.data));
      setRecordDirty(false);
      setRecordErrors({});
    }
  }, [patient.data]);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((state) => ({ ...state, [key]: value }));
  const setRecordPart = (changes: Partial<RecordDraft>) => {
    setRecord((state) => ({ ...state, ...changes }));
    setRecordDirty(true);
  };

  const body = useCallback(() => {
    const measurement = Object.fromEntries(VITALS.map((vital) => [vital.key, number(draft.vitals[vital.key])]));
    const measured = Object.values(measurement).some((value) => value !== null);
    const duration = number(draft.duration_value);
    return {
      onset: draft.onset,
      duration_value: duration,
      duration_unit: duration === null ? null : draft.duration_unit,
      pattern: draft.pattern,
      course: draft.course,
      radiates: draft.radiates,
      radiation_description: draft.radiates ? draft.radiation_description.trim() || null : null,
      ...draft.timing,
      recent_trauma: draft.recent_trauma,
      recent_surgery: draft.recent_surgery,
      anatomical_sites: draft.anatomical_sites,
      quality_codes: draft.quality_codes,
      symptom_codes: draft.symptom_codes,
      symptoms_note: draft.symptoms_note.trim() || null,
      factor_codes: draft.factor_codes,
      aggravating_note: draft.aggravating_note.trim() || null,
      relieving_note: draft.relieving_note.trim() || null,
      confounder_codes: draft.confounder_codes,
      medications: draft.given.map((use) => ({
        class_code: use.class_code,
        name: use.name.trim() || null,
        hours_since_last_dose: number(use.hours_since_last_dose),
        dose_category: 'UNKNOWN',
        frequency: 'UNKNOWN',
        pain_effect: 'UNKNOWN',
        sedation_effect: 'UNKNOWN',
      })),
      functional_impact: draft.functional_impact,
      measurement: measured ? measurement : null,
      self_report:
        draft.nrs === null
          ? null
          : { nrs: draft.nrs, scale_code: 'NRS', note: draft.self_report_note.trim() || null },
    };
  }, [draft]);

  /**
   * The assessment row is created the moment a patient is chosen, so the camera clip and
   * the amplifier recording have something to be filed against. Every later step amends
   * the same row; an assessment abandoned halfway is a draft, not nothing.
   */
  const save = useCallback(async (): Promise<AssessmentDetail | null> => {
    if (!patientId) return null;
    setFailure(null);
    try {
      const saved = assessment
        ? await request<AssessmentDetail>(`/api/assessments/${assessment.id}`, { method: 'PATCH', body: body() })
        : await request<AssessmentDetail>('/api/assessments', { method: 'POST', body: { patient_id: patientId, ...body() } });
      setAssessment(saved);
      setSavedAt(new Date());
      return saved;
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The assessment could not be saved.');
      return null;
    }
  }, [assessment, body, patientId]);

  const saveRecord = useCallback(async (): Promise<boolean> => {
    if (!patientId) return false;
    const errors = validatePatient(record.fields);
    setRecordErrors(errors);
    if (Object.keys(errors).length > 0) {
      setFailure('The patient block has fields that need attention.');
      return false;
    }
    setFailure(null);
    try {
      await request<PatientDetail>(`/api/patients/${patientId}`, {
        method: 'PATCH',
        body: {
          ...patientPayload(record.fields),
          condition_codes: record.condition_codes,
          medications: record.medications
            .filter((entry) => entry.name.trim())
            .map((entry) => ({
              name: entry.name.trim(),
              dose: entry.dose.trim() || null,
              frequency: entry.frequency.trim() || null,
              is_analgesic: entry.is_analgesic,
            })),
          allergies: record.allergies.trim() || null,
          medical_history: record.medical_history.trim() || null,
          previous_surgeries: record.previous_surgeries.trim() || null,
        },
      });
      setRecordDirty(false);
      patient.reload();
      return true;
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The patient record could not be saved.');
      return false;
    }
  }, [patient, patientId, record]);

  const go = useCallback(
    async (target: number) => {
      if (target === step || !patientId) return;
      setBusy(true);
      let ok = true;
      if (recordDirty) ok = await saveRecord();
      if (ok) {
        const saved = await save();
        ok = saved !== null;
      }
      setBusy(false);
      if (ok) setStep(target);
    },
    [patientId, recordDirty, save, saveRecord, step],
  );

  const compute = useCallback(async () => {
    setBusy(true);
    const saved = await save();
    if (!saved) {
      setBusy(false);
      return;
    }
    try {
      setAssessment(await request<AssessmentDetail>(`/api/assessments/${saved.id}/predict`, { method: 'POST' }));
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The estimate could not be made.');
    } finally {
      setBusy(false);
    }
  }, [save]);

  const validate = useCallback(async () => {
    if (!assessment) return;
    setBusy(true);
    try {
      await request(`/api/assessments/${assessment.id}/validate`, { method: 'POST', body: { agreement: 'AGREE' } });
      navigate(`/assessments/${assessment.id}`);
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The assessment was not validated.');
      setBusy(false);
    }
  }, [assessment, navigate]);

  const finish = useCallback(async () => {
    setBusy(true);
    const saved = await save();
    setBusy(false);
    if (saved) navigate(`/assessments/${saved.id}`);
  }, [navigate, save]);

  const exportPdf = useCallback(async () => {
    if (!assessment) return;
    try {
      await download(`/api/reports/${assessment.id}/generate`, 'pain-assessment.pdf');
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The PDF could not be generated.');
    }
  }, [assessment]);

  const prediction = assessment?.prediction ?? null;
  const worseWith = (factors.data ?? []).filter((entry) => entry.kind === 'AGGRAVATING');
  const betterWith = (factors.data ?? []).filter((entry) => entry.kind === 'RELIEVING');
  const symptomGroups = useMemo(() => {
    const groups = new Map<string, Symptom[]>();
    for (const entry of symptoms.data ?? []) {
      const list = groups.get(entry.group) ?? [];
      list.push(entry);
      groups.set(entry.group, list);
    }
    return [...groups.entries()];
  }, [symptoms.data]);
  const classLabel = labels.medicationClass;
  const bmi = useMemo(() => {
    const weight = number(draft.vitals.weight_kg);
    const height = number(draft.vitals.height_cm);
    if (weight === null || height === null || height <= 0) return null;
    return weight / (height / 100) ** 2;
  }, [draft.vitals.weight_kg, draft.vitals.height_cm]);
  const completeness = assessment?.completeness ?? null;
  const missing = assessment?.missing_fields ?? [];
  const canValidate = user?.role === 'DOCTOR' && Boolean(prediction) && !prediction?.refused;

  if (editId && existing.error) {
    return (
      <Card className="p-6 text-[13px] text-danger">
        That assessment could not be opened: {existing.error}
      </Card>
    );
  }

  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="mb-1 text-xs text-mute">
            Step {step + 1} of {STEPS.length}
          </div>
          <h1 className="text-[26px] leading-tight font-semibold text-ink">
            {editId ? 'Edit assessment' : 'New assessment'}
          </h1>
          <p className="mt-1 text-[13px] text-mute">
            Answer what you can. Empty optional fields are recorded as "None recorded".
          </p>
        </div>
        <Button variant="ghost" onClick={() => navigate(assessment ? `/assessments/${assessment.id}` : '/assessments')}>
          {assessment ? 'Close' : 'Cancel'}
        </Button>
      </div>

      {failure && (
        <Card className="flex items-start gap-2.5 border-danger/30 bg-danger/8 p-4">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <p className="text-[12px] leading-relaxed text-soft">{failure}</p>
        </Card>
      )}

      {patient.error && (
        <Card className="flex flex-wrap items-center justify-between gap-3 border-danger/30 bg-danger/8 p-4">
          <p className="text-[12px] text-soft">The patient record could not be loaded: {patient.error}</p>
          <Button size="sm" onClick={() => patient.reload()}>
            Try again
          </Button>
        </Card>
      )}

      {assessment && <WarningList warnings={assessment.warnings} />}

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
          <div className="flex min-w-0 items-center gap-3">
            <Tile tone="accent" className="h-9 w-9 rounded-lg">
              {patient.data ? patient.data.code.slice(-3) : '?'}
            </Tile>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[14px] font-semibold text-ink">
                  {patient.data?.display_name ?? 'No patient selected'}
                </span>
                {assessment && (
                  <Pill tone="neutral" size="xs">
                    {assessment.status.toLowerCase()}
                  </Pill>
                )}
              </div>
              <p className="truncate text-[11px] text-mute">
                {patient.data
                  ? [patient.data.code, patient.data.age !== null ? `${patient.data.age} years` : null, patient.data.ward]
                      .filter(Boolean)
                      .join(' · ')
                  : 'Pick a patient to begin'}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-3 text-[11px]">
            {savedAt && (
              <span className="inline-flex items-center gap-1.5 font-medium text-ok">
                <CloudCheck className="h-3.5 w-3.5" />
                Saved {savedAt.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
            {user && (
              <Pill tone="neutral" size="xs">
                {user.display_name}
              </Pill>
            )}
          </div>
        </div>
        <div className="border-t border-hairline pt-3">
          <Stepper
            steps={STEPS}
            current={step}
            reach={patientId ? STEPS.length - 1 : 0}
            onJump={(target) => void go(target)}
          />
        </div>
      </Card>

      <div className={cx('grid grid-cols-1 gap-4', !WIDE_STEPS.has(step) && 'xl:grid-cols-[1fr_320px]')}>
        <div className="space-y-4">
          {step === 0 && (
            <>
              <Card className="space-y-5 p-5">
                <CardHead
                  title="Patient"
                  sub={
                    editId
                      ? 'The record this assessment belongs to. Corrections made here are saved to the record.'
                      : 'Pick the patient. Corrections made here are saved to the record, not just to this visit.'
                  }
                />
                {!editId && (
                  <div className="space-y-1.5">
                    <span className="block text-xs font-medium text-soft">Patient</span>
                    <Select
                      label="Select patient"
                      className="w-full [&>button]:w-full sm:max-w-sm"
                      searchable
                      options={(patients.data?.items ?? []).map((entry) => ({
                        value: entry.id,
                        label: entry.display_name,
                        hint: `${entry.code}${entry.ward ? ` · ${entry.ward}` : ''}`,
                      }))}
                      value={patientId}
                      onChange={(value) => {
                        setPatientId(value);
                        setAssessment(null);
                        setDraft(EMPTY);
                      }}
                    />
                    {patients.data && patients.data.items.length === 0 && (
                      <p className="text-[11.5px] text-mute">
                        No patients yet. Register one from the Patients screen first.
                      </p>
                    )}
                  </div>
                )}
                {patient.data && (
                  <div className="space-y-4 border-t border-hairline pt-4">
                    <PatientFields
                      values={record.fields}
                      errors={recordErrors}
                      code={patient.data.code}
                      onChange={(fields) => setRecordPart({ fields })}
                    />
                    <div className="flex flex-wrap items-center gap-3">
                      <Button icon={<Save className="h-3.5 w-3.5" />} disabled={busy || !recordDirty} onClick={() => void saveRecord()}>
                        Save to patient record
                      </Button>
                      {!recordDirty && <span className="text-[11px] text-faint">Nothing unsaved.</span>}
                    </div>
                  </div>
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Assessing clinician" sub="Taken from the signed-in account." />
                <dl className="grid grid-cols-1 gap-x-8 gap-y-2 sm:grid-cols-2">
                  <Line label="Name" value={assessment?.recorded_by?.display_name ?? user?.display_name ?? ''} />
                  <Line label="Speciality" value={(assessment?.recorded_by ?? user)?.speciality || 'None recorded'} />
                  <Line label="Registration number" value={(assessment?.recorded_by ?? user)?.registration_number || 'None recorded'} />
                  <Line label="Validated" value="Not validated" />
                </dl>
                <p className="text-[11px] text-faint">
                  Speciality and registration number are edited in Settings. Only a doctor can
                  validate, from the Review step or the assessment page.
                </p>
              </Card>
            </>
          )}

          {step === SITE_STEP && (
            <SitePicker
              sites={draft.anatomical_sites}
              onChange={(sites) => set('anatomical_sites', sites)}
              qualities={qualities.data ?? []}
            />
          )}

          {step === 2 && (
            <>
              <Card className="space-y-4 p-5">
                <CardHead title="Character" sub="What the pain feels like. Choose everything that applies." />
                <div className="flex flex-wrap gap-1.5">
                  {(qualities.data ?? []).map((entry) => (
                    <Choice
                      key={entry.code}
                      kind="check"
                      checked={draft.quality_codes.includes(entry.code)}
                      onClick={() => set('quality_codes', toggle(draft.quality_codes, entry.code))}
                    >
                      {entry.label}
                    </Choice>
                  ))}
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Onset, duration, pattern and course" />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Labelled label="Onset">
                    <Segmented
                      size="md"
                      className="w-full"
                      options={ONSET_OPTIONS}
                      value={draft.onset}
                      onChange={(value) => set('onset', value)}
                    />
                  </Labelled>
                  <Labelled label="Duration">
                    <div className="flex gap-2">
                      <TextField
                        type="number"
                        min={0}
                        step="any"
                        inputMode="decimal"
                        value={draft.duration_value}
                        onChange={(event) => set('duration_value', event.target.value)}
                        className="flex-1"
                      />
                      <Select
                        label="Unit"
                        className="shrink-0 [&>button]:h-11"
                        clearable={false}
                        options={DURATION_UNITS.map((unit) => ({
                          value: unit.value,
                          label: number(draft.duration_value) === 1 ? unit.singular : unit.plural,
                        }))}
                        value={draft.duration_unit}
                        onChange={(value) => set('duration_unit', (value as DurationUnit | null) ?? 'hours')}
                      />
                    </div>
                    <p className="text-[11px] text-faint">
                      {number(draft.duration_value) === null
                        ? 'Leave empty if not known.'
                        : durationLabel(number(draft.duration_value), draft.duration_unit)}
                    </p>
                  </Labelled>
                  <Labelled label="Pattern">
                    <Segmented
                      size="md"
                      className="w-full"
                      options={PATTERN_OPTIONS}
                      value={draft.pattern}
                      onChange={(value) => set('pattern', value)}
                    />
                  </Labelled>
                  <Labelled label="Course since onset">
                    <Segmented
                      size="md"
                      className="w-full"
                      options={COURSE_OPTIONS}
                      value={draft.course}
                      onChange={(value) => set('course', value)}
                    />
                  </Labelled>
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Radiation" sub="Whether it travels from where it starts. Recorded as “None reported” when it does not." />
                <Toggle checked={draft.radiates} onChange={(value) => set('radiates', value)} label="The pain travels" />
                {draft.radiates && (
                  <Note
                    label="Where it travels"
                    value={draft.radiation_description}
                    onChange={(value) => set('radiation_description', value)}
                  />
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Timing" sub="When it is felt. Nothing chosen is recorded as “No particular timing recorded”." />
                <div className="flex flex-wrap gap-1.5">
                  {TIMINGS.map((entry) => (
                    <Choice
                      key={entry.key}
                      kind="check"
                      checked={draft.timing[entry.key]}
                      onClick={() => set('timing', { ...draft.timing, [entry.key]: !draft.timing[entry.key] })}
                    >
                      {entry.label}
                    </Choice>
                  ))}
                </div>
                <div className="flex flex-wrap gap-1.5 border-t border-hairline pt-4">
                  <Choice kind="check" checked={draft.recent_trauma} onClick={() => set('recent_trauma', !draft.recent_trauma)}>
                    Recent trauma
                  </Choice>
                  <Choice kind="check" checked={draft.recent_surgery} onClick={() => set('recent_surgery', !draft.recent_surgery)}>
                    Recent surgery
                  </Choice>
                </div>
              </Card>
            </>
          )}

          {step === 3 && (
            <>
              <Card className="space-y-4 p-5">
                <CardHead title="Associated symptoms" sub="What else the patient reports right now. Add anything the list does not cover below." />
                {symptomGroups.map(([group, entries]) => (
                  <div key={group} className="space-y-1.5">
                    <p className="eyebrow">{group.toLowerCase()}</p>
                    <div className="flex flex-wrap gap-1.5">
                      {entries.map((entry) => (
                        <Choice
                          key={entry.code}
                          kind="check"
                          checked={draft.symptom_codes.includes(entry.code)}
                          onClick={() => set('symptom_codes', toggle(draft.symptom_codes, entry.code))}
                        >
                          {entry.label}
                        </Choice>
                      ))}
                    </div>
                  </div>
                ))}
                <Note label="Other symptoms" value={draft.symptoms_note} onChange={(value) => set('symptoms_note', value)} />
              </Card>

              <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                <Card className="space-y-4 p-5">
                  <CardHead title="Worse with" />
                  <div className="flex flex-wrap gap-1.5">
                    {worseWith.map((entry) => (
                      <Choice
                        key={entry.code}
                        kind="check"
                        checked={draft.factor_codes.includes(entry.code)}
                        onClick={() => set('factor_codes', toggle(draft.factor_codes, entry.code))}
                      >
                        {entry.label}
                      </Choice>
                    ))}
                  </div>
                  <Note label="Other" value={draft.aggravating_note} onChange={(value) => set('aggravating_note', value)} />
                </Card>
                <Card className="space-y-4 p-5">
                  <CardHead title="Better with" />
                  <div className="flex flex-wrap gap-1.5">
                    {betterWith.map((entry) => (
                      <Choice
                        key={entry.code}
                        kind="check"
                        checked={draft.factor_codes.includes(entry.code)}
                        onClick={() => set('factor_codes', toggle(draft.factor_codes, entry.code))}
                      >
                        {entry.label}
                      </Choice>
                    ))}
                  </div>
                  <Note label="Other" value={draft.relieving_note} onChange={(value) => set('relieving_note', value)} />
                </Card>
              </div>

              <Card className="space-y-4 p-5">
                <CardHead title="Recorded context" sub="What is moving the vital signs other than the pain." />
                <div className="space-y-2">
                  {(confounders.data ?? []).map((entry) => {
                    const on = draft.confounder_codes.includes(entry.code);
                    return (
                      <button
                        key={entry.code}
                        type="button"
                        onClick={() => set('confounder_codes', toggle(draft.confounder_codes, entry.code))}
                        className={cx(
                          'flex w-full items-start gap-3 rounded-[10px] border px-3 py-2.5 text-left transition-colors',
                          on ? 'border-accent-edge bg-accent-wash' : 'border-hairline hover:border-hairline-strong',
                        )}
                      >
                        <span
                          className={cx(
                            'mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border',
                            on ? 'border-transparent bg-clinical text-white dark:bg-accent dark:text-[#04121f]' : 'border-hairline-strong',
                          )}
                        >
                          {on && <Check className="h-3 w-3" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[13px] font-medium text-ink">{entry.label}</span>
                          <span className="block text-[11.5px] leading-relaxed text-mute">{entry.note}</span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Chronic conditions" sub="Held on the patient record. Read by the consistency checks and the rule layer." />
                <div className="flex flex-wrap gap-1.5">
                  {(diseases.data ?? []).map((entry) => (
                    <Choice
                      key={entry.code}
                      kind="check"
                      checked={record.condition_codes.includes(entry.code)}
                      onClick={() => setRecordPart({ condition_codes: toggle(record.condition_codes, entry.code) })}
                    >
                      {entry.label}
                    </Choice>
                  ))}
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead
                  title="Current medication"
                  sub="The patient's standing medication, held on the record."
                  action={
                    <Button
                      size="sm"
                      icon={<Plus className="h-3.5 w-3.5" />}
                      onClick={() =>
                        setRecordPart({
                          medications: [...record.medications, { name: '', dose: '', frequency: '', is_analgesic: false }],
                        })
                      }
                    >
                      Add
                    </Button>
                  }
                />
                {record.medications.length === 0 ? (
                  <p className="text-[12.5px] text-mute">None recorded.</p>
                ) : (
                  <ul className="space-y-2">
                    {record.medications.map((entry, index) => (
                      <li key={index} className="grid grid-cols-1 gap-2 rounded-[10px] border border-hairline p-3 sm:grid-cols-[1fr_8rem_9rem_auto_auto] sm:items-end">
                        <TextField label="Name" value={entry.name} onChange={(event) => setRecordPart({ medications: record.medications.map((item, at) => (at === index ? { ...item, name: event.target.value } : item)) })} />
                        <TextField label="Dose" value={entry.dose} onChange={(event) => setRecordPart({ medications: record.medications.map((item, at) => (at === index ? { ...item, dose: event.target.value } : item)) })} />
                        <TextField label="Frequency" value={entry.frequency} onChange={(event) => setRecordPart({ medications: record.medications.map((item, at) => (at === index ? { ...item, frequency: event.target.value } : item)) })} />
                        <Choice kind="check" checked={entry.is_analgesic} onClick={() => setRecordPart({ medications: record.medications.map((item, at) => (at === index ? { ...item, is_analgesic: !item.is_analgesic } : item)) })}>
                          Analgesic
                        </Choice>
                        <button type="button" aria-label="Remove" onClick={() => setRecordPart({ medications: record.medications.filter((_, at) => at !== index) })} className="justify-self-end rounded-md p-2 text-faint transition-colors hover:bg-danger/10 hover:text-danger">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead
                  title="Given for this pain"
                  sub="Analgesia or sedation taken for this episode. Recent doses are a confounder the estimate accounts for."
                  action={
                    <Select
                      label="Add a class"
                      size="sm"
                      searchable
                      options={(medicationClasses.data ?? [])
                        .filter((entry) => !draft.given.some((use) => use.class_code === entry.code))
                        .map((entry) => ({ value: entry.code, label: entry.label }))}
                      value={null}
                      onChange={(value) => {
                        if (value) set('given', [...draft.given, { class_code: value, name: '', hours_since_last_dose: '' }]);
                      }}
                    />
                  }
                />
                {draft.given.length === 0 ? (
                  <p className="text-[12.5px] text-mute">None recorded.</p>
                ) : (
                  <ul className="space-y-2">
                    {draft.given.map((use, index) => (
                      <li key={use.class_code} className="grid grid-cols-1 gap-2 rounded-[10px] border border-hairline p-3 sm:grid-cols-[10rem_1fr_9rem_auto] sm:items-end">
                        <span className="text-[13px] font-medium text-ink">{classLabel.get(use.class_code) ?? use.class_code}</span>
                        <TextField label="Name as given" value={use.name} onChange={(event) => set('given', draft.given.map((item, at) => (at === index ? { ...item, name: event.target.value } : item)))} />
                        <TextField label="Hours since last dose" type="number" min={0} step="0.5" value={use.hours_since_last_dose} onChange={(event) => set('given', draft.given.map((item, at) => (at === index ? { ...item, hours_since_last_dose: event.target.value } : item)))} />
                        <button type="button" aria-label="Remove" onClick={() => set('given', draft.given.filter((_, at) => at !== index))} className="justify-self-end rounded-md p-2 text-faint transition-colors hover:bg-danger/10 hover:text-danger">
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Allergies and history" sub="Held on the patient record." />
                <Note label="Allergies" value={record.allergies} onChange={(value) => setRecordPart({ allergies: value })} />
                <Note label="Relevant history" value={record.medical_history} onChange={(value) => setRecordPart({ medical_history: value })} />
                <Note label="Previous surgery" value={record.previous_surgeries} onChange={(value) => setRecordPart({ previous_surgeries: value })} />
                <div className="flex flex-wrap items-center gap-3 border-t border-hairline pt-4">
                  <Button icon={<Save className="h-3.5 w-3.5" />} disabled={busy || !recordDirty} onClick={() => void saveRecord()}>
                    Save to patient record
                  </Button>
                  {!recordDirty && <span className="text-[11px] text-faint">Nothing unsaved.</span>}
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Effect on function" sub="What the pain stops the patient doing, 0 to 4 in each domain." />
                <div className="space-y-3">
                  {FUNCTIONAL_DOMAINS.map((domain) => (
                    <div key={domain.key} className="flex flex-wrap items-center gap-3">
                      <span className="w-32 shrink-0 text-[13px] text-soft">{domain.label}</span>
                      <Segmented
                        options={IMPACT_WORD.map((label, score) => ({ value: String(score), label }))}
                        value={String(draft.functional_impact[domain.key] ?? '')}
                        onChange={(value) => set('functional_impact', { ...draft.functional_impact, [domain.key]: Number(value) })}
                      />
                    </div>
                  ))}
                </div>
              </Card>
            </>
          )}

          {step === 4 && (
            <Card className="space-y-5 p-5">
              <CardHead
                title="Self-report"
                sub="The patient's own score on the 0 to 10 numeric rating scale. It is stored on its own, never used as an input to the AI, and shown beside the estimate for comparison."
              />
              <NrsScale value={draft.nrs} onChange={(value) => set('nrs', value)} />
              {draft.nrs !== null && (
                <button type="button" onClick={() => set('nrs', null)} className="text-[11.5px] text-mute underline hover:text-ink">
                  Clear the score
                </button>
              )}
              <Note label="Note on the score" value={draft.self_report_note} onChange={(value) => set('self_report_note', value)} />
            </Card>
          )}

          {step === 5 && (
            <Card className="space-y-4 p-5">
              <CardHead title="Physiology" sub="Read off the monitor or taken at the bedside. Vitals are context for the estimate, not pain measures." />
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
                {VITALS.map((vital) => (
                  <TextField
                    key={vital.key}
                    label={vital.label}
                    type="number"
                    step="any"
                    inputMode="decimal"
                    trailing={<span className="text-[11px] text-faint">{vital.unit}</span>}
                    value={draft.vitals[vital.key]}
                    onChange={(event) => set('vitals', { ...draft.vitals, [vital.key]: event.target.value })}
                  />
                ))}
              </div>
              {bmi !== null && (
                <p className="rounded-[10px] bg-sunken px-3 py-2 text-[12px] text-soft">
                  Body mass index <span className="font-semibold text-ink tabular-nums">{bmi.toFixed(1)}</span> kg/m², from the weight and height.
                </p>
              )}
            </Card>
          )}

          {step === CAMERA_STEP && (
            <BehaviourPanel patientId={patientId} assessmentId={assessment?.id ?? null} onObservation={() => setSavedAt(new Date())} />
          )}

          {step === SIGNAL_STEP && <SignalPanel patientId={patientId} reportedNrs={draft.nrs} />}

          {step === ANALYSIS_STEP && (
            <EstimatePanel prediction={prediction} selfReport={assessment?.self_report ?? draft.nrs} onRun={() => void compute()} busy={busy} />
          )}

          {step === REVIEW_STEP && (
            <>
              {assessment && patient.data ? (
                <AssessmentSummary
                  assessment={assessment}
                  patient={patient.data}
                  clinician={assessment.recorded_by ?? user}
                  labels={labels}
                />
              ) : (
                <Card className="p-6 text-[13px] text-mute">Nothing has been recorded yet. Choose a patient on the first step.</Card>
              )}
              <Card className="space-y-4 p-5">
                <CardHead title="Finish" sub="Save and close keeps it as a draft. Validation is a doctor's act and marks the assessment validated under their name." />
                {assessment && !prediction && (
                  <p className="text-[12px] text-warn">No estimate has been computed yet. It can be computed on the AI analysis step, or later from the assessment page.</p>
                )}
                <div className="flex flex-wrap gap-2">
                  <Button icon={<Save className="h-4 w-4" />} disabled={busy || !patientId} onClick={() => void finish()}>
                    Save and close
                  </Button>
                  <Button icon={<FileDown className="h-4 w-4" />} disabled={busy || !assessment} onClick={() => void exportPdf()}>
                    Export PDF
                  </Button>
                  {user?.role === 'DOCTOR' && (
                    <Button variant="primary" icon={<Check className="h-4 w-4" />} disabled={busy || !canValidate} onClick={() => void validate()}>
                      Validate
                    </Button>
                  )}
                </div>
                {user?.role === 'NURSE' && (
                  <p className="text-[11.5px] text-faint">A nurse records and estimates; a doctor validates.</p>
                )}
              </Card>
            </>
          )}

          <div className="flex items-center justify-between">
            <Button icon={<ArrowLeft className="h-4 w-4" />} disabled={step === 0 || busy} onClick={() => void go(step - 1)}>
              Back
            </Button>
            {step < STEPS.length - 1 && (
              <Button variant="primary" disabled={!patientId || busy} onClick={() => void go(step + 1)}>
                {busy ? 'Saving…' : 'Continue'}
                <ArrowRight className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {!WIDE_STEPS.has(step) && (
          <div className="space-y-4">
            <Card className="p-4">
              <CardHead title="Completeness" sub="Information available to the model" />
              {completeness === null ? (
                <p className="mt-3 text-[12px] text-mute">Measured by the server once the assessment is saved.</p>
              ) : (
                <>
                  <div className="mt-3 flex items-baseline gap-2">
                    <span className="text-[30px] leading-none font-semibold text-ink tabular-nums">{Math.round(completeness * 100)}%</span>
                    <span className="text-[12px] text-mute">complete</span>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-sunken">
                    <div
                      className="h-full rounded-full transition-[width] duration-500 ease-out"
                      style={{
                        width: `${completeness * 100}%`,
                        background: completeness > 0.8 ? 'var(--ok)' : completeness > 0.5 ? 'var(--accent)' : 'var(--warn)',
                      }}
                    />
                  </div>
                </>
              )}
              {missing.length > 0 && (
                <>
                  <p className="eyebrow mt-4 mb-2">Missing</p>
                  <ul className="space-y-1.5">
                    {missing.slice(0, 8).map((field) => (
                      <li key={field} className="flex items-center gap-2 text-[11.5px] text-mute">
                        <span className="h-1 w-1 shrink-0 rounded-full bg-warn" />
                        {field.replace(/_/g, ' ')}
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </Card>

            {draft.nrs !== null && (
              <Card className="p-4">
                <CardHead title="Reported" sub="What the patient said" />
                <div className="mt-3 flex items-center gap-4">
                  <span className="grid h-14 w-14 shrink-0 place-items-center rounded-xl text-[20px] font-semibold text-white" style={{ background: BAND_VAR[bandOf(draft.nrs)] }}>
                    {draft.nrs}
                  </span>
                  <div>
                    <p className="text-[13px] font-medium text-ink">{BAND_LABEL[bandOf(draft.nrs)]}</p>
                    <p className="mt-0.5 text-[11px] text-mute">
                      {prediction?.estimated_pain != null ? `model ${prediction.estimated_pain.toFixed(1)}, for comparison` : 'no estimate yet'}
                    </p>
                  </div>
                </div>
              </Card>
            )}

            <Card className="space-y-2 p-4">
              <CardHead title="Measured channels" sub="Optional. Skipping one is recorded as missing, not as zero." />
              <Channel icon={<Video className="h-3.5 w-3.5" />} label="Camera and voice" onClick={() => void go(CAMERA_STEP)} />
              <Channel icon={<Activity className="h-3.5 w-3.5" />} label="EEG and EMG" onClick={() => void go(SIGNAL_STEP)} />
            </Card>
          </div>
        )}
      </div>
    </>
  );
};

const Labelled: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="space-y-1.5">
    <span className="block text-xs font-medium text-soft">{label}</span>
    {children}
  </div>
);

const Line: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-4 border-b border-hairline py-1.5">
    <dt className="shrink-0 text-[12px] text-mute">{label}</dt>
    <dd className="min-w-0 text-right text-[13px] font-medium text-ink">{value}</dd>
  </div>
);

const Note: React.FC<{ label: string; value: string; onChange: (value: string) => void }> = ({ label, value, onChange }) => (
  <label className="block space-y-1.5">
    <span className="block text-xs font-medium text-soft">{label}</span>
    <textarea
      value={value}
      rows={2}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-[10px] border border-hairline bg-surface p-3 text-[13px] text-ink outline-none transition-colors focus:border-accent"
    />
  </label>
);

const Channel: React.FC<{ icon: React.ReactNode; label: string; onClick: () => void }> = ({ icon, label, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="flex w-full items-center gap-2.5 rounded-[10px] border border-hairline px-3 py-2 text-left transition-colors hover:border-hairline-strong"
  >
    <span className="shrink-0 text-faint">{icon}</span>
    <span className="min-w-0 flex-1 truncate text-[12.5px] text-soft">{label}</span>
  </button>
);
