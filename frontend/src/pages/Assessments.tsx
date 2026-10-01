import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ClipboardList, Plus, Search, SlidersHorizontal } from 'lucide-react';

import { useQuery } from '../api/hooks';
import type { AssessmentStatus, AssessmentSummary, Page } from '../api/types';
import { Card, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile, type Tone } from '../ui/Pill';
import { SearchField, Toggle } from '../ui/Field';
import { Segmented } from '../ui/Segmented';
import { DataTable, type Column } from '../ui/Table';
import { bandOf } from '../ui/charts';
import { whenShort } from '../lib/format';

type Lane = 'all' | 'DRAFT' | 'ESTIMATED' | 'VALIDATED';

const LANE_LABEL: Record<Lane, string> = {
  all: 'All',
  DRAFT: 'Drafts',
  ESTIMATED: 'Estimated',
  VALIDATED: 'Signed',
};

const STATUS_TONE: Record<AssessmentStatus, Tone> = {
  DRAFT: 'neutral',
  ESTIMATED: 'accent',
  VALIDATED: 'ok',
};

const STATUS_WORD: Record<AssessmentStatus, string> = {
  DRAFT: 'Draft',
  ESTIMATED: 'Estimated',
  VALIDATED: 'Signed',
};

const PRIORITY_TONE: Record<string, Tone> = {
  HIGH: 'danger',
  ELEVATED: 'warn',
  MODERATE: 'warn',
  ROUTINE: 'neutral',
  LOW: 'neutral',
};

const PAGE_SIZE = 25;

const bandTone = (score: number): Tone => {
  const band = bandOf(score);
  return band === 'severe' ? 'danger' : band === 'moderate' ? 'warn' : band === 'mild' ? 'teal' : 'neutral';
};

