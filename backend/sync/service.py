"""One synchronisation run, from "what does the publisher have?" to "is it trainable?".

The stages are the ones the brief asks for, in order, and each writes a `SyncEvent`
whether it succeeded, was skipped or failed. A dataset that is not here has a reason on
file rather than simply being absent, which is what makes the result auditable afterwards.

Three things keep an unattended run from doing damage.

*Acquisition is capped per run.* Discovery may turn up sixty new datasets; downloading
sixty datasets unattended is how a volume fills. The rest keep their rows and are
collected on the next pass, newest and most relevant first.

*Every failure is contained to its dataset.* A publisher that returns nonsense for one
entry must not abandon the other fifty-nine, so each dataset is wrapped and its exception
recorded against it.

*Nothing is retried blindly.* A failed acquisition gets exponential backoff; a refused
licence is not retried at all, because it will not have changed.
"""

from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.sync import catalog, diseases, licensing, profile, storage, suitability, validate
from backend.sync import sources as connectors
from backend.sync.sources import RemoteDataset, Unavailable
from config import get_settings
from database.models import (
    Availability,
    ExternalDataset,
    ExternalDatasetVersion,
    ExternalSource,
    Granularity,
    ModelVersion,
    QualityStatus,
    RunStatus,
    SyncOutcome,
    SyncRun,
    SyncStage,
)

logger = logging.getLogger("painsense.sync")

OK = SyncOutcome.OK
SKIPPED = SyncOutcome.SKIPPED
FAILED = SyncOutcome.FAILED


@dataclass
class RunSummary:
    source_code: str
    run_id: str
    discovered: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    acquired: int = 0
    duplicates: int = 0
    metadata_only: int = 0
    failed: int = 0
    diseases_created: int = 0
    training_queued: int = 0
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "source": self.source_code,
            "run_id": self.run_id,
            "discovered": self.discovered,
            "created": self.created,
            "updated": self.updated,
            "unchanged": self.unchanged,
            "acquired": self.acquired,
            "duplicates": self.duplicates,
            "metadata_only": self.metadata_only,
            "failed": self.failed,
            "diseases_created": self.diseases_created,
            "training_queued": self.training_queued,
            "errors": self.errors[:20],
        }


def ensure_sources(db: Session) -> int:
    """Create the `external_sources` row for any connector that has none.

    Configuration lives on the row, not in the code, so an existing row is left exactly as
    an operator left it — including disabled, and including a hand-edited search list.
    """
    created = 0
    for connector in connectors.CONNECTORS:
        if db.get(ExternalSource, connector.code) is not None:
            continue
        db.add(
            ExternalSource(
                code=connector.code,
                label=connector.label,
                organisation=connector.organisation,
                homepage=connector.homepage,
                enabled=True,
                poll_interval_minutes=get_settings().sync_interval_minutes,
                config=dict(connector.default_config),
            )
        )
        created += 1
    if created:
        db.commit()
    return created


def due_sources(db: Session, at: datetime | None = None) -> list[ExternalSource]:
    moment = at or catalog.now()
    rows = db.scalars(select(ExternalSource).where(ExternalSource.enabled.is_(True))).all()
    return [row for row in rows if row.next_run_at is None or row.next_run_at <= moment]


