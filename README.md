# Pain Score

A clinical decision-support platform for pain assessment. A clinician records where the pain
is, what it is like, what comes with it, and the vital signs measured during the examination.
The platform estimates pain intensity on a 0-10 scale, explains what moved that estimate,
lists the categories the recorded picture is compatible with, raises rule-based alerts, and
produces a PDF report for the patient's file.

Most of what reaches an estimate is entered by the clinician from an ordinary examination.
Two things are measured by the platform itself, and each is a separate channel with its own
quality gate: an EEG and EMG recording from an attached amplifier, and a short camera and
microphone clip from which the eyes, the face and the voice are measured. The platform
also reaches outwards in one direction, to public dataset publishers, for research data
about diseases. See [external dataset synchronisation](docs/external-datasets.md).

Written for the ICAIMB 2026 PAIN SCORE challenge at University of Batna 2.

## Three separations that shape the design

**The patient's self-reported score is never a model input.** It is recorded in its own
table and the structure the pipeline reads has no field for it, so it cannot reach inference
through an oversight. It is the reference the model is trained and evaluated against, and
the interface and the report print the two numbers side by side. Where they disagree, the
platform says so rather than assuming the model is right.

**The ledger holds no clinical content.** A block carries a hash, a link to the block before
it and a signature. There are no names, findings or measurements in it, so a patient cannot
be derived from the ledger, whoever reads it.

**A recording is measured and then deleted.** A clip of a patient's face and voice is the
most identifying thing the platform touches, and once the thirty-odd numbers are out of it
there is no clinical question the file answers that they do not. So it is discarded unless
the clinician asks for it to be kept, and a kept clip is encrypted under its own data key.
Its digest is held either way, which ties the measures to the clip they came from and
identifies nobody.

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
config.py           settings, read from .env
database/           ORM models, session, reference-data seeding
knowledge/          taxonomies, wards, consistency checks, cause knowledge base, rule engine
security/           authentication, encryption, hybrid PQC, keystore, audit, ledger
dataset/synthetic/  synthetic generator and clinical archetypes (training data only)
backend/
  api/              HTTP layer, one module per resource
  ai/               quality gate, features, model registry, estimator, training
  behaviour/        camera and microphone: eyes, face, voice, quality, voice model
  signals/          EEG and EMG acquisition, simulator, features, inference
  reports/          PDF generation
  migrations/       Alembic
  tests/
frontend/
  src/
    api/            typed client and query hooks
    anatomy/        3D body: parametric model, scene, site picker
    components/     patient form, assessment summary, estimate panel, layout
    pages/          one module per route
