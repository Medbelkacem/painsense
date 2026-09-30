import { Plus, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'

import { usePatients } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { BandBadge, SyntheticTag, TrendTag } from '@/components/tags'
import { Button, LinkButton } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/choice'
import { EmptyState, QueryState } from '@/components/ui/feedback'
import { Input } from '@/components/ui/field'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatRelative, formatScore } from '@/utils/format'

const PAGE_SIZE = 25

export function PatientsPage() {
  const [search, setSearch] = useState('')
  const [submitted, setSubmitted] = useState('')
  const [includeArchived, setIncludeArchived] = useState(false)
  const [offset, setOffset] = useState(0)

  const params = useMemo(() => {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
    if (submitted) query.set('search', submitted)
    if (includeArchived) query.set('include_archived', 'true')
    return query
  }, [submitted, includeArchived, offset])

  const patients = usePatients(params)
  const total = patients.data?.total ?? 0

  return (
    <>
      <PageHeader
        title="Patients"
        description="Names are stored sealed. Searching by name decrypts the candidates on the server."
        actions={
          <LinkButton to="/patients/new" variant="primary">
            <Plus aria-hidden className="size-4" />
            New patient
          </LinkButton>
        }
      />

      <Card className="p-3">
        <form
          className="flex flex-wrap items-center gap-3"
          onSubmit={(event) => {
            event.preventDefault()
            setOffset(0)
            setSubmitted(search.trim())
          }}
        >
          <div className="relative min-w-0 flex-1">
            <Search
              aria-hidden
              className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-faint"
            />
            <Input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Patient code, name or ward"
              aria-label="Search patients"
              className="pl-9"
            />
          </div>
          <Button type="submit" variant="secondary">
            Search
          </Button>
          <Checkbox
            checked={includeArchived}
            onChange={(next) => {
              setOffset(0)
              setIncludeArchived(next)
            }}
            label="Include archived"
          />
        </form>
      </Card>

      <Card>
        <QueryState
          isPending={patients.isPending}
          error={patients.error}
          isEmpty={total === 0}
          empty={
            <EmptyState
              title={submitted ? 'No patient matched that search' : 'No patients yet'}
              description={
                submitted
                  ? 'Try the patient code, or part of the family name.'
                  : 'Create the first patient record to begin.'
              }
              action={<LinkButton to="/patients/new">New patient</LinkButton>}
            />
          }
        >
          <TableWrap>
            <thead>
              <tr>
                <Th>Patient</Th>
                <Th>Age and sex</Th>
                <Th>Ward</Th>
                <Th align="right">Latest estimate</Th>
                <Th align="right">Self-report</Th>
                <Th>Trend</Th>
                <Th>Last seen</Th>
              </tr>
            </thead>
            <tbody>
              {patients.data?.items.map((patient) => (
                <Tr key={patient.id}>
                  <Td>
                    <Link
                      to={`/patients/${patient.id}`}
                      className="font-medium text-accent-strong hover:underline"
                    >
                      {patient.display_name}
                    </Link>
                    <span className="block text-xs text-muted tabular">{patient.code}</span>
                    <span className="mt-1 flex flex-wrap gap-1">
                      {patient.is_synthetic && <SyntheticTag compact />}
                      {patient.archived && (
                        <span className="text-xs text-muted">Archived</span>
                      )}
                    </span>
                  </Td>
                  <Td className="text-body">
                    {patient.age ?? '—'} · {patient.sex}
                  </Td>
                  <Td className="text-body">{patient.ward ?? '—'}</Td>
                  <Td align="right">
                    <span className="inline-flex items-center gap-2">
                      {formatScore(patient.latest_estimated_pain)}
                      {patient.latest_estimated_pain !== null && (
                        <BandBadge
                          band={
                            patient.latest_estimated_pain >= 6.5
                              ? 'SEVERE'
                              : patient.latest_estimated_pain >= 3.5
                                ? 'MODERATE'
                                : 'MILD'
                          }
                        />
                      )}
                    </span>
                  </Td>
                  <Td align="right">{formatScore(patient.latest_self_report, 0)}</Td>
                  <Td>
                    <TrendTag trend={patient.trend} />
                  </Td>
                  <Td className="text-muted">{formatRelative(patient.latest_assessment_at)}</Td>
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
