# Pain Score

A clinical decision-support platform for pain assessment. A clinician records where the pain
is, what it is like, what comes with it, and the vital signs measured during the examination.
The platform estimates pain intensity on a 0-10 scale, explains what moved that estimate,
lists the categories the recorded picture is compatible with, raises rule-based alerts, and
produces a PDF report for the patient's file.

No sensor, wearable or external device is involved anywhere. Every physiological value is
entered by the clinician from a normal examination; the platform measures nothing itself.

Written for the ICAIMB 2026 PAIN SCORE challenge at University of Batna 2.

## Two separations that shape the design

**The patient's self-reported score is never a model input.** It is recorded in its own
table and the structure the pipeline reads has no field for it, so it cannot reach inference
through an oversight. It is the reference the model is trained and evaluated against, and
the interface and the report print the two numbers side by side. Where they disagree, the
platform says so rather than assuming the model is right.

**The ledger holds no clinical content.** A block carries a hash, a link to the block before
it and a signature. There are no names, findings or measurements in it, so a patient cannot
be derived from the ledger, whoever reads it.

## Architecture

```
React PWA ─► FastAPI ─► clinical data layer ─► PostgreSQL
                │                                  │
                ├─► estimation pipeline            └─► audit chain and signed ledger
                └─► encrypted document store
```

The estimation pipeline runs in order: data-quality gate, feature assembly, gradient
boosting for the point estimate, two quantile models for the interval, SHAP for the
contributions, then a transparent rule layer for the candidate categories, the alerts and
the priority indicator.

```
backend/
  app/
    api/            HTTP layer, one module per resource
    ai/             quality gate, features, model registry, estimator, training
    knowledge/      taxonomies, question engine, cause knowledge base, rule engine
    security/       authentication, encryption, hybrid PQC, keystore, audit
    blockchain/     canonical hashing, append-only ledger, verification
    reports/        PDF generation
    database/       models, session, reference-data seeding
    datasets/       synthetic generator, clinical archetypes, demonstration cases
  migrations/       Alembic
  tests/
frontend/
  src/
    api/            typed client and query hooks
    components/     interface primitives, body map, pain scale
    charts/         trend and distribution charts
    forms/          patient form, assessment wizard steps
    pages/          one module per route
  e2e/              Playwright
```

## Prerequisites

Python 3.12, Node 20 or later, and PostgreSQL for any shared environment. SQLite is the
default when `DATABASE_URL` is unset and is enough for a local run. Docker Compose v2 for
the container route.

## Install

```
cd backend
python -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

cd ../frontend
npm install
```

`requirements.txt` holds what the service needs at runtime; `requirements-dev.txt` adds
pytest and ruff.

## Configuration

Copy `.env.example` to `.env` at the repository root and fill it in. Docker Compose reads
that file, and so does the backend; a backend started from `backend/` also reads
`backend/.env`, which takes precedence, for when the local database is keyed differently
from the container stack.

`MASTER_KEY`, `JWT_SECRET` and `JWT_REFRESH_SECRET` each need 32 random bytes in base64:

```
python -c "import os,base64;print(base64.b64encode(os.urandom(32)).decode())"
```

Left empty, each is replaced by a random per-process value so a development machine can
start without a `.env`. Those values change at every restart, which invalidates issued
tokens and makes existing encrypted records unreadable. Set `PAINSCORE_ENV=production` to
refuse startup instead.

| Variable | Purpose |
| --- | --- |
| `DATABASE_URL` | PostgreSQL or SQLite connection string |
| `MASTER_KEY` | Wraps the per-record data keys |
| `JWT_SECRET`, `JWT_REFRESH_SECRET` | Token signing |
| `ACCESS_TOKEN_TTL_MINUTES`, `REFRESH_TOKEN_TTL_DAYS` | Session lifetimes |
| `KEY_STORE_PATH` | Ledger signing keys, kept outside the database |
| `MODEL_STORE_PATH`, `DATASET_PATH`, `DOCUMENT_STORE_PATH` | State directories |
| `CORS_ORIGINS` | Comma-separated origins allowed to call the API |
| `MAX_DOCUMENT_BYTES` | Largest accepted upload |
| `PAINSCORE_ENV` | `production` refuses to start without the secrets above |

## Database

```
cd backend
.venv/bin/alembic upgrade head
.venv/bin/python -m app.cli bootstrap --email you@hospital.example --password "a long passphrase" --admin
```

`bootstrap` also loads the reference taxonomies. `python -m app.cli seed` reloads them on
their own after an upgrade.

## Dataset and model

The estimator has nothing to run on until a dataset exists and a model is trained.

