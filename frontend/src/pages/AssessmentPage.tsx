import { CheckCircle2, Download, RefreshCw } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { bandOf } from '@/anatomy/palette'
import {
  downloadReport,
  useAddNote,
  useAssessment,
  useDocuments,
  usePatientHistory,
  useRunEstimate,
  useValidateAssessment,
} from '@/api/queries'
import type { AnatomicalSiteDetail, AssessmentDetail } from '@/api/types'
import { PainTrendChart } from '@/charts/PainTrendChart'
import { DocumentPanel } from '@/components/DocumentPanel'
import { PageHeader } from '@/components/PageHeader'
import { PainScale } from '@/components/PainScale'
import { BandBadge, QualityBadge, SyntheticTag } from '@/components/tags'
import { Button, LinkButton } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Notice, QueryState } from '@/components/ui/feedback'
import { Textarea } from '@/components/ui/field'
import { cn } from '@/utils/cn'
import { formatDateTime, formatPercent, formatScore } from '@/utils/format'

const DISAGREEMENT = 2

export function AssessmentPage() {
  const { assessmentId = '' } = useParams()
  const assessment = useAssessment(assessmentId)
  const runEstimate = useRunEstimate(assessmentId)
  const validate = useValidateAssessment(assessmentId)
  const documents = useDocuments(new URLSearchParams({ assessment_id: assessmentId }))
  const history = usePatientHistory(assessment.data?.patient_id)
  const addNote = useAddNote(assessmentId)
  const [note, setNote] = useState('')

  return (
    <QueryState isPending={assessment.isPending} error={assessment.error}>
      {assessment.data && (
        <>
          <PageHeader
            title="Pain assessment"
            description={
              <>
                <Link
                  to={`/patients/${assessment.data.patient_id}`}
                  className="font-medium text-accent-strong hover:underline"
                >
                  {assessment.data.patient_code}
                </Link>
                {' · '}
                {assessment.data.patient_age_years ?? '—'} years ·{' '}
                {formatDateTime(assessment.data.created_at)}
              </>
            }
            meta={
              <>
                <span className="rounded bg-canvas px-2 py-0.5 text-xs text-muted">
                  {assessment.data.status.toLowerCase()}
                </span>
                {assessment.data.is_synthetic && <SyntheticTag />}
              </>
            }
            actions={
              <>
                <Button
                  variant="secondary"
                  loading={runEstimate.isPending}
                  onClick={() => runEstimate.mutate(undefined)}
                >
                  <RefreshCw aria-hidden className="size-4" />
                  Re-run the estimate
                </Button>
                {assessment.data.prediction && assessment.data.status !== 'VALIDATED' && (
                  <Button loading={validate.isPending} onClick={() => validate.mutate(undefined)}>
                    <CheckCircle2 aria-hidden className="size-4" />
                    Validate
                  </Button>
                )}
                <Button
                  variant="secondary"
                  onClick={() =>
                    void downloadReport(
                      assessmentId,
                      `pain-assessment-${assessment.data.patient_code}.pdf`,
                    )
                  }
                >
                  <Download aria-hidden className="size-4" />
                  Report
                </Button>
              </>
            }
          />

          <Result assessment={assessment.data} />

          <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
            <div className="space-y-4">
              <RecordedFindings assessment={assessment.data} />
              <Card>
                <CardHeader title="Clinical notes" />
                <CardBody className="space-y-3">
                  {assessment.data.notes.length === 0 && (
                    <p className="text-[0.8125rem] text-muted">No notes on this assessment yet.</p>
                  )}
                  <ul className="space-y-3">
                    {assessment.data.notes.map((entry) => (
                      <li key={entry.id} className="border-l-2 border-line pl-3">
                        <p className="text-xs text-muted">{formatDateTime(entry.created_at)}</p>
                        <p className="text-sm text-ink">{entry.body}</p>
                      </li>
                    ))}
                  </ul>
                  <Textarea
                    rows={3}
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    placeholder="Add a note"
                    aria-label="Add a clinical note"
                  />
                  <Button
                    size="sm"
                    disabled={!note.trim()}
                    loading={addNote.isPending}
                    onClick={async () => {
                      await addNote.mutateAsync(note.trim())
                      setNote('')
                    }}
                  >
                    Add note
                  </Button>
                </CardBody>
              </Card>
            </div>

            <div className="space-y-4">
              {history.data && history.data.points.length > 1 && (
                <Card>
                  <CardHeader
                    title="This patient over time"
                    actions={
                      <LinkButton
                        to={`/patients/${assessment.data.patient_id}/history`}
                        size="sm"
                        variant="ghost"
                      >
                        Full history
                      </LinkButton>
                    }
                  />
                  <CardBody>
                    <PainTrendChart points={history.data.points} height={200} />
                  </CardBody>
                </Card>
              )}
              <Card>
                <CardHeader title="Documents" />
                <CardBody>
                  <DocumentPanel
                    patientId={assessment.data.patient_id}
                    assessmentId={assessmentId}
                    documents={documents.data ?? []}
                  />
                </CardBody>
              </Card>
            </div>
          </div>
        </>
      )}
    </QueryState>
  )
}

