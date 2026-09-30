import { useFactors, useQualities } from '@/api/queries'
import type { Course, Onset, Pattern } from '@/api/types'
import { Checkbox, Chip, ChipGroup, SegmentedControl } from '@/components/ui/choice'
import { Field, Fieldset, Input, Textarea } from '@/components/ui/field'
import { Spinner } from '@/components/ui/feedback'
import type { Draft } from './draft'

const ONSET: { value: Onset; label: string }[] = [
  { value: 'SUDDEN', label: 'Sudden' },
  { value: 'GRADUAL', label: 'Gradual' },
  { value: 'UNKNOWN', label: 'Not known' },
]

const PATTERN: { value: Pattern; label: string }[] = [
  { value: 'CONSTANT', label: 'Constant' },
  { value: 'INTERMITTENT', label: 'Intermittent' },
  { value: 'EPISODIC', label: 'Episodic' },
  { value: 'UNKNOWN', label: 'Not known' },
]

const COURSE: { value: Course; label: string }[] = [
  { value: 'IMPROVING', label: 'Improving' },
  { value: 'STABLE', label: 'Stable' },
  { value: 'WORSENING', label: 'Worsening' },
  { value: 'PROGRESSIVE', label: 'Progressive' },
  { value: 'UNKNOWN', label: 'Not known' },
]

/** Duration is entered in whatever unit suits the case and stored in hours. */
const UNITS = [
  { label: 'hours', factor: 1 },
  { label: 'days', factor: 24 },
  { label: 'weeks', factor: 168 },
  { label: 'months', factor: 720 },
]

export function CharacterStep({
  draft,
  update,
}: {
  draft: Draft
  update: (patch: Partial<Draft>) => void
}) {
  const qualities = useQualities()
  const factors = useFactors()
  if (qualities.isPending || factors.isPending) return <Spinner />

  const toggle = (key: 'quality_codes' | 'factor_codes', code: string) =>
    update({
      [key]: draft[key].includes(code)
        ? draft[key].filter((item) => item !== code)
        : [...draft[key], code],
    })

  return (
    <div className="space-y-7">
      <Fieldset
        legend="Character of the pain"
        description="Choose everything that applies. Some descriptors are associated with neuropathic pain, which the model reads as one signal among many."
      >
        <ChipGroup>
          {qualities.data?.map((quality) => (
            <Chip
              key={quality.code}
              selected={draft.quality_codes.includes(quality.code)}
              onClick={() => toggle('quality_codes', quality.code)}
            >
              {quality.label}
            </Chip>
          ))}
        </ChipGroup>
      </Fieldset>

      <Fieldset legend="Time course">
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[0.8125rem] font-medium text-body">Onset</span>
            <SegmentedControl
              label="Onset"
              value={draft.onset}
              onChange={(onset) => update({ onset })}
              options={ONSET}
            />
          </div>
          <DurationField draft={draft} update={update} />
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[0.8125rem] font-medium text-body">Pattern</span>
            <SegmentedControl
              label="Pattern"
              value={draft.pattern}
              onChange={(pattern) => update({ pattern })}
              options={PATTERN}
            />
          </div>
          {draft.pattern === 'EPISODIC' && (
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Episodes per day">
                {(props) => (
                  <Input
                    {...props}
                    type="number"
                    min={0}
                    max={100}
                    value={draft.episodes_per_day ?? ''}
                    onChange={(event) =>
                      update({
                        episodes_per_day: event.target.value ? Number(event.target.value) : null,
                      })
                    }
                  />
                )}
              </Field>
              <Field label="Length of each episode" hint="In minutes.">
                {(props) => (
                  <Input
                    {...props}
                    type="number"
                    min={0}
                    value={draft.episode_minutes ?? ''}
                    onChange={(event) =>
                      update({
                        episode_minutes: event.target.value ? Number(event.target.value) : null,
                      })
                    }
                  />
                )}
              </Field>
            </div>
          )}
          <div className="flex flex-wrap items-center gap-3">
            <span className="text-[0.8125rem] font-medium text-body">Course</span>
            <SegmentedControl
              label="Course"
              value={draft.course}
              onChange={(course) => update({ course })}
              options={COURSE}
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-2">
            <Checkbox
              checked={draft.night_pain}
              onChange={(night_pain) => update({ night_pain })}
              label="Worse at night"
            />
            <Checkbox
              checked={draft.morning_pain}
              onChange={(morning_pain) => update({ morning_pain })}
              label="Worse in the morning"
            />
            <Checkbox
              checked={draft.pain_after_activity}
              onChange={(pain_after_activity) => update({ pain_after_activity })}
              label="Worse after activity"
            />
            <Checkbox
              checked={draft.pain_at_rest}
              onChange={(pain_at_rest) => update({ pain_at_rest })}
              label="Present at rest"
            />
          </div>
        </div>
      </Fieldset>

      <Fieldset legend="Radiation">
        <div className="space-y-3">
          <Checkbox
            checked={draft.radiates}
            onChange={(radiates) => update({ radiates })}
            label="The pain radiates"
          />
          {draft.radiates && (
            <div className="space-y-3 border-l-2 border-line pl-4">
              <Field label="Where does it radiate to?">
                {(props) => (
                  <Textarea
                    {...props}
                    rows={2}
                    value={draft.radiation_description}
                    onChange={(event) => update({ radiation_description: event.target.value })}
                    placeholder="Direction and how far it travels"
                  />
                )}
              </Field>
              <div className="grid gap-2 sm:grid-cols-3">
                <Checkbox
                  checked={draft.radiation_numbness}
                  onChange={(radiation_numbness) => update({ radiation_numbness })}
                  label="With numbness"
                />
                <Checkbox
                  checked={draft.radiation_tingling}
                  onChange={(radiation_tingling) => update({ radiation_tingling })}
                  label="With tingling"
                />
                <Checkbox
                  checked={draft.radiation_weakness}
                  onChange={(radiation_weakness) => update({ radiation_weakness })}
                  label="With weakness"
                />
              </div>
            </div>
          )}
        </div>
      </Fieldset>

      <div className="grid gap-6 sm:grid-cols-2">
        <Fieldset legend="What makes it worse">
          <ChipGroup>
            {factors.data
              ?.filter((factor) => factor.kind === 'AGGRAVATING')
              .map((factor) => (
                <Chip
                  key={factor.code}
                  selected={draft.factor_codes.includes(factor.code)}
                  onClick={() => toggle('factor_codes', factor.code)}
                >
                  {factor.label}
                </Chip>
              ))}
          </ChipGroup>
        </Fieldset>
        <Fieldset legend="What makes it better">
          <ChipGroup>
            {factors.data
              ?.filter((factor) => factor.kind === 'RELIEVING')
              .map((factor) => (
                <Chip
                  key={factor.code}
                  selected={draft.factor_codes.includes(factor.code)}
                  onClick={() => toggle('factor_codes', factor.code)}
                >
                  {factor.label}
                </Chip>
              ))}
          </ChipGroup>
        </Fieldset>
      </div>

      <Fieldset legend="Setting">
        <div className="grid gap-2 sm:grid-cols-2">
          <Checkbox
            checked={draft.recent_trauma}
            onChange={(recent_trauma) => update({ recent_trauma })}
            label="Recent injury or trauma"
          />
          <Checkbox
            checked={draft.recent_surgery}
            onChange={(recent_surgery) => update({ recent_surgery })}
            label="Surgery in the last 30 days"
          />
        </div>
      </Fieldset>
    </div>
  )
}

