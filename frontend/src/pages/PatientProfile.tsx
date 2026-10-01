import React, { useCallback, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Activity, AlertTriangle, ArrowLeft, ChevronRight, FileDown, FileText, HeartPulse, Pencil,
  Plus, Thermometer, Trash2, Wind,
} from 'lucide-react';

import { ApiError, download, request } from '../api/client';
import { useQuery } from '../api/hooks';
import { useSession } from '../auth/session';
import type {
  AssessmentStatus, AssessmentSummary, ClinicalDocument, Disease, PatientBaseline,
  PatientDetail, PatientHistory, PatientTimeline,
} from '../api/types';
import { Card, CardHead, EmptyState } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile, type Tone } from '../ui/Pill';
import { Tabs } from '../ui/Nav';
import { DataTable, type Column } from '../ui/Table';
import { bandOf, BAND_LABEL, BAND_VAR, TrendChart, type TrendPoint } from '../ui/charts';
import { whenShort } from '../lib/format';
import { NONE_RECORDED, SEX_LABEL, SMOKING_LABEL } from '../lib/clinical';
import { PatientDialog } from '../components/PatientForm';

type TabKey = 'overview' | 'assessments' | 'history' | 'medical' | 'documents' | 'timeline';

const STATUS_TONE: Record<AssessmentStatus, Tone> = {
  DRAFT: 'neutral',
  ESTIMATED: 'accent',
  VALIDATED: 'ok',
};

