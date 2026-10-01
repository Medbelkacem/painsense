import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  FileDown, FileText, Fingerprint, Image as ImageIcon, Search, Table2, Upload, UserRound,
} from 'lucide-react';

import { ApiError, download, request } from '../api/client';
import { useQuery } from '../api/hooks';
import type { ClinicalDocument, DocumentKind, Page, PatientSummary } from '../api/types';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile } from '../ui/Pill';
import { SearchField } from '../ui/Field';
import { Select } from '../ui/Dropdown';
import { whenShort } from '../lib/format';
import { cx } from '../lib/cx';

const KIND_LABEL: Record<DocumentKind, string> = {
  XRAY: 'X-ray',
  WOUND_PHOTO: 'Wound photograph',
  CT: 'CT',
  MRI: 'MRI',
  ULTRASOUND: 'Ultrasound',
  ECG: 'ECG',
  LABORATORY: 'Laboratory',
  REPORT: 'Report',
  PRESCRIPTION: 'Prescription',
  OTHER: 'Other',
};

const KIND_OPTIONS = (Object.keys(KIND_LABEL) as DocumentKind[]).map((value) => ({
  value,
  label: KIND_LABEL[value],
}));

const kindIcon = (kind: DocumentKind) => {
  if (kind === 'LABORATORY') return <Table2 className="h-4 w-4" />;
  if (kind === 'REPORT' || kind === 'PRESCRIPTION' || kind === 'OTHER') {
    return <FileText className="h-4 w-4" />;
  }
  return <ImageIcon className="h-4 w-4" />;
};

const kilobytes = (bytes: number) => `${Math.max(1, Math.round(bytes / 1024))} kB`;