export const Assessments: React.FC = () => {
  const navigate = useNavigate();
  const [lane, setLane] = useState<Lane>('all');
  const [mine, setMine] = useState(false);
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);

  const path = useMemo(() => {
    const search = new URLSearchParams({
      limit: String(PAGE_SIZE),
      offset: String(page * PAGE_SIZE),
    });
    if (lane !== 'all') search.set('status', lane);
    if (mine) search.set('mine_only', 'true');
    return `/api/assessments?${search}`;
  }, [lane, mine, page]);

  const { data, error, loading } = useQuery<Page<AssessmentSummary>>(path, 60);

  // The API pages and filters by status; the box narrows the page in hand by patient code
  // or location, which is what a clinician scanning a ward list is doing.
  const rows = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return data?.items ?? [];
    return (data?.items ?? []).filter((row) =>
      `${row.patient_code} ${row.location_labels.join(' ')}`.toLowerCase().includes(needle),
    );
  }, [data, query]);

  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const columns: Column<AssessmentSummary>[] = [
    {
      key: 'patient',
      header: 'Patient',
      cell: (row) => <span className="font-semibold text-ink">{row.patient_code}</span>,
    },
    {
      key: 'age',
      header: 'Age',
      hideBelow: 'lg',
      cell: (row) => (
        <span className="text-mute tabular-nums">{row.patient_age_years ?? '—'}</span>
      ),
    },
    {
      key: 'site',
      header: 'Location',
      hideBelow: 'sm',
      cell: (row) => (
        <span className="text-mute">{row.location_labels.join(', ') || 'Not recorded'}</span>
      ),
    },
    {
      key: 'at',
      header: 'When',
      hideBelow: 'md',
      cell: (row) => <span className="text-mute">{whenShort(new Date(row.created_at))}</span>,
    },
    {
      key: 'reported',
      header: 'Reported',
      cell: (row) =>
        row.self_report === null ? (
          <span className="text-faint">—</span>
        ) : (
          <Tile tone={bandTone(row.self_report)} className="h-6 w-7 rounded-md">
            {row.self_report}
          </Tile>
        ),
    },
    {
      key: 'estimate',
      header: 'AI',
      cell: (row) =>
        row.estimated_pain === null ? (
          <span className="text-faint">—</span>
        ) : (
          <span className="font-semibold text-violet tabular-nums">
            {row.estimated_pain.toFixed(1)}
          </span>
        ),
    },
    {
      key: 'priority',
      header: 'Priority',
      hideBelow: 'lg',
      cell: (row) =>
        row.priority_level === null ? (
          <span className="text-faint">—</span>
        ) : (
          <Pill tone={PRIORITY_TONE[row.priority_level] ?? 'neutral'} size="xs">
            {row.priority_level.toLowerCase()}
          </Pill>
        ),
    },
    {
      key: 'alerts',
      header: 'Cues',
      hideBelow: 'lg',
      cell: (row) =>
        row.alert_count > 0 ? (
          <Pill tone="warn" size="xs">
            {row.alert_count}
          </Pill>
        ) : (
          <span className="text-faint">—</span>
        ),
    },
    {
      key: 'status',
      header: 'Status',
      align: 'right',
      cell: (row) => (
        <div className="flex items-center justify-end gap-1.5">
          {row.is_synthetic && (
            <Pill tone="violet" size="xs">
              synthetic
            </Pill>
          )}
          <Pill tone={STATUS_TONE[row.status]} size="xs" dot>
            {STATUS_WORD[row.status]}
          </Pill>
        </div>
      ),
    },
  ];

  return (
    <>
      <PageHead
        title="Assessments"
        sub="Drafts, signed records and everything still waiting on a clinician."
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

      {error && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">
          The assessments could not be loaded: {error}
        </Card>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <Segmented
            size="md"
            options={(Object.keys(LANE_LABEL) as Lane[]).map((value) => ({
              value,
              label: value === 'all' ? `All ${total}` : LANE_LABEL[value],
            }))}
            value={lane}
            onChange={(value) => {
              setLane(value);
              setPage(0);
            }}
          />
          <SearchField
            icon={<Search className="h-4 w-4" />}
            value={query}
            placeholder="Patient code or location…"
            onChange={(event) => setQuery(event.target.value)}
            className="w-full min-w-[12rem] sm:w-64"
          />
          <Toggle checked={mine} onChange={setMine} label="Only mine" />
          <span className="ml-auto text-[12px] text-faint">
            {loading ? 'Loading…' : `${rows.length} shown of ${total}`}
          </span>
        </div>

        <div className="mt-4">
          <DataTable
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            onRowClick={(row) => navigate(`/patients/${row.patient_id}`)}
            empty={
              <EmptyState
                icon={<SlidersHorizontal className="h-5 w-5" />}
                title={total === 0 ? 'No assessment recorded yet' : 'Nothing in this lane'}
                sub={
                  total === 0
                    ? 'Record one and it appears here, with the estimate beside the patient’s own answer.'
                    : 'Switch to All, or clear the search box.'
                }
                action={
                  total === 0 ? (
                    <Button
                      variant="primary"
                      icon={<Plus className="h-4 w-4" />}
                      onClick={() => navigate('/assessments/new')}
                    >
                      New assessment
                    </Button>
                  ) : undefined
                }
              />
            }
          />
        </div>

        {pageCount > 1 && (
          <div className="mt-3 flex items-center justify-between border-t border-hairline pt-3 text-[12px] text-mute">
            <span>
              Page {page + 1} of {pageCount}
            </span>
            <div className="flex gap-2">
              <Button size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>
                Previous
              </Button>
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

      <Card className="flex flex-wrap items-center gap-4 p-4">
        <Tile tone="accent" className="h-9 w-9 rounded-lg">
          <ClipboardList className="h-4 w-4" />
        </Tile>
        <p className="min-w-0 flex-1 text-[12.5px] text-mute">
          An assessment stays a draft until a clinician signs it. The model estimate is recorded
          alongside the patient's own answer — never instead of it.
        </p>
      </Card>
    </>
  );
};
