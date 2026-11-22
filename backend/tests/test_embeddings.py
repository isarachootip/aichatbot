"""Unit tests for pluggable 1024-dim embedding providers and batching."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.config import Settings
from app.rag.embeddings import (
    EXPECTED_DIMENSIONS,
    BgeM3Embedder,
    MockEmbedder,
    OpenAIEmbedder,
    create_embedder,
)


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=True))


async def test_mock_embedder_is_deterministic_1024d_and_preserves_thai_similarity() -> None:
    embedder = MockEmbedder()

    vecs = await embedder.embed_texts(
        [
            "ค่าจัดส่งมาตรฐาน 40 บาท ส่งฟรีครบ 500 บาท",
            "นโยบายคืนสินค้าภายใน 7 วัน",
        ]
    )
    query_vec = await embedder.embed_query("ค่าจัดส่งกี่บาท ส่งฟรีเท่าไหร่")

    assert len(vecs) == 2
    assert len(vecs[0]) == EXPECTED_DIMENSIONS
    assert len(query_vec) == EXPECTED_DIMENSIONS
    assert abs(_cosine(query_vec, query_vec) - 1.0) < 1e-5
    assert _cosine(query_vec, vecs[0]) > _cosine(query_vec, vecs[1])
    assert await embedder.embed_query("ค่าจัดส่งกี่บาท ส่งฟรีเท่าไหร่") == query_vec


async def test_openai_embedder_batches_requests_and_validates_dimensions() -> None:
    fake_client = SimpleNamespace(embeddings=SimpleNamespace(create=AsyncMock()))

    async def _fake_create(*, model: str, input: list[str], dimensions: int) -> SimpleNamespace:
        assert model == "text-embedding-3-small"
        assert dimensions == 1024
        return SimpleNamespace(
            data=[SimpleNamespace(embedding=[0.01] * dimensions) for _ in input]
        )

    fake_client.embeddings.create.side_effect = _fake_create
    embedder = OpenAIEmbedder(
        api_key="test-key",
        model="text-embedding-3-small",
        client=fake_client,
    )

    vectors = await embedder.embed_texts(["a", "b", "c", "d", "e"], batch_size=2)

    assert len(vectors) == 5
    assert all(len(v) == 1024 for v in vectors)
    assert fake_client.embeddings.create.await_count == 3


async def test_bge_m3_embedder_batches_and_returns_1024d_vectors() -> None:
    calls: list[list[str]] = []

    class _FakeSTModel:
        def encode(
            self,
            sentences: list[str],
            *,
            batch_size: int,
            normalize_embeddings: bool,
            show_progress_bar: bool,
        ) -> list[list[float]]:
            assert normalize_embeddings is True
            assert show_progress_bar is False
            assert batch_size == 2
            calls.append(list(sentences))
            return [[0.02] * 1024 for _ in sentences]

    embedder = BgeM3Embedder(model_name="BAAI/bge-m3", model=_FakeSTModel())

    vectors = await embedder.embed_texts(["ข้อ 1", "ข้อ 2", "ข้อ 3"], batch_size=2)

    assert len(vectors) == 3
    assert all(len(v) == 1024 for v in vectors)
    assert len(calls) == 1


def test_create_embedder_factory_respects_config_and_enforces_1024_dims() -> None:
    mock_settings = Settings(embedding_provider="mock", embedding_dimensions=1024)
    assert isinstance(create_embedder(mock_settings), MockEmbedder)

    openai_settings = Settings(
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimensions=1024,
        openai_api_key="sk-test",
    )
    assert isinstance(create_embedder(openai_settings), OpenAIEmbedder)

    bge_settings = Settings(embedding_provider="bge_m3", embedding_dimensions=1024)
    assert isinstance(create_embedder(bge_settings), BgeM3Embedder)

    with pytest.raises(ValueError, match="locked to 1024"):
        create_embedder(Settings(embedding_provider="mock", embedding_dimensions=512))
