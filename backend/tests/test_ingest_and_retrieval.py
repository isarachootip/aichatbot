"""Integration tests for ingestion pipeline, hybrid RRF search, and tenant isolation."""

from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.storage import InMemoryStorage
from app.core.tenant_context import tenant_scoped_session
from app.models.knowledge import Chunk, Document
from app.models.tenant import BotSetting, Tenant
from app.rag.embeddings import MockEmbedder
from app.rag.retrieval import _CandidateHit, fuse_rrf, hybrid_search
from app.workers.ingest import ingest_document


def test_fuse_rrf_boosts_chunks_found_by_both_branches() -> None:
    doc_id = uuid4()
    c1, c2, c3 = uuid4(), uuid4(), uuid4()
    vec_hits = [
        _CandidateHit(c1, doc_id, "a.txt", 1, 0, "first vector", rank=1),
        _CandidateHit(c2, doc_id, "a.txt", 1, 1, "both branches", rank=2),
    ]
    kw_hits = [
        _CandidateHit(c2, doc_id, "a.txt", 1, 1, "both branches", rank=1),
        _CandidateHit(c3, doc_id, "a.txt", 2, 2, "only keyword", rank=2),
    ]

    fused = fuse_rrf(vec_hits, kw_hits, rrf_k=60, top_k=6)

    assert [item.chunk_id for item in fused] == [c2, c1, c3]
    assert fused[0].vector_rank == 2
    assert fused[0].keyword_rank == 1


@pytest.mark.usefixtures("clean_database")
async def test_ingest_document_ready_and_idempotent_reingest(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    doc_id = uuid4()
    async with admin_session_factory() as session, session.begin():
        session.add(Tenant(id=tenant_id, name="Shop Ingest"))
        await session.flush()
        session.add(BotSetting(tenant_id=tenant_id, shop_name="Shop Ingest"))
        session.add(
            Document(
                id=doc_id,
                tenant_id=tenant_id,
                filename="shipping_faq.txt",
                mime="text/plain",
                storage_key="ingest/shipping_faq.txt",
                status="pending",
            )
        )

    storage = InMemoryStorage()
    await storage.upload_bytes(
        "ingest/shipping_faq.txt",
        "ค่าจัดส่งมาตรฐาน 40 บาท ส่งฟรีเมื่อซื้อครบ 500 บาท ตัดรอบส่ง 14:00 น.".encode(),
        "text/plain",
    )
    embedder = MockEmbedder()

    first = await ingest_document(
        app_session_factory,
        storage,
        embedder,
        tenant_id=tenant_id,
        document_id=doc_id,
    )
    assert first.status == "ready"
    assert first.chunk_count == 1

    # Re-ingest should replace existing chunks without duplicating rows
    second = await ingest_document(
        app_session_factory,
        storage,
        embedder,
        tenant_id=tenant_id,
        document_id=doc_id,
    )
    assert second.status == "ready"
    assert second.chunk_count == 1

    async with tenant_scoped_session(app_session_factory, tenant_id) as session:
        chunks = (
            await session.execute(select(Chunk).where(Chunk.document_id == doc_id))
        ).scalars().all()
        assert len(chunks) == 1
        assert chunks[0].embedding is not None
        assert chunks[0].tsv is not None


@pytest.mark.usefixtures("clean_database")
async def test_ingest_document_marks_failed_on_parse_error(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_id = uuid4()
    doc_id = uuid4()
    async with admin_session_factory() as session, session.begin():
        session.add(Tenant(id=tenant_id, name="Shop Fail"))
        await session.flush()
        session.add(
            Document(
                id=doc_id,
                tenant_id=tenant_id,
                filename="bad.png",
                mime="image/png",
                storage_key="fail/bad.png",
                status="pending",
            )
        )

    storage = InMemoryStorage()
    await storage.upload_bytes("fail/bad.png", b"not-a-document", "image/png")

    result = await ingest_document(
        app_session_factory,
        storage,
        MockEmbedder(),
        tenant_id=tenant_id,
        document_id=doc_id,
    )
    assert result.status == "failed"
    assert result.error is not None and "Unsupported file format" in result.error

    async with tenant_scoped_session(app_session_factory, tenant_id) as session:
        doc = (await session.execute(select(Document).where(Document.id == doc_id))).scalar_one()
        assert doc.status == "failed"
        assert doc.error is not None


@pytest.mark.usefixtures("clean_database")
async def test_hybrid_search_ranks_relevant_thai_chunk_and_blocks_cross_tenant_leak(
    admin_session_factory: async_sessionmaker[AsyncSession],
    app_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    tenant_a, tenant_b = uuid4(), uuid4()
    doc_a1, doc_a2, doc_b = uuid4(), uuid4(), uuid4()

    async with admin_session_factory() as session, session.begin():
        session.add_all([Tenant(id=tenant_a, name="Shop A"), Tenant(id=tenant_b, name="Shop B")])
        await session.flush()
        session.add_all(
            [
                Document(
                    id=doc_a1,
                    tenant_id=tenant_a,
                    filename="shipping_a.txt",
                    mime="text/plain",
                    storage_key="a/shipping.txt",
                    status="pending",
                ),
                Document(
                    id=doc_a2,
                    tenant_id=tenant_a,
                    filename="return_a.txt",
                    mime="text/plain",
                    storage_key="a/return.txt",
                    status="pending",
                ),
                Document(
                    id=doc_b,
                    tenant_id=tenant_b,
                    filename="secret_b.txt",
                    mime="text/plain",
                    storage_key="b/secret.txt",
                    status="pending",
                ),
            ]
        )

    storage = InMemoryStorage()
    await storage.upload_bytes(
        "a/shipping.txt",
        "ค่าจัดส่งมาตรฐาน 40 บาท ส่งฟรีเมื่อซื้อครบ 500 บาท".encode(),
        "text/plain",
    )
    await storage.upload_bytes(
        "a/return.txt",
        "นโยบายคืนสินค้าภายใน 7 วัน ต้องมีป้ายราคาครบถ้วน".encode(),
        "text/plain",
    )
    await storage.upload_bytes(
        "b/secret.txt",
        "รหัสลับส่วนลด 99% ของร้าน B และค่าจัดส่งฟรีทุกออเดอร์ของร้าน B".encode(),
        "text/plain",
    )

    embedder = MockEmbedder()
    for tid, did in [(tenant_a, doc_a1), (tenant_a, doc_a2), (tenant_b, doc_b)]:
        res = await ingest_document(
            app_session_factory,
            storage,
            embedder,
            tenant_id=tid,
            document_id=did,
        )
        assert res.status == "ready"

    async with tenant_scoped_session(app_session_factory, tenant_a) as session:
        hits = await hybrid_search(
            session,
            embedder,
            tenant_id=tenant_a,
            query="ค่าจัดส่งเท่าไหร่ ส่งฟรีครบกี่บาทครับ",
        )
        assert len(hits) >= 1
        assert hits[0].document_id == doc_a1
        assert hits[0].filename == "shipping_a.txt"
        assert all(hit.document_id != doc_b for hit in hits)
        assert all("ร้าน B" not in hit.content for hit in hits)