function DurationField({
  draft,
  update,
}: {
  draft: Draft
  update: (patch: Partial<Draft>) => void
}) {
  const hours = draft.duration_hours
  const unit = pickUnit(hours)
  const shown = hours === null ? '' : Math.round((hours / unit.factor) * 10) / 10

  return (
    <div className="flex flex-wrap items-end gap-2">
      <Field label="How long has it been going on?" className="w-40">
        {(props) => (
          <Input
            {...props}
            type="number"
            min={0}
            step="0.5"
            value={shown}
            onChange={(event) =>
              update({
                duration_hours: event.target.value ? Number(event.target.value) * unit.factor : null,
              })
            }
          />
        )}
      </Field>
      <select
        value={unit.label}
        aria-label="Duration unit"
        onChange={(event) => {
          const next = UNITS.find((entry) => entry.label === event.target.value)!
          update({ duration_hours: shown === '' ? null : Number(shown) * next.factor })
        }}
        className="mb-0.5 rounded-md border border-line bg-surface px-2 py-2 text-sm text-body"
      >
        {UNITS.map((entry) => (
          <option key={entry.label} value={entry.label}>
            {entry.label}
          </option>
        ))}
      </select>
    </div>
  )
}

function pickUnit(hours: number | null) {
  if (hours === null) return UNITS[0]
  return (
    [...UNITS].reverse().find((unit) => hours >= unit.factor && hours % unit.factor === 0) ??
    (hours >= 720 ? UNITS[3] : hours >= 168 ? UNITS[2] : hours >= 24 ? UNITS[1] : UNITS[0])
  )
}
