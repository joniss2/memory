"""Stufe 1 -- Extraktion.

Der wichtigste Trace-Punkt im ganzen System: wenn ein Agent etwas „vergessen"
hat, wurde es meist hier nie extrahiert (Abschnitt 5, Stufe 1). Deshalb landet
auch das Nichtgefundene in der Spur -- ein leerer Extraktionsschritt ist ein
Befund, keine Leerstelle.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import psycopg

from provenance.config import Settings
from provenance.embeddings.base import Embedder
from provenance.llm.base import LLMError, LLMProvider, LLMRequest, parse_json_object
from provenance.pipeline.types import Candidate, Discarded, ExtractionResult
from provenance.prompts import load_prompt
from provenance.store import context_turns
from provenance.trace import STAGE_EXTRACT, TraceRecorder

MAX_CONTENT_CHARS = 500
PROMPT_NAME = "extract.v1"


def extract(
    conn: psycopg.Connection,
    *,
    llm: LLMProvider,
    embedder: Embedder,
    settings: Settings,
    recorder: TraceRecorder,
    turn: dict[str, Any],
    subject_label: str | None = None,
) -> ExtractionResult:
    subject_id: str = turn["subject_id"]
    label = subject_label or subject_id
    occurred_at: datetime = turn["occurred_at"]

    history = context_turns(
        conn,
        subject_id=subject_id,
        session_id=turn["session_id"],
        before_turn_id=turn["id"],
        limit=settings.extract_context_turns,
    )
    context_text = _format_context(history)

    prompt = load_prompt(PROMPT_NAME)
    system, user = prompt.render(
        subject_label=label,
        occurred_at=occurred_at.isoformat(),
        context=context_text or "(keiner)",
        role=turn["role"],
        content=turn["content"],
    )

    payload = {
        "subject_id": subject_id,
        "subject_label": label,
        "turn": {
            "id": turn["id"],
            "role": turn["role"],
            "content": turn["content"],
            "occurred_at": occurred_at.isoformat(),
        },
        "context": history,
    }

    started = time.perf_counter()
    error: str | None = None
    raw_text = ""
    parsed: dict[str, Any] = {}
    model_name = settings.llm_model_extract

    try:
        response = llm.complete(
            LLMRequest(
                task="extract",
                system=system,
                user=user,
                model=settings.llm_model_extract,
                payload=payload,
            )
        )
        raw_text = response.text
        model_name = response.model
        tokens_in, tokens_out = response.tokens_in, response.tokens_out
        parsed = parse_json_object(raw_text)
    except LLMError as exc:
        error = str(exc)
        tokens_in = tokens_out = 0

    duration_ms = int((time.perf_counter() - started) * 1000)

    candidates, non_extractions, discarded = _coerce(parsed, occurred_at, label)

    step_id = recorder.step(
        STAGE_EXTRACT,
        model=model_name,
        prompt_ref=prompt.ref,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        input={
            "turn_id": turn["id"],
            "role": turn["role"],
            "content": turn["content"],
            "context_turn_ids": [item["id"] for item in history],
            "context_turns": len(history),
        },
        output={
            "error": error,
            # Die rohe Modellantwort. Ohne sie ist im Nachhinein nicht zu
            # unterscheiden, ob das Modell nichts gefunden oder der Parser
            # etwas verworfen hat.
            "raw": raw_text[:8000],
            "candidates": [candidate.as_payload() for candidate in candidates],
            "non_extractions": [
                {"text": item.text, "reason": item.reason} for item in non_extractions
            ],
            "discarded": [{"text": item.text, "reason": item.reason} for item in discarded],
            "candidate_count": len(candidates),
        },
    )

    return ExtractionResult(
        candidates=candidates,
        non_extractions=non_extractions,
        discarded=discarded,
        step_id=step_id,
        prompt_ref=prompt.ref,
        model=model_name,
    )


def _format_context(history: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for item in history:
        content = "(gelöscht)" if item.get("redacted_at") else item["content"]
        lines.append(f"[{item['occurred_at'].isoformat()}] {item['role']}: {content}")
    return "\n".join(lines)


def _coerce(
    parsed: dict[str, Any], occurred_at: datetime, label: str
) -> tuple[list[Candidate], list[Discarded], list[Discarded]]:
    """Übersetzt die Modellantwort in Kandidaten und protokolliert Verworfenes.

    Modelle liefern gelegentlich Unbrauchbares. Was hier ausgesondert wird,
    verschwindet nicht still, sondern steht mit Grund im Trace -- sonst wäre
    der Unterschied zwischen „nicht erkannt" und „aussortiert" später nicht
    mehr feststellbar.
    """
    candidates: list[Candidate] = []
    discarded: list[Discarded] = []
    non_extractions: list[Discarded] = []
    seen: set[str] = set()

    for item in _as_list(parsed.get("non_extractions")):
        if isinstance(item, dict):
            non_extractions.append(
                Discarded(
                    text=str(item.get("text") or "")[:MAX_CONTENT_CHARS],
                    reason=str(item.get("reason") or "ohne Begründung")[:500],
                )
            )
        elif isinstance(item, str):
            non_extractions.append(Discarded(text=item[:MAX_CONTENT_CHARS], reason="ohne Begründung"))

    for item in _as_list(parsed.get("facts")):
        if not isinstance(item, dict):
            discarded.append(Discarded(text=str(item)[:200], reason="kein Objekt"))
            continue

        content = str(item.get("content") or "").strip()
        if not content:
            discarded.append(Discarded(text=str(item)[:200], reason="leerer Inhalt"))
            continue
        if len(content) > MAX_CONTENT_CHARS:
            discarded.append(
                Discarded(text=content[:200], reason=f"länger als {MAX_CONTENT_CHARS} Zeichen")
            )
            continue

        key = content.casefold()
        if key in seen:
            discarded.append(Discarded(text=content, reason="Dublette innerhalb desselben Turns"))
            continue
        seen.add(key)

        op_hint = str(item.get("op_hint") or "assert").lower()
        if op_hint not in {"assert", "retract"}:
            op_hint = "assert"

        triple = _coerce_triple(item.get("triple"), label)
        confidence = _coerce_confidence(item.get("confidence"))
        valid_from = _coerce_datetime(item.get("valid_from")) or occurred_at

        candidates.append(
            Candidate(
                content=content,
                confidence=confidence,
                valid_from=valid_from,
                op_hint=op_hint,
                triple=triple,
                match_predicates=[str(p) for p in _as_list(item.get("match_predicates"))][:12],
                match_terms=[str(t) for t in _as_list(item.get("match_terms"))][:12],
                temporary=bool(item.get("temporary")),
                source_text=str(item.get("source_text") or "")[:MAX_CONTENT_CHARS],
            )
        )

    return candidates, non_extractions, discarded


def _coerce_triple(value: Any, label: str) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    predicate = str(value.get("predicate") or "").strip()
    dst = str(value.get("dst") or "").strip()
    if not predicate or not dst:
        return None
    src = str(value.get("src") or label).strip() or label
    return {
        "src": src[:200],
        "src_kind": _optional_str(value.get("src_kind")),
        "predicate": predicate[:80],
        "dst": dst[:200],
        "dst_kind": _optional_str(value.get("dst_kind")),
    }


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:80] or None


def _coerce_confidence(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.5
    return min(1.0, max(0.0, number))


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip().replace("Z", "+00:00")
    for candidate in (text, f"{text}T00:00:00+00:00"):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]
