import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, Database, FlaskConical, Lock, Play } from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useSession } from '../auth/session';
import type { DatasetExplorer, GeneratedDataset, Job } from '../api/types';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill } from '../ui/Pill';
import { TextField } from '../ui/Field';
import { DataTable, type Column } from '../ui/Table';
import { BarRows } from '../ui/charts';
import { percent, whenShort } from '../lib/format';

const SPLIT_COLOURS = ['var(--accent)', 'var(--brand-teal)', 'var(--brand-violet)', 'var(--warn)'];

const LIMITS = {
  patients: { min: 20, max: 100_000, initial: 1200 },
  assessments: { min: 100, max: 1_500_000, initial: 12_000 },
  seed: { min: 0, max: 2 ** 31 - 1, initial: 42 },
};

const word = (key: string) => key.replace(/_/g, ' ');

export const Dataset: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useSession();
  const admin = user?.role === 'SUPER_ADMIN' || user?.role === 'CLINIC_ADMIN';

  const [explorer, setExplorer] = useState<DatasetExplorer | null>(null);
  const [forbidden, setForbidden] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [job, setJob] = useState<Job | null>(null);

  const load = useCallback(() => {
    request<DatasetExplorer>('/api/datasets/explorer')
      .then((payload) => {
        setExplorer(payload);
        setError(null);
      })
      .catch((cause) => {
        if (cause instanceof ApiError && cause.status === 403) setForbidden(true);
        else setError(cause instanceof ApiError ? cause.message : 'Could not reach the server');
      })
      .finally(() => setLoading(false));
  }, []);

  useEffect(load, [load]);

  // A generation runs in the worker; the page keeps asking after the job until it
  // settles, then reads the explorer again so the new version is the one on screen.
  const running = job !== null && (job.status === 'QUEUED' || job.status === 'RUNNING');
  const jobId = job?.id ?? null;

  useEffect(() => {
    if (!running || !jobId) return;
    const timer = window.setInterval(() => {
      request<Job>(`/api/jobs/${jobId}`)
        .then((next) => {
          setJob(next);
          if (next.status === 'DONE') load();
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [running, jobId, load]);

  const latest = explorer?.latest ?? null;

  const splits = useMemo(
    () =>
      Object.entries(latest?.split ?? {}).map(([label, value], index) => ({
        label,
        value,
        colour: SPLIT_COLOURS[index % SPLIT_COLOURS.length],
      })),
    [latest],
  );
  const splitTotal = splits.reduce((sum, split) => sum + split.value, 0);

  const distributions = useMemo(
    () =>
      Object.entries(latest?.distribution ?? {}).map(([name, values]) => ({
        name,
        rows: Object.entries(values)
          .map(([label, value]) => ({ label: word(label), value }))
          .sort((a, b) => b.value - a.value)
          .slice(0, 12),
      })),
    [latest],
  );

  const anatomy = useMemo(
    () =>
      Object.entries(explorer?.anatomy ?? {})
        .map(([label, value]) => ({ label: word(label), value }))
        .sort((a, b) => b.value - a.value),
    [explorer],
  );

  const columns: Column<GeneratedDataset>[] = [
    {
      key: 'version',
      header: 'Version',
      cell: (row) => (
        <span className="inline-flex items-center gap-2 font-semibold text-ink">
          {row.version}
          {row.version === latest?.version && (
            <Pill tone="ok" size="xs" dot>
              latest
            </Pill>
          )}
        </span>
      ),
    },
    {
      key: 'at',
      header: 'Generated',
      cell: (row) => <span className="text-mute">{whenShort(new Date(row.generated_at))}</span>,
    },
    {
      key: 'rows',
      header: 'Rows',
      align: 'right',
      cell: (row) => (
        <span className="text-ink tabular-nums">{row.n_rows.toLocaleString('en-GB')}</span>
      ),
    },
    {
      key: 'patients',
      header: 'Patients',
      align: 'right',
      hideBelow: 'sm',
      cell: (row) => (
        <span className="text-mute tabular-nums">{row.n_patients.toLocaleString('en-GB')}</span>
      ),
    },
    {
      key: 'seed',
      header: 'Seed',
      align: 'right',
      hideBelow: 'md',
      cell: (row) => <span className="text-mute tabular-nums">{row.seed}</span>,
    },
    {
      key: 'generator',
      header: 'Generator',
      align: 'right',
      hideBelow: 'lg',
      cell: (row) => <span className="text-faint">{row.generator_version}</span>,
    },
  ];

  if (forbidden) {
    return (
      <>
        <PageHead title="Dataset" />
        <Card>
          <EmptyState
            icon={<Lock className="h-5 w-5" />}
            title="Available to research and administrator accounts"
            sub="The synthetic dataset and the knowledge base behind it are research tools. Ask an administrator for a research role if you need them."
          />
        </Card>
      </>
    );
  }

  return (
    <>
      <PageHead
        title="Dataset"
        sub={
          latest
            ? `${latest.version} · ${latest.n_rows.toLocaleString('en-GB')} rows over ${latest.n_patients.toLocaleString('en-GB')} synthetic patients`
            : 'The synthetic records the model is trained on, and the knowledge base they are drawn from.'
        }
        action={
          <Button icon={<Activity className="h-4 w-4" />} onClick={() => navigate('/ai-models')}>
            AI models
          </Button>
        }
      />

      {error && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">{error}</Card>
      )}

      {latest && (
        <Card className="flex flex-wrap items-center gap-3 border-violet/25 bg-violet/8 p-4">
          <Pill tone="violet" icon={<FlaskConical className="h-3 w-3" />}>
            Synthetic data
          </Pill>
          <p className="min-w-0 flex-1 text-[12.5px] text-soft">
            Generated from the knowledge base with seed {latest.seed}. No record corresponds to a
            real person, and nothing here supports a claim about a real population.
          </p>
        </Card>
      )}

      {admin && <Generate job={job} onQueued={setJob} />}

      {loading ? (
        <p className="py-16 text-center text-[13px] text-mute">Loading…</p>
      ) : !latest ? (
        <Card>
          <EmptyState
            icon={<Database className="h-5 w-5" />}
            title="No synthetic dataset generated yet"
            sub={
              admin
                ? 'Generate one with the form above. Training a model needs a dataset to learn from.'
                : 'An administrator generates the first version from this page. The knowledge base below is already in place.'
            }
          />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              { label: 'Rows', value: latest.n_rows.toLocaleString('en-GB'), note: 'Assessments in the set' },
              { label: 'Patients', value: latest.n_patients.toLocaleString('en-GB'), note: 'Synthetic records' },
              { label: 'Generated', value: whenShort(new Date(latest.generated_at)), note: latest.version },
              { label: 'Seed', value: String(latest.seed), note: `Generator ${latest.generator_version}` },
            ].map((stat) => (
              <Card key={stat.label} className="p-4">
                <p className="text-xs font-medium text-mute">{stat.label}</p>
                <p className="mt-2 truncate text-[22px] leading-none font-semibold text-ink tabular-nums">
                  {stat.value}
                </p>
                <p className="mt-2 truncate text-[11px] text-faint">{stat.note}</p>
              </Card>
            ))}
          </div>

          {splits.length > 0 && (
            <Card className="p-5">
              <CardHead
                title="Split"
                sub="Patient-disjoint: no record of one patient appears in two splits"
              />
              <div className="mt-4 flex h-3 overflow-hidden rounded-full bg-sunken">
                {splits.map((split) => (
                  <div
                    key={split.label}
                    title={`${split.label}: ${split.value.toLocaleString('en-GB')}`}
                    style={{ width: percent(split.value, splitTotal), background: split.colour }}
                  />
                ))}
              </div>
              <div className="mt-3 flex flex-wrap gap-5">
                {splits.map((split) => (
                  <span key={split.label} className="flex items-center gap-2 text-[12px]">
                    <span className="h-2.5 w-2.5 rounded-sm" style={{ background: split.colour }} />
                    <span className="text-soft capitalize">{split.label}</span>
                    <span className="font-medium text-ink tabular-nums">
                      {split.value.toLocaleString('en-GB')}
                    </span>
                    <span className="text-faint">{percent(split.value, splitTotal)}</span>
                  </span>
                ))}
              </div>
            </Card>
          )}

          {distributions.length > 0 && (
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              {distributions.map((entry, index) => (
                <Card key={entry.name} className="p-5">
                  <CardHead
                    title={<span className="capitalize">{word(entry.name)}</span>}
                    sub="Count of rows in the whole set"
                  />
                  <div className="mt-4">
                    <BarRows
                      rows={entry.rows}
                      colour={SPLIT_COLOURS[index % SPLIT_COLOURS.length]}
                      format={(value) => value.toLocaleString('en-GB')}
                    />
                  </div>
                </Card>
              ))}
            </div>
          )}
        </>
      )}

      {explorer && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card className="p-5 lg:col-span-2">
            <CardHead
              title="Knowledge base"
              sub="What the generator draws on and what the rules engine reads"
            />
            <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                ['Pain types', explorer.pain_types],
                ['Pain qualities', explorer.pain_qualities],
                ['Symptoms', explorer.symptoms],
                ['Diseases', explorer.diseases],
                ['Medication classes', explorer.medication_classes],
                ['Confounders', explorer.confounders],
                ['Questions', explorer.questions],
                ['Red-flag rules', explorer.rules],
              ].map(([label, value]) => (
                <div key={label} className="rounded-[10px] border border-hairline bg-sunken px-3 py-2.5">
                  <p className="text-[11px] text-mute">{label}</p>
                  <p className="mt-1 text-[20px] leading-none font-semibold text-ink tabular-nums">
                    {value}
                  </p>
                </div>
              ))}
            </div>
          </Card>

          <Card className="p-5">
            <CardHead title="Anatomy" sub="Structures in the ontology" />
            <div className="mt-4">
              {anatomy.length === 0 ? (
                <p className="py-6 text-center text-[13px] text-mute">Nothing loaded.</p>
              ) : (
                <BarRows rows={anatomy} colour="var(--brand-teal)" />
              )}
            </div>
          </Card>
        </div>
      )}

      {(explorer?.versions.length ?? 0) > 1 && (
        <Card className="p-4">
          <CardHead className="px-1 pb-3" title="Versions" sub="Every generated set, newest first" />
          <DataTable columns={columns} rows={explorer?.versions ?? []} rowKey={(row) => row.version} />
        </Card>
      )}
    </>
  );
};

