import type { Question } from '@/api/types'
import { Chip, ChipGroup, Checkbox } from '@/components/ui/choice'
import { Field, Input, Select, Textarea } from '@/components/ui/field'

type Answer = unknown

/**
 * Renders whatever the question engine returned.
 *
 * Nothing about which question to ask, or when, lives in here. The server decides the set
 * from the picture so far; this only knows how to draw the five kinds of control.
 */
export function QuestionField({
  question,
  value,
  onChange,
}: {
  question: Question
  value: Answer
  onChange: (next: Answer) => void
}) {
  if (question.kind === 'BOOL') {
    return (
      <div className="space-y-1.5">
        <Checkbox
          checked={value === true}
          onChange={(next) => onChange(next ? true : false)}
          label={question.prompt}
          hint={question.help_text || undefined}
        />
        {value !== undefined && (
          <button
            type="button"
            onClick={() => onChange(undefined)}
            className="ml-6.5 text-xs text-muted underline hover:text-ink"
          >
            Clear answer
          </button>
        )}
      </div>
    )
  }

  if (question.kind === 'MULTI') {
    const selected = Array.isArray(value) ? (value as string[]) : []
    return (
      <Field label={question.prompt} hint={question.help_text || undefined}>
        {() => (
          <ChipGroup>
            {question.options.map((option) => (
              <Chip
                key={option.value}
                selected={selected.includes(option.value)}
                onClick={() =>
                  onChange(
                    selected.includes(option.value)
                      ? selected.filter((item) => item !== option.value)
                      : [...selected, option.value],
                  )
                }
              >
                {option.label}
              </Chip>
            ))}
          </ChipGroup>
        )}
      </Field>
    )
  }

  if (question.kind === 'SINGLE') {
    return (
      <Field label={question.prompt} hint={question.help_text || undefined}>
        {(props) => (
          <Select
            {...props}
            value={typeof value === 'string' ? value : ''}
            onChange={(event) => onChange(event.target.value || undefined)}
          >
            <option value="">Not recorded</option>
            {question.options.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </Select>
        )}
      </Field>
    )
  }

  if (question.kind === 'NUMBER') {
    return (
      <Field
        label={question.prompt}
        hint={question.help_text || (question.unit ? `In ${question.unit}.` : undefined)}
      >
        {(props) => (
          <Input
            {...props}
            type="number"
            inputMode="decimal"
            min={question.minimum ?? undefined}
            max={question.maximum ?? undefined}
            value={typeof value === 'number' ? value : ''}
            onChange={(event) =>
              onChange(event.target.value === '' ? undefined : Number(event.target.value))
            }
          />
        )}
      </Field>
    )
  }

  return (
    <Field label={question.prompt} hint={question.help_text || undefined}>
      {(props) => (
        <Textarea
          {...props}
          rows={2}
          value={typeof value === 'string' ? value : ''}
          onChange={(event) => onChange(event.target.value || undefined)}
        />
      )}
    </Field>
  )
}
