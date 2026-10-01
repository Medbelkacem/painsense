import hashlib
import uuid
from io import BytesIO
from typing import Annotated

from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
    status,
)
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import select

from backend.api import schemas
from backend.api.assessments import get_assessment
from backend.api.patients import get_patient
from config import get_settings
from database.models import ADMIN_ROLES, DocumentKind, MedicalDocument, User
from backend.dependencies import ClinicalUser, DbSession, client_ip
from security import audit, encryption

router = APIRouter(prefix="/api/documents", tags=["documents"])

PDF_TEXT_PAGE_LIMIT = 20
EXTRACTED_TEXT_LIMIT = 20_000

SIGNATURES = (
    (b"%PDF-", "application/pdf"),
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
)


def _detect_media_type(data: bytes) -> str:
    for prefix, media_type in SIGNATURES:
        if data.startswith(prefix):
            return media_type
    raise HTTPException(
        status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Only PDF, JPEG and PNG files are accepted",
    )


def _extract_pdf_text(data: bytes) -> str | None:
    try:
        reader = PdfReader(BytesIO(data))
        pages = [page.extract_text() or "" for page in reader.pages[:PDF_TEXT_PAGE_LIMIT]]
    except (PyPdfError, ValueError, KeyError, OSError):
        return None
    text = "\n".join(pages).strip()
    return text[:EXTRACTED_TEXT_LIMIT] or None


def _document_aad(document_id: uuid.UUID) -> bytes:
    return f"document:{document_id}".encode()


def _safe_filename(name: str) -> str:
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    cleaned = "".join(ch for ch in base if ch.isprintable() and ch not in '"\\')
    return cleaned.strip() or "document"


def _require_editor(document: MedicalDocument, user: User) -> None:
    if user.role not in ADMIN_ROLES and document.uploaded_by != user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the clinician who uploaded this document can change its findings",
        )


@router.post("", response_model=schemas.DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    db: DbSession,
    user: ClinicalUser,
    patient_id: Annotated[uuid.UUID, Form()],
    file: Annotated[UploadFile, File()],
    kind: Annotated[DocumentKind, Form()] = DocumentKind.OTHER,
    assessment_id: Annotated[uuid.UUID | None, Form()] = None,
    findings: Annotated[str | None, Form()] = None,
) -> schemas.DocumentOut:
    settings = get_settings()
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail="The file is empty")
    if len(data) > settings.max_document_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Files are limited to {settings.max_document_bytes // (1024 * 1024)} MB",
        )

    media_type = _detect_media_type(data)
    patient = get_patient(db, patient_id)
    if assessment_id is not None:
        assessment = get_assessment(db, assessment_id)
        if assessment.patient_id != patient.id:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="That assessment belongs to another patient",
            )

    document = MedicalDocument(
        patient_id=patient.id,
        assessment_id=assessment_id,
        kind=kind,
        original_filename=_safe_filename(file.filename or "document")[:255],
        media_type=media_type,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        storage_name=uuid.uuid4().hex,
        wrapped_key=b"",
        findings=findings,
        extracted_text=_extract_pdf_text(data) if media_type == "application/pdf" else None,
        uploaded_by=user.id,
    )
    db.add(document)
    db.flush()

    ciphertext, wrapped = encryption.encrypt_blob(data, aad=_document_aad(document.id))
    document.wrapped_key = wrapped
    (settings.document_store_path / document.storage_name).write_bytes(ciphertext)
    db.commit()
    db.refresh(document)

    audit.record(
        db,
        event_type=audit.DOCUMENT_UPLOADED,
        actor_id=user.id,
        actor_label=user.email,
        resource="document",
        resource_id=str(document.id),
        client_ip=client_ip(request),
        meta={"kind": kind.value, "media_type": media_type, "bytes": len(data)},
        ledger_payload={
            "document_id": str(document.id),
            "patient_code": patient.code,
            "kind": kind.value,
            "sha256": document.sha256,
            "size_bytes": document.size_bytes,
        },
    )
    return schemas.DocumentOut.model_validate(document)


@router.get("", response_model=list[schemas.DocumentOut])
def list_documents(
    db: DbSession,
    user: ClinicalUser,
    patient_id: uuid.UUID | None = None,
    assessment_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> list[schemas.DocumentOut]:
    if patient_id is None and assessment_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Name the patient or the assessment whose documents to list",
        )
    filters = []
    if patient_id is not None:
        filters.append(MedicalDocument.patient_id == patient_id)
    if assessment_id is not None:
        filters.append(MedicalDocument.assessment_id == assessment_id)
    rows = db.scalars(
        select(MedicalDocument)
        .where(*filters)
        .order_by(MedicalDocument.uploaded_at.desc())
        .limit(limit)
    )
    return [schemas.DocumentOut.model_validate(row) for row in rows]


def _get_document(db, document_id: uuid.UUID) -> MedicalDocument:
    document = db.get(MedicalDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    return document


@router.get("/{document_id}", response_model=schemas.DocumentOut)
def read_document(
    document_id: uuid.UUID, db: DbSession, user: ClinicalUser
) -> schemas.DocumentOut:
    return schemas.DocumentOut.model_validate(_get_document(db, document_id))


@router.get("/{document_id}/content")
def download_document(
    document_id: uuid.UUID, request: Request, db: DbSession, user: ClinicalUser
) -> Response:
    document = _get_document(db, document_id)
    path = get_settings().document_store_path / document.storage_name
    if not path.exists():
        raise HTTPException(
            status.HTTP_410_GONE, detail="The stored file is no longer present on this server"
        )
    data = encryption.decrypt_blob(
        path.read_bytes(), document.wrapped_key, aad=_document_aad(document.id)
    )
    if hashlib.sha256(data).hexdigest() != document.sha256:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="The decrypted file does not match the digest recorded at upload",
        )

    audit.record(
        db,
        event_type=audit.DOCUMENT_VIEWED,
        actor_id=user.id,
        actor_label=user.email,
        resource="document",
        resource_id=str(document.id),
        client_ip=client_ip(request),
    )
    return Response(
        content=data,
        media_type=document.media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="{_safe_filename(document.original_filename)}"'
            ),
            "Cache-Control": "no-store",
        },
    )


@router.patch("/{document_id}", response_model=schemas.DocumentOut)
def set_findings(
    document_id: uuid.UUID,
    payload: schemas.DocumentFindings,
    request: Request,
    db: DbSession,
    user: ClinicalUser,
) -> schemas.DocumentOut:
    document = _get_document(db, document_id)
    _require_editor(document, user)
    document.findings = payload.findings
    db.commit()
    db.refresh(document)
    audit.record(
        db,
        event_type=audit.DOCUMENT_UPDATED,
        actor_id=user.id,
        actor_label=user.email,
        resource="document",
        resource_id=str(document.id),
        client_ip=client_ip(request),
        meta={"findings_updated": True},
        ledger_payload={
            "document_id": str(document.id),
            "sha256": document.sha256,
            "findings_length": len(payload.findings),
        },
    )
    return schemas.DocumentOut.model_validate(document)
