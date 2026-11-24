"""Knowledge-base document upload, listing, deletion, and re-ingestion service."""

import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.plans import get_plan_config
from app.core.queue import JobEnqueuer
from app.core.storage import ObjectStorage
from app.core.tenant_context import tenant_scoped_session
from app.models.knowledge import Chunk, Document
from app.models.tenant import Tenant
from app.schemas.documents import DocumentResponse, DocumentStatus

logger = get_logger("app.services.documents")

INGEST_JOB_NAME = "ingest_document_job"
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
ALLOWED_EXTENSIONS: frozenset[str] = frozenset({".pdf", ".docx", ".xlsx", ".csv", ".txt"})
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9ก-๙._-]+")


class DocumentNotFoundError(LookupError):
    """Raised when a document does not exist in the caller's tenant."""


class DocumentLimitExceededError(ValueError):
    """Raised when the tenant reaches their subscription plan's max_documents."""


class InvalidDocumentError(ValueError):
    """Raised on unsupported file extension, empty file, or oversized upload."""


def _validate_upload(filename: str, data: bytes) -> str:
    base = Path(filename or "document.txt").name.strip()
    ext = Path(base).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise InvalidDocumentError(
            f"Unsupported format '{ext or 'unknown'}'. Allowed: PDF, DOCX, XLSX, CSV, TXT"
        )
    if not data:
        raise InvalidDocumentError("Uploaded file is empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise InvalidDocumentError("Uploaded file exceeds the 20 MB limit")
    return _SAFE_NAME_RE.sub("_", base)[:180] or f"file{ext}"


def _to_response(doc: Document, chunk_count: int) -> DocumentResponse:
    status_val: DocumentStatus = doc.status  # type: ignore[assignment]
    return DocumentResponse(
        id=doc.id, filename=doc.filename, mime=doc.mime, status=status_val,
        error=doc.error, chunk_count=chunk_count, uploaded_at=doc.uploaded_at,
    )


async def _safe_delete_object(storage: ObjectStorage, key: str) -> None:
    try:
        await storage.delete_object(key)
    except Exception as exc:
        logger.warning("document_storage_delete_failed", key=key, error=str(exc))


async def upload_document(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    enqueuer: JobEnqueuer,
    *,
    tenant_id: UUID,
    filename: str,
    mime: str,
    data: bytes,
) -> DocumentResponse:
    """Validate upload, enforce plan limit, store bytes, create row, and enqueue ingest."""
    safe_name = _validate_upload(filename, data)

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        tenant = (await session.execute(select(Tenant).where(Tenant.id == tenant_id))).scalar_one()
        plan = get_plan_config(tenant.plan)
        doc_count = int(
            (
                await session.execute(
                    select(func.count(Document.id)).where(Document.tenant_id == tenant_id)
                )
            ).scalar_one()
        )
        if doc_count >= plan.max_documents:
            raise DocumentLimitExceededError(
                f"Document limit reached ({plan.max_documents} for plan '{plan.name}')"
            )

    doc_id = uuid4()
    storage_key = f"{tenant_id}/{doc_id}/{safe_name}"
    await storage.ensure_bucket()
    await storage.upload_bytes(storage_key, data, mime or "application/octet-stream")

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        doc = Document(
            id=doc_id, tenant_id=tenant_id, filename=Path(filename or safe_name).name,
            mime=mime or "application/octet-stream", storage_key=storage_key,
            status="pending", error=None,
        )
        session.add(doc)
        await session.flush()
        response = _to_response(doc, chunk_count=0)

    await enqueuer.enqueue(INGEST_JOB_NAME, str(tenant_id), str(doc_id))
    logger.info("document_uploaded", tenant_id=str(tenant_id), document_id=str(doc_id))
    return response


async def list_documents(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
) -> list[DocumentResponse]:
    """Return all tenant documents ordered newest-first with chunk counts."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        stmt = (
            select(Document, func.count(Chunk.id))
            .outerjoin(Chunk, Chunk.document_id == Document.id)
            .where(Document.tenant_id == tenant_id)
            .group_by(Document.id)
            .order_by(Document.uploaded_at.desc())
        )
        rows = (await session.execute(stmt)).all()
    return [_to_response(doc, int(chunk_count)) for doc, chunk_count in rows]


async def delete_document(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    *,
    tenant_id: UUID,
    document_id: UUID,
) -> None:
    """Delete a tenant document (cascading chunks) and remove its stored object."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        doc = (
            await session.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        storage_key = doc.storage_key
        await session.delete(doc)

    await _safe_delete_object(storage, storage_key)


async def reupload_document(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    enqueuer: JobEnqueuer,
    *,
    tenant_id: UUID,
    document_id: UUID,
    filename: str,
    mime: str,
    data: bytes,
) -> DocumentResponse:
    """Replace an existing document's file bytes and re-enqueue ingestion."""
    safe_name = _validate_upload(filename, data)

    async with tenant_scoped_session(session_factory, tenant_id) as session:
        doc = (
            await session.execute(
                select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
            )
        ).scalar_one_or_none()
        if doc is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        old_key = doc.storage_key

    new_key = f"{tenant_id}/{document_id}/{uuid4().hex[:8]}_{safe_name}"
    content_type = mime or "application/octet-stream"
    await storage.ensure_bucket()
    await storage.upload_bytes(new_key, data, content_type)
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        q = select(Document).where(Document.id == document_id, Document.tenant_id == tenant_id)
        doc_row = (await session.execute(q)).scalar_one()
        doc_row.filename, doc_row.mime = Path(filename or safe_name).name, content_type
        doc_row.storage_key, doc_row.status, doc_row.error = new_key, "pending", None
        doc_row.uploaded_at = datetime.now(UTC)
        await session.flush()
        response = _to_response(doc_row, chunk_count=0)

    if old_key != new_key:
        await _safe_delete_object(storage, old_key)
    await enqueuer.enqueue(INGEST_JOB_NAME, str(tenant_id), str(document_id))
    return response
