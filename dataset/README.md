# Pain dataset collection and integration

Collects pain datasets from their publishers, records what each publisher permits,
normalizes whatever was legitimately obtained onto one schema, and builds a model-ready
table with a patient-level split.

```
backend/.venv/bin/python -m dataset.pipeline run
backend/.venv/bin/python -m dataset.pipeline run --offline    # skip every network step
```

Run from the repository root on Python 3.12. `pandas`, `pyarrow` and `scipy` come from
`backend/requirements.txt`. The discovery and download steps need `kaggle.com`,
`physionet.org` and `nit.ovgu.de`; everything after them is offline.

No Kaggle credentials are required — the public dataset API answers search and download
for public datasets unauthenticated. If `~/.kaggle/kaggle.json` exists its username and key
are sent as HTTP basic auth, and `metadata/kaggle_catalog.json` records whether credentials
were present for the run.

## Layout

```
dataset/
├── dataset.parquet         every normalized record in one schema
├── model_ready.parquet     the encoded feature matrix
├── train|validation|test.parquet
├── raw/                    archives as downloaded, plus an extracted copy; never rewritten
├── sources/                one directory per source, as normalized
├── metadata/               registry, manifests, licences, download log, profiles
├── reports/                generated access, validation, leakage and statistics reports
├── pipeline/               the code that builds all of the above
└── tests/
```

A directory appears under `raw/` only once something has been obtained from that source, so
there is no empty `raw/biovid` or `raw/tame_pain` standing in for a dataset this pipeline
does not hold. Those are where the two restricted datasets would be extracted if they were
ever obtained under a signed agreement, and the access checks already profile those paths,
so they would be picked up without a code change.

## The rules this pipeline follows

**It does not bypass access control.** A dataset whose publisher requires a signed
agreement is registered with its real access status and the procedure a person would have to
follow, and is not downloaded. `download-physionet` refuses any resource whose status is not
`open`; `download-kaggle` refuses a licence flagged for review unless a reviewer passes
`--accept-reviewed-license` with a reason, which is then recorded.

**It does not invent a pain scale conversion.** `self_reported_nrs` is the regression target
and is populated only where the publisher documents the label as a 0-10 numeric rating
scale. Any other label is preserved verbatim in `original_pain_score` with its scale named
in `original_pain_scale`, and the target stays null. The decision is declared per source in
`pipeline/sources.py` as `nrs_mapping` with a written `nrs_mapping_reason`, and enforced in
one place: `Source.chunks()` clears the target for any source whose mapping is not `direct`,
whatever its normalizer produced.

**It does not claim a figure it did not measure.** A record or subject count in the registry
is a measurement where the dataset was read and the publisher's stated figure where it was
not, and the entry's note says which. Every statistic in `reports/statistics.md` is computed
from the parquet on disk.

**It does not mix real and synthetic data silently.** Every record carries `synthetic`
alongside its source, licence, version and retrieval time, and
`merge --data-source real|synthetic|all` selects between them.

**It does not delete a record for looking wrong.** Validation reports; it never edits. A
physiologically impossible reading is named and kept, because deciding whether it is a
transcription error or a genuinely unusual patient is a clinical judgement.

## The steps

Each is also a subcommand of `python -m dataset.pipeline`, so it can be run and inspected on
its own. `run` executes them in this order, each in its own process, and records every exit
code in `metadata/pipeline_run.json`.

