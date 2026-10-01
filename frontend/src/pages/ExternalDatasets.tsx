import React, { useMemo, useState } from 'react';
import {
  AlertTriangle,
  Database,
  Download,
  ExternalLink,
  Lock,
  RefreshCw,
  Search,
  X,
} from 'lucide-react';
import { useQuery } from '../api/hooks';
import { ApiError, request } from '../api/client';
import type {
  ExternalDataset,
  ExternalDatasetDetail,
  SyncOverview,
} from '../api/types';
import {
  AccessPill,
  AvailabilityPill,
  GranularityPill,
  LicencePill,
  OutcomeDot,
  Pill,
  QualityPill,
  formatBytes,
  formatWhen,
} from '../components/ui/Indicators';

/**
 * The external dataset dashboard.
 *
 * Every list on this page comes from the API. Sources, diseases, dataset types, licences
 * and access statuses are rendered from whatever the backend returns, so a publisher
 * added to `app.sync.sources`, or a disease created automatically from a new dataset,
 * appears here with no change to this file.
 */

const Card: React.FC<{ className?: string; children: React.ReactNode }> = ({
  className = '',
  children,
}) => (
  <div className={`bg-slate-900 border border-slate-800 rounded-xl ${className}`}>{children}</div>
);

const Stat: React.FC<{ label: string; value: string; hint?: string }> = ({
  label,
  value,
  hint,
}) => (
  <Card className="p-4">
    <div className="text-[11px] font-medium text-slate-400">{label}</div>
    <div className="mt-1 text-2xl font-bold text-ink tabular-nums">{value}</div>
    {hint && <div className="mt-0.5 text-[10px] text-slate-500">{hint}</div>}
  </Card>
);