```

## Prerequisites

Python 3.12, Node 20 or later, and PostgreSQL for any shared environment. SQLite is the
default when `DATABASE_URL` is unset and is enough for a local run. Docker Compose v2 for
the container route.

`ffmpeg` has to be on the path for the camera and microphone analysis: a browser writes its
recording as Opus in a WebM container and nothing in the Python stack decodes that. The
container image installs it; on Debian or Ubuntu, `apt install ffmpeg`.

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

The schema comes from the migrations and nothing else: no seeded patients, no sample
scores. The only rows written at start-up are the reference taxonomies.

```
cd backend
PYTHONPATH=.. .venv/bin/alembic upgrade head
PYTHONPATH=.. .venv/bin/python -m backend.cli bootstrap --email you@hospital.example --password "a long passphrase" --admin
```

`bootstrap` also loads the reference taxonomies. `python -m backend.cli seed` reloads them
on their own after an upgrade. Every screen starts empty and says so.

## Accounts and roles

| Role | Can |
| --- | --- |
| `DOCTOR` | Register patients, record, estimate, validate and delete assessments, export PDFs |
| `NURSE` | Register patients, record and estimate; cannot validate or delete |
| `PATIENT` | Read one record, the one an administrator tied to the account, and export its PDFs |
| `CLINIC_ADMIN`, `SUPER_ADMIN` | Everything clinical except validation, plus accounts, models and datasets |
| `RESEARCHER`, `AUDITOR` | Models and datasets; integrity and audit |

Self-registration creates a doctor or a nurse account from the profession given. Patient
accounts are created by an administrator on the Accounts page.

## External datasets

The platform polls WHO, CDC, Kaggle and PhysioNet for published disease datasets,
catalogues what they hold, retrieves what the licence and access policy permit, and shows
the result per disease. Restricted datasets are recorded with the steps a person would
follow to obtain them; their files are never requested.

```bash
python -m backend.cli sync --discover-only      # catalogue, download nothing
python -m backend.cli sync --source kaggle      # one publisher
```

The `worker` service runs this on a schedule. Full behaviour, configuration and the
reasoning behind each gate: [docs/external-datasets.md](docs/external-datasets.md).

## Burn assessment

A burn module covering incident documentation, the burned surface area on both the
Lund-Browder and Rule of Nines charts, depth categories, pain around wound care on the
platform's existing scales, the wound-care log, follow-up and clinician review.

Patient-reported, model-suggested and clinician-confirmed findings are stored in separate
columns throughout, and only a clinician can move a suggestion into an assessment. The
adult surface-area chart is refused for a patient under 15, and superficial erythema is
excluded from the total and reported separately.

Behaviour, the charts themselves and what is deliberately not built:
[docs/burncare.md](docs/burncare.md).

## EEG & EMG analysis

Records EEG and surface EMG, with optional pulse, skin conductance and respiration
channels beside them; measures per-channel signal quality; and extracts standard spectral
and amplitude features, a pulse rate with its variability, and the skin conductance level
with its spontaneous responses.

A model is fitted on those features from the PainMonit database, 52 volunteers under
calibrated contact heat, validated on people it never saw:

```bash
python -m backend.cli train-signal-pain --dataset /path/to/painmonit
```

It reads skin conductance alone — the corpus samples at 250 Hz, under the rate these EMG
channels need — and predicts that corpus's continuous visual analogue rating, 0 to 100,
with 15.1 of error against 24.1 for predicting the mean, and AUC 0.94 telling a rest
window from the hottest stimulus. It is not on a 0-10 scale and no conversion onto one is
published, so the scale is stored and shown beside every number. The database's clinical
half carries the only 0-10 ratings in it and no candidate beat the mean on them, so that
model is registered inactive rather than served.

A labelled simulator covers development and the degraded states — detached electrode,
clipped amplifier, mains hum, dropped lead — and simulated data can never merge with
hardware data.

Hardware, wiring, electrical safety and how to test the workflow:
[docs/eeg-emg.md](docs/eeg-emg.md).

## Camera and microphone

Records a short clip and measures what the eyes, the face and the voice are doing: the
palpebral aperture and how far it has narrowed from this patient's own resting opening, the
blink rate, the time spent with the eyes squeezed shut, the pupil diameter in millimetres
and its unrest, the gaze, the brow, the mouth, head movement, and the pitch, jitter,
shimmer, harmonics-to-noise, speech rate and non-speech vocalisation of the voice.

The patient is asked to look at the camera with their eyes open, and that is a gate rather
than a courtesy: the eye measures come only from frames where both eyes are found open, and
below a floor of such frames the eye modality is refused rather than averaged over a
handful. The millimetre scale comes from the iris, whose visible diameter is close to
11.7 mm in every adult eye, so nothing has to be calibrated.

This is the platform's behavioural observation channel, and it matters most for the patients
who cannot be asked for a number — a newborn, someone with dementia, someone in critical
care — because for exactly those patients the reference scale is observational and every one
of those scales has a facial item and most have a vocal one.

The measures are features of the clinical estimator. The acoustic ones additionally feed a
separate model trained on real human recordings — 779 utterances from 194 speakers in the
PainSpeech-4 corpus, 0.65 levels of speaker-grouped error against 1.00 for predicting the
mean — which predicts that corpus's four-point scale and never a score out of ten, because
no mapping between the two is published.

The clip is deleted once the measures are out of it unless the clinician asks for it to be
kept.

```
PYTHONPATH=.. .venv/bin/python -m backend.behaviour.training    # the voice model, on the acquired corpus
```

What is measured, how, what it is refused for, and what it does not mean:
[docs/camera-and-microphone.md](docs/camera-and-microphone.md).

## Dataset and model

The estimator has nothing to run on until a dataset exists and a model is trained. The
dataset is synthetic training data, never patients: it is written under `backend/datasets/`
and does not appear anywhere in the interface.

```
cd backend
PYTHONPATH=.. .venv/bin/python ../scripts/generate_dataset.py --patients 1200 --assessments 12000 --seed 42
PYTHONPATH=.. .venv/bin/python -m backend.cli train
```

`train` fits the newest generated dataset, registers the model and makes it the active one.
Until a model is active, the estimate endpoint refuses rather than returning a number.
Both steps are also available to administrators from the Dataset and AI models pages.

## Running

```
cd backend && PYTHONPATH=.. .venv/bin/uvicorn backend.main:app --reload --port 8000
cd frontend && npm run dev
```

The interface is on `https://localhost:5173` when `frontend/certs/` holds a certificate
(`scripts/dev-cert.sh` issues one; the camera and microphone need it away from localhost)
and on `http://localhost:5173` otherwise. It proxies `/api` to the backend; point it
elsewhere with `API_PROXY=http://host:port npm run dev`.

