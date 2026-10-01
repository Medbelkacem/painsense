import React, { useMemo, useState } from 'react';
import { Download, ScrollText, Search } from 'lucide-react';

import { ApiError, download } from '../api/client';
import { useQuery } from '../api/hooks';
import type { AuditEntry, Page } from '../api/types';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile, type Tone } from '../ui/Pill';
import { SearchField } from '../ui/Field';
import { Select } from '../ui/Dropdown';
import { DataTable, type Column } from '../ui/Table';
import { whenShort } from '../lib/format';

const PAGE_SIZE = 50;

/** The verbs the API records, grouped so a row is readable at a glance. */
function toneFor(eventType: string): Tone {
  if (eventType.startsWith('LOGIN') || eventType.startsWith('SESSION')) {
    return eventType.includes('FAILED') ? 'danger' : 'accent';
  }
  if (eventType.includes('DELETED') || eventType.includes('REVOKED')) return 'danger';
  if (eventType.includes('EXPORT') || eventType.includes('REPORT')) return 'warn';
  if (eventType.includes('PREDICT')) return 'violet';
  if (eventType.includes('VERIFIED') || eventType.includes('ROTATED')) return 'ok';
  if (eventType.includes('VIEWED') || eventType.includes('READ')) return 'neutral';
  return 'teal';
}

const word = (eventType: string) => eventType.replace(/_/g, ' ').toLowerCase();