def run_source(
    db: Session,
    source_code: str,
    *,
    trigger: str = "schedule",
    job_id=None,
    acquire: bool | None = None,
    limit: int | None = None,
    progress=None,
) -> RunSummary:
    settings = get_settings()
    source = db.get(ExternalSource, source_code)
    if source is None:
        raise KeyError(f"no configured source {source_code!r}")
    connector = connectors.get(source_code)

    run = SyncRun(source_code=source_code, trigger=trigger, job_id=job_id)
    db.add(run)
    db.flush()
    summary = RunSummary(source_code=source_code, run_id=str(run.id))
    budget = settings.sync_max_acquisitions_per_run if limit is None else limit
    may_acquire = settings.sync_auto_acquire if acquire is None else acquire

    try:
        found = connector.discover(dict(source.config or {}))
    except Exception as exc:  # noqa: BLE001 - recorded against the run, not re-raised
        catalog.log(
            db,
            run=run,
            source_code=source_code,
            stage=SyncStage.DISCOVER,
            outcome=FAILED,
            message=str(exc)[:1000],
        )
        _finish(db, run, source, summary, status=RunStatus.FAILED, error=str(exc))
        summary.errors.append(str(exc))
        return summary

    summary.discovered = len(found)
    catalog.log(
        db,
        run=run,
        source_code=source_code,
        stage=SyncStage.DISCOVER,
        outcome=OK,
        message=f"the publisher listed {len(found)} dataset(s) matching the configured search",
        detail={"count": len(found)},
    )

    pending: list[tuple[ExternalDataset, RemoteDataset]] = []
    for index, remote in enumerate(found):
        try:
            result = catalog.upsert(db, source_code, remote)
        except Exception as exc:  # noqa: BLE001 - one bad listing must not end the run
            summary.failed += 1
            summary.errors.append(f"{remote.external_id}: {exc}")
            catalog.log(
                db,
                run=run,
                source_code=source_code,
                stage=SyncStage.DISCOVER,
                outcome=FAILED,
                external_id=remote.external_id,
                message=f"the listing could not be recorded: {exc}",
            )
            continue

        if result.created:
            summary.created += 1
        elif result.changed:
            summary.updated += 1
        else:
            summary.unchanged += 1

        if result.needs_work and _identify(db, run, result.dataset, remote):
            summary.diseases_created += 1
        if result.dataset.availability is not Availability.AVAILABLE or result.changed:
            pending.append((result.dataset, remote))
        if progress and found:
            progress(0.1 + 0.3 * (index + 1) / len(found), "cataloguing what the publisher listed")
    db.commit()

    if may_acquire:
        _acquire_batch(db, run, source, connector, pending, summary, budget, progress)
    else:
        catalog.log(
            db,
            run=run,
            source_code=source_code,
            stage=SyncStage.ACQUIRE,
            outcome=SKIPPED,
            message="automatic acquisition is switched off for this deployment",
        )

    _finish(db, run, source, summary, status=RunStatus.DONE, error=None)
    return summary


def _identify(db: Session, run: SyncRun, row: ExternalDataset, remote: RemoteDataset) -> bool:
    """Attach the dataset to a disease, creating the entry when it is genuinely new."""
    match = diseases.identify(db, remote.search_text, source_ref=f"{row.source_code}:{row.external_id}")
    row.disease_code = match.code
    row.disease_match = match.as_dict()
    db.flush()
    catalog.log(
        db,
        run=run,
        source_code=row.source_code,
        stage=SyncStage.IDENTIFY_DISEASE,
        outcome=OK if match.code else SKIPPED,
        dataset=row,
        message=(
            f"linked to {match.label} ({match.code}) on {match.basis}"
            if match.code
            else match.basis
        ),
        detail=match.as_dict(),
    )
    return match.created


