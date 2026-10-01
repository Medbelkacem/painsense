import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Filter, Plus, Search, Users } from 'lucide-react';

import { useQuery } from '../api/hooks';
import type { Analytics, Page, PatientSummary, Trend } from '../api/types';
import { Card, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile, type Tone } from '../ui/Pill';
import { SearchField, Toggle } from '../ui/Field';
import { DataTable, type Column } from '../ui/Table';
import { bandOf } from '../ui/charts';
import { whenShort } from '../lib/format';
import { SEX_LABEL } from '../lib/clinical';
import { PatientDialog } from '../components/PatientForm';

const PAGE_SIZE = 25;

const TREND_WORD: Record<Trend, string> = {
  RISING: 'Rising',
  FALLING: 'Falling',
  STABLE: 'Stable',
  UNKNOWN: '',
};

const TREND_TONE: Record<Trend, Tone> = {
  RISING: 'danger',
  FALLING: 'ok',
  STABLE: 'neutral',
  UNKNOWN: 'neutral',
};

const bandTone = (score: number): Tone => {
  const band = bandOf(score);
  return band === 'severe'
    ? 'danger'
    : band === 'moderate'
      ? 'warn'
      : band === 'mild'
        ? 'teal'
        : 'neutral';
};

const Metric: React.FC<{ label: string; value: React.ReactNode; note: string }> = ({
  label,
  value,
  note,
}) => (
  <Card className="p-4">
    <p className="text-xs font-medium text-mute">{label}</p>
    <p className="mt-2 text-[28px] leading-none font-semibold text-ink tabular-nums">{value}</p>
    <p className="mt-2 text-[11px] text-faint">{note}</p>
  </Card>
);

