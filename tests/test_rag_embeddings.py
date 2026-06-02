from __future__ import annotations

import pytest

from backend.rag.embeddings import (
    EmbeddingProviderError,
    FakeEmbeddingProvider,
    get_embedding_provider,
)


def test_fake_embedding_provider_is_deterministic() -> None:
    provider = FakeEmbeddingProvider()

    a = provider.embed_query("portable profile retrieval")
    b = provider.embed_query("portable profile retrieval")
    c = provider.embed_query("coffee menu policy")

    assert provider.backend == "fake"
    assert provider.model == "fake-64d"
    assert provider.dim == 64
    assert a == b
    assert a != c
    assert len(a) == 64


def test_fake_embed_documents_matches_query_embedding() -> None:
    provider = FakeEmbeddingProvider(dim=8)

    docs = provider.embed_documents(["alpha", "beta"])

    assert docs[0] == provider.embed_query("alpha")
    assert len(docs[0]) == 8
    assert len(docs[1]) == 8


def test_provider_factory_uses_configured_fake_backend(monkeypatch) -> None:
    from backend import config

    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "fake")
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "")

    provider = get_embedding_provider()

    assert isinstance(provider, FakeEmbeddingProvider)


def test_provider_factory_rejects_unknown_backend(monkeypatch) -> None:
    from backend import config

    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "unknown")

    with pytest.raises(EmbeddingProviderError, match="unknown embedding backend"):
        get_embedding_provider()


def test_voyage_provider_requires_api_key(monkeypatch) -> None:
    from backend import config

    monkeypatch.setattr(config, "EMBEDDING_BACKEND", "voyage")
    monkeypatch.setattr(config, "EMBEDDING_MODEL", "voyage-3-large")
    monkeypatch.setattr(config, "VOYAGE_API_KEY", "")

    with pytest.raises(EmbeddingProviderError, match="VOYAGE_API_KEY"):
        get_embedding_provider()