const Generate: React.FC<{ job: Job | null; onQueued: (job: Job) => void }> = ({
  job,
  onQueued,
}) => {
  const [patients, setPatients] = useState(String(LIMITS.patients.initial));
  const [assessments, setAssessments] = useState(String(LIMITS.assessments.initial));
  const [seed, setSeed] = useState(String(LIMITS.seed.initial));
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const running = job !== null && (job.status === 'QUEUED' || job.status === 'RUNNING');

  const within = (value: string, limit: { min: number; max: number }) => {
    const number = Number(value);
    return Number.isInteger(number) && number >= limit.min && number <= limit.max;
  };
  const valid =
    within(patients, LIMITS.patients) &&
    within(assessments, LIMITS.assessments) &&
    within(seed, LIMITS.seed);

  const submit = async () => {
    setBusy(true);
    setFailure(null);
    try {
      onQueued(
        await request<Job>('/api/datasets/generate', {
          method: 'POST',
          body: {
            patients: Number(patients),
            assessments: Number(assessments),
            seed: Number(seed),
          },
        }),
      );
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The job could not be queued.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card className="p-5">
      <CardHead
        title="Generate a dataset"
        sub="Runs in the background worker. The same seed and sizes give the same records."
        action={
          job && (
            <Pill
              tone={job.status === 'FAILED' ? 'danger' : job.status === 'DONE' ? 'ok' : 'accent'}
              size="xs"
              dot
            >
              {running
                ? `${job.status.toLowerCase()} · ${Math.round(job.progress * 100)}%`
                : job.status.toLowerCase()}
            </Pill>
          )
        }
      />
      {(failure || job?.error) && (
        <p className="mt-3 rounded-[10px] border border-danger/25 bg-danger/8 px-3 py-2 text-[12px] text-danger">
          {failure ?? job?.error}
        </p>
      )}
      <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_1fr_auto] sm:items-end">
        <TextField
          label="Patients"
          type="number"
          inputMode="numeric"
          min={LIMITS.patients.min}
          max={LIMITS.patients.max}
          value={patients}
          onChange={(event) => setPatients(event.target.value)}
          hint={`${LIMITS.patients.min.toLocaleString('en-GB')} to ${LIMITS.patients.max.toLocaleString('en-GB')}`}
        />
        <TextField
          label="Assessments"
          type="number"
          inputMode="numeric"
          min={LIMITS.assessments.min}
          max={LIMITS.assessments.max}
          value={assessments}
          onChange={(event) => setAssessments(event.target.value)}
          hint={`${LIMITS.assessments.min.toLocaleString('en-GB')} to ${LIMITS.assessments.max.toLocaleString('en-GB')}`}
        />
        <TextField
          label="Seed"
          type="number"
          inputMode="numeric"
          min={LIMITS.seed.min}
          max={LIMITS.seed.max}
          value={seed}
          onChange={(event) => setSeed(event.target.value)}
          hint="Any non-negative integer"
        />
        <Button
          variant="primary"
          icon={<Play className="h-4 w-4" />}
          disabled={!valid || busy || running}
          onClick={() => void submit()}
          className="sm:mb-6"
        >
          {running ? 'Generating…' : 'Generate'}
        </Button>
      </div>
    </Card>
  );
};
