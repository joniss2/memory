"""Stufe 4 -- Injection.

Meist übersehen, regelmäßig schuldig: ein Fakt kann korrekt extrahiert,
korrekt gespeichert und korrekt gefunden worden sein -- und fällt an Rang 9
aus dem Budget. Ohne diesen Trace-Punkt sucht man den Fehler an drei
falschen Stellen (Abschnitt 5, Stufe 4).
"""

from __future__ import annotations

import time

from provenance.config import Settings
from provenance.llm.base import estimate_tokens
from provenance.pipeline.types import Injection, RetrievedFact
from provenance.trace import STAGE_INJECT, TraceRecorder

HEADER = "Bekanntes über die Person:"


def inject(
    *,
    settings: Settings,
    recorder: TraceRecorder,
    facts: list[RetrievedFact],
    token_budget: int | None = None,
) -> Injection:
    budget = token_budget if token_budget is not None else settings.injection_token_budget
    started = time.perf_counter()

    included: list[RetrievedFact] = []
    dropped: list[dict[str, object]] = []
    used = estimate_tokens(HEADER)

    for rank, fact in enumerate(facts, start=1):
        line = _render_line(fact)
        cost = estimate_tokens(line)
        if used + cost > budget:
            dropped.append(
                {
                    "fact_id": fact.fact_id,
                    "rank": rank,
                    "content": fact.content,
                    "tokens": cost,
                    "reason": f"Budget erschöpft ({used}/{budget} Token belegt)",
                }
            )
            continue
        included.append(fact)
        used += cost

    text = "\n".join([HEADER, *[_render_line(fact) for fact in included]]) if included else ""

    duration_ms = int((time.perf_counter() - started) * 1000)
    recorder.step(
        STAGE_INJECT,
        duration_ms=duration_ms,
        input={
            "token_budget": budget,
            "ranked": [
                {"fact_id": fact.fact_id, "rank": rank, "score": round(fact.score, 6)}
                for rank, fact in enumerate(facts, start=1)
            ],
        },
        output={
            "text": text,
            "included": [fact.fact_id for fact in included],
            # Der eigentliche Zweck dieses Schritts: was war da und kam nicht mit?
            "dropped": dropped,
            "tokens_used": used,
        },
        tokens_out=used,
    )
    return Injection(
        text=text, included=included, dropped=dropped, tokens_used=used, token_budget=budget
    )


def _render_line(fact: RetrievedFact) -> str:
    stamp = fact.valid_from.date().isoformat() if fact.valid_from else "?"
    return f"- {fact.content} (seit {stamp}, Fakt {fact.fact_id})"
