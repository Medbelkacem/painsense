import React from 'react';
import { BrainCircuit } from 'lucide-react';

import type { Prediction } from '../api/types';
import { Button } from '../ui/Button';
import { Card, CardHead } from '../ui/Card';
import { Gauge } from '../ui/charts';
import { cx } from '../lib/cx';

const Figure: React.FC<{ label: string; value: React.ReactNode; tone?: 'violet' }> = ({
  label,
  value,
  tone,
}) => (
  <div className="flex items-baseline justify-between border-b border-hairline pb-2">
    <span className="text-[12px] text-mute">{label}</span>
    <span
      className={cx(
        'text-[17px] font-semibold tabular-nums',
        tone === 'violet' ? 'text-violet' : 'text-ink',
      )}
    >
      {value}
    </span>
  </div>
);

interface EstimatePanelProps {
  prediction: Prediction | null;
  selfReport: number | null;
  /** Absent on a read-only page, present where the estimate can be (re)run. */
  onRun?: () => void;
  busy?: boolean;
}

/** The model's number next to the patient's, with the cues and contributions under it. */
export const EstimatePanel: React.FC<EstimatePanelProps> = ({ prediction, selfReport, onRun, busy }) => (
  <>
    <Card className="p-5">
      <CardHead
        title="AI estimate"
        sub="The model's estimate next to what the patient reported. The patient's score is never a model input."
        action={
          onRun && (
            <Button
              variant="primary"
              icon={<BrainCircuit className="h-4 w-4" />}
              disabled={busy}
              onClick={onRun}
            >
              {busy ? 'Working…' : prediction ? 'Run again' : 'Compute pain score'}
            </Button>
          )
        }
      />
      {!prediction ? (
        <p className="py-12 text-center text-[13px] text-mute">
          {onRun
            ? 'Nothing has been estimated yet. Computing the score saves the assessment and asks the model.'
            : 'No estimate has been produced for this assessment.'}
        </p>
      ) : prediction.refused ? (
        <div className="mt-4 rounded-[10px] border border-warn/30 bg-warn/8 p-4">
          <p className="text-[13px] font-semibold text-ink">The model declined to estimate</p>
          <p className="mt-1 text-[12px] leading-relaxed text-soft">{prediction.refusal_reason}</p>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-8">
          <Gauge value={prediction.estimated_pain ?? 0} caption={prediction.band_label ?? ''} />
          <div className="min-w-[240px] flex-1 space-y-3">
            <Figure label="Patient-reported" value={selfReport === null ? 'Not recorded' : `${selfReport} / 10`} />
            <Figure
              label="Estimated range"
              value={
                prediction.interval_low !== null && prediction.interval_high !== null
                  ? `${prediction.interval_low.toFixed(1)} to ${prediction.interval_high.toFixed(1)}`
                  : 'Not available'
              }
              tone="violet"
            />
            <Figure label="Data quality" value={prediction.data_quality.toLowerCase()} />
            <Figure label="Priority" value={prediction.priority_label ?? 'Not available'} />
            <p className="pt-1 text-[11px] leading-relaxed text-faint">
              The estimate supports the clinical conversation. Where it and the patient
              disagree, the patient's own report is the reference.
            </p>
          </div>
        </div>
      )}
    </Card>

    {prediction && prediction.alerts.length > 0 && (
      <Card className="space-y-2 p-5">
        <CardHead title="Clinical review cues" />
        {prediction.alerts.map((alert) => (
          <div key={alert.rule_code} className="rounded-[10px] border border-warn/25 bg-warn/8 p-3">
            <p className="text-[13px] font-semibold text-ink">{alert.label}</p>
            <p className="mt-1 text-[11.5px] leading-relaxed text-soft">{alert.advice}</p>
            {alert.context_notes.map((note) => (
              <p key={note} className="mt-1 text-[11px] text-mute">
                {note}
              </p>
            ))}
          </div>
        ))}
      </Card>
    )}

    {prediction && prediction.contributions.length > 0 && (
      <Card className="space-y-2 p-5">
        <CardHead title="What moved the estimate" sub="The largest contributions, as the explainer reports them." />
        <ul className="space-y-1.5">
          {prediction.contributions.slice(0, 10).map((entry) => (
            <li key={entry.feature} className="flex items-center gap-3 text-[12.5px]">
              <span className="min-w-0 flex-1 truncate text-soft">{entry.label}</span>
              <span
                className={cx(
                  'shrink-0 font-medium tabular-nums',
                  entry.contribution >= 0 ? 'text-warn' : 'text-teal',
                )}
              >
                {entry.contribution >= 0 ? '+' : ''}
                {entry.contribution.toFixed(2)}
              </span>
            </li>
          ))}
        </ul>
      </Card>
    )}

    {prediction && prediction.categories.length > 0 && (
      <Card className="space-y-2 p-5">
        <CardHead title="Compatible categories" sub="What the recorded picture is consistent with. Not a diagnosis." />
        <ul className="divide-y divide-hairline">
          {prediction.categories.slice(0, 8).map((entry) => (
            <li key={entry.cause_code} className="py-2">
              <div className="flex items-baseline justify-between gap-3">
                <span className="text-[13px] font-medium text-ink">{entry.label}</span>
                <span className="shrink-0 text-[12px] text-mute tabular-nums">
                  {(entry.score * 100).toFixed(0)}%
                </span>
              </div>
              {entry.missing.length > 0 && (
                <p className="mt-0.5 text-[11px] text-mute">Not recorded: {entry.missing.join(', ')}</p>
              )}
            </li>
          ))}
        </ul>
      </Card>
    )}

    {prediction && prediction.quality_issues.length > 0 && (
      <Card className="space-y-1.5 p-5">
        <CardHead title="Data quality findings" />
        {prediction.quality_issues.map((issue) => (
          <p key={issue} className="text-[11.5px] leading-relaxed text-warn">
            {issue}
          </p>
        ))}
      </Card>
    )}
  </>
);
