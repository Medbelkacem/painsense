import { useConfounders, useSymptoms } from '@/api/queries'
import { Chip, ChipGroup } from '@/components/ui/choice'
import { Fieldset } from '@/components/ui/field'
import { Notice, Spinner } from '@/components/ui/feedback'
import type { Draft } from './draft'

export function SymptomsStep({
  draft,
  update,
}: {
  draft: Draft
  update: (patch: Partial<Draft>) => void
}) {
  const symptoms = useSymptoms()
  const confounders = useConfounders()
  if (symptoms.isPending || confounders.isPending) return <Spinner />

  const toggle = (key: 'symptom_codes' | 'confounder_codes', code: string) =>
    update({
      [key]: draft[key].includes(code)
        ? draft[key].filter((item) => item !== code)
        : [...draft[key], code],
    })

  const groups = new Map<string, typeof symptoms.data>()
  for (const symptom of symptoms.data ?? []) {
    const list = groups.get(symptom.group) ?? []
    list.push(symptom)
    groups.set(symptom.group, list)
  }

  return (
    <div className="space-y-7">
      <Fieldset
        legend="Associated symptoms"
        description="Some of these are read by the red-flag rules, which run whether or not an estimate is produced."
      >
        <div className="space-y-3">
          {[...groups.entries()].map(([group, entries]) => (
            <div key={group}>
              <p className="mb-1.5 text-xs font-medium tracking-wide text-muted uppercase">
                {group.toLowerCase()}
              </p>
              <ChipGroup>
                {entries?.map((symptom) => (
                  <Chip
                    key={symptom.code}
                    tone={symptom.alarm ? 'alert' : 'neutral'}
                    selected={draft.symptom_codes.includes(symptom.code)}
                    onClick={() => toggle('symptom_codes', symptom.code)}
                  >
                    {symptom.label}
                  </Chip>
                ))}
              </ChipGroup>
            </div>
          ))}
        </div>
      </Fieldset>

      <Fieldset
        legend="Context that can affect the measured values"
        description="Recording these is what lets the platform say a raised heart rate has another explanation, rather than reading it as pain."
      >
        <div className="space-y-2">
          <ChipGroup>
            {confounders.data?.map((confounder) => (
              <Chip
                key={confounder.code}
                selected={draft.confounder_codes.includes(confounder.code)}
                onClick={() => toggle('confounder_codes', confounder.code)}
              >
                {confounder.label}
              </Chip>
            ))}
          </ChipGroup>
          {draft.confounder_codes.length > 0 && (
            <Notice tone="info">
              <ul className="space-y-1">
                {confounders.data
                  ?.filter((entry) => draft.confounder_codes.includes(entry.code))
                  .map((entry) => (
                    <li key={entry.code}>
                      <span className="font-medium">{entry.label}.</span> {entry.note}
                    </li>
                  ))}
              </ul>
            </Notice>
          )}
        </div>
      </Fieldset>
    </div>
  )
}