def _acquire_batch(
    db: Session,
    run: SyncRun,
    source: ExternalSource,
    connector,
    pending: list[tuple[ExternalDataset, RemoteDataset]],
    summary: RunSummary,
    budget: int,
    progress,
) -> None:
    # Most relevant first, then most recently revised: when the budget runs out, what was
    # left behind should be the least interesting rather than the alphabetically last.
    ordered = sorted(
        pending,
        key=lambda pair: (-pair[0].relevance, -(pair[0].changed_at or pair[0].first_seen_at).timestamp()),
    )
    spent = 0
    for row, remote in ordered:
        refusal = licensing.refusal(row.access_status, row.licence_verdict)
        if refusal:
            catalog.record_metadata_only(db, row, refusal)
            summary.metadata_only += 1
            catalog.log(
                db,
                run=run,
                source_code=row.source_code,
                stage=SyncStage.ACQUIRE,
                outcome=SKIPPED,
                dataset=row,
                message=refusal,
                detail={
                    "access_status": row.access_status.value,
                    "licence": row.licence,
                    "licence_verdict": row.licence_verdict.value,
                    "access_procedure": row.access_procedure,
                },
            )
            db.commit()
            continue

        if not catalog.due(row):
            catalog.log(
                db,
                run=run,
                source_code=row.source_code,
                stage=SyncStage.ACQUIRE,
                outcome=SKIPPED,
                dataset=row,
                message=(
                    f"{row.attempts} previous attempt(s) failed; the next is not due until "
                    f"{row.next_attempt_at.isoformat(timespec='seconds')}"
                ),
            )
            continue

        if spent >= budget:
            catalog.log(
                db,
                run=run,
                source_code=row.source_code,
                stage=SyncStage.ACQUIRE,
                outcome=SKIPPED,
                dataset=row,
                message=(
                    f"this run's acquisition budget of {budget} dataset(s) is spent; the "
                    "dataset keeps its place and is collected on the next run"
                ),
            )
            continue

        spent += 1
        if progress:
            progress(0.4 + 0.5 * spent / max(1, min(budget, len(ordered))), f"retrieving {row.external_id}")
        try:
            acquired = _acquire_one(db, run, connector, row, remote, summary)
        except Exception as exc:  # noqa: BLE001 - contained to this dataset
            db.rollback()
            row = db.get(ExternalDataset, row.id)
            summary.failed += 1
            summary.errors.append(f"{row.external_id}: {exc}")
            until = catalog.record_failure(db, row, traceback.format_exc()[-2000:])
            catalog.log(
                db,
                run=run,
                source_code=row.source_code,
                stage=SyncStage.ACQUIRE,
                outcome=FAILED,
                dataset=row,
                message=f"{exc}",
                detail={"retry_after": until.isoformat(timespec="seconds")},
            )
            db.commit()
            continue
        if acquired:
            summary.acquired += 1
        db.commit()


def _acquire_one(
    db: Session,
    run: SyncRun,
    connector,
    row: ExternalDataset,
    remote: RemoteDataset,
    summary: RunSummary,
) -> bool:
    settings = get_settings()
    key = storage.key_for(row.source_code, row.external_id, remote.publisher_version or "current")
    destination = storage.prepare(key)

    try:
        result = connector.fetch(remote, destination, max_bytes=settings.sync_max_dataset_bytes)
    except Unavailable:
        storage.discard(key)
        raise

    held = catalog.holds_content(db, row, result.sha256)
    if held is not None:
        # Same bytes under a possibly new version label. Nothing is stored twice; the
        # existing copy is what the platform holds and the attempt is recorded as a
        # duplicate so the run's numbers add up.
        storage.discard(key)
        summary.duplicates += 1
        catalog.record_success(db, row)
        catalog.log(
            db,
            run=run,
            source_code=row.source_code,
            stage=SyncStage.ACQUIRE,
            outcome=SKIPPED,
            dataset=row,
            message=(
                f"the publisher's copy is byte-identical to version {held.version} already "
                "held, so it was not stored again"
            ),
            detail={"sha256": result.sha256, "existing_version": held.version},
        )
        return False

    version_label = result.version
    if catalog.version_named(db, row, version_label) is not None:
        # The publisher reused a version label for different bytes. Both copies are kept;
        # the newer one is suffixed so the provenance of each stays intact.
        version_label = f"{version_label}+{result.sha256[:8]}"

    stored = storage.resolve(key)
    files = tuple(path for path in result.files if path.is_file())
    measured = profile.describe(files, declared_format=result.file_format)
    report = validate.check(files, measured)

    version = ExternalDatasetVersion(
        dataset_id=row.id,
        version=version_label[:64],
        source_url=result.retrieved_from[:1000],
        licence=row.licence,
        storage_backend=storage.FILESYSTEM,
        storage_key=key,
        bytes=result.bytes,
        sha256=result.sha256,
        file_format=result.file_format,
        file_count=len(files),
        manifest=[item.as_dict() for item in storage.manifest(stored)][:500],
        records=measured.rows,
        columns=measured.columns,
        missing_value_pct=measured.missing_value_pct,
        quality_status=report.status,
        quality_findings=report.as_dicts(),
    )
    db.add(version)
    db.flush()

    catalog.log(
        db,
        run=run,
        source_code=row.source_code,
        stage=SyncStage.ACQUIRE,
        outcome=OK,
        dataset=row,
        message=(
            f"retrieved {result.bytes:,} byte(s) in {len(files)} file(s) as version "
            f"{version.version}"
        ),
        detail={
            "sha256": result.sha256,
            "version": version.version,
            "licence": row.licence,
            "notes": result.notes,
        },
    )
    catalog.log(
        db,
        run=run,
        source_code=row.source_code,
        stage=SyncStage.VALIDATE,
        outcome=FAILED if report.status is QualityStatus.FAILED else OK,
        dataset=row,
        message=(
            f"{report.status.value.lower().replace('_', ' ')} with "
            f"{len(report.findings)} finding(s)"
        ),
        detail={"findings": report.as_dicts(), "profile": measured.as_dict()},
    )

    if measured.granularity is not Granularity.UNKNOWN:
        row.granularity = measured.granularity
    if measured.rows is not None:
        row.records_claimed = row.records_claimed or measured.rows
    catalog.record_success(db, row)

    _preprocess(db, run, row, version, report, stored)
    _assess(db, run, row, version, measured, summary)
    return True


