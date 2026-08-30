from __future__ import annotations

from provenance.config import Settings, get_settings
from provenance.embeddings.base import Embedder, EmbeddingError
from provenance.embeddings.hashing import HashingEmbedder
from provenance.embeddings.openai_compat import OpenAICompatEmbedder

__all__ = ["Embedder", "EmbeddingError", "HashingEmbedder", "OpenAICompatEmbedder", "build_embedder"]


def build_embedder(settings: Settings | None = None) -> Embedder:
    settings = settings or get_settings()
    provider = settings.embedding_provider.lower()
    if provider == "hashing":
        return HashingEmbedder(dim=settings.embedding_dim)
    if provider in {"openai", "ollama", "vllm", "openai_compat"}:
        return OpenAICompatEmbedder(
            base_url=settings.embedding_base_url,
            model=settings.embedding_model,
            dim=settings.embedding_dim,
            api_key=settings.embedding_api_key,
            allow_insecure_http=settings.llm_allow_insecure_http,
        )
    raise ValueError(f"unbekannter Einbettungsanbieter: {settings.embedding_provider!r}")