function Result({ assessment }: { assessment: AssessmentDetail }) {
  const prediction = assessment.prediction

  if (!prediction) {
    return (
      <Notice tone="caution" title="No estimate has been produced yet">
        Run the estimate to see the model output for this record.
      </Notice>
    )
  }

  if (prediction.refused) {
    return (
      <Card className="border-caution/40">
        <CardHeader
          title="Insufficient data"
          description="The pipeline ran and declined to produce an estimate."
        />
        <CardBody className="space-y-4">
          <Notice tone="caution">{prediction.refusal_reason}</Notice>
          {prediction.missing_fields.length > 0 && (
            <div>
              <p className="text-sm font-medium text-ink">Not recorded</p>
              <ul className="mt-1 list-inside list-disc text-[0.8125rem] text-body">
                {prediction.missing_fields.map((field) => (
                  <li key={field}>{field}</li>
                ))}
              </ul>
            </div>
          )}
          <AlertList assessment={assessment} />
        </CardBody>
      </Card>
    )
  }

  const gap =
    assessment.self_report !== null && prediction.estimated_pain !== null
      ? prediction.estimated_pain - assessment.self_report
      : null

  return (
    <div className="space-y-4">
      <Card>
        <CardBody className="space-y-5">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Headline
              label="Estimated pain"
              value={formatScore(prediction.estimated_pain)}
              suffix="/ 10"
              badge={<BandBadge band={prediction.band} label={prediction.band_label} />}
            />
            <Headline
              label="Patient-reported"
              value={formatScore(assessment.self_report, 0)}
              suffix="/ 10"
              muted
            />
            <Headline
              label="Clinical priority"
              value={formatScore(prediction.priority_score)}
              suffix="/ 10"
              muted
            />
            <Headline
              label="Uncertainty interval"
              value={`${formatScore(prediction.interval_low)}–${formatScore(prediction.interval_high)}`}
              badge={<QualityBadge quality={prediction.data_quality} />}
            />
          </div>

          <PainScale
            estimate={prediction.estimated_pain}
            selfReport={assessment.self_report}
            intervalLow={prediction.interval_low}
            intervalHigh={prediction.interval_high}
          />

          <p className="text-xs leading-relaxed text-muted">
            The interval is the 10th to 90th model quantile. On held-out data it covered{' '}
            {formatPercent(prediction.interval_observed_coverage)} of self-reported scores, against a
            nominal {formatPercent(prediction.interval_nominal_level)}. Model{' '}
            <span className="tabular">{prediction.model_version}</span>, trained on{' '}
            <span className="tabular">{prediction.dataset_version}</span>.
          </p>

          {gap !== null && Math.abs(gap) >= DISAGREEMENT && (
            <Notice tone="caution" title="The estimate and the patient's score differ">
              They are {Math.abs(gap).toFixed(1)} points apart. Self-report remains a legitimate
              clinical reference and the platform does not assume the model is the more accurate of
              the two.
            </Notice>
          )}
        </CardBody>
      </Card>

      <AlertList assessment={assessment} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="Model contributions"
            description="How much each recorded field moved this estimate."
          />
          <CardBody className="space-y-2">
            {prediction.contributions.map((item) => (
              <div key={item.feature} className="flex items-center gap-3">
                <span className="w-44 shrink-0 text-[0.8125rem] text-body">{item.label}</span>
                <div className="flex h-2 flex-1 items-center">
                  <div className="flex h-2 w-1/2 justify-end">
                    {item.contribution < 0 && (
                      <span
                        className="h-2 rounded-l bg-positive/60"
                        style={{ width: `${Math.min(Math.abs(item.contribution) * 40, 100)}%` }}
                      />
                    )}
                  </div>
                  <div className="h-3 w-px bg-line-strong" />
                  <div className="h-2 w-1/2">
                    {item.contribution > 0 && (
                      <span
                        className="block h-2 rounded-r bg-accent/70"
                        style={{ width: `${Math.min(item.contribution * 40, 100)}%` }}
                      />
                    )}
                  </div>
                </div>
                <span className="w-12 shrink-0 text-right text-xs text-muted tabular">
                  {item.contribution > 0 ? '+' : ''}
                  {item.contribution.toFixed(2)}
                </span>
              </div>
            ))}
            <p className="pt-2 text-xs leading-relaxed text-muted">
              These are contributions to this model output. They are not evidence that a factor
              caused the pain.
            </p>
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            title="Potentially compatible categories"
            description="Patterns the recorded information fits. None of them is a diagnosis."
          />
          <CardBody className="space-y-3">
            {prediction.categories.length === 0 && (
              <p className="text-[0.8125rem] text-muted">
                No category reached the reporting threshold.
              </p>
            )}
            {prediction.categories.map((category) => (
              <details key={category.cause_code} className="rounded-md border border-line p-3">
                <summary className="flex cursor-pointer items-center justify-between gap-3 text-sm">
                  <span className="font-medium text-ink">{category.label}</span>
                  <span className="shrink-0 rounded-full bg-accent-soft px-2 py-0.5 text-xs font-semibold text-accent-strong tabular">
                    {category.score.toFixed(2)}
                  </span>
                </summary>
                <div className="mt-2 space-y-1.5 text-[0.8125rem]">
                  <p>
                    <span className="font-medium text-positive">Present: </span>
                    <span className="text-body">{category.matched.join(', ') || 'none'}</span>
                  </p>
                  <p>
                    <span className="font-medium text-muted">Not recorded: </span>
                    <span className="text-body">{category.missing.join(', ') || 'none'}</span>
                  </p>
                  {category.note && <p className="text-xs text-muted">{category.note}</p>}
                </div>
              </details>
            ))}
          </CardBody>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader
            title="What the priority indicator is made of"
            description="An arithmetic of the recorded findings. Not a probability of anything."
          />
          <CardBody>
            <ul className="divide-y divide-line text-sm">
              {prediction.priority_factors.map((factor) => (
                <li key={factor.label} className="flex justify-between gap-3 py-2">
                  <span className="text-body">{factor.label}</span>
                  <span className="font-semibold text-ink tabular">+{factor.points}</span>
                </li>
              ))}
            </ul>
          </CardBody>
        </Card>

        {prediction.confounder_notes.length > 0 && (
          <Card>
            <CardHeader
              title="Context affecting the measured values"
              description="Recorded context that can move the same values the model read."
            />
            <CardBody className="space-y-3">
              {prediction.confounder_notes.map((note) => (
                <div key={note.code}>
                  <p className="text-sm font-medium text-ink">{note.label}</p>
                  <p className="text-[0.8125rem] text-body">{note.explanation}</p>
                  <p className="mt-0.5 text-xs text-muted">
                    {note.vitals_deranged.length
                      ? `Values recorded outside their range: ${note.vitals_deranged.join(', ')}.`
                      : 'No affected value is outside its reference range.'}
                  </p>
                </div>
              ))}
            </CardBody>
          </Card>
        )}
      </div>

      {(prediction.missing_fields.length > 0 || prediction.quality_issues.length > 0) && (
        <Card>
          <CardHeader title="Data quality" />
          <CardBody className="space-y-2 text-[0.8125rem]">
            {prediction.missing_fields.length > 0 && (
              <p>
                <span className="font-medium text-ink">Not recorded: </span>
                <span className="text-body">{prediction.missing_fields.join(', ')}</span>
              </p>
            )}
            {prediction.quality_issues.map((issue) => (
              <p key={issue} className="text-caution">
                {issue}
              </p>
            ))}
          </CardBody>
        </Card>
      )}
    </div>
  )
}

