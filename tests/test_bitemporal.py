"""Zwei Zeitachsen, drei Fragen (Abschnitt 4.2)."""

from __future__ import annotations

import time

from provenance.db.pool import connection
from provenance.store import AsOf, active_facts
from tests.conftest import at


def contents(subject: str, as_of: AsOf) -> set[str]:
    with connection() as conn:
        return {row["content"] for row in active_facts(conn, subject_id=subject, as_of=as_of)}


def now_in_db():
    with connection() as conn:
        return conn.execute("SELECT now() AS n").fetchone()["n"]


def test_transaction_time_replay(ingest):
    """Was wusste das System am 14. Mai?"""
    ingest("Ich wohne in Köln.", at(1))
    before = now_in_db()
    time.sleep(0.02)
    ingest("Ich bin nach Leipzig gezogen.", at(6))

    assert contents("s", AsOf(transaction_time=before)) == {"Wohnt in Köln."}
    assert contents("s", AsOf()) == {"Wohnt in Leipzig."}


def test_valid_time_sees_superseded_facts(ingest):
    """Ein abgelöster Fakt hat in seinem Fenster gegolten und zählt mit."""
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich bin nach Leipzig gezogen.", at(6))

    assert contents("s", AsOf(valid_time=at(3))) == {"Wohnt in Köln."}
    assert contents("s", AsOf(valid_time=at(9))) == {"Wohnt in Leipzig."}


def test_valid_time_ignores_retracted_facts(ingest):
    """Ein Widerruf nimmt die Aussage zurück -- auch rückwirkend."""
    ingest("Ich arbeite bei ACME.", at(1))
    ingest("Vergiss, was ich über meinen Arbeitgeber gesagt habe.", at(7))

    assert contents("s", AsOf(valid_time=at(3))) == set()
    assert contents("s", AsOf()) == set()


def test_recall_respects_transaction_time(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    before = now_in_db()
    time.sleep(0.02)
    ingest("Ich bin nach Leipzig gezogen.", at(6))

    then = service.recall(subject_id="s", query="Wo wohnt er?", as_of=AsOf(transaction_time=before))
    assert "Köln" in then.injection.text
    assert "Leipzig" not in then.injection.text


def test_graph_source_cannot_leak_across_the_time_window(service, ingest):
    """Kanten tragen keine Transaktionszeit; der Filter muss am Fakt greifen.

    Regression: die Graphquelle lieferte Kandidaten an der bitemporalen
    Fensterbedingung vorbei, weil die Kandidatenliste erst nach dem Fusionieren
    gefiltert wurde.
    """
    ingest("Ich wohne in Köln.", at(1))
    before = now_in_db()
    time.sleep(0.02)
    ingest("Ich bin nach Leipzig gezogen.", at(6))

    result = service.recall(
        subject_id="s", query="Köln Leipzig wohnt", as_of=AsOf(transaction_time=before)
    )
    assert [fact.content for fact in result.facts] == ["Wohnt in Köln."]
