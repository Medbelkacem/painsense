import React, { useMemo, useRef, useState } from 'react';
import {
  FileText, Fingerprint, Image as ImageIcon, Search, ShieldCheck, Table2, Upload,
} from 'lucide-react';
import { Card, CardHead, EmptyState, PageHead } from '../ui/Card';
import { Button } from '../ui/Button';
import { Pill, Tile } from '../ui/Pill';
import { SearchField } from '../ui/Field';
import { Select } from '../ui/Dropdown';
import { Segmented } from '../ui/Segmented';
import { Waveform } from '../ui/charts';
import { documents, patients } from '../demo/cohort';
import { cx } from '../lib/cx';

type Lane = 'all' | 'Imaging' | 'Laboratory' | 'Medical record' | 'Cardiology';

const kindIcon: Record<string, React.ReactNode> = {
  Imaging: <ImageIcon className="h-4 w-4" />,
  Laboratory: <Table2 className="h-4 w-4" />,
  Cardiology: <FileText className="h-4 w-4" />,
  'Medical record': <FileText className="h-4 w-4" />,
};

export const Documents: React.FC = () => {
  const [lane, setLane] = useState<Lane>('all');
  const [query, setQuery] = useState('');
  const [patient, setPatient] = useState<string | null>(null);
  const [selected, setSelected] = useState<string>(documents[0].name);
  const [dragging, setDragging] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const rows = useMemo(
    () =>
      documents.filter((document) => {
        if (lane !== 'all' && document.kind !== lane) return false;
        if (patient && document.patient !== patient) return false;
        if (query && !document.name.toLowerCase().includes(query.trim().toLowerCase())) return false;
        return true;
      }),
    [lane, patient, query],
  );

  const open = documents.find((document) => document.name === selected) ?? documents[0];

  return (
    <>
      <PageHead
        title="Documents"
        sub="Files attached to patients and assessments, with integrity recorded on upload."
        action={
          <Button
            variant="primary"
            icon={<Upload className="h-4 w-4" />}
            onClick={() => picker.current?.click()}
          >
            Upload document
          </Button>
        }
      />

      {/* The drop zone is deliberately the first thing on the page: attaching a file is
          the only reason most people open this screen. */}
      <Card
        className={cx(
          'border-dashed p-8 text-center transition-colors',
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
        }}
      >
        <input ref={picker} type="file" multiple className="hidden" />
        <Tile tone="accent" className="mx-auto h-11 w-11 rounded-xl">
          <Upload className="h-5 w-5" />
        </Tile>
        <p className="mt-3 text-[14px] font-medium text-ink">Drag and drop files, or browse</p>
        <p className="mt-1 text-[12px] text-mute">
          PDF, DICOM, JPG, PNG and CSV up to 50 MB each. Every upload is hashed and the hash is
          written to the integrity ledger.
        </p>
        <Button className="mt-4" onClick={() => picker.current?.click()}>
          Browse files
        </Button>
      </Card>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_380px]">
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-2">
            <Segmented
              options={[
                { value: 'all', label: 'All' },
                { value: 'Imaging', label: 'Imaging' },
                { value: 'Laboratory', label: 'Laboratory' },
                { value: 'Cardiology', label: 'Cardiology' },
                { value: 'Medical record', label: 'Records' },
              ]}
              value={lane}
              onChange={setLane}
            />
            <SearchField
              icon={<Search className="h-4 w-4" />}
              value={query}
              placeholder="File name…"
              onChange={(event) => setQuery(event.target.value)}
              className="w-full min-w-[10rem] sm:w-52"
            />
            <Select
              label="Patient"
              searchable
              options={[...new Set(documents.map((document) => document.patient))].map((value) => ({
                value,
                label: value,
              }))}
              value={patient}
              onChange={setPatient}
            />
            <span className="ml-auto text-[12px] text-faint">{rows.length} files</span>
          </div>

          {rows.length === 0 ? (
            <EmptyState
              icon={<FileText className="h-5 w-5" />}
              title="No file matches"
              sub="Try another category, or clear the patient filter."
            />
          ) : (
            <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {rows.map((document) => (
                <li key={document.name}>
                  <button
                    type="button"
                    onClick={() => setSelected(document.name)}
                    className={cx(
                      'flex w-full items-center gap-3 rounded-xl border p-3 text-left transition-colors',
                      document.name === selected
                        ? 'border-accent-edge bg-accent-wash'
                        : 'border-hairline bg-surface hover:border-hairline-strong',
                    )}
                  >
                    <Tile tone={document.verified ? 'accent' : 'warn'} className="h-9 w-9 rounded-lg">
                      {kindIcon[document.kind]}
                    </Tile>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-[13px] font-medium text-ink">{document.name}</p>
                      <p className="truncate text-[11px] text-mute">
                        {document.patient} · {document.size} · {document.at}
                      </p>
                    </div>
                    <Pill tone={document.verified ? 'ok' : 'warn'} size="xs">
                      {document.verified ? 'Verified' : 'Pending'}
                    </Pill>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card className="flex flex-col p-5">
          <CardHead title={open.name} sub={`${open.kind} · ${open.size}`} />

          <div className="mt-4 overflow-hidden rounded-xl border border-hairline bg-sunken">
            {open.kind === 'Cardiology' ? (
              <div className="hairline-grid p-4">
                <Waveform className="h-24" seed={11} />
                <Waveform className="h-24" seed={23} />
              </div>
            ) : (
              <div className="grid h-48 place-items-center text-[12px] text-faint">
                Preview rendered on open
              </div>
            )}
          </div>

          <dl className="mt-4 space-y-2">
            {[
              ['Patient', open.patient],
              ['Uploaded', open.at],
              ['Category', open.kind],
              ['Size', open.size],
              ['Linked assessment', 'A-2026-4480'],
            ].map(([label, value]) => (
              <div key={label} className="flex items-baseline justify-between gap-4 border-b border-hairline pb-1.5">
                <dt className="text-[12px] text-mute">{label}</dt>
                <dd className="text-[12.5px] font-medium text-ink">{value}</dd>
              </div>
            ))}
          </dl>

          <div className="mt-4 rounded-xl border border-ok/25 bg-ok/8 p-3">
            <div className="flex items-center gap-2">
              <ShieldCheck className="h-4 w-4 shrink-0 text-ok" />
              <span className="text-[12.5px] font-medium text-ink">Hash recorded in the ledger</span>
            </div>
            <p className="mt-1.5 flex items-center gap-1.5 font-mono text-[11px] break-all text-mute">
              <Fingerprint className="h-3 w-3 shrink-0" />
              sha256:4f7a91c0bb3e0d52a71f38c9e2046b8d…e19c
            </p>
          </div>

          <p className="mt-4 text-[11px] leading-relaxed text-faint">
            Documents belonging to {patients.length} synthetic patients. Nothing here is a real
            clinical record.
          </p>
        </Card>
      </div>
    </>
  );
};