function AlertList({ assessment }: { assessment: AssessmentDetail }) {
  const alerts = assessment.prediction?.alerts ?? []
  if (alerts.length === 0) return null

  return (
    <Card className="border-alert/30">
      <CardHeader
        title="Clinical alerts"
        description="Features of the recorded information that usually warrant prompt review. Not a diagnosis."
      />
      <CardBody className="space-y-3">
        {alerts.map((alert) => (
          <div
            key={alert.rule_code}
            className={
              alert.severity === 'HIGH'
                ? 'rounded-md border border-alert/30 bg-alert-soft p-3'
                : 'rounded-md border border-caution/30 bg-caution-soft p-3'
            }
          >
            <p className="flex items-center gap-2 text-sm font-semibold">
              <span
                className={
                  alert.severity === 'HIGH'
                    ? 'rounded bg-alert px-1.5 py-0.5 text-[0.625rem] text-white'
                    : 'rounded bg-caution px-1.5 py-0.5 text-[0.625rem] text-white'
                }
              >
                {alert.severity}
              </span>
              <span className="text-ink">{alert.label}</span>
            </p>
            <p className="mt-1 text-[0.8125rem] text-body">{alert.advice}</p>
            {alert.context_notes.length > 0 && (
              <p className="mt-1 text-xs text-muted">
                Recorded context that can also explain this: {alert.context_notes.join(', ')}.
              </p>
            )}
          </div>
        ))}
      </CardBody>
    </Card>
  )
}

