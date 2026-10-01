import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowLeft, Download, FlaskConical } from 'lucide-react';
import { Card, CardHead, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill } from '../ui/Pill';
import { BandBars, BarRows, Donut } from '../ui/charts';
import { assessments, countBy, datasetSplit, nrsDistribution, patients, PAIN_TYPES } from '../demo/cohort';
import { percent } from '../lib/format';

const SPLIT_COLOURS = ['var(--accent)', 'var(--brand-teal)', 'var(--brand-violet)'];

export const Dataset: React.FC = () => {
  const navigate = useNavigate();

  const counts = nrsDistribution();
  const ageBands = [
    ['18 – 29', patients.filter((patient) => patient.age < 30).length],
    ['30 – 44', patients.filter((patient) => patient.age >= 30 && patient.age < 45).length],
    ['45 – 59', patients.filter((patient) => patient.age >= 45 && patient.age < 60).length],
    ['60 – 74', patients.filter((patient) => patient.age >= 60 && patient.age < 75).length],
    ['75 +', patients.filter((patient) => patient.age >= 75).length],
  ] as const;

  const byType = countBy(assessments as unknown as Record<string, unknown>[], 'painType').map(
    (row, index) => ({
      label: row.label,
      value: row.value,
      colour: ['var(--accent)', 'var(--brand-teal)', 'var(--brand-violet)', 'var(--band-moderate)', 'var(--band-severe)', 'var(--band-none)', 'var(--ok)'][index % 7],
    }),
  );

  const byLocation = countBy(assessments as unknown as Record<string, unknown>[], 'site').slice(0, 8);

  const missing = [
    { label: 'Respiratory rate', value: 12 },
    { label: 'Analgesia detail', value: 9 },
    { label: 'Sleep quality', value: 7 },
    { label: 'Onset time', value: 4 },
    { label: 'Temperature', value: 2 },
  ];

  const splits = [
    { label: 'Training', value: datasetSplit.train },
    { label: 'Validation', value: datasetSplit.validation },
    { label: 'Test', value: datasetSplit.test },
  ];

  return (
    <>
      <PageHead
        title="Dataset"
        sub={`The records behind PainSense GB v2.1 · ${PAIN_TYPES.length} pain types · ${datasetSplit.total.toLocaleString('en-GB')} rows`}
        action={
          <>
            <Button icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate('/ai-models')}>
              Back to model
            </Button>
            <Button variant="primary" icon={<Download className="h-4 w-4" />}>
              Download data card
            </Button>
          </>
        }
      />

      <Card className="flex flex-wrap items-center gap-3 border-violet/25 bg-violet/8 p-4">
        <Pill tone="violet" icon={<FlaskConical className="h-3 w-3" />}>
          Synthetic data
        </Pill>
        <p className="min-w-0 flex-1 text-[12.5px] text-soft">
          Generated from published pain-assessment distributions. No record corresponds to a real
          person, and nothing here may be used to make a claim about a real population.
        </p>
      </Card>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[
          { label: 'Total records', value: datasetSplit.total },
          { label: 'Training', value: datasetSplit.train },
          { label: 'Validation', value: datasetSplit.validation },
          { label: 'Test', value: datasetSplit.test },
        ].map((stat) => (
          <Card key={stat.label} className="p-4">
            <p className="text-xs font-medium text-mute">{stat.label}</p>
            <p className="mt-2 text-[26px] leading-none font-semibold text-ink tabular-nums">
              {stat.value.toLocaleString('en-GB')}
            </p>
            <p className="mt-2 text-[11px] text-faint">
              {percent(stat.value, datasetSplit.total)} of the set
            </p>
          </Card>
        ))}
      </div>

      <Card className="p-5">
        <CardHead title="Split" sub="Patient-disjoint — no record of one patient appears in two splits" />
        <div className="mt-4 flex h-3 overflow-hidden rounded-full">
          {splits.map((split, index) => (
            <div
              key={split.label}
              title={`${split.label}: ${split.value.toLocaleString('en-GB')}`}
              style={{
                width: percent(split.value, datasetSplit.total),
                background: SPLIT_COLOURS[index],
              }}
            />
          ))}
        </div>
        <div className="mt-3 flex flex-wrap gap-5">
          {splits.map((split, index) => (
            <span key={split.label} className="flex items-center gap-2 text-[12px]">
              <span className="h-2.5 w-2.5 rounded-sm" style={{ background: SPLIT_COLOURS[index] }} />
              <span className="text-soft">{split.label}</span>
              <span className="font-medium text-ink tabular-nums">
                {split.value.toLocaleString('en-GB')}
              </span>
            </span>
          ))}
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="p-5 lg:col-span-2">
          <CardHead title="Pain distribution" sub="Target variable across the whole set" />
          <div className="mt-4">
            <BandBars counts={counts} />
          </div>
        </Card>

        <Card className="p-5">
          <CardHead title="Pain types" sub="Class balance" />
          <div className="mt-4 flex flex-wrap items-center gap-5">
            <Donut slices={byType} size={116} />
            <ul className="min-w-[140px] flex-1 space-y-1.5">
              {byType.map((slice) => (
                <li key={slice.label} className="flex items-center gap-2 text-[11.5px]">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: slice.colour }} />
                  <span className="min-w-0 flex-1 truncate text-soft">{slice.label}</span>
                  <span className="font-medium text-ink tabular-nums">{slice.value}</span>
                </li>
              ))}
            </ul>
          </div>
        </Card>

        <Card className="p-5">
          <CardHead title="Age distribution" sub="Cohort shape" />
          <div className="mt-4">
            <BarRows
              rows={ageBands.map(([label, value]) => ({ label, value }))}
              colour="var(--brand-teal)"
            />
          </div>
        </Card>

        <Card className="p-5">
          <CardHead title="Pain locations" sub="Most frequent regions" />
          <div className="mt-4">
            <BarRows rows={byLocation} colour="var(--accent)" />
          </div>
        </Card>

        <Card className="p-5">
          <CardHead title="Missing values" sub="Share of rows without the field" />
          <div className="mt-4">
            <BarRows
              rows={missing}
              colour="var(--warn)"
              format={(value) => `${value}%`}
            />
          </div>
          <p className="mt-4 border-t border-hairline pt-3 text-[11px] leading-relaxed text-faint">
            Missing fields are not imputed. The model reports a wider interval instead, which is
            what the Completeness card on an assessment is telling you.
          </p>
        </Card>
      </div>
    </>
  );
};
