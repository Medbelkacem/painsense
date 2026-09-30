import { Download } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { downloadReport, useAssessments } from '@/api/queries'
import type { AssessmentStatus } from '@/api/types'
import { PageHeader } from '@/components/PageHeader'
import { BandBadge, SyntheticTag } from '@/components/tags'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { SegmentedControl } from '@/components/ui/choice'
import { EmptyState, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatDateTime, formatScore } from '@/utils/format'

type Filter = AssessmentStatus | 'ALL'
const PAGE_SIZE = 25

export function ReportsPage() {
  const [filter, setFilter] = useState<Filter>('ALL')
  const [offset, setOffset] = useState(0)

  const params = useMemo(() => {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
    if (filter !== 'ALL') query.set('status', filter)
    return query
  }, [filter, offset])

  const assessments = useAssessments(params)
  const total = assessments.data?.total ?? 0

  return (
    <>
      <PageHeader
        title="Assessments"
        description="Every recorded assessment, with the report available for each."
        actions={
          <SegmentedControl
            label="Status"
            value={filter}
            onChange={(next) => {
              setOffset(0)
              setFilter(next)
            }}
            options={[
              { value: 'ALL', label: 'All' },
              { value: 'DRAFT', label: 'Draft' },
              { value: 'ESTIMATED', label: 'Estimated' },
              { value: 'VALIDATED', label: 'Validated' },
            ]}
          />
        }
      />

      <Card>
        <QueryState
          isPending={assessments.isPending}
          error={assessments.error}
          isEmpty={total === 0}
          empty={<EmptyState title="No assessments match this filter" />}
        >
          <TableWrap>
            <thead>
              <tr>
                <Th>Recorded</Th>
                <Th>Patient</Th>
                <Th>Site</Th>
                <Th align="right">Estimate</Th>
                <Th align="right">Self-report</Th>
                <Th align="right">Priority</Th>
                <Th>Alerts</Th>
                <Th>Status</Th>
                <Th>Report</Th>
              </tr>
            </thead>
            <tbody>
              {assessments.data?.items.map((assessment) => (
                <Tr key={assessment.id}>
                  <Td>
                    <Link
                      to={`/assessments/${assessment.id}`}
                      className="font-medium text-accent-strong hover:underline"
                    >
                      {formatDateTime(assessment.created_at)}
                    </Link>
                  </Td>
                  <Td>
                    <Link
                      to={`/patients/${assessment.patient_id}`}
                      className="text-body hover:underline tabular"
                    >
                      {assessment.patient_code}
                    </Link>
                    {assessment.is_synthetic && (
                      <span className="ml-2 inline-block align-middle">
                        <SyntheticTag compact />
                      </span>
                    )}
                  </Td>
                  <Td className="text-body">{assessment.location_labels.join(', ') || '—'}</Td>
                  <Td align="right">
                    <span className="inline-flex items-center gap-2">
                      {formatScore(assessment.estimated_pain)}
                      <BandBadge band={assessment.band} />
                    </span>
                  </Td>
                  <Td align="right">{formatScore(assessment.self_report, 0)}</Td>
                  <Td align="right">{formatScore(assessment.priority_score)}</Td>
                  <Td>
                    {assessment.alert_count > 0 ? (
                      <span className="rounded-full bg-alert-soft px-2 py-0.5 text-xs font-medium text-alert">
                        {assessment.alert_count}
                      </span>
                    ) : (
                      <span className="text-muted">—</span>
                    )}
                  </Td>
                  <Td className="text-muted">{assessment.status.toLowerCase()}</Td>
                  <Td>
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() =>
                        void downloadReport(
                          assessment.id,
                          `pain-assessment-${assessment.patient_code}.pdf`,
                        )
                      }
                    >
                      <Download aria-hidden className="size-4" />
                      PDF
                    </Button>
                  </Td>
                </Tr>
              ))}
            </tbody>
          </TableWrap>

          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between gap-3 px-4 py-3 text-[0.8125rem] text-muted">
              <span>
                {offset + 1}&ndash;{Math.min(offset + PAGE_SIZE, total)} of {total}
              </span>
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
                >
                  Previous
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  disabled={offset + PAGE_SIZE >= total}
                  onClick={() => setOffset(offset + PAGE_SIZE)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </QueryState>
      </Card>
    </>
  )
}
