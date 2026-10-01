import React, { useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  ArrowUpRight, ClipboardList, Plus, Stethoscope, TriangleAlert, Users,
} from 'lucide-react';

import { useQuery } from '../api/hooks';
import { useSession } from '../auth/session';
import type { Analytics, PainBandCode } from '../api/types';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile } from '../ui/Pill';
import { BarRows, bandOf, BAND_VAR, Sparkline } from '../ui/charts';
import { dateLong, percent, whenShort } from '../lib/format';

/** The bands the estimator reports, with the colour each is drawn in. */
const BANDS: { code: PainBandCode; label: string; range: string; colour: string }[] = [
  { code: 'NONE', label: 'No pain', range: '0', colour: BAND_VAR.none },
  { code: 'MILD', label: 'Mild', range: '1 – 3', colour: BAND_VAR.mild },
  { code: 'MODERATE', label: 'Moderate', range: '4 – 6', colour: BAND_VAR.moderate },
  { code: 'SEVERE', label: 'Severe', range: '7 – 9', colour: BAND_VAR.severe },
  { code: 'EXTREME', label: 'Extreme', range: '10', colour: BAND_VAR.severe },
];

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

const Stat: React.FC<{
  label: string;
  value: React.ReactNode;
  note: React.ReactNode;
  trend?: readonly number[];
  tone?: string;
  icon: React.ReactNode;
  to: string;
}> = ({ label, value, note, trend, tone = 'var(--accent)', icon, to }) => (
  <Link
    to={to}
    className="group rounded-[14px] border border-hairline bg-surface p-4 shadow-card transition-[transform,box-shadow] duration-200 hover:-translate-y-0.5 hover:shadow-lift"
  >
    <div className="flex items-start justify-between">
      <span className="text-xs font-medium text-mute">{label}</span>
      <span className="text-faint transition-colors group-hover:text-accent">{icon}</span>
    </div>
    <div className="mt-3 flex items-end justify-between gap-3">
      <div>
        <div className="text-[30px] leading-none font-semibold text-ink tabular-nums">{value}</div>
        <div className="mt-2">{note}</div>
      </div>
      {/* Only where there is a real series behind it. A sparkline over invented numbers
          is the one decoration this page cannot afford. */}
      {trend && trend.length > 2 && (
        <div className="w-24 shrink-0 opacity-90">
          <Sparkline values={trend} tone={tone} />
        </div>
      )}
    </div>
  </Link>
);

