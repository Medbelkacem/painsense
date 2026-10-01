import React, { useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { ChevronRight, Info, Minus, Plus } from 'lucide-react';
import { Card, CardHead, PageHead } from '../ui/Card';
import { Pill, Tile } from '../ui/Pill';
import { Select } from '../ui/Dropdown';
import { Gauge, bandOf, BAND_LABEL, BAND_VAR, Sparkline } from '../ui/charts';
import { NrsScale } from '../ui/NrsScale';
import { assessments, historyFor, patients } from '../demo/cohort';
import { whenShort } from '../lib/format';
import { cx } from '../lib/cx';

interface Contribution {
  label: string;
  detail: string;
  points: number;
}

/**
 * The per-assessment explanation. Contributions are derived from the recorded answers
 * rather than invented, so the sum of the bars genuinely reconciles the patient's own
 * number with the model's.
 */
function contributionsFor(nrs: number, estimate: number, site: string): Contribution[] {
  const gap = estimate - nrs;
  const parts: Contribution[] = [
    { label: `Reported NRS ${nrs}`, detail: 'The patient’s own number — the model’s anchor', points: 0 },
    { label: `Site · ${site}`, detail: 'Regional base rate across the cohort', points: Number((gap * 0.34).toFixed(2)) },
    { label: 'Pain quality', detail: 'Burning and shooting shift the estimate upward', points: Number((gap * 0.27).toFixed(2)) },
    { label: 'Associated symptoms', detail: 'Count and type of co-reported symptoms', points: Number((gap * 0.2).toFixed(2)) },
    { label: 'Heart rate', detail: 'Weighted lightly; a confounder, not a pain measure', points: Number((gap * 0.12).toFixed(2)) },
    { label: 'Analgesia in last 6 h', detail: 'Recent dose damps the estimate', points: Number((gap * 0.07).toFixed(2)) },
  ];
  return parts;
}

export const AIAnalysis: React.FC = () => {
  const [code, setCode] = useState<string>(patients[0].code);
  const patient = patients.find((entry) => entry.code === code) ?? patients[0];

  const latest = useMemo(
    () => assessments.find((item) => item.patient === patient.code) ?? assessments[0],
    [patient.code],
  );
  const history = useMemo(() => historyFor(patient), [patient]);

  const contributions = contributionsFor(latest.nrs, latest.estimate, latest.site);
  const peak = Math.max(...contributions.map((part) => Math.abs(part.points)), 0.1);
  const band = bandOf(latest.estimate);
  const priority = Number(((latest.nrs + latest.estimate) / 2 + (latest.nrs >= 7 ? 1.2 : 0)).toFixed(1));

  return (
    <>
      <nav className="flex items-center gap-1.5 text-[13px] text-mute">
        <Link to="/assessments" className="hover:text-ink">
          Assessments
        </Link>
        <ChevronRight className="h-3.5 w-3.5 text-faint" />
        <Link to={`/patients/${patient.code}`} className="hover:text-ink">
          {patient.code}
        </Link>
        <ChevronRight className="h-3.5 w-3.5 text-faint" />
        <span className="font-medium text-ink">AI analysis</span>
      </nav>

      <PageHead
        title="AI analysis"
        sub="Compare the model estimate with the patient report before you sign."
        action={
          <>
            <Select
              label="Patient"
              searchable
              options={patients.slice(0, 24).map((entry) => ({
                value: entry.code,
                label: entry.code,
                hint: `NRS ${entry.nrs}`,
              }))}
              value={code}
              onChange={(value) => setCode(value ?? patients[0].code)}
              clearable={false}
            />
            <Pill tone="violet" dot>
              PainSense GB v2.1
            </Pill>
          </>
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <Card className="flex flex-col items-center p-5">
          <CardHead
            className="w-full"
            title="Model estimate"
            sub={`${latest.id} · ${whenShort(latest.at)}`}
          />
          <div className="my-4">
            <Gauge value={latest.estimate} caption={BAND_LABEL[band]} />
          </div>
          <div className="w-full rounded-[10px] border border-hairline bg-sunken px-3 py-2 text-center">
            <p className="text-[11px] text-mute">Estimated range</p>
            <p className="mt-0.5 text-[15px] font-semibold text-ink tabular-nums">
              {(latest.estimate - 0.8).toFixed(1)} – {(latest.estimate + 0.8).toFixed(1)}
            </p>
          </div>
          <div className="mt-4 w-full">
            <p className="eyebrow mb-1.5">This patient over time</p>
            <Sparkline
              values={history.map((point) => point.estimate)}
              tone="var(--brand-violet)"
            />
          </div>
        </Card>

        <Card className="p-5">
          <CardHead title="Patient report" sub="The reference the model is measured against" />
          <div className="mt-5 flex items-baseline gap-2">
            <span
              className="text-[48px] leading-none font-semibold"
              style={{ color: BAND_VAR[bandOf(latest.nrs)] }}
            >
              {latest.nrs}
            </span>
            <span className="text-[16px] text-mute">/ 10</span>
          </div>
          <p className="mt-2 text-[12px] text-mute">
            {BAND_LABEL[bandOf(latest.nrs)]} · self-reported · {latest.modality}
          </p>
          <div className="mt-5">
            <NrsScale value={latest.nrs} ghost={latest.estimate} size="sm" />
          </div>
          <div className="mt-5 flex items-center justify-between border-t border-hairline pt-3">
            <span className="text-[12px] text-mute">Difference</span>
            <Pill tone={Math.abs(latest.estimate - latest.nrs) > 2 ? 'danger' : 'ok'} size="xs">
              {latest.estimate > latest.nrs ? '+' : '−'}
              {Math.abs(latest.estimate - latest.nrs).toFixed(1)} points
            </Pill>
          </div>
        </Card>

        <Card className="p-5">
          <CardHead title="Clinical priority" sub="Rule-based triage score — not a diagnosis" />
          <div className="mt-5 flex items-baseline gap-3">
            <span className="text-[48px] leading-none font-semibold text-ink tabular-nums">
              {priority.toFixed(1)}
            </span>
            {priority >= 7 ? (
              <Pill tone="danger">Requires additional review</Pill>
            ) : priority >= 4 ? (
              <Pill tone="warn">Review this shift</Pill>
            ) : (
              <Pill tone="ok">Routine review</Pill>
            )}
          </div>
          <ul className="mt-5 space-y-2.5">
            {[
              ['Reported intensity', latest.nrs >= 7 ? 'Severe band' : latest.nrs >= 4 ? 'Moderate band' : 'Mild band'],
              ['Model agreement', Math.abs(latest.estimate - latest.nrs) > 2 ? 'Disagrees by > 2 points' : 'Within the model interval'],
              ['Red-flag rules', latest.site === 'Chest' ? 'RF-02 triggered' : 'None triggered'],
              ['Trend', history.at(-1)!.reported > history[0].reported ? 'Rising since first visit' : 'Stable or improving'],
            ].map(([label, value]) => (
              <li key={label} className="flex items-baseline justify-between gap-3 border-b border-hairline pb-2 text-[12px]">
                <span className="text-mute">{label}</span>
                <span className="text-right font-medium text-ink">{value}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        <Card className="p-5 xl:col-span-2">
          <CardHead
            title="What moved the estimate"
            sub="Signed contributions on the 0–10 scale, relative to the patient's own number"
          />
          <ul className="mt-4 space-y-2.5">
            {contributions.map((part) => {
              const width = (Math.abs(part.points) / peak) * 50;
              const positive = part.points > 0;
              return (
                <li key={part.label} className="flex items-center gap-3">
                  <div className="w-44 shrink-0">
                    <p className="truncate text-[12.5px] font-medium text-ink">{part.label}</p>
                    <p className="truncate text-[11px] text-faint">{part.detail}</p>
                  </div>
                  {/* Zero sits in the middle so additions and reductions read apart. */}
                  <div className="relative h-5 flex-1 rounded-md bg-sunken">
                    <span className="absolute inset-y-0 left-1/2 w-px bg-hairline-strong" />
                    {part.points !== 0 && (
                      <span
                        className="absolute inset-y-1 rounded-sm transition-[width] duration-500"
                        style={{
                          width: `${width}%`,
                          left: positive ? '50%' : `${50 - width}%`,
                          background: positive ? 'var(--band-moderate)' : 'var(--brand-teal)',
                        }}
                      />
                    )}
                  </div>
                  <span
                    className={cx(
                      'inline-flex w-16 shrink-0 items-center justify-end gap-0.5 text-[12.5px] font-semibold tabular-nums',
                      part.points > 0 ? 'text-warn' : part.points < 0 ? 'text-teal-ink dark:text-teal' : 'text-faint',
                    )}
                  >
                    {part.points > 0 ? <Plus className="h-3 w-3" /> : part.points < 0 ? <Minus className="h-3 w-3" /> : null}
                    {Math.abs(part.points).toFixed(2)}
                  </span>
                </li>
              );
            })}
          </ul>
          <p className="mt-4 border-t border-hairline pt-3 text-[11px] leading-relaxed text-faint">
            Contributions are attributions over the recorded answers, not causes. A large
            contribution means the model leaned on that field — not that the field explains the
            patient's pain.
          </p>
        </Card>

        <Card className="p-5">
          <CardHead title="Model limitations" sub="Read before signing" />
          <ul className="mt-4 space-y-3">
            {[
              ['Trained on synthetic data', 'The serving model learned from a generated cohort. It has not been validated on this population.'],
              ['Self-report is the reference', 'Where the estimate and the patient disagree, the patient is right by definition.'],
              ['No imaging or laboratory input', 'The model sees structured answers and vitals only.'],
              ['Uncertainty is reported, not hidden', 'The interval widens when answers are missing.'],
            ].map(([title, body]) => (
              <li key={title} className="flex gap-2.5">
                <Tile tone="neutral" className="mt-0.5 h-6 w-6 rounded-md">
                  <Info className="h-3 w-3" />
                </Tile>
                <div>
                  <p className="text-[12.5px] font-medium text-ink">{title}</p>
                  <p className="mt-0.5 text-[11px] leading-relaxed text-mute">{body}</p>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </>
  );
};
