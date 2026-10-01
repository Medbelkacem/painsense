import React, { useMemo } from 'react';
import { AlertTriangle } from 'lucide-react';

import { useQuery } from '../api/hooks';
import type {
  AssessmentDetail, Confounder, Disease, Finding, MedicationClass, PainFactor, PainQuality,
  PatientDetail, Symptom,
} from '../api/types';
import { Card, CardHead } from '../ui/Card';
import { NONE_RECORDED, SEX_LABEL, SMOKING_LABEL, word } from '../lib/clinical';

export interface CatalogLabels {
  quality: Map<string, string>;
  symptom: Map<string, string>;
  factor: Map<string, PainFactor>;
  confounder: Map<string, string>;
  disease: Map<string, string>;
  medicationClass: Map<string, string>;
  ready: boolean;
}

/** The vocabularies every summary needs to turn a code into a word. */
export function useCatalogLabels(): CatalogLabels {
  const qualities = useQuery<PainQuality[]>('/api/pain-qualities');
  const symptoms = useQuery<Symptom[]>('/api/symptoms');
  const factors = useQuery<PainFactor[]>('/api/pain-factors');
  const confounders = useQuery<Confounder[]>('/api/confounders');
  const diseases = useQuery<Disease[]>('/api/diseases');
  const classes = useQuery<MedicationClass[]>('/api/medication-classes');

  return useMemo(
    () => ({
      quality: new Map((qualities.data ?? []).map((entry) => [entry.code, entry.label])),
      symptom: new Map((symptoms.data ?? []).map((entry) => [entry.code, entry.label])),
      factor: new Map((factors.data ?? []).map((entry) => [entry.code, entry])),
      confounder: new Map((confounders.data ?? []).map((entry) => [entry.code, entry.label])),
      disease: new Map((diseases.data ?? []).map((entry) => [entry.code, entry.label])),
      medicationClass: new Map((classes.data ?? []).map((entry) => [entry.code, entry.label])),
      ready: Boolean(
        qualities.data && symptoms.data && factors.data && confounders.data && diseases.data,
      ),
    }),
    [qualities.data, symptoms.data, factors.data, confounders.data, diseases.data, classes.data],
  );
}

export const Row: React.FC<{ label: string; value: React.ReactNode }> = ({ label, value }) => (
  <div className="grid grid-cols-[minmax(7rem,11rem)_1fr] gap-x-4 border-b border-hairline py-1.5 last:border-0">
    <dt className="text-[12px] text-mute">{label}</dt>
    <dd className="min-w-0 text-[13px] font-medium text-ink">{value}</dd>
  </div>
);

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <Card className="space-y-3 p-5">
    <CardHead title={title} />
    <dl>{children}</dl>
  </Card>
);

function joined(parts: (string | null | undefined)[], fallback = NONE_RECORDED): string {
  const kept = parts.map((part) => (part ?? '').trim()).filter(Boolean);
  return kept.length ? kept.join(', ') : fallback;
}

function withNote(coded: string[], note: string | null): string {
  const parts = [...coded, (note ?? '').trim()].filter(Boolean);
  return parts.length ? parts.join('; ') : NONE_RECORDED;
}

export const WarningList: React.FC<{ warnings: Finding[] }> = ({ warnings }) => {
  const urgent = warnings.filter((warning) => warning.level === 'URGENT');
  const rest = warnings.filter((warning) => warning.level !== 'URGENT');
  if (warnings.length === 0) return null;
  return (
    <>
      {urgent.length > 0 && (
        <Card className="space-y-1.5 border-danger/40 bg-danger/8 p-4" role="alert">
          <p className="flex items-center gap-2 text-[14px] font-semibold text-danger">
            <AlertTriangle className="h-4 w-4" />
            Requires urgent clinical review
          </p>
          {urgent.map((warning) => (
            <p key={warning.code} className="text-[12.5px] text-soft">
              {warning.message}
            </p>
          ))}
        </Card>
      )}
      {rest.length > 0 && (
        <Card className="space-y-1.5 border-warn/30 bg-warn/8 p-4">
          {rest.map((warning) => (
            <p key={warning.code} className="flex items-start gap-2 text-[12.5px] text-soft">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
              {warning.message}
            </p>
          ))}
        </Card>
      )}
    </>
  );
};

