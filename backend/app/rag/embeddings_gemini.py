"""Google Gemini 1024-dim embedding provider via google-genai SDK."""

import asyncio
import math
from collections.abc import Sequence
from typing import Protocol

from google import genai
from google.genai import types as genai_types

from app.rag.embeddings_mock import EXPECTED_DIMENSIONS


def resolve_vertexai_flag(api_key: str, explicit_flag: bool | None) -> bool:
    """Use standard Gemini Developer API by default unless Vertex AI is explicitly enabled."""
    del api_key
    return bool(explicit_flag) if explicit_flag is not None else False


def _l2_normalize(values: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return [0.0] * len(values)
    return [float(v) / norm for v in values]


class _EmbeddingLike(Protocol):
    values: Sequence[float] | None


class _EmbedResponseLike(Protocol):
    embeddings: Sequence[_EmbeddingLike] | None


class _ModelsEndpointLike(Protocol):
    def embed_content(
        self,
        *,
        model: str,
        contents: list[str],
        config: object,
    ) -> _EmbedResponseLike: ...


class _GenAIClientLike(Protocol):
    models: _ModelsEndpointLike


class GeminiEmbedder:
    """Google Gemini embedder locked to 1024-dim L2-normalized vectors."""

    dimensions: int = EXPECTED_DIMENSIONS

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-embedding-001",
        use_vertexai: bool | None = None,
        client: _GenAIClientLike | None = None,
    ) -> None:
        if not api_key and client is None:
            raise ValueError("GEMINI_API_KEY is required when EMBEDDING_PROVIDER=gemini")
        self._model = model
        self._vertexai = resolve_vertexai_flag(api_key, use_vertexai)
        self._client: _GenAIClientLike = (
            client
            if client is not None
            else genai.Client(  # type: ignore[assignment]
                api_key=api_key,
                vertexai=self._vertexai,
            )
        )

    def _embed_batch_sync(self, batch: list[str], task_type: str) -> list[list[float]]:
        config = genai_types.EmbedContentConfig(
            output_dimensionality=self.dimensions,
            task_type=task_type,
        )
        response = self._client.models.embed_content(
            model=self._model,
            contents=batch,
            config=config,
        )
        embeddings = response.embeddings or []
        vectors: list[list[float]] = []
        for item in embeddings:
            raw = list(item.values or [])
            if len(raw) != self.dimensions:
                raise ValueError(
                    f"Gemini dimension mismatch: expected {self.dimensions}, got {len(raw)}"
                )
            vectors.append(_l2_normalize(raw))
        if len(vectors) != len(batch):
            raise ValueError(
                f"Gemini returned {len(vectors)} embeddings for {len(batch)} inputs"
            )
        return vectors

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 32,
    ) -> list[list[float]]:
        if not texts:
            return []
        items = list(texts)
        results: list[list[float]] = []
        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            batch_vecs = await asyncio.to_thread(
                self._embed_batch_sync,
                batch,
                "RETRIEVAL_DOCUMENT",
            )
            results.extend(batch_vecs)
        return results

    async def embed_query(self, query: str) -> list[float]:
        vecs = await asyncio.to_thread(
            self._embed_batch_sync,
            [query],
            "RETRIEVAL_QUERY",
        )
        return vecs[0]
