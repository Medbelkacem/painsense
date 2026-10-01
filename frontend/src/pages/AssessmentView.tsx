import React, { useCallback, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ArrowLeft, Check, ChevronRight, FileDown, FileText, Pencil, Trash2,
} from 'lucide-react';

import { ApiError, download, request } from '../api/client';
import { useQuery } from '../api/hooks';
import { useSession } from '../auth/session';
import type { AssessmentDetail, AssessmentStatus, PatientDetail } from '../api/types';
import { Card, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, type Tone } from '../ui/Pill';
import { whenShort } from '../lib/format';
import { AssessmentSummary, useCatalogLabels, WarningList } from '../components/AssessmentSummary';
import { EstimatePanel } from '../components/EstimatePanel';

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

export const AssessmentView: React.FC = () => {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { user } = useSession();
  const labels = useCatalogLabels();
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);

  const assessment = useQuery<AssessmentDetail>(id ? `/api/assessments/${id}` : null);
  const patient = useQuery<PatientDetail>(
    assessment.data ? `/api/patients/${assessment.data.patient_id}` : null,
  );
  const admin = user?.role === 'SUPER_ADMIN' || user?.role === 'CLINIC_ADMIN';
  const role = user?.role;
  const patientAccount = role === 'PATIENT';
  const owner = Boolean(assessment.data && user && assessment.data.doctor_id === user.id);
  const mayEdit = !patientAccount && assessment.data?.status !== 'VALIDATED' && (owner || admin);
  const mayValidate = role === 'DOCTOR' && owner && assessment.data?.status === 'ESTIMATED';
  const mayDelete = (owner && role === 'DOCTOR') || admin;

  const act = useCallback(
    async (work: () => Promise<void>, fallback: string) => {
      setBusy(true);
      setFailure(null);
      try {
        await work();
      } catch (cause) {
        setFailure(cause instanceof ApiError ? cause.message : fallback);
      } finally {
        setBusy(false);
      }
    },
    [],
  );

  const exportPdf = () =>
    act(() => download(`/api/reports/${id}/generate`, 'pain-assessment.pdf'), 'The PDF could not be generated.');

  const validate = () =>
    act(async () => {
      await request(`/api/assessments/${id}/validate`, { method: 'POST', body: { agreement: 'AGREE' } });
      assessment.reload();
    }, 'The assessment was not validated.');

  const compute = () =>
    act(async () => {
      await request(`/api/assessments/${id}/predict`, { method: 'POST' });
      assessment.reload();
    }, 'The estimate could not be made.');

  const remove = () =>
    act(async () => {
      await request<void>(`/api/assessments/${id}`, { method: 'DELETE' });
      navigate(patientAccount ? '/my-record' : '/assessments', { replace: true });
    }, 'The assessment could not be deleted.');

  if (assessment.error) {
    return (
      <Card>
        <EmptyState
          icon={<FileText className="h-5 w-5" />}
          title="That assessment could not be opened"
          sub={assessment.error}
          action={
            <Button size="sm" icon={<ArrowLeft className="h-4 w-4" />} onClick={() => navigate(-1)}>
              Back
            </Button>
          }
        />
      </Card>
    );
  }
  if (!assessment.data || !patient.data) {
    return <p className="py-16 text-center text-[13px] text-mute">Loading the assessment…</p>;
  }

  const record = assessment.data;
  const validator = record.validated_by_name ? { display_name: record.validated_by_name } : null;

  return (
    <>
      <nav className="flex flex-wrap items-center gap-1.5 text-[13px] text-mute">
        {patientAccount ? (
          <Link to="/my-record" className="transition-colors hover:text-ink">
            My record
          </Link>
        ) : (
          <>
            <Link to="/patients" className="transition-colors hover:text-ink">
              Patients
            </Link>
            <ChevronRight className="h-3.5 w-3.5 text-faint" />
            <Link to={`/patients/${record.patient_id}`} className="transition-colors hover:text-ink">
              {record.patient_code}
            </Link>
          </>
        )}
        <ChevronRight className="h-3.5 w-3.5 text-faint" />
        <span className="font-medium text-ink">Assessment of {whenShort(new Date(record.created_at))}</span>
      </nav>

      <PageHead
        title={
          <span className="inline-flex flex-wrap items-center gap-3">
            {patient.data.display_name}
            <Pill tone={STATUS_TONE[record.status]} dot>
              {STATUS_WORD[record.status]}
            </Pill>
          </span>
        }
        sub={`${record.patient_code} · recorded ${new Date(record.created_at).toLocaleString('en-GB')}`}
        action={
          <>
            <Button icon={<FileDown className="h-4 w-4" />} disabled={busy} onClick={() => void exportPdf()}>
              Export PDF
            </Button>
            {mayEdit && (
              <Button icon={<Pencil className="h-4 w-4" />} onClick={() => navigate(`/assessments/${record.id}/edit`)}>
                Edit
              </Button>
            )}
            {mayValidate && (
              <Button variant="primary" icon={<Check className="h-4 w-4" />} disabled={busy} onClick={() => void validate()}>
                Validate
              </Button>
            )}
            {mayDelete && (
              <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} onClick={() => setConfirmDelete(true)}>
                Delete
              </Button>
            )}
          </>
        }
      />

      {failure && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">{failure}</Card>
      )}

      <WarningList warnings={record.warnings} />

      {record.status === 'DRAFT' && mayEdit && (
        <Card className="flex flex-wrap items-center justify-between gap-3 p-4">
          <p className="text-[12.5px] text-soft">
            This assessment has no estimate yet. Computing the score asks the model with what has
            been recorded so far.
          </p>
          <Button variant="primary" size="sm" disabled={busy} onClick={() => void compute()}>
            Compute pain score
          </Button>
        </Card>
      )}

      <AssessmentSummary
        assessment={record}
        patient={patient.data}
        clinician={record.recorded_by}
        validator={validator}
        labels={labels}
      />

      <EstimatePanel
        prediction={record.prediction}
        selfReport={record.self_report}
        onRun={mayEdit ? () => void compute() : undefined}
        busy={busy}
      />

      {confirmDelete && (
        <div
          className="fixed inset-0 z-[90] flex items-center justify-center bg-[#0b1b33]/40 px-4 backdrop-blur-[2px]"
          onPointerDown={(event) => {
            if (event.target === event.currentTarget) setConfirmDelete(false);
          }}
        >
          <div role="alertdialog" aria-modal className="w-full max-w-md rounded-2xl border border-hairline bg-surface p-5 shadow-pop">
            <h2 className="text-[16px] font-semibold text-ink">Delete this assessment?</h2>
            <p className="mt-2 text-[12.5px] leading-relaxed text-soft">
              The recorded findings, the estimate and the self-reported score are deleted. The
              audit trail keeps the fact that it existed. This cannot be undone.
            </p>
            <div className="mt-5 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmDelete(false)}>
                Keep it
              </Button>
              <Button variant="danger" icon={<Trash2 className="h-4 w-4" />} disabled={busy} onClick={() => void remove()}>
                {busy ? 'Deleting…' : 'Delete'}
              </Button>
            </div>
          </div>
        </div>
      )}
    </>
  );
};
