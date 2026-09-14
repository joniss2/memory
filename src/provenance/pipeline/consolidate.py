"""Stufe 2 -- Konsolidierung.

„Hier bricht jedes System, und hier misst niemand." (Abschnitt 5, Stufe 2)

Zwei Härtungen sind hier in Code gegossen, nicht in den Prompt:

1. Ein Widerspruch ist ein eigener Ausgang, keine stille Überschreibung. Der
   abgelöste Fakt bekommt ``superseded`` und bleibt mit Zeitstempel und
   Begründung abrufbar.
2. Rückzug verlangt mehr Konfidenz als Hinzufügen. Die Schwelle ist
   asymmetrisch, und sie wird nach dem Modellaufruf angewandt -- ein Modell,
   das zu gern vergisst, kann sie nicht umreden. Wird eine Entscheidung
   überstimmt, steht die ursprünglich vorgeschlagene in
   ``lineage.proposed_op``.
"""

from __future__ import annotations

import json
import time
from contextlib import suppress
from datetime import datetime
from typing import Any

import psycopg

from provenance.config import Settings
from provenance.embeddings.base import Embedder
from provenance.graph import materialise_triple
from provenance.llm.base import LLMError, LLMProvider, LLMRequest, parse_json_object
from provenance.pipeline.types import DECISIONS, AppliedDecision, Candidate, Decision
from provenance.prompts import load_prompt
from provenance.store import (
    close_edges_for_facts,
    close_fact,
    insert_fact,
    insert_lineage,
    neighbours_for_candidate,
)
from provenance.trace import STAGE_CONSOLIDATE, TraceRecorder

PROMPT_NAME = "consolidate.v1"


def consolidate(
    conn: psycopg.Connection,
    *,
    llm: LLMProvider,
    embedder: Embedder,
    settings: Settings,
    recorder: TraceRecorder,
    subject_id: str,
    candidate: Candidate,
    turn: dict[str, Any],
    tx_time: datetime,
    subject_label: str | None = None,
) -> AppliedDecision:
    label = subject_label or subject_id
    embedding = embedder.embed([candidate.content])[0]

    neighbours = neighbours_for_candidate(
        conn,
        subject_id=subject_id,
        embedding=embedding,
        limit=settings.consolidate_neighbours,
        predicates=candidate.match_predicates,
        terms=candidate.match_terms,
    )
    relevant = [
        neighbour
        for neighbour in neighbours
        if neighbour.get("matched_by") != "vector"
        or (neighbour.get("similarity") or 0.0) >= settings.consolidate_similarity_floor
    ]

    prompt = load_prompt(PROMPT_NAME)
    started = time.perf_counter()
    error: str | None = None
    raw_text = ""
    model_name = settings.llm_model_consolidate
    tokens_in = tokens_out = 0
    skipped_reason: str | None = None

    if not relevant:
        # Abschnitt 10, Gegenmaßnahme zu den Kosten: Stufe 2 nur bei
        # Ähnlichkeitstreffern oberhalb einer Schwelle. Ohne Nachbarn gibt es
        # nichts zu konsolidieren -- der Kandidat ist neu.
        skipped_reason = (
            f"kein Nachbar über der Ähnlichkeitsschwelle "
            f"{settings.consolidate_similarity_floor}; Modellaufruf gespart"
        )
        decision = Decision(
            op="add",
            target_fact_ids=[],
            rationale="Kein vergleichbarer Fakt vorhanden.",
            confidence=candidate.confidence,
        )
        model_name = "(kein Aufruf)"
    else:
        system, user = prompt.render(
            subject_label=label,
            occurred_at=turn["occurred_at"].isoformat(),
            candidate=json.dumps(candidate.as_payload(), ensure_ascii=False, indent=2),
            neighbours=_format_neighbours(relevant),
        )
        payload = {
            "subject_id": subject_id,
            "subject_label": label,
            "candidate": candidate.as_payload(),
            "neighbours": [_neighbour_payload(item) for item in relevant],
        }
        try:
            response = llm.complete(
                LLMRequest(
                    task="consolidate",
                    system=system,
                    user=user,
                    model=settings.llm_model_consolidate,
                    payload=payload,
                )
            )
            raw_text = response.text
            model_name = response.model
            tokens_in, tokens_out = response.tokens_in, response.tokens_out
            decision = _coerce_decision(parse_json_object(raw_text), candidate)
        except LLMError as exc:
            error = str(exc)
            # Ein gescheiterter Modellaufruf darf nie zu einem Rückzug führen.
            decision = Decision(
                op="add",
                target_fact_ids=[],
                rationale=f"Konsolidierung nicht möglich ({exc}); Kandidat wird nur hinzugefügt.",
                confidence=candidate.confidence,
            )

    known_ids = {int(item["id"]) for item in relevant}
    decision = _apply_policy(decision, candidate, settings, known_ids)

    duration_ms = int((time.perf_counter() - started) * 1000)
    applied = _apply(
        conn,
        embedder=embedder,
        subject_id=subject_id,
        candidate=candidate,
        decision=decision,
        turn=turn,
        tx_time=tx_time,
        embedding=embedding,
        trace_id=recorder.trace_id,
    )

    recorder.step(
        STAGE_CONSOLIDATE,
        model=model_name,
        prompt_ref=prompt.ref,
        duration_ms=duration_ms,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        input={
            "candidate": candidate.as_payload(),
            "neighbours": [_neighbour_payload(item) for item in neighbours],
            "neighbours_considered": [int(item["id"]) for item in relevant],
            "similarity_floor": settings.consolidate_similarity_floor,
            "skipped_model_call": skipped_reason,
        },
        output={
            "error": error,
            "raw": raw_text[:8000],
            "decision": decision.op,
            "proposed_op": decision.proposed_op,
            "policy_note": decision.policy_note,
            "rationale": decision.rationale,
            "confidence": decision.confidence,
            "target_fact_ids": decision.target_fact_ids,
            "applied": applied.summary(),
            "thresholds": {
                "add": settings.add_min_confidence,
                "update": settings.update_min_confidence,
                "retract": settings.retract_min_confidence,
            },
        },
    )
    return applied


