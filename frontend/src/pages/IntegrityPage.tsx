import { CheckCircle2, ShieldAlert, ShieldCheck } from 'lucide-react'

import { useIntegrity, useVerifyIntegrity } from '@/api/queries'
import { PageHeader } from '@/components/PageHeader'
import { StatTile } from '@/components/StatTile'
import { Button } from '@/components/ui/button'
import { Card, CardBody, CardHeader } from '@/components/ui/card'
import { Notice, QueryState } from '@/components/ui/feedback'
import { formatDateTime } from '@/utils/format'

export function IntegrityPage() {
  const integrity = useIntegrity()
  const verify = useVerifyIntegrity()
  const status = verify.data ?? integrity.data

  return (
    <>
      <PageHeader
        title="Record integrity"
        description="Every clinical record is hashed and chained. Verification recomputes every hash from the stored fields and checks the signature on every block."
        actions={
          <Button loading={verify.isPending} onClick={() => verify.mutate()}>
            <ShieldCheck aria-hidden className="size-4" />
            Verify now
          </Button>
        }
      />

      <QueryState isPending={integrity.isPending} error={integrity.error}>
        {status && (
          <>
            {status.ledger_valid && status.audit_valid ? (
              <Notice tone="info" title="Both chains verify">
                <span className="flex flex-wrap items-center gap-x-4 gap-y-1">
                  <span className="inline-flex items-center gap-1">
                    <CheckCircle2 aria-hidden className="size-3.5" />
                    {status.blocks} ledger blocks
                  </span>
                  <span className="inline-flex items-center gap-1">
                    <CheckCircle2 aria-hidden className="size-3.5" />
                    {status.audit_entries} audit entries
                  </span>
                  <span>Last checked {formatDateTime(status.verified_at)}</span>
                </span>
              </Notice>
            ) : (
              <Notice tone="alert" title="A chain did not verify">
                <ShieldAlert aria-hidden className="mb-1 inline size-4" /> The records below no
                longer hash to what was stored. Treat the affected records as altered.
              </Notice>
            )}

            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <StatTile label="Ledger blocks" value={status.blocks} />
              <StatTile label="Audit entries" value={status.audit_entries} />
              <StatTile
                label="Problems found"
                value={status.problems.length}
                tone={status.problems.length ? 'alert' : 'default'}
              />
              <StatTile label="Signature scheme" value={<span className="text-base">{status.signature_scheme ?? '—'}</span>} />
            </div>

            <Card>
              <CardHeader
                title="How the chain works"
                description="What is stored, and what makes an alteration visible."
              />
              <CardBody className="space-y-3 text-[0.8125rem] leading-relaxed text-body">
                <p>
                  A clinical record is serialised in one canonical form and hashed with SHA-256. The
                  hash, a link to the block before it and a signature go into an append-only ledger.
                  The record itself does not: there are no names, no findings and no measurements in
                  a block, so nothing can be read back out of it.
                </p>
                <p>
                  Changing a stored record changes its hash, which no longer matches the block.
                  Rewriting the block to match breaks the link to the next one. Rewriting the whole
                  chain needs the signing key, which is held in a file-backed keystore outside the
                  database, so a dump of the database is not enough.
                </p>
                <p>
                  The signing key fingerprint is{' '}
                  <span className="font-mono text-xs break-all">{status.key_fingerprint}</span>.
                </p>
              </CardBody>
            </Card>

            {status.problems.length > 0 && (
              <Card className="border-alert/30">
                <CardHeader title="Problems" />
                <CardBody>
                  <ul className="space-y-2 text-[0.8125rem]">
                    {status.problems.map((problem, index) => (
                      <li key={index} className="rounded border border-alert/25 bg-alert-soft p-2.5">
                        <p className="font-medium text-alert">
                          Block {problem.height} · {problem.kind}
                        </p>
                        <p className="text-body">{problem.detail}</p>
                      </li>
                    ))}
                  </ul>
                </CardBody>
              </Card>
            )}
          </>
        )}
      </QueryState>
    </>
  )
}
