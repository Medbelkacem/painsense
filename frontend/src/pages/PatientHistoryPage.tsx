import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import { useComparison, usePatient, usePatientHistory } from '@/api/queries'
import { PainTrendChart } from '@/charts/PainTrendChart'
import { VitalsTrendChart } from '@/charts/VitalsTrendChart'
import { PageHeader } from '@/components/PageHeader'
import { BandBadge, TrendTag } from '@/components/tags'
import { LinkButton } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Select } from '@/components/ui/field'
import { EmptyState, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatDateTime, formatScore, formatSigned } from '@/utils/format'

export function PatientHistoryPage() {
  const { patientId = '' } = useParams()
  const patient = usePatient(patientId)
  const history = usePatientHistory(patientId)
  const points = useMemo(() => history.data?.points ?? [], [history.data])

  // Default to the two most recent, which is the comparison a clinician asks for first.
  const [current, setCurrent] = useState('')
  const [previous, setPrevious] = useState('')
  const selectedCurrent = current || points.at(-1)?.assessment_id || ''
  const selectedPrevious = previous || points.at(-2)?.assessment_id || ''
  const comparison = useComparison(selectedCurrent || undefined, selectedPrevious || undefined)
  const shown = comparison.data

  return (
    <>
      <PageHeader
        title="Assessment history"
        description={patient.data ? `${patient.data.display_name} · ${patient.data.code}` : undefined}
        actions={<LinkButton to={`/patients/${patientId}`}>Back to the patient</LinkButton>}
        meta={history.data && <TrendTag trend={history.data.trend} change={history.data.change_from_previous} />}
      />

      <QueryState
        isPending={history.isPending}
        error={history.error}
        isEmpty={points.length === 0}
        empty={<EmptyState title="No assessments recorded yet" />}
      >
        <div className="grid gap-4 lg:grid-cols-2">
          <Card>
            <CardHeader title="Pain over time" description="Estimate and the patient's own score." />
            <CardBody>
              <PainTrendChart points={points} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Measured values over time" />
            <CardBody>
              <VitalsTrendChart points={points} />
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader title="Every assessment" />
          <TableWrap>
            <thead>
              <tr>
                <Th>Recorded</Th>
                <Th align="right">Estimate</Th>
                <Th align="right">Self-report</Th>
                <Th align="right">Priority</Th>
                <Th align="right">Heart rate</Th>
                <Th align="right">Saturation</Th>
                <Th>Band</Th>
              </tr>
            </thead>
            <tbody>
              {[...points].reverse().map((point) => (
                <Tr key={point.assessment_id}>
                  <Td>
                    <Link
                      to={`/assessments/${point.assessment_id}`}
                      className="font-medium text-accent-strong hover:underline"
                    >
                      {formatDateTime(point.created_at)}
                    </Link>
                  </Td>
                  <Td align="right">{formatScore(point.estimated_pain)}</Td>
                  <Td align="right">{formatScore(point.self_report, 0)}</Td>
                  <Td align="right">{formatScore(point.priority_score)}</Td>
                  <Td align="right">{point.hr ?? '—'}</Td>
                  <Td align="right">{point.spo2 ?? '—'}</Td>
                  <Td>
                    <BandBadge band={point.band} />
                  </Td>
                </Tr>
              ))}
            </tbody>
          </TableWrap>
        </Card>

        {points.length >= 2 && (
          <Card>
            <CardHeader
              title="Compare two assessments"
              description="What changed between the two records, side by side."
            />
            <CardBody className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <label className="space-y-1.5 text-[0.8125rem] font-medium text-body">
                  Earlier
                  <Select
                    value={selectedPrevious}
                    onChange={(event) => setPrevious(event.target.value)}
                  >
                    {points.map((point) => (
                      <option key={point.assessment_id} value={point.assessment_id}>
                        {formatDateTime(point.created_at)}
                      </option>
                    ))}
                  </Select>
                </label>
                <label className="space-y-1.5 text-[0.8125rem] font-medium text-body">
                  Later
                  <Select value={selectedCurrent} onChange={(event) => setCurrent(event.target.value)}>
                    {points.map((point) => (
                      <option key={point.assessment_id} value={point.assessment_id}>
                        {formatDateTime(point.created_at)}
                      </option>
                    ))}
                  </Select>
                </label>
              </div>

              {shown && (
                <>
                  <TableWrap>
                    <thead>
                      <tr>
                        <Th>Field</Th>
                        <Th align="right">Earlier</Th>
                        <Th align="right">Later</Th>
                        <Th align="right">Change</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {shown.fields.map((field) => (
                        <Tr key={field.field}>
                          <Td className="text-body">{field.label}</Td>
                          <Td align="right">{field.previous ?? '—'}</Td>
                          <Td align="right">{field.current ?? '—'}</Td>
                          <Td
                            align="right"
                            className={
                              field.change === null
                                ? 'text-faint'
                                : field.change > 0
                                  ? 'text-alert'
                                  : field.change < 0
                                    ? 'text-positive'
                                    : 'text-muted'
                            }
                          >
                            {formatSigned(field.change)}
                          </Td>
                        </Tr>
                      ))}
                    </tbody>
                  </TableWrap>
                  <div className="grid gap-3 text-[0.8125rem] sm:grid-cols-2">
                    <div>
                      <p className="font-medium text-ink">New symptoms</p>
                      <p className="text-muted">{shown.symptoms_added.join(', ') || 'None'}</p>
                    </div>
                    <div>
                      <p className="font-medium text-ink">Symptoms no longer recorded</p>
                      <p className="text-muted">{shown.symptoms_resolved.join(', ') || 'None'}</p>
                    </div>
                  </div>
                </>
              )}
            </CardBody>
          </Card>
        )}
      </QueryState>
    </>
  )
}
