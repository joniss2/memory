"""Stufe 2: die Härtungen aus Abschnitt 5.

Diese Tests erzwingen bestimmte Modellentscheidungen über den vorgegebenen
Anbieter. Das ist der Punkt: die Richtlinie soll auch dann greifen, wenn das
Modell etwas anderes will.
"""

from __future__ import annotations

import json

import pytest

from provenance.llm.scripted import ScriptedProvider
from provenance.service import MemoryService
from provenance.store import all_facts, get_fact, lineage_for_fact
from tests.conftest import at


def extraction(content: str, *, predicate: str = "wohnt_in", dst: str = "Köln", confidence: float = 0.9):
    return {
        "facts": [
            {
                "content": content,
                "confidence": confidence,
                "op_hint": "assert",
                "triple": {
                    "src": "s", "src_kind": "person",
                    "predicate": predicate, "dst": dst, "dst_kind": "ort",
                },
            }
        ],
        "non_extractions": [],
    }


def decision(op: str, targets: list[int], confidence: float, rationale: str = "Testentscheidung"):
    return {"op": op, "target_fact_ids": targets, "confidence": confidence, "rationale": rationale}


@pytest.fixture
def scripted():
    provider = ScriptedProvider()
    return provider, MemoryService(llm=provider)


def seed(provider, service, content="Wohnt in Köln.", dst="Köln", when=None):
    provider.push(extraction(content, dst=dst))
    return service.ingest_turn(
        subject_id="s", session_id="t", role="user",
        content="egal, die Extraktion ist vorgegeben",
        occurred_at=when or at(1),
    )


def test_retract_below_threshold_is_downgraded_and_recorded(scripted, settings):
    """Vergessen ist teurer als Erinnern: unterhalb der Schwelle bleibt der Fakt."""
    provider, service = scripted
    first = seed(provider, service)
    fact_id = first.decisions[0].fact_id

    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    provider.push(decision("retract", [fact_id], confidence=settings.retract_min_confidence - 0.2))
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(6)
    )

    applied = result.decisions[0]
    assert applied.decision.op == "noop"
    assert applied.decision.proposed_op == "retract"
    assert "Vergessen ist teurer als Erinnern" in (applied.decision.policy_note or "")
    assert get_fact_status(fact_id) == "active"

    ops = [row["op"] for row in lineage_for_fact_rows(fact_id)]
    assert "noop" in ops
    proposed = [row["proposed_op"] for row in lineage_for_fact_rows(fact_id) if row["op"] == "noop"]
    assert proposed == ["retract"]


def test_retract_above_threshold_is_applied(scripted, settings):
    provider, service = scripted
    first = seed(provider, service)
    fact_id = first.decisions[0].fact_id

    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    provider.push(decision("retract", [fact_id], confidence=settings.retract_min_confidence + 0.1))
    service.ingest_turn(subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(6))

    assert get_fact_status(fact_id) == "retracted"


def test_update_below_threshold_becomes_add(scripted, settings):
    """Im Zweifel ergänzen statt ablösen -- der bestehende Fakt bleibt."""
    provider, service = scripted
    first = seed(provider, service)
    fact_id = first.decisions[0].fact_id

    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    provider.push(decision("update", [fact_id], confidence=settings.update_min_confidence - 0.2))
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(6)
    )

    assert result.decisions[0].decision.op == "add"
    assert result.decisions[0].decision.proposed_op == "update"
    assert get_fact_status(fact_id) == "active"


def test_update_supersedes_without_overwriting(scripted, settings):
    """Nichts wird überschrieben: der alte Fakt behält Inhalt und bekommt Endzeitpunkte."""
    provider, service = scripted
    first = seed(provider, service)
    old_id = first.decisions[0].fact_id

    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    provider.push(decision("update", [old_id], confidence=0.95))
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(6)
    )
    new_id = result.decisions[0].fact_id

    old = get_fact_row(old_id)
    assert old["content"] == "Wohnt in Köln."  # unverändert
    assert old["status"] == "superseded"
    assert old["invalidated_at"] is not None
    assert old["valid_to"] == at(6)

    rows = lineage_for_fact_rows(new_id)
    assert any(row["op"] == "update" and row["parent_id"] == old_id for row in rows)


def test_targets_the_model_never_saw_are_dropped(scripted):
    """Ein Modell darf nur über das entscheiden, was ihm vorgelegt wurde."""
    provider, service = scripted
    first = seed(provider, service)
    real_id = first.decisions[0].fact_id

    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    provider.push(decision("update", [real_id, 9999], confidence=0.95))
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(6)
    )

    applied = result.decisions[0]
    assert applied.superseded == [real_id]
    assert "9999" in (applied.decision.policy_note or "")


def test_model_failure_never_retracts(scripted):
    """Ein gescheiterter Modellaufruf darf nie zu einem Rückzug führen."""
    provider, service = scripted
    first = seed(provider, service)
    fact_id = first.decisions[0].fact_id

    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    # Die Warteschlange ist jetzt leer -> der Konsolidierungsaufruf wirft.
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(6)
    )

    assert result.decisions[0].decision.op == "add"
    assert get_fact_status(fact_id) == "active"


def test_unparseable_decision_falls_back_to_add(scripted):
    provider, service = scripted
    seed(provider, service)
    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    provider.push("das ist kein JSON")
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(6)
    )
    assert result.decisions[0].decision.op == "add"


def test_no_neighbours_skips_the_model_call(scripted):
    """Abschnitt 10: Stufe 2 nur bei Ähnlichkeitstreffern oberhalb einer Schwelle."""
    provider, service = scripted
    result = seed(provider, service)
    assert provider.calls[-1].task == "extract"
    assert len(provider.calls) == 1
    step = consolidation_step(result.trace_id)
    assert step["input"]["skipped_model_call"] is not None
    assert step["model"] == "(kein Aufruf)"


# ------------------------------------------------------------------- Helfer


def get_fact_status(fact_id: int) -> str:
    return get_fact_row(fact_id)["status"]


def get_fact_row(fact_id: int):
    from provenance.db.pool import connection

    with connection() as conn:
        return get_fact(conn, fact_id)


def lineage_for_fact_rows(fact_id: int):
    from provenance.db.pool import connection

    with connection() as conn:
        return lineage_for_fact(conn, fact_id)


def consolidation_step(trace_id: int):
    from provenance.db.pool import connection
    from provenance.store import trace_steps

    with connection() as conn:
        return next(step for step in trace_steps(conn, trace_id) if step["stage"] == 2)


def test_all_facts_helper_sees_every_state(scripted):
    provider, service = scripted
    first = seed(provider, service)
    provider.push(extraction("Wohnt in Leipzig.", dst="Leipzig"))
    provider.push(decision("update", [first.decisions[0].fact_id], confidence=0.95))
    service.ingest_turn(subject_id="s", session_id="t", role="user", content="e", occurred_at=at(6))
    from provenance.db.pool import connection

    with connection() as conn:
        rows = all_facts(conn, subject_id="s")
    assert {row["status"] for row in rows} == {"superseded", "active"}
    assert json.loads(json.dumps([row["content"] for row in rows])) == [
        "Wohnt in Köln.", "Wohnt in Leipzig."
    ]