export const Dashboard: React.FC = () => {
  const navigate = useNavigate();
  const { user } = useSession();
  const { data, error, loading } = useQuery<Analytics>('/api/analytics', 120);

  const today = new Date();
  const greeting =
    today.getHours() < 12
      ? 'Good morning'
      : today.getHours() < 18
        ? 'Good afternoon'
        : 'Good evening';

  const bandTotal = useMemo(
    () => Object.values(data?.band_distribution ?? {}).reduce((sum, value) => sum + value, 0),
    [data],
  );

  const daily = data?.daily_mean_pain ?? [];
  const dailySeries = daily.map((point) => point.mean_pain);

  // The review queue: estimated but unsigned, worst disagreement first — that is the
  // order a clinician wants, not the order they were recorded in.
  const queue = useMemo(
    () =>
      (data?.recent_assessments ?? [])
        .filter((row) => row.status !== 'VALIDATED')
        .map((row) => ({
          row,
          drift:
            row.estimated_pain !== null && row.self_report !== null
              ? row.estimated_pain - row.self_report
              : null,
        }))
        .sort((a, b) => Math.abs(b.drift ?? 0) - Math.abs(a.drift ?? 0)),
    [data],
  );

  const regions = useMemo(
    () =>
      Object.entries(data?.region_distribution ?? {})
        .slice(0, 8)
        .map(([code, value]) => ({ label: REGION_WORD[code] ?? code, value })),
    [data],
  );

  const empty = data !== null && data.assessments_total === 0;

  return (
    <>
      <PageHead
        eyebrow={dateLong(today)}
        title={`${greeting}${user ? `, ${user.display_name}` : ''}.`}
        sub="Here is your clinical overview."
        action={
          <Button
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            kbd="N"
            onClick={() => navigate('/assessments/new')}
          >
            New assessment
          </Button>
        }
      />

      {error && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">
          The overview could not be loaded: {error}
        </Card>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat
          label="Patients"
          value={loading ? '—' : (data?.patients_total ?? 0)}
          note={<span className="text-[11px] text-faint">On file in this workspace</span>}
          icon={<Users className="h-4 w-4" />}
          to="/patients"
        />
        <Stat
          label="Today's assessments"
          value={loading ? '—' : (data?.assessments_today ?? 0)}
          note={
            <span className="text-[11px] text-faint">
              {data?.assessments_total ?? 0} in total
            </span>
          }
          trend={dailySeries.map((_, index) => daily[index].count)}
          tone="var(--brand-teal)"
          icon={<ClipboardList className="h-4 w-4" />}
          to="/assessments"
        />
        <Stat
          label="Awaiting a signature"
          value={loading ? '—' : (data?.assessments_awaiting_validation ?? 0)}
          note={
            (data?.assessments_awaiting_validation ?? 0) > 0 ? (
              <Pill tone="warn" size="xs">
                estimated, not signed
              </Pill>
            ) : (
              <span className="text-[11px] text-faint">Nothing outstanding</span>
            )
          }
          icon={<Stethoscope className="h-4 w-4" />}
          to="/assessments"
        />
        <Stat
          label="Open review cues"
          value={loading ? '—' : (data?.alerts_open ?? 0)}
          note={<span className="text-[11px] text-faint">Raised by the rule layer</span>}
          tone="var(--warn)"
          icon={<TriangleAlert className="h-4 w-4" />}
          to="/assessments"
        />
      </div>

      {empty ? (
        <Card>
          <EmptyState
            icon={<ClipboardList className="h-5 w-5" />}
            title="Nothing recorded yet"
            sub="Every figure on this page is computed from recorded assessments. Record the first one and the overview fills in."
            action={
              <Button
                variant="primary"
                icon={<Plus className="h-4 w-4" />}
                onClick={() => navigate('/assessments/new')}
              >
                New assessment
              </Button>
            }
          />
        </Card>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card className="p-5 xl:col-span-2">
              <CardHead
                title="Estimated pain by band"
                sub={`${bandTotal} estimate${bandTotal === 1 ? '' : 's'} on record`}
              />
              <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-5">
                {BANDS.map((band) => {
                  const count = data?.band_distribution[band.code] ?? 0;
                  return (
                    <div
                      key={band.code}
                      className="rounded-[10px] border border-hairline bg-sunken px-3 py-2.5"
                    >
                      <div className="flex items-center gap-1.5">
                        <span
                          className="h-2 w-2 shrink-0 rounded-full"
                          style={{ background: band.colour }}
                        />
                        <span className="truncate text-[11px] font-medium text-soft">
                          {band.label}
                        </span>
                      </div>
                      <div className="mt-1.5 flex items-baseline gap-1.5">
                        <span className="text-xl font-semibold text-ink tabular-nums">
                          {count}
                        </span>
                        <span className="text-[11px] text-mute">
                          {percent(count, bandTotal || 1)}
                        </span>
                      </div>
                      <span className="mt-0.5 block text-[10px] text-faint">{band.range}</span>
                    </div>
                  );
                })}
              </div>

              {daily.length > 1 ? (
                <div className="mt-6">
                  <div className="flex items-baseline justify-between">
                    <span className="eyebrow">Mean estimate, last 30 days</span>
                    <span className="text-[11px] text-faint tabular-nums">
                      {daily[0].date} → {daily[daily.length - 1].date}
                    </span>
                  </div>
                  <Sparkline values={dailySeries} className="mt-2 h-16" />
                </div>
              ) : (
                <p className="mt-6 text-[11.5px] text-faint">
                  A trend line appears once estimates exist on more than one day.
                </p>
              )}
            </Card>

            <Card className="flex flex-col p-5">
              <CardHead
                title="Agreement"
                sub="The model against the patient's own answer"
              />
              <dl className="mt-4 flex-1 space-y-3">
                <Measure
                  label="Mean reported"
                  value={data?.mean_self_report}
                  suffix=" / 10"
                />
                <Measure
                  label="Mean estimated"
                  value={data?.mean_estimated_pain}
                  suffix=" / 10"
                  tone="violet"
                />
                <Measure
                  label="Mean absolute error"
                  value={data?.estimate_vs_self_report_mae}
                  suffix=" points"
                />
                <Measure
                  label="Reported 7 or above"
                  value={data?.high_pain_count}
                  suffix=""
                />
              </dl>
              <p className="mt-4 border-t border-hairline pt-3 text-[11px] leading-relaxed text-faint">
                Where the two disagree, the patient's report is the reference. The error
                figure is the model's, not theirs.
              </p>
            </Card>
          </div>

          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <Card className="p-5 xl:col-span-2">
              <CardHead
                title="Review queue"
                sub="Estimated but not yet signed, widest disagreement first"
                action={
                  <Button size="sm" onClick={() => navigate('/assessments')}>
                    Open all
                  </Button>
                }
              />
              {queue.length === 0 ? (
                <p className="py-10 text-center text-[13px] text-mute">
                  Nothing is waiting on a signature.
                </p>
              ) : (
                <ul className="mt-3 divide-y divide-hairline">
                  {queue.slice(0, 6).map(({ row, drift }) => (
                    <li key={row.id}>
                      <Link
                        to={`/patients/${row.patient_id}`}
                        className="-mx-2 flex items-center gap-3 rounded-lg px-2 py-2.5 transition-colors hover:bg-sunken"
                      >
                        <Tile
                          tone={
                            row.self_report === null
                              ? 'neutral'
                              : bandOf(row.self_report) === 'severe'
                                ? 'danger'
                                : bandOf(row.self_report) === 'moderate'
                                  ? 'warn'
                                  : 'teal'
                          }
                          className="h-9 w-9"
                        >
                          {row.self_report ?? '—'}
                        </Tile>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13px] font-medium text-ink">
                            {row.patient_code}
                          </p>
                          <p className="truncate text-[11px] text-mute">
                            {row.location_labels.join(', ') || 'Location not recorded'}
                          </p>
                        </div>
                        <div className="hidden text-right sm:block">
                          <p className="text-[13px] font-semibold text-violet tabular-nums">
                            {row.estimated_pain?.toFixed(1) ?? '—'}
                          </p>
                          <p className="text-[10px] text-faint">AI estimate</p>
                        </div>
                        {drift !== null && (
                          <Pill
                            tone={Math.abs(drift) > 2.5 ? 'danger' : 'warn'}
                            size="xs"
                            className="shrink-0"
                          >
                            {drift > 0 ? '+' : '−'}
                            {Math.abs(drift).toFixed(1)}
                          </Pill>
                        )}
                        <ArrowUpRight className="h-3.5 w-3.5 shrink-0 text-faint" />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </Card>

            <div className="space-y-4">
              <Card className="p-5">
                <CardHead title="Where the pain is" sub="Across every recorded site" />
                {regions.length === 0 ? (
                  <p className="py-6 text-center text-[13px] text-mute">
                    No site has been recorded yet.
                  </p>
                ) : (
                  <div className="mt-4">
                    <BarRows rows={regions} />
                  </div>
                )}
              </Card>

              <Card className="p-5">
                <CardHead title="Latest activity" sub="Across the workspace" />
                <ol className="mt-4 space-y-3.5">
                  {(data?.recent_assessments ?? []).slice(0, 6).map((row, index, all) => (
                    <li key={row.id} className="flex gap-3">
                      <div className="flex flex-col items-center">
                        <span
                          className="mt-1 h-2 w-2 shrink-0 rounded-full ring-4 ring-[var(--surface)]"
                          style={{
                            background:
                              row.self_report === null
                                ? 'var(--hairline-strong)'
                                : BAND_VAR[bandOf(row.self_report)],
                          }}
                        />
                        {index < all.length - 1 && (
                          <span className="mt-1 w-px flex-1 bg-hairline" />
                        )}
                      </div>
                      <div className="min-w-0 flex-1 pb-0.5">
                        <p className="truncate text-[12.5px] text-ink">
                          <span className="font-medium">{row.patient_code}</span>{' '}
                          <span className="text-mute">
                            {row.self_report === null
                              ? '· no reported score'
                              : `· reported ${row.self_report}`}
                            {row.location_labels[0] ? ` · ${row.location_labels[0]}` : ''}
                          </span>
                        </p>
                        <p className="mt-0.5 text-[11px] text-faint">
                          {whenShort(new Date(row.created_at))} · {row.status.toLowerCase()}
                        </p>
                      </div>
                    </li>
                  ))}
                </ol>
              </Card>
            </div>
          </div>
        </>
      )}
    </>
  );
};

const Measure: React.FC<{
  label: string;
  value: number | null | undefined;
  suffix: string;
  tone?: 'violet';
}> = ({ label, value, suffix, tone }) => (
  <div className="flex items-baseline justify-between gap-3 border-b border-hairline pb-2">
    <dt className="text-[12px] text-mute">{label}</dt>
    <dd
      className={`text-[17px] font-semibold tabular-nums ${
        tone === 'violet' ? 'text-violet' : 'text-ink'
      }`}
    >
      {value === null || value === undefined ? '—' : `${value}${suffix}`}
    </dd>
  </div>
);
