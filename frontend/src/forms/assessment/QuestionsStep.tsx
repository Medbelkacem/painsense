import { useMemo } from 'react'

import { useAnatomy, useApplicableQuestions } from '@/api/queries'
import type { PatientDetail, QuestionContext } from '@/api/types'
import { QuestionField } from '@/components/QuestionField'
import { EmptyState, Notice, Spinner } from '@/components/ui/feedback'
import { locationCodes, type Draft } from './draft'

/**
 * The questions come from the server for the picture recorded so far, and the set is
 * re-fetched as answers change because one answer can open another question.
 */
export function QuestionsStep({
  draft,
  update,
  patient,
}: {
  draft: Draft
  update: (patch: Partial<Draft>) => void
  patient: PatientDetail
}) {
  const anatomy = useAnatomy()
  // Left as the cached array rather than defaulted here: a fresh [] every render would
  // rebuild the context and re-ask the server for the question set on every keystroke.
  const structures = anatomy.data?.structures

  const context = useMemo<QuestionContext>(
    () => ({
      patient_id: patient.id,
      age: patient.age,
      sex: patient.sex,
      locations: locationCodes(draft, structures ?? []),
      quality_codes: draft.quality_codes,
      symptom_codes: draft.symptom_codes,
      factor_codes: draft.factor_codes,
      confounder_codes: draft.confounder_codes,
      onset: draft.onset,
      pattern: draft.pattern,
      course: draft.course,
      duration_hours: draft.duration_hours,
      radiates: draft.radiates,
      recent_trauma: draft.recent_trauma,
      recent_surgery: draft.recent_surgery,
      answers: draft.answers,
    }),
    [draft, patient, structures],
  )

  // Held back until the ontology is there, so the first request is not made with the
  // structures left out of the picture.
  const questions = useApplicableQuestions(context, !anatomy.isPending)
  if (anatomy.isPending || questions.isPending) {
    return <Spinner label="Working out which questions apply" />
  }

  const groups = new Map<string, { label: string; items: NonNullable<typeof questions.data> }>()
  for (const question of questions.data ?? []) {
    const bucket = groups.get(question.group) ?? { label: question.group_label, items: [] }
    bucket.items.push(question)
    groups.set(question.group, bucket)
  }

  const answered = Object.keys(draft.answers).filter(
    (code) => draft.answers[code] !== undefined,
  ).length

  return (
    <div className="space-y-6">
      <Notice tone="info">
        {questions.data?.length ?? 0} question{questions.data?.length === 1 ? '' : 's'} apply to this
        picture, {answered} answered. The set changes as you fill it in: answering one question can
        open another.
      </Notice>

      {groups.size === 0 ? (
        <EmptyState
          title="No questions apply yet"
          description="Record the site and character of the pain first."
        />
      ) : (
        [...groups.entries()].map(([code, group]) => (
          <section key={code} className="space-y-4">
            <h3 className="border-b border-line pb-1.5 text-sm font-semibold text-ink">
              {group.label}
            </h3>
            <div className="grid gap-4 sm:grid-cols-2">
              {group.items.map((question) => (
                <QuestionField
                  key={question.code}
                  question={question}
                  value={draft.answers[question.code]}
                  onChange={(value) =>
                    update({ answers: { ...draft.answers, [question.code]: value } })
                  }
                />
              ))}
            </div>
          </section>
        ))
      )}
    </div>
  )
}