const BAND_TEXT = {
  NONE: 'text-band-none',
  MILD: 'text-band-mild',
  MODERATE: 'text-band-moderate',
  SEVERE: 'text-band-severe',
  EXTREME: 'text-band-extreme',
} as const

/**
 * The structures localised on the 3D model.
 *
 * Printed beside the sites rather than instead of them: the site is what the estimate was
 * built from, and the structure is the finer record of where the clinician found the pain.
 * The intensity given here is the clinician's note on that site and is not a model input.
 */
function LocalisedStructures({ sites }: { sites: AnatomicalSiteDetail[] }) {
  if (!sites.length) return null
  return (
    <div className="mt-4 rounded-md border border-line bg-raised p-3">
      <p className="text-xs font-medium tracking-wide text-muted uppercase">
        Localised structures
      </p>
      <ul className="mt-1.5 space-y-1.5">
        {sites.map((site) => (
          <li key={`${site.structure_code}-${site.side}`} className="text-[0.8125rem]">
            <span className="text-ink">{site.label}</span>
            {site.side !== 'MIDLINE' && site.side !== 'NOT_APPLICABLE' && (
              <span className="text-muted"> · {site.side.toLowerCase()}</span>
            )}
            {site.intensity !== null && (
              <span className={cn('ml-1.5 font-medium tabular', BAND_TEXT[bandOf(site.intensity)])}>
                {site.intensity}/10
              </span>
            )}
            {site.is_primary && <span className="ml-1.5 text-xs text-accent-strong">main site</span>}
            {site.latin && <span className="block text-xs text-muted italic">{site.latin}</span>}
            {site.note && <span className="block text-xs text-muted">{site.note}</span>}
          </li>
        ))}
      </ul>
    </div>
  )
}