def _preprocess(db, run, row, version, report, stored) -> None:
    if report.cleaned is None:
        catalog.log(
            db,
            run=run,
            source_code=row.source_code,
            stage=SyncStage.PREPROCESS,
            outcome=SKIPPED,
            dataset=row,
            message="no parsable table was available to preprocess",
        )
        return
    try:
        validate.write_preprocessed(report.cleaned, stored / "preprocessed" / "table.parquet")
    except Exception as exc:  # noqa: BLE001 - the stored original is unaffected
        catalog.log(
            db,
            run=run,
            source_code=row.source_code,
            stage=SyncStage.PREPROCESS,
            outcome=FAILED,
            dataset=row,
            message=f"the normalised copy could not be written: {exc}",
        )
        return
    version.preprocessed_key = f"{version.storage_key}/preprocessed/table.parquet"
    db.flush()
    catalog.log(
        db,
        run=run,
        source_code=row.source_code,
        stage=SyncStage.PREPROCESS,
        outcome=OK,
        dataset=row,
        message=(
            f"wrote a normalised parquet copy of {len(report.cleaned):,} row(s) alongside "
            "the stored original"
        ),
        detail={"path": version.preprocessed_key, "duplicate_rows": report.duplicate_rows},
    )


def _assess(db, run, row, version, measured, summary: RunSummary) -> None:
    verdict = suitability.assess(measured)
    version.suitability = verdict.as_dict()
    version.trainable = verdict.trainable
    db.flush()
    catalog.log(
        db,
        run=run,
        source_code=row.source_code,
        stage=SyncStage.SUITABILITY,
        outcome=OK if verdict.trainable else SKIPPED,
        dataset=row,
        message=(
            "suitable for a per-subject pain intensity baseline"
            if verdict.trainable
            else "; ".join(verdict.reasons)[:1000]
        ),
        detail=verdict.as_dict(),
    )
    if not verdict.trainable:
        return
    if not get_settings().sync_auto_train:
        catalog.log(
            db,
            run=run,
            source_code=row.source_code,
            stage=SyncStage.TRAIN,
            outcome=SKIPPED,
            dataset=row,
            message="automatic training is switched off for this deployment",
        )
        return

    from backend.api import jobs

    job = jobs.enqueue(
        db,
        jobs.TRAIN_EXTERNAL_BASELINE,
        {"version_id": str(version.id)},
        None,
    )
    version.training_job_id = job.id
    db.flush()
    summary.training_queued += 1
    catalog.log(
        db,
        run=run,
        source_code=row.source_code,
        stage=SyncStage.TRAIN,
        outcome=OK,
        dataset=row,
        message=f"queued a baseline training job for version {version.version}",
        detail={"job_id": str(job.id)},
    )


