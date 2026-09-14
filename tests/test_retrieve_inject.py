"""Stufen 3 und 4: Fusion und Budget."""

from __future__ import annotations

from provenance.db.pool import connection
from provenance.pipeline.retrieve import _reciprocal_rank_fusion
from provenance.store import build_tsquery, trace_steps
from tests.conftest import at


def steps(trace_id: int, stage: int):
    with connection() as conn:
        return next(step for step in trace_steps(conn, trace_id) if step["stage"] == stage)


def test_rrf_prefers_facts_found_by_several_sources():
    fused = _reciprocal_rank_fusion({"a": [1, 2], "b": [2, 3], "c": [2]}, k=60)
    assert fused[0][0] == 2


def test_rrf_is_stable_for_equal_scores():
    fused = _reciprocal_rank_fusion({"a": [7, 3], "b": [3, 7]}, k=60)
    assert [fact_id for fact_id, _ in fused] == [3, 7]


def test_tsquery_uses_or_semantics():
    """Mit UND-Verknüpfung liefert eine ganze Frage fast immer nichts."""
    assert build_tsquery("Wo wohnt er?") == "wo or wohnt or er"
    assert build_tsquery("") == ""


def test_trace_records_source_ranks(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich arbeite bei ACME.", at(2))
    result = service.recall(subject_id="s", query="Wo wohnt er?")

    output = steps(result.trace_id, 3)["output"]
    assert set(output["per_source"]) == {"vector", "fulltext", "graph"}
    assert output["fused"][0]["rank"] == 1
    assert output["fused"][0]["sources"]


def test_every_source_contributes(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    result = service.recall(subject_id="s", query="Wohnt Köln")
    output = steps(result.trace_id, 3)["output"]
    assert output["per_source"]["vector"], "Vektorquelle leer"
    assert output["per_source"]["fulltext"], "Volltextquelle leer"
    assert output["per_source"]["graph"], "Graphquelle leer"


def test_graph_source_finds_facts_via_entities(service, ingest):
    """Die Graphquelle trägt mehrstufige Bezüge bei -- über Knotennamen."""
    ingest("Ich arbeite bei ACME.", at(1))
    result = service.recall(subject_id="s", query="ACME")
    output = steps(result.trace_id, 3)["output"]
    assert output["per_source"]["graph"]
    assert steps(result.trace_id, 3)["input"]["graph_seeds"]


def test_injection_records_what_fell_out_of_budget(service, ingest):
    """Ein Fakt an Rang 9, der am Budget scheitert, muss sichtbar sein."""
    for month in range(1, 7):
        ingest(f"Ich mag Zutat{month}.", at(month))

    result = service.recall(subject_id="s", query="Was mag er?", token_budget=24)
    assert result.injection.dropped, "nichts als weggefallen protokolliert"
    dropped = result.injection.dropped[0]
    assert "Budget erschöpft" in dropped["reason"]
    assert dropped["rank"] >= 1

    output = steps(result.trace_id, 4)["output"]
    assert len(output["dropped"]) == len(result.injection.dropped)
    assert output["tokens_used"] <= 24


def test_injection_stays_within_budget(service, ingest):
    for month in range(1, 9):
        ingest(f"Ich mag Zutat{month}.", at(month))
    result = service.recall(subject_id="s", query="Was mag er?", token_budget=40)
    assert result.injection.tokens_used <= 40


def test_empty_memory_yields_empty_context(service):
    result = service.recall(subject_id="niemand", query="Wo wohnt er?")
    assert result.facts == []
    assert result.injection.text == ""


def test_recall_writes_a_read_trace(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    result = service.recall(subject_id="s", query="Wo wohnt er?")
    with connection() as conn:
        trace = conn.execute(
            "SELECT kind, query FROM traces WHERE id = %s", (result.trace_id,)
        ).fetchone()
    assert trace["kind"] == "read"
    assert trace["query"] == "Wo wohnt er?"
