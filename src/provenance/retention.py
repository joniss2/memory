"""Gestufte Aufbewahrung.

Abschnitt 10: vollständige Traces sind größer als die Fakten. Nach einer
Frist werden sie auf Metadaten reduziert -- Stufe, Modell, Prompt-Version,
Dauer, Tokenzahlen bleiben, Ein- und Ausgabe gehen. Die Abstammung bleibt
unbefristet: sie ist die Herkunftsspur, nicht der Debug-Puffer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from provenance.erasure import redact_trace_steps


def prune_traces(
    conn: psycopg.Connection, *, older_than_days: int, subject_id: str | None = None
) -> dict[str, Any]:
    """Reduziert alte Trace-Schritte auf ihre Metadaten."""
    cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
    params: list[Any] = [cutoff]
    scope = ""
    if subject_id is not None:
        scope = " AND t.subject_id = %s"
        params.append(subject_id)

    rows = conn.execute(
        f"""
        SELECT ts.id FROM trace_steps ts JOIN traces t ON t.id = ts.trace_id
        WHERE t.started_at < %s AND ts.redacted_at IS NULL{scope}
        ORDER BY ts.id
        """,
        params,
    ).fetchall()
    step_ids = [int(row["id"]) for row in rows]
    now = datetime.now(UTC)
    redacted = redact_trace_steps(conn, step_ids, at=now)
    return {"cutoff": cutoff.isoformat(), "reduced_steps": len(redacted)}


def storage_report(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """Wie groß ist was? Damit die Aufbewahrungsfrist keine Glaubensfrage bleibt."""
    rows = conn.execute(
        """
        SELECT relname AS tabelle,
               pg_size_pretty(pg_total_relation_size(c.oid)) AS groesse,
               pg_total_relation_size(c.oid) AS bytes,
               n_live_tup AS zeilen
        FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
        LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY pg_total_relation_size(c.oid) DESC
        """
    ).fetchall()
    return [dict(row) for row in rows]
