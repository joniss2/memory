"""Löschung (Abschnitt 7) -- der Punkt, an dem sich Architekturen entscheiden."""

from __future__ import annotations

import pytest

from provenance import erasure
from provenance.db.pool import connection
from provenance.store import get_fact, trace_steps
from tests.conftest import at


def residue(needle: str, subject: str = "s") -> list[str]:
    from provenance.evals.runner import find_residue

    return find_residue(subject, needle)


def test_preview_includes_derived_facts(ingest):
    """Die transitive Hülle über lineage.parent_id, Abschnitt 7 Schritt 1."""
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich bin nach Leipzig gezogen.", at(6))

    with connection() as conn:
        plan = erasure.preview(conn, subject_id="s", fact_ids=[1])
    assert plan.roots == [1]
    assert plan.derived == [2]
    assert {item["content"] for item in plan.facts} == {"Wohnt in Köln.", "Wohnt in Leipzig."}


def test_preview_changes_nothing(ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        erasure.preview(conn, subject_id="s", fact_ids=[1])
        conn.commit()
        assert get_fact(conn, 1)["status"] == "active"
        assert get_fact(conn, 1)["content"] == "Wohnt in Köln."


def test_erasure_leaves_the_row_but_not_the_content(ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        erasure.execute(conn, subject_id="s", fact_ids=[1], reason="Test")
        conn.commit()
        row = conn.execute(
            "SELECT status, content, embedding, content_tsv, triple, erased_at "
            "FROM facts WHERE id = 1"
        ).fetchone()
    # Die leere Zeile bleibt bewusst stehen: sie belegt, dass gelöscht wurde.
    assert row is not None
    assert row["status"] == "erased"
    assert row["content"] == ""
    assert row["embedding"] is None
    # Ohne content_tsv fände die Volltextquelle den Fakt weiterhin.
    assert row["content_tsv"] is None
    assert row["triple"] is None
    assert row["erased_at"] is not None


def test_nothing_is_left_anywhere(ingest):
    """Fakten, Rohmaterial, Knoten und Auditlog -- überall nachgesehen."""
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich bin nach Leipzig gezogen.", at(6))
    with connection() as conn:
        erasure.execute(conn, subject_id="s", fact_ids=[1], reason="Test")
        conn.commit()

    for needle in ("Köln", "Leipzig", "gezogen"):
        assert residue(needle) == [], f"{needle} ist noch auffindbar"


def test_edges_are_closed(ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        erasure.execute(conn, subject_id="s", fact_ids=[1])
        conn.commit()
        open_edges = conn.execute(
            "SELECT count(*) AS n FROM edges WHERE valid_to IS NULL"
        ).fetchone()
    assert open_edges["n"] == 0


def test_trace_redaction_keeps_structure_and_timing(ingest):
    """Abschnitt 7 Schritt 5: Werte gehen, Struktur und Zeitstempel bleiben."""
    result = ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        before = next(s for s in trace_steps(conn, result.trace_id) if s["stage"] == 1)
        erasure.execute(conn, subject_id="s", fact_ids=[1])
        conn.commit()
        after = next(s for s in trace_steps(conn, result.trace_id) if s["stage"] == 1)

    assert after["redacted_at"] is not None
    assert after["duration_ms"] == before["duration_ms"]
    assert after["prompt_ref"] == before["prompt_ref"]
    # Schlüssel und Verschachtelung bleiben, Blätter sind leer.
    assert set(after["output"]) == set(before["output"])
    assert after["output"]["candidates"][0]["content"] is None
    assert set(after["output"]["candidates"][0]) == set(before["output"]["candidates"][0])


def test_redact_json_preserves_shape():
    payload = {"a": [{"b": "geheim", "c": 3}], "d": None, "e": {"f": True}}
    assert erasure.redact_json(payload) == {"a": [{"b": None, "c": None}], "d": None, "e": {"f": None}}


def test_subject_erasure_also_clears_raw_turns(ingest):
    """Der Ursprungstext ist die unmittelbarste personenbezogene Ablage."""
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        erasure.execute(conn, subject_id="s", reason="Auskunftsbegehren")
        conn.commit()
        turn = conn.execute("SELECT content, redacted_at FROM turns WHERE id = 1").fetchone()
    assert turn["content"] == ""
    assert turn["redacted_at"] is not None
    assert residue("Köln") == []


def test_entity_survives_while_another_fact_supports_it(ingest):
    """Ein Knoten bleibt, solange ihn ein nicht gelöschter Fakt belegt."""
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich arbeite bei ACME.", at(2))
    with connection() as conn:
        erasure.execute(conn, subject_id="s", fact_ids=[1])
        conn.commit()
        names = {
            row["name"]
            for row in conn.execute("SELECT name FROM entities WHERE subject_id = 's'").fetchall()
        }
    # "s" trägt weiterhin die ACME-Kante, "Köln" nicht mehr.
    assert "ACME" in names
    assert "s" in names
    assert "Köln" not in names


def test_receipt_records_what_went(ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        receipt = erasure.execute(
            conn, subject_id="s", fact_ids=[1], reason="Art. 17", requested_by="jonas"
        )
        conn.commit()
        stored = erasure.receipts(conn, subject_id="s")
    assert receipt.receipt_id > 0
    assert stored[0]["reason"] == "Art. 17"
    assert stored[0]["affected"]["facts"] == [1]
    assert stored[0]["affected"]["trace_steps"]


def test_erased_facts_never_come_back_from_recall(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        erasure.execute(conn, subject_id="s", fact_ids=[1])
        conn.commit()
    result = service.recall(subject_id="s", query="Wo wohnt er? Köln")
    assert result.facts == []
    assert result.injection.text == ""


def test_erasing_nothing_is_harmless():
    with connection() as conn:
        receipt = erasure.execute(conn, subject_id="unbekannt", fact_ids=[])
        conn.commit()
    assert receipt.preview.fact_ids == []


def test_facts_of_another_subject_are_out_of_reach(ingest):
    ingest("Ich wohne in Köln.", at(1), subject="a")
    ingest("Ich wohne in Bonn.", at(1), subject="b")
    with connection() as conn:
        plan = erasure.preview(conn, subject_id="a", fact_ids=[1, 2])
    assert plan.roots == [1]


@pytest.mark.parametrize("scope", ["subject", "facts"])
def test_erasure_is_idempotent(ingest, scope):
    ingest("Ich wohne in Köln.", at(1))
    ids = None if scope == "subject" else [1]
    with connection() as conn:
        erasure.execute(conn, subject_id="s", fact_ids=ids)
        second = erasure.execute(conn, subject_id="s", fact_ids=ids)
        conn.commit()
    assert second.preview.fact_ids == []