function RecordedFindings({ assessment }: { assessment: AssessmentDetail }) {
  const answers = Object.entries(assessment.answers)
  return (
    <Card>
      <CardHeader title="What was recorded" />
      <CardBody>
        <dl className="grid gap-x-6 gap-y-3 text-[0.8125rem] sm:grid-cols-2">
          <Entry term="Site" value={assessment.location_labels.join(', ')} />
          <Entry term="Onset" value={assessment.onset.toLowerCase()} />
          <Entry
            term="Duration"
            value={assessment.duration_hours ? `${assessment.duration_hours} hours` : null}
          />
          <Entry term="Pattern" value={assessment.pattern.toLowerCase()} />
          <Entry term="Course" value={assessment.course.toLowerCase()} />
          <Entry
            term="Radiation"
            value={assessment.radiates ? (assessment.radiation_description ?? 'Reported') : 'None'}
          />
          <Entry
            term="Heart rate"
            value={assessment.measurement?.hr ? `${assessment.measurement.hr} beats/min` : null}
          />
          <Entry
            term="Blood pressure"
            value={
              assessment.measurement?.sbp && assessment.measurement?.dbp
                ? `${assessment.measurement.sbp}/${assessment.measurement.dbp} mmHg`
                : null
            }
          />
          <Entry
            term="Oxygen saturation"
            value={assessment.measurement?.spo2 ? `${assessment.measurement.spo2} %` : null}
          />
          <Entry
            term="Temperature"
            value={
              assessment.measurement?.temperature_c
                ? `${assessment.measurement.temperature_c} °C`
                : null
            }
          />
        </dl>

        <LocalisedStructures sites={assessment.anatomical_sites} />

        {answers.length > 0 && (
          <details className="mt-4">
            <summary className="cursor-pointer text-[0.8125rem] font-medium text-accent-strong">
              {answers.length} question{answers.length === 1 ? '' : 's'} answered
            </summary>
            <dl className="mt-2 grid gap-x-6 gap-y-2 text-[0.8125rem] sm:grid-cols-2">
              {answers.map(([code, value]) => (
                <Entry
                  key={code}
                  term={code.toLowerCase().replaceAll('_', ' ')}
                  value={
                    Array.isArray(value)
                      ? value.join(', ')
                      : typeof value === 'boolean'
                        ? value
                          ? 'yes'
                          : 'no'
                        : String(value)
                  }
                />
              ))}
            </dl>
          </details>
        )}
      </CardBody>
    </Card>
  )
}

function Entry({ term, value }: { term: string; value: string | null | undefined }) {
  return (
    <div>
      <dt className="text-muted">{term}</dt>
      <dd className="text-ink">{value || '—'}</dd>
    </div>
  )
}

function Headline({
  label,
  value,
  suffix,
  badge,
  muted = false,
}: {
  label: string
  value: string
  suffix?: string
  badge?: React.ReactNode
  muted?: boolean
}) {
  return (
    <div>
      <p className="text-xs font-medium tracking-wide text-muted uppercase">{label}</p>
      <p
        className={`mt-1 text-3xl font-semibold tabular ${muted ? 'text-body' : 'text-ink'}`}
      >
        {value}
        {suffix && <span className="ml-1 text-base font-normal text-muted">{suffix}</span>}
      </p>
      {badge && <div className="mt-1.5">{badge}</div>}
    </div>
  )
}
