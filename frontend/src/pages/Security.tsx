import React, { useCallback, useState } from 'react';
import {
  CircleAlert, CircleCheck, KeyRound, RefreshCw, ShieldCheck, TriangleAlert,
} from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type { IntegrityStatus, SecurityStatus } from '../api/types';
import { Card, CardHead, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile, type Tone } from '../ui/Pill';
import { whenRelative, whenShort } from '../lib/format';
import { cx } from '../lib/cx';

const STATE_TONE: Record<string, Tone> = {
  ACTIVE: 'ok',
  AVAILABLE: 'ok',
  DEGRADED: 'warn',
  UNAVAILABLE: 'warn',
  MISSING: 'danger',
  FAILED: 'danger',
};

export const Security: React.FC = () => {
  const status = useQuery<SecurityStatus>('/api/security');
  const [verifying, setVerifying] = useState(false);
  const [verified, setVerified] = useState<IntegrityStatus | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const verify = useCallback(async () => {
    setVerifying(true);
    setFailure(null);
    try {
      // Walks both chains server-side and writes an audit entry of its own.
      setVerified(await request<IntegrityStatus>('/api/integrity/verify', { method: 'POST' }));
      status.reload();
    } catch (cause) {
      setFailure(
        cause instanceof ApiError ? cause.message : 'The chain could not be verified.',
      );
    } finally {
      setVerifying(false);
    }
  }, [status]);

  const integrity = verified ?? status.data?.integrity ?? null;
  const problems = integrity?.problems ?? [];

  return (
    <>
      <PageHead
        title="Integrity & security"
        sub="How records are protected, and the evidence that they have not been altered."
        action={
          <Button
            variant="primary"
            icon={<RefreshCw className={cx('h-4 w-4', verifying && 'animate-spin')} />}
            disabled={verifying}
            onClick={() => void verify()}
          >
            {verifying ? 'Verifying chain…' : 'Verify chain'}
          </Button>
        }
      />

      {(status.error || failure) && (
        <Card className="flex items-start gap-2.5 border-danger/25 bg-danger/8 p-4">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0 text-danger" />
          <p className="text-[12px] leading-relaxed text-soft">
            {failure ?? status.error}
            {status.error && ' — this screen needs an auditor or administrator account.'}
          </p>
        </Card>
      )}

      {status.loading && status.data === null && (
        <p className="py-16 text-center text-[13px] text-mute">Reading the keystore…</p>
      )}

      {status.data && (
        <>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-3">
            {status.data.algorithms.map((algorithm) => (
              <Card key={algorithm.name} className="flex items-start gap-3 p-4">
                <Tile
                  tone={STATE_TONE[algorithm.status.toUpperCase()] ?? 'neutral'}
                  className="h-9 w-9 rounded-lg"
                >
                  <ShieldCheck className="h-4 w-4" />
                </Tile>
                <div className="min-w-0 flex-1">
                  <p className="text-[12.5px] text-mute">{algorithm.purpose}</p>
                  <p className="mt-0.5 truncate text-[14px] font-semibold text-ink">
                    {algorithm.name}
                  </p>
                  <p className="mt-1 text-[11px] leading-relaxed text-faint">
                    {algorithm.detail}
                  </p>
                </div>
                <Pill
                  tone={STATE_TONE[algorithm.status.toUpperCase()] ?? 'neutral'}
                  size="xs"
                  dot
                >
                  {algorithm.status.toLowerCase()}
                </Pill>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              { label: 'Live sessions', value: status.data.session_count, note: 'Not revoked, not expired' },
              { label: 'Failed sign-ins', value: status.data.failed_logins_24h, note: 'Last 24 hours' },
              { label: 'Locked accounts', value: status.data.locked_accounts, note: 'Awaiting an unlock' },
              { label: 'Sealed patient records', value: status.data.patients_sealed, note: 'Identity encrypted at rest' },
            ].map((stat) => (
              <Card key={stat.label} className="p-4">
                <p className="text-xs font-medium text-mute">{stat.label}</p>
                <p className="mt-2 text-[26px] leading-none font-semibold text-ink tabular-nums">
                  {stat.value}
                </p>
                <p className="mt-2 text-[11px] text-faint">{stat.note}</p>
              </Card>
            ))}
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_380px]">
            <Card className="p-5">
              <CardHead
                title="Hash chains"
                sub="Each entry carries the hash of the one before it, so a changed record breaks the links after it."
                action={
                  integrity && (
                    <Pill
                      tone={integrity.ledger_valid && integrity.audit_valid ? 'ok' : 'danger'}
                      size="xs"
                      icon={
                        integrity.ledger_valid && integrity.audit_valid ? (
                          <CircleCheck className="h-3 w-3" />
                        ) : (
                          <CircleAlert className="h-3 w-3" />
                        )
                      }
                    >
                      {integrity.ledger_valid && integrity.audit_valid
                        ? `verified ${whenRelative(new Date(integrity.verified_at))}`
                        : 'verification failed'}
                    </Pill>
                  )
                }
              />

              {integrity && (
                <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <Chain
                    title="Signed ledger"
                    valid={integrity.ledger_valid}
                    length={integrity.blocks}
                    unit="block"
                    detail={
                      integrity.signature_scheme
                        ? `${integrity.signature_scheme} · key ${integrity.key_fingerprint?.slice(0, 16) ?? '—'}`
                        : 'No signature scheme reported'
                    }
                  />
                  <Chain
                    title="Audit chain"
                    valid={integrity.audit_valid}
                    length={integrity.audit_entries}
                    unit="entry"
                    detail="SHA-256 linked, append-only"
                  />
                </div>
              )}

              {problems.length > 0 && (
                <div className="mt-4 space-y-2">
                  <p className="eyebrow">Problems found</p>
                  {problems.map((problem) => (
                    <div
                      key={`${problem.kind}:${problem.height}`}
                      className="rounded-[10px] border border-danger/25 bg-danger/8 px-3 py-2"
                    >
                      <p className="text-[12.5px] font-medium text-ink">
                        {problem.kind.replace(/_/g, ' ').toLowerCase()} at {problem.height}
                      </p>
                      <p className="mt-0.5 text-[11.5px] leading-relaxed text-soft">
                        {problem.detail}
                      </p>
                    </div>
                  ))}
                </div>
              )}

              <p className="mt-4 border-t border-hairline pt-3 text-[11px] leading-relaxed text-faint">
                A block carries a hash, a link to the block before it and a signature — no
                names, findings or measurements. The chain proves that records have not been
                altered after the fact; it is not a distributed ledger and makes no claim to
                be one.
              </p>
            </Card>

            <div className="space-y-4">
              <Card className="p-5">
                <CardHead
                  title="Post-quantum levels"
                  sub="What the hybrid scheme is configured at"
                />
                <dl className="mt-3 space-y-2">
                  {[
                    ['Key encapsulation', status.data.pqc_kem_level],
                    ['Signature', status.data.pqc_sign_level],
                    ['Master keys in ring', String(status.data.master_key_versions_in_ring)],
                    ['Documents encrypted', String(status.data.documents_encrypted)],
                  ].map(([label, value]) => (
                    <div
                      key={label}
                      className="flex items-baseline justify-between gap-4 border-b border-hairline pb-1.5"
                    >
                      <dt className="text-[12px] text-mute">{label}</dt>
                      <dd className="text-[12px] font-medium text-ink">{value}</dd>
                    </div>
                  ))}
                </dl>
              </Card>

              <Card className="p-5">
                <CardHead title="Key material" sub="Held in the workspace keystore" />
                {status.data.keys.length === 0 ? (
                  <p className="mt-3 text-[13px] text-mute">No key version on record.</p>
                ) : (
                  <ul className="mt-3 space-y-2">
                    {status.data.keys.map((key) => (
                      <li
                        key={`${key.label}:${key.version}`}
                        className="rounded-[10px] border border-hairline bg-sunken px-3 py-2"
                      >
                        <div className="flex items-center gap-2">
                          <KeyRound className="h-3.5 w-3.5 shrink-0 text-faint" />
                          <span className="min-w-0 flex-1 truncate text-[12.5px] font-medium text-ink">
                            {key.label} v{key.version}
                          </span>
                          {key.is_current && (
                            <Pill tone="ok" size="xs">
                              current
                            </Pill>
                          )}
                        </div>
                        <p className="mt-1 truncate text-[11px] text-mute">
                          {key.algorithm} · {key.purpose}
                        </p>
                        <p className="truncate text-[11px] text-faint">
                          {key.fingerprint.slice(0, 24)}… · created{' '}
                          {whenShort(new Date(key.created_at))}
                          {key.rotated_at && ` · rotated ${whenShort(new Date(key.rotated_at))}`}
                        </p>
                      </li>
                    ))}
                  </ul>
                )}
              </Card>

              <Card className="p-5">
                <CardHead title="Security events" sub="Most recent first" />
                {status.data.recent_events.length === 0 ? (
                  <p className="mt-3 text-[13px] text-mute">Nothing recorded yet.</p>
                ) : (
                  <ul className="mt-3 divide-y divide-hairline">
                    {status.data.recent_events.map((event) => {
                      const row = event as {
                        seq: number;
                        timestamp: string;
                        event_type: string;
                        actor: string | null;
                        client_ip: string | null;
                      };
                      return (
                        <li key={row.seq} className="flex items-center gap-3 py-2.5">
                          <span
                            className={cx(
                              'h-1.5 w-1.5 shrink-0 rounded-full',
                              row.event_type.includes('FAILED') ? 'bg-danger' : 'bg-ok',
                            )}
                          />
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-[12.5px] text-ink">
                              {row.event_type.replace(/_/g, ' ').toLowerCase()}
                            </p>
                            <p className="truncate text-[11px] text-mute">
                              {[row.actor, row.client_ip].filter(Boolean).join(' · ') || 'system'}
                            </p>
                          </div>
                          <span className="shrink-0 text-[11px] text-faint">
                            {whenRelative(new Date(row.timestamp))}
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                )}
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
};

const Chain: React.FC<{
  title: string;
  valid: boolean;
  length: number;
  unit: string;
  detail: string;
}> = ({ title, valid, length, unit, detail }) => (
  <div
    className={cx(
      'rounded-[10px] border p-4',
      valid ? 'border-ok/25 bg-ok/8' : 'border-danger/25 bg-danger/8',
    )}
  >
    <div className="flex items-center gap-2">
      {valid ? (
        <CircleCheck className="h-4 w-4 shrink-0 text-ok" />
      ) : (
        <CircleAlert className="h-4 w-4 shrink-0 text-danger" />
      )}
      <span className="text-[13px] font-semibold text-ink">{title}</span>
    </div>
    <p className="mt-2 text-[24px] leading-none font-semibold text-ink tabular-nums">
      {length.toLocaleString('en-GB')}
      <span className="ml-1.5 text-[12px] font-normal text-mute">
        {unit}
        {length === 1 ? '' : 's'} checked
      </span>
    </p>
    <p className="mt-2 text-[11px] leading-relaxed text-mute">{detail}</p>
  </div>
);
