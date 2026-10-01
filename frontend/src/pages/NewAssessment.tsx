import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Activity, ArrowLeft, ArrowRight, BrainCircuit, Check, CloudCheck, Plus, Save,
  Sparkles, Trash2, TriangleAlert, Video,
} from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type {
  AnatomicalSiteIn, AssessmentDetail, Confounder, Course, Disease, FunctionalImpact,
  MedicationClass, MedicationUse, Onset, OnsetSpeed, PainFactor, PainQuality, PainScale,
  PainType, Page, Pattern, PatientDetail, PatientSummary, ClinicalQuestion,
  ProfileCatalogue, Sex, SmokingStatus, Symptom,
} from '../api/types';
import { useSession } from '../auth/session';
import { SitePicker } from '../anatomy/SitePicker';
import { BehaviourPanel } from '../capture/BehaviourPanel';
import { SignalPanel } from '../signals/SignalPanel';
import { Button } from '../ui/Button';
import { Card, CardHead, EmptyState } from '../ui/Card';
import { Select } from '../ui/Dropdown';
import { Choice, TextField, Toggle } from '../ui/Field';
import { Stepper } from '../ui/Nav';
import { NrsScale } from '../ui/NrsScale';
import { Pill, Tile } from '../ui/Pill';
import { Segmented } from '../ui/Segmented';
import { bandOf, BAND_LABEL, BAND_VAR, Gauge } from '../ui/charts';
import { cx } from '../lib/cx';

const STEPS = [
  { label: 'Patient' },
  { label: 'History' },
  { label: 'Site' },
  { label: 'Pain' },
  { label: 'Intensity' },
  { label: 'Symptoms' },
  { label: 'Treatment' },
  { label: 'Physiology' },
  { label: 'Camera & voice' },
  { label: 'EEG & EMG' },
  { label: 'Questions' },
  { label: 'AI analysis' },
  { label: 'Review' },
];

const ANALYSIS_STEP = 11;
const REVIEW_STEP = 12;

const SEX_LABEL: Record<Sex, string> = {
  F: 'Female',
  M: 'Male',
  OTHER: 'Other',
  UNDISCLOSED: 'Not disclosed',
};

const SMOKING_LABEL: Record<SmokingStatus, string> = {
  NEVER: 'Never smoked',
  FORMER: 'Former smoker',
  CURRENT: 'Current smoker',
  UNKNOWN: 'Not known',
};

const ONSET: { value: Onset; label: string }[] = [
  { value: 'SUDDEN', label: 'Sudden' },
  { value: 'GRADUAL', label: 'Gradual' },
  { value: 'UNKNOWN', label: 'Not known' },
];

const ONSET_SPEED: { value: OnsetSpeed; label: string }[] = [
  { value: 'SECONDS', label: 'Over seconds' },
  { value: 'MINUTES', label: 'Over minutes' },
  { value: 'HOURS', label: 'Over hours' },
  { value: 'DAYS', label: 'Over days' },
  { value: 'WEEKS_OR_MORE', label: 'Over weeks or longer' },
  { value: 'UNKNOWN', label: 'Not known' },
];

const PATTERN: { value: Pattern; label: string }[] = [
  { value: 'CONSTANT', label: 'Constant' },
  { value: 'INTERMITTENT', label: 'Comes and goes' },
  { value: 'EPISODIC', label: 'In distinct episodes' },
  { value: 'UNKNOWN', label: 'Not known' },
];

const COURSE: { value: Course; label: string }[] = [
  { value: 'IMPROVING', label: 'Improving' },
  { value: 'STABLE', label: 'Unchanged' },
  { value: 'WORSENING', label: 'Worsening' },
  { value: 'PROGRESSIVE', label: 'Progressive' },
  { value: 'UNKNOWN', label: 'Not known' },
];

const DOSE_CATEGORY = [
  { value: 'LOW', label: 'Low' },
  { value: 'STANDARD', label: 'Standard' },
  { value: 'HIGH', label: 'High' },
  { value: 'UNKNOWN', label: 'Not known' },
] as const;

const DOSE_FREQUENCY = [
  { value: 'SINGLE', label: 'Single dose' },
  { value: 'DAILY', label: 'Once daily' },
  { value: 'TWICE_DAILY', label: 'Twice daily' },
  { value: 'THREE_TIMES_DAILY', label: 'Three times daily' },
  { value: 'FOUR_TIMES_DAILY', label: 'Four times daily' },
  { value: 'AS_NEEDED', label: 'As needed' },
  { value: 'CONTINUOUS', label: 'Continuous' },
  { value: 'UNKNOWN', label: 'Not known' },
] as const;

const PAIN_EFFECT = [
  { value: 'NONE', label: 'No relief' },
  { value: 'PARTIAL', label: 'Partial relief' },
  { value: 'GOOD', label: 'Good relief' },
  { value: 'UNKNOWN', label: 'Not known' },
] as const;

const SEDATION_EFFECT = [
  { value: 'NONE', label: 'Not sedated' },
  { value: 'MILD', label: 'Mildly sedated' },
  { value: 'MARKED', label: 'Markedly sedated' },
  { value: 'UNKNOWN', label: 'Not known' },
] as const;

/** The functional domains the API scores 0–4, with the words for each step. */
const FUNCTIONAL_DOMAINS: { key: keyof FunctionalImpact; label: string }[] = [
  { key: 'mobility', label: 'Mobility' },
  { key: 'sleep', label: 'Sleep' },
  { key: 'work', label: 'Work' },
  { key: 'daily_activity', label: 'Daily activities' },
  { key: 'self_care', label: 'Self-care' },
];

const IMPACT_WORD = ['None', 'Slight', 'Moderate', 'Severe', 'Unable'];

/** Vitals, with the unit and the plausible span the API will reject outside of. */
const VITALS = [
  { key: 'hr', label: 'Heart rate', unit: 'bpm', placeholder: '76' },
  { key: 'resp_rate', label: 'Respiratory rate', unit: '/min', placeholder: '16' },
  { key: 'sbp', label: 'Systolic pressure', unit: 'mmHg', placeholder: '124' },
  { key: 'dbp', label: 'Diastolic pressure', unit: 'mmHg', placeholder: '78' },
  { key: 'spo2', label: 'Oxygen saturation', unit: '%', placeholder: '98' },
  { key: 'temperature_c', label: 'Temperature', unit: '°C', placeholder: '37.1' },
  { key: 'glucose_mmol', label: 'Blood glucose', unit: 'mmol/L', placeholder: '5.4' },
  { key: 'weight_kg', label: 'Weight', unit: 'kg', placeholder: '72' },
  { key: 'height_cm', label: 'Height', unit: 'cm', placeholder: '174' },
] as const;

type VitalKey = (typeof VITALS)[number]['key'];

interface Draft {
  onset: Onset;
  onset_speed: OnsetSpeed;
  started_at: string;
  duration_hours: string;
  pattern: Pattern;
  course: Course;
  recurrent: boolean;
  episodes_per_day: string;
  episode_minutes: string;
  night_pain: boolean;
  morning_pain: boolean;
  afternoon_pain: boolean;
  evening_pain: boolean;
  variable_timing: boolean;
  pain_after_activity: boolean;
  pain_at_rest: boolean;
  functional_impact: FunctionalImpact;
  radiates: boolean;
  radiation_description: string;
  radiation_numbness: boolean;
  radiation_tingling: boolean;
  radiation_weakness: boolean;
  recent_trauma: boolean;
  recent_surgery: boolean;
  profile_code: string | null;
  profile_modifiers: string[];
  pregnancy_trimester: number | null;
  expected_pain: boolean;
  anatomical_sites: AnatomicalSiteIn[];
  quality_codes: string[];
  symptom_codes: string[];
  factor_codes: string[];
  confounder_codes: string[];
  medications: MedicationUse[];
  answers: Record<string, unknown>;
  vitals: Record<VitalKey, string>;
  scale_code: string;
  nrs: number | null;
  raw_score: string;
  scale_items: Record<string, number>;
  self_report_note: string;
}

const EMPTY_VITALS = Object.fromEntries(VITALS.map((vital) => [vital.key, ''])) as Record<
  VitalKey,
  string
>;

const EMPTY: Draft = {
  onset: 'UNKNOWN',
  onset_speed: 'UNKNOWN',
  started_at: '',
  duration_hours: '',
  pattern: 'UNKNOWN',
  course: 'UNKNOWN',
  recurrent: false,
  episodes_per_day: '',
  episode_minutes: '',
  night_pain: false,
  morning_pain: false,
  afternoon_pain: false,
  evening_pain: false,
  variable_timing: false,
  pain_after_activity: false,
  pain_at_rest: false,
  functional_impact: {},
  radiates: false,
  radiation_description: '',
  radiation_numbness: false,
  radiation_tingling: false,
  radiation_weakness: false,
  recent_trauma: false,
  recent_surgery: false,
  profile_code: null,
  profile_modifiers: [],
  pregnancy_trimester: null,
  expected_pain: false,
  anatomical_sites: [],
  quality_codes: [],
  symptom_codes: [],
  factor_codes: [],
  confounder_codes: [],
  medications: [],
  answers: {},
  vitals: EMPTY_VITALS,
  scale_code: 'NRS',
  nrs: null,
  raw_score: '',
  scale_items: {},
  self_report_note: '',
};

/** The patient-level facts this form can amend, kept apart from the assessment's own. */
interface Record_ {
  given_name: string;
  family_name: string;
  phone: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  sex: Sex;
  birth_date: string;
  ward: string;
  smoking_status: SmokingStatus;
  condition_codes: string[];
  allergies: string;
  medical_history: string;
  previous_surgeries: string;
  family_history: string;
  lifestyle_notes: string;
}

