import type { UseFormRegister, FieldErrors } from 'react-hook-form'

import { useDiseases } from '@/api/queries'
import { Chip, ChipGroup } from '@/components/ui/choice'
import { Field, Fieldset, Input, Select, Textarea } from '@/components/ui/field'
import type { Medication } from '@/api/types'
import type { PatientForm } from '@/validation/schemas'
import { Button } from '@/components/ui/button'
import { Trash2 } from 'lucide-react'

export function IdentityFields({
  register,
  errors,
}: {
  register: UseFormRegister<PatientForm>
  errors: FieldErrors<PatientForm>
}) {
  return (
    <Fieldset
      legend="Identity"
      description="Stored encrypted under a key of its own. No identity card number is collected."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Given name" error={errors.given_name?.message} required>
          {(props) => <Input {...props} {...register('given_name')} autoComplete="off" />}
        </Field>
        <Field label="Family name" error={errors.family_name?.message} required>
          {(props) => <Input {...props} {...register('family_name')} autoComplete="off" />}
        </Field>
        <Field label="Telephone" error={errors.phone?.message}>
          {(props) => <Input {...props} {...register('phone')} type="tel" autoComplete="off" />}
        </Field>
        <Field label="Ward or unit" error={errors.ward?.message}>
          {(props) => <Input {...props} {...register('ward')} autoComplete="off" />}
        </Field>
        <Field label="Emergency contact" error={errors.emergency_contact_name?.message}>
          {(props) => <Input {...props} {...register('emergency_contact_name')} autoComplete="off" />}
        </Field>
        <Field label="Emergency contact telephone" error={errors.emergency_contact_phone?.message}>
          {(props) => (
            <Input {...props} {...register('emergency_contact_phone')} type="tel" autoComplete="off" />
          )}
        </Field>
      </div>
    </Fieldset>
  )
}

export function DemographicFields({
  register,
  errors,
}: {
  register: UseFormRegister<PatientForm>
  errors: FieldErrors<PatientForm>
}) {
  return (
    <Fieldset legend="Demographics">
      <div className="grid gap-4 sm:grid-cols-3">
        <Field label="Date of birth" error={errors.birth_date?.message}>
          {(props) => <Input {...props} {...register('birth_date')} type="date" />}
        </Field>
        <Field label="Sex" error={errors.sex?.message}>
          {(props) => (
            <Select {...props} {...register('sex')}>
              <option value="F">Female</option>
              <option value="M">Male</option>
              <option value="OTHER">Other</option>
              <option value="UNDISCLOSED">Not disclosed</option>
            </Select>
          )}
        </Field>
        <Field label="Smoking status" error={errors.smoking_status?.message}>
          {(props) => (
            <Select {...props} {...register('smoking_status')}>
              <option value="UNKNOWN">Not known</option>
              <option value="NEVER">Never smoked</option>
              <option value="FORMER">Former smoker</option>
              <option value="CURRENT">Current smoker</option>
            </Select>
          )}
        </Field>
      </div>
    </Fieldset>
  )
}

export function ConditionPicker({
  selected,
  onToggle,
}: {
  selected: string[]
  onToggle: (code: string) => void
}) {
  const diseases = useDiseases()
  const groups = new Map<string, { code: string; label: string }[]>()
  for (const disease of diseases.data ?? []) {
    const list = groups.get(disease.category) ?? []
    list.push(disease)
    groups.set(disease.category, list)
  }

  return (
    <Fieldset
      legend="Chronic conditions"
      description="Attached to the patient, not to one assessment. Not every condition causes pain."
    >
      <div className="space-y-3">
        {[...groups.entries()].map(([category, entries]) => (
          <div key={category}>
            <p className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">
              {category.toLowerCase().replaceAll('_', ' ')}
            </p>
            <ChipGroup>
              {entries.map((disease) => (
                <Chip
                  key={disease.code}
                  selected={selected.includes(disease.code)}
                  onClick={() => onToggle(disease.code)}
                >
                  {disease.label}
                </Chip>
              ))}
            </ChipGroup>
          </div>
        ))}
      </div>
    </Fieldset>
  )
}

export function MedicationEditor({
  medications,
  onChange,
}: {
  medications: Medication[]
  onChange: (next: Medication[]) => void
}) {
  const update = (index: number, patch: Partial<Medication>) =>
    onChange(medications.map((item, position) => (position === index ? { ...item, ...patch } : item)))

  return (
    <Fieldset legend="Current medication">
      <div className="space-y-2">
        {medications.map((medication, index) => (
          <div key={index} className="grid gap-2 sm:grid-cols-[2fr_1fr_1.2fr_auto]">
            <Input
              value={medication.name}
              onChange={(event) => update(index, { name: event.target.value })}
              placeholder="Name"
              aria-label={`Medication ${index + 1} name`}
            />
            <Input
              value={medication.dose ?? ''}
              onChange={(event) => update(index, { dose: event.target.value })}
              placeholder="Dose"
              aria-label={`Medication ${index + 1} dose`}
            />
            <Input
              value={medication.frequency ?? ''}
              onChange={(event) => update(index, { frequency: event.target.value })}
              placeholder="Frequency"
              aria-label={`Medication ${index + 1} frequency`}
            />
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-label={`Remove medication ${index + 1}`}
              onClick={() => onChange(medications.filter((_, position) => position !== index))}
            >
              <Trash2 aria-hidden className="size-4" />
            </Button>
          </div>
        ))}
        <Button
          type="button"
          variant="secondary"
          size="sm"
          onClick={() => onChange([...medications, { name: '' }])}
        >
          Add a medication
        </Button>
      </div>
    </Fieldset>
  )
}

export function HistoryFields({
  register,
}: {
  register: UseFormRegister<PatientForm>
}) {
  return (
    <Fieldset legend="Relevant history">
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Medical history">
          {(props) => <Textarea {...props} {...register('medical_history')} rows={3} />}
        </Field>
        <Field label="Previous surgery">
          {(props) => <Textarea {...props} {...register('previous_surgeries')} rows={3} />}
        </Field>
        <Field label="Allergies">
          {(props) => <Textarea {...props} {...register('allergies')} rows={2} />}
        </Field>
        <Field label="Family history">
          {(props) => <Textarea {...props} {...register('family_history')} rows={2} />}
        </Field>
      </div>
    </Fieldset>
  )
}
