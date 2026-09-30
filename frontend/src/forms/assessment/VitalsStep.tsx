import { useVitalRanges } from '@/api/queries'
import type { Measurement } from '@/api/types'
import { Field, Input } from '@/components/ui/field'
import { Notice, Spinner } from '@/components/ui/feedback'
import type { Draft } from './draft'

type VitalKey = keyof Measurement

const FIELDS: { key: VitalKey; label: string; unit: string; step?: string }[] = [
  { key: 'hr', label: 'Heart rate', unit: 'beats/min' },
  { key: 'resp_rate', label: 'Respiratory rate', unit: 'breaths/min' },
  { key: 'sbp', label: 'Systolic blood pressure', unit: 'mmHg' },
  { key: 'dbp', label: 'Diastolic blood pressure', unit: 'mmHg' },
  { key: 'spo2', label: 'Oxygen saturation', unit: '%' },
  { key: 'temperature_c', label: 'Temperature', unit: '°C', step: '0.1' },
  { key: 'glucose_mmol', label: 'Blood glucose', unit: 'mmol/L', step: '0.1' },
  { key: 'weight_kg', label: 'Weight', unit: 'kg', step: '0.1' },
  { key: 'height_cm', label: 'Height', unit: 'cm' },
]

export function VitalsStep({
  draft,
  update,
}: {
  draft: Draft
  update: (patch: Partial<Draft>) => void
}) {
  const ranges = useVitalRanges()
  if (ranges.isPending) return <Spinner />

  const rangeFor = (key: VitalKey) => ranges.data?.find((entry) => entry.field === key)

  const set = (key: VitalKey, raw: string) =>
    update({
      measurement: { ...draft.measurement, [key]: raw === '' ? null : Number(raw) },
    })

  const bmi = (() => {
    const { weight_kg, height_cm } = draft.measurement
    if (!weight_kg || !height_cm) return null
    return Math.round((weight_kg / (height_cm / 100) ** 2) * 10) / 10
  })()

  return (
    <div className="space-y-5">
      <Notice tone="info">
        These are values the clinician measured during the examination. The platform measures
        nothing itself. Anything left blank stays missing, and the model treats it as missing rather
        than filling it in.
      </Notice>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {FIELDS.map((field) => {
          const range = rangeFor(field.key)
          const value = draft.measurement[field.key]
          const outsideReference =
            typeof value === 'number' &&
            range?.reference_min !== null &&
            range?.reference_max !== null &&
            range !== undefined &&
            (value < (range.reference_min ?? -Infinity) || value > (range.reference_max ?? Infinity))

          return (
            <Field
              key={field.key}
              label={`${field.label} (${field.unit})`}
              hint={
                outsideReference
                  ? `Outside the usual range of ${range?.reference_min}–${range?.reference_max}. Stored as entered.`
                  : range
                    ? `Accepted between ${range.accepted_min} and ${range.accepted_max}.`
                    : undefined
              }
            >
              {(props) => (
                <Input
                  {...props}
                  type="number"
                  inputMode="decimal"
                  step={field.step}
                  min={range?.accepted_min}
                  max={range?.accepted_max}
                  value={value ?? ''}
                  onChange={(event) => set(field.key, event.target.value)}
                  className={outsideReference ? 'border-caution focus:border-caution' : undefined}
                />
              )}
            </Field>
          )
        })}
      </div>

      {bmi !== null && (
        <p className="text-[0.8125rem] text-muted">
          Body mass index <span className="font-semibold text-ink tabular">{bmi}</span>, derived from
          the weight and height above.
        </p>
      )}
    </div>
  )
}
