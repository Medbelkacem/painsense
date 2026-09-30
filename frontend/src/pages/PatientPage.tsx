import { Archive, FileText, Plus, Upload } from 'lucide-react'
import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'

import {
  useArchivePatient,
  useDiseases,
  useDocuments,
  usePatient,
  usePatientAssessments,
  usePatientHistory,
} from '@/api/queries'
import { PainTrendChart } from '@/charts/PainTrendChart'
import { DocumentPanel } from '@/components/DocumentPanel'
import { PageHeader } from '@/components/PageHeader'
import { BandBadge, SyntheticTag, TrendTag } from '@/components/tags'
import { Button, LinkButton } from '@/components/ui/button'
import { Card, CardBody, CardHeader, DescriptionList, DescriptionRow } from '@/components/ui/card'
import { Dialog } from '@/components/ui/dialog'
import { EmptyState, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatDate, formatDateTime, formatScore } from '@/utils/format'

export function PatientPage() {
  const { patientId = '' } = useParams()
  const patient = usePatient(patientId)
  const assessments = usePatientAssessments(patientId)
  const history = usePatientHistory(patientId)
  const diseases = useDiseases()
  const documents = useDocuments(new URLSearchParams({ patient_id: patientId }))
  const archive = useArchivePatient(patientId)
  const [confirmArchive, setConfirmArchive] = useState(false)

  const diseaseLabel = (code: string) =>
    diseases.data?.find((entry) => entry.code === code)?.label ?? code

  return (
    <QueryState isPending={patient.isPending} error={patient.error}>
      {patient.data && (
        <>
          <PageHeader
            title={patient.data.display_name}
            meta={
              <span className="flex flex-wrap items-center gap-2">
                <span className="rounded bg-canvas px-2 py-0.5 text-xs text-muted tabular">
                  {patient.data.code}
                </span>
                {patient.data.is_synthetic && <SyntheticTag />}
                {patient.data.archived && (
                  <span className="text-xs font-medium text-caution">Archived</span>
                )}
              </span>
            }
            description={`${patient.data.age ?? '—'} years · ${patient.data.sex} · ${
              patient.data.ward ?? 'no ward recorded'
            }`}
            actions={
              <>
                <LinkButton to={`/patients/${patientId}/history`} variant="secondary">
                  <FileText aria-hidden className="size-4" />
                  History
                </LinkButton>
                {!patient.data.archived && (
                  <>
                    <Button variant="secondary" onClick={() => setConfirmArchive(true)}>
                      <Archive aria-hidden className="size-4" />
                      Archive
                    </Button>
                    <LinkButton to={`/patients/${patientId}/assessment`} variant="primary">
                      <Plus aria-hidden className="size-4" />
                      New assessment
                    </LinkButton>
                  </>
                )}
              </>
            }
          />

          <div className="grid gap-4 lg:grid-cols-[1fr_1.4fr]">
            <div className="space-y-4">
              <Card>
                <CardHeader title="Latest" />
                <CardBody className="space-y-3">
                  <div className="flex items-end justify-between gap-3">
                    <div>
                      <p className="text-xs text-muted">Estimated pain</p>
                      <p className="text-3xl font-semibold text-ink tabular">
                        {formatScore(patient.data.latest_estimated_pain)}
                        <span className="ml-1 text-base font-normal text-muted">/ 10</span>
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-muted">Patient-reported</p>
                      <p className="text-3xl font-semibold text-body tabular">
                        {formatScore(patient.data.latest_self_report, 0)}
                        <span className="ml-1 text-base font-normal text-muted">/ 10</span>
                      </p>
                    </div>
                  </div>
                  <TrendTag
                    trend={patient.data.trend}
                    change={history.data?.change_from_previous}
                  />
                  <p className="text-xs text-muted">
                    {patient.data.assessment_count} assessment
                    {patient.data.assessment_count === 1 ? '' : 's'} on file.
                  </p>
                </CardBody>
              </Card>

              <Card>
                <CardHeader title="Clinical context" />
                <CardBody>
                  <DescriptionList>
                    <DescriptionRow term="Date of birth">
                      {formatDate(patient.data.birth_date)}
                    </DescriptionRow>
                    <DescriptionRow term="Smoking">
                      {patient.data.smoking_status.toLowerCase()}
                    </DescriptionRow>
                    <DescriptionRow term="Chronic conditions">
                      {patient.data.conditions.length
                        ? patient.data.conditions.map((row) => diseaseLabel(row.disease_code)).join(', ')
                        : 'None recorded'}
                    </DescriptionRow>
                    <DescriptionRow term="Medication">
                      {patient.data.medications.length
                        ? patient.data.medications
                            .map((row) => [row.name, row.dose, row.frequency].filter(Boolean).join(' '))
                            .join(' · ')
                        : 'None recorded'}
                    </DescriptionRow>
                    <DescriptionRow term="Allergies">
                      {patient.data.allergies ?? 'None recorded'}
                    </DescriptionRow>
                    <DescriptionRow term="Medical history">
                      {patient.data.medical_history ?? 'None recorded'}
                    </DescriptionRow>
                    <DescriptionRow term="Previous surgery">
                      {patient.data.previous_surgeries ?? 'None recorded'}
                    </DescriptionRow>
                    <DescriptionRow term="Contact">
                      {patient.data.identity?.phone ?? '—'}
                    </DescriptionRow>
                  </DescriptionList>
                </CardBody>
              </Card>
            </div>

            <div className="space-y-4">
              <Card>
                <CardHeader title="Pain over time" />
                <CardBody>
                  {history.data && history.data.points.length > 1 ? (
                    <PainTrendChart points={history.data.points} />
                  ) : (
                    <EmptyState
                      title="Not enough history for a trend"
                      description="Two assessments with an estimate are needed before a line can be drawn."
                    />
                  )}
                </CardBody>
              </Card>

              <Card>
                <CardHeader title="Assessments" />
                <QueryState
                  isPending={assessments.isPending}
                  error={assessments.error}
                  isEmpty={!assessments.data?.length}
                  empty={
                    <EmptyState
                      title="No assessments yet"
                      action={
                        <LinkButton to={`/patients/${patientId}/assessment`} variant="primary">
                          Record the first assessment
                        </LinkButton>
                      }
                    />
                  }
                >
                  <TableWrap>
                    <thead>
                      <tr>
                        <Th>Recorded</Th>
                        <Th>Site</Th>
                        <Th align="right">Estimate</Th>
                        <Th align="right">Self-report</Th>
                        <Th>Status</Th>
                      </tr>
                    </thead>
                    <tbody>
                      {assessments.data?.map((assessment) => (
                        <Tr key={assessment.id}>
                          <Td>
                            <Link
                              to={`/assessments/${assessment.id}`}
                              className="font-medium text-accent-strong hover:underline"
                            >
                              {formatDateTime(assessment.created_at)}
                            </Link>
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
                          <Td className="text-muted">{assessment.status.toLowerCase()}</Td>
                        </Tr>
                      ))}
                    </tbody>
                  </TableWrap>
                </QueryState>
              </Card>

              <Card>
                <CardHeader
                  title="Documents"
                  description="Stored encrypted. Findings are entered by the clinician."
                  actions={<Upload aria-hidden className="size-4 text-muted" />}
                />
                <CardBody>
                  <DocumentPanel patientId={patientId} documents={documents.data ?? []} />
                </CardBody>
              </Card>
            </div>
          </div>

          <Dialog
            open={confirmArchive}
            onClose={() => setConfirmArchive(false)}
            title="Archive this patient record?"
            description="Archived records stay readable and keep their history. No new assessment can be recorded against them."
            footer={
              <>
                <Button variant="secondary" onClick={() => setConfirmArchive(false)}>
                  Cancel
                </Button>
                <Button
                  loading={archive.isPending}
                  onClick={async () => {
                    await archive.mutateAsync()
                    setConfirmArchive(false)
                  }}
                >
                  Archive
                </Button>
              </>
            }
          >
            <p className="text-sm text-body">
              {patient.data.display_name} ({patient.data.code})
            </p>
          </Dialog>
        </>
      )}
    </QueryState>
  )
}
