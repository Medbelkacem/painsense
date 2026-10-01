# External dataset synchronisation

The platform polls dataset publishers, records what they hold, retrieves what it is
permitted to retrieve, and makes the result visible per disease. This document covers how
it decides, how to configure it, and what it deliberately will not do.

## The two questions it keeps apart

A dataset has an **access status** — what the publisher permits — and an **availability** —
what this platform actually holds. They are separate columns because they are separate
facts. Conflating them is how a dashboard ends up claiming a dataset it never downloaded.

| Access status | Meaning | Retrieved? |
| --- | --- | --- |
| `OPEN` | Anyone may take the files under the stated licence | Yes, if the licence also permits |
| `REGISTRATION_REQUIRED` | An account and accepted terms are needed | No |
| `CREDENTIALED` | Credentialing, usually with human-subjects training, plus a signed DUA | No |
| `AGREEMENT_REQUIRED` | A signed data use agreement | No |
| `DOCUMENT_ONLY` | Published as PDFs or bulletins, not through a data interface | No |
| `UNKNOWN` | The policy could not be read | No |

Anything not `OPEN` is catalogued with the steps a person would follow to obtain it, and no
request is made for its files. Nothing in `app/sync` attempts to satisfy an access control,
including with credentials that happen to be configured.

## Licence verdicts

The licence gate is separate from the access gate and answers a different question: given
that we may take a copy, what may we do with it?

| Verdict | Meaning | Retrieved? |
| --- | --- | --- |
| `PERMISSIVE` | Holding and redistributing are both permitted | Yes |
| `RESEARCH_ONLY` | Research use of a copy; no redistribution, no commercial use | Yes |
| `REVIEW_REQUIRED` | Not recognised automatically | No — a person must read it |
| `RESTRICTED` | Requires a signed instrument or individual grant | No |
| `UNKNOWN` | The publisher states no licence | No |

`RESEARCH_ONLY` exists because most of what WHO publishes is CC BY-NC-SA. Treating that as
restricted would exclude it wrongly; treating it as permissive would lose the fact that it
cannot be redistributed. The verdict is recomputed on every poll, so a relicensed dataset
changes gate in either direction on the next run.

## Sources

| Code | Publisher | Discovery | What it serves |
| --- | --- | --- | --- |
| `who_gho` | WHO Global Health Observatory | OData indicator catalogue | Population statistics per country and period. Never patient-level. |
| `cdc_socrata` | CDC open data | Socrata catalogue API | Mixed: summary tables and some case-level files. |
| `kaggle` | Kaggle | Dataset search API | Community datasets of every shape and licence. |
| `physionet` | PhysioNet | Project page parsing | Mostly credentialed; a few open projects. |

Each connector declares the hosts it may reach, and the HTTP client refuses any URL outside
them. This matters because download URLs arrive inside publisher responses: a compromised
or misconfigured API could otherwise point the worker at an internal address. Redirects are
followed by hand with the same check at each hop, and addresses that resolve inside the
network are refused.

Sources live in the `external_sources` table, one row each, created on first use. The
search configuration is on the row, not in the code — edit it through
`PATCH /api/external-datasets/sources/{code}` or directly.

## What a run does

1. **Discover.** Read the publisher's catalogue. No dataset files are fetched.
2. **Record.** Upsert the listing. A digest of the publisher's stated facts
   (`metadata_fingerprint`) decides whether anything was revised; an unchanged digest ends
   the work for that dataset.
3. **Identify the disease.** Match a disease name as a whole phrase in the title or
   description, against diseases the platform already holds first, then against a
   vocabulary of diseases these publishers carry.
4. **Create the disease if new.** Flagged `curated=False` with provenance — see below.
5. **Gate.** Apply the access and licence rules above. A refusal is recorded with its
   reason and the access procedure; it is not retried, because nothing about it changes.
6. **Retrieve.** Stream to disk under a per-version directory, capped at
   `SYNC_MAX_DATASET_BYTES`, with the digest taken from the bytes as they arrive.
7. **Deduplicate.** If the digest matches a version already held, discard the download and
   record a duplicate. A publisher bumping a version number without changing a byte does
   not produce a second copy.
8. **Profile and validate.** Count rows, read columns, find the subject and rating columns,
   record findings. The stored original is never edited.
9. **Preprocess.** Write a de-duplicated parquet copy with normalised headers alongside it.
10. **Assess suitability.** Decide whether the dataset can train anything (below).
11. **Train, if suitable.** Queue a baseline job.