# ----------------------------------------------------------------- Richtlinie


def _apply_policy(
    decision: Decision, candidate: Candidate, settings: Settings, known_ids: set[int]
) -> Decision:
    """Die Härtungen aus Abschnitt 5, Stufe 2 -- nach dem Modell, nicht davor."""
    proposed = decision.op
    notes: list[str] = []

    targets = [fact_id for fact_id in decision.target_fact_ids if fact_id in known_ids]
    if len(targets) != len(decision.target_fact_ids):
        unknown = sorted(set(decision.target_fact_ids) - known_ids)
        notes.append(
            f"Nicht vorgelegte Fakt-IDs verworfen: {unknown}. "
            "Ein Modell darf nur über das entscheiden, was ihm gezeigt wurde."
        )
    op = decision.op

    if op in {"update", "retract", "merge", "noop"} and not targets:
        if op == "retract":
            notes.append("Rückzug ohne auffindbares Ziel; nichts zu tun.")
            op = "noop"
        elif op == "noop":
            notes.append("Kein Ziel benannt; Kandidat wird als neu behandelt.")
            op = "add"
        else:
            notes.append(f"„{op}" + "“ ohne gültiges Ziel; Kandidat wird hinzugefügt.")
            op = "add"

    if op == "retract" and decision.confidence < settings.retract_min_confidence:
        notes.append(
            f"Rückzug verlangt Konfidenz ≥ {settings.retract_min_confidence}, "
            f"vorgeschlagen war {decision.confidence:.2f}. Vergessen ist teurer als Erinnern -- "
            "der bestehende Fakt bleibt."
        )
        op, targets = "noop", targets[:1]
    elif op in {"update", "merge"} and decision.confidence < settings.update_min_confidence:
        notes.append(
            f"Ablösung verlangt Konfidenz ≥ {settings.update_min_confidence}, "
            f"vorgeschlagen war {decision.confidence:.2f}. Der Kandidat wird ergänzt, "
            "statt den bestehenden Fakt abzulösen."
        )
        op, targets = "add", []
    elif op == "add" and decision.confidence < settings.add_min_confidence:
        notes.append(
            f"Aufnahme verlangt Konfidenz ≥ {settings.add_min_confidence}, "
            f"vorgeschlagen war {decision.confidence:.2f}. Kandidat verworfen."
        )
        op, targets = "noop", []

    return Decision(
        op=op,
        target_fact_ids=targets,
        rationale=decision.rationale,
        confidence=decision.confidence,
        proposed_op=proposed if proposed != op else None,
        policy_note=" ".join(notes) or None,
    )


# ------------------------------------------------------------------ Anwendung


