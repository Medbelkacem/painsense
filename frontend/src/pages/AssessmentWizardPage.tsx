import { ArrowLeft, ArrowRight, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'

import {
  useCreateAssessment,
  useDocuments,
  usePatient,
  useRunEstimate,
  useUpdateAssessment,
} from '@/api/queries'
import { DocumentPanel } from '@/components/DocumentPanel'
import { PageHeader } from '@/components/PageHeader'
import { SyntheticTag } from '@/components/tags'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Notice, QueryState } from '@/components/ui/feedback'
import { CharacterStep } from '@/forms/assessment/CharacterStep'
import { QuestionsStep } from '@/forms/assessment/QuestionsStep'
import { SelfReportStep } from '@/forms/assessment/SelfReportStep'
import { SiteStep } from '@/forms/assessment/SiteStep'
import { SymptomsStep } from '@/forms/assessment/SymptomsStep'
import { VitalsStep } from '@/forms/assessment/VitalsStep'
import { emptyDraft, toBody, toPayload, type Draft } from '@/forms/assessment/draft'
import { cn } from '@/utils/cn'

const STEPS = [
  { key: 'site', title: 'Site', blurb: 'Where is the pain?' },
  { key: 'character', title: 'Character', blurb: 'What is it like, and for how long?' },
  { key: 'symptoms', title: 'Symptoms', blurb: 'What comes with it, and in what context?' },
  { key: 'questions', title: 'Questions', blurb: 'Questions that apply to this case' },
  { key: 'vitals', title: 'Measurements', blurb: 'Values taken at the examination' },
  { key: 'documents', title: 'Documents', blurb: 'Reports and images on file' },
  { key: 'review', title: 'Review', blurb: "The patient's own score, then the estimate" },
] as const

export function AssessmentWizardPage() {
  const { patientId = '' } = useParams()
  const navigate = useNavigate()
  const patient = usePatient(patientId)

  const [step, setStep] = useState(0)
  const [draft, setDraft] = useState<Draft>(emptyDraft)
  const [assessmentId, setAssessmentId] = useState<string | null>(null)
  const [failure, setFailure] = useState<string | null>(null)

  const createAssessment = useCreateAssessment()
  const updateAssessment = useUpdateAssessment(assessmentId ?? '')
  const runEstimate = useRunEstimate(assessmentId ?? '')
  const documents = useDocuments(
    new URLSearchParams(assessmentId ? { assessment_id: assessmentId } : { patient_id: patientId }),
  )

  const update = (patch: Partial<Draft>) => setDraft((current) => ({ ...current, ...patch }))
  // Either surface counts: a structure recorded on the model also records a region.
  const noSiteYet = draft.locations.length === 0 && draft.anatomical_sites.length === 0

  const goTo = async (next: number) => {
    setFailure(null)
    // The document step needs a record to attach to, so the draft is saved on the way in.
    if (next >= 5 && !assessmentId) {
      try {
        const created = await createAssessment.mutateAsync(toPayload(draft, patientId))
        setAssessmentId(created.id)
      } catch (error) {
        setFailure(error instanceof Error ? error.message : 'The assessment could not be saved')
        return
      }
    }
    setStep(next)
  }

  const finish = async () => {
    setFailure(null)
    try {
      let id = assessmentId
      if (!id) {
        id = (await createAssessment.mutateAsync(toPayload(draft, patientId))).id
        setAssessmentId(id)
      } else {
        await updateAssessment.mutateAsync(toBody(draft))
      }
      await runEstimate.mutateAsync(undefined)
      navigate(`/assessments/${id}`)
    } catch (error) {
      setFailure(error instanceof Error ? error.message : 'The estimate could not be produced')
    }
  }

  const busy = createAssessment.isPending || updateAssessment.isPending || runEstimate.isPending

  return (
    <QueryState isPending={patient.isPending} error={patient.error}>
      {patient.data && (
        <>
          <PageHeader
            title="New assessment"
            description={`${patient.data.display_name} · ${patient.data.code} · ${
              patient.data.age ?? '—'
            } years`}
            meta={patient.data.is_synthetic && <SyntheticTag />}
          />

          <ol className="flex gap-1 overflow-x-auto pb-1">
            {STEPS.map((entry, index) => (
              <li key={entry.key} className="flex-1">
                <button
                  type="button"
                  onClick={() => (index < step ? setStep(index) : undefined)}
                  disabled={index > step}
                  className={cn(
                    'w-full rounded-md border-b-2 px-2 py-1.5 text-left text-xs whitespace-nowrap transition-colors',
                    index === step
                      ? 'border-accent font-semibold text-accent-strong'
                      : index < step
                        ? 'border-line-strong text-body hover:bg-canvas'
                        : 'border-line text-faint',
                  )}
                >
                  <span className="tabular">{index + 1}.</span> {entry.title}
                </button>
              </li>
            ))}
          </ol>

          {failure && (
            <Notice tone="alert" title="Could not continue">
              {failure}
            </Notice>
          )}

          <Card>
            <CardHeader title={STEPS[step].title} description={STEPS[step].blurb} />
            <CardBody>
              {step === 0 && (
                <SiteStep draft={draft} update={update} patient={patient.data} />
              )}
              {step === 1 && <CharacterStep draft={draft} update={update} />}
              {step === 2 && <SymptomsStep draft={draft} update={update} />}
              {step === 3 && (
                <QuestionsStep draft={draft} update={update} patient={patient.data} />
              )}
              {step === 4 && <VitalsStep draft={draft} update={update} />}
              {step === 5 && assessmentId && (
                <DocumentPanel
                  patientId={patientId}
                  assessmentId={assessmentId}
                  documents={documents.data ?? []}
                />
              )}
              {step === 6 && <SelfReportStep draft={draft} update={update} />}
            </CardBody>
          </Card>

          <div className="flex flex-wrap items-center justify-between gap-3">
            <Button
              variant="secondary"
              onClick={() => (step === 0 ? navigate(`/patients/${patientId}`) : setStep(step - 1))}
            >
              <ArrowLeft aria-hidden className="size-4" />
              {step === 0 ? 'Cancel' : 'Back'}
            </Button>

            {step < STEPS.length - 1 ? (
              <Button onClick={() => void goTo(step + 1)} disabled={noSiteYet} loading={busy}>
                Continue
                <ArrowRight aria-hidden className="size-4" />
              </Button>
            ) : (
              <Button onClick={() => void finish()} loading={busy}>
                <Sparkles aria-hidden className="size-4" />
                Run the estimate
              </Button>
            )}
          </div>

          {noSiteYet && step === 0 && (
            <p className="text-right text-xs text-muted">Select a site to continue.</p>
          )}
        </>
      )}
    </QueryState>
  )
}
