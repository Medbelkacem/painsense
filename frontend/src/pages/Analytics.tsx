import React, { useMemo } from 'react';
import { LineChart } from 'lucide-react';

import { useQuery } from '../api/hooks';
import type { Analytics as AnalyticsOut, AssessmentSummary, Page } from '../api/types';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Pill } from '../ui/Pill';
import {
  AgreementPlot, BandBars, BarRows, BAND_VAR, Donut, Sparkline, bandOf,
} from '../ui/charts';
import { percent } from '../lib/format';

/** How many assessments the scatter and the distribution are drawn from. */
const SAMPLE = 100;

const BAND_COLOUR: Record<string, string> = {
  NONE: BAND_VAR.none,
  MILD: BAND_VAR.mild,
  MODERATE: BAND_VAR.moderate,
  SEVERE: BAND_VAR.severe,
  EXTREME: 'var(--brand-violet)',
};

const REGION_WORD: Record<string, string> = {
  HEAD: 'Head',
  NECK: 'Neck',
  CHEST: 'Chest',
  ABDOMEN: 'Abdomen',
  PELVIS: 'Pelvis',
  BACK: 'Back',
  UPPER_LIMB: 'Upper limb',
  LOWER_LIMB: 'Lower limb',
  GENERALISED: 'Generalised',
};

