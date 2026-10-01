import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Activity, AlertTriangle, Database, GitBranch, Info, Play, ShieldOff } from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import { useSession } from '../auth/session';
import type { Drift, Job, ModelStatus, TrainedModel } from '../api/types';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile, type Tone } from '../ui/Pill';
import { DataTable, type Column } from '../ui/Table';
import { BarRows } from '../ui/charts';
import { whenShort } from '../lib/format';

const Metric: React.FC<{ label: string; value: string; note: string }> = ({
  label,
  value,
  note,
}) => (
  <div className="rounded-[10px] border border-hairline bg-sunken px-3 py-2.5">
    <p className="text-[11px] text-mute">{label}</p>
    <p className="mt-1 text-[22px] leading-none font-semibold text-ink tabular-nums">{value}</p>
    <p className="mt-1.5 text-[10px] text-faint">{note}</p>
  </div>
);

const driftTone = (level: string): Tone => {
  const key = level.toUpperCase();
  if (key.includes('HIGH') || key.includes('SEVERE')) return 'danger';
  if (key.includes('MODERATE') || key.includes('WARN')) return 'warn';
  if (key.includes('INSUFFICIENT') || key.includes('UNKNOWN')) return 'neutral';
  return 'ok';
};

/** The coverage is only on the record when training wrote it into the profile. */
function coverageOf(model: TrainedModel): number | null {
  const value = model.training_profile?.interval_coverage;
  return typeof value === 'number' ? value : null;
}

