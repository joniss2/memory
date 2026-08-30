"""Schema und Migrationen."""

from __future__ import annotations

import pytest

from provenance.db.migration import load_migrations, migrate
from provenance.db.pool import connection


def test_migrations_are_idempotent():
    assert migrate() == []


def test_all_seven_tables_plus_receipt_exist():
    with connection() as conn:
        rows = conn.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        ).fetchall()
    names = {row["tablename"] for row in rows}
    assert {
        "turns", "facts", "lineage", "entities", "edges", "traces", "trace_steps",
    } <= names
    assert "erasure_receipts" in names


def test_changed_migration_is_refused():
    """Eine bereits angewandte Migration darf sich nicht ändern.

    Ohne diese Prüfung würde eine nachträglich bearbeitete Migration auf
    frischen Datenbanken etwas anderes anlegen als auf gewachsenen -- und
    genau das fällt erst im Betrieb auf.
    """
    with connection() as conn:
        conn.execute(
            "UPDATE schema_migrations SET checksum = 'abweichend' WHERE version = %s",
            (load_migrations()[0].version,),
        )
        conn.commit()
    try:
        with pytest.raises(RuntimeError, match="geändert"):
            migrate()
    finally:
        with connection() as conn:
            conn.execute(
                "UPDATE schema_migrations SET checksum = %s WHERE version = %s",
                (load_migrations()[0].checksum, load_migrations()[0].version),
            )
            conn.commit()


def test_edge_requires_supporting_fact():
    """Es gibt keine Kante ohne belegenden Fakt (Abschnitt 4.4)."""
    with connection() as conn:
        columns = conn.execute(
            """
            SELECT is_nullable FROM information_schema.columns
            WHERE table_name = 'edges' AND column_name = 'fact_id'
            """
        ).fetchone()
    assert columns["is_nullable"] == "NO"


def test_add_lineage_cannot_have_parent():
    with connection() as conn:
        turn = conn.execute(
            "INSERT INTO turns (subject_id, session_id, role, content) "
            "VALUES ('s','t','user','x') RETURNING id"
        ).fetchone()
        trace = conn.execute(
            "INSERT INTO traces (subject_id, kind, turn_id) VALUES ('s','write',%s) RETURNING id",
            (turn["id"],),
        ).fetchone()
        facts = [
            conn.execute(
                "INSERT INTO facts (subject_id, content, valid_from) "
                "VALUES ('s', %s, now()) RETURNING id",
                (f"f{i}",),
            ).fetchone()["id"]
            for i in range(2)
        ]
        with pytest.raises(Exception, match="lineage_add_has_no_parent"):
            conn.execute(
                "INSERT INTO lineage (fact_id, parent_id, op, trace_id) "
                "VALUES (%s, %s, 'add', %s)",
                (facts[0], facts[1], trace["id"]),
            )
        conn.rollback()