```
.venv/bin/python -m app.datasets.generate --rows 10000 --seed 42
.venv/bin/python -m app.ai.training
```

The generator is reproducible: the same seed and row count produce the same file. Every
record is synthetic and the files say so. Until a model is active, the estimate endpoint
refuses rather than returning a number.

Optionally load seven synthetic demonstration patients covering different presentations:

```
.venv/bin/python -m app.cli demo --email you@hospital.example
```

## Running

```
cd backend && .venv/bin/uvicorn app.main:app --reload --port 8000
cd frontend && npm run dev
```

The interface is on `http://localhost:5173` and proxies `/api` to the backend. Point it
somewhere else with `API_URL=http://host:port npm run dev`.

## Tests

```
cd backend
.venv/bin/python -m pytest tests
.venv/bin/ruff check app tests migrations

cd ../frontend
npm test
npm run lint
npx playwright install chromium   # once
npm run e2e
```

The backend suite covers authentication and lockout, record and document encryption, the
hybrid key agreement and signatures including tamper detection on both halves, the ledger
and audit chains including detection of an edited record, the question engine, the rule
engine, the data-quality gate, the estimation pipeline, and the HTTP workflow end to end.
The Playwright suite drives a browser through sign-in, patient creation, the seven-step
assessment, the estimate, validation and the PDF download.

## Docker

```
docker compose up --build       # or: docker-compose up --build
```

The interface is then on `http://localhost:8080`. The backend applies migrations on start,
and creates the first administrator when `BOOTSTRAP_ADMIN_EMAIL` and
`BOOTSTRAP_ADMIN_PASSWORD` are set. The keystore, the trained artifacts, the datasets and
the uploaded documents live on named volumes.

## Progressive web app

The frontend installs as a PWA. The application shell is precached so it opens offline;
every `/api` request is network-only and nothing from it is written to a cache, so no
clinical data is left on the device by the service worker.

## Security

| Primitive | Used for | Library |
| --- | --- | --- |
| Argon2id | Password hashing | argon2-cffi |
| AES-256-GCM | Records and documents at rest | cryptography |
| X25519 with ML-KEM-768 | Key establishment | cryptography, pqcrypto |
| Ed25519 with ML-DSA-65 | Ledger block signatures | cryptography, pqcrypto |
| SHA-256 | Record and chain hashing | hashlib |

Key establishment and signatures are hybrid: both halves must break for the construction to
break, so adopting the post-quantum half never weakens what the classical one already gave.
The post-quantum primitives come from pqcrypto, which packages the PQClean implementations.
Nothing here implements a cipher.

Records are sealed under a per-record data key which is itself wrapped by the master key.
Direct patient identifiers are sealed rather than kept in queryable columns, and no identity
card number is collected. Documents are encrypted before they reach the disk, and the SHA-256
recorded at upload is checked when the file is read back.

TLS is not terminated by this service. It belongs to the reverse proxy in front of it, and
`/api/security` reports it as a deployment responsibility rather than as active, because
that page reports only what the process can demonstrate. Every other row on it is produced
by exercising the primitive when the page loads.

Sessions use short-lived JWT access tokens held in memory by the client and single-use
refresh tokens in an HttpOnly cookie, with a double-submit CSRF token on the two endpoints
that act on that cookie. Failed sign-ins are rate limited per address; successful ones are
not, because a department shares one outbound address. Individual accounts are separately
protected by a lockout counter.

## Limitations

- The model is trained on synthetic data only. Its metrics describe agreement with synthetic
  self-reported scores and say nothing about clinical performance. Nothing here has been
  validated against patient data.
- The reference is the patient's self-reported score, which is itself subjective and varies
  with context. Agreement with it is not the same as measuring pain.
- The reported interval is the 10th to 90th model quantile. The coverage it achieved on
  held-out data is measured during training and shown next to it; it is usually below the
  nominal 80 per cent.
- No imaging model is implemented. Documents are stored and displayed, text already present
  in a PDF is extracted, and the findings are the clinician's.
- The rate limiter and the ledger append path hold their state in the application process,
  which is enough for a single-process deployment. More than one worker needs a shared store
  and a database-level lock.
- `/api/security` reports TLS as a deployment responsibility rather than as implemented.

## Disclaimer

This is a research and educational prototype. It is not a medical device, it produces no
diagnosis, and it does not replace clinical judgement. The estimate it reports is a model
output to be reviewed by a clinician. The patient's self-reported score is stored separately
and is never used as a model input. Alerts report features of the recorded information that
usually warrant prompt review; they are not diagnoses. Categories are patterns the recorded
information is compatible with; they are not diagnoses either.
