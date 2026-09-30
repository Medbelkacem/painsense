import { ArrowRight, Plus } from 'lucide-react'
import { Link } from 'react-router-dom'

import { useAnalytics, useIntegrity } from '@/api/queries'
import { Disclaimer } from '@/components/Disclaimer'
import { PageHeader } from '@/components/PageHeader'
import { StatTile } from '@/components/StatTile'
import { BandBadge, SyntheticTag } from '@/components/tags'
import { LinkButton } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { EmptyState, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { PainTrendChart } from '@/charts/PainTrendChart'
import { formatRelative, formatScore } from '@/utils/format'

export function DashboardPage() {
  const analytics = useAnalytics()
  const integrity = useIntegrity()

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Activity across the records this account can see."
        actions={
          <LinkButton to="/patients/new" variant="primary">
            <Plus aria-hidden className="size-4" />
            New patient
          </LinkButton>
        }
      />

      <Disclaimer />

      <QueryState isPending={analytics.isPending} error={analytics.error}>
        {analytics.data && (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile
                label="Patients"
                value={analytics.data.patients_total}
                hint={
                  analytics.data.patients_synthetic > 0
                    ? `${analytics.data.patients_synthetic} synthetic`
                    : undefined
                }
              />
              <StatTile
                label="Assessments today"
                value={analytics.data.assessments_today}
                hint={`${analytics.data.assessments_total} in total`}
              />
              <StatTile
                label="Awaiting review"
                value={analytics.data.assessments_awaiting_validation}
                hint="Estimated, not yet validated"
                tone={analytics.data.assessments_awaiting_validation > 0 ? 'caution' : 'default'}
              />
              <StatTile
                label="Estimates of 7 or more"
                value={analytics.data.high_pain_count}
                hint={`${analytics.data.alerts_open} alert rules triggered`}
                tone={analytics.data.high_pain_count > 0 ? 'alert' : 'default'}
              />
            </div>

            <div className="grid gap-4 lg:grid-cols-[1.6fr_1fr]">
              <Card>
                <CardHeader
                  title="Estimated pain over the last 30 days"
                  description="Mean estimate per day, over the assessments recorded that day."
                />
                <CardBody>
                  {analytics.data.daily_mean_pain.length ? (
                    <PainTrendChart
                      points={analytics.data.daily_mean_pain.map((point) => ({
                        assessment_id: point.date,
                        created_at: point.date,
                        estimated_pain: point.mean_pain,
                        self_report: null,
                        priority_score: null,
                        band: null,
                        hr: null,
                        resp_rate: null,
                        sbp: null,
                        dbp: null,
                        spo2: null,
                        temperature_c: null,
                      }))}
                    />
                  ) : (
                    <EmptyState
                      title="No estimates yet"
                      description="Record an assessment and run the estimate to see a trend here."
                    />
                  )}
                </CardBody>
              </Card>

              <div className="space-y-4">
                <Card>
                  <CardHeader title="Estimate against self-report" />
                  <CardBody className="space-y-3 text-sm">
                    <Figure
                      label="Mean estimated pain"
                      value={formatScore(analytics.data.mean_estimated_pain)}
                    />
                    <Figure
                      label="Mean patient-reported"
                      value={formatScore(analytics.data.mean_self_report)}
                    />
                    <Figure
                      label="Mean absolute difference"
                      value={formatScore(analytics.data.estimate_vs_self_report_mae, 2)}
                    />
                    <p className="text-xs leading-relaxed text-muted">
                      A description of how far the two have diverged here. It does not say which of
                      them is closer to the patient&rsquo;s experience.
                    </p>
                  </CardBody>
                </Card>

                <Card>
                  <CardHeader title="Record integrity" />
                  <CardBody className="space-y-2 text-sm">
                    <QueryState isPending={integrity.isPending} error={integrity.error}>
                      {integrity.data && (
                        <>
                          <Figure
                            label="Ledger"
                            value={
                              integrity.data.ledger_valid
                                ? `Valid, ${integrity.data.blocks} blocks`
                                : 'Broken'
                            }
                          />
                          <Figure
                            label="Audit chain"
                            value={
                              integrity.data.audit_valid
                                ? `Valid, ${integrity.data.audit_entries} entries`
                                : 'Broken'
                            }
                          />
                          <Link
                            to="/integrity"
                            className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-accent-strong hover:underline"
                          >
                            Verify now
                            <ArrowRight aria-hidden className="size-3.5" />
                          </Link>
                        </>
                      )}
                    </QueryState>
                  </CardBody>
                </Card>
              </div>
            </div>

            <Card>
              <CardHeader
                title="Recent assessments"
                actions={
                  <Link
                    to="/reports"
                    className="text-[0.8125rem] font-medium text-accent-strong hover:underline"
                  >
                    See all
                  </Link>
                }
              />
              {analytics.data.recent_assessments.length === 0 ? (
                <EmptyState
                  title="No assessments yet"
                  description="Create a patient and record the first assessment."
                  action={<LinkButton to="/patients/new">New patient</LinkButton>}
                />
              ) : (
                <TableWrap>
                  <thead>
                    <tr>
                      <Th>Patient</Th>
                      <Th>Site</Th>
                      <Th align="right">Estimate</Th>
                      <Th align="right">Self-report</Th>
                      <Th align="right">Priority</Th>
                      <Th>Recorded</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {analytics.data.recent_assessments.map((assessment) => (
                      <Tr key={assessment.id}>
                        <Td>
                          <Link
                            to={`/assessments/${assessment.id}`}
                            className="font-medium text-accent-strong hover:underline"
                          >
                            {assessment.patient_code}
                          </Link>
                          {assessment.is_synthetic && (
                            <span className="ml-2 inline-block align-middle">
                              <SyntheticTag compact />
                            </span>
                          )}
                        </Td>
                        <Td className="text-body">
                          {assessment.location_labels.join(', ') || '—'}
                        </Td>
                        <Td align="right">
                          <span className="inline-flex items-center gap-2">
                            {formatScore(assessment.estimated_pain)}
                            <BandBadge band={assessment.band} />
                          </span>
                        </Td>
                        <Td align="right">{formatScore(assessment.self_report, 0)}</Td>
                        <Td align="right">{formatScore(assessment.priority_score)}</Td>
                        <Td className="text-muted">{formatRelative(assessment.created_at)}</Td>
                      </Tr>
                    ))}
                  </tbody>
                </TableWrap>
              )}
            </Card>
          </>
        )}
      </QueryState>
    </>
  )
}

function Figure({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <span className="text-[0.8125rem] text-muted">{label}</span>
      <span className="font-semibold text-ink tabular">{value}</span>
    </div>
  )
}
