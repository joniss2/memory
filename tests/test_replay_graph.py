"""Replay, Graphprojektion und Aufbewahrung."""

from __future__ import annotations

import pytest

from provenance.db.pool import connection
from provenance.graph import entity_snapshot
from provenance.replay import purge_subject, replay_session
from provenance.retention import prune_traces
from tests.conftest import at


def test_replay_is_deterministic(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich bin nach Leipzig gezogen.", at(6))
    with connection() as conn:
        result = replay_session(conn, service=service, source_subject="s")
        conn.commit()
    assert result.turns_replayed == 2
    assert not result.differs
    assert set(result.unchanged) == {"Wohnt in Leipzig."}


def test_replay_leaves_the_original_untouched(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        replay_session(conn, service=service, source_subject="s")
        conn.commit()
        original = conn.execute(
            "SELECT count(*) AS n FROM facts WHERE subject_id = 's'"
        ).fetchone()
    assert original["n"] == 1


def test_purge_refuses_real_subjects():
    with connection() as conn, pytest.raises(ValueError, match="beschränkt"):
        purge_subject(conn, "jonas")


def test_purge_removes_a_replay_completely(service, ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        result = replay_session(conn, service=service, source_subject="s")
        purge_subject(conn, result.target_subject)
        conn.commit()
        left = conn.execute(
            "SELECT count(*) AS n FROM facts WHERE subject_id = %s", (result.target_subject,)
        ).fetchone()
    assert left["n"] == 0


def test_every_edge_has_a_supporting_fact(ingest):
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich arbeite bei ACME.", at(2))
    with connection() as conn:
        snapshot = entity_snapshot(conn, subject_id="s")
    assert snapshot["edges"]
    for edge in snapshot["edges"]:
        assert edge["fact_id"] is not None
        assert edge["fact_content"]
        assert edge["origin_turn"] is not None


def test_graph_time_slider(ingest):
    ingest("Ich wohne in Köln.", at(1))
    ingest("Ich bin nach Leipzig gezogen.", at(6))
    with connection() as conn:
        march = entity_snapshot(conn, subject_id="s", at=at(3))
        september = entity_snapshot(conn, subject_id="s", at=at(9))
    assert {edge["dst_name"] for edge in march["edges"]} == {"Köln"}
    assert {edge["dst_name"] for edge in september["edges"]} == {"Leipzig"}


def test_pruning_reduces_traces_to_metadata(ingest):
    result = ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        conn.execute("UPDATE traces SET started_at = now() - interval '90 days'")
        report = prune_traces(conn, older_than_days=30)
        conn.commit()
        row = conn.execute(
            "SELECT stage, duration_ms, prompt_ref, output, redacted_at "
            "FROM trace_steps WHERE trace_id = %s ORDER BY stage LIMIT 1",
            (result.trace_id,),
        ).fetchone()
    assert report["reduced_steps"] > 0
    # Metadaten bleiben, Inhalt geht.
    assert row["duration_ms"] is not None
    assert row["prompt_ref"].startswith("extract.v1@")
    assert row["redacted_at"] is not None
    assert row["output"]["raw"] is None


def test_pruning_leaves_lineage_untouched(ingest):
    ingest("Ich wohne in Köln.", at(1))
    with connection() as conn:
        conn.execute("UPDATE traces SET started_at = now() - interval '90 days'")
        prune_traces(conn, older_than_days=30)
        conn.commit()
        rows = conn.execute("SELECT op, rationale FROM lineage").fetchall()
    # Abstammung ist die Herkunftsspur, nicht der Debug-Puffer: unbefristet.
    assert rows and rows[0]["rationale"]
