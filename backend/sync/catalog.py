"""Writing what discovery found into the database, and deciding what changed.

Three rules shape this module.

*An entry exists from the moment a dataset is considered.* A dataset nobody here may
download still gets a row, with the publisher's access status and the steps a person would
follow. Absence would be indistinguishable from never having looked.

*Measured never loses to claimed.* `records_claimed` comes from the publisher and
`ExternalDatasetVersion.records` is counted from the file. Re-running discovery refreshes
the first and cannot touch the second.

*Change is detected, not assumed.* The metadata fingerprint decides whether a listing was
revised. An unchanged fingerprint ends the work for that dataset in a few microseconds,
which is what makes a six-hourly poll over four publishers reasonable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from database.models import (
    Availability,
    ExternalDataset,
    ExternalDatasetVersion,
    SyncEvent,
    SyncOutcome,
    SyncRun,
    SyncStage,
)
from backend.sync import fingerprint, licensing
from backend.sync.sources import RemoteDataset

logger = logging.getLogger("painsense.sync")

#: Backoff between acquisition attempts for a dataset that keeps failing. A publisher
#: having a bad afternoon should not be hammered, and a dataset that is permanently broken
#: should stop consuming a slot in every run. Capped so a dataset is never retired for good.
RETRY_BACKOFF_MINUTES = (15, 60, 240, 720, 1440)


def now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class Upserted:
    dataset: ExternalDataset
    created: bool
    changed: bool

    @property
    def needs_work(self) -> bool:
        return self.created or self.changed


def log(
    db: Session,
    *,
    run: SyncRun | None,
    source_code: str,
    stage: SyncStage,
    outcome: SyncOutcome,
    message: str,
    dataset: ExternalDataset | None = None,
    external_id: str = "",
    detail: dict | None = None,
) -> SyncEvent:
    event = SyncEvent(
        run_id=run.id if run is not None else None,
        dataset_id=dataset.id if dataset is not None else None,
        source_code=source_code,
        external_id=(external_id or (dataset.external_id if dataset else ""))[:255],
        stage=stage,
        outcome=outcome,
        message=message[:4000],
        detail=detail or {},
    )
    db.add(event)
    level = logging.WARNING if outcome is SyncOutcome.FAILED else logging.INFO
    logger.log(level, "%s %s %s: %s", source_code, stage.value, outcome.value, message)
    return event


def upsert(db: Session, source_code: str, remote: RemoteDataset) -> Upserted:
    """Create or refresh the row for one discovered dataset.

    The licence verdict is recomputed every pass rather than stored once: a publisher that
    relicenses a dataset should see the gate change on the next poll, in either direction.
    """
    digest = fingerprint.of_metadata(remote.fingerprint_fields())
    row = db.scalar(
        select(ExternalDataset).where(
            ExternalDataset.source_code == source_code,
            ExternalDataset.external_id == remote.external_id,
        )
    )
    verdict = licensing.verdict(remote.licence)
    stamp = now()

    if row is None:
        row = ExternalDataset(
            source_code=source_code,
            external_id=remote.external_id,
            metadata_fingerprint=digest,
            first_seen_at=stamp,
        )
        db.add(row)
        created, changed = True, True
    else:
        created = False
        changed = row.metadata_fingerprint != digest

    row.name = remote.name[:400]
    row.description = remote.description
    row.source_url = remote.source_url[:500]
    row.download_url = remote.download_url[:1000] if remote.download_url else None
    row.download_mechanism = remote.download_mechanism[:80]
    row.dataset_type = remote.dataset_type
    row.modalities = list(remote.modalities)
    row.target_labels = list(remote.target_labels)
    row.access_status = remote.access_status
    row.access_procedure = licensing.procedure(remote.access_status)
    row.licence = remote.licence[:255] if remote.licence else None
    row.licence_url = remote.licence_url[:500] if remote.licence_url else None
    row.licence_verdict = verdict
    row.redistribution = licensing.redistribution_note(verdict)[:255]
    row.publisher_version = remote.publisher_version[:64] if remote.publisher_version else None
    row.publisher_updated_at = remote.publisher_updated_at
    row.records_claimed = remote.records_claimed
    row.relevance = remote.relevance
    row.notes = remote.notes
    row.last_checked_at = stamp

    # Granularity is a measurement once a file has been profiled. A later discovery pass
    # has only the publisher's description again, so it must not overwrite what was read
    # off the data.
    if created or row.availability is not Availability.AVAILABLE:
        row.granularity = remote.granularity

    if changed:
        row.metadata_fingerprint = digest
        row.changed_at = stamp
        # A revised listing is worth another attempt even if the last one failed.
        row.next_attempt_at = None
        row.attempts = 0
    db.flush()
    return Upserted(row, created, changed)


def holds_content(db: Session, dataset: ExternalDataset, digest: str) -> ExternalDatasetVersion | None:
    """The stored version carrying these exact bytes, if the platform already has them."""
    return db.scalar(
        select(ExternalDatasetVersion).where(
            ExternalDatasetVersion.dataset_id == dataset.id,
            ExternalDatasetVersion.sha256 == digest,
        )
    )


def version_named(db: Session, dataset: ExternalDataset, version: str) -> ExternalDatasetVersion | None:
    return db.scalar(
        select(ExternalDatasetVersion).where(
            ExternalDatasetVersion.dataset_id == dataset.id,
            ExternalDatasetVersion.version == version,
        )
    )


def due(dataset: ExternalDataset, at: datetime | None = None) -> bool:
    """Whether this dataset's next acquisition attempt is allowed yet."""
    if dataset.next_attempt_at is None:
        return True
    return (at or now()) >= dataset.next_attempt_at


def record_failure(db: Session, dataset: ExternalDataset, message: str) -> datetime:
    dataset.attempts += 1
    dataset.last_error = message[:4000]
    dataset.availability = Availability.FAILED
    index = min(dataset.attempts - 1, len(RETRY_BACKOFF_MINUTES) - 1)
    dataset.next_attempt_at = now() + timedelta(minutes=RETRY_BACKOFF_MINUTES[index])
    db.flush()
    return dataset.next_attempt_at


def record_success(db: Session, dataset: ExternalDataset) -> None:
    dataset.attempts = 0
    dataset.last_error = None
    dataset.next_attempt_at = None
    dataset.availability = Availability.AVAILABLE
    db.flush()


def record_metadata_only(db: Session, dataset: ExternalDataset, reason: str) -> None:
    """A dataset the platform will not fetch: catalogued with the reason, not retried.

    `next_attempt_at` is left unset rather than scheduled, because nothing about a refused
    licence or a credentialing requirement changes by trying again in an hour. A revised
    listing clears this through `upsert`.
    """
    dataset.availability = Availability.METADATA_ONLY
    dataset.last_error = None
    dataset.notes = reason if not dataset.notes else f"{dataset.notes} {reason}"
    db.flush()


def counts_for(db: Session, run: SyncRun) -> dict[str, int]:
    rows = db.scalars(select(SyncEvent).where(SyncEvent.run_id == run.id)).all()
    tally: dict[str, int] = {}
    for event in rows:
        key = f"{event.stage.value.lower()}_{event.outcome.value.lower()}"
        tally[key] = tally.get(key, 0) + 1
    return tally