export const Audit: React.FC = () => {
  const [query, setQuery] = useState('');
  const [eventType, setEventType] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const [selected, setSelected] = useState<AuditEntry | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const types = useQuery<string[]>('/api/audit/event-types');
  const summary = useQuery<{ total: number; by_event: Record<string, number> }>(
    '/api/audit/summary',
  );

  const path = useMemo(() => {
    const search = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    });
    if (eventType) search.set('event_type', eventType);
    return `/api/audit?${search}`;
  }, [eventType, page]);

  const { data, error, loading } = useQuery<Page<AuditEntry>>(path, 60);

  // The API filters by event type and actor; the box narrows the page in hand, which is
  // what someone chasing one patient code through the log is actually doing.
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return data?.items ?? [];
    return (data?.items ?? []).filter((row) =>
      `${row.event_type} ${row.actor_label ?? ''} ${row.resource ?? ''} ${row.resource_id ?? ''}`
        .toLowerCase()
        .includes(needle),
    );
  }, [data, query]);

  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const byEvent = summary.data?.by_event ?? {};
  const count = (predicate: (name: string) => boolean) =>
    Object.entries(byEvent)
      .filter(([name]) => predicate(name))
      .reduce((sum, [, value]) => sum + value, 0);

  const exportCsv = async () => {
    setFailure(null);
    try {
      await download('/api/audit/export', 'audit-log.csv', { method: 'GET' });
    } catch (cause) {
      setFailure(
        cause instanceof ApiError
          ? cause.message
          : 'The export could not be produced. It needs an auditor or administrator account.',
      );
    }
  };

  const columns: Column<AuditEntry>[] = [
    {
      key: 'seq',
      header: '#',
      cell: (row) => <span className="text-faint tabular-nums">{row.seq}</span>,
    },
    {
      key: 'at',
      header: 'When',
      cell: (row) => <span className="text-mute">{whenShort(new Date(row.timestamp))}</span>,
    },
    {
      key: 'event',
      header: 'Event',
      cell: (row) => <span className="font-medium text-ink">{word(row.event_type)}</span>,
    },
    {
      key: 'actor',
      header: 'Actor',
      hideBelow: 'md',
      cell: (row) => <span className="text-soft">{row.actor_label ?? 'system'}</span>,
    },
    {
      key: 'resource',
      header: 'Subject',
      hideBelow: 'lg',
      cell: (row) => (
        <span className="text-mute">
          {row.resource ?? '—'}
          {row.resource_id && (
            <span className="ml-1 text-faint">{row.resource_id.slice(0, 8)}</span>
          )}
        </span>
      ),
    },
    {
      key: 'ip',
      header: 'Source',
      hideBelow: 'lg',
      cell: (row) => <span className="text-[12px] text-mute">{row.client_ip ?? '—'}</span>,
    },
    {
      key: 'kind',
      header: 'Kind',
      align: 'right',
      cell: (row) => (
        <Pill tone={toneFor(row.event_type)} size="xs">
          {row.event_type.split('_')[0].toLowerCase()}
        </Pill>
      ),
    },
  ];

  return (
    <>
      <PageHead
        title="Audit log"
        sub="Every sign-in, read, prediction and export, recorded under the account that caused it."
        action={
          <Button icon={<Download className="h-4 w-4" />} onClick={() => void exportCsv()}>
            Export CSV
          </Button>
        }
      />

      {(error || failure) && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">
          {failure ?? error}
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          {
            label: 'Events recorded',
            value: summary.data?.total ?? total,
            note: 'Since the workspace opened',
          },
          {
            label: 'Records read',
            value: count((name) => name.includes('VIEWED') || name.includes('READ')),
            note: 'Patient and assessment reads',
          },
          {
            label: 'Failed sign-ins',
            value: count((name) => name.includes('LOGIN_FAILED')),
            note: 'Blocked at the gateway',
          },
          {
            label: 'Exports',
            value: count((name) => name.includes('EXPORT') || name.includes('REPORT')),
            note: 'Reports and datasets',
          },
        ].map((stat) => (
          <Card key={stat.label} className="p-4">
            <p className="text-xs font-medium text-mute">{stat.label}</p>
            <p className="mt-2 text-[26px] leading-none font-semibold text-ink tabular-nums">
              {summary.loading && summary.data === null
                ? '—'
                : stat.value.toLocaleString('en-GB')}
            </p>
            <p className="mt-2 text-[11px] text-faint">{stat.note}</p>
          </Card>
        ))}
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_340px]">
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <SearchField
              icon={<Search className="h-4 w-4" />}
              value={query}
              placeholder="Event, actor or subject…"
              onChange={(event) => setQuery(event.target.value)}
              className="w-full min-w-[12rem] sm:w-64"
            />
            <Select
              label="Event type"
              searchable
              clearable
              options={(types.data ?? []).map((value) => ({ value, label: word(value) }))}
              value={eventType}
              onChange={(value) => {
                setEventType(value);
                setPage(0);
              }}
            />
            <span className="ml-auto text-[12px] text-faint">
              {loading ? 'Loading…' : `${rows.length} of ${total}`}
            </span>
          </div>

          <div className="mt-4">
            <DataTable
              columns={columns}
              rows={rows}
              rowKey={(row) => String(row.seq)}
              onRowClick={setSelected}
              empty={
                <EmptyState
                  icon={<ScrollText className="h-5 w-5" />}
                  title={total === 0 ? 'Nothing recorded yet' : 'No event matches'}
                  sub={
                    total === 0
                      ? 'The log fills in as the workspace is used. The first entry is your own sign-in.'
                      : 'Clear the event type, or the search box.'
                  }
                />
              }
            />
          </div>

          {pageCount > 1 && (
            <div className="mt-3 flex items-center justify-between border-t border-hairline pt-3 text-[12px] text-mute">
              <span>
                Page {page + 1} of {pageCount}
              </span>
              <div className="flex gap-2">
                <Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                  Previous
                </Button>
                <Button
                  size="sm"
                  disabled={page >= pageCount - 1}
                  onClick={() => setPage(page + 1)}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
        </Card>

        <Card className="p-5">
          <CardHead
            title="Event detail"
            sub={selected ? `Entry ${selected.seq}` : 'Select a row'}
          />
          {selected ? (
            <>
              <div className="mt-4 flex items-center gap-3">
                <Tile tone={toneFor(selected.event_type)} className="h-10 w-10 rounded-xl">
                  <ScrollText className="h-4 w-4" />
                </Tile>
                <div className="min-w-0">
                  <p className="text-[14px] font-semibold text-ink">
                    {word(selected.event_type)}
                  </p>
                  <p className="text-[11px] text-mute">
                    {whenShort(new Date(selected.timestamp))}
                  </p>
                </div>
              </div>
              <dl className="mt-4 space-y-2">
                {[
                  ['Sequence', String(selected.seq)],
                  ['Actor', selected.actor_label ?? 'system'],
                  ['Resource', selected.resource ?? '—'],
                  ['Resource id', selected.resource_id ?? '—'],
                  ['Source address', selected.client_ip ?? '—'],
                ].map(([label, value]) => (
                  <div
                    key={label}
                    className="flex items-baseline justify-between gap-4 border-b border-hairline pb-1.5"
                  >
                    <dt className="shrink-0 text-[12px] text-mute">{label}</dt>
                    <dd className="min-w-0 truncate text-right text-[12px] font-medium text-ink">
                      {value}
                    </dd>
                  </div>
                ))}
              </dl>

              {Object.keys(selected.meta).length > 0 && (
                <>
                  <p className="eyebrow mt-4 mb-2">Recorded detail</p>
                  <dl className="space-y-1">
                    {Object.entries(selected.meta).map(([key, value]) => (
                      <div
                        key={key}
                        className="flex items-baseline justify-between gap-3 text-[11.5px]"
                      >
                        <dt className="shrink-0 text-mute">{key.replace(/_/g, ' ')}</dt>
                        <dd className="min-w-0 truncate text-right text-soft">
                          {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                        </dd>
                      </div>
                    ))}
                  </dl>
                </>
              )}

              <p className="mt-4 border-t border-hairline pt-3 text-[11px] leading-relaxed text-faint">
                Entry hash <span className="text-mute">{selected.entry_hash.slice(0, 24)}…</span>
                <br />
                Audit entries are append-only and each carries the hash of the one before it.
                Deleting one breaks verification on the Integrity screen.
              </p>
            </>
          ) : (
            <EmptyState icon={<ScrollText className="h-5 w-5" />} title="Nothing selected" />
          )}
        </Card>
      </div>
    </>
  );
};