const STATUS_WORD: Record<AssessmentStatus, string> = {
  DRAFT: 'Draft',
  ESTIMATED: 'Estimated',
  VALIDATED: 'Validated',
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

const Vital: React.FC<{
  icon: React.ReactNode;
  label: string;
  value: string;
  unit: string;
}> = ({ icon, label, value, unit }) => (
  <div className="flex items-center gap-2">
    <span className="text-faint">{icon}</span>
    <div className="leading-tight">
      <p className="text-[10px] text-faint">{label}</p>
      <p className="text-[13px] font-semibold text-ink tabular-nums">
        {value}
        <span className="ml-0.5 text-[10px] font-normal text-mute">{unit}</span>
      </p>
    </div>
  </div>
);

interface PatientProfileProps {
  /** Given by the patient's own page; the route parameter otherwise. */
  patientId?: string;
}

export const PatientProfile: React.FC<PatientProfileProps> = ({ patientId }) => {
  const { id: routeId } = useParams<{ id: string }>();
  const id = patientId ?? routeId;
  const navigate = useNavigate();
  const { user } = useSession();
  const [tab, setTab] = useState<TabKey>('overview');
  const [failure, setFailure] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [busy, setBusy] = useState(false);

  const readOnly = user?.role === 'PATIENT';
  const mayDelete = user?.role === 'DOCTOR' || user?.role === 'SUPER_ADMIN' || user?.role === 'CLINIC_ADMIN';

  const patient = useQuery<PatientDetail>(id ? `/api/patients/${id}` : null);
  const history = useQuery<PatientHistory>(id ? `/api/patients/${id}/history` : null);
  const assessments = useQuery<AssessmentSummary[]>(
    id ? `/api/patients/${id}/assessments` : null,
  );
  const baseline = useQuery<PatientBaseline>(id ? `/api/patients/${id}/baseline` : null);
  const timeline = useQuery<PatientTimeline>(
    tab === 'timeline' && id ? `/api/patients/${id}/timeline` : null,
  );
  const documents = useQuery<ClinicalDocument[]>(
    id && !readOnly ? `/api/documents?patient_id=${id}` : null,
  );
  const diseases = useQuery<Disease[]>(tab === 'medical' ? '/api/diseases' : null);

  const diseaseLabel = useMemo(
    () => new Map((diseases.data ?? []).map((entry) => [entry.code, entry.label])),
    [diseases.data],
  );

  const points = useMemo<TrendPoint[]>(
    () =>
      (history.data?.points ?? [])
        .filter((point) => point.self_report !== null || point.estimated_pain !== null)
        .map((point) => ({
          label: new Date(point.created_at).toLocaleDateString('en-GB', {
            day: '2-digit',
            month: 'short',
          }),
          reported: point.self_report ?? 0,
          estimate: point.estimated_pain ?? 0,
        })),
    [history.data],
  );

  const latestVitals = useMemo(
    () => (history.data?.points ?? []).at(-1) ?? null,
    [history.data],
  );

  const exportPdf = useCallback(async (assessmentId: string) => {
    setFailure(null);
    try {
      await download(`/api/reports/${assessmentId}/generate`, 'pain-assessment.pdf');
    } catch (cause) {
      setFailure(
        cause instanceof ApiError ? cause.message : 'The report could not be generated.',
      );
    }
  }, []);

  const remove = useCallback(async () => {
    if (!id) return;
    setBusy(true);
    setFailure(null);
    try {
      await request<void>(`/api/patients/${id}`, { method: 'DELETE' });
      navigate('/patients', { replace: true });
    } catch (cause) {
      setFailure(cause instanceof ApiError ? cause.message : 'The record could not be deleted.');
      setBusy(false);
      setConfirmDelete(false);
    }
  }, [id, navigate]);

  if (patient.error) {
    return (
      <Card>
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="That patient could not be opened"
          sub={patient.error}
          action={
            readOnly ? undefined : (
              <Button
                size="sm"
                icon={<ArrowLeft className="h-4 w-4" />}
                onClick={() => navigate('/patients')}
              >
                Back to patients
              </Button>
            )
          }
        />
      </Card>
    );
  }

  if (!patient.data) {
    return <p className="py-16 text-center text-[13px] text-mute">Loading the record…</p>;
  }

  const record = patient.data;
  const reported = record.latest_self_report;
  const estimate = record.latest_estimated_pain;

  const columns: Column<AssessmentSummary>[] = [
    {
      key: 'at',
      header: 'When',
      cell: (row) => (
        <span className="font-medium text-ink">{whenShort(new Date(row.created_at))}</span>
      ),
    },
    {
      key: 'site',
      header: 'Site',
      hideBelow: 'sm',
      cell: (row) => (
        <span className="text-soft">{row.location_labels.join(', ') || NONE_RECORDED}</span>
      ),
    },
    {
      key: 'reported',
      header: 'Reported',
      cell: (row) => (
        <span className="font-semibold text-ink tabular-nums">{row.self_report ?? ''}</span>
      ),
    },
    {
      key: 'estimate',
      header: 'AI',
      cell: (row) => (
        <span className="font-semibold text-violet tabular-nums">
          {row.estimated_pain?.toFixed(1) ?? ''}
        </span>
      ),
    },
    {
      key: 'priority',
      header: 'Priority',
      hideBelow: 'md',
      cell: (row) => (
        <span className="text-mute">{row.priority_level?.toLowerCase() ?? ''}</span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      align: 'right',
      cell: (row) => (
        <span className="inline-flex items-center justify-end gap-2">
          <Pill tone={STATUS_TONE[row.status]} size="xs">
            {STATUS_WORD[row.status]}
          </Pill>
          <button
            type="button"
            aria-label="Export the PDF"
            title="Export the PDF"
            onClick={(event) => {
              event.stopPropagation();
              void exportPdf(row.id);
            }}
            className="rounded-md p-1 text-faint transition-colors hover:bg-sunken hover:text-ink"
          >
            <FileDown className="h-3.5 w-3.5" />
          </button>
        </span>
      ),
    },
  ];

  return (
    <>
      {!readOnly && (
        <nav className="flex items-center gap-1.5 text-[13px] text-mute">
          <Link to="/patients" className="transition-colors hover:text-ink">
            Patients
          </Link>
          <ChevronRight className="h-3.5 w-3.5 text-faint" />
          <span className="font-medium text-ink">{record.code}</span>
        </nav>
      )}

      {failure && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">{failure}</Card>
      )}

      <Card className="p-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-4">
            <Tile tone="accent" className="h-12 w-12 rounded-xl text-base">
              {record.code.slice(-3)}
            </Tile>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[11px] text-faint">Patient</span>
                {record.archived && <Pill size="xs">Archived</Pill>}
              </div>
              <h1 className="mt-0.5 text-[24px] leading-tight font-semibold text-ink">
                {record.display_name}
              </h1>
              <p className="mt-1 text-[13px] text-mute">
                {[
                  record.code,
                  record.age !== null ? `${record.age} ${record.age === 1 ? 'year' : 'years'}` : null,
                  SEX_LABEL[record.sex],
                  record.ward,
                  record.latest_assessment_at
                    ? `last assessment ${whenShort(new Date(record.latest_assessment_at))}`
                    : 'no assessment yet',
                ]
                  .filter(Boolean)
                  .join(' · ')}
              </p>
            </div>
          </div>

          {!readOnly && (
            <div className="flex flex-wrap items-center gap-2">
              <Button icon={<Pencil className="h-4 w-4" />} onClick={() => setEditing(true)}>
                Edit
              </Button>
              {mayDelete && (
                <Button
                  variant="danger"
                  icon={<Trash2 className="h-4 w-4" />}
                  onClick={() => setConfirmDelete(true)}
                >
                  Delete
                </Button>
              )}
              <Button
                variant="primary"
                icon={<Plus className="h-4 w-4" />}
                disabled={record.archived}
                onClick={() => navigate(`/assessments/new?patient=${record.id}`)}
              >
                New assessment
              </Button>
            </div>
          )}
        </div>

        <div className="mt-5 grid grid-cols-2 gap-4 border-t border-hairline pt-4 lg:grid-cols-4">
          <div>
            <p className="text-[11px] text-faint">Reported pain</p>
            <p
              className="mt-1 text-[26px] leading-none font-semibold"
              style={{ color: reported === null ? 'var(--text-faint)' : BAND_VAR[bandOf(reported)] }}
            >
              {reported ?? '–'}
              {reported !== null && (
                <span className="ml-1 text-[13px] font-normal text-mute">/ 10</span>
              )}
            </p>
            <p className="mt-1.5 text-[11px] text-mute">
              {reported === null
                ? 'Nothing reported yet'
                : `Patient-reported · ${BAND_LABEL[bandOf(reported)]}`}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-faint">AI estimate</p>
            <p className="mt-1 text-[26px] leading-none font-semibold text-violet">
              {estimate?.toFixed(1) ?? '–'}
              {estimate !== null && (
                <span className="ml-1 text-[13px] font-normal text-mute">/ 10</span>
              )}
            </p>
            <p className="mt-1.5 text-[11px] text-mute">
              {estimate === null ? 'Not estimated' : 'Latest model output'}
            </p>
          </div>
          <div>
            <p className="text-[11px] text-faint">Trajectory</p>
            <div className="mt-1 flex items-center gap-2">
              <span className="text-[26px] leading-none font-semibold text-ink">
                {history.data?.change_from_previous === null ||
                history.data?.change_from_previous === undefined
                  ? '–'
                  : `${history.data.change_from_previous > 0 ? '+' : ''}${history.data.change_from_previous.toFixed(1)}`}
              </span>
              {record.trend !== 'UNKNOWN' && (
                <Pill
                  tone={
                    record.trend === 'RISING'
                      ? 'danger'
                      : record.trend === 'FALLING'
                        ? 'ok'
                        : 'neutral'
                  }
                  size="xs"
                >
                  {record.trend.toLowerCase()}
                </Pill>
              )}
            </div>
            <p className="mt-1.5 text-[11px] text-mute">
              {record.assessment_count} assessment{record.assessment_count === 1 ? '' : 's'} on
              record
            </p>
          </div>
          <div>
            <p className="text-[11px] text-faint">
              {latestVitals
                ? `Vitals · ${whenShort(new Date(latestVitals.created_at))}`
                : 'Vitals'}
            </p>
            {latestVitals ? (
              <div className="mt-2 flex flex-wrap gap-x-5 gap-y-2">
                <Vital
                  icon={<HeartPulse className="h-3.5 w-3.5" />}
                  label="HR"
                  value={latestVitals.hr?.toFixed(0) ?? '–'}
                  unit="bpm"
                />
                <Vital
                  icon={<Wind className="h-3.5 w-3.5" />}
                  label="RR"
                  value={latestVitals.resp_rate?.toFixed(0) ?? '–'}
                  unit="/min"
                />
                <Vital
                  icon={<Activity className="h-3.5 w-3.5" />}
                  label="BP"
                  value={
                    latestVitals.sbp && latestVitals.dbp
                      ? `${latestVitals.sbp.toFixed(0)}/${latestVitals.dbp.toFixed(0)}`
                      : '–'
                  }
                  unit="mmHg"
                />
                <Vital
                  icon={<Thermometer className="h-3.5 w-3.5" />}
                  label="Temp"
                  value={latestVitals.temperature_c?.toFixed(1) ?? '–'}
                  unit="°C"
                />
              </div>
            ) : (
              <p className="mt-2 text-[11px] text-mute">None recorded.</p>
            )}
          </div>
        </div>
      </Card>

      {record.warnings.length > 0 && (
        <Card className="space-y-2 border-warn/30 bg-warn/8 p-4">
          {record.warnings.map((warning) => (
            <p key={warning.code} className="flex items-start gap-2 text-[12.5px] text-soft">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warn" />
              {warning.message}
            </p>
          ))}
        </Card>
      )}

      <Tabs
        tabs={[
          { value: 'overview', label: 'Overview' },
          { value: 'assessments', label: 'Assessments', count: assessments.data?.length },
          { value: 'history', label: 'Pain history' },
          { value: 'medical', label: 'Medical history' },
          ...(readOnly
            ? []
            : [{ value: 'documents' as const, label: 'Documents', count: documents.data?.length }]),
          { value: 'timeline', label: 'Timeline' },
        ]}
        value={tab}
        onChange={setTab}
      />

      {tab === 'overview' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
          <Card className="p-5 lg:col-span-2">
            <CardHead title="Patient" sub="The record as it is held" />
            <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
              {[
                ['Name', record.identity ? `${record.identity.given_name} ${record.identity.family_name}` : 'Sealed'],
                ['Internal identifier', record.code],
                ['Age', record.age !== null ? `${record.age} ${record.age === 1 ? 'year' : 'years'}` : NONE_RECORDED],
                ['Sex', SEX_LABEL[record.sex]],
                ['Ward', record.ward ?? NONE_RECORDED],
                ['Telephone', record.identity?.phone || NONE_RECORDED],
                [
                  'Emergency contact',
                  [record.identity?.emergency_contact_name, record.identity?.emergency_contact_phone]
                    .filter(Boolean)
                    .join(' · ') || NONE_RECORDED,
                ],
                ['Smoking status', SMOKING_LABEL[record.smoking_status]],
                ['On file since', new Date(record.created_at).toLocaleDateString('en-GB')],
              ].map(([label, value]) => (
                <div
                  key={label}
                  className="flex items-baseline justify-between gap-4 border-b border-hairline pb-2"
                >
                  <dt className="shrink-0 text-[12px] text-mute">{label}</dt>
                  <dd className="min-w-0 truncate text-right text-[13px] font-medium text-ink">
                    {value}
                  </dd>
                </div>
              ))}
            </dl>
          </Card>

          <Card className="p-5">
            <CardHead
              title="Resting baseline"
              sub={
                baseline.data
                  ? `From ${baseline.data.assessments_used} assessment${baseline.data.assessments_used === 1 ? '' : 's'}`
                  : 'What this patient reads as at rest'
              }
            />
            {(baseline.data?.vitals.length ?? 0) === 0 ? (
              <p className="py-8 text-center text-[13px] text-mute">
                No baseline yet. It builds up as vitals are recorded.
              </p>
            ) : (
              <ul className="mt-3 space-y-2">
                {baseline.data?.vitals.map((vital) => (
                  <li
                    key={vital.field}
                    className="flex items-baseline justify-between gap-2 border-b border-hairline pb-1.5 text-[12.5px]"
                  >
                    <span className="text-mute">{vital.label}</span>
                    <span className="flex items-baseline gap-2">
                      <span className="text-ink tabular-nums">{vital.baseline.toFixed(1)}</span>
                      {vital.delta !== null && (
                        <Pill tone={vital.departed ? 'warn' : 'neutral'} size="xs">
                          {vital.delta > 0 ? '+' : ''}
                          {vital.delta.toFixed(1)}
                        </Pill>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}

      {tab === 'history' && (
        <Card className="p-5">
          <CardHead
            title="Pain history"
            sub={`Reported against the model's estimate · ${points.length} assessment${points.length === 1 ? '' : 's'}`}
          />
          {points.length < 2 ? (
            <p className="py-12 text-center text-[13px] text-mute">
              A history needs at least two assessments with a score behind them.
            </p>
          ) : (
            <>
              <div className="mt-3 flex flex-wrap gap-4 text-[11px]">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-0.5 w-5 rounded-full bg-accent" />
                  <span className="font-medium text-ink">Reported</span>
                  <span className="text-faint">self-reported, the reference</span>
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-0.5 w-5 rounded-full border-t-2 border-dashed border-violet" />
                  <span className="font-medium text-ink">AI estimate</span>
                  <span className="text-faint">model output</span>
                </span>
              </div>
              <TrendChart points={points} />
              <div className="mt-4 grid grid-cols-2 gap-4 border-t border-hairline pt-4 sm:grid-cols-4">
                <Stat label="Assessments" value={String(points.length)} />
                <Stat
                  label="Peak reported"
                  value={String(Math.max(...points.map((point) => point.reported)))}
                />
                <Stat
                  label="Mean gap, AI to reported"
                  value={(
                    points.reduce(
                      (sum, point) => sum + Math.abs(point.estimate - point.reported),
                      0,
                    ) / points.length
                  ).toFixed(1)}
                />
                <Stat label="Trend" value={history.data?.trend.toLowerCase() ?? ''} />
              </div>
            </>
          )}
        </Card>
      )}

      {tab === 'assessments' && (
        <Card className="p-4">
          <DataTable
            columns={columns}
            rows={assessments.data ?? []}
            rowKey={(row) => row.id}
            onRowClick={(row) => navigate(`/assessments/${row.id}`)}
            empty={
              <EmptyState
                icon={<FileText className="h-5 w-5" />}
                title="No assessment recorded yet"
                sub={
                  readOnly
                    ? 'Assessments recorded by the clinical team appear here.'
                    : 'Start one from the button above and it will appear here.'
                }
                action={
                  readOnly || record.archived ? undefined : (
                    <Button
                      variant="primary"
                      size="sm"
                      icon={<Plus className="h-4 w-4" />}
                      onClick={() => navigate(`/assessments/new?patient=${record.id}`)}
                    >
                      Create assessment
                    </Button>
                  )
                }
              />
            }
          />
        </Card>
      )}

      {tab === 'medical' && (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Card className="space-y-4 p-5">
            <CardHead title="Chronic conditions" />
            {record.conditions.length === 0 ? (
              <p className="text-[13px] text-mute">{NONE_RECORDED}</p>
            ) : (
              <ul className="space-y-1.5">
                {record.conditions.map((condition) => (
                  <li key={condition.disease_code} className="text-[13px] text-soft">
                    {diseaseLabel.get(condition.disease_code) ?? condition.disease_code}
                    {condition.diagnosed_year && (
                      <span className="text-mute"> · since {condition.diagnosed_year}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          <Card className="space-y-4 p-5">
            <CardHead title="Current medication" />
            {record.medications.length === 0 ? (
              <p className="text-[13px] text-mute">{NONE_RECORDED}</p>
            ) : (
              <ul className="space-y-1.5">
                {record.medications.map((medication) => (
                  <li key={medication.id} className="flex flex-wrap items-baseline gap-2">
                    <span className="text-[13px] font-medium text-ink">{medication.name}</span>
                    {medication.dose && (
                      <span className="text-[12px] text-mute">{medication.dose}</span>
                    )}
                    {medication.frequency && (
                      <span className="text-[12px] text-mute">{medication.frequency}</span>
                    )}
                    {medication.is_analgesic && (
                      <Pill tone="violet" size="xs">
                        analgesic
                      </Pill>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>

          {[
            ['Allergies', record.allergies],
            ['Relevant history', record.medical_history],
            ['Previous surgery', record.previous_surgeries],
            ['Family history', record.family_history],
            ['Lifestyle', record.lifestyle_notes],
          ].map(([label, value]) => (
            <Card key={label} className="space-y-2 p-5">
              <CardHead title={label as string} />
              <p className="text-[13px] leading-relaxed whitespace-pre-line text-soft">
                {value || <span className="text-mute">{NONE_RECORDED}</span>}
              </p>
            </Card>
          ))}
          {!readOnly && (
            <p className="text-[11.5px] text-faint lg:col-span-2">
              Conditions, medication and history are recorded on the assessment form, where the
              clinician has the patient in front of them.
            </p>
          )}
        </div>
      )}

      {tab === 'documents' && !readOnly && (
        <Card className="p-4">
          {(documents.data ?? []).length === 0 ? (
            <EmptyState
              icon={<FileText className="h-5 w-5" />}
              title="No document attached"
              sub="Imaging, laboratory results and reports uploaded for this patient appear here."
              action={
                <Button size="sm" onClick={() => navigate('/documents')}>
                  Open documents
                </Button>
              }
            />
          ) : (
            <ul className="divide-y divide-hairline">
              {documents.data?.map((document) => (
                <li key={document.id} className="flex items-center gap-3 py-3">
                  <Tile tone="accent" className="h-9 w-9 rounded-lg">
                    <FileText className="h-4 w-4" />
                  </Tile>
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-[13px] font-medium text-ink">
                      {document.original_filename}
                    </p>
                    <p className="text-[11px] text-mute">
                      {document.kind.replace(/_/g, ' ').toLowerCase()} ·{' '}
                      {(document.size_bytes / 1024).toFixed(0)} kB ·{' '}
                      {whenShort(new Date(document.uploaded_at))}
                    </p>
                  </div>
                  <Pill tone="ok" size="xs" title={`sha256 ${document.sha256}`}>
                    digest held
                  </Pill>
                </li>
              ))}
            </ul>
          )}
        </Card>
      )}

      {tab === 'timeline' && (
        <Card className="p-5">
          <CardHead title="Timeline" sub="Everything recorded against this patient, newest first" />
          {timeline.loading ? (
            <p className="py-10 text-center text-[13px] text-mute">Loading…</p>
          ) : (timeline.data?.events.length ?? 0) === 0 ? (
            <p className="py-10 text-center text-[13px] text-mute">Nothing recorded yet.</p>
          ) : (
            <ol className="mt-4 space-y-3.5">
              {[...(timeline.data?.events ?? [])].reverse().map((event, index, all) => (
                <li key={`${event.at}:${event.kind}:${index}`} className="flex gap-3">
                  <div className="flex flex-col items-center">
                    <span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-accent ring-4 ring-[var(--surface)]" />
                    {index < all.length - 1 && <span className="mt-1 w-px flex-1 bg-hairline" />}
                  </div>
                  <div className="min-w-0 flex-1 pb-0.5">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <p className="text-[12.5px] font-medium text-ink">{event.title}</p>
                      <Pill size="xs">{event.kind.replace(/_/g, ' ').toLowerCase()}</Pill>
                      {event.value !== null && event.value !== undefined && (
                        <Tile tone={bandTone(event.value)} className="h-5 w-6 rounded text-[10px]">
                          {event.value}
                        </Tile>
                      )}
                    </div>
                    {event.detail && (
                      <p className="mt-0.5 text-[11.5px] leading-snug text-mute">{event.detail}</p>
                    )}
                    <p className="mt-0.5 text-[11px] text-faint">
                      {whenShort(new Date(event.at))}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}

      {editing && (
        <PatientDialog
          existing={record}
          onClose={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            patient.reload();
          }}
        />
      )}

      {confirmDelete && (
        <div
          className="fixed inset-0 z-[90] flex items-center justify-center bg-[#0b1b33]/40 px-4 backdrop-blur-[2px]"
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) setConfirmDelete(false);
          }}
        >
          <div
            role="alertdialog"
            aria-modal
            className="w-full max-w-md rounded-2xl border border-hairline bg-surface p-5 shadow-pop"
          >
            <h2 className="text-[16px] font-semibold text-ink">Delete {record.display_name}?</h2>
            <p className="mt-2 text-[12.5px] leading-relaxed text-soft">
              The record, its {record.assessment_count} assessment
              {record.assessment_count === 1 ? '' : 's'}, estimates, documents and recordings are
              deleted. The audit trail keeps the fact that the record existed. This cannot be
              undone.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                Keep it
              </Button>
              <Button
                variant="danger"
                icon={<Trash2 className="h-4 w-4" />}
                disabled={busy}
                onClick={() => void remove()}
              >
                {busy ? 'Deleting…' : 'Delete the record'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};

const Stat: React.FC<{ label: string; value: string }> = ({ label, value }) => (
  <div>
    <p className="text-[11px] text-faint">{label}</p>
    <p className="mt-1 text-[17px] font-semibold text-ink tabular-nums">{value}</p>
  </div>
);