Every step writes a `SyncEvent`, successful or not, so a dataset that is not held has a
reason on file rather than simply being absent.

## Discovered diseases

When a publisher holds data for a disease the platform has not heard of, the disease is
created in the `diseases` table with `curated=False`, `origin='external_sync'`, the source
reference and the discovery time.

`GET /api/diseases` — the comorbidity list a clinician is offered when recording a
patient's history — returns **curated entries only**. A disease that arrived from a
publisher is visible on the dataset dashboard and queryable through the API, and is not put
in front of a clinician as a vetted option. Promoting one means adding it to
`app/knowledge/diseases.py`; the next seed sets `curated=True` on the existing row.

## The training gate

Most datasets fail it, which is the correct outcome. Four conditions, each checked against
measurements taken from the stored file rather than the publisher's description:

- rows describe individual people, not places and periods;
- a column carries a pain rating on a recognised scale (a binary pain/no-pain flag is
  reported as present but insufficient for a 0-10 regression);
- a subject identifier exists, so splits can be grouped by person — without it any score is
  leakage;
- enough rows and enough distinct subjects for a grouped split to mean something.

A dataset that passes trains **its own baseline**, not the platform's clinical estimator.
`app/sync/training.py` fits a random forest to that dataset's own numeric columns,
predicting that dataset's rating column, with `GroupShuffleSplit` and `GroupKFold` by
subject throughout. The result is recorded as a `ModelVersion` with `is_active=False` and a
`model_name` of `external-baseline:<dataset>`. It shares no feature schema with the
clinical model and is never used for a clinical estimate. Its score is reported next to the
error of predicting the training mean, so a model that found nothing is visible as such.

## Configuration

| Variable | Default | Effect |
| --- | --- | --- |
| `SYNC_ENABLED` | `true` | Whether the worker schedules runs at all |
| `SYNC_INTERVAL_MINUTES` | `360` | Default poll interval for a newly created source row |
| `SYNC_AUTO_ACQUIRE` | `true` | `false` catalogues without downloading anything |
| `SYNC_AUTO_TRAIN` | `true` | `false` assesses suitability without queueing training |
| `SYNC_MAX_DATASET_BYTES` | `268435456` | Per-dataset ceiling, enforced while streaming |
| `SYNC_MAX_ACQUISITIONS_PER_RUN` | `3` | Downloads per source per run; the rest wait |
| `SYNC_REQUEST_TIMEOUT_SECONDS` | `60` | Per-request timeout; downloads get ten times this |
| `KAGGLE_USERNAME`, `KAGGLE_KEY` | empty | Optional. Discovery works without them |

Set `SYNC_AUTO_ACQUIRE=false` on a new deployment until you have reviewed which licences
the institution accepts.

Kaggle credentials come from <https://www.kaggle.com/settings> → API → Create New Token.
They are the operator's own account used through Kaggle's documented API, and they are
never returned by any endpoint.

## Running it

The `worker` service in `docker-compose.yml` does this automatically. By hand:

```bash
# Catalogue what every due publisher lists, without downloading anything
python -m backend.cli sync --discover-only

# One source, retrieving at most two datasets
python -m backend.cli sync --source kaggle --limit 2

# Through the API (admin only); the worker picks the job up
curl -X POST localhost:8000/api/external-datasets/sync \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{}'
```

## API

| Endpoint | Role | Purpose |
| --- | --- | --- |
| `GET /api/external-datasets/overview` | research | Everything the dashboard renders, in one request |
| `GET /api/external-datasets` | research | The catalogue, filterable by source, disease, availability, access, name |
| `GET /api/external-datasets/{id}` | research | One dataset with every stored version |
| `GET /api/external-datasets/sources` | research | Configured publishers and their schedules |
| `PATCH /api/external-datasets/sources/{code}` | admin | Enable, disable, reschedule, reconfigure |
| `POST /api/external-datasets/sync` | admin | Queue a run; audited |
| `GET /api/external-datasets/runs` | research | Run history |
| `GET /api/external-datasets/events` | research | The synchronisation log |

## What it will not do

- Satisfy an access control, with or without credentials.
- Present an aggregate statistics table as a clinical dataset.
- Store a response that is not what it claimed to be — a Kaggle sign-in page returned in
  place of an archive is a failed acquisition, not a stored file.
- Overwrite a measured figure with a publisher's claim. `records` is counted from the file;
  `records_claimed` is what the publisher said; neither replaces the other.
- Train the clinical estimator on an external dataset.
- Redistribute anything. Every version row carries the licence its bytes arrived under.