def _apply(
    conn: psycopg.Connection,
    *,
    embedder: Embedder,
    subject_id: str,
    candidate: Candidate,
    decision: Decision,
    turn: dict[str, Any],
    tx_time: datetime,
    embedding: list[float],
    trace_id: int,
) -> AppliedDecision:
    applied = AppliedDecision(decision=decision, candidate=candidate, fact_id=None)
    occurred_at: datetime = turn["occurred_at"]

    if decision.op == "noop":
        for target in decision.target_fact_ids:
            insert_lineage(
                conn,
                fact_id=target,
                parent_id=None,
                op="noop",
                rationale=decision.rationale,
                trace_id=trace_id,
                proposed_op=decision.proposed_op,
            )
        return applied

    if decision.op == "retract":
        for target in decision.target_fact_ids:
            closed = close_fact(
                conn, fact_id=target, status="retracted", at=tx_time, valid_to=occurred_at
            )
            if closed is not None:
                applied.retracted.append(target)
            insert_lineage(
                conn,
                fact_id=target,
                parent_id=None,
                op="retract",
                rationale=decision.rationale,
                trace_id=trace_id,
                proposed_op=decision.proposed_op,
            )
        applied.closed_edge_ids = close_edges_for_facts(
            conn, fact_ids=applied.retracted, at=occurred_at
        )
        return applied

    # add | update | merge legen alle einen neuen Fakt an. Nichts wird
    # überschrieben -- der abgelöste Fakt bleibt mit seinen Zeitstempeln stehen.
    fact = insert_fact(
        conn,
        subject_id=subject_id,
        content=candidate.content,
        embedding=embedding,
        valid_from=candidate.valid_from,
        confidence=candidate.confidence,
        origin_turn=turn["id"],
        triple=candidate.triple,
    )
    applied.fact_id = int(fact["id"])

    if decision.op == "add":
        insert_lineage(
            conn,
            fact_id=applied.fact_id,
            parent_id=None,
            op="add",
            rationale=decision.rationale,
            trace_id=trace_id,
            proposed_op=decision.proposed_op,
        )
    else:
        for target in decision.target_fact_ids:
            closed = close_fact(
                conn,
                fact_id=target,
                status="superseded",
                at=tx_time,
                valid_to=candidate.valid_from,
            )
            if closed is not None:
                applied.superseded.append(target)
            insert_lineage(
                conn,
                fact_id=applied.fact_id,
                parent_id=target,
                op=decision.op,
                rationale=decision.rationale,
                trace_id=trace_id,
                proposed_op=decision.proposed_op,
            )
        applied.closed_edge_ids = close_edges_for_facts(
            conn, fact_ids=applied.superseded, at=candidate.valid_from
        )

    edge_id = materialise_triple(
        conn,
        embedder=embedder,
        subject_id=subject_id,
        triple=candidate.triple,
        fact_id=applied.fact_id,
        valid_from=candidate.valid_from,
    )
    if edge_id is not None:
        applied.edge_ids.append(edge_id)
    return applied


# --------------------------------------------------------------------- Hilfen


def _coerce_decision(parsed: dict[str, Any], candidate: Candidate) -> Decision:
    op = str(parsed.get("op") or "").strip().lower()
    if op not in DECISIONS:
        return Decision(
            op="add",
            target_fact_ids=[],
            rationale=f"Unbrauchbare Entscheidung {op!r}; Kandidat wird hinzugefügt.",
            confidence=candidate.confidence,
        )
    targets: list[int] = []
    raw_targets = parsed.get("target_fact_ids")
    if isinstance(raw_targets, (list, tuple)):
        for value in raw_targets:
            try:
                targets.append(int(value))
            except (TypeError, ValueError):
                continue
    elif raw_targets is not None:
        with suppress(TypeError, ValueError):
            targets.append(int(raw_targets))

    try:
        confidence = min(1.0, max(0.0, float(parsed.get("confidence"))))
    except (TypeError, ValueError):
        confidence = candidate.confidence

    return Decision(
        op=op,
        target_fact_ids=list(dict.fromkeys(targets)),
        rationale=str(parsed.get("rationale") or "").strip()[:2000] or "(ohne Begründung)",
        confidence=confidence,
    )


def _neighbour_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "content": row["content"],
        "triple": row.get("triple"),
        "similarity": round(float(row["similarity"]), 4) if row.get("similarity") is not None else None,
        "status": row.get("status"),
        "valid_from": row["valid_from"].isoformat() if row.get("valid_from") else None,
        "matched_by": row.get("matched_by"),
    }


def _format_neighbours(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "(keine)"
    lines: list[str] = []
    for row in rows:
        similarity = row.get("similarity")
        marker = f"{similarity:.3f}" if similarity is not None else "--"
        triple = row.get("triple") or {}
        structure = (
            f" [{triple.get('src')} {triple.get('predicate')} {triple.get('dst')}]" if triple else ""
        )
        lines.append(
            f"- id={row['id']} (Ähnlichkeit {marker}, gültig ab "
            f"{row['valid_from'].isoformat() if row.get('valid_from') else '?'}): "
            f"{row['content']}{structure}"
        )
    return "\n".join(lines)