export const Patients: React.FC = () => {
  const navigate = useNavigate();

  const [query, setQuery] = useState('');
  const [needle, setNeedle] = useState('');
  const [archived, setArchived] = useState(false);
  const [page, setPage] = useState(0);
  const [creating, setCreating] = useState(false);

  // Debounced so a typed ward name is one request, not eight.
  React.useEffect(() => {
    const timer = window.setTimeout(() => {
      setNeedle(query.trim());
      setPage(0);
    }, 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  const path = useMemo(() => {
    const search = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    });
    if (needle) search.set('search', needle);
    if (archived) search.set('include_archived', 'true');
    return `/api/patients?${search}`;
  }, [needle, archived, page]);

  const { data, error, loading, reload } = useQuery<Page<PatientSummary>>(path);
  const analytics = useQuery<Analytics>('/api/analytics');

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(needle) || archived;

  const clear = () => {
    setQuery('');
    setArchived(false);
    setPage(0);
  };

  // The API returns the list newest-first and pages it server-side, so there is no column
  // sorting here: sorting one page of twenty-five would claim an order over the whole
  // list that the rows in hand cannot support.
  const columns: Column<PatientSummary>[] = [
    {
      key: 'patient',
      header: 'Patient',
      cell: (patient) => (
        <div className="flex items-center gap-2.5">
          <Tile
            tone={
              patient.latest_self_report === null
                ? 'neutral'
                : bandTone(patient.latest_self_report)
            }
          >
            {patient.code.slice(-3)}
          </Tile>
          <div className="min-w-0">
            <p className="truncate font-semibold text-ink">{patient.display_name}</p>
            <p className="truncate text-[11px] text-faint">{patient.code}</p>
          </div>
        </div>
      ),
    },
    {
      key: 'age',
      header: 'Age',
      hideBelow: 'md',
      cell: (patient) => <span className="text-mute tabular-nums">{patient.age ?? ''}</span>,
    },
    {
      key: 'sex',
      header: 'Sex',
      hideBelow: 'md',
      cell: (patient) => <span className="text-mute">{SEX_LABEL[patient.sex]}</span>,
    },
    {
      key: 'ward',
      header: 'Ward',
      hideBelow: 'lg',
      cell: (patient) => <span className="text-soft">{patient.ward ?? 'None recorded'}</span>,
    },
    {
      key: 'reported',
      header: 'Reported',
      cell: (patient) =>
        patient.latest_self_report === null ? (
          <span className="text-faint">none</span>
        ) : (
          <Tile tone={bandTone(patient.latest_self_report)} className="h-6 w-7 rounded-md">
            {patient.latest_self_report}
          </Tile>
        ),
    },
    {
      key: 'estimate',
      header: 'AI estimate',
      cell: (patient) =>
        patient.latest_estimated_pain === null ? (
          <span className="text-faint">none</span>
        ) : (
          <span className="font-semibold text-violet tabular-nums">
            {patient.latest_estimated_pain.toFixed(1)}
          </span>
        ),
    },
    {
      key: 'count',
      header: 'Assessments',
      hideBelow: 'lg',
      cell: (patient) => (
        <span className="text-mute tabular-nums">{patient.assessment_count}</span>
      ),
    },
    {
      key: 'last',
      header: 'Last assessment',
      hideBelow: 'md',
      cell: (patient) => (
        <span className="text-mute">
          {patient.latest_assessment_at
            ? whenShort(new Date(patient.latest_assessment_at))
            : 'None yet'}
        </span>
      ),
    },
    {
      key: 'trend',
      header: 'Trend',
      align: 'right',
      cell: (patient) => (
        <div className="flex items-center justify-end gap-1.5">
          {patient.archived && <Pill size="xs">archived</Pill>}
          {patient.trend !== 'UNKNOWN' && (
            <Pill tone={TREND_TONE[patient.trend]} size="xs">
              {TREND_WORD[patient.trend]}
            </Pill>
          )}
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHead
        title="Patients"
        sub="Everyone on file, newest assessment first."
        action={
          <Button
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            onClick={() => setCreating(true)}
          >
            New patient
          </Button>
        }
      />

      {error && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">
          The patient list could not be loaded: {error}
        </Card>
      )}

      <div className="grid grid-cols-2 gap-4 xl:grid-cols-4">
        <Metric
          label="All patients"
          value={analytics.data?.patients_total ?? 0}
          note="On file in this workspace"
        />
        <Metric
          label="Assessments"
          value={analytics.data?.assessments_total ?? 0}
          note={`${analytics.data?.assessments_today ?? 0} recorded today`}
        />
        <Metric
          label="Awaiting validation"
          value={analytics.data?.assessments_awaiting_validation ?? 0}
          note="Estimated but not yet validated by a doctor"
        />
        <Metric
          label="Estimated 7 or above"
          value={analytics.data?.high_pain_count ?? 0}
          note="Severe band on the latest estimate"
        />
      </div>

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <SearchField
            icon={<Search className="h-4 w-4" />}
            value={query}
            placeholder="Search by name, code or ward"
            onChange={(event) => setQuery(event.target.value)}
            className="w-full min-w-[14rem] sm:w-80"
          />
          <Toggle checked={archived} onChange={setArchived} label="Include archived" />
          {filtered && (
            <button
              type="button"
              onClick={clear}
              className="text-[13px] font-medium text-accent-ink hover:underline"
            >
              Clear
            </button>
          )}
          <span className="ml-auto text-[12px] text-faint">
            {loading ? 'Loading…' : `${rows.length} of ${total}`}
          </span>
        </div>

        <div className="mt-4">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(patient) => patient.id}
            onRowClick={(patient) => navigate(`/patients/${patient.id}`)}
            empty={
              <EmptyState
                icon={filtered ? <Filter className="h-5 w-5" /> : <Users className="h-5 w-5" />}
                title={filtered ? 'Nothing matches that search' : 'No patients yet'}
                sub={
                  filtered
                    ? 'Clear the search box, or widen it to a ward name.'
                    : 'Register the first patient, then create an assessment from their record.'
                }
                action={
                  filtered ? (
                    <Button size="sm" onClick={clear}>
                      Clear
                    </Button>
                  ) : (
                    <Button
                      variant="primary"
                      icon={<Plus className="h-4 w-4" />}
                      onClick={() => setCreating(true)}
                    >
                      Create assessment
                    </Button>
                  )
                }
              />
            }
          />
        </div>

        {pageCount > 1 && (
          <div className="mt-3 flex items-center justify-between border-t border-hairline pt-3 text-[12px] text-mute">
            <span>
              Showing {page * PAGE_SIZE + 1} to {Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
            </span>
            <div className="flex items-center gap-2">
              <Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </Button>
              <span className="tabular-nums">
                {page + 1} / {pageCount}
              </span>
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

      {creating && (
        <PatientDialog
          onClose={() => setCreating(false)}
          onSaved={(patient) => {
            setCreating(false);
            reload();
            analytics.reload();
            navigate(`/assessments/new?patient=${patient.id}`);
          }}
        />
      )}
    </>
  );
};