export const Documents: React.FC = () => {
  const [query, setQuery] = useState('');
  const [needle, setNeedle] = useState('');
  const [patientId, setPatientId] = useState<string | null>(null);
  const [kindFilter, setKindFilter] = useState<DocumentKind | null>(null);
  const [uploadKind, setUploadKind] = useState<DocumentKind | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const picker = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const timer = window.setTimeout(() => setNeedle(query.trim()), 220);
    return () => window.clearTimeout(timer);
  }, [query]);

  const patientPath = useMemo(() => {
    const search = new URLSearchParams({ limit: '25' });
    if (needle) search.set('search', needle);
    return `/api/patients?${search}`;
  }, [needle]);

  const patients = useQuery<Page<PatientSummary>>(patientPath);
  const documents = useQuery<ClinicalDocument[]>(
    patientId ? `/api/documents?patient_id=${patientId}` : null,
  );
  const reloadDocuments = documents.reload;

  const patient = useMemo(
    () => patients.data?.items.find((row) => row.id === patientId) ?? null,
    [patients.data, patientId],
  );

  const rows = useMemo(
    () => (documents.data ?? []).filter((row) => !kindFilter || row.kind === kindFilter),
    [documents.data, kindFilter],
  );

  const selected = rows.find((row) => row.id === selectedId) ?? rows[0] ?? null;

  const upload = useCallback(
    async (file: File) => {
      if (!patientId) return;
      setBusy(true);
      setFailure(null);
      const form = new FormData();
      form.set('patient_id', patientId);
      form.set('file', file);
      if (uploadKind) form.set('kind', uploadKind);
      try {
        const stored = await request<ClinicalDocument>('/api/documents', {
          method: 'POST',
          body: form,
        });
        setSelectedId(stored.id);
        reloadDocuments();
      } catch (cause) {
        setFailure(cause instanceof ApiError ? cause.message : 'The file could not be uploaded.');
      } finally {
        setBusy(false);
      }
    },
    [patientId, uploadKind, reloadDocuments],
  );

  const pickPatient = (value: string | null) => {
    setPatientId(value);
    setSelectedId(null);
    setFailure(null);
  };

  return (
    <>
      <PageHead
        title="Documents"
        sub="Imaging, results and reports attached to a patient. Each file is hashed as it arrives."
        action={
          <Button
            variant="primary"
            icon={<Upload className="h-4 w-4" />}
            disabled={!patientId || busy}
            onClick={() => picker.current?.click()}
          >
            {busy ? 'Uploading…' : 'Upload document'}
          </Button>
        }
      />

      <input
        ref={picker}
        type="file"
        accept="application/pdf,image/jpeg,image/png"
        className="hidden"
        onChange={(event) => {
          const file = event.target.files?.[0];
          event.target.value = '';
          if (file) void upload(file);
        }}
      />

      {(failure || documents.error || patients.error) && (
        <Card className="border-danger/25 bg-danger/8 p-4 text-[12px] text-danger">
          {failure ?? documents.error ?? patients.error}
        </Card>
      )}

      <Card className="p-4">
        <div className="flex flex-wrap items-center gap-2">
          <SearchField
            icon={<Search className="h-4 w-4" />}
            value={query}
            placeholder="Find a patient by name, code or ward…"
            onChange={(event) => setQuery(event.target.value)}
            className="w-full min-w-[12rem] sm:w-72"
          />
          <Select
            label="Patient"
            searchable
            options={(patients.data?.items ?? []).map((row) => ({
              value: row.id,
              label: row.display_name,
              hint: row.code,
            }))}
            value={patientId}
            onChange={pickPatient}
          />
          <Select
            label="Category"
            options={KIND_OPTIONS}
            value={kindFilter}
            onChange={setKindFilter}
            size="sm"
          />
          <span className="ml-auto text-[12px] text-faint">
            {patients.loading
              ? 'Loading…'
              : patientId
                ? `${rows.length} file${rows.length === 1 ? '' : 's'}`
                : `${patients.data?.total ?? 0} patients`}
          </span>
        </div>
      </Card>

      {!patientId ? (
        <Card>
          <EmptyState
            icon={<UserRound className="h-5 w-5" />}
            title="Pick a patient to see their documents"
            sub="Search above, then choose the patient. Files are always attached to one record and never float on their own."
          />
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_380px]">
          <div className="space-y-4">
            <Card
              className={cx(
                'border-dashed p-6 text-center transition-colors',
                dragging ? 'border-accent bg-accent-wash' : 'border-hairline-strong',
              )}
              onDragOver={(event) => {
                event.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(event) => {
                event.preventDefault();
                setDragging(false);
                const file = event.dataTransfer.files?.[0];
                if (file) void upload(file);
              }}
            >
              <Tile tone="accent" className="mx-auto h-10 w-10 rounded-xl">
                <Upload className="h-4 w-4" />
              </Tile>
              <p className="mt-3 text-[13px] font-medium text-ink">
                Drop a file for {patient?.display_name ?? 'this patient'}, or browse
              </p>
              <p className="mt-1 text-[12px] text-mute">
                PDF, JPEG or PNG, up to 15 MB. The SHA-256 digest is taken on upload and kept
                with the file.
              </p>
              <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
                <Select
                  label="Category"
                  options={KIND_OPTIONS}
                  value={uploadKind}
                  onChange={setUploadKind}
                  size="sm"
                />
                <Button size="sm" disabled={busy} onClick={() => picker.current?.click()}>
                  Browse files
                </Button>
              </div>
            </Card>

            <Card className="p-4">
              {documents.loading ? (
                <p className="py-10 text-center text-[13px] text-mute">Loading…</p>
              ) : rows.length === 0 ? (
                <EmptyState
                  icon={<FileText className="h-5 w-5" />}
                  title={
                    kindFilter && (documents.data?.length ?? 0) > 0
                      ? 'No file in that category'
                      : 'No document attached yet'
                  }
                  sub={
                    kindFilter && (documents.data?.length ?? 0) > 0
                      ? 'Clear the category filter to see the rest.'
                      : 'Upload the first file for this patient and it appears here.'
                  }
                  action={
                    kindFilter && (documents.data?.length ?? 0) > 0 ? (
                      <Button size="sm" onClick={() => setKindFilter(null)}>
                        Clear
                      </Button>
                    ) : (
                      <Button
                        variant="primary"
                        size="sm"
                        icon={<Upload className="h-4 w-4" />}
                        disabled={busy}
                        onClick={() => picker.current?.click()}
                      >
                        Upload document
                      </Button>
                    )
                  }
                />
              ) : (
                <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {rows.map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(row.id)}
                        className={cx(
                          'flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors',
                          row.id === selected?.id
                            ? 'border-accent-edge bg-accent-wash'
                            : 'border-hairline bg-surface hover:border-hairline-strong',
                        )}
                      >
                        <Tile tone="accent" className="h-9 w-9 rounded-lg">
                          {kindIcon(row.kind)}
                        </Tile>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-[13px] font-medium text-ink">
                            {row.original_filename}
                          </p>
                          <p className="truncate text-[11px] text-mute">
                            {KIND_LABEL[row.kind]} · {kilobytes(row.size_bytes)} ·{' '}
                            {whenShort(new Date(row.uploaded_at))}
                          </p>
                        </div>
                        {row.findings && (
                          <Pill tone="teal" size="xs">
                            findings
                          </Pill>
                        )}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>

          <Card className="p-5">
            {selected ? (
              <Detail
                key={selected.id}
                document={selected}
                onSaved={documents.reload}
                onFailure={setFailure}
              />
            ) : (
              <>
                <CardHead title="Document" sub="Select a file" />
                <EmptyState icon={<FileText className="h-5 w-5" />} title="Nothing selected" />
              </>
            )}
          </Card>
        </div>
      )}
    </>
  );
};

const Detail: React.FC<{
  document: ClinicalDocument;
  onSaved: () => void;
  onFailure: (message: string | null) => void;
}> = ({ document, onSaved, onFailure }) => {
  const [findings, setFindings] = useState(document.findings ?? '');
  const [saving, setSaving] = useState(false);
  const dirty = findings !== (document.findings ?? '');

  const save = async () => {
    setSaving(true);
    onFailure(null);
    try {
      await request<ClinicalDocument>(`/api/documents/${document.id}`, {
        method: 'PATCH',
        body: { findings },
      });
      onSaved();
    } catch (cause) {
      onFailure(cause instanceof ApiError ? cause.message : 'The findings could not be saved.');
    } finally {
      setSaving(false);
    }
  };

  const open = async () => {
    onFailure(null);
    try {
      await download(`/api/documents/${document.id}/content`, document.original_filename, {
        method: 'GET',
      });
    } catch (cause) {
      onFailure(cause instanceof ApiError ? cause.message : 'The file could not be fetched.');
    }
  };

  return (
    <>
      <CardHead
        title={<span className="break-all">{document.original_filename}</span>}
        sub={`${KIND_LABEL[document.kind]} · ${kilobytes(document.size_bytes)}`}
        action={
          <Button size="sm" icon={<FileDown className="h-4 w-4" />} onClick={() => void open()}>
            Open
          </Button>
        }
      />

      <dl className="mt-4 space-y-2">
        {[
          ['Category', KIND_LABEL[document.kind]],
          ['Media type', document.media_type],
          ['Size', kilobytes(document.size_bytes)],
          ['Uploaded', whenShort(new Date(document.uploaded_at))],
          ['Linked assessment', document.assessment_id ? document.assessment_id.slice(0, 8) : '—'],
        ].map(([label, value]) => (
          <div
            key={label}
            className="flex items-baseline justify-between gap-4 border-b border-hairline pb-1.5"
          >
            <dt className="shrink-0 text-[12px] text-mute">{label}</dt>
            <dd className="min-w-0 truncate text-right text-[12.5px] font-medium text-ink">
              {value}
            </dd>
          </div>
        ))}
      </dl>

      <div className="mt-4 rounded-xl border border-hairline bg-sunken p-3">
        <div className="flex items-center gap-2">
          <Fingerprint className="h-4 w-4 shrink-0 text-mute" />
          <span className="text-[12.5px] font-medium text-ink">Digest held on upload</span>
        </div>
        <p className="mt-1.5 font-mono text-[11px] break-all text-mute">sha256 {document.sha256}</p>
      </div>

      <label className="mt-4 block space-y-1.5">
        <span className="block text-xs font-medium text-soft">Findings</span>
        <textarea
          value={findings}
          rows={5}
          placeholder="What the clinician read in this document…"
          onChange={(event) => setFindings(event.target.value)}
          className="w-full rounded-[10px] border border-hairline bg-surface p-3 text-[13px] text-ink outline-none transition-colors focus:border-accent placeholder:text-faint"
        />
      </label>
      <div className="mt-2 flex items-center justify-between gap-3">
        <span className="text-[11px] text-faint">Only the uploader can change the findings.</span>
        <Button
          variant="primary"
          size="sm"
          disabled={!dirty || saving}
          onClick={() => void save()}
        >
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </div>

      {document.extracted_text && (
        <details className="mt-4 border-t border-hairline pt-3">
          <summary className="cursor-pointer text-[12px] font-medium text-soft">
            Text read from the file
          </summary>
          <p className="mt-2 max-h-56 overflow-y-auto text-[12px] leading-relaxed whitespace-pre-line text-mute">
            {document.extracted_text}
          </p>
        </details>
      )}
    </>
  );
};