export const Analytics: React.FC = () => {
  const analytics = useQuery<AnalyticsOut>('/api/analytics', 120);
  // The aggregate endpoint has no per-assessment pairs, and the scatter needs them. One
  // page of summaries is enough to draw it, and the caption says so rather than implying
  // the whole cohort is plotted.
  const recent = useQuery<Page<AssessmentSummary>>(`/api/assessments?limit=${SAMPLE}`);

  const rows = recent.data?.items ?? [];

  const paired = useMemo(
    () =>
      rows
        .filter((row) => row.self_report !== null && row.estimated_pain !== null)
        .map((row) => ({
          reported: row.self_report as number,
          estimate: row.estimated_pain as number,
        })),
    [rows],
  );

  /** Eleven buckets of reported score, from the sample in hand. */
  const counts = useMemo(() => {
    const buckets = Array.from({ length: 11 }, () => 0);
    for (const row of rows) {
      if (row.self_report === null) continue;
      const score = Math.round(row.self_report);
      if (score >= 0 && score <= 10) buckets[score] += 1;
    }
    return buckets;
  }, [rows]);

  const reportedCount = counts.reduce((sum, value) => sum + value, 0);

  const bands = useMemo(
    () =>
      Object.entries(analytics.data?.band_distribution ?? {}).map(([code, value]) => ({
        label: code.toLowerCase(),
        value,
        colour: BAND_COLOUR[code] ?? 'var(--accent)',
      })),
    [analytics.data],
  );

  const bandTotal = bands.reduce((sum, slice) => sum + slice.value, 0);

  const regions = useMemo(
    () =>
      Object.entries(analytics.data?.region_distribution ?? {})
        .slice(0, 9)
        .map(([code, value]) => ({ label: REGION_WORD[code] ?? code, value })),
    [analytics.data],
  );

  const daily = analytics.data?.daily_mean_pain ?? [];
  const severeShare = analytics.data
    ? percent(analytics.data.high_pain_count, analytics.data.assessments_total || 1)
    : '—';

  const empty = analytics.data !== null && analytics.data.assessments_total === 0;

  return (
    <>
      <PageHead
        title="Analytics"
        sub="Cohort patterns across assessments. Every figure traces back to the records you can open."
        action={
          analytics.data && (
            <Pill size="xs">
              {analytics.data.assessments_total} assessment
              {analytics.data.assessments_total === 1 ? '' : 's'}
            </Pill>
          )
        }
      />

      {analytics.error && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">
          The figures could not be loaded: {analytics.error}
        </Card>
      )}

      {empty ? (
        <Card>
          <EmptyState
            icon={<LineChart className="h-5 w-5" />}
            title="Nothing to analyse yet"
            sub="This page is computed from recorded assessments. It fills in as they are recorded."
          />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            {[
              {
                label: 'Mean reported',
                value: analytics.data?.mean_self_report?.toFixed(1) ?? '—',
                note: 'Patient-reported, out of 10',
              },
              {
                label: 'Mean estimated',
                value: analytics.data?.mean_estimated_pain?.toFixed(1) ?? '—',
                note: 'Model output, out of 10',
              },
              {
                label: 'Mean |AI − reported|',
                value: analytics.data?.estimate_vs_self_report_mae?.toFixed(2) ?? '—',
                note: 'Where both numbers exist',
              },
              {
                label: 'Severe share',
                value: severeShare,
                note: 'Estimated 7 and above',
              },
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

          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            <Card className="p-5">
              <CardHead
                title="Reported pain distribution"
                sub={`Patient-reported score across the ${reportedCount} most recent assessments carrying one`}
              />
              {reportedCount === 0 ? (
                <p className="py-10 text-center text-[13px] text-mute">
                  No reported score on record yet.
                </p>
              ) : (
                <div className="mt-4">
                  <BandBars counts={counts} />
                  <div className="mt-2 flex justify-between text-[11px] text-faint">
                    <span>0 · No pain</span>
                    <span>10 · Worst imaginable</span>
                  </div>
                </div>
              )}
            </Card>

            <Card className="p-5">
              <CardHead title="Pain by region" sub="Every recorded site, across all assessments" />
              {regions.length === 0 ? (
                <p className="py-10 text-center text-[13px] text-mute">
                  No site has been recorded yet.
                </p>
              ) : (
                <div className="mt-4">
                  <BarRows rows={regions} colour="var(--accent)" />
                </div>
              )}
            </Card>

            <Card className="p-5">
              <CardHead title="Estimates by band" sub="Share of every estimate on record" />
              {bands.length === 0 ? (
                <p className="py-10 text-center text-[13px] text-mute">
                  Nothing has been estimated yet.
                </p>
              ) : (
                <div className="mt-4 flex flex-wrap items-center gap-6">
                  <Donut slices={bands} />
                  <ul className="min-w-[180px] flex-1 space-y-1.5">
                    {bands.map((slice) => (
                      <li key={slice.label} className="flex items-center gap-2 text-[12px]">
                        <span
                          className="h-2.5 w-2.5 shrink-0 rounded-sm"
                          style={{ background: slice.colour }}
                        />
                        <span className="min-w-0 flex-1 truncate text-soft">{slice.label}</span>
                        <span className="font-medium text-ink tabular-nums">
                          {percent(slice.value, bandTotal)}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </Card>

            <Card className="p-5">
              <CardHead title="Estimated pain over time" sub="Daily mean, last 30 days" />
              {daily.length < 2 ? (
                <p className="py-10 text-center text-[13px] text-mute">
                  A trend line needs estimates on more than one day.
                </p>
              ) : (
                <>
                  <div className="mt-6">
                    <Sparkline
                      values={daily.map((point) => point.mean_pain)}
                      tone="var(--accent)"
                      className="h-40"
                    />
                  </div>
                  <div className="mt-2 flex justify-between text-[11px] text-faint tabular-nums">
                    <span>{daily[0].date}</span>
                    <span>{daily[daily.length - 1].date}</span>
                  </div>
                </>
              )}
            </Card>

            <Card className="p-5 lg:col-span-2">
              <CardHead
                title="AI estimate against the patient's own answer"
                sub={`Each point is one assessment. The dashed line is perfect agreement. ${paired.length} of the ${SAMPLE} most recent carry both numbers.`}
              />
              {paired.length === 0 ? (
                <p className="py-10 text-center text-[13px] text-mute">
                  No assessment yet carries both a reported score and an estimate.
                </p>
              ) : (
                <div className="mt-4 flex flex-wrap items-center gap-8">
                  <div className="w-full max-w-[260px]">
                    <AgreementPlot points={paired} />
                    <p className="mt-1 text-center text-[11px] text-faint">
                      x · reported — y · model estimate
                    </p>
                  </div>
                  <ul className="min-w-[220px] flex-1 space-y-2.5">
                    {[0, 1, 2, 3].map((threshold) => {
                      const within = paired.filter(
                        (point) => Math.abs(point.estimate - point.reported) <= threshold + 0.5,
                      ).length;
                      return (
                        <li key={threshold}>
                          <div className="flex items-baseline justify-between text-[12px]">
                            <span className="text-mute">Within ±{threshold + 0.5} points</span>
                            <span className="font-semibold text-ink tabular-nums">
                              {percent(within, paired.length)}
                            </span>
                          </div>
                          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-sunken">
                            <div
                              className="h-full rounded-full transition-[width] duration-500"
                              style={{
                                width: percent(within, paired.length),
                                background: BAND_VAR[bandOf(10 - threshold * 3)],
                              }}
                            />
                          </div>
                        </li>
                      );
                    })}
                  </ul>
                </div>
              )}
            </Card>
          </div>
        </>
      )}
    </>
  );
};
