import { FileText, Paperclip } from 'lucide-react'
import { useRef, useState } from 'react'

import { api } from '@/api/client'
import { useSetFindings, useUploadDocument } from '@/api/queries'
import type { DocumentKind, MedicalDocument } from '@/api/types'
import { Button } from '@/components/ui/button'
import { Field, Select, Textarea } from '@/components/ui/field'
import { EmptyState, Notice } from '@/components/ui/feedback'
import { formatDateTime } from '@/utils/format'

const KINDS: { value: DocumentKind; label: string }[] = [
  { value: 'XRAY', label: 'Radiograph' },
  { value: 'CT', label: 'CT' },
  { value: 'MRI', label: 'MRI' },
  { value: 'ULTRASOUND', label: 'Ultrasound' },
  { value: 'ECG', label: 'ECG' },
  { value: 'LABORATORY', label: 'Laboratory result' },
  { value: 'REPORT', label: 'Medical report' },
  { value: 'PRESCRIPTION', label: 'Prescription' },
  { value: 'OTHER', label: 'Other' },
]

const readableSize = (bytes: number) =>
  bytes < 1024 * 1024 ? `${Math.round(bytes / 1024)} kB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`

export function DocumentPanel({
  patientId,
  assessmentId,
  documents,
}: {
  patientId: string
  assessmentId?: string
  documents: MedicalDocument[]
}) {
  const upload = useUploadDocument()
  const [kind, setKind] = useState<DocumentKind>('XRAY')
  const fileInput = useRef<HTMLInputElement>(null)

  const onFile = async (file: File) => {
    const form = new FormData()
    form.append('patient_id', patientId)
    form.append('kind', kind)
    if (assessmentId) form.append('assessment_id', assessmentId)
    form.append('file', file)
    await upload.mutateAsync(form)
    if (fileInput.current) fileInput.current.value = ''
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Document type" className="w-44">
          {(props) => (
            <Select
              {...props}
              value={kind}
              onChange={(event) => setKind(event.target.value as DocumentKind)}
            >
              {KINDS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          )}
        </Field>
        <div>
          <input
            ref={fileInput}
            type="file"
            accept="application/pdf,image/jpeg,image/png"
            className="hidden"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) void onFile(file)
            }}
          />
          <Button
            type="button"
            variant="secondary"
            loading={upload.isPending}
            onClick={() => fileInput.current?.click()}
          >
            <Paperclip aria-hidden className="size-4" />
            Attach a file
          </Button>
        </div>
        <p className="text-xs text-muted">PDF, JPEG or PNG.</p>
      </div>

      {upload.isError && (
        <Notice tone="alert" title="The file was not accepted">
          {upload.error instanceof Error ? upload.error.message : 'Unexpected error'}
        </Notice>
      )}

      {documents.length === 0 ? (
        <EmptyState
          title="No documents attached"
          description="Reports and images are stored encrypted. The platform does not read images."
        />
      ) : (
        <ul className="divide-y divide-line">
          {documents.map((document) => (
            <DocumentRow key={document.id} document={document} />
          ))}
        </ul>
      )}
    </div>
  )
}

function DocumentRow({ document: record }: { document: MedicalDocument }) {
  const [findings, setFindings] = useState(record.findings ?? '')
  const [open, setOpen] = useState(false)
  const save = useSetFindings(record.id)

  const view = async () => {
    const blob = await api.get<Blob>(`/api/documents/${record.id}/content`)
    window.open(URL.createObjectURL(blob), '_blank', 'noopener')
  }

  return (
    <li className="py-3">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="flex items-center gap-1.5 text-sm font-medium text-ink">
            <FileText aria-hidden className="size-4 shrink-0 text-muted" />
            <span className="truncate">{record.original_filename}</span>
          </p>
          <p className="mt-0.5 text-xs text-muted">
            {record.kind.toLowerCase()} · {readableSize(record.size_bytes)} ·{' '}
            {formatDateTime(record.uploaded_at)}
          </p>
          <p className="mt-0.5 font-mono text-[0.6875rem] break-all text-faint">
            sha256 {record.sha256.slice(0, 32)}…
          </p>
        </div>
        <div className="flex gap-2">
          <Button size="sm" variant="secondary" onClick={() => void view()}>
            Open
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setOpen((value) => !value)}>
            {open ? 'Hide' : 'Findings'}
          </Button>
        </div>
      </div>

      {record.extracted_text && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-muted hover:text-ink">
            Text found in the document
          </summary>
          <pre className="mt-1 max-h-40 overflow-auto rounded border border-line bg-canvas p-2 text-xs whitespace-pre-wrap text-body">
            {record.extracted_text}
          </pre>
        </details>
      )}

      {open && (
        <div className="mt-3 space-y-2">
          <Field
            label="Clinician's findings"
            hint="The platform does not interpret images. This reading is yours."
          >
            {(props) => (
              <Textarea
                {...props}
                rows={3}
                value={findings}
                onChange={(event) => setFindings(event.target.value)}
              />
            )}
          </Field>
          <Button
            size="sm"
            loading={save.isPending}
            onClick={async () => {
              await save.mutateAsync(findings)
              setOpen(false)
            }}
          >
            Save findings
          </Button>
        </div>
      )}
    </li>
  )
}
