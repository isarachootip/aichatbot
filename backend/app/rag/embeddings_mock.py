"""Deterministic 1024-dim Thai feature-hashed embedder for unit tests and offline evals."""

import hashlib
import math
from collections.abc import Sequence

from app.rag.thai_nlp import tokenize_words

EXPECTED_DIMENSIONS = 1024


class MockEmbedder:
    """Deterministic 1024-dim feature-hashed Thai embedder for tests and offline runs."""

    dimensions: int = EXPECTED_DIMENSIONS

    def _embed_single(self, text: str) -> list[float]:
        vec = [0.0] * self.dimensions
        words = [tok.lower() for tok in tokenize_words(text)]
        features = list(words)
        compact = "".join(words)
        for idx in range(max(0, len(compact) - 2)):
            features.append(f"3g:{compact[idx : idx + 3]}")

        if not features:
            vec[0] = 1.0
            return vec

        for feat in features:
            digest = hashlib.sha256(feat.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % self.dimensions
            sign = 1.0 if (digest[4] & 1) == 0 else -1.0
            weight = 2.0 if not feat.startswith("3g:") else 0.5
            vec[bucket] += sign * weight

        norm = math.sqrt(sum(val * val for val in vec))
        if norm == 0.0:
            vec[0] = 1.0
            return vec
        return [val / norm for val in vec]

    async def embed_texts(
        self,
        texts: Sequence[str],
        *,
        batch_size: int = 32,
    ) -> list[list[float]]:
        del batch_size
        return [self._embed_single(text) for text in texts]

    async def embed_query(self, query: str) -> list[float]:
        return self._embed_single(query)
