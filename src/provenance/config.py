"""Konfiguration. Alles über Umgebungsvariablen mit dem Präfix PROVENANCE_."""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PROVENANCE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # -- Ablage -----------------------------------------------------------
    database_url: str = "postgresql://provenance:provenance@localhost:5432/provenance"
    embedding_dim: int = 1024
    pool_min_size: int = 1
    pool_max_size: int = 8

    # Textsuchkonfiguration für facts.content_tsv. 'simple' ist bewusst die
    # Vorgabe: die Volltextquelle trägt in der Fusion Eigennamen und Zahlen
    # bei (Abschnitt 5, Stufe 3), und dort schadet Stemming eher, als es
    # nützt. Wer überwiegend deutschen Fließtext ablegt, setzt 'german' --
    # danach ist ein Reindex der bestehenden Fakten nötig.
    fts_config: str = "simple"

    # -- LLM --------------------------------------------------------------
    # 'openai' spricht jede OpenAI-kompatible Schnittstelle an, also auch
    # Ollama (/v1) und vLLM. 'heuristic' ist der deterministische Ersatz für
    # Läufe ohne Modell.
    llm_provider: str = "heuristic"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_model_extract: str = "qwen2.5:7b-instruct"
    llm_model_consolidate: str = "qwen2.5:7b-instruct"
    llm_timeout_s: float = 120.0
    llm_max_retries: int = 2

    # -- Embeddings -------------------------------------------------------
    # 'hashing' ist deterministisch und ohne Netz nutzbar; 'openai' spricht
    # dieselbe kompatible Schnittstelle wie oben an.
    embedding_provider: str = "hashing"
    embedding_base_url: str = "http://localhost:11434/v1"
    embedding_api_key: str = ""
    embedding_model: str = "bge-m3"

    # -- Stufe 1: Extraktion ----------------------------------------------
    extract_context_turns: int = 6

    # -- Stufe 2: Konsolidierung ------------------------------------------
    consolidate_neighbours: int = 8
    # Nur oberhalb dieser Ähnlichkeit wird überhaupt konsolidiert; darunter
    # ist der Kandidat neu (Abschnitt 10, Gegenmaßnahme zu den Kosten).
    consolidate_similarity_floor: float = 0.35
    add_min_confidence: float = 0.35
    # Vergessen ist teurer als Erinnern: die Schwelle ist asymmetrisch
    # (Abschnitt 5, Stufe 2, Härtung 2).
    retract_min_confidence: float = 0.75
    update_min_confidence: float = 0.55

    # -- Stufe 3: Retrieval ------------------------------------------------
    retrieval_limit: int = 12
    retrieval_candidates_per_source: int = 24
    rrf_k: int = 60
    graph_hops: int = 2

    # -- Stufe 4: Injection ------------------------------------------------
    injection_token_budget: int = 512

    # -- Aufbewahrung ------------------------------------------------------
    # Abschnitt 10: Traces nach 30 Tagen auf Metadaten reduzieren, Lineage
    # unbefristet halten.
    trace_retention_days: int = 30

    # -- Server ------------------------------------------------------------
    host: str = "0.0.0.0"
    port: int = 8080
    dashboard_enabled: bool = True

    api_token: str = Field(
        default="",
        description="Wenn gesetzt, verlangt die HTTP-API Bearer-Authentisierung.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