## The assessment form

One wizard records a patient (name, identifier issued as `PS-YYYY-NNNNNN`, age, sex, ward
from a fixed list, Algerian telephone numbers, emergency contact, smoking status), the
assessing clinician from the signed-in account, the pain (sites on the anatomical model,
character, onset, duration as a number and a unit, pattern, course, radiation, timing),
symptoms, factors and context with free text beside every coded picker, the patient's own
0 to 10 score, vital signs, and the two optional measured channels. A draft is written the
moment a patient is chosen and amended on every step, so nothing is lost when a form is
left halfway. Empty optional fields are shown as "None recorded" on screen and in the PDF.

Three cross-checks run on every save and warn without blocking: a chronic condition that is
usually treated with no treatment on the medication list, an age that does not fit the ward,
and fever with chest pain of sudden onset, which puts a "Requires urgent clinical review"
banner on the assessment and on the report.

The EEG and EMG step has a "Simulation mode" switch, off by default. With it on, samples come
from the software simulator and every record is stored and labelled SIMULATION.

## Tests

Backend tests cover the API, the form rules, the consistency checks, deletion, the roles and
the PDF layout. Run everything with:

```
backend/.venv/bin/python -m pytest        # from the repository root
backend/.venv/bin/ruff check .

cd frontend
npx tsc -b
npm run lint
```

The backend suite covers authentication and lockout, record and document encryption, the
hybrid key agreement and signatures including tamper detection on both halves, the ledger
and audit chains including detection of an edited record, the question engine, the rule
engine, the data-quality gate, the estimation pipeline, and the HTTP workflow end to end.
There is no browser test suite in the repository; the interface is checked by hand.

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

- The clinical model is trained on synthetic data only. Its metrics describe agreement with
  synthetic self-reported scores and say nothing about clinical performance. Nothing in it
  has been validated against patient data. The voice model is the exception and is trained
  on a real corpus, which brings its own limits — see below.
- The camera and microphone measure behaviour, not pain. Every figure they produce also
  moves with fear, fatigue, room light, sedation and how far the patient sat from the lens.
  The facial measurement is geometry over a detected face box, not a trained expression
  model, so it reads orbital tightening and brow lowering and not the levator contraction
  that completes the Prkachin and Solomon score. It has been validated against rendered
  faces with known geometry, which tests the arithmetic and not the detection — the
  detection is the library's, at its published rate, on real faces this platform has not
  evaluated.
- The voice model predicts the four-level scale of the corpus it was trained on and not a
  0-10 score; no mapping between the two is published. That corpus is elicited pain in
  healthy volunteers speaking Arabic, and it publishes coefficients rather than audio, so
  the correspondence between what it was trained on and what is measured at the bedside is
  an inference from its column naming rather than something it states.
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