export const AIModels: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useSession();
  const admin = user?.role === 'SUPER_ADMIN' || user?.role === 'CLINIC_ADMIN';

  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);

  const status = useQuery<ModelStatus>('/api/model');
  const drift = useQuery<Drift>(status.data?.trained ? '/api/model/drift' : null);
  const reloadStatus = status.reload;
  const reloadDrift = drift.reload;

  const training = job !== null && (job.status === 'QUEUED' || job.status === 'RUNNING');
  const jobId = job?.id ?? null;

  useEffect(() => {
    if (!training || !jobId) return;
    const timer = window.setInterval(() => {
      request<Job>(`/api/jobs/${jobId}`)
        .then((next) => {
          setJob(next);
          if (next.status === 'DONE') {
            reloadStatus();
            reloadDrift();
          }
        })
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [training, jobId, reloadStatus, reloadDrift]);

  const train = async () => {
    setBusy('train');
    setFailure(null);
    try {
      setJob(await request<Job>('/api/model/train', { method: 'POST', body: {} }));
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'Training could not be queued.');
    } finally {
      setBusy(null);
    }
  };

  const activate = async (version: string) => {
    setBusy(version);
    setFailure(null);
    try {
      await request<TrainedModel>(`/api/model/${encodeURIComponent(version)}/activate`, {
        method: 'POST',
      });
      status.reload();
      drift.reload();
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The version could not be activated.');
    } finally {
      setBusy(null);
    }
  };

  const active = status.data?.active ?? null;

  const importance = useMemo(
    () =>
      [...(active?.feature_importance ?? [])]
        .sort((a, b) => b.importance - a.importance)
        .slice(0, 15)
        .map((row) => ({ label: row.label ?? row.feature, value: row.importance })),
    [active],
  );

  const columns: Column<TrainedModel>[] = [
    {
      key: 'version',
      header: 'Version',
      cell: (row) => (
        <span className="inline-flex items-center gap-2 font-semibold text-ink">
          <GitBranch className="h-3.5 w-3.5 shrink-0 text-faint" />
          <span className="break-all">{row.version}</span>
        </span>
      ),
    },
    {
      key: 'trained',
      header: 'Trained',
      hideBelow: 'sm',
      cell: (row) => <span className="text-mute">{whenShort(new Date(row.trained_at))}</span>,
    },
    {
      key: 'dataset',
      header: 'Dataset',
      hideBelow: 'lg',
      cell: (row) => <span className="text-mute">{row.dataset_version}</span>,
    },
    {
      key: 'rows',
      header: 'Train rows',
      align: 'right',
      hideBelow: 'md',
      cell: (row) => (
        <span className="text-mute tabular-nums">{row.n_train.toLocaleString('en-GB')}</span>
      ),
    },
    {
      key: 'mae',
      header: 'MAE',
      align: 'right',
      cell: (row) => <span className="font-medium text-ink tabular-nums">{row.mae.toFixed(2)}</span>,
    },
    {
      key: 'r2',
      header: 'R²',
      align: 'right',
      hideBelow: 'sm',
      cell: (row) => <span className="text-mute tabular-nums">{row.r2.toFixed(2)}</span>,
    },
    {
      key: 'state',
      header: 'State',
      align: 'right',
      cell: (row) =>
        row.is_active ? (
          <Pill tone="ok" size="xs" dot>
            Active
          </Pill>
        ) : admin ? (
          <Button
            size="sm"
            disabled={busy !== null}
            onClick={(event) => {
              event.stopPropagation();
              void activate(row.version);
            }}
          >
            {busy === row.version ? 'Activating…' : 'Activate'}
          </Button>
        ) : (
          <Pill size="xs">Stored</Pill>
        ),
    },
  ];

  const trainButton = (
    <Button
      variant="primary"
      icon={<Play className="h-4 w-4" />}
      disabled={busy !== null || training}
      onClick={() => void train()}
    >
      {training ? 'Training…' : 'Train a model'}
    </Button>
  );

  return (
    <>
      <PageHead
        title="AI models"
        sub="Metrics come from the held-out test split of the synthetic dataset. They are reported as measured."
        action={
          <>
            {admin && trainButton}
            <Button icon={<Database className="h-4 w-4" />} onClick={() => navigate('/dataset')}>
              Dataset
            </Button>
          </>
        }
      />

      {(failure || status.error) && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">
          {failure ?? status.error}
        </Card>
      )}

      {job && (
        <Card className="flex flex-wrap items-center gap-3 p-4">
          <Pill
            tone={job.status === 'FAILED' ? 'danger' : job.status === 'DONE' ? 'ok' : 'accent'}
            size="xs"
            dot
          >
            {job.status.toLowerCase()}
          </Pill>
          <p className="min-w-0 flex-1 text-[12.5px] text-soft">
            {job.status === 'FAILED'
              ? (job.error ?? 'Training failed.')
              : job.status === 'DONE'
                ? 'Training finished. The new version is listed below and activated if it won the comparison.'
                : `Training in the background worker · ${Math.round(job.progress * 100)}%`}
          </p>
        </Card>
      )}

      {status.loading ? (
        <p className="py-16 text-center text-[13px] text-mute">Loading…</p>
      ) : status.data && !status.data.trained ? (
        <Card>
          <EmptyState
            icon={<Activity className="h-5 w-5" />}
            title="No model registered"
            sub={
              admin
                ? 'Train one here, or run `python -m backend.cli train` once a dataset has been generated. Estimates stay unavailable until a version is active.'
                : 'An administrator trains the first version from this page, or with `python -m backend.cli train` once a dataset has been generated.'
            }
            action={
              admin ? (
                trainButton
              ) : (
                <Button icon={<Database className="h-4 w-4" />} onClick={() => navigate('/dataset')}>
                  See the dataset
                </Button>
              )
            }
          />
        </Card>
      ) : (
        status.data &&
        active && (
          <>
            <Card className="p-5">
              <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="flex min-w-0 items-start gap-3">
                  <Tile tone="accent" className="h-10 w-10 rounded-xl">
                    <Play className="h-4 w-4" />
                  </Tile>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h2 className="text-[16px] font-semibold text-ink">{active.model_name}</h2>
                      <Pill tone="ok" size="xs" dot>
                        Active
                      </Pill>
                      <Pill size="xs" className="max-w-full">
                        <span className="truncate">{active.version}</span>
                      </Pill>
                    </div>
                    <p className="mt-1 text-[12.5px] text-mute">
                      {active.algorithm} · trained {whenShort(new Date(active.trained_at))} on{' '}
                      {active.dataset_version}
                    </p>
                  </div>
                </div>
                <div className="flex flex-wrap gap-x-5 gap-y-1 text-[12px] text-mute">
                  <span>
                    <span className="font-medium text-ink tabular-nums">
                      {status.data.feature_count}
                    </span>{' '}
                    features · schema {status.data.feature_schema_version}
                  </span>
                  <span>
                    <span className="font-medium text-ink tabular-nums">
                      {status.data.prediction_count.toLocaleString('en-GB')}
                    </span>{' '}
                    estimates served
                  </span>
                </div>
              </div>

              <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
                <Metric label="MAE" value={active.mae.toFixed(2)} note="Mean absolute error, 0–10 scale" />
                <Metric label="RMSE" value={active.rmse.toFixed(2)} note="Root mean squared error" />
                <Metric label="R²" value={active.r2.toFixed(2)} note="Variance explained" />
                <Metric label="Pearson r" value={active.pearson.toFixed(2)} note="Against the reference score" />
                <Metric
                  label="F1 by band"
                  value={active.f1_band === null ? '—' : active.f1_band.toFixed(2)}
                  note="Macro F1 over the pain bands"
                />
                <Metric
                  label="Cross-validated MAE"
                  value={`${active.cv_mae_mean.toFixed(2)} ± ${active.cv_mae_sd.toFixed(2)}`}
                  note={`${active.cv_folds} folds on the training split`}
                />
                <Metric label="Residual SD" value={active.residual_sd.toFixed(2)} note="Spread of the error" />
                {coverageOf(active) !== null ? (
                  <Metric
                    label="Interval coverage"
                    value={`${Math.round(coverageOf(active)! * 100)}%`}
                    note="Reference inside the 10th–90th range"
                  />
                ) : (
                  <Metric
                    label="Inference"
                    value={active.inference_ms === null ? '—' : `${active.inference_ms.toFixed(1)} ms`}
                    note="Per estimate"
                  />
                )}
              </div>

              <p className="mt-4 border-t border-hairline pt-3 text-[11px] text-faint">
                Split {active.n_train.toLocaleString('en-GB')} train ·{' '}
                {active.n_validation.toLocaleString('en-GB')} validation ·{' '}
                {active.n_test.toLocaleString('en-GB')} test
                {active.notes && <span className="block mt-1 leading-relaxed">{active.notes}</span>}
              </p>
            </Card>

            <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
              <Card className="p-5 xl:col-span-2">
                <CardHead
                  title="Feature importance"
                  sub="Permutation importance on the validation split"
                />
                <div className="mt-4">
                  {importance.length === 0 ? (
                    <p className="py-8 text-center text-[13px] text-mute">
                      This version carries no importance table.
                    </p>
                  ) : (
                    <BarRows
                      rows={importance}
                      colour="var(--brand-violet)"
                      format={(value) => value.toFixed(3)}
                    />
                  )}
                </div>
              </Card>

              <Card className="p-5">
                <CardHead
                  title="Drift"
                  sub={
                    drift.data
                      ? `Last ${drift.data.sample_size.toLocaleString('en-GB')} estimates against the training profile`
                      : 'Recent estimates against the training profile'
                  }
                />
                {drift.error ? (
                  <p className="mt-4 text-[12.5px] leading-relaxed text-mute">{drift.error}</p>
                ) : drift.data ? (
                  <>
                    <div className="mt-4 flex items-center gap-2">
                      <Pill tone={driftTone(drift.data.level)} dot>
                        {drift.data.level.replace(/_/g, ' ').toLowerCase()}
                      </Pill>
                    </div>
                    {drift.data.warnings.length === 0 ? (
                      <p className="mt-3 text-[12px] text-mute">Nothing flagged.</p>
                    ) : (
                      <ul className="mt-3 space-y-2">
                        {drift.data.warnings.map((line) => (
                          <li key={line} className="flex gap-2 text-[12px] leading-relaxed text-soft">
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-warn" />
                            {line}
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                ) : (
                  <p className="mt-4 text-[12px] text-mute">Loading…</p>
                )}
              </Card>
            </div>

            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Card className="p-5">
                <CardHead title="Limitations" sub="Carried into every report" />
                <ul className="mt-4 space-y-3">
                  {status.data.limitations.map((line) => (
                    <li key={line} className="flex gap-2.5 text-[12px] leading-relaxed text-soft">
                      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
                      {line}
                    </li>
                  ))}
                </ul>
              </Card>

              <Card className="p-5">
                <CardHead title="Kept out of the features" sub="Read by nobody but the clinician" />
                <ul className="mt-4 space-y-3">
                  {status.data.excluded_from_features.map((line) => (
                    <li key={line} className="flex gap-2.5 text-[12px] leading-relaxed text-soft">
                      <ShieldOff className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
                      {line}
                    </li>
                  ))}
                </ul>
              </Card>
            </div>

            <Card className="p-4">
              <CardHead
                className="px-1 pb-3"
                title="Versions"
                sub={
                  admin
                    ? 'Every trained model is kept. Activating one makes it the version behind new estimates.'
                    : 'Every trained model is kept for audit.'
                }
              />
              <DataTable
                columns={columns}
                rows={status.data.versions}
                rowKey={(row) => row.version}
              />
            </Card>
          </>
        )
      )}
    </>
  );
};
