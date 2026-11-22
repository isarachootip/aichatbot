"""Hybrid retrieval: pgvector cosine (top 20) + PyThaiNLP tsvector (top 20) -> RRF top 6."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import Row, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import Chunk, Document
from app.rag.embeddings import Embedder
from app.rag.thai_nlp import build_search_tsquery
from app.rag.types import RetrievedChunk


@dataclass(frozen=True)
class _CandidateHit:
    """Internal candidate row returned by a single retrieval branch."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page: int
    chunk_index: int
    content: str
    rank: int


def fuse_rrf(
    vector_hits: Sequence[_CandidateHit],
    keyword_hits: Sequence[_CandidateHit],
    *,
    rrf_k: int = 60,
    top_k: int = 6,
) -> list[RetrievedChunk]:
    """Merge ranked vector and keyword candidate lists via Reciprocal Rank Fusion."""
    scores: dict[UUID, float] = {}
    candidates: dict[UUID, _CandidateHit] = {}
    vector_ranks: dict[UUID, int] = {}
    keyword_ranks: dict[UUID, int] = {}

    for hit in vector_hits:
        candidates[hit.chunk_id] = hit
        vector_ranks[hit.chunk_id] = hit.rank
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + (1.0 / (rrf_k + hit.rank))

    for hit in keyword_hits:
        candidates.setdefault(hit.chunk_id, hit)
        keyword_ranks[hit.chunk_id] = hit.rank
        scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + (1.0 / (rrf_k + hit.rank))

    ranked_ids = sorted(
        scores.keys(),
        key=lambda cid: (
            -scores[cid],
            vector_ranks.get(cid, 10_000),
            keyword_ranks.get(cid, 10_000),
            str(cid),
        ),
    )

    fused: list[RetrievedChunk] = []
    for cid in ranked_ids[:top_k]:
        item = candidates[cid]
        fused.append(
            RetrievedChunk(
                chunk_id=item.chunk_id,
                document_id=item.document_id,
                filename=item.filename,
                page=item.page,
                chunk_index=item.chunk_index,
                content=item.content,
                rrf_score=scores[cid],
                vector_rank=vector_ranks.get(cid),
                keyword_rank=keyword_ranks.get(cid),
            )
        )
    return fused


_ChunkRow = Row[UUID, UUID, str, int, int, str]


def _rows_to_hits(rows: Sequence[_ChunkRow]) -> list[_CandidateHit]:
    return [
        _CandidateHit(
            chunk_id=row[0],
            document_id=row[1],
            filename=row[2],
            page=row[3],
            chunk_index=row[4],
            content=row[5],
            rank=idx,
        )
        for idx, row in enumerate(rows, start=1)
    ]


async def _vector_search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query_embedding: list[float],
    limit: int,
) -> list[_CandidateHit]:
    distance_expr = Chunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page,
            Chunk.chunk_index,
            Chunk.content,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
            Document.status == "ready",
            Chunk.embedding.is_not(None),
        )
        .order_by(distance_expr.asc(), Chunk.chunk_index.asc())
        .limit(limit)
    )
    return _rows_to_hits((await session.execute(stmt)).all())


async def _keyword_search(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    query: str,
    limit: int,
) -> list[_CandidateHit]:
    tsquery_str = build_search_tsquery(query)
    if not tsquery_str:
        return []

    tsquery_expr = func.to_tsquery("simple", tsquery_str)
    rank_expr = func.ts_rank_cd(Chunk.tsv, tsquery_expr)
    stmt = (
        select(
            Chunk.id,
            Chunk.document_id,
            Document.filename,
            Chunk.page,
            Chunk.chunk_index,
            Chunk.content,
        )
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Chunk.tenant_id == tenant_id,
            Document.tenant_id == tenant_id,
            Document.status == "ready",
            Chunk.tsv.is_not(None),
            Chunk.tsv.op("@@")(tsquery_expr),
        )
        .order_by(rank_expr.desc(), Chunk.chunk_index.asc())
        .limit(limit)
    )
    return _rows_to_hits((await session.execute(stmt)).all())


async def hybrid_search(
    session: AsyncSession,
    embedder: Embedder,
    *,
    tenant_id: UUID,
    query: str,
    vector_top_k: int = 20,
    keyword_top_k: int = 20,
    final_top_k: int = 6,
    rrf_k: int = 60,
) -> list[RetrievedChunk]:
    """Run tenant-filtered hybrid vector + Thai keyword search merged via RRF.

    Must be invoked inside `tenant_scoped_session` so PostgreSQL FORCE RLS
    and explicit `tenant_id` predicates both guard every row.
    """
    cleaned_query = query.strip()
    if not cleaned_query:
        return []

    query_embedding = await embedder.embed_query(cleaned_query)
    vector_hits = await _vector_search(
        session,
        tenant_id=tenant_id,
        query_embedding=query_embedding,
        limit=vector_top_k,
    )
    keyword_hits = await _keyword_search(
        session,
        tenant_id=tenant_id,
        query=cleaned_query,
        limit=keyword_top_k,
    )
    return fuse_rrf(vector_hits, keyword_hits, rrf_k=rrf_k, top_k=final_top_k)
