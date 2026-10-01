import React, { useState } from 'react';
import { Plus, Save, X } from 'lucide-react';

import { ApiError, request } from '../api/client';
import type { PatientDetail, SmokingStatus, Ward } from '../api/types';
import { WARDS } from '../api/types';
import { Button } from '../ui/Button';
import { Select } from '../ui/Dropdown';
import { Choice, TextField } from '../ui/Field';
import { SMOKING_LABEL } from '../lib/clinical';
import { phoneError } from '../lib/phone';

export interface PatientFormValues {
  given_name: string;
  family_name: string;
  sex: 'F' | 'M' | '';
  age_years: string;
  birth_date: string;
  ward: Ward | null;
  phone: string;
  emergency_contact_name: string;
  emergency_contact_phone: string;
  smoking_status: SmokingStatus;
}

export const EMPTY_PATIENT: PatientFormValues = {
  given_name: '',
  family_name: '',
  sex: '',
  age_years: '',
  birth_date: '',
  ward: null,
  phone: '',
  emergency_contact_name: '',
  emergency_contact_phone: '',
  smoking_status: 'UNKNOWN',
};

export function patientFormFrom(record: PatientDetail): PatientFormValues {
  return {
    given_name: record.identity?.given_name ?? '',
    family_name: record.identity?.family_name ?? '',
    sex: record.sex === 'F' || record.sex === 'M' ? record.sex : '',
    age_years: record.age_years !== null ? String(record.age_years) : record.age !== null ? String(record.age) : '',
    birth_date: record.birth_date ?? '',
    ward: record.ward,
    phone: record.identity?.phone ?? '',
    emergency_contact_name: record.identity?.emergency_contact_name ?? '',
    emergency_contact_phone: record.identity?.emergency_contact_phone ?? '',
    smoking_status: record.smoking_status,
  };
}

function ageFromBirthDate(value: string): number | null {
  const born = new Date(value);
  if (Number.isNaN(born.getTime())) return null;
  const today = new Date();
  let years = today.getFullYear() - born.getFullYear();
  if (
    today.getMonth() < born.getMonth() ||
    (today.getMonth() === born.getMonth() && today.getDate() < born.getDate())
  ) {
    years -= 1;
  }
  return years;
}

export type PatientFormErrors = Partial<Record<keyof PatientFormValues, string>>;

export function validatePatient(values: PatientFormValues): PatientFormErrors {
  const errors: PatientFormErrors = {};
  if (!values.given_name.trim()) errors.given_name = 'Required.';
  if (!values.family_name.trim()) errors.family_name = 'Required.';
  if (values.sex === '') errors.sex = 'Choose F or M.';
  const age = Number(values.age_years);
  if (values.age_years.trim() === '' || !Number.isInteger(age) || age < 0 || age > 120) {
    errors.age_years = 'A whole number between 0 and 120.';
  }
  if (values.birth_date && (ageFromBirthDate(values.birth_date) ?? -1) < 0) {
    errors.birth_date = 'The date of birth is in the future.';
  }
  const phone = phoneError(values.phone);
  if (phone) errors.phone = phone;
  const contact = phoneError(values.emergency_contact_phone);
  if (contact) errors.emergency_contact_phone = contact;
  if (values.emergency_contact_phone.trim() && !values.emergency_contact_name.trim()) {
    errors.emergency_contact_name = 'Name the person this number belongs to.';
  }
  return errors;
}

export function patientPayload(values: PatientFormValues) {
  return {
    identity: {
      given_name: values.given_name.trim(),
      family_name: values.family_name.trim(),
      phone: values.phone.trim() || null,
      emergency_contact_name: values.emergency_contact_name.trim() || null,
      emergency_contact_phone: values.emergency_contact_phone.trim() || null,
    },
    sex: values.sex,
    age_years: Number(values.age_years),
    birth_date: values.birth_date || null,
    ward: values.ward,
    smoking_status: values.smoking_status,
  };
}

const Labelled: React.FC<{ label: string; error?: string; children: React.ReactNode }> = ({
  label,
  error,
  children,
}) => (
  <div className="space-y-1.5">
    <span className="block text-xs font-medium text-soft">{label}</span>
    {children}
    {error && <p className="text-[11px] text-danger">{error}</p>}
  </div>
);

