import { useMemo, useState } from 'react'

import { useAudit } from '@/api/queries'
import { useAuth } from '@/auth/AuthProvider'
import { PageHeader } from '@/components/PageHeader'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Input } from '@/components/ui/field'
import { EmptyState, Notice, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatDateTime } from '@/utils/format'

const PAGE_SIZE = 50

export function AuditPage() {
  const { user } = useAuth()
  const [eventType, setEventType] = useState('')
  const [offset, setOffset] = useState(0)

  const params = useMemo(() => {
    const query = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) })
    if (eventType.trim()) query.set('event_type', eventType.trim().toUpperCase())
    return query
  }, [eventType, offset])

  const audit = useAudit(params)
  const total = audit.data?.total ?? 0

  return (
    <>
      <PageHeader
        title="Audit trail"
        description={
          user?.role === 'ADMIN'
            ? 'Every recorded event. Entries are chained: altering one breaks the chain that /integrity checks.'
            : 'The events recorded under your account. Administrators see the whole trail.'
        }
      />

      <Notice tone="info">
        Nothing here can be edited through the API. The only writer is the append path, and any
        change made behind it is detected by the integrity check.
      </Notice>

      <Card className="p-3">
        <div className="flex flex-wrap items-center gap-3">
          <Input
            value={eventType}
            onChange={(event) => {
              setOffset(0)
              setEventType(event.target.value)
            }}
            placeholder="Filter by event type, for example PREDICTION_RUN"
            aria-label="Filter by event type"
            className="max-w-md"
          />
          <span className="text-[0.8125rem] text-muted">{total} entries</span>
        </div>
      </Card>

      <Card>
        <QueryState
          isPending={audit.isPending}
          error={audit.error}
          isEmpty={total === 0}
          empty={<EmptyState title="No audit entries match this filter" />}
        >
          <TableWrap>
            <thead>
              <tr>
                <Th align="right">Seq</Th>
                <Th>When</Th>
                <Th>Event</Th>
                <Th>Actor</Th>
                <Th>Resource</Th>
                <Th>Entry hash</Th>
              </tr>
            </thead>
            <tbody>
              {audit.data?.items.map((entry) => (
                <Tr key={entry.seq}>
                  <Td align="right" className="text-muted">
                    {entry.seq}
                  </Td>
                  <Td className="text-muted">{formatDateTime(entry.timestamp)}</Td>
                  <Td className="font-medium text-ink">{entry.event_type.toLowerCase()}</Td>
                  <Td className="text-body">{entry.actor_label ?? '—'}</Td>
                  <Td className="text-body">
                    {entry.resource ?? '—'}
                    {entry.resource_id && (
                      <span className="block font-mono text-[0.6875rem] text-faint">
                        {entry.resource_id.slice(0, 20)}
                      </span>
                    )}
                  </Td>
                  <Td>
                    <span className="font-mono text-[0.6875rem] text-faint">
                      {entry.entry_hash.slice(0, 16)}…
                    </span>
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