| step | what it does |
| --- | --- |
| `discover-kaggle` | 23 pain queries against Kaggle's dataset API, deduplicated and scored for relevance, into `metadata/kaggle_catalog.json`. Relevance counts whole-word matches only, so a dataset of *paintings* does not rank as one about *pain*. Each result carries a `license_verdict` of `permissive` or `review_required`. Nothing is downloaded |
| `discover-physionet` | Sweeps the topic pages for `pain`, `nociception` and `analgesia` plus the database index, then parses each project page's access policy, licence, data use agreement, version and DOI |
| `biovid-access`, `tame-pain-access` | Read each publisher's page, record the access status and the procedure a person would follow, and quote the sentences relied on into an `evidence` field so a claim can be traced. Publisher-stated counts are labelled as theirs |
| `download-kaggle`, `download-physionet` | Nothing is downloaded unless a dataset is named. The original archive is kept beside an extracted copy, archive and every file are SHA-256 checksummed, an existing archive is never replaced without `--force`, and a member with an absolute path or `..` is refused. Every attempt, successful or refused, appends to `metadata/download_log.json` |
| `inspect` | Profiles every source present on disk into `metadata/profiles/`. A directory holding no machine-readable table profiles as `has_tabular_data: false` rather than as an empty dataset. Each continuous column is tested against a uniform distribution over its own range; one indistinguishable from uniform noise is reported, because that is not what clinical measurement looks like |
| `normalize` | Maps each source onto the schema in `pipeline/schema.py`, writing `records.parquet`, `source_features.parquet` and `normalization_report.json` per source under `sources/` |
| `merge` | Writes `dataset.parquet` (partitioned by `data_source` above 2,000,000 rows), `model_ready.parquet` and the three splits |
| `validate` | Writes `reports/validation.md` and `reports/leakage.md` with their JSON forms under `metadata/`. Exits 2 if any check of severity `error` fires or any leakage finding is blocking, so a CI job fails rather than training anyway |
| `statistics` | Writes `reports/statistics.md` and `metadata/dataset_statistics.json`, computed entirely from the unified parquet and the split assignment |

### The split

The unit of assignment is the patient, never the record. Patients are stratified by bands of
their own mean label and then dealt into train, validation and test at 70/15/15, so every
assessment belonging to one patient lands in exactly one split. The assignment is a pure
function of the patient identifiers, the labels and the seed, so `--seed 42` reproduces
exactly. Records with no patient identifier cannot be assigned and are excluded from the
model-ready table, with the count recorded. After assignment the split is audited, and a
patient found in more than one split stops the run.

### The encoding

Fitted on the training split alone, then applied unchanged to validation and test, so no
information crosses the split boundary:

- numeric: median imputation plus a per-column missing indicator, then z-score
  standardisation using the training mean and standard deviation
- single-value categorical: one indicator per level seen in training, up to 20 levels, plus
  an `__other__` indicator and a missing indicator
- multi-value categorical: one presence indicator per token seen in training, up to 40
  tokens, matched as whole semicolon-delimited items, plus a token count

Every field in the schema's `label` group is excluded from the candidate features. Identity
and provenance columns are carried through unencoded so a row can be traced back, but are
never offered as features.

### Leakage

Target leakage is checked two ways, because either alone is evadable: a name check against
the forbidden patterns in `pipeline/checks.py`, and a Spearman correlation check at 0.98 that
catches a derived target renamed to something innocuous.

## Seeds and thresholds

| quantity | value | where |
| --- | --- | --- |
| split seed | 42 | `encode.DEFAULT_SEED`, overridable with `--seed` |
| split ratios | 0.70 / 0.15 / 0.15 | `encode.DEFAULT_RATIOS` |
| single-file parquet threshold | 2,000,000 rows | `merge.PARTITION_ABOVE` |
| correlation leakage threshold | 0.98 Spearman | `checks.CORRELATION_THRESHOLD` |
| outlier threshold | 3.0 interquartile ranges | `checks.OUTLIER_IQR_MULTIPLIER` |
| categorical levels kept | 20 | `encode.MAX_LEVELS` |
| multi-value tokens kept | 40 | `encode.MAX_TOKENS` |
| uniformity test seed | 20260101 | `profile.UNIFORMITY_SEED` |

The synthetic source carries its own generator seed in its provenance manifest.

## Checksums

`metadata/download_log.json` holds, for every downloaded dataset, the archive's SHA-256 and
one SHA-256 per extracted file. Q-Pain also ships its publisher's own `SHA256SUMS.txt`:

```
cd dataset/raw/physionet/q-pain/extracted/q-pain-*/ && sha256sum -c SHA256SUMS.txt
```

## What this pipeline will not do

It will not download a dataset whose publisher requires a signed agreement, and it will not
simulate having one. It will not convert between pain scales without a documented mapping.
It will not impute a label. It will not delete a record for looking wrong. And it will not
report a count for a dataset it did not read — a figure taken from a publisher's page is
labelled as theirs wherever it appears.
