from __future__ import annotations

from provenance.config import Settings, get_settings
from provenance.llm.base import (
    LLMError,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    estimate_tokens,
    parse_json_object,
)
from provenance.llm.heuristic import HeuristicProvider
from provenance.llm.naive import NaiveProvider
from provenance.llm.openai_compat import OpenAICompatProvider
from provenance.llm.scripted import ScriptedProvider

__all__ = [
    "HeuristicProvider",
    "LLMError",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "NaiveProvider",
    "OpenAICompatProvider",
    "ScriptedProvider",
    "build_llm",
    "estimate_tokens",
    "parse_json_object",
]


def build_llm(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    provider = settings.llm_provider.lower()
    if provider == "heuristic":
        return HeuristicProvider()
    if provider == "naive":
        # Vergleichsmaßstab, kein Betriebsmodus. Siehe provenance.llm.naive.
        return NaiveProvider()
    if provider in {"openai", "ollama", "vllm", "openai_compat"}:
        return OpenAICompatProvider(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            timeout_s=settings.llm_timeout_s,
            max_retries=settings.llm_max_retries,
        )
    if provider == "scripted":
        return ScriptedProvider()
    raise ValueError(f"unbekannter Modellanbieter: {settings.llm_provider!r}")
