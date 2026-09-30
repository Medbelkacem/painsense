import { useSecurity } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Notice, QueryState } from '@/components/ui/feedback'
import { Td, TableWrap, Th, Tr } from '@/components/ui/table'
import { formatDateTime } from '@/utils/format'

const TONE = {
  ACTIVE: 'positive',
  VALID: 'positive',
  DEPLOYMENT: 'accent',
  BROKEN: 'alert',
  FAILING: 'alert',
} as const

export function SecurityPage() {
  const security = useSecurity()

  return (
    <>
      <PageHeader
        title="Security"
        description="Each row below is produced by exercising the primitive, not by reading a configuration flag."
      />

      <QueryState isPending={security.isPending} error={security.error}>
        {security.data && (
          <>
            <Notice tone="info">
              The statuses are measured when this page loads: a key agreement is run, a signature is
              produced and verified against both the right and a wrong message, and a record is
              sealed and reopened. A primitive that is unavailable reports itself as failing rather
              than as active.
            </Notice>

            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {security.data.algorithms.map((entry) => (
                <div key={entry.name} className="rounded-lg border border-line bg-surface p-4">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-sm font-semibold text-ink">{entry.name}</p>
                    <Badge tone={TONE[entry.status as keyof typeof TONE] ?? 'neutral'}>
                      {entry.status}
                    </Badge>
                  </div>
                  <p className="mt-1 text-xs font-medium text-muted">{entry.purpose}</p>
                  <p className="mt-2 text-[0.8125rem] leading-relaxed text-body">{entry.detail}</p>
                </div>
              ))}
            </div>

            <div className="grid gap-4 lg:grid-cols-2">
              <Card>
                <CardHeader
                  title="Keys"
                  description={`Held in ${security.data.keystore_path}, outside the database.`}
                />
                <CardBody>
                  <dl className="space-y-4 text-[0.8125rem]">
                    {security.data.keys.map((key) => (
                      <div key={key.label}>
                        <dt className="font-medium text-ink">{key.label}</dt>
                        <dd className="text-body">{key.purpose}</dd>
                        <dd className="text-muted">{key.algorithm}</dd>
                        <dd className="font-mono text-xs break-all text-faint">
                          {key.fingerprint}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </CardBody>
              </Card>

              <Card>
                <CardHeader
                  title="Recent security events"
                  description={`${security.data.session_count} refresh session${
                    security.data.session_count === 1 ? '' : 's'
                  } outstanding.`}
                />
                <TableWrap>
                  <thead>
                    <tr>
                      <Th>When</Th>
                      <Th>Event</Th>
                      <Th>Actor</Th>
                    </tr>
                  </thead>
                  <tbody>
                    {security.data.recent_events.map((event) => (
                      <Tr key={String(event.seq)}>
                        <Td className="text-muted">{formatDateTime(String(event.timestamp))}</Td>
                        <Td className="text-ink">{String(event.event_type).toLowerCase()}</Td>
                        <Td className="text-body">{String(event.actor ?? '—')}</Td>
                      </Tr>
                    ))}
                  </tbody>
                </TableWrap>
              </Card>
            </div>

            <Card>
              <CardHeader title="What is implemented, and what is not" />
              <CardBody className="space-y-3 text-[0.8125rem] leading-relaxed text-body">
                <p>
                  Key establishment and signatures are hybrid: X25519 with ML-KEM-768, and Ed25519
                  with ML-DSA-65. Both halves have to break for the construction to break, so
                  adopting the post-quantum half never weakens what the classical one already gave.
                  The post-quantum primitives come from pqcrypto, which packages the PQClean
                  implementations; the classical ones and AES-256-GCM come from the cryptography
                  package.
                </p>
                <p>
                  Transport encryption is not done by this service. TLS is terminated by the reverse
                  proxy in front of it, which is why it is reported as a deployment responsibility
                  rather than as active here.
                </p>
              </CardBody>
            </Card>
          </>
        )}
      </QueryState>
    </>
  )
}
