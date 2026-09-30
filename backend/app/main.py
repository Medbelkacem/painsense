"""Application entry point."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect

from app.api import (
    ai_model,
    analytics,
    anatomy,
    assessments,
    audit,
    auth,
    catalog,
    datasets,
    doctors,
    documents,
    integrity,
    patients,
    physiology,
    reports,
    security,
)
from app.config import get_settings
from app.database.database import SessionLocal, engine
from app.database.seed import seed_reference_data

logger = logging.getLogger("painscore")

DISCLAIMER = (
    "AI-assisted research and educational prototype. It does not constitute a medical "
    "diagnosis and does not replace professional clinical judgement."
)

API_PREFIX = "/api"
STATIC_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "geolocation=(), camera=(), microphone=()",
}
# The API returns JSON and nothing else, so it needs no script, style or frame source.
API_CSP = "default-src 'none'; base-uri 'none'; frame-ancestors 'none'"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if inspect(engine).has_table("users"):
        with SessionLocal() as db:
            counts = seed_reference_data(db)
        logger.info("reference data present: %d rows", sum(counts.values()))
    else:
        logger.error(
            "database schema is missing; run 'alembic upgrade head' before serving requests"
        )
    yield


app = FastAPI(
    title="Pain Score",
    version="0.1.0",
    summary="Clinical decision support for pain assessment from manually entered findings.",
    description=DISCLAIMER,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-CSRF-Token"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.update(STATIC_HEADERS)
    if request.url.scheme == "https":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    if request.url.path.startswith(API_PREFIX):
        response.headers["Content-Security-Policy"] = API_CSP
        # Clinical responses must not sit in a shared or browser cache.
        response.headers["Cache-Control"] = "no-store"
    return response


for router in (
    auth.router,
    doctors.router,
    patients.router,
    assessments.router,
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
    ai_model.router,
):
    app.include_router(router)


@app.get("/api/health", tags=["platform"])
def health() -> dict:
    return {
        "status": "ok",
        "schema_ready": inspect(engine).has_table("users"),
        "disclaimer": DISCLAIMER,
    }
