import { PageHeader } from '@/components/PageHeader'
import { Card, CardBody, CardHeader } from '@/components/ui/card'

const LAYERS = [
  {
    title: 'React application',
    detail:
      'Installable as a progressive web app. The shell is cached for offline start-up; every call for clinical data goes to the network and nothing from it is written to a cache.',
  },
  {
    title: 'FastAPI',
    detail:
      'Authentication, authorisation and validation. A measurement outside what a person can physiologically have is refused with a message; one that is possible but abnormal is stored exactly as entered.',
  },
  {
    title: 'Clinical data layer',
    detail:
      'A normalised schema keyed by UUID. Direct identifiers are sealed, and the patient’s self-reported score lives in its own table, apart from anything the model reads.',
  },
  {
    title: 'Estimation pipeline',
    detail:
      'Quality gate, feature assembly, gradient boosting for the point estimate, two quantile models for the interval, SHAP for the contributions, then the transparent rule layer for alerts and priority.',
  },
  {
    title: 'PostgreSQL',
    detail: 'Clinical records, the audit chain and the ledger. Migrations are managed by Alembic.',
  },
  {
    title: 'Encrypted storage',
    detail:
      'Documents are sealed with AES-256-GCM under a per-file key before they reach the disk. The store on its own yields nothing.',
  },
]

const SECURITY = [
  ['Argon2id', 'Password hashing'],
  ['AES-256-GCM', 'Records and documents at rest'],
  ['X25519 with ML-KEM-768', 'Key establishment'],
  ['Ed25519 with ML-DSA-65', 'Ledger block signatures'],
  ['SHA-256', 'Record and chain hashing'],
  ['Append-only ledger', 'Tamper evidence'],
]

export function ArchitecturePage() {
  return (
    <>
      <PageHeader
        title="Architecture"
        description="How a recorded finding becomes an estimate, and what protects it on the way."
      />

      <Card>
        <CardHeader title="Request path" />
        <CardBody>
          <ol className="space-y-0">
            {LAYERS.map((layer, index) => (
              <li key={layer.title} className="relative flex gap-4 pb-6 last:pb-0">
                <div className="flex flex-col items-center">
                  <span className="flex size-7 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent-strong tabular">
                    {index + 1}
                  </span>
                  {index < LAYERS.length - 1 && <span className="mt-1 w-px flex-1 bg-line" />}
                </div>
                <div className="min-w-0 pb-1">
                  <p className="text-sm font-semibold text-ink">{layer.title}</p>
                  <p className="mt-0.5 text-[0.8125rem] leading-relaxed text-body">
                    {layer.detail}
                  </p>
                </div>
              </li>
            ))}
          </ol>
        </CardBody>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader title="Security layer" description="Applied across every step above." />
          <CardBody>
            <dl className="divide-y divide-line text-[0.8125rem]">
              {SECURITY.map(([name, purpose]) => (
                <div key={name} className="flex justify-between gap-3 py-2">
                  <dt className="font-medium text-ink">{name}</dt>
                  <dd className="text-right text-muted">{purpose}</dd>
                </div>
              ))}
            </dl>
          </CardBody>
        </Card>

        <Card>
          <CardHeader title="Two separations that are load-bearing" />
          <CardBody className="space-y-3 text-[0.8125rem] leading-relaxed text-body">
            <p>
              <span className="font-semibold text-ink">Self-report is not an input.</span> The
              structure the pipeline reads has no field for the patient&rsquo;s own score, so it
              cannot reach inference through an oversight. It is the reference the model is trained
              and measured against, and the report prints the two side by side.
            </p>
            <p>
              <span className="font-semibold text-ink">Names are not in the ledger.</span> A block
              holds a hash, a link and a signature. There is nothing in a block to derive a patient
              from, which is a property of what is stored rather than a policy about who may read
              it.
            </p>
          </CardBody>
        </Card>
      </div>

      <Card>
        <CardHeader title="What the platform does not do" />
        <CardBody>
          <ul className="space-y-2 text-[0.8125rem] leading-relaxed text-body">
            <li className="border-l-2 border-line pl-3">
              It measures nothing. Every physiological value is entered by the clinician from a
              normal examination. No sensor, wearable or external device is involved anywhere.
            </li>
            <li className="border-l-2 border-line pl-3">
              It does not read images. Documents are stored and shown; the findings are the
              clinician&rsquo;s, and no imaging model is implemented.
            </li>
            <li className="border-l-2 border-line pl-3">
              It does not diagnose. Categories are patterns the recorded information is compatible
              with, and alerts report features that usually warrant review.
            </li>
          </ul>
        </CardBody>
      </Card>
    </>
  )
}
