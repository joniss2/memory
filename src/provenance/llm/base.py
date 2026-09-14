"""Schnittstelle zum Sprachmodell.

Die einzige externe Abhängigkeit des Systems (Abschnitt 3) und deshalb
bewusst schmal: ein Aufruf, eine Antwort, gezählte Token.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass(slots=True)
class LLMResponse:
    text: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    raw: dict[str, Any] | None = None


@dataclass(slots=True)
class LLMRequest:
    """Ein Pipeline-Schritt, der ein Modell fragt.

    ``payload`` trägt dieselben Daten wie ``user``, nur unformatiert. Echte
    Anbieter ignorieren es; der deterministische Ersatz aus
    :mod:`provenance.llm.heuristic` arbeitet darauf, statt seinen eigenen
    Prompt zurückzuparsen.
    """

    task: str  # extract | consolidate
    system: str
    user: str
    model: str
    payload: dict[str, Any] = field(default_factory=dict)
    temperature: float = 0.0
    max_tokens: int | None = None


@runtime_checkable
class LLMProvider(Protocol):
    name: str

    def complete(self, request: LLMRequest) -> LLMResponse: ...


class LLMError(RuntimeError):
    pass


_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


def parse_json_object(text: str) -> dict[str, Any]:
    """Holt ein JSON-Objekt aus einer Modellantwort.

    Modelle rahmen ihre Antwort gern in Codefences oder stellen einen Satz
    voran. Beides wird toleriert -- ein Parse-Fehler an dieser Stelle würde
    sonst einen ganzen Turn verwerfen.
    """
    candidate = text.strip()
    if not candidate:
        raise LLMError("leere Modellantwort")

    fenced = _FENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start == -1 or end <= start:
            raise LLMError(f"keine JSON-Struktur in der Antwort: {text[:200]!r}") from None
        try:
            parsed = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise LLMError(f"unlesbares JSON in der Antwort: {text[:200]!r}") from exc

    if not isinstance(parsed, dict):
        raise LLMError(f"JSON-Objekt erwartet, {type(parsed).__name__} erhalten")
    return parsed


def estimate_tokens(text: str) -> int:
    """Grobe Schätzung, wenn der Anbieter keine Nutzung meldet.

    Vier Zeichen je Token ist für europäische Sprachen brauchbar genau; die
    Zahl steuert nur das Budget in Stufe 4 und die Kostenanzeige, nichts
    Fachliches.
    """
    return max(1, (len(text) + 3) // 4)