def _finish(db, run, source, summary: RunSummary, *, status: RunStatus, error: str | None) -> None:
    run.status = status
    run.finished_at = catalog.now()
    run.counts = summary.as_dict()
    run.error = error[:4000] if error else None
    source.last_run_at = run.finished_at
    source.last_status = status.value
    source.last_error = run.error
    source.next_run_at = run.finished_at + timedelta(
        minutes=max(5, source.poll_interval_minutes)
    )
    source.consecutive_failures = (
        source.consecutive_failures + 1 if status is RunStatus.FAILED else 0
    )
    db.commit()


def run_due(db: Session, *, trigger: str = "schedule", job_id=None, progress=None) -> list[dict]:
    """Run every source whose schedule has come round. Used by the background worker."""
    ensure_sources(db)
    results = []
    for source in due_sources(db):
        try:
            results.append(
                run_source(db, source.code, trigger=trigger, job_id=job_id, progress=progress).as_dict()
            )
        except Exception as exc:
            db.rollback()
            logger.exception("source %s failed", source.code)
            results.append({"source": source.code, "error": str(exc)})
    return results


def train_external_baseline(db: Session, version_id, *, progress=None) -> dict:
    """Fit the baseline model a suitability verdict asked for.

    Recorded as a `ModelVersion` with `is_active=False`. Nothing here may activate a
    model: the clinical estimator is selected by `app.ai`, and a regressor fitted on a
    publisher's own columns has no business answering a bedside question.
    """
    from backend.sync import training as external_training

    version = db.get(ExternalDatasetVersion, version_id)
    if version is None:
        raise LookupError(f"no acquired dataset version {version_id}")
    dataset = db.get(ExternalDataset, version.dataset_id)
    if not version.trainable:
        raise external_training.NotTrainable(
            "this version was not assessed as suitable for training"
        )
    if not version.preprocessed_key:
        raise external_training.NotTrainable("no preprocessed table was written for this version")

    import pandas as pd

    frame = pd.read_parquet(storage.resolve(version.preprocessed_key))
    verdict = version.suitability or {}
    target = _normalised(verdict.get("target_column"))
    subject = _normalised(verdict.get("subject_column"))
    if target not in frame.columns or subject not in frame.columns:
        raise external_training.NotTrainable(
            f"the preprocessed table has no {target!r}/{subject!r} column pair"
        )

    if progress:
        progress(0.3, "fitting the baseline")
    result, model = external_training.train(frame, target=target, subject=subject)
    label = external_training.version_label(dataset.external_id, version.version)
    artifact = external_training.persist(
        model, get_settings().model_store_path / f"{label}.joblib"
    )
    if progress:
        progress(0.9, "recording the model version")

    db.add(
        ModelVersion(
            version=label,
            model_name=f"{external_training.MODEL_NAME_PREFIX}:{dataset.external_id}"[:64],
            algorithm=result.algorithm,
            dataset_version=f"{dataset.source_code}:{dataset.external_id}@{version.version}"[:64],
            n_train=result.n_train,
            n_validation=0,
            n_test=result.n_test,
            mae=result.mae,
            rmse=result.rmse,
            r2=result.r2,
            pearson=result.pearson,
            cv_folds=result.cv_folds,
            cv_mae_mean=result.cv_mae_mean,
            cv_mae_sd=result.cv_mae_sd,
            residual_sd=result.residual_sd,
            features=result.features,
            feature_importance=result.feature_importance,
            training_profile=result.as_dict(),
            artifact_name=artifact.name,
            is_active=False,
            notes=(
                "Baseline fitted on an external dataset's own columns, with splits grouped "
                "by subject. It predicts that dataset's rating column and shares no feature "
                "schema with the clinical pain estimator. Not usable for a clinical estimate."
            ),
        )
    )
    db.commit()
    return {"model_version": label, **result.as_dict()}


def _normalised(name: str | None) -> str:
    return (name or "").strip().casefold().replace(" ", "_").replace("-", "_")