export const ExternalDatasets: React.FC = () => {
  const overview = useQuery<SyncOverview>('/api/external-datasets/overview', 20);
  const [source, setSource] = useState('');
  const [disease, setDisease] = useState('');
  const [availability, setAvailability] = useState('');
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const query = useMemo(() => {
    const params = new URLSearchParams({ limit: '200' });
    if (source) params.set('source', source);
    if (disease) params.set('disease', disease);
    if (availability) params.set('availability', availability);
    if (search.trim()) params.set('search', search.trim());
    return `/api/external-datasets?${params.toString()}`;
  }, [source, disease, availability, search]);

  const datasets = useQuery<ExternalDataset[]>(query, 20);

  async function startSync() {
    setStarting(true);
    setMessage(null);
    try {
      await request('/api/external-datasets/sync', {
        method: 'POST',
        body: source ? { source } : {},
      });
      setMessage(
        'Synchronisation queued. The background worker picks it up; this page refreshes itself.',
      );
    } catch (cause) {
      setMessage(
        cause instanceof ApiError ? cause.message : 'The run could not be queued.',
      );
    } finally {
      setStarting(false);
    }
  }

  const totals = overview.data?.totals;
  const sources = overview.data?.sources ?? [];
  const diseases = overview.data?.diseases ?? [];

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight text-ink">External datasets</h1>
          <p className="text-xs text-slate-400">
            Datasets published by WHO, CDC, Kaggle, PhysioNet and any other configured source
          </p>
        </div>
        <button
          onClick={startSync}
          disabled={starting}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-3.5 py-2 text-xs font-semibold text-white transition hover:bg-blue-500 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${starting ? 'animate-spin' : ''}`} />
          {source ? `Synchronise ${source}` : 'Synchronise all sources'}
        </button>
      </header>

      {message && (
        <div className="rounded-lg border border-blue-500/30 bg-blue-500/10 px-4 py-2.5 text-xs text-blue-200">
          {message}
        </div>
      )}
      {overview.error && (
        <div className="flex items-center gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-4 py-2.5 text-xs text-red-200">
          <AlertTriangle className="h-4 w-4 shrink-0" />
          {overview.error}
        </div>
      )}

      {overview.data && (
        <p className="rounded-lg border border-slate-800 bg-slate-900/60 px-4 py-2.5 text-[11px] leading-relaxed text-slate-400">
          {overview.data.notice}
        </p>
      )}

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="Datasets catalogued" value={String(totals?.datasets ?? '—')} />
        <Stat
          label="Held locally"
          value={String(totals?.available ?? '—')}
          hint={totals ? formatBytes(totals.bytes_held) : undefined}
        />
        <Stat
          label="Metadata only"
          value={String(totals?.metadata_only ?? '—')}
          hint="access restricted by the publisher"
        />
        <Stat label="Stored versions" value={String(totals?.versions ?? '—')} />
        <Stat
          label="Training-eligible"
          value={String(totals?.trainable_versions ?? '—')}
          hint="per-subject with a pain rating"
        />
      </div>

      <section className="grid gap-4 lg:grid-cols-2">
        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-200">Configured sources</h2>
          <div className="space-y-2">
            {sources.length === 0 && (
              <p className="text-xs text-slate-500">No sources configured.</p>
            )}
            {sources.map((entry) => (
              <div
                key={entry.code}
                className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2"
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-xs font-medium text-slate-200">
                      {entry.label}
                    </span>
                    {!entry.enabled && <Pill>disabled</Pill>}
                    {entry.uses_credentials && (
                      <Pill
                        tone={
                          entry.credentials_present
                            ? 'bg-emerald-500/10 text-emerald-300 border-emerald-500/30'
                            : 'bg-slate-800 text-slate-400 border-slate-700'
                        }
                        title={
                          entry.credentials_present
                            ? 'API credentials are configured for this publisher.'
                            : 'No credentials configured. Public search still works; some downloads will not.'
                        }
                      >
                        {entry.credentials_present ? 'credentialed' : 'anonymous'}
                      </Pill>
                    )}
                  </div>
                  <div className="mt-0.5 truncate text-[10px] text-slate-500">
                    {entry.organisation} · every {entry.poll_interval_minutes} min · last run{' '}
                    {formatWhen(entry.last_run_at)}
                  </div>
                  {entry.last_error && (
                    <div className="mt-0.5 truncate text-[10px] text-red-400" title={entry.last_error}>
                      {entry.last_error}
                    </div>
                  )}
                </div>
                <button
                  onClick={() => setSource(source === entry.code ? '' : entry.code)}
                  className={`rounded-md border px-2 py-1 text-[10px] font-medium transition ${
                    source === entry.code
                      ? 'border-blue-500/40 bg-blue-600/20 text-blue-300'
                      : 'border-slate-700 text-slate-400 hover:text-slate-200'
                  }`}
                >
                  {source === entry.code ? 'filtering' : 'filter'}
                </button>
              </div>
            ))}
          </div>
        </Card>

        <Card className="p-5">
          <h2 className="mb-3 text-sm font-semibold text-slate-200">
            Diseases with external data
          </h2>
          <div className="max-h-72 space-y-1.5 overflow-y-auto pr-1">
            {diseases.length === 0 && (
              <p className="text-xs text-slate-500">
                No disease has external datasets yet. Run a synchronisation to populate this.
              </p>
            )}
            {diseases.map((entry) => (
              <button
                key={entry.code}
                onClick={() => setDisease(disease === entry.code ? '' : entry.code)}
                className={`flex w-full items-center justify-between gap-3 rounded-lg border px-3 py-2 text-left transition ${
                  disease === entry.code
                    ? 'border-blue-500/40 bg-blue-600/10'
                    : 'border-slate-800 bg-slate-950/50 hover:border-slate-700'
                }`}
              >
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-xs font-medium text-slate-200">
                      {entry.label}
                    </span>
                    {!entry.curated && (
                      <Pill
                        tone="bg-violet-500/10 text-violet-300 border-violet-500/30"
                        title={`Created automatically when a dataset for it was discovered${
                          entry.discovered_at ? ` (${formatWhen(entry.discovered_at)})` : ''
                        }. Not offered in clinical forms until reviewed.`}
                      >
                        discovered
                      </Pill>
                    )}
                  </div>
                  <div className="mt-0.5 text-[10px] text-slate-500">
                    {entry.sources.join(', ') || '—'}
                    {entry.records_held > 0 &&
                      ` · ${entry.records_held.toLocaleString()} records held`}
                  </div>
                </div>
                <div className="shrink-0 text-right">
                  <div className="text-xs font-semibold tabular-nums text-slate-200">
                    {entry.datasets}
                  </div>
                  <div className="text-[10px] text-slate-500">
                    {entry.available} held
                  </div>
                </div>
              </button>
            ))}
          </div>
        </Card>
      </section>

      <Card className="overflow-hidden">
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-800 p-4">
          <div className="relative min-w-48 flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search dataset names"
              className="w-full rounded-lg border border-slate-800 bg-slate-950 py-2 pl-9 pr-3 text-xs text-slate-200 placeholder:text-slate-600 focus:border-blue-500 focus:outline-none"
            />
          </div>
          <select
            value={availability}
            onChange={(event) => setAvailability(event.target.value)}
            className="rounded-lg border border-slate-800 bg-slate-950 px-3 py-2 text-xs text-slate-300 focus:border-blue-500 focus:outline-none"
          >
            <option value="">Any availability</option>
            <option value="AVAILABLE">Held locally</option>
            <option value="METADATA_ONLY">Metadata only</option>
            <option value="NOT_ATTEMPTED">Not yet collected</option>
            <option value="FAILED">Failed</option>
          </select>
          {(source || disease || availability || search) && (
            <button
              onClick={() => {
                setSource('');
                setDisease('');
                setAvailability('');
                setSearch('');
              }}
              className="flex items-center gap-1 rounded-lg border border-slate-800 px-2.5 py-2 text-[11px] text-slate-400 hover:text-slate-200"
            >
              <X className="h-3 w-3" /> Clear
            </button>
          )}
          <span className="ml-auto text-[11px] text-slate-500">
            {datasets.data ? `${datasets.data.length} shown` : ''}
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full min-w-200 text-left text-xs">
            <thead className="bg-slate-950/60 text-[10px] uppercase tracking-wider text-slate-500">
              <tr>
                <th className="px-4 py-2.5 font-medium">Dataset</th>
                <th className="px-3 py-2.5 font-medium">Source</th>
                <th className="px-3 py-2.5 font-medium">Disease</th>
                <th className="px-3 py-2.5 font-medium">Access</th>
                <th className="px-3 py-2.5 font-medium">Licence</th>
                <th className="px-3 py-2.5 font-medium">Held</th>
                <th className="px-3 py-2.5 font-medium">Checked</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {datasets.loading && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-500">
                    Loading…
                  </td>
                </tr>
              )}
              {!datasets.loading && datasets.data?.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-10 text-center text-slate-500">
                    Nothing matches these filters.
                  </td>
                </tr>
              )}
              {datasets.data?.map((row) => (
                <tr
                  key={row.id}
                  onClick={() => setSelected(row.id)}
                  className="cursor-pointer transition hover:bg-slate-800/40"
                >
                  <td className="max-w-md px-4 py-2.5">
                    <div className="truncate font-medium text-slate-200">{row.name}</div>
                    <div className="truncate font-mono text-[10px] text-slate-500">
                      {row.external_id}
                    </div>
                  </td>
                  <td className="px-3 py-2.5 text-slate-400">{row.source_code}</td>
                  <td className="px-3 py-2.5 text-slate-400">
                    {row.disease_code ?? <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-3 py-2.5">
                    <AccessPill value={row.access_status} />
                  </td>
                  <td className="px-3 py-2.5">
                    <LicencePill value={row.licence_verdict} />
                  </td>
                  <td className="px-3 py-2.5">
                    <AvailabilityPill value={row.availability} />
                  </td>
                  <td className="px-3 py-2.5 whitespace-nowrap text-slate-500">
                    {formatWhen(row.last_checked_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="p-5">
        <h2 className="mb-3 text-sm font-semibold text-slate-200">Synchronisation log</h2>
        <div className="max-h-80 space-y-1 overflow-y-auto pr-1 font-mono text-[11px]">
          {(overview.data?.recent_events ?? []).length === 0 && (
            <p className="font-sans text-xs text-slate-500">No runs recorded yet.</p>
          )}
          {overview.data?.recent_events.map((event) => (
            <div key={event.id} className="flex gap-2 border-b border-slate-800/60 py-1">
              <span className="w-16 shrink-0 text-slate-600">{formatWhen(event.at)}</span>
              <span className="w-24 shrink-0 text-slate-500">
                {event.stage.toLowerCase().replace(/_/g, ' ')}
              </span>
              <span className="w-14 shrink-0">
                <OutcomeDot value={event.outcome} />
              </span>
              <span className="min-w-0 flex-1 text-slate-400">
                <span className="text-slate-500">{event.external_id || event.source_code}</span>{' '}
                {event.message}
              </span>
            </div>
          ))}
        </div>
      </Card>

      {selected && <DatasetDrawer id={selected} onClose={() => setSelected(null)} />}
    </div>
  );
};

const DatasetDrawer: React.FC<{ id: string; onClose: () => void }> = ({ id, onClose }) => {
  const { data, error, loading } = useQuery<ExternalDatasetDetail>(
    `/api/external-datasets/${id}`,
  );

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-slate-950/70 backdrop-blur-sm"
      onClick={onClose}
    >
      <aside
        onClick={(event) => event.stopPropagation()}
        className="h-full w-full max-w-2xl overflow-y-auto border-l border-slate-800 bg-slate-900 p-6"
      >
        <div className="mb-4 flex items-start justify-between gap-4">
          <div className="min-w-0">
            <h2 className="text-lg font-semibold text-ink">{data?.name ?? 'Dataset'}</h2>
            <p className="truncate font-mono text-[11px] text-slate-500">{data?.external_id}</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800">
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading && <p className="text-xs text-slate-500">Loading…</p>}
        {error && <p className="text-xs text-red-400">{error}</p>}

        {data && (
          <div className="space-y-5">
            <div className="flex flex-wrap gap-1.5">
              <AccessPill value={data.access_status} />
              <LicencePill value={data.licence_verdict} />
              <AvailabilityPill value={data.availability} />
              <GranularityPill value={data.granularity} />
              <Pill>{data.dataset_type.replace(/_/g, ' ')}</Pill>
            </div>

            {data.description && (
              <p className="text-xs leading-relaxed text-slate-400">{data.description}</p>
            )}

            <Section title="Provenance">
              <Field label="Publisher">{data.source_code}</Field>
              <Field label="Source page">
                <a
                  href={data.source_url}
                  target="_blank"
                  rel="noreferrer noopener"
                  className="inline-flex items-center gap-1 text-blue-400 hover:underline"
                >
                  open <ExternalLink className="h-3 w-3" />
                </a>
              </Field>
              <Field label="Licence">{data.licence ?? 'none stated'}</Field>
              <Field label="Redistribution">{data.redistribution}</Field>
              <Field label="Publisher version">{data.publisher_version ?? '—'}</Field>
              <Field label="Publisher updated">{formatWhen(data.publisher_updated_at)}</Field>
              <Field label="First seen">{formatWhen(data.first_seen_at)}</Field>
              <Field label="Last checked">{formatWhen(data.last_checked_at)}</Field>
            </Section>

            {data.disease_match?.basis && (
              <Section title="Disease identification">
                <Field label="Linked to">{data.disease_code ?? 'no disease'}</Field>
                <Field label="Basis">{data.disease_match.basis}</Field>
              </Section>
            )}

            {data.availability === 'METADATA_ONLY' && data.access_procedure.length > 0 && (
              <div className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-4">
                <div className="mb-2 flex items-center gap-2 text-xs font-semibold text-amber-300">
                  <Lock className="h-3.5 w-3.5" />
                  The publisher restricts access to this dataset
                </div>
                <p className="mb-2 text-[11px] text-amber-200/70">
                  No files were requested. To obtain it yourself:
                </p>
                <ol className="list-inside list-decimal space-y-1 text-[11px] text-slate-300">
                  {data.access_procedure.map((step, index) => (
                    <li key={index}>{step}</li>
                  ))}
                </ol>
              </div>
            )}

            {data.last_error && (
              <div className="rounded-lg border border-red-500/30 bg-red-500/5 p-3">
                <div className="mb-1 text-xs font-semibold text-red-300">
                  Last attempt failed ({data.attempts} attempt{data.attempts === 1 ? '' : 's'})
                </div>
                <pre className="max-h-32 overflow-auto whitespace-pre-wrap font-mono text-[10px] text-red-200/70">
                  {data.last_error}
                </pre>
                {data.next_attempt_at && (
                  <p className="mt-1 text-[10px] text-slate-500">
                    Next attempt {formatWhen(data.next_attempt_at)}
                  </p>
                )}
              </div>
            )}

            <div>
              <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold text-slate-200">
                <Database className="h-3.5 w-3.5" />
                Stored versions ({data.versions.length})
              </h3>
              {data.versions.length === 0 && (
                <p className="text-[11px] text-slate-500">
                  No copy is held. {data.notes || ''}
                </p>
              )}
              <div className="space-y-3">
                {data.versions.map((version) => (
                  <div
                    key={version.id}
                    className="rounded-lg border border-slate-800 bg-slate-950/60 p-3"
                  >
                    <div className="mb-2 flex flex-wrap items-center gap-2">
                      <span className="font-mono text-xs font-semibold text-slate-200">
                        v{version.version}
                      </span>
                      <QualityPill value={version.quality_status} />
                      {version.trainable && (
                        <Pill tone="bg-sky-500/10 text-sky-300 border-sky-500/30">
                          training-eligible
                        </Pill>
                      )}
                      <span className="ml-auto text-[10px] text-slate-500">
                        {formatWhen(version.acquired_at)}
                      </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                      <Field label="Size">
                        {formatBytes(version.bytes)} in {version.file_count} file
                        {version.file_count === 1 ? '' : 's'}
                      </Field>
                      <Field label="Rows measured">
                        {version.records?.toLocaleString() ?? 'not tabular'}
                      </Field>
                      <Field label="Columns">{version.columns.length || '—'}</Field>
                      <Field label="Missing cells">
                        {version.missing_value_pct === null
                          ? '—'
                          : `${version.missing_value_pct.toFixed(1)}%`}
                      </Field>
                      <Field label="Licence at acquisition">{version.licence ?? '—'}</Field>
                      <Field label="Format">{version.file_format || '—'}</Field>
                    </div>
                    <div className="mt-2 break-all font-mono text-[10px] text-slate-600">
                      sha256 {version.sha256}
                    </div>

                    {version.quality_findings.length > 0 && (
                      <ul className="mt-2 space-y-0.5">
                        {version.quality_findings.map((finding, index) => (
                          <li
                            key={index}
                            className={`text-[10px] ${
                              finding.severity === 'error' ? 'text-red-300' : 'text-amber-300/80'
                            }`}
                          >
                            [{finding.severity}] {finding.message}
                          </li>
                        ))}
                      </ul>
                    )}

                    <div className="mt-2 rounded border border-slate-800 bg-slate-900/60 p-2">
                      <div className="mb-1 text-[10px] font-semibold text-slate-400">
                        Training suitability
                      </div>
                      {(version.suitability.conditions_met ?? []).map((item, index) => (
                        <div key={index} className="text-[10px] text-emerald-300/80">
                          ✓ {item}
                        </div>
                      ))}
                      {(version.suitability.reasons ?? []).map((item, index) => (
                        <div key={index} className="text-[10px] text-slate-400">
                          · {item}
                        </div>
                      ))}
                      {version.suitability.note && (
                        <div className="mt-1 text-[10px] italic text-slate-500">
                          {version.suitability.note}
                        </div>
                      )}
                    </div>

                    {version.manifest.length > 0 && (
                      <details className="mt-2">
                        <summary className="cursor-pointer text-[10px] text-slate-500 hover:text-slate-300">
                          <Download className="mr-1 inline h-3 w-3" />
                          {version.manifest.length} stored file
                          {version.manifest.length === 1 ? '' : 's'}
                        </summary>
                        <ul className="mt-1 space-y-0.5 font-mono text-[10px] text-slate-500">
                          {version.manifest.slice(0, 40).map((file) => (
                            <li key={file.name} className="truncate">
                              {formatBytes(file.bytes).padStart(8)} {file.name}
                            </li>
                          ))}
                        </ul>
                      </details>
                    )}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
};

const Section: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <div>
    <h3 className="mb-2 text-xs font-semibold text-slate-200">{title}</h3>
    <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">{children}</div>
  </div>
);

const Field: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="flex min-w-0 gap-2">
    <span className="shrink-0 text-slate-500">{label}</span>
    <span className="min-w-0 truncate text-slate-300">{children}</span>
  </div>
);
