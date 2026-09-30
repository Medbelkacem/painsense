import { Field, Textarea } from '@/components/ui/field'
import { Notice } from '@/components/ui/feedback'
import { cn } from '@/utils/cn'
import type { Draft } from './draft'

const SCORES = Array.from({ length: 11 }, (_, index) => index)

export function SelfReportStep({
  draft,
  update,
}: {
  draft: Draft
  update: (patch: Partial<Draft>) => void
}) {
  return (
    <div className="space-y-5">
      <Notice tone="info" title="Recorded separately from the estimate">
        The patient&rsquo;s own score is kept apart from everything the model reads. It is the
        reference the model is measured against, never an input to it, and the report prints the two
        side by side rather than merging them.
      </Notice>

      <fieldset>
        <legend className="mb-2 text-sm font-semibold text-ink">
          Patient-reported score, 0 to 10
        </legend>
        <div className="flex flex-wrap gap-1.5">
          {SCORES.map((score) => (
            <button
              key={score}
              type="button"
              aria-pressed={draft.self_report_nrs === score}
              onClick={() =>
                update({ self_report_nrs: draft.self_report_nrs === score ? null : score })
              }
              className={cn(
                'size-11 rounded-md border text-sm font-medium transition-colors tabular',
                draft.self_report_nrs === score
                  ? 'border-accent bg-accent text-white'
                  : 'border-line bg-surface text-body hover:border-line-strong hover:bg-canvas',
              )}
            >
              {score}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted">
          0 is no pain, 10 is the worst pain imaginable. Leave it unset if the patient cannot give a
          score.
        </p>
      </fieldset>

      <Field label="Note on how the score was given">
        {(props) => (
          <Textarea
            {...props}
            rows={3}
            value={draft.self_report_note}
            onChange={(event) => update({ self_report_note: event.target.value })}
            placeholder="For example: reported through a relative, or given reluctantly"
          />
        )}
      </Field>
    </div>
  )
}
