"""Trace-Aufzeichnung.

Jede Stufe schreibt ihren Schritt, auch wenn sie nichts gefunden hat. Ein
leerer Extraktionsschritt ist ein Befund, keine Leerstelle (Abschnitt 5,
Stufe 1).
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import psycopg

from provenance.db.pool import Jsonb

STAGE_EXTRACT = 1
STAGE_CONSOLIDATE = 2
STAGE_RETRIEVE = 3
STAGE_INJECT = 4

STAGE_NAMES = {
    STAGE_EXTRACT: "Extraktion",
    STAGE_CONSOLIDATE: "Konsolidierung",
    STAGE_RETRIEVE: "Retrieval",
    STAGE_INJECT: "Injection",
}


@dataclass
class TraceRecorder:
    conn: psycopg.Connection
    trace_id: int
    _started: float = field(default_factory=time.perf_counter)
    step_ids: list[int] = field(default_factory=list)

    def step(
        self,
        stage: int,
        *,
        input: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
        model: str | None = None,
        prompt_ref: str | None = None,
        duration_ms: int | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> int:
        row = self.conn.execute(
            """
            INSERT INTO trace_steps
                (trace_id, stage, model, prompt_ref, input, output,
                 duration_ms, tokens_in, tokens_out)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                self.trace_id,
                stage,
                model,
                prompt_ref,
                Jsonb(input) if input is not None else None,
                Jsonb(output) if output is not None else None,
                duration_ms,
                tokens_in,
                tokens_out,
            ),
        ).fetchone()
        assert row is not None
        self.step_ids.append(int(row["id"]))
        return int(row["id"])

    def finish(self) -> None:
        elapsed_ms = int((time.perf_counter() - self._started) * 1000)
        self.conn.execute(
            "UPDATE traces SET duration_ms = %s WHERE id = %s",
            (elapsed_ms, self.trace_id),
        )


@contextmanager
def record(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    kind: str,
    turn_id: int | None = None,
    query: str | None = None,
) -> Iterator[TraceRecorder]:
    """Öffnet einen Trace und schließt ihn auch dann, wenn eine Stufe wirft.

    Ein abgebrochener Lauf ist der interessanteste Fall für die
    Entwickleransicht -- er darf nicht der einzige sein, der keine Spur
    hinterlässt.
    """
    row = conn.execute(
        """
        INSERT INTO traces (subject_id, kind, turn_id, query)
        VALUES (%s, %s::trace_kind, %s, %s)
        RETURNING id
        """,
        (subject_id, kind, turn_id, query),
    ).fetchone()
    assert row is not None
    recorder = TraceRecorder(conn=conn, trace_id=int(row["id"]))
    try:
        yield recorder
    finally:
        recorder.finish()


class Stopwatch:
    """Millisekunden für einen Abschnitt, ohne jedes Mal dieselben drei Zeilen."""

    def __init__(self) -> None:
        self._start = time.perf_counter()

    def lap(self) -> int:
        now = time.perf_counter()
        elapsed = int((now - self._start) * 1000)
        self._start = now
        return elapsed

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._start) * 1000)
