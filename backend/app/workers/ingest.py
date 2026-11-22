"""ARQ document ingestion pipeline: download -> parse -> chunk -> embed -> index."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger
from app.core.storage import ObjectStorage
from app.core.tenant_context import tenant_scoped_session
from app.models.knowledge import Chunk, Document
from app.rag.chunking import chunk_pages
from app.rag.embeddings import Embedder
from app.rag.parsing import parse_document
from app.rag.thai_nlp import to_tsv_text

logger = get_logger("app.workers.ingest")


@dataclass(frozen=True)
class IngestResult:
    """Outcome summary of ingesting a single tenant document."""

    document_id: UUID
    status: str
    chunk_count: int
    error: str | None = None


async def _mark_document_failed(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    document_id: UUID,
    error_message: str,
) -> None:
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        stmt = select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
        doc = (await session.execute(stmt)).scalar_one_or_none()
        if doc is not None:
            doc.status = "failed"
            doc.error = error_message[:2000]


async def ingest_document(
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    embedder: Embedder,
    *,
    tenant_id: UUID,
    document_id: UUID,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
    embed_batch_size: int = 32,
) -> IngestResult:
    """Run the full tenant-isolated ingestion pipeline for a single document."""
    async with tenant_scoped_session(session_factory, tenant_id) as session:
        stmt = select(Document).where(
            Document.id == document_id,
            Document.tenant_id == tenant_id,
        )
        doc = (await session.execute(stmt)).scalar_one_or_none()
        if doc is None:
            raise LookupError(f"Document {document_id} not found for tenant {tenant_id}")
        doc.status = "processing"
        doc.error = None
        filename = doc.filename
        mime = doc.mime
        storage_key = doc.storage_key

    try:
        raw_bytes = await storage.download_bytes(storage_key)
        pages = parse_document(raw_bytes, filename=filename, mime=mime)
        chunks = chunk_pages(
            pages,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
        )
        if not chunks:
            raise ValueError("Document yielded zero chunks after parsing and chunking")

        vectors = await embedder.embed_texts(
            [item.content for item in chunks],
            batch_size=embed_batch_size,
        )

        async with tenant_scoped_session(session_factory, tenant_id) as session:
            # Make re-ingestion idempotent by clearing any previous chunks for this document
            await session.execute(
                delete(Chunk).where(
                    Chunk.tenant_id == tenant_id,
                    Chunk.document_id == document_id,
                )
            )
            for item, vector in zip(chunks, vectors, strict=True):
                tsv_text = to_tsv_text(item.content)
                session.add(
                    Chunk(
                        tenant_id=tenant_id,
                        document_id=document_id,
                        content=item.content,
                        page=item.page,
                        chunk_index=item.chunk_index,
                        tokens=item.tokens,
                        embedding=vector,
                        tsv=func.to_tsvector("simple", tsv_text),
                    )
                )

            doc_stmt = select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
            )
            refreshed = (await session.execute(doc_stmt)).scalar_one()
            refreshed.status = "ready"
            refreshed.error = None

        logger.info(
            "document_ingested",
            tenant_id=str(tenant_id),
            document_id=str(document_id),
            filename=filename,
            chunk_count=len(chunks),
        )
        return IngestResult(
            document_id=document_id,
            status="ready",
            chunk_count=len(chunks),
        )
    except Exception as exc:
        err_msg = f"{type(exc).__name__}: {exc}"
        await _mark_document_failed(
            session_factory,
            tenant_id=tenant_id,
            document_id=document_id,
            error_message=err_msg,
        )
        logger.exception(
            "document_ingest_failed",
            tenant_id=str(tenant_id),
            document_id=str(document_id),
            error=err_msg,
        )
        return IngestResult(
            document_id=document_id,
            status="failed",
            chunk_count=0,
            error=err_msg,
        )


async def ingest_document_job(
    ctx: dict[str, object],
    tenant_id_str: str,
    document_id_str: str,
) -> dict[str, object]:
    """ARQ task entrypoint for asynchronous document ingestion."""
    session_factory = ctx["session_factory"]
    storage = ctx["storage"]
    embedder = ctx["embedder"]
    if not isinstance(storage, ObjectStorage) or not isinstance(embedder, Embedder):
        raise RuntimeError("ARQ worker context missing storage or embedder")

    result = await ingest_document(
        session_factory,  # type: ignore[arg-type]
        storage,
        embedder,
        tenant_id=UUID(tenant_id_str),
        document_id=UUID(document_id_str),
    )
    return {
        "document_id": str(result.document_id),
        "status": result.status,
        "chunk_count": result.chunk_count,
        "error": result.error,
    }
