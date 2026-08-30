"""OpenAI-kompatible Schnittstelle -- deckt OpenAI, Ollama (/v1) und vLLM ab."""

from __future__ import annotations

import time
from typing import Any

import httpx

from provenance.llm.base import LLMError, LLMRequest, LLMResponse, estimate_tokens


class OpenAICompatProvider:
    name = "openai"

    def __init__(
        self,
        base_url: str,
        api_key: str = "",
        timeout_s: float = 120.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client = client
        self._owns_client = client is None

    def _http(self) -> httpx.Client:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.Client(timeout=self.timeout_s, headers=headers)
        return self._client

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def complete(self, request: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {
            "model": request.model,
            "temperature": request.temperature,
            "messages": [
                {"role": "system", "content": request.system},
                {"role": "user", "content": request.user},
            ],
            # Beide Stufen liefern JSON. Anbieter, die den Parameter nicht
            # kennen, ignorieren ihn; der Parser in base.py fängt den Rest.
            "response_format": {"type": "json_object"},
        }
        if request.max_tokens is not None:
            body["max_tokens"] = request.max_tokens

        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self._http().post(f"{self.base_url}/chat/completions", json=body)
                if response.status_code >= 500 or response.status_code == 429:
                    raise LLMError(f"HTTP {response.status_code}: {response.text[:200]}")
                response.raise_for_status()
                data = response.json()
                break
            except (httpx.HTTPError, LLMError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise LLMError(f"Modellaufruf fehlgeschlagen: {exc}") from exc
                time.sleep(min(2.0**attempt, 8.0))
        else:  # pragma: no cover - die Schleife bricht immer über break/raise
            raise LLMError(f"Modellaufruf fehlgeschlagen: {last_error}")

        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError(f"unerwartete Antwortstruktur: {str(data)[:200]}") from exc

        usage = data.get("usage") or {}
        return LLMResponse(
            text=text,
            model=data.get("model", request.model),
            tokens_in=int(usage.get("prompt_tokens") or estimate_tokens(request.system + request.user)),
            tokens_out=int(usage.get("completion_tokens") or estimate_tokens(text)),
            raw=data,
        )
