"""Stufe 1: was gefunden wurde -- und was ausdrücklich nicht."""

from __future__ import annotations

from provenance.db.pool import connection
from provenance.llm.scripted import ScriptedProvider
from provenance.service import MemoryService
from provenance.store import trace_steps
from tests.conftest import at


def step_one(trace_id: int):
    with connection() as conn:
        return next(step for step in trace_steps(conn, trace_id) if step["stage"] == 1)


def test_non_extractions_are_recorded(ingest):
    """Ein leerer Extraktionsschritt ist ein Befund, keine Leerstelle."""
    result = ingest("Hallo! Wie geht es dir?", at(1))
    assert result.extraction.candidates == []
    reasons = [item.reason for item in result.extraction.non_extractions]
    assert len(reasons) == 2
    output = step_one(result.trace_id)["output"]
    assert len(output["non_extractions"]) == 2
    assert output["candidate_count"] == 0


def test_raw_model_answer_is_kept(ingest):
    """Ohne die rohe Antwort lässt sich später nicht unterscheiden, ob das
    Modell nichts fand oder der Parser etwas verwarf."""
    result = ingest("Ich wohne in Köln.", at(1))
    assert '"facts"' in step_one(result.trace_id)["output"]["raw"]


def test_prompt_version_is_recorded(ingest):
    result = ingest("Ich wohne in Köln.", at(1))
    assert step_one(result.trace_id)["prompt_ref"].startswith("extract.v1@")


def test_context_turns_are_referenced(ingest):
    ingest("Ich wohne in Köln.", at(1))
    second = ingest("Ich arbeite bei ACME.", at(2))
    assert step_one(second.trace_id)["input"]["context_turns"] == 1


def test_malformed_candidates_are_discarded_with_reason():
    provider = ScriptedProvider(
        [
            {
                "facts": [
                    {"content": "Wohnt in Köln.", "confidence": 0.9},
                    {"content": "", "confidence": 0.9},
                    {"content": "Wohnt in Köln.", "confidence": 0.9},
                    {"content": "x" * 900, "confidence": 0.9},
                    "kein Objekt",
                ],
                "non_extractions": [],
            }
        ]
    )
    service = MemoryService(llm=provider)
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(1)
    )
    assert len(result.extraction.candidates) == 1
    reasons = {item.reason for item in result.extraction.discarded}
    assert "leerer Inhalt" in reasons
    assert "Dublette innerhalb desselben Turns" in reasons
    assert any("Zeichen" in reason for reason in reasons)
    assert "kein Objekt" in reasons


def test_out_of_range_confidence_is_clamped():
    provider = ScriptedProvider(
        [{"facts": [{"content": "Wohnt in Köln.", "confidence": 7.5}], "non_extractions": []}]
    )
    service = MemoryService(llm=provider)
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="user", content="egal", occurred_at=at(1)
    )
    assert result.extraction.candidates[0].confidence == 1.0


def test_validity_time_is_taken_from_the_sentence(ingest):
    """„seit März" ist der Gültigkeitsbeginn, nicht der Zeitpunkt der Aussage."""
    result = ingest("Ich bin seit März Vegetarier.", at(5))
    candidate = result.extraction.candidates[0]
    assert candidate.valid_from.month == 3
    assert candidate.valid_from < at(5)


def test_assistant_turns_do_not_yield_facts_about_the_subject(service):
    result = service.ingest_turn(
        subject_id="s", session_id="t", role="assistant",
        content="Du wohnst in Köln.", occurred_at=at(1),
    )
    assert result.extraction.candidates == []
    assert result.extraction.non_extractions
