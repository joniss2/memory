"""Einbettungen über eine OpenAI-kompatible Schnittstelle (OpenAI, Ollama, vLLM)."""

from __future__ import annotations

import math
import time
from collections.abc import Sequence

import httpx

from provenance.config import require_secure_transport
from provenance.embeddings.base import EmbeddingError


class OpenAICompatEmbedder:
    name = "openai"

    def __init__(
        self,
        base_url: str,
        model: str,
        dim: int = 1024,
        api_key: str = "",
        timeout_s: float = 60.0,
        max_retries: int = 2,
        client: httpx.Client | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        # Dieselbe Prüfung wie bei der Textgenerierung: der einzubettende Text
        # ist der Gesprächsinhalt der betroffenen Person, nicht weniger
        # schutzbedürftig, nur weil am Ende ein Vektor zurückkommt.
        require_secure_transport(self.base_url, allow_insecure=allow_insecure_http)
        self.model = model
        self.dim = dim
        self.api_key = api_key
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self._client = client

    def _http(self) -> httpx.Client:
        if self._client is None:
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.Client(timeout=self.timeout_s, headers=headers)
        return self._client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        body = {"model": self.model, "input": list(texts), "dimensions": self.dim}
        last_error: Exception | str | None = None
        dimensions_dropped = False
        attempt = 0
        data = None
        while attempt <= self.max_retries:
            try:
                response = self._http().post(f"{self.base_url}/embeddings", json=body)
                if (
                    response.status_code == 400
                    and "dimensions" in body
                    and "dimensions" in response.text
                    and not dimensions_dropped
                ):
                    # Nicht jeder Anbieter kennt den Parameter; ohne ihn muss
                    # das Modell von sich aus die konfigurierte Weite liefern.
                    # Das kostet bewusst keinen Versuch: sonst scheiterte der
                    # Rückfall genau dann, wenn er im letzten Anlauf nötig wird.
                    last_error = response.text[:200]
                    body.pop("dimensions", None)
                    dimensions_dropped = True
                    continue
                response.raise_for_status()
                data = response.json()
                break
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    raise EmbeddingError(f"Einbettung fehlgeschlagen: {exc}") from exc
                time.sleep(min(2.0**attempt, 8.0))
            attempt += 1
        if data is None:
            raise EmbeddingError(f"Einbettung fehlgeschlagen: {last_error}")

        try:
            rows = sorted(data["data"], key=lambda item: item.get("index", 0))
            vectors = [[float(v) for v in row["embedding"]] for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError(f"unerwartete Antwortstruktur: {str(data)[:200]}") from exc

        for vector in vectors:
            if len(vector) != self.dim:
                raise EmbeddingError(
                    f"Modell {self.model!r} liefert {len(vector)} Dimensionen, "
                    f"das Schema erwartet {self.dim}. PROVENANCE_EMBEDDING_DIM anpassen "
                    "und neu migrieren, oder ein passendes Modell wählen."
                )
        return [_l2(v) for v in vectors]


def _l2(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vector))
    return vector if norm == 0.0 else [v / norm for v in vector]