const EMPTY_RECORD: Record_ = {
  given_name: '',
  family_name: '',
  phone: '',
  emergency_contact_name: '',
  emergency_contact_phone: '',
  sex: 'UNDISCLOSED',
  birth_date: '',
  ward: '',
  smoking_status: 'UNKNOWN',
  condition_codes: [],
  allergies: '',
  medical_history: '',
  previous_surgeries: '',
  family_history: '',
  lifestyle_notes: '',
};

const number = (value: string): number | null => {
  const trimmed = value.trim();
  if (trimmed === '') return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
};

const toggle = (list: string[], value: string): string[] =>
  list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];

export const NewAssessment: React.FC = () => {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const { user } = useSession();

  const [step, setStep] = useState(0);
  const [patientId, setPatientId] = useState<string | null>(params.get('patient'));
  const [draft, setDraft] = useState<Draft>(EMPTY);
  const [record, setRecord] = useState<Record_>(EMPTY_RECORD);
  const [assessment, setAssessment] = useState<AssessmentDetail | null>(null);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [recordSaved, setRecordSaved] = useState<string | null>(null);

  // --- reference data ------------------------------------------------------------------
  const patients = useQuery<Page<PatientSummary>>('/api/patients?limit=100');
  const patient = useQuery<PatientDetail>(patientId ? `/api/patients/${patientId}` : null);
  const qualities = useQuery<PainQuality[]>('/api/catalog/pain-qualities');
  const painTypes = useQuery<PainType[]>('/api/catalog/pain-types');
  const symptoms = useQuery<Symptom[]>('/api/catalog/symptoms');
  const factors = useQuery<PainFactor[]>('/api/catalog/pain-factors');
  const confounders = useQuery<Confounder[]>('/api/catalog/confounders');
  const medicationClasses = useQuery<MedicationClass[]>('/api/catalog/medication-classes');
  const diseases = useQuery<Disease[]>('/api/catalog/diseases');
  const profiles = useQuery<ProfileCatalogue>('/api/catalog/patient-profiles');

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((state) => ({ ...state, [key]: value }));

  const setVital = (key: VitalKey, value: string) =>
    setDraft((state) => ({ ...state, vitals: { ...state.vitals, [key]: value } }));

  // Seed the editable patient block from the record once it lands.
  useEffect(() => {
    const data = patient.data;
    if (!data) return;
    setRecord({
      given_name: data.identity?.given_name ?? '',
      family_name: data.identity?.family_name ?? '',
      phone: data.identity?.phone ?? '',
      emergency_contact_name: data.identity?.emergency_contact_name ?? '',
      emergency_contact_phone: data.identity?.emergency_contact_phone ?? '',
      sex: data.sex,
      birth_date: data.birth_date ?? '',
      ward: data.ward ?? '',
      smoking_status: data.smoking_status,
      condition_codes: data.conditions.map((entry) => entry.disease_code),
      allergies: data.allergies ?? '',
      medical_history: data.medical_history ?? '',
      previous_surgeries: data.previous_surgeries ?? '',
      family_history: data.family_history ?? '',
      lifestyle_notes: data.lifestyle_notes ?? '',
    });
  }, [patient.data]);

  const scales = profiles.data?.scales ?? [];
  const scale = useMemo(
    () => scales.find((entry) => entry.code === draft.scale_code) ?? null,
    [scales, draft.scale_code],
  );

  /** What the patient reported, projected onto 0–10 the way the API will project it. */
  const projected = useMemo(() => {
    if (!scale || scale.code === 'NRS') return draft.nrs;
    const raw = scale.items.length
      ? Object.values(draft.scale_items).reduce((sum, value) => sum + value, 0)
      : number(draft.raw_score);
    if (raw === null) return null;
    const span = scale.maximum - scale.minimum || 1;
    return Math.round(((raw - scale.minimum) / span) * 10 * 10) / 10;
  }, [scale, draft.nrs, draft.raw_score, draft.scale_items]);

  // --- the payload the API takes --------------------------------------------------------
  const body = useCallback(() => {
    const measurement = Object.fromEntries(
      VITALS.map((vital) => [vital.key, number(draft.vitals[vital.key])]),
    );
    const measured = Object.values(measurement).some((value) => value !== null);

    const selfReport = (() => {
      if (!scale) return null;
      if (scale.code === 'NRS') {
        return draft.nrs === null
          ? null
          : {
              nrs: draft.nrs,
              scale_code: 'NRS',
              note: draft.self_report_note || null,
            };
      }
      if (scale.items.length > 0) {
        if (Object.keys(draft.scale_items).length === 0) return null;
        return {
          scale_code: scale.code,
          items: draft.scale_items,
          note: draft.self_report_note || null,
        };
      }
      const raw = number(draft.raw_score);
      return raw === null
        ? null
        : { scale_code: scale.code, raw_score: raw, note: draft.self_report_note || null };
    })();

    // A site's structure also names a pain location, so the API derives `locations` from
    // the sites rather than being told twice.
    return {
      onset: draft.onset,
      onset_speed: draft.onset_speed,
      started_at: draft.started_at ? new Date(draft.started_at).toISOString() : null,
      duration_hours: number(draft.duration_hours),
      pattern: draft.pattern,
      course: draft.course,
      recurrent: draft.recurrent,
      episodes_per_day: number(draft.episodes_per_day),
      episode_minutes: number(draft.episode_minutes),
      night_pain: draft.night_pain,
      morning_pain: draft.morning_pain,
      afternoon_pain: draft.afternoon_pain,
      evening_pain: draft.evening_pain,
      variable_timing: draft.variable_timing,
      pain_after_activity: draft.pain_after_activity,
      pain_at_rest: draft.pain_at_rest,
      functional_impact: draft.functional_impact,
      radiates: draft.radiates,
      radiation_description: draft.radiation_description || null,
      radiation_numbness: draft.radiation_numbness,
      radiation_tingling: draft.radiation_tingling,
      radiation_weakness: draft.radiation_weakness,
      recent_trauma: draft.recent_trauma,
      recent_surgery: draft.recent_surgery,
      profile_code: draft.profile_code,
      profile_modifiers: draft.profile_modifiers,
      pregnancy_trimester: draft.pregnancy_trimester,
      expected_pain: draft.expected_pain,
      anatomical_sites: draft.anatomical_sites,
      quality_codes: draft.quality_codes,
      symptom_codes: draft.symptom_codes,
      factor_codes: draft.factor_codes,
      confounder_codes: draft.confounder_codes,
      medications: draft.medications,
      answers: draft.answers,
      measurement: measured ? measurement : null,
      self_report: selfReport,
    };
  }, [draft, scale]);

  /**
   * Write the draft to the server.
   *
   * The assessment row is created the moment a patient is chosen, so the camera clip and
   * the amplifier recording have something to be filed against. Every later step amends
   * the same row rather than accumulating a form that is posted once at the end — an
   * assessment abandoned halfway is then a draft in the record, not nothing.
   */
  const save = useCallback(async (): Promise<AssessmentDetail | null> => {
    if (!patientId) return null;
    setFailure(null);
    try {
      const saved = assessment
        ? await request<AssessmentDetail>(`/api/assessments/${assessment.id}`, {
            method: 'PATCH',
            body: body(),
          })
        : await request<AssessmentDetail>('/api/assessments', {
            method: 'POST',
            body: { patient_id: patientId, ...body() },
          });
      setAssessment(saved);
      setSavedAt(new Date());
      return saved;
    } catch (cause) {
      setFailure(
        cause instanceof ApiError ? cause.message : 'The assessment could not be saved.',
      );
      return null;
    }
  }, [assessment, body, patientId]);

  const go = useCallback(
    async (target: number) => {
      if (target === step) return;
      setBusy(true);
      if (patientId && target > 0) await save();
      setBusy(false);
      setStep(target);
    },
    [patientId, save, step],
  );

  const saveRecord = useCallback(async () => {
    if (!patientId) return;
    setBusy(true);
    setFailure(null);
    try {
      await request<PatientDetail>(`/api/patients/${patientId}`, {
        method: 'PATCH',
        body: {
          identity:
            record.given_name && record.family_name
              ? {
                  given_name: record.given_name,
                  family_name: record.family_name,
                  phone: record.phone || null,
                  emergency_contact_name: record.emergency_contact_name || null,
                  emergency_contact_phone: record.emergency_contact_phone || null,
                }
              : null,
          sex: record.sex,
          birth_date: record.birth_date || null,
          ward: record.ward || null,
          smoking_status: record.smoking_status,
          condition_codes: record.condition_codes,
          allergies: record.allergies || null,
          medical_history: record.medical_history || null,
          previous_surgeries: record.previous_surgeries || null,
          family_history: record.family_history || null,
          lifestyle_notes: record.lifestyle_notes || null,
        },
      });
      patient.reload();
      setRecordSaved(new Date().toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' }));
    } catch (cause) {
      setFailure(
        cause instanceof ApiError ? cause.message : 'The patient record could not be saved.',
      );
    } finally {
      setBusy(false);
    }
  }, [patient, patientId, record]);

  const predict = useCallback(async () => {
    setBusy(true);
    const saved = await save();
    if (!saved) {
      setBusy(false);
      return;
    }
    try {
      setAssessment(
        await request<AssessmentDetail>(`/api/assessments/${saved.id}/predict`, {
          method: 'POST',
        }),
      );
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The estimate could not be made.');
    } finally {
      setBusy(false);
    }
  }, [save]);

  const sign = useCallback(async () => {
    if (!assessment) return;
    setBusy(true);
    try {
      await request(`/api/assessments/${assessment.id}/validate`, {
        method: 'POST',
        body: { agreement: 'AGREE' },
      });
      navigate('/assessments');
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The assessment was not signed.');
      setBusy(false);
    }
  }, [assessment, navigate]);

  // --- adaptive questions ---------------------------------------------------------------
  const [questions, setQuestions] = useState<ClinicalQuestion[] | null>(null);
  useEffect(() => {
    if (step !== 10 || !patientId) return;
    let cancelled = false;
    request<ClinicalQuestion[]>('/api/catalog/clinical-questions/applicable', {
      method: 'POST',
      body: {
        patient_id: patientId,
        locations: draft.anatomical_sites.map((site) => site.structure_code),
        quality_codes: draft.quality_codes,
        symptom_codes: draft.symptom_codes,
        condition_codes: record.condition_codes,
        factor_codes: draft.factor_codes,
        confounder_codes: draft.confounder_codes,
        onset: draft.onset,
        pattern: draft.pattern,
        course: draft.course,
        duration_hours: number(draft.duration_hours),
        radiates: draft.radiates,
        recent_trauma: draft.recent_trauma,
        recent_surgery: draft.recent_surgery,
        medication_classes: draft.medications.map((entry) => entry.class_code),
        functional_impact: draft.functional_impact,
        answers: draft.answers,
      },
    })
      .then((list) => {
        if (!cancelled) setQuestions(list);
      })
      .catch(() => {
        if (!cancelled) setQuestions([]);
      });
    return () => {
      cancelled = true;
    };
    // The context is read once on entering the step; re-asking on every keystroke would
    // reorder the form under the clinician's hands.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step, patientId]);

  // --- derived ---------------------------------------------------------------------------
  const prediction = assessment?.prediction ?? null;
  const bmi = useMemo(() => {
    const weight = number(draft.vitals.weight_kg);
    const height = number(draft.vitals.height_cm);
    if (weight === null || height === null || height <= 0) return null;
    return weight / (height / 100) ** 2;
  }, [draft.vitals.weight_kg, draft.vitals.height_cm]);

  const qualityLabel = useMemo(
    () => new Map((qualities.data ?? []).map((entry) => [entry.code, entry.label])),
    [qualities.data],
  );
  const symptomLabel = useMemo(
    () => new Map((symptoms.data ?? []).map((entry) => [entry.code, entry.label])),
    [symptoms.data],
  );
  const factorLabel = useMemo(
    () => new Map((factors.data ?? []).map((entry) => [entry.code, entry.label])),
    [factors.data],
  );
  const confounderLabel = useMemo(
    () => new Map((confounders.data ?? []).map((entry) => [entry.code, entry.label])),
    [confounders.data],
  );
  const diseaseLabel = useMemo(
    () => new Map((diseases.data ?? []).map((entry) => [entry.code, entry.label])),
    [diseases.data],
  );
  const classLabel = useMemo(
    () => new Map((medicationClasses.data ?? []).map((entry) => [entry.code, entry.label])),
    [medicationClasses.data],
  );

  const worseWith = (factors.data ?? []).filter((entry) => entry.kind === 'AGGRAVATING');
  const betterWith = (factors.data ?? []).filter((entry) => entry.kind === 'RELIEVING');

  const timings: { key: keyof Draft; label: string }[] = [
    { key: 'morning_pain', label: 'Morning' },
    { key: 'afternoon_pain', label: 'Afternoon' },
    { key: 'evening_pain', label: 'Evening' },
    { key: 'night_pain', label: 'Night' },
    { key: 'variable_timing', label: 'No fixed time' },
  ];

  const completeness = assessment?.completeness ?? null;
  const missing = assessment?.missing_fields ?? [];

  const canAdvance = step === 0 ? patientId !== null : true;

  return (
    <>
      <PageHeader
        step={step}
        onCancel={() => navigate('/assessments')}
      />

      {failure && (
        <Card className="flex items-start gap-2.5 border-danger/30 bg-danger/8 p-4">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <p className="text-[12px] leading-relaxed text-soft">{failure}</p>
        </Card>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-center justify-between gap-3 pb-3">
          <div className="flex min-w-0 items-center gap-3">
            <Tile tone="accent" className="h-9 w-9 rounded-lg">
              {patient.data ? patient.data.code.slice(-3) : '—'}
            </Tile>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[14px] font-semibold text-ink">
                  {patient.data?.display_name ?? 'No patient selected'}
                </span>
                {patient.data?.is_synthetic && (
                  <Pill tone="violet" size="xs" dot>
                    Synthetic record
                  </Pill>
                )}
                {assessment && (
                  <Pill tone="neutral" size="xs">
                    {assessment.status.toLowerCase()}
                  </Pill>
                )}
              </div>
              <p className="truncate text-[11px] text-mute">
                {patient.data
                  ? [
                      patient.data.code,
                      patient.data.age !== null ? `${patient.data.age} years` : null,
                      SEX_LABEL[patient.data.sex],
                      patient.data.ward,
                    ]
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

      <div
        className={cx(
          'grid grid-cols-1 gap-4',
          step !== 2 && step !== 8 && step !== 9 && 'xl:grid-cols-[1fr_320px]',
        )}
      >
        <div className="space-y-4">
          {/* --- 0 · patient and clinician ------------------------------------------- */}
          {step === 0 && (
            <>
              <Card className="space-y-5 p-5">
                <CardHead
                  title="Who is this assessment for?"
                  sub="The record is amended here as well as read — a telephone number corrected at the bedside is corrected everywhere."
                />
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
                    onChange={setPatientId}
                  />
                  {patients.data && patients.data.items.length === 0 && (
                    <p className="text-[11.5px] text-mute">
                      No patient is on file yet. Register one from the Patients screen first.
                    </p>
                  )}
                </div>

                {patient.data && (
                  <div className="space-y-4 border-t border-hairline pt-4">
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
                      <TextField
                        label="Given name"
                        value={record.given_name}
                        onChange={(event) =>
                          setRecord((state) => ({ ...state, given_name: event.target.value }))
                        }
                      />
                      <TextField
                        label="Family name"
                        value={record.family_name}
                        onChange={(event) =>
                          setRecord((state) => ({ ...state, family_name: event.target.value }))
                        }
                      />
                      <TextField
                        label="Internal identifier"
                        value={patient.data.code}
                        readOnly
                        hint="Assigned by the platform; it cannot be edited."
                      />
                      <TextField
                        label="Date of birth"
                        type="date"
                        value={record.birth_date}
                        onChange={(event) =>
                          setRecord((state) => ({ ...state, birth_date: event.target.value }))
                        }
                        hint={
                          patient.data.age !== null ? `${patient.data.age} years old` : undefined
                        }
                      />
                      <Labelled label="Sex">
                        <Select
                          label="Sex"
                          className="w-full [&>button]:w-full"
                          options={(Object.keys(SEX_LABEL) as Sex[]).map((value) => ({
                            value,
                            label: SEX_LABEL[value],
                          }))}
                          value={record.sex}
                          onChange={(value) =>
                            setRecord((state) => ({ ...state, sex: (value ?? 'UNDISCLOSED') as Sex }))
                          }
                        />
                      </Labelled>
                      <TextField
                        label="Ward"
                        value={record.ward}
                        placeholder="Emergency department"
                        onChange={(event) =>
                          setRecord((state) => ({ ...state, ward: event.target.value }))
                        }
                      />
                      <TextField
                        label="Telephone"
                        value={record.phone}
                        onChange={(event) =>
                          setRecord((state) => ({ ...state, phone: event.target.value }))
                        }
                      />
                      <TextField
                        label="Emergency contact"
                        value={record.emergency_contact_name}
                        onChange={(event) =>
                          setRecord((state) => ({
                            ...state,
                            emergency_contact_name: event.target.value,
                          }))
                        }
                      />
                      <TextField
                        label="Emergency telephone"
                        value={record.emergency_contact_phone}
                        onChange={(event) =>
                          setRecord((state) => ({
                            ...state,
                            emergency_contact_phone: event.target.value,
                          }))
                        }
                      />
                      <Labelled label="Smoking status">
                        <Select
                          label="Smoking status"
                          className="w-full [&>button]:w-full"
                          options={(Object.keys(SMOKING_LABEL) as SmokingStatus[]).map(
                            (value) => ({ value, label: SMOKING_LABEL[value] }),
                          )}
                          value={record.smoking_status}
                          onChange={(value) =>
                            setRecord((state) => ({
                              ...state,
                              smoking_status: (value ?? 'UNKNOWN') as SmokingStatus,
                            }))
                          }
                        />
                      </Labelled>
                    </div>
                    <div className="flex flex-wrap items-center gap-3">
                      <Button
                        icon={<Save className="h-3.5 w-3.5" />}
                        disabled={busy}
                        onClick={() => void saveRecord()}
                      >
                        Save to patient record
                      </Button>
                      {recordSaved && (
                        <span className="text-[11px] text-ok">Record saved at {recordSaved}</span>
                      )}
                    </div>
                  </div>
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead
                  title="Assessing clinician"
                  sub="Taken from the signed-in account. Signing writes it into the ledger."
                />
                <dl className="grid grid-cols-1 gap-x-8 gap-y-2 sm:grid-cols-2">
                  <Row label="Name" value={user?.display_name ?? '—'} />
                  <Row label="Speciality" value={user?.speciality ?? 'Not recorded'} />
                  <Row label="Registration" value={user?.registration_number ?? 'Not recorded'} />
                  <Row
                    label="Validated"
                    value={
                      assessment?.validated_at
                        ? new Date(assessment.validated_at).toLocaleString('en-GB')
                        : 'Not yet signed'
                    }
                  />
                </dl>
                <p className="text-[11px] text-faint">
                  Speciality and registration are edited in Settings, so one correction
                  carries to every assessment and every report.
                </p>
              </Card>

              {profiles.data && (
                <Card className="space-y-4 p-5">
                  <CardHead
                    title="Population"
                    sub="Which physiological band a reading is compared against, and which scale the estimate is checked against."
                  />
                  <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                    <Labelled label="Profile">
                      <Select
                        label="Decided by age"
                        className="w-full [&>button]:w-full"
                        clearable
                        options={profiles.data.primary.map((entry) => ({
                          value: entry.code,
                          label: entry.label,
                          hint: entry.can_self_report ? 'can self-report' : 'observational',
                        }))}
                        value={draft.profile_code}
                        onChange={(value) => set('profile_code', value)}
                      />
                    </Labelled>
                    <Labelled label="Pregnancy trimester">
                      <Select
                        label="Not applicable"
                        className="w-full [&>button]:w-full"
                        clearable
                        options={[
                          { value: '1', label: 'First' },
                          { value: '2', label: 'Second' },
                          { value: '3', label: 'Third' },
                        ]}
                        value={
                          draft.pregnancy_trimester === null
                            ? null
                            : String(draft.pregnancy_trimester)
                        }
                        onChange={(value) =>
                          set('pregnancy_trimester', value === null ? null : Number(value))
                        }
                      />
                    </Labelled>
                  </div>
                  {profiles.data.modifiers.length > 0 && (
                    <div>
                      <span className="mb-1.5 block text-xs font-medium text-soft">
                        Modifiers
                      </span>
                      <div className="flex flex-wrap gap-1.5">
                        {profiles.data.modifiers.map((entry) => (
                          <Choice
                            key={entry.code}
                            kind="check"
                            checked={draft.profile_modifiers.includes(entry.code)}
                            onClick={() =>
                              set('profile_modifiers', toggle(draft.profile_modifiers, entry.code))
                            }
                          >
                            {entry.label}
                          </Choice>
                        ))}
                      </div>
                    </div>
                  )}
                  <p className="text-[11px] leading-relaxed text-faint">
                    {profiles.data.notice}
                  </p>
                </Card>
              )}
            </>
          )}

          {/* --- 1 · history -------------------------------------------------------- */}
          {step === 1 && (
            <>
              <Card className="space-y-4 p-5">
                <CardHead
                  title="Chronic conditions"
                  sub="What the patient already carries. Read by the rule layer when it weighs a finding."
                />
                {diseases.loading ? (
                  <p className="py-6 text-center text-[13px] text-mute">Loading…</p>
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {(diseases.data ?? [])
                      .filter((entry) => entry.pain_relevant)
                      .map((entry) => (
                        <Choice
                          key={entry.code}
                          kind="check"
                          checked={record.condition_codes.includes(entry.code)}
                          onClick={() =>
                            setRecord((state) => ({
                              ...state,
                              condition_codes: toggle(state.condition_codes, entry.code),
                            }))
                          }
                        >
                          {entry.label}
                        </Choice>
                      ))}
                  </div>
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead
                  title="Allergies and history"
                  sub="Held on the patient, not on this assessment, so it is there next time."
                />
                <Note
                  label="Allergies"
                  value={record.allergies}
                  placeholder="Penicillin — rash. No known food allergy…"
                  onChange={(value) => setRecord((state) => ({ ...state, allergies: value }))}
                />
                <Note
                  label="Relevant history"
                  value={record.medical_history}
                  placeholder="Long-standing lumbar disc disease, treated conservatively…"
                  onChange={(value) =>
                    setRecord((state) => ({ ...state, medical_history: value }))
                  }
                />
                <Note
                  label="Previous surgery"
                  value={record.previous_surgeries}
                  placeholder="Laparoscopic cholecystectomy, 2019…"
                  onChange={(value) =>
                    setRecord((state) => ({ ...state, previous_surgeries: value }))
                  }
                />
                <Note
                  label="Family history"
                  value={record.family_history}
                  placeholder="Father: ischaemic heart disease at 54…"
                  onChange={(value) => setRecord((state) => ({ ...state, family_history: value }))}
                />
                <Note
                  label="Lifestyle"
                  value={record.lifestyle_notes}
                  placeholder="Sedentary work, walks 20 minutes daily…"
                  onChange={(value) =>
                    setRecord((state) => ({ ...state, lifestyle_notes: value }))
                  }
                />
                <div className="flex flex-wrap items-center gap-3 border-t border-hairline pt-4">
                  <Button
                    icon={<Save className="h-3.5 w-3.5" />}
                    disabled={busy || !patientId}
                    onClick={() => void saveRecord()}
                  >
                    Save to patient record
                  </Button>
                  {recordSaved && (
                    <span className="text-[11px] text-ok">Record saved at {recordSaved}</span>
                  )}
                </div>
              </Card>

              {patient.data && patient.data.medications.length > 0 && (
                <Card className="space-y-2 p-5">
                  <CardHead
                    title="Medication on file"
                    sub="The patient's standing prescription. What was given for this episode is recorded on the Treatment step."
                  />
                  <ul className="divide-y divide-hairline">
                    {patient.data.medications.map((entry) => (
                      <li
                        key={entry.id}
                        className="flex flex-wrap items-baseline gap-2 py-2 text-[12.5px]"
                      >
                        <span className="font-medium text-ink">{entry.name}</span>
                        {entry.dose && <span className="text-mute">{entry.dose}</span>}
                        {entry.frequency && <span className="text-mute">{entry.frequency}</span>}
                        {entry.is_analgesic && (
                          <Pill tone="violet" size="xs">
                            analgesic
                          </Pill>
                        )}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}
            </>
          )}

          {/* --- 2 · site ----------------------------------------------------------- */}
          {step === 2 && (
            <SitePicker
              sites={draft.anatomical_sites}
              onChange={(sites) => set('anatomical_sites', sites)}
              qualities={qualities.data ?? []}
            />
          )}

          {/* --- 3 · pain description ----------------------------------------------- */}
          {step === 3 && (
            <>
              <Card className="space-y-4 p-5">
                <CardHead
                  title="Character"
                  sub="What the pain feels like, across all sites. A site can carry its own character on the Site step."
                />
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
                {(qualities.data ?? []).some(
                  (entry) => entry.neuropathic_hint && draft.quality_codes.includes(entry.code),
                ) && (
                  <p className="text-[11.5px] text-violet">
                    One of these descriptions is associated with neuropathic pain. The rule
                    layer notes it; it does not decide a type on its own.
                  </p>
                )}
                {painTypes.data && painTypes.data.length > 0 && (
                  <p className="border-t border-hairline pt-3 text-[11px] leading-relaxed text-faint">
                    The pain type is derived from the character, the site and the course
                    rather than asked for directly — the candidate types appear with the
                    estimate.
                  </p>
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Onset and duration" />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
                  <Labelled label="Onset">
                    <Select
                      label="Onset"
                      className="w-full [&>button]:w-full"
                      options={ONSET}
                      value={draft.onset}
                      onChange={(value) => set('onset', (value ?? 'UNKNOWN') as Onset)}
                    />
                  </Labelled>
                  <Labelled label="Came on">
                    <Select
                      label="How quickly"
                      className="w-full [&>button]:w-full"
                      options={ONSET_SPEED}
                      value={draft.onset_speed}
                      onChange={(value) => set('onset_speed', (value ?? 'UNKNOWN') as OnsetSpeed)}
                    />
                  </Labelled>
                  <TextField
                    label="Started at"
                    type="datetime-local"
                    value={draft.started_at}
                    onChange={(event) => set('started_at', event.target.value)}
                  />
                  <TextField
                    label="Duration"
                    type="number"
                    min={0}
                    step="0.5"
                    placeholder="6"
                    trailing={<span className="text-[11px] text-faint">hours</span>}
                    value={draft.duration_hours}
                    onChange={(event) => set('duration_hours', event.target.value)}
                  />
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Pattern and course" />
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <Labelled label="Pattern">
                    <Select
                      label="Pattern"
                      className="w-full [&>button]:w-full"
                      options={PATTERN}
                      value={draft.pattern}
                      onChange={(value) => set('pattern', (value ?? 'UNKNOWN') as Pattern)}
                    />
                  </Labelled>
                  <Labelled label="Course since onset">
                    <Select
                      label="Course"
                      className="w-full [&>button]:w-full"
                      options={COURSE}
                      value={draft.course}
                      onChange={(value) => set('course', (value ?? 'UNKNOWN') as Course)}
                    />
                  </Labelled>
                </div>
                <div className="space-y-3 border-t border-hairline pt-4">
                  <Toggle
                    checked={draft.recurrent}
                    onChange={(value) => set('recurrent', value)}
                    label="This has happened before"
                  />
                  {(draft.recurrent || draft.pattern === 'EPISODIC') && (
                    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                      <TextField
                        label="Episodes per day"
                        type="number"
                        min={0}
                        step="1"
                        placeholder="3"
                        value={draft.episodes_per_day}
                        onChange={(event) => set('episodes_per_day', event.target.value)}
                      />
                      <TextField
                        label="Each episode lasts"
                        type="number"
                        min={0}
                        step="5"
                        placeholder="20"
                        trailing={<span className="text-[11px] text-faint">min</span>}
                        value={draft.episode_minutes}
                        onChange={(event) => set('episode_minutes', event.target.value)}
                      />
                    </div>
                  )}
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Timing" sub="When in the day it is felt, and what brings it on." />
                <div className="flex flex-wrap gap-1.5">
                  {timings.map((entry) => (
                    <Choice
                      key={String(entry.key)}
                      kind="check"
                      checked={Boolean(draft[entry.key])}
                      onClick={() => set(entry.key, !draft[entry.key] as never)}
                    >
                      {entry.label}
                    </Choice>
                  ))}
                </div>
                <div className="flex flex-wrap gap-1.5 border-t border-hairline pt-4">
                  <Choice
                    kind="check"
                    checked={draft.pain_at_rest}
                    onClick={() => set('pain_at_rest', !draft.pain_at_rest)}
                  >
                    Present at rest
                  </Choice>
                  <Choice
                    kind="check"
                    checked={draft.pain_after_activity}
                    onClick={() => set('pain_after_activity', !draft.pain_after_activity)}
                  >
                    Comes on after activity
                  </Choice>
                </div>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead title="Radiation" sub="Whether it travels, and what travels with it." />
                <Toggle
                  checked={draft.radiates}
                  onChange={(value) => set('radiates', value)}
                  label="The pain travels from where it starts"
                />
                {draft.radiates && (
                  <>
                    <Note
                      label="Where it travels"
                      value={draft.radiation_description}
                      placeholder="Down the back of the left leg to the calf…"
                      onChange={(value) => set('radiation_description', value)}
                    />
                    <div className="flex flex-wrap gap-1.5">
                      <Choice
                        kind="check"
                        checked={draft.radiation_numbness}
                        onClick={() => set('radiation_numbness', !draft.radiation_numbness)}
                      >
                        With numbness
                      </Choice>
                      <Choice
                        kind="check"
                        checked={draft.radiation_tingling}
                        onClick={() => set('radiation_tingling', !draft.radiation_tingling)}
                      >
                        With tingling
                      </Choice>
                      <Choice
                        kind="check"
                        checked={draft.radiation_weakness}
                        onClick={() => set('radiation_weakness', !draft.radiation_weakness)}
                      >
                        With weakness
                      </Choice>
                    </div>
                  </>
                )}
              </Card>
            </>
          )}

          {/* --- 4 · intensity ------------------------------------------------------ */}
          {step === 4 && (
            <Card className="space-y-5 p-5">
              <CardHead
                title="Reported intensity"
                sub="The patient's own score. It is the reference the estimate is checked against, never an input to it."
              />
              {scales.length > 0 && (
                <Labelled label="Scale">
                  <Select
                    label="Scale"
                    className="w-full [&>button]:w-full sm:max-w-md"
                    options={scales.map((entry) => ({
                      value: entry.code,
                      label: entry.label,
                      hint: entry.population,
                    }))}
                    value={draft.scale_code}
                    onChange={(value) => {
                      setDraft((state) => ({
                        ...state,
                        scale_code: value ?? 'NRS',
                        nrs: null,
                        raw_score: '',
                        scale_items: {},
                      }));
                    }}
                  />
                </Labelled>
              )}

              {scale && scale.note && (
                <p className="rounded-[10px] bg-sunken px-3 py-2 text-[11.5px] leading-relaxed text-mute">
                  {scale.note}
                </p>
              )}

              {(!scale || scale.code === 'NRS') && (
                <NrsScale
                  value={draft.nrs}
                  onChange={(value) => set('nrs', value)}
                  ghost={prediction?.estimated_pain ?? null}
                />
              )}

              {scale && scale.code !== 'NRS' && scale.items.length === 0 && (
                <TextField
                  label={`Score on ${scale.label}`}
                  type="number"
                  min={scale.minimum}
                  max={scale.maximum}
                  value={draft.raw_score}
                  onChange={(event) => set('raw_score', event.target.value)}
                  hint={`Scored between ${scale.minimum} and ${scale.maximum} on this instrument's own range.`}
                />
              )}

              {scale && scale.items.length > 0 && (
                <ScaleItems
                  scale={scale}
                  values={draft.scale_items}
                  onChange={(items) => set('scale_items', items)}
                />
              )}

              {projected !== null && scale && scale.code !== 'NRS' && (
                <p className="text-[12px] text-soft">
                  That is <span className="font-semibold text-ink">{projected}</span> of 10 once
                  projected onto the common scale — the figure the two numbers are compared on.
                </p>
              )}

              <Note
                label="Note on the score"
                value={draft.self_report_note}
                placeholder="Reported through the daughter; patient dysphasic after the stroke…"
                onChange={(value) => set('self_report_note', value)}
              />

              <div className="border-t border-hairline pt-4">
                <Toggle
                  checked={draft.expected_pain}
                  onChange={(value) => set('expected_pain', value)}
                  label="This pain is expected in context"
                />
                <p className="mt-1 text-[11px] leading-relaxed text-faint">
                  Post-operative pain on day one, for instance. The priority indicator reads
                  an expected pain differently from an unexplained one.
                </p>
              </div>
            </Card>
          )}

          {/* --- 5 · symptoms, factors, context ------------------------------------- */}
          {step === 5 && (
            <>
              <Card className="space-y-4 p-5">
                <CardHead
                  title="Associated symptoms"
                  sub="What else the patient is reporting right now."
                />
                <div className="flex flex-wrap gap-1.5">
                  {(symptoms.data ?? []).map((entry) => (
                    <Choice
                      key={entry.code}
                      kind="check"
                      checked={draft.symptom_codes.includes(entry.code)}
                      onClick={() => set('symptom_codes', toggle(draft.symptom_codes, entry.code))}
                    >
                      {entry.label}
                      {entry.alarm && <span className="ml-1 text-warn">·</span>}
                    </Choice>
                  ))}
                </div>
                <p className="text-[11px] text-faint">
                  A dot marks a symptom the rule layer treats as an alarm feature.
                </p>
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
                </Card>
              </div>

              <Card className="space-y-4 p-5">
                <CardHead
                  title="Recorded context"
                  sub="What is moving the vital signs other than the pain. Named rather than silently absorbed."
                />
                <div className="space-y-2">
                  {(confounders.data ?? []).map((entry) => {
                    const on = draft.confounder_codes.includes(entry.code);
                    return (
                      <button
                        key={entry.code}
                        type="button"
                        onClick={() =>
                          set('confounder_codes', toggle(draft.confounder_codes, entry.code))
                        }
                        className={cx(
                          'flex w-full items-start gap-3 rounded-[10px] border px-3 py-2.5 text-left transition-colors',
                          on
                            ? 'border-accent-edge bg-accent-wash'
                            : 'border-hairline hover:border-hairline-strong',
                        )}
                      >
                        <span
                          className={cx(
                            'mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded border',
                            on
                              ? 'border-transparent bg-clinical text-white dark:bg-accent dark:text-[#04121f]'
                              : 'border-hairline-strong',
                          )}
                        >
                          {on && <Check className="h-3 w-3" />}
                        </span>
                        <span className="min-w-0">
                          <span className="block text-[13px] font-medium text-ink">
                            {entry.label}
                          </span>
                          <span className="block text-[11.5px] leading-relaxed text-mute">
                            {entry.note}
                          </span>
                        </span>
                      </button>
                    );
                  })}
                </div>
              </Card>
            </>
          )}

          {/* --- 6 · treatment and function ----------------------------------------- */}
          {step === 6 && (
            <>
              <Card className="space-y-4 p-5">
                <CardHead
                  title="Current medication"
                  sub="What the patient has had for this pain, and what it did."
                  action={
                    <Select
                      label="Add a class"
                      size="sm"
                      searchable
                      options={(medicationClasses.data ?? [])
                        .filter(
                          (entry) =>
                            !draft.medications.some((use) => use.class_code === entry.code),
                        )
                        .map((entry) => ({
                          value: entry.code,
                          label: entry.label,
                          hint: entry.analgesic ? 'analgesic' : entry.sedating ? 'sedating' : '',
                        }))}
                      value={null}
                      onChange={(value) => {
                        if (!value) return;
                        set('medications', [
                          ...draft.medications,
                          {
                            class_code: value,
                            dose_category: 'UNKNOWN',
                            frequency: 'UNKNOWN',
                            pain_effect: 'UNKNOWN',
                            sedation_effect: 'UNKNOWN',
                          },
                        ]);
                      }}
                    />
                  }
                />
                {draft.medications.length === 0 ? (
                  <EmptyState
                    icon={<Plus className="h-5 w-5" />}
                    title="No medication recorded"
                    sub="Add the class the patient has had. Analgesia within the last hours is a confounder the estimate accounts for."
                  />
                ) : (
                  <ul className="space-y-2">
                    {draft.medications.map((use, index) => (
                      <li
                        key={use.class_code}
                        className="space-y-3 rounded-[10px] border border-hairline p-3"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <span className="text-[13px] font-medium text-ink">
                            {classLabel.get(use.class_code) ?? use.class_code}
                          </span>
                          <button
                            type="button"
                            aria-label="Remove"
                            onClick={() =>
                              set(
                                'medications',
                                draft.medications.filter((_, at) => at !== index),
                              )
                            }
                            className="rounded-md p-1 text-faint transition-colors hover:bg-danger/10 hover:text-danger"
                          >
                            <Trash2 className="h-3.5 w-3.5" />
                          </button>
                        </div>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                          <TextField
                            label="Name as given"
                            placeholder="Paracetamol 1 g"
                            value={use.name ?? ''}
                            onChange={(event) =>
                              set(
                                'medications',
                                draft.medications.map((entry, at) =>
                                  at === index ? { ...entry, name: event.target.value } : entry,
                                ),
                              )
                            }
                          />
                          <Labelled label="Dose">
                            <Select
                              label="Dose"
                              className="w-full [&>button]:w-full"
                              options={DOSE_CATEGORY}
                              value={use.dose_category}
                              onChange={(value) =>
                                set(
                                  'medications',
                                  draft.medications.map((entry, at) =>
                                    at === index
                                      ? {
                                          ...entry,
                                          dose_category: (value ??
                                            'UNKNOWN') as MedicationUse['dose_category'],
                                        }
                                      : entry,
                                  ),
                                )
                              }
                            />
                          </Labelled>
                          <Labelled label="Frequency">
                            <Select
                              label="Frequency"
                              className="w-full [&>button]:w-full"
                              options={DOSE_FREQUENCY}
                              value={use.frequency}
                              onChange={(value) =>
                                set(
                                  'medications',
                                  draft.medications.map((entry, at) =>
                                    at === index
                                      ? {
                                          ...entry,
                                          frequency: (value ??
                                            'UNKNOWN') as MedicationUse['frequency'],
                                        }
                                      : entry,
                                  ),
                                )
                              }
                            />
                          </Labelled>
                          <TextField
                            label="Hours since last dose"
                            type="number"
                            min={0}
                            step="0.5"
                            placeholder="2"
                            value={use.hours_since_last_dose ?? ''}
                            onChange={(event) =>
                              set(
                                'medications',
                                draft.medications.map((entry, at) =>
                                  at === index
                                    ? {
                                        ...entry,
                                        hours_since_last_dose: number(event.target.value),
                                      }
                                    : entry,
                                ),
                              )
                            }
                          />
                          <Labelled label="Effect on the pain">
                            <Select
                              label="Effect"
                              className="w-full [&>button]:w-full"
                              options={PAIN_EFFECT}
                              value={use.pain_effect}
                              onChange={(value) =>
                                set(
                                  'medications',
                                  draft.medications.map((entry, at) =>
                                    at === index
                                      ? {
                                          ...entry,
                                          pain_effect: (value ??
                                            'UNKNOWN') as MedicationUse['pain_effect'],
                                        }
                                      : entry,
                                  ),
                                )
                              }
                            />
                          </Labelled>
                          <Labelled label="Sedation">
                            <Select
                              label="Sedation"
                              className="w-full [&>button]:w-full"
                              options={SEDATION_EFFECT}
                              value={use.sedation_effect}
                              onChange={(value) =>
                                set(
                                  'medications',
                                  draft.medications.map((entry, at) =>
                                    at === index
                                      ? {
                                          ...entry,
                                          sedation_effect: (value ??
                                            'UNKNOWN') as MedicationUse['sedation_effect'],
                                        }
                                      : entry,
                                  ),
                                )
                              }
                            />
                          </Labelled>
                        </div>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead
                  title="Effect on function"
                  sub="What the pain is stopping the patient doing — scored 0 to 4 in each domain."
                />
                <div className="space-y-3">
                  {FUNCTIONAL_DOMAINS.map((domain) => (
                    <div key={domain.key} className="flex flex-wrap items-center gap-3">
                      <span className="w-32 shrink-0 text-[13px] text-soft">{domain.label}</span>
                      <Segmented
                        options={IMPACT_WORD.map((label, score) => ({
                          value: String(score),
                          label,
                        }))}
                        value={String(draft.functional_impact[domain.key] ?? '')}
                        onChange={(value) =>
                          set('functional_impact', {
                            ...draft.functional_impact,
                            [domain.key]: Number(value),
                          })
                        }
                      />
                    </div>
                  ))}
                </div>
              </Card>

              <Card className="space-y-3 p-5">
                <CardHead title="Recent events" />
                <div className="flex flex-wrap gap-1.5">
                  <Choice
                    kind="check"
                    checked={draft.recent_trauma}
                    onClick={() => set('recent_trauma', !draft.recent_trauma)}
                  >
                    Recent trauma
                  </Choice>
                  <Choice
                    kind="check"
                    checked={draft.recent_surgery}
                    onClick={() => set('recent_surgery', !draft.recent_surgery)}
                  >
                    Recent surgery
                  </Choice>
                </div>
              </Card>
            </>
          )}

          {/* --- 7 · physiology ----------------------------------------------------- */}
          {step === 7 && (
            <Card className="space-y-4 p-5">
              <CardHead
                title="Physiology"
                sub="Entered at the bedside or read off the monitor. Vitals are confounders, not pain measures."
              />
              <div className="grid grid-cols-2 gap-4 lg:grid-cols-3">
                {VITALS.map((vital) => (
                  <TextField
                    key={vital.key}
                    label={vital.label}
                    type="number"
                    step="any"
                    placeholder={vital.placeholder}
                    trailing={<span className="text-[11px] text-faint">{vital.unit}</span>}
                    value={draft.vitals[vital.key]}
                    onChange={(event) => setVital(vital.key, event.target.value)}
                  />
                ))}
              </div>
              {bmi !== null && (
                <p className="rounded-[10px] bg-sunken px-3 py-2 text-[12px] text-soft">
                  Body mass index{' '}
                  <span className="font-semibold text-ink tabular-nums">{bmi.toFixed(1)}</span>{' '}
                  kg/m², computed from the weight and height rather than entered.
                </p>
              )}
              <p className="text-[11px] leading-relaxed text-faint">
                The model weights vitals lightly and reports when they are absent. Each
                reading is compared against the band for the population chosen on the first
                step, not against one adult range.
              </p>
            </Card>
          )}

          {/* --- 8 · camera and voice ----------------------------------------------- */}
          {step === 8 && (
            <BehaviourPanel
              patientId={patientId}
              assessmentId={assessment?.id ?? null}
              onObservation={() => setSavedAt(new Date())}
            />
          )}

          {/* --- 9 · EEG and EMG ---------------------------------------------------- */}
          {step === 9 && (
            <SignalPanel patientId={patientId} reportedNrs={projected} />
          )}

          {/* --- 10 · adaptive questions -------------------------------------------- */}
          {step === 10 && (
            <Card className="space-y-5 p-5">
              <CardHead
                title="Questions for this picture"
                sub="Drawn from the question bank by what has been recorded so far — the form asks about jaw radiation for a chest pain and not for a knee."
                action={
                  questions && (
                    <Pill tone="violet" size="xs">
                      {questions.length} applicable
                    </Pill>
                  )
                }
              />
              {questions === null ? (
                <p className="py-8 text-center text-[13px] text-mute">Choosing the questions…</p>
              ) : questions.length === 0 ? (
                <EmptyState
                  title="Nothing further to ask"
                  sub="The question bank has nothing that applies to what has been recorded. Go on to the analysis."
                />
              ) : (
                <div className="space-y-5">
                  {Object.entries(
                    questions.reduce<Record<string, ClinicalQuestion[]>>((groups, question) => {
                      const list = groups[question.group_label] ?? [];
                      list.push(question);
                      groups[question.group_label] = list;
                      return groups;
                    }, {}),
                  ).map(([group, entries]) => (
                    <div key={group} className="space-y-3">
                      <p className="eyebrow">{group}</p>
                      {entries.map((question) => (
                        <QuestionField
                          key={question.code}
                          question={question}
                          value={draft.answers[question.code]}
                          onChange={(value) =>
                            set('answers', { ...draft.answers, [question.code]: value })
                          }
                        />
                      ))}
                    </div>
                  ))}
                </div>
              )}
            </Card>
          )}

          {/* --- 11 · AI analysis --------------------------------------------------- */}
          {step === ANALYSIS_STEP && (
            <>
              <Card className="p-5">
                <CardHead
                  title="AI analysis"
                  sub="The model's estimate next to what the patient reported."
                  action={
                    <Button
                      variant="primary"
                      icon={<BrainCircuit className="h-4 w-4" />}
                      disabled={busy || !patientId}
                      onClick={() => void predict()}
                    >
                      {prediction ? 'Run again' : 'Run the estimate'}
                    </Button>
                  }
                />
                {!prediction ? (
                  <p className="py-12 text-center text-[13px] text-mute">
                    Nothing has been estimated yet. Running the estimate saves the assessment
                    and asks the model.
                  </p>
                ) : prediction.refused ? (
                  <div className="mt-4 rounded-[10px] border border-warn/30 bg-warn/8 p-4">
                    <p className="text-[13px] font-semibold text-ink">
                      The model declined to estimate
                    </p>
                    <p className="mt-1 text-[12px] leading-relaxed text-soft">
                      {prediction.refusal_reason}
                    </p>
                  </div>
                ) : (
                  <div className="mt-4 flex flex-wrap items-center gap-8">
                    <Gauge
                      value={prediction.estimated_pain ?? 0}
                      caption={prediction.band_label ?? ''}
                    />
                    <div className="min-w-[240px] flex-1 space-y-3">
                      <Figure
                        label="Patient-reported"
                        value={
                          assessment?.self_report === null || assessment?.self_report === undefined
                            ? '—'
                            : `${assessment.self_report} / 10`
                        }
                      />
                      <Figure
                        label="Estimated range"
                        value={
                          prediction.interval_low !== null && prediction.interval_high !== null
                            ? `${prediction.interval_low.toFixed(1)} – ${prediction.interval_high.toFixed(1)}`
                            : '—'
                        }
                        tone="violet"
                      />
                      <Figure
                        label="Data quality"
                        value={prediction.data_quality.toLowerCase()}
                      />
                      <Figure
                        label="Priority"
                        value={prediction.priority_label ?? '—'}
                      />
                      <p className="pt-1 text-[11px] leading-relaxed text-faint">
                        The estimate supports the clinical conversation. Where it and the
                        patient disagree, the patient's own report is the reference.
                      </p>
                    </div>
                  </div>
                )}
              </Card>

              {prediction && prediction.alerts.length > 0 && (
                <Card className="space-y-2 p-5">
                  <CardHead title="Clinical review cues" />
                  {prediction.alerts.map((alert) => (
                    <div
                      key={alert.rule_code}
                      className="rounded-[10px] border border-warn/25 bg-warn/8 p-3"
                    >
                      <p className="text-[13px] font-semibold text-ink">{alert.label}</p>
                      <p className="mt-1 text-[11.5px] leading-relaxed text-soft">
                        {alert.advice}
                      </p>
                      {alert.context_notes.map((note) => (
                        <p key={note} className="mt-1 text-[11px] text-mute">
                          {note}
                        </p>
                      ))}
                    </div>
                  ))}
                </Card>
              )}

              {prediction && prediction.contributions.length > 0 && (
                <Card className="space-y-2 p-5">
                  <CardHead
                    title="What moved the estimate"
                    sub="The largest contributions, as the explainer reports them."
                  />
                  <ul className="space-y-1.5">
                    {prediction.contributions.slice(0, 10).map((entry) => (
                      <li key={entry.feature} className="flex items-center gap-3 text-[12.5px]">
                        <span className="min-w-0 flex-1 truncate text-soft">{entry.label}</span>
                        <span
                          className={cx(
                            'shrink-0 font-medium tabular-nums',
                            entry.contribution >= 0 ? 'text-warn' : 'text-teal',
                          )}
                        >
                          {entry.contribution >= 0 ? '+' : ''}
                          {entry.contribution.toFixed(2)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {prediction && prediction.categories.length > 0 && (
                <Card className="space-y-2 p-5">
                  <CardHead
                    title="Compatible categories"
                    sub="What the recorded picture is consistent with. Not a diagnosis."
                  />
                  <ul className="divide-y divide-hairline">
                    {prediction.categories.slice(0, 8).map((entry) => (
                      <li key={entry.cause_code} className="py-2">
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="text-[13px] font-medium text-ink">{entry.label}</span>
                          <span className="shrink-0 text-[12px] text-mute tabular-nums">
                            {(entry.score * 100).toFixed(0)}%
                          </span>
                        </div>
                        {entry.missing.length > 0 && (
                          <p className="mt-0.5 text-[11px] text-mute">
                            Not recorded: {entry.missing.join(', ')}
                          </p>
                        )}
                      </li>
                    ))}
                  </ul>
                </Card>
              )}

              {prediction && prediction.quality_issues.length > 0 && (
                <Card className="space-y-1.5 p-5">
                  <CardHead title="Data quality findings" />
                  {prediction.quality_issues.map((issue) => (
                    <p key={issue} className="text-[11.5px] leading-relaxed text-warn">
                      {issue}
                    </p>
                  ))}
                </Card>
              )}
            </>
          )}

          {/* --- 12 · review and sign ------------------------------------------------ */}
          {step === REVIEW_STEP && (
            <>
              <Card className="space-y-3 p-5">
                <CardHead title="Patient" />
                <dl className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
                  <Row
                    label="Name"
                    value={
                      [record.given_name, record.family_name].filter(Boolean).join(' ') ||
                      patient.data?.display_name ||
                      '—'
                    }
                  />
                  <Row label="Internal identifier" value={patient.data?.code ?? '—'} />
                  <Row
                    label="Age and sex"
                    value={
                      patient.data
                        ? `${patient.data.age ?? '—'} · ${SEX_LABEL[patient.data.sex]}`
                        : '—'
                    }
                  />
                  <Row label="Ward" value={record.ward || '—'} />
                  <Row label="Telephone" value={record.phone || '—'} />
                  <Row
                    label="Emergency contact"
                    value={
                      [record.emergency_contact_name, record.emergency_contact_phone]
                        .filter(Boolean)
                        .join(' · ') || '—'
                    }
                  />
                  <Row label="Smoking status" value={SMOKING_LABEL[record.smoking_status]} />
                </dl>
              </Card>

              <Card className="space-y-3 p-5">
                <CardHead title="Assessing clinician" />
                <dl className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
                  <Row label="Name" value={user?.display_name ?? '—'} />
                  <Row label="Speciality" value={user?.speciality ?? '—'} />
                  <Row label="Registration" value={user?.registration_number ?? '—'} />
                  <Row
                    label="Validated"
                    value={
                      assessment?.validated_at
                        ? new Date(assessment.validated_at).toLocaleString('en-GB')
                        : 'Not yet signed'
                    }
                  />
                </dl>
              </Card>

              <Card className="space-y-3 p-5">
                <CardHead title="Pain description" />
                <dl className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
                  <Row
                    label="Site"
                    value={
                      assessment?.anatomical_sites.length
                        ? assessment.anatomical_sites
                            .map(
                              (site) =>
                                `${site.label}${
                                  site.side === 'NOT_APPLICABLE' ? '' : ` (${site.side.toLowerCase()})`
                                }${site.is_primary ? ' — primary' : ''}`,
                            )
                            .join('; ')
                        : '—'
                    }
                  />
                  <Row
                    label="Character"
                    value={
                      draft.quality_codes.map((code) => qualityLabel.get(code) ?? code).join(', ') ||
                      '—'
                    }
                  />
                  <Row
                    label="Onset"
                    value={
                      draft.onset === 'UNKNOWN' && draft.onset_speed === 'UNKNOWN'
                        ? '—'
                        : [
                            ONSET.find((entry) => entry.value === draft.onset)?.label,
                            ONSET_SPEED.find((entry) => entry.value === draft.onset_speed)?.label,
                          ]
                            .filter((entry) => entry && entry !== 'Not known')
                            .join(', ')
                    }
                  />
                  <Row
                    label="Duration"
                    value={
                      draft.duration_hours
                        ? `${draft.duration_hours} hours`
                        : draft.started_at
                          ? `since ${new Date(draft.started_at).toLocaleString('en-GB')}`
                          : '—'
                    }
                  />
                  <Row
                    label="Pattern"
                    value={PATTERN.find((entry) => entry.value === draft.pattern)?.label ?? '—'}
                  />
                  <Row
                    label="Course"
                    value={COURSE.find((entry) => entry.value === draft.course)?.label ?? '—'}
                  />
                  <Row
                    label="Radiation"
                    value={
                      draft.radiates
                        ? [
                            draft.radiation_description || 'travels',
                            draft.radiation_numbness ? 'numbness' : null,
                            draft.radiation_tingling ? 'tingling' : null,
                            draft.radiation_weakness ? 'weakness' : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')
                        : 'None'
                    }
                  />
                  <Row
                    label="Timing"
                    value={
                      [
                        ...timings
                          .filter((entry) => draft[entry.key])
                          .map((entry) => entry.label.toLowerCase()),
                        draft.pain_at_rest ? 'at rest' : null,
                        draft.pain_after_activity ? 'after activity' : null,
                        draft.recurrent ? 'recurrent' : null,
                      ]
                        .filter(Boolean)
                        .join(', ') || '—'
                    }
                  />
                </dl>
              </Card>

              <Card className="space-y-3 p-5">
                <CardHead title="Symptoms, factors and context" />
                <dl className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
                  <Row
                    label="Associated symptoms"
                    value={
                      draft.symptom_codes.map((code) => symptomLabel.get(code) ?? code).join(', ') ||
                      '—'
                    }
                  />
                  <Row
                    label="Worse with"
                    value={
                      draft.factor_codes
                        .filter((code) => worseWith.some((entry) => entry.code === code))
                        .map((code) => factorLabel.get(code) ?? code)
                        .join(', ') || '—'
                    }
                  />
                  <Row
                    label="Better with"
                    value={
                      draft.factor_codes
                        .filter((code) => betterWith.some((entry) => entry.code === code))
                        .map((code) => factorLabel.get(code) ?? code)
                        .join(', ') || '—'
                    }
                  />
                  <Row
                    label="Recorded context"
                    value={
                      draft.confounder_codes
                        .map((code) => confounderLabel.get(code) ?? code)
                        .join(', ') || '—'
                    }
                  />
                  <Row
                    label="Chronic conditions"
                    value={
                      record.condition_codes
                        .map((code) => diseaseLabel.get(code) ?? code)
                        .join(', ') || '—'
                    }
                  />
                  <Row
                    label="Current medication"
                    value={
                      draft.medications
                        .map(
                          (use) =>
                            `${use.name || classLabel.get(use.class_code) || use.class_code}${
                              use.pain_effect === 'UNKNOWN'
                                ? ''
                                : ` — ${PAIN_EFFECT.find((entry) => entry.value === use.pain_effect)?.label.toLowerCase()}`
                            }`,
                        )
                        .join('; ') || '—'
                    }
                  />
                  <Row label="Allergies" value={record.allergies || '—'} />
                  <Row label="Relevant history" value={record.medical_history || '—'} />
                  <Row label="Previous surgery" value={record.previous_surgeries || '—'} />
                </dl>
              </Card>

              <Card className="space-y-3 p-5">
                <CardHead title="Measured" />
                <dl className="grid grid-cols-1 gap-x-8 gap-y-1 sm:grid-cols-2">
                  {VITALS.filter((vital) => draft.vitals[vital.key] !== '').map((vital) => (
                    <Row
                      key={vital.key}
                      label={vital.label}
                      value={`${draft.vitals[vital.key]} ${vital.unit}`}
                    />
                  ))}
                  {bmi !== null && (
                    <Row label="Body mass index" value={`${bmi.toFixed(1)} kg/m²`} />
                  )}
                  <Row
                    label="Reported intensity"
                    value={projected === null ? '—' : `${projected} / 10 · ${draft.scale_code}`}
                  />
                  <Row
                    label="AI estimate"
                    value={
                      prediction?.estimated_pain != null
                        ? `${prediction.estimated_pain.toFixed(1)} / 10`
                        : 'Not estimated'
                    }
                  />
                </dl>
              </Card>

              <Card className="space-y-4 p-5">
                <CardHead
                  title="Sign"
                  sub="Signing writes an entry to the audit ledger under your account and marks the assessment validated."
                />
                {!assessment && (
                  <p className="text-[12px] text-mute">
                    Nothing has been recorded yet. Choose a patient on the first step.
                  </p>
                )}
                {assessment && !prediction && (
                  <p className="text-[12px] text-warn">
                    No estimate has been made. Run the analysis first, or sign the assessment
                    as it stands — it will remain a draft without one.
                  </p>
                )}
                <Button
                  variant="primary"
                  icon={<Check className="h-4 w-4" />}
                  disabled={busy || !assessment || !prediction}
                  onClick={() => void sign()}
                >
                  Sign and record
                </Button>
              </Card>
            </>
          )}

          <div className="flex items-center justify-between">
            <Button
              icon={<ArrowLeft className="h-4 w-4" />}
              disabled={step === 0 || busy}
              onClick={() => void go(step - 1)}
            >
              Back
            </Button>
            {step < STEPS.length - 1 && (
              <Button
                variant="primary"
                disabled={!canAdvance || busy}
                onClick={() => void go(step + 1)}
              >
                {busy ? 'Saving…' : 'Continue'}
                <ArrowRight className="h-4 w-4" />
              </Button>
            )}
          </div>
        </div>

        {/* --- the rail, on the steps that have room for it ------------------------- */}
        {step !== 2 && step !== 8 && step !== 9 && (
          <div className="space-y-4">
            <Card className="p-4">
              <CardHead title="Completeness" sub="Information available to the model" />
              {completeness === null ? (
                <p className="mt-3 text-[12px] text-mute">
                  Measured by the server once the assessment is saved.
                </p>
              ) : (
                <>
                  <div className="mt-3 flex items-baseline gap-2">
                    <span className="text-[30px] leading-none font-semibold text-ink tabular-nums">
                      {Math.round(completeness * 100)}%
                    </span>
                    <span className="text-[12px] text-mute">complete</span>
                  </div>
                  <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-sunken">
                    <div
                      className="h-full rounded-full transition-[width] duration-500 ease-out"
                      style={{
                        width: `${completeness * 100}%`,
                        background:
                          completeness > 0.8
                            ? 'var(--ok)'
                            : completeness > 0.5
                              ? 'var(--accent)'
                              : 'var(--warn)',
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

            {projected !== null && (
              <Card className="p-4">
                <CardHead title="Reported" sub="What the patient said" />
                <div className="mt-3 flex items-center gap-4">
                  <span
                    className="grid h-14 w-14 shrink-0 place-items-center rounded-xl text-[20px] font-semibold text-white"
                    style={{ background: BAND_VAR[bandOf(projected)] }}
                  >
                    {projected.toFixed(1)}
                  </span>
                  <div>
                    <p className="text-[13px] font-medium text-ink">
                      {BAND_LABEL[bandOf(projected)]}
                    </p>
                    <p className="mt-0.5 flex items-center gap-1 text-[11px] text-mute">
                      <Sparkles className="h-3 w-3" />
                      {prediction?.estimated_pain != null
                        ? `model ${prediction.estimated_pain.toFixed(1)}`
                        : 'no estimate yet'}
                    </p>
                  </div>
                </div>
              </Card>
            )}

            <Card className="space-y-2 p-4">
              <CardHead title="Channels" sub="Measured by the platform itself" />
              <Channel
                icon={<Video className="h-3.5 w-3.5" />}
                label="Camera and voice"
                done={step > 8}
                onClick={() => void go(8)}
              />
              <Channel
                icon={<Activity className="h-3.5 w-3.5" />}
                label="EEG and EMG"
                done={step > 9}
                onClick={() => void go(9)}
              />
              <p className="pt-1 text-[11px] leading-relaxed text-faint">
                Both are optional. Skipping one shows up as missing information rather than
                as a zero.
              </p>
            </Card>
          </div>
        )}
      </div>
    </>
  );
};

/* --- small parts ---------------------------------------------------------------------- */

const PageHeader: React.FC<{ step: number; onCancel: () => void }> = ({ step, onCancel }) => (
  <div className="flex flex-wrap items-end justify-between gap-4">
    <div className="min-w-0">
      <div className="mb-1 text-xs text-mute">
        Step {step + 1} of {STEPS.length}
      </div>
      <h1 className="text-[26px] leading-tight font-semibold text-ink">New assessment</h1>
      <p className="mt-1 text-[13px] text-mute">
        Answer what you can — the model reports what it was missing.
      </p>
    </div>
    <Button variant="ghost" onClick={onCancel}>
      Cancel
    </Button>
  </div>
);

const Labelled: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="space-y-1.5">
    <span className="block text-xs font-medium text-soft">{label}</span>
    {children}
  </div>
);

const Row: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="flex items-baseline justify-between gap-4 border-b border-hairline py-1.5">
    <dt className="shrink-0 text-[12px] text-mute">{label}</dt>
    <dd className="min-w-0 text-right text-[13px] font-medium text-ink">{value}</dd>
  </div>
);

const Figure: React.FC<{ label: string; value: React.ReactNode; tone?: 'violet' }> = ({
  label,
  value,
  tone,
}) => (
  <div className="flex items-baseline justify-between border-b border-hairline pb-2">
    <span className="text-[12px] text-mute">{label}</span>
    <span
      className={cx(
        'text-[17px] font-semibold tabular-nums',
        tone === 'violet' ? 'text-violet' : 'text-ink',
      )}
    >
      {value}
    </span>
  </div>
);

const Note: React.FC<{
  label: string;
  value: string;
  placeholder?: string;
  onChange: (value: string) => void;
}> = ({ label, value, placeholder, onChange }) => (
  <label className="block space-y-1.5">
    <span className="block text-xs font-medium text-soft">{label}</span>
    <textarea
      value={value}
      rows={2}
      placeholder={placeholder}
      onChange={(event) => onChange(event.target.value)}
      className="w-full rounded-[10px] border border-hairline bg-surface p-3 text-[13px] text-ink outline-none transition-colors focus:border-accent placeholder:text-faint"
    />
  </label>
);

const Channel: React.FC<{
  icon: React.ReactNode;
  label: string;
  done: boolean;
  onClick: () => void;
}> = ({ icon, label, done, onClick }) => (
  <button
    type="button"
    onClick={onClick}
    className="flex w-full items-center gap-2.5 rounded-[10px] border border-hairline px-3 py-2 text-left transition-colors hover:border-hairline-strong"
  >
    <span className="shrink-0 text-faint">{icon}</span>
    <span className="min-w-0 flex-1 truncate text-[12.5px] text-soft">{label}</span>
    {done && <Check className="h-3.5 w-3.5 shrink-0 text-ok" />}
  </button>
);

/** One item of an observational scale, scored on its own anchors. */
const ScaleItems: React.FC<{
  scale: PainScale;
  values: Record<string, number>;
  onChange: (values: Record<string, number>) => void;
}> = ({ scale, values, onChange }) => (
  <div className="space-y-4">
    {scale.items.map((item) => (
      <div key={item.code}>
        <div className="mb-1.5 flex items-baseline justify-between gap-2">
          <span className="text-[13px] font-medium text-ink">{item.label}</span>
          <span className="text-[11px] text-faint">
            {item.minimum}–{item.maximum}
          </span>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {item.anchors.map((anchor, score) => (
            <Choice
              key={anchor}
              kind="radio"
              checked={values[item.code] === item.minimum + score}
              onClick={() => onChange({ ...values, [item.code]: item.minimum + score })}
            >
              {anchor}
            </Choice>
          ))}
        </div>
      </div>
    ))}
    <p className="text-[11.5px] text-soft">
      Total{' '}
      <span className="font-semibold text-ink tabular-nums">
        {Object.values(values).reduce((sum, value) => sum + value, 0)}
      </span>{' '}
      of {scale.maximum} — computed here and recomputed by the server rather than trusted.
    </p>
  </div>
);

/** A question from the bank, rendered by its declared kind. */
const QuestionField: React.FC<{
  question: ClinicalQuestion;
  value: unknown;
  onChange: (value: unknown) => void;
}> = ({ question, value, onChange }) => {
  const body = (() => {
    if (question.kind === 'BOOL') {
      return (
        <Segmented
          options={[
            { value: 'yes', label: 'Yes' },
            { value: 'no', label: 'No' },
          ]}
          value={value === true ? 'yes' : value === false ? 'no' : ''}
          onChange={(answer) => onChange(answer === 'yes')}
        />
      );
    }
    if (question.kind === 'NUMBER') {
      return (
        <TextField
          type="number"
          min={question.minimum ?? undefined}
          max={question.maximum ?? undefined}
          step="any"
          value={typeof value === 'number' || typeof value === 'string' ? String(value) : ''}
          onChange={(event) => onChange(number(event.target.value))}
          trailing={
            question.unit ? <span className="text-[11px] text-faint">{question.unit}</span> : null
          }
        />
      );
    }
    if (question.kind === 'MULTI') {
      const chosen = Array.isArray(value) ? (value as string[]) : [];
      return (
        <div className="flex flex-wrap gap-1.5">
          {question.options.map((option) => (
            <Choice
              key={option.value}
              kind="check"
              checked={chosen.includes(option.value)}
              onClick={() => onChange(toggle(chosen, option.value))}
            >
              {option.label}
            </Choice>
          ))}
        </div>
      );
    }
    if (question.options.length > 0) {
      return (
        <div className="flex flex-wrap gap-1.5">
          {question.options.map((option) => (
            <Choice
              key={option.value}
              kind="radio"
              checked={value === option.value}
              onClick={() => onChange(option.value)}
            >
              {option.label}
            </Choice>
          ))}
        </div>
      );
    }
    return (
      <textarea
        value={typeof value === 'string' ? value : ''}
        rows={2}
        onChange={(event) => onChange(event.target.value)}
        className="w-full rounded-[10px] border border-hairline bg-surface p-3 text-[13px] text-ink outline-none transition-colors focus:border-accent placeholder:text-faint"
      />
    );
  })();

  return (
    <div className="space-y-1.5">
      <p className="text-[13px] font-medium text-ink">{question.prompt}</p>
      {body}
      {question.help_text && (
        <p className="text-[11px] leading-relaxed text-faint">{question.help_text}</p>
      )}
    </div>
  );
};
