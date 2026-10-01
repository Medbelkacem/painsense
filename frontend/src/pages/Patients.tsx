import React, { useCallback, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Filter, Plus, Search, Users, X } from 'lucide-react';

import { ApiError, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type {
  Analytics, Page, PatientDetail, PatientSummary, Sex, SmokingStatus, Trend,
} from '../api/types';
import { Card, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile, type Tone } from '../ui/Pill';
import { SearchField, TextField, Toggle } from '../ui/Field';
import { Select } from '../ui/Dropdown';
import { DataTable, type Column } from '../ui/Table';
import { bandOf } from '../ui/charts';
import { whenShort } from '../lib/format';

const PAGE_SIZE = 25;

const SEX_LABEL: Record<Sex, string> = {
  F: 'Female',
  M: 'Male',
  OTHER: 'Other',
  UNDISCLOSED: 'Not disclosed',
};

const SMOKING_LABEL: Record<SmokingStatus, string> = {
  NEVER: 'Never smoked',
  FORMER: 'Former smoker',
  CURRENT: 'Current smoker',
  UNKNOWN: 'Not known',
};

const TREND_WORD: Record<Trend, string> = {
  RISING: 'Rising',
  FALLING: 'Falling',
  STABLE: 'Stable',
  UNKNOWN: '—',
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
  const [syntheticOnly, setSyntheticOnly] = useState(false);
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
    if (syntheticOnly) search.set('synthetic_only', 'true');
    return `/api/patients?${search}`;
  }, [needle, archived, syntheticOnly, page]);

  const { data, error, loading, reload } = useQuery<Page<PatientSummary>>(path);
  const analytics = useQuery<Analytics>('/api/analytics');

  const rows = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const filtered = Boolean(needle) || archived || syntheticOnly;

  const clear = () => {
    setQuery('');
    setArchived(false);
    setSyntheticOnly(false);
    setPage(0);
  };

  // The API returns the list newest-first and pages it server-side, so there is no column
  // sorting here: sorting one page of twenty-five would claim an order over the whole
  // cohort that the rows in hand cannot support.
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
      cell: (patient) => <span className="text-mute tabular-nums">{patient.age ?? '—'}</span>,
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
      cell: (patient) => <span className="text-soft">{patient.ward ?? '—'}</span>,
    },
    {
      key: 'reported',
      header: 'Reported',
      cell: (patient) =>
        patient.latest_self_report === null ? (
          <span className="text-faint">—</span>
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
          <span className="text-faint">—</span>
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
          {patient.is_synthetic && (
            <Pill tone="violet" size="xs">
              synthetic
            </Pill>
          )}
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
          value={analytics.data?.patients_total ?? '—'}
          note="On file in this workspace"
        />
        <Metric
          label="Assessments"
          value={analytics.data?.assessments_total ?? '—'}
          note={`${analytics.data?.assessments_today ?? 0} recorded today`}
        />
        <Metric
          label="Awaiting a signature"
          value={analytics.data?.assessments_awaiting_validation ?? '—'}
          note="Estimated but not yet validated"
        />
        <Metric
          label="Reported 7 or above"
          value={analytics.data?.high_pain_count ?? '—'}
          note="Severe pain on the latest assessment"
        />
      </div>

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-3">
          <SearchField
            icon={<Search className="h-4 w-4" />}
            value={query}
            placeholder="Search by name, code or ward…"
            onChange={(event) => setQuery(event.target.value)}
            className="w-full min-w-[14rem] sm:w-80"
          />
          <Toggle checked={archived} onChange={setArchived} label="Include archived" />
          <Toggle checked={syntheticOnly} onChange={setSyntheticOnly} label="Synthetic only" />
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
                title={filtered ? 'Nothing matches that search' : 'No patient on file yet'}
                sub={
                  filtered
                    ? 'Clear the search box, or widen it to a ward name.'
                    : 'Register the first patient and the assessment wizard has somebody to record against.'
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
                      New patient
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
              Showing {page * PAGE_SIZE + 1}–{Math.min(total, (page + 1) * PAGE_SIZE)} of {total}
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
        <NewPatient
          onClose={() => setCreating(false)}
          onCreated={(patient) => {
            setCreating(false);
            reload();
            analytics.reload();
            navigate(`/patients/${patient.id}`);
          }}
        />
      )}
    </>
  );
};

/** Registering a patient. The minimum the record needs; the rest is filled in on the
 *  assessment itself, where the clinician already has the patient in front of them. */
