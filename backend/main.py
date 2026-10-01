import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from cryptography.exceptions import InvalidTag
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError, OperationalError
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend.api import (
    ai_model,
    analytics,
    anatomy,
    assessments,
    audit,
    auth,
    behaviour,
    burns,
    catalog,
    datasets,
    doctors,
    documents,
    external_datasets,
    health,
    integrity,
    jobs,
    patients,
    physiology,
    predictions,
    reports,
    security,
    signals,
)
from config import get_settings
from database.session import SessionLocal, engine
from database.seed import seed_reference_data
from security.encryption import KeyVersionUnavailable
from security.key_management import KeyManagementService

logger = logging.getLogger("painsense")

API_PREFIX = "/api"
STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}

API_CSP = "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"
REQUEST_ID_HEADER = "X-Request-ID"

ERROR_CODES = {
    400: "invalid_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    410: "gone",
    413: "payload_too_large",
    415: "unsupported_media_type",
    422: "invalid_clinical_data",
    429: "rate_limited",
    500: "internal_error",
    503: "service_unavailable",
}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "time": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in ("request_id", "method", "path", "status", "elapsed_ms", "actor"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        for handler in root.handlers:
            if get_settings().log_format == "json":
                handler.setFormatter(JsonFormatter())
        return
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter()
        if get_settings().log_format == "json"
        else logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    root.addHandler(handler)
    root.setLevel(logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    if inspect(engine).has_table("users"):
        with SessionLocal() as db:
            counts = seed_reference_data(db)
            KeyManagementService(db).sync()
        logger.info("reference data present: %d rows", sum(counts.values()))
    else:
        logger.error(
            "database schema is missing; run 'alembic upgrade head' before serving requests"
        )
    yield


app = FastAPI(
    title="PainSense",
    version=health.VERSION,
    summary="AI-assisted pain assessment from manually entered clinical findings.",
    description=health.DISCLAIMER,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token", REQUEST_ID_HEADER],
    expose_headers=[REQUEST_ID_HEADER, "Content-Disposition"],
)


def _error(request: Request, status_code: int, message: str, detail=None) -> JSONResponse:
    body = {
        "error": {
            "code": ERROR_CODES.get(status_code, "error"),
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
        },
        "detail": detail if detail is not None else message,
    }
    return JSONResponse(status_code=status_code, content=body)


@app.exception_handler(StarletteHTTPException)
async def http_error(request: Request, exc: StarletteHTTPException):
    detail = exc.detail
    message = detail if isinstance(detail, str) else ERROR_CODES.get(exc.status_code, "error")
    response = _error(request, exc.status_code, message, detail)
    if exc.headers:
        response.headers.update(exc.headers)
    return response


def _validation_detail(exc: RequestValidationError) -> list[dict]:
    # Pydantic puts the original exception object in ctx and echoes the submitted
    # value in input. Neither survives JSON encoding, and the submitted value has
    # no business travelling back out of the service, so only the field path, the
    # message and the kind of failure are reported.
    return [
        {
            "loc": [str(part) for part in error.get("loc", ())],
            "msg": error.get("msg", ""),
            "type": error.get("type", ""),
        }
        for error in exc.errors()
    ]


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    return _error(request, 422, "Invalid clinical data", _validation_detail(exc))


@app.exception_handler(KeyVersionUnavailable)
async def key_version_error(request: Request, exc: KeyVersionUnavailable):
    logger.error("sealed record unreadable: %s", exc, extra=_log_extra(request))
    return _error(
        request,
        409,
        "This record was sealed under a key version this server does not hold.",
    )


@app.exception_handler(InvalidTag)
async def decryption_error(request: Request, exc: InvalidTag):
    logger.error("decryption failed", extra=_log_extra(request))
    return _error(
        request,
        409,
        "A sealed record could not be opened. The stored data or the key does not match.",
    )


@app.exception_handler(IntegrityError)
async def integrity_error(request: Request, exc: IntegrityError):
    logger.warning("integrity error: %s", exc.orig, extra=_log_extra(request))
    return _error(request, 409, "The change conflicts with an existing record.")


@app.exception_handler(OperationalError)
async def database_error(request: Request, exc: OperationalError):
    logger.error("database unavailable: %s", exc.orig, extra=_log_extra(request))
    return _error(request, 503, "Database unavailable")


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    logger.exception("unhandled error", extra=_log_extra(request))
    return _error(request, 500, "An internal error occurred. Quote the request id.")


def _log_extra(request: Request) -> dict:
    return {
        "request_id": getattr(request.state, "request_id", None),
        "method": request.method,
        "path": request.url.path,
    }


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex[:16]
    request.state.request_id = request_id[:64]
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        health.metrics.observe(
            _route_name(request), 500, (time.perf_counter() - started) * 1000
        )
        raise
    elapsed = (time.perf_counter() - started) * 1000
    response.headers[REQUEST_ID_HEADER] = request.state.request_id
    response.headers.update(STATIC_HEADERS)
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith(API_PREFIX):
        response.headers["Content-Security-Policy"] = API_CSP

        response.headers["Cache-Control"] = "no-store"
        health.metrics.observe(_route_name(request), response.status_code, elapsed)
        user = getattr(request.state, "user", None)
        logger.info(
            "%s %s %d %.1fms",
            request.method,
            request.url.path,
            response.status_code,
            elapsed,
            extra={
                "request_id": request.state.request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "elapsed_ms": round(elapsed, 1),
                "actor": str(user.id) if user is not None else None,
            },
        )
    return response


def _route_name(request: Request) -> str:
    route = request.scope.get("route")
    path = getattr(route, "path", None) or request.url.path
    return f"{request.method} {path}"


for router in (
    health.router,
    auth.router,
    doctors.router,
    patients.router,
    assessments.router,
    predictions.router,
    physiology.router,
    documents.router,
    reports.router,
    catalog.router,
    anatomy.router,
    analytics.router,
    integrity.router,
    security.router,
    audit.router,
    datasets.router,
    external_datasets.router,
    burns.router,
    signals.router,
    behaviour.router,
    ai_model.router,
    jobs.router,
):
    app.include_router(router)
