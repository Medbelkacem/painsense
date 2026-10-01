import time
from collections import Counter
from threading import Lock

from fastapi import APIRouter, Request, Response, status
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from backend.ai import features, model
from backend.dependencies import DbSession
from database.models import ModelVersion
from database.session import engine

router = APIRouter(prefix="/api/health", tags=["platform"])

VERSION = "1.0.0"
DISCLAIMER = (
    "AI-assisted research and educational prototype. It does not constitute a medical "
    "diagnosis and does not replace professional clinical judgement."
)


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self.started_at = time.time()
        self.requests = Counter()
        self.statuses = Counter()
        self.latency_ms = Counter()
        self.slowest_ms: dict[str, float] = {}
        self.inference_count = 0
        self.inference_ms_total = 0.0

    def observe(self, route: str, status_code: int, elapsed_ms: float) -> None:
        with self._lock:
            self.requests[route] += 1
            self.statuses[str(status_code)[0] + "xx"] += 1
            self.latency_ms[route] += elapsed_ms
            self.slowest_ms[route] = max(self.slowest_ms.get(route, 0.0), elapsed_ms)

    def observe_inference(self, elapsed_ms: float) -> None:
        with self._lock:
            self.inference_count += 1
            self.inference_ms_total += elapsed_ms

    def snapshot(self) -> dict:
        with self._lock:
            routes = {
                route: {
                    "count": count,
                    "mean_ms": round(self.latency_ms[route] / count, 2),
                    "max_ms": round(self.slowest_ms[route], 2),
                }
                for route, count in self.requests.most_common(40)
            }
            return {
                "uptime_seconds": round(time.time() - self.started_at),
                "requests_total": sum(self.requests.values()),
                "status_classes": dict(self.statuses),
                "routes": routes,
                "inference": {
                    "count": self.inference_count,
                    "mean_ms": (
                        round(self.inference_ms_total / self.inference_count, 2)
                        if self.inference_count
                        else None
                    ),
                },
            }


metrics = Metrics()


def _database_check(db) -> dict:
    started = time.perf_counter()
    try:
        db.execute(text("SELECT 1"))
        # Inspected through the session's own connection: a second connection would queue
        # behind the lock this one holds on SQLite.
        ready = inspect(db.connection()).has_table("users")
    except SQLAlchemyError as exc:
        return {"ok": False, "detail": type(exc).__name__}
    return {
        "ok": ready,
        "detail": "schema ready" if ready else "schema missing; run alembic upgrade head",
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "dialect": engine.dialect.name,
    }


def _model_check(db) -> dict:
    row = db.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))
    if row is None:
        return {"ok": False, "detail": "no active model"}
    try:
        bundle = model.load(row.version)
    except model.ModelUnavailable as exc:
        return {"ok": False, "detail": str(exc), "version": row.version}
    current = (
        tuple(bundle.feature_names) == features.NAMES
        and bundle.feature_schema_version == features.FEATURE_SCHEMA_VERSION
    )
    return {
        "ok": current,
        "detail": "active" if current else "fitted on a previous feature schema",
        "version": row.version,
        "feature_schema_version": bundle.feature_schema_version,
        "mae": row.mae,
    }


@router.get("")
def health(request: Request, response: Response, db: DbSession) -> dict:
    checks = {"database": _database_check(db), "model": _model_check(db)}
    healthy = checks["database"]["ok"]
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "ok" if healthy else "degraded",
        "schema_ready": checks["database"]["ok"],
        "checks": checks,
        "version": VERSION,
        "disclaimer": DISCLAIMER,
        "request_id": getattr(request.state, "request_id", None),
    }


@router.get("/database")
def health_database(response: Response, db: DbSession) -> dict:
    check = _database_check(db)
    if not check["ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return check


@router.get("/model")
def health_model(response: Response, db: DbSession) -> dict:
    check = _model_check(db)
    if not check["ok"]:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return check


@router.get("/metrics")
def health_metrics() -> dict:
    return metrics.snapshot()