interface SummaryProps {
  assessment: AssessmentDetail;
  patient: PatientDetail;
  clinician: { display_name: string; speciality?: string | null; registration_number?: string | null } | null;
  validator?: { display_name: string } | null;
  labels: CatalogLabels;
}

/** Every recorded field, label beside value, in the order the paper form lists them. */
export const AssessmentSummary: React.FC<SummaryProps> = ({
  assessment,
  patient,
  clinician,
  validator,
  labels,
}) => {
  const identity = patient.identity;
  const sites = assessment.anatomical_sites.map(
    (site) =>
      `${site.label}${site.side === 'NOT_APPLICABLE' || site.side === 'MIDLINE' ? '' : ` (${site.side.toLowerCase()})`}${site.is_primary ? ', primary' : ''}`,
  );
  const siteText = sites.length ? sites.join('; ') : joined(assessment.location_labels);
  const timing = [
    assessment.morning_pain && 'morning',
    assessment.afternoon_pain && 'afternoon',
    assessment.evening_pain && 'evening',
    assessment.night_pain && 'night',
    assessment.variable_timing && 'no fixed time',
    assessment.pain_at_rest && 'at rest',
    assessment.pain_after_activity && 'after activity',
  ].filter(Boolean) as string[];
  const factorsOf = (kind: 'AGGRAVATING' | 'RELIEVING') =>
    assessment.factor_codes
      .filter((code) => labels.factor.get(code)?.kind === kind)
      .map((code) => labels.factor.get(code)?.label ?? code);
  const age = assessment.patient_age_years ?? patient.age;

  const validated = assessment.validated_at
    ? `Validated${validator ? ` by ${validator.display_name}` : ''} on ${new Date(assessment.validated_at).toLocaleString('en-GB')}`
    : 'Not validated';

  return (
    <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
      <Section title="Patient">
        <Row label="Name" value={identity ? `${identity.given_name} ${identity.family_name}` : 'Sealed'} />
        <Row label="Internal identifier" value={patient.code} />
        <Row label="Age" value={age !== null ? `${age} ${age === 1 ? 'year' : 'years'}` : NONE_RECORDED} />
        <Row label="Sex" value={SEX_LABEL[patient.sex]} />
        <Row label="Ward" value={patient.ward ?? NONE_RECORDED} />
        <Row label="Telephone" value={identity?.phone || NONE_RECORDED} />
        <Row
          label="Emergency contact"
          value={joined([identity?.emergency_contact_name, identity?.emergency_contact_phone])}
        />
        <Row label="Smoking status" value={SMOKING_LABEL[patient.smoking_status]} />
      </Section>

      <Section title="Assessing clinician">
        <Row label="Name" value={clinician?.display_name ?? NONE_RECORDED} />
        <Row label="Speciality" value={clinician?.speciality || NONE_RECORDED} />
        <Row label="Registration number" value={clinician?.registration_number || NONE_RECORDED} />
        <Row label="Validated" value={validated} />
      </Section>

      <Section title="Pain description">
        <Row label="Site" value={siteText} />
        <Row
          label="Character"
          value={joined(assessment.quality_codes.map((code) => labels.quality.get(code) ?? code))}
        />
        <Row label="Onset" value={word(assessment.onset)} />
        <Row label="Duration" value={assessment.duration_label} />
        <Row label="Pattern" value={word(assessment.pattern)} />
        <Row label="Course" value={word(assessment.course)} />
        <Row
          label="Radiation"
          value={
            assessment.radiates
              ? assessment.radiation_description?.trim() || 'Reported, not described'
              : 'None reported'
          }
        />
        <Row label="Timing" value={timing.length ? timing.join(', ') : 'No particular timing recorded'} />
      </Section>

      <Section title="Symptoms, factors and context">
        <Row
          label="Associated symptoms"
          value={withNote(
            assessment.symptom_codes.map((code) => labels.symptom.get(code) ?? code),
            assessment.symptoms_note,
          )}
        />
        <Row label="Worse with" value={withNote(factorsOf('AGGRAVATING'), assessment.aggravating_note)} />
        <Row label="Better with" value={withNote(factorsOf('RELIEVING'), assessment.relieving_note)} />
        <Row
          label="Recorded context"
          value={joined(assessment.confounder_codes.map((code) => labels.confounder.get(code) ?? code))}
        />
        <Row
          label="Chronic conditions"
          value={joined(patient.conditions.map((entry) => labels.disease.get(entry.disease_code) ?? entry.disease_code))}
        />
        <Row
          label="Current medication"
          value={joined([
            ...patient.medications.map((entry) =>
              [entry.name, entry.dose, entry.frequency].filter(Boolean).join(' '),
            ),
            ...assessment.medications.map((use) =>
              [use.name || use.class_label, use.hours_since_last_dose !== null && use.hours_since_last_dose !== undefined ? `${use.hours_since_last_dose} h ago` : null]
                .filter(Boolean)
                .join(', '),
            ),
          ])}
        />
        <Row label="Allergies" value={patient.allergies?.trim() || NONE_RECORDED} />
        <Row label="Relevant history" value={patient.medical_history?.trim() || NONE_RECORDED} />
        <Row label="Previous surgery" value={patient.previous_surgeries?.trim() || NONE_RECORDED} />
      </Section>

      <Section title="Self-report">
        <Row
          label="NRS 0 to 10"
          value={assessment.self_report !== null ? `${assessment.self_report} / 10` : 'Not recorded'}
        />
        <Row label="Note" value={assessment.self_report_detail?.note?.trim() || NONE_RECORDED} />
        <Row
          label="AI estimate"
          value={
            assessment.prediction?.estimated_pain != null
              ? `${assessment.prediction.estimated_pain.toFixed(1)} / 10, shown for comparison only`
              : 'Not estimated'
          }
        />
      </Section>

      <Section title="Measured values">
        {assessment.measurement ? (
          <>
            <Row label="Heart rate" value={assessment.measurement.hr != null ? `${assessment.measurement.hr} bpm` : NONE_RECORDED} />
            <Row label="Respiratory rate" value={assessment.measurement.resp_rate != null ? `${assessment.measurement.resp_rate} /min` : NONE_RECORDED} />
            <Row
              label="Blood pressure"
              value={
                assessment.measurement.sbp != null && assessment.measurement.dbp != null
                  ? `${assessment.measurement.sbp}/${assessment.measurement.dbp} mmHg`
                  : NONE_RECORDED
              }
            />
            <Row label="Oxygen saturation" value={assessment.measurement.spo2 != null ? `${assessment.measurement.spo2} %` : NONE_RECORDED} />
            <Row label="Temperature" value={assessment.measurement.temperature_c != null ? `${assessment.measurement.temperature_c} °C` : NONE_RECORDED} />
            <Row label="Blood glucose" value={assessment.measurement.glucose_mmol != null ? `${assessment.measurement.glucose_mmol} mmol/L` : NONE_RECORDED} />
            <Row
              label="Weight, height, BMI"
              value={
                assessment.measurement.bmi != null
                  ? `${assessment.measurement.weight_kg} kg, ${assessment.measurement.height_cm} cm, BMI ${assessment.measurement.bmi}`
                  : NONE_RECORDED
              }
            />
          </>
        ) : (
          <Row label="Vital signs" value={NONE_RECORDED} />
        )}
      </Section>
    </div>
  );
};
