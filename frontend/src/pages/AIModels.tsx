import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Database, GitBranch, Info, Play } from 'lucide-react';
import { Card, CardHead, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile } from '../ui/Pill';
import { Menu, Select } from '../ui/Dropdown';
import { DataTable, type Column } from '../ui/Table';
import { BarRows } from '../ui/charts';
import { datasetSplit, featureImportance, modelVersions } from '../demo/cohort';

type Version = (typeof modelVersions)[number];

const Metric: React.FC<{ label: string; value: string; note: string; good?: boolean }> = ({
  label,
  value,
  note,
  good,
}) => (
  <div className="rounded-[10px] border border-hairline bg-sunken px-3 py-2.5">
    <p className="text-[11px] text-mute">{label}</p>
    <p className="mt-1 text-[22px] leading-none font-semibold text-ink tabular-nums">{value}</p>
    <p className={`mt-1.5 text-[10px] ${good ? 'text-ok' : 'text-faint'}`}>{note}</p>
  </div>
);

export const AIModels: React.FC = () => {
  const navigate = useNavigate();
  const [compare, setCompare] = useState<string | null>(null);

  const serving = modelVersions[0];
  const against = modelVersions.find((entry) => entry.version === compare) ?? null;

  const delta = (key: 'mae' | 'rmse' | 'r2' | 'coverage') =>
    against === null ? null : Number((serving[key] - against[key]).toFixed(2));

  const columns: Column<Version>[] = [
    {
      key: 'version',
      header: 'Version',
      cell: (row) => (
        <span className="inline-flex items-center gap-2 font-semibold text-ink">
          <GitBranch className="h-3.5 w-3.5 text-faint" />
          {row.version}
        </span>
      ),
    },
    { key: 'trainedOn', header: 'Trained', cell: (row) => <span className="text-mute">{row.trainedOn}</span> },
    {
      key: 'records',
      header: 'Records',
      hideBelow: 'sm',
      cell: (row) => <span className="text-mute tabular-nums">{row.records.toLocaleString('en-GB')}</span>,
    },
    { key: 'mae', header: 'MAE', align: 'right', cell: (row) => <span className="font-medium text-ink tabular-nums">{row.mae.toFixed(2)}</span> },
    { key: 'rmse', header: 'RMSE', align: 'right', hideBelow: 'sm', cell: (row) => <span className="text-mute tabular-nums">{row.rmse.toFixed(2)}</span> },
    { key: 'r2', header: 'R²', align: 'right', cell: (row) => <span className="text-mute tabular-nums">{row.r2.toFixed(2)}</span> },
    {
      key: 'state',
      header: 'State',
      align: 'right',
      cell: (row) => (
        <Pill tone={row.state === 'Serving' ? 'ok' : 'neutral'} size="xs" dot>
          {row.state}
        </Pill>
      ),
    },
  ];

  return (
    <>
      <PageHead
        title="AI models"
        sub="Metrics come from the held-out evaluation split. Values here are reported, never rounded in the model's favour."
        action={
          <>
            <Select
              label="Compare with"
              options={modelVersions
                .filter((entry) => entry.state !== 'Serving')
                .map((entry) => ({ value: entry.version, label: entry.version, hint: entry.trainedOn }))}
              value={compare}
              onChange={setCompare}
            />
            <Button icon={<Database className="h-4 w-4" />} onClick={() => navigate('/dataset')}>
              Dataset
            </Button>
          </>
        }
      />

      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <Tile tone="accent" className="h-10 w-10 rounded-xl">
              <Play className="h-4 w-4" />
            </Tile>
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-[16px] font-semibold text-ink">PainSense Gradient Boosting</h2>
                <Pill tone="ok" size="xs" dot>
                  Serving
                </Pill>
                <Pill tone="neutral" size="xs">
                  {serving.version}
                </Pill>
              </div>
              <p className="mt-1 text-[12.5px] text-mute">
                Regression on the 0–10 scale · trained {serving.trainedOn} ·{' '}
                {datasetSplit.train.toLocaleString('en-GB')} synthetic training records
              </p>
            </div>
          </div>
          <Menu
            width="w-56"
            entries={[
              { label: 'Download model card', onSelect: () => undefined },
              { label: 'Export evaluation report', onSelect: () => undefined },
              null,
              { label: 'Roll back to v2.0', tone: 'danger' as const, onSelect: () => undefined },
            ]}
            trigger={({ toggle }) => <Button onClick={toggle}>Model actions</Button>}
          />
        </div>

        <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Metric
            label="MAE"
            value={serving.mae.toFixed(2)}
            note={against ? `${delta('mae')! < 0 ? '' : '+'}${delta('mae')} vs ${against.version}` : 'Mean absolute error'}
            good={against !== null && delta('mae')! < 0}
          />
          <Metric
            label="RMSE"
            value={serving.rmse.toFixed(2)}
            note={against ? `${delta('rmse')! < 0 ? '' : '+'}${delta('rmse')} vs ${against.version}` : 'Root mean squared error'}
            good={against !== null && delta('rmse')! < 0}
          />
          <Metric
            label="R²"
            value={serving.r2.toFixed(2)}
            note={against ? `${delta('r2')! > 0 ? '+' : ''}${delta('r2')} vs ${against.version}` : 'Variance explained'}
            good={against !== null && delta('r2')! > 0}
          />
          <Metric
            label="Interval coverage"
            value={`${Math.round(serving.coverage * 100)}%`}
            note={against ? `${delta('coverage')! > 0 ? '+' : ''}${delta('coverage')} vs ${against.version}` : 'True value inside the range'}
            good={against !== null && delta('coverage')! > 0}
          />
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHead
            title="Global feature importance"
            sub="Mean absolute contribution across the evaluation split"
          />
          <div className="mt-4">
            <BarRows
              rows={featureImportance.map((row) => ({ label: row.label, value: row.value }))}
              colour="var(--brand-violet)"
              format={(value) => value.toFixed(2)}
            />
          </div>
        </Card>

        <Card className="p-5">
          <CardHead title="Limitations" sub="Carried into every report" />
          <ul className="mt-4 space-y-3">
            {[
              'Trained and validated on synthetic data only.',
              'Self-reported NRS is the reference, never the model.',
              'No imaging, laboratory or free-text input.',
              'Interval widens where answers are missing; it is not a confidence score.',
            ].map((line) => (
              <li key={line} className="flex gap-2.5 text-[12px] leading-relaxed text-soft">
                <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-faint" />
                {line}
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card className="p-4">
        <CardHead className="px-1 pb-3" title="Version history" sub="Every trained model kept for audit" />
        <DataTable columns={columns} rows={modelVersions} rowKey={(row) => row.version} />
      </Card>
    </>
  );
};
