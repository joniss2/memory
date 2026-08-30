"""Vorgegebene Antworten. Für Tests, die eine bestimmte Modellentscheidung
erzwingen wollen, ohne ein Modell zu brauchen."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from typing import Any

from provenance.llm.base import LLMError, LLMRequest, LLMResponse, estimate_tokens


class ScriptedProvider:
    name = "scripted"

    def __init__(self, responses: Iterable[Any] | None = None) -> None:
        self._queue: deque[Any] = deque(responses or ())
        self.calls: list[LLMRequest] = []

    def push(self, response: Any) -> None:
        self._queue.append(response)

    def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if not self._queue:
            raise LLMError(f"keine vorgegebene Antwort mehr für task={request.task!r}")
        item = self._queue.popleft()
        text = item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)
        return LLMResponse(
            text=text,
            model=request.model,
            tokens_in=estimate_tokens(request.system + request.user),
            tokens_out=estimate_tokens(text),
        )