const NewPatient: React.FC<{
  onClose: () => void;
  onCreated: (patient: PatientDetail) => void;
}> = ({ onClose, onCreated }) => {
  const [givenName, setGivenName] = useState('');
  const [familyName, setFamilyName] = useState('');
  const [sex, setSex] = useState<Sex>('UNDISCLOSED');
  const [birthDate, setBirthDate] = useState('');
  const [ward, setWard] = useState('');
  const [phone, setPhone] = useState('');
  const [contactName, setContactName] = useState('');
  const [contactPhone, setContactPhone] = useState('');
  const [smoking, setSmoking] = useState<SmokingStatus>('UNKNOWN');
  const [synthetic, setSynthetic] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const submit = useCallback(async () => {
    setBusy(true);
    setFailure(null);
    try {
      onCreated(
        await request<PatientDetail>('/api/patients', {
          method: 'POST',
          body: {
            identity: {
              given_name: givenName.trim(),
              family_name: familyName.trim(),
              phone: phone.trim() || null,
              emergency_contact_name: contactName.trim() || null,
              emergency_contact_phone: contactPhone.trim() || null,
            },
            sex,
            birth_date: birthDate || null,
            ward: ward.trim() || null,
            smoking_status: smoking,
            is_synthetic: synthetic,
          },
        }),
      );
    } catch (cause) {
      setFailure(
        cause instanceof ApiError ? cause.message : 'The patient could not be registered.',
      );
      setBusy(false);
    }
  }, [
    birthDate, contactName, contactPhone, familyName, givenName, onCreated, phone, sex,
    smoking, synthetic, ward,
  ]);

  const complete = givenName.trim().length > 0 && familyName.trim().length > 0;

  return (
    <div
      className="fixed inset-0 z-[90] flex items-start justify-center overflow-y-auto bg-[#0b1b33]/40 px-4 py-[8vh] backdrop-blur-[2px]"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal
        aria-label="Register a patient"
        className="w-full max-w-2xl rounded-2xl border border-hairline bg-surface p-5 shadow-pop"
      >
        <div className="flex items-start justify-between gap-4 pb-4">
          <div>
            <h2 className="text-[17px] font-semibold text-ink">Register a patient</h2>
            <p className="mt-1 text-[12px] text-mute">
              The identifier is assigned by the platform. The name is sealed at rest.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded-lg p-1.5 text-faint hover:bg-sunken hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {failure && (
          <p className="mb-4 rounded-[10px] border border-danger/25 bg-danger/8 px-3 py-2 text-[12px] text-danger">
            {failure}
          </p>
        )}

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <TextField
            label="Given name"
            value={givenName}
            onChange={(event) => setGivenName(event.target.value)}
          />
          <TextField
            label="Family name"
            value={familyName}
            onChange={(event) => setFamilyName(event.target.value)}
          />
          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-soft">Sex</span>
            <Select
              label="Sex"
              className="w-full [&>button]:w-full"
              options={(Object.keys(SEX_LABEL) as Sex[]).map((value) => ({
                value,
                label: SEX_LABEL[value],
              }))}
              value={sex}
              onChange={(value) => setSex((value ?? 'UNDISCLOSED') as Sex)}
            />
          </div>
          <TextField
            label="Date of birth"
            type="date"
            value={birthDate}
            onChange={(event) => setBirthDate(event.target.value)}
          />
          <TextField
            label="Ward"
            placeholder="Emergency department"
            value={ward}
            onChange={(event) => setWard(event.target.value)}
          />
          <TextField
            label="Telephone"
            value={phone}
            onChange={(event) => setPhone(event.target.value)}
          />
          <TextField
            label="Emergency contact"
            value={contactName}
            onChange={(event) => setContactName(event.target.value)}
          />
          <TextField
            label="Emergency telephone"
            value={contactPhone}
            onChange={(event) => setContactPhone(event.target.value)}
          />
          <div className="space-y-1.5">
            <span className="block text-xs font-medium text-soft">Smoking status</span>
            <Select
              label="Smoking status"
              className="w-full [&>button]:w-full"
              options={(Object.keys(SMOKING_LABEL) as SmokingStatus[]).map((value) => ({
                value,
                label: SMOKING_LABEL[value],
              }))}
              value={smoking}
              onChange={(value) => setSmoking((value ?? 'UNKNOWN') as SmokingStatus)}
            />
          </div>
        </div>

        <div className="mt-4 border-t border-hairline pt-4">
          <Toggle
            checked={synthetic}
            onChange={setSynthetic}
            label="This is a synthetic record"
          />
          <p className="mt-1 text-[11px] leading-relaxed text-faint">
            Marks the record as made up rather than a real person, so it is labelled
            everywhere it appears and can be excluded from an export.
          </p>
        </div>

        <div className="mt-5 flex items-center justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="primary"
            icon={<Plus className="h-4 w-4" />}
            disabled={!complete || busy}
            onClick={() => void submit()}
          >
            {busy ? 'Registering…' : 'Register'}
          </Button>
        </div>
      </div>
    </div>
  );
};
