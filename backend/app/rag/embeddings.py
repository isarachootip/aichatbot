"""Pluggable 1024-dim embedding providers (BAAI/bge-m3, OpenAI, deterministic mock)."""

import asyncio
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from openai import AsyncOpenAI

from app.core.config import Settings
from app.rag.embeddings_mock import EXPECTED_DIMENSIONS, MockEmbedder

__all__ = [
    "EXPECTED_DIMENSIONS",
    "BgeM3Embedder",
    "Embedder",
    "MockEmbedder",
    "OpenAIEmbedder",
    "create_embedder",
]


@runtime_checkable
class Embedder(Protocol):
    """Async batch embedding interface locked to 1024-dimensional vectors."""

    dimensions: int

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 32,
    ) -> list[list[float]]:
        """Embed a sequence of document chunks in batches."""
        ...

    async def embed_query(self, query: str) -> list[float]:
        """Embed a single customer search query."""
        ...


class _SentenceTransformerLike(Protocol):
    def encode(
        self,
        sentences: list[str],
        *,
        batch_size: int,
        normalize_embeddings: bool,
        show_progress_bar: bool,
    ) -> object: ...


class _EmbeddingItemLike(Protocol):
    embedding: Sequence[float]


class _EmbeddingsResponseLike(Protocol):
    data: Sequence[_EmbeddingItemLike]


class _EmbeddingsEndpointLike(Protocol):
    async def create(
        self,
        *,
        model: str,
        input: list[str],
        dimensions: int,
    ) -> _EmbeddingsResponseLike: ...


class _OpenAIClientLike(Protocol):
    embeddings: _EmbeddingsEndpointLike


def _validate_vectors(vectors: list[list[float]], dimensions: int) -> list[list[float]]:
    for vec in vectors:
        if len(vec) != dimensions:
            raise ValueError(
                f"Embedding vector dimension mismatch: expected {dimensions}, got {len(vec)}"
            )
    return vectors


class BgeM3Embedder:
    """Local sentence-transformers embedder defaulting to BAAI/bge-m3 (1024 dims)."""

    dimensions: int = EXPECTED_DIMENSIONS

    def __init__(
        self,
        *,
        model_name: str = "BAAI/bge-m3",
        model: _SentenceTransformerLike | None = None,
    ) -> None:
        self._model_name = model_name
        self._model = model

    def _get_model(self) -> _SentenceTransformerLike:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise RuntimeError(
                    "sentence-transformers is not installed. Install optional extra "
                    "`pip install -e '.[local-embeddings]'` or switch EMBEDDING_PROVIDER."
                ) from exc
            loaded: _SentenceTransformerLike = SentenceTransformer(self._model_name)
            self._model = loaded
        return self._model

    def _encode_sync(self, texts: list[str], batch_size: int) -> list[list[float]]:
        raw = self._get_model().encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        rows = raw.tolist() if hasattr(raw, "tolist") else raw
        if not isinstance(rows, list):
            raise TypeError("Unexpected output type from SentenceTransformer.encode")
        return _validate_vectors([[float(val) for val in row] for row in rows], self.dimensions)

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 32,
    ) -> list[list[float]]:
        if not texts:
            return []
        return await asyncio.to_thread(self._encode_sync, list(texts), batch_size)

    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed_texts([query], batch_size=1))[0]


class OpenAIEmbedder:
    """OpenAI embeddings API provider locked to dimensions=1024."""

    dimensions: int = EXPECTED_DIMENSIONS

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "text-embedding-3-small",
        client: _OpenAIClientLike | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ValueError("OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai")
        self._model = model
        self._client: _OpenAIClientLike = (
            client
            if client is not None
            else AsyncOpenAI(api_key=api_key)  # type: ignore[assignment]
        )

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 32,
    ) -> list[list[float]]:
        if not texts:
            return []
        results: list[list[float]] = []
        items = list(texts)
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            response = await self._client.embeddings.create(
                model=self._model,
                input=batch,
                dimensions=self.dimensions,
            )
            batch_vecs = [[float(v) for v in item.embedding] for item in response.data]
            results.extend(_validate_vectors(batch_vecs, self.dimensions))
        return results

    async def embed_query(self, query: str) -> list[float]:
        return (await self.embed_texts([query], batch_size=1))[0]


def create_embedder(settings: Settings) -> Embedder:
    """Instantiate the configured embedding provider enforcing 1024 dimensions."""
    if settings.embedding_dimensions != EXPECTED_DIMENSIONS:
        raise ValueError(
            f"EMBEDDING_DIMENSIONS is locked to {EXPECTED_DIMENSIONS} by pgvector schema"
        )
    if settings.embedding_provider == "mock":
        return MockEmbedder()
    if settings.embedding_provider == "openai":
        model = (
            settings.embedding_model
            if settings.embedding_model.startswith("text-embedding-")
            else "text-embedding-3-small"
        )
        return OpenAIEmbedder(api_key=settings.openai_api_key, model=model)
    return BgeM3Embedder(model_name=settings.embedding_model)