export const PatientFields: React.FC<{
  values: PatientFormValues;
  errors: PatientFormErrors;
  onChange: (values: PatientFormValues) => void;
  /** The platform's identifier, shown read-only once the record exists. */
  code?: string;
}> = ({ values, errors, onChange, code }) => {
  const set = <K extends keyof PatientFormValues>(key: K, value: PatientFormValues[K]) =>
    onChange({ ...values, [key]: value });

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
      <TextField
        label="Given name"
        required
        value={values.given_name}
        error={errors.given_name}
        onChange={(event) => set('given_name', event.target.value)}
      />
      <TextField
        label="Family name"
        required
        value={values.family_name}
        error={errors.family_name}
        onChange={(event) => set('family_name', event.target.value)}
      />
      <TextField
        label="Internal identifier"
        value={code ?? 'Assigned on save'}
        readOnly
        hint="PS-YYYY-NNNNNN, issued by the platform and never edited."
      />
      <TextField
        label="Age"
        type="number"
        required
        min={0}
        max={120}
        step={1}
        trailing={<span className="text-[11px] text-faint">years</span>}
        value={values.age_years}
        error={errors.age_years}
        onChange={(event) => set('age_years', event.target.value)}
      />
      <TextField
        label="Date of birth"
        type="date"
        value={values.birth_date}
        error={errors.birth_date}
        hint="Optional. When given, the age follows from it."
        onChange={(event) => {
          const birth = event.target.value;
          const derived = birth ? ageFromBirthDate(birth) : null;
          onChange({
            ...values,
            birth_date: birth,
            age_years: derived !== null && derived >= 0 ? String(derived) : values.age_years,
          });
        }}
      />
      <Labelled label="Sex" error={errors.sex}>
        <div className="flex gap-1.5">
          {(['F', 'M'] as const).map((value) => (
            <Choice
              key={value}
              kind="radio"
              checked={values.sex === value}
              onClick={() => set('sex', value)}
            >
              {value === 'F' ? 'F · Female' : 'M · Male'}
            </Choice>
          ))}
        </div>
      </Labelled>
      <Labelled label="Ward" error={errors.ward}>
        <Select
          label="Choose a ward"
          className="w-full [&>button]:w-full"
          clearable
          options={WARDS.map((ward) => ({ value: ward, label: ward }))}
          value={values.ward}
          onChange={(value) => set('ward', (value as Ward | null) ?? null)}
        />
      </Labelled>
      <TextField
        label="Telephone"
        type="tel"
        inputMode="tel"
        value={values.phone}
        error={errors.phone}
        hint="Algerian number, with or without +213."
        onChange={(event) => set('phone', event.target.value)}
      />
      <Labelled label="Smoking status">
        <Select
          label="Smoking status"
          className="w-full [&>button]:w-full"
          options={(Object.keys(SMOKING_LABEL) as SmokingStatus[]).map((value) => ({
            value,
            label: SMOKING_LABEL[value],
          }))}
          value={values.smoking_status}
          onChange={(value) => set('smoking_status', (value as SmokingStatus | null) ?? 'UNKNOWN')}
        />
      </Labelled>
      <TextField
        label="Emergency contact"
        value={values.emergency_contact_name}
        error={errors.emergency_contact_name}
        onChange={(event) => set('emergency_contact_name', event.target.value)}
      />
      <TextField
        label="Emergency contact telephone"
        type="tel"
        inputMode="tel"
        value={values.emergency_contact_phone}
        error={errors.emergency_contact_phone}
        onChange={(event) => set('emergency_contact_phone', event.target.value)}
      />
    </div>
  );
};

/**
 * The register-or-edit dialog. One component for both because the fields are the same
 * and the only difference is the verb and the route the payload goes to.
 */
export const PatientDialog: React.FC<{
  existing?: PatientDetail;
  onClose: () => void;
  onSaved: (patient: PatientDetail) => void;
}> = ({ existing, onClose, onSaved }) => {
  const [values, setValues] = useState<PatientFormValues>(
    existing ? patientFormFrom(existing) : EMPTY_PATIENT,
  );
  const [errors, setErrors] = useState<PatientFormErrors>({});
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = async () => {
    const found = validatePatient(values);
    setErrors(found);
    if (Object.keys(found).length > 0) return;
    setBusy(true);
    setFailure(null);
    try {
      const saved = existing
        ? await request<PatientDetail>(`/api/patients/${existing.id}`, {
            method: 'PATCH',
            body: patientPayload(values),
          })
        : await request<PatientDetail>('/api/patients', {
            method: 'POST',
            body: patientPayload(values),
          });
      onSaved(saved);
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The record could not be saved.');
      setBusy(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center overflow-y-auto bg-[#0b1b33]/40 px-4 py-[6vh] backdrop-blur-[2px]"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal
        aria-label={existing ? 'Edit the patient record' : 'Register a patient'}
        className="w-full max-w-3xl rounded-2xl border border-hairline bg-surface p-5 shadow-pop"
      >
        <div className="flex items-start justify-between gap-4 pb-4">
          <div>
            <h2 className="text-[17px] font-semibold text-ink">
              {existing ? 'Edit the patient record' : 'Register a patient'}
            </h2>
            <p className="mt-1 text-[12px] text-mute">
              Name, age and sex are required. The name and telephone numbers are sealed at
              rest.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-faint hover:bg-sunken hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {failure && (
          <p className="mb-4 rounded-[10px] border border-danger/25 bg-danger/8 px-3 py-2 text-[12px] text-danger">
            {failure}
          </p>
        )}

        <PatientFields values={values} errors={errors} onChange={setValues} code={existing?.code} />

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon={existing ? <Save className="h-4 w-4" /> : <Plus className="h-4 w-4" />}
            disabled={busy}
            onClick={() => void submit()}
          >
            {busy ? 'Saving…' : existing ? 'Save changes' : 'Register'}
          </Button>
        </div>
      </div>
    </div>
  );
};
