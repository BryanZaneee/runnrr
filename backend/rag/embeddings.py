"""Embedding providers for profile-scoped RAG indexes.

Optional embedding backends are imported only when their provider is
constructed, so core EasyAgent imports stay lightweight.
"""
from __future__ import annotations

import hashlib
import math
import re
import time
from typing import Protocol


class EmbeddingProviderError(RuntimeError):
    """Raised when an embedding backend is missing or misconfigured."""


class EmbeddingProvider(Protocol):
    backend: str
    model: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class FakeEmbeddingProvider:
    """Deterministic token-hash embeddings for tests and local smoke runs."""

    backend = "fake"

    def __init__(self, *, dim: int = 64, model: str | None = None) -> None:
        if dim <= 0:
            raise ValueError("dim must be positive")
        self.dim = dim
        self.model = model or f"fake-{dim}d"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = _TOKEN_RE.findall(str(text).lower())
        if not tokens:
            tokens = [str(text)]
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[index] += sign
        return _normalize(vec)


_VOYAGE_DIMS = {
    "voyage-3-large": 1024,
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-code-3": 1024,
}


class VoyageEmbeddingProvider:
    backend = "voyage"

    def __init__(
        self,
        *,
        model: str = "voyage-3-large",
        api_key: str | None = None,
        dim: int | None = None,
    ) -> None:
        self.model = model
        self.dim = dim or _VOYAGE_DIMS.get(model, 1024)
        # config.VOYAGE_API_KEY is the single source of truth (env-derived at import,
        # patchable in tests). Only fall back to it when no key was passed, so an
        # explicitly-empty key still raises below instead of silently reading os.environ.
        if api_key is None:
            from backend import config

            api_key = config.VOYAGE_API_KEY
        self._api_key = api_key
        if not self._api_key:
            raise EmbeddingProviderError(
                "VOYAGE_API_KEY is required when EASYAGENT_EMBEDDING_BACKEND=voyage"
            )
        try:
            import voyageai
        except ModuleNotFoundError as exc:
            raise EmbeddingProviderError(
                "Voyage embeddings require the optional voyageai package. "
                'Install it with `pip install "easyagent[rag]"`.'
            ) from exc
        self._client = voyageai.Client(api_key=self._api_key)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, input_type="document")

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], input_type="query")[0]

    def _embed(self, texts: list[str], *, input_type: str) -> list[list[float]]:
        # Retry with exponential backoff on rate-limit errors. The Voyage free
        # tier (no payment method) allows only 3 requests/min and 10K tokens/min,
        # so a build fires faster than the limit and must wait out the window.
        from voyageai.error import RateLimitError

        delay = 20.0
        for attempt in range(6):
            try:
                response = self._client.embed(
                    texts, model=self.model, input_type=input_type
                )
                return [
                    [float(value) for value in embedding]
                    for embedding in response.embeddings
                ]
            except RateLimitError:
                if attempt >= 5:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 120.0)
        raise RuntimeError("unreachable")  # pragma: no cover


_LOCAL_DIMS = {
    "BAAI/bge-small-en-v1.5": 384,
    "bge-small-en-v1.5": 384,
    "all-MiniLM-L6-v2": 384,
}


class LocalEmbeddingProvider:
    backend = "local"

    def __init__(
        self,
        *,
        model: str = "BAAI/bge-small-en-v1.5",
        dim: int | None = None,
    ) -> None:
        self.model = model
        self.dim = dim or _LOCAL_DIMS.get(model, 384)
        self._model_obj = None

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._encode(texts)

    def embed_query(self, text: str) -> list[float]:
        return self._encode([text])[0]

    def _model(self):
        if self._model_obj is not None:
            return self._model_obj
        try:
            from sentence_transformers import SentenceTransformer
        except ModuleNotFoundError as exc:
            raise EmbeddingProviderError(
                "Local embeddings require sentence-transformers. "
                'Install it with `pip install "easyagent[rag-local]"`.'
            ) from exc
        self._model_obj = SentenceTransformer(self.model)
        actual_dim = self._model_obj.get_sentence_embedding_dimension()
        if actual_dim:
            self.dim = int(actual_dim)
        return self._model_obj

    def _encode(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model().encode(texts, normalize_embeddings=True)
        return [[float(value) for value in vector] for vector in vectors]


def get_embedding_provider(
    backend: str | None = None,
    model: str | None = None,
) -> EmbeddingProvider:
    """Create the configured embedding provider."""
    from backend import config

    selected_backend = (backend or config.EMBEDDING_BACKEND or "voyage").strip().lower()
    selected_model = (model or config.EMBEDDING_MODEL or "").strip()

    if selected_backend == "fake":
        return FakeEmbeddingProvider(model=selected_model or None)
    if selected_backend == "voyage":
        return VoyageEmbeddingProvider(
            model=selected_model or "voyage-3-large",
            api_key=config.VOYAGE_API_KEY,
        )
    if selected_backend == "local":
        return LocalEmbeddingProvider(model=selected_model or "BAAI/bge-small-en-v1.5")
    raise EmbeddingProviderError(f"unknown embedding backend: {selected_backend}")


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vec))
    if norm <= 0:
        return vec
    return [value / norm for value in vec]
