import logging
import signal
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from config import get_settings
from database.models import BackgroundJob, JobStatus
from database.session import SessionLocal

logger = logging.getLogger("painsense.worker")

POLL_SECONDS = 2.0

#: How often the worker asks whether any external source is due. The sources themselves
#: are polled on their own interval, measured in hours; this only decides how promptly a
#: due source is noticed.
SCHEDULE_CHECK_SECONDS = 60.0


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _progress(db, job: BackgroundJob):
    def report(fraction: float, message: str | None = None) -> None:
        job.progress = round(max(0.0, min(1.0, fraction)), 3)
        if message:
            job.result = {**(job.result or {}), "message": message}
        db.commit()

    return report


def run_generate_dataset(db, job: BackgroundJob) -> dict:
    from dataset.synthetic import generate

    parameters = job.parameters
    report = _progress(db, job)
    path, metadata = generate.write(
        patients=int(parameters.get("patients", 5000)),
        assessments=int(parameters.get("assessments", 100_000)),
        seed=int(parameters.get("seed", 42)),
        hard_case_share=float(parameters.get("hard_case_share", 0.12)),
        progress=report,
    )
    generate.register(metadata, path, actor_id=job.requested_by)
    return {
        "version": metadata["version"],
        "path": str(path),
        "patients": metadata["counts"]["patients"],
        "assessments": metadata["counts"]["assessments"],
    }


def run_train_model(db, job: BackgroundJob) -> dict:
    from backend.ai import training

    parameters = job.parameters
    report = _progress(db, job)
    dataset = parameters.get("dataset")
    row = training.train(
        db,
        dataset_path=Path(dataset) if dataset else None,
        seed=int(parameters.get("seed", 0)),
        cv_folds=int(parameters.get("cv_folds", 5)),
        actor_id=job.requested_by,
        progress=report,
    )
    return {
        "version": row.version,
        "algorithm": row.algorithm,
        "mae": row.mae,
        "rmse": row.rmse,
        "r2": row.r2,
        "f1_band": row.f1_band,
    }


def run_sync_datasets(db, job: BackgroundJob) -> dict:
    from backend.sync import service

    parameters = job.parameters
    report = _progress(db, job)
    source = parameters.get("source")
    if source:
        summary = service.run_source(
            db,
            source,
            trigger=parameters.get("trigger", "manual"),
            job_id=job.id,
            acquire=parameters.get("acquire"),
            limit=parameters.get("limit"),
            progress=report,
        )
        return {"sources": [summary.as_dict()]}
    return {
        "sources": service.run_due(
            db, trigger=parameters.get("trigger", "schedule"), job_id=job.id, progress=report
        )
    }


def run_train_external_baseline(db, job: BackgroundJob) -> dict:
    from backend.sync import service

    return service.train_external_baseline(
        db, job.parameters["version_id"], progress=_progress(db, job)
    )


def run_rewrap_keys(db, job: BackgroundJob) -> dict:
    from security.key_management import KeyManagementService

    changed = KeyManagementService(db).rewrap_all()
    return {"rewrapped": changed}


HANDLERS = {
    "generate_dataset": run_generate_dataset,
    "train_model": run_train_model,
    "rewrap_keys": run_rewrap_keys,
    "sync_datasets": run_sync_datasets,
    "train_external_baseline": run_train_external_baseline,
}


def claim(db) -> BackgroundJob | None:
    job = db.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.status == JobStatus.QUEUED)
        .order_by(BackgroundJob.created_at)
        .limit(1)
    )
    if job is None:
        return None
    job.status = JobStatus.RUNNING
    job.started_at = _now()
    db.commit()
    return job


def run(job: BackgroundJob, db) -> None:
    handler = HANDLERS.get(job.kind)
    try:
        if handler is None:
            raise ValueError(f"unknown job kind {job.kind}")
        result = handler(db, job)
        job.result = {**(job.result or {}), **result}
        job.status = JobStatus.DONE
        job.progress = 1.0
    except Exception:
        db.rollback()
        job.status = JobStatus.FAILED
        job.error = traceback.format_exc()[-4000:]
        logger.exception("job %s failed", job.id)
    job.finished_at = _now()
    db.commit()


def schedule_sync(db) -> BackgroundJob | None:
    """Queue a synchronisation job when a source is due and none is already pending.

    The guard matters: discovery takes minutes against four publishers, and a scheduler
    that queued another job every minute would pile up runs that each re-do the last
    one's work. One in flight at a time is enough, because `run_due` picks up every source
    that has come round.
    """
    from backend.api.jobs import SYNC_DATASETS
    from backend.sync import service

    if not get_settings().sync_enabled:
        return None
    service.ensure_sources(db)
    in_flight = db.scalar(
        select(BackgroundJob).where(
            BackgroundJob.kind == SYNC_DATASETS,
            BackgroundJob.status.in_((JobStatus.QUEUED, JobStatus.RUNNING)),
        )
    )
    if in_flight is not None or not service.due_sources(db):
        return None
    job = BackgroundJob(kind=SYNC_DATASETS, parameters={"trigger": "schedule"})
    db.add(job)
    db.commit()
    logger.info("queued scheduled dataset synchronisation %s", job.id)
    return job


def recover_orphans(db) -> int:
    rows = db.scalars(
        select(BackgroundJob).where(BackgroundJob.status == JobStatus.RUNNING)
    ).all()
    for job in rows:
        job.status = JobStatus.FAILED
        job.error = "The worker stopped before this job finished."
        job.finished_at = _now()
    db.commit()
    return len(rows)


def main(once: bool = False) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    stopping = {"now": False}

    def stop(*_args) -> None:
        stopping["now"] = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    with SessionLocal() as db:
        orphans = recover_orphans(db)
        if orphans:
            logger.warning("marked %d orphaned job(s) as failed", orphans)

    logger.info("worker started")
    next_schedule_check = 0.0
    while not stopping["now"]:
        if time.monotonic() >= next_schedule_check:
            next_schedule_check = time.monotonic() + SCHEDULE_CHECK_SECONDS
            with SessionLocal() as db:
                try:
                    schedule_sync(db)
                except Exception:
                    # A scheduling failure must not take the worker down with it; the
                    # queue still needs draining and the next check is a minute away.
                    db.rollback()
                    logger.exception("could not schedule dataset synchronisation")
        with SessionLocal() as db:
            job = claim(db)
            if job is not None:
                logger.info("running %s job %s", job.kind, job.id)
                run(job, db)
                logger.info("job %s finished with status %s", job.id, job.status.value)
                continue
        if once:
            break
        time.sleep(POLL_SECONDS)
    logger.info("worker stopped")


if __name__ == "__main__":
    import sys

    main(once="--once" in sys.argv)
