"""Die Pipeline als Ganzes.

``ingest_turn`` fährt die Stufen 1--2, ``recall`` die Stufen 3--4. Beides
läuft in genau einer Transaktion: der Trace, die Fakten, die Abstammung und
die Kanten sind entweder alle da oder keiner von ihnen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from provenance.config import Settings, get_settings
from provenance.db.pool import transaction
from provenance.embeddings import build_embedder
from provenance.embeddings.base import Embedder
from provenance.llm import build_llm
from provenance.llm.base import LLMProvider
from provenance.pipeline.consolidate import consolidate
from provenance.pipeline.extract import extract
from provenance.pipeline.inject import inject
from provenance.pipeline.retrieve import retrieve
from provenance.pipeline.types import AppliedDecision, ExtractionResult, Injection, RetrievedFact
from provenance.store import NOW, AsOf, insert_turn
from provenance.trace import record


@dataclass(slots=True)
class IngestResult:
    turn_id: int
    trace_id: int
    extraction: ExtractionResult
    decisions: list[AppliedDecision] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "turn_id": self.turn_id,
            "trace_id": self.trace_id,
            "candidates": len(self.extraction.candidates),
            "non_extractions": [
                {"text": item.text, "reason": item.reason} for item in self.extraction.non_extractions
            ],
            "discarded": [
                {"text": item.text, "reason": item.reason} for item in self.extraction.discarded
            ],
            "decisions": [item.summary() for item in self.decisions],
        }


@dataclass(slots=True)
class RecallResult:
    trace_id: int
    facts: list[RetrievedFact]
    injection: Injection

    def as_dict(self) -> dict[str, Any]:
        from provenance.pipeline.retrieve import as_dicts

        return {
            "trace_id": self.trace_id,
            "context": self.injection.text,
            "facts": as_dicts(self.facts),
            "tokens_used": self.injection.tokens_used,
            "token_budget": self.injection.token_budget,
            "dropped": self.injection.dropped,
        }


class MemoryService:
    """Ein Dienst, ein Modell, eine Einbettung, eine Datenbank."""

    def __init__(
        self,
        settings: Settings | None = None,
        llm: LLMProvider | None = None,
        embedder: Embedder | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.llm = llm or build_llm(self.settings)
        self.embedder = embedder or build_embedder(self.settings)

    # ------------------------------------------------------------ Stufen 1-2

    def ingest_turn(
        self,
        *,
        subject_id: str,
        session_id: str,
        role: str,
        content: str,
        occurred_at: datetime | None = None,
        subject_label: str | None = None,
    ) -> IngestResult:
        with transaction() as conn:
            return self.ingest_turn_in(
                conn,
                subject_id=subject_id,
                session_id=session_id,
                role=role,
                content=content,
                occurred_at=occurred_at,
                subject_label=subject_label,
            )

    def ingest_turn_in(
        self,
        conn: psycopg.Connection,
        *,
        subject_id: str,
        session_id: str,
        role: str,
        content: str,
        occurred_at: datetime | None = None,
        subject_label: str | None = None,
    ) -> IngestResult:
        tx_time = _transaction_time(conn)
        turn = insert_turn(
            conn,
            subject_id=subject_id,
            session_id=session_id,
            role=role,
            content=content,
            occurred_at=occurred_at,
        )
        with record(conn, subject_id=subject_id, kind="write", turn_id=int(turn["id"])) as recorder:
            extraction = extract(
                conn,
                llm=self.llm,
                embedder=self.embedder,
                settings=self.settings,
                recorder=recorder,
                turn=turn,
                subject_label=subject_label,
            )
            decisions: list[AppliedDecision] = []
            for candidate in extraction.candidates:
                decisions.append(
                    consolidate(
                        conn,
                        llm=self.llm,
                        embedder=self.embedder,
                        settings=self.settings,
                        recorder=recorder,
                        subject_id=subject_id,
                        candidate=candidate,
                        turn=turn,
                        tx_time=tx_time,
                        subject_label=subject_label,
                    )
                )
            return IngestResult(
                turn_id=int(turn["id"]),
                trace_id=recorder.trace_id,
                extraction=extraction,
                decisions=decisions,
            )

    # ------------------------------------------------------------ Stufen 3-4

    def recall(
        self,
        *,
        subject_id: str,
        query: str,
        as_of: AsOf = NOW,
        limit: int | None = None,
        token_budget: int | None = None,
    ) -> RecallResult:
        with transaction() as conn:
            return self.recall_in(
                conn,
                subject_id=subject_id,
                query=query,
                as_of=as_of,
                limit=limit,
                token_budget=token_budget,
            )

    def recall_in(
        self,
        conn: psycopg.Connection,
        *,
        subject_id: str,
        query: str,
        as_of: AsOf = NOW,
        limit: int | None = None,
        token_budget: int | None = None,
    ) -> RecallResult:
        with record(conn, subject_id=subject_id, kind="read", query=query) as recorder:
            facts = retrieve(
                conn,
                embedder=self.embedder,
                settings=self.settings,
                recorder=recorder,
                subject_id=subject_id,
                query=query,
                as_of=as_of,
                limit=limit,
            )
            injection = inject(
                settings=self.settings,
                recorder=recorder,
                facts=facts,
                token_budget=token_budget,
            )
            return RecallResult(trace_id=recorder.trace_id, facts=facts, injection=injection)


def _transaction_time(conn: psycopg.Connection) -> datetime:
    """Ein Zeitpunkt für die ganze Transaktion.

    ``now()`` in Postgres ist die Startzeit der Transaktion und damit über
    alle Schreibvorgänge desselben Turns konstant. Das ist die Voraussetzung
    dafür, dass ein Replay auf Transaktionszeit einen scharfen Schnitt
    liefert statt einer Millisekunden-Unschärfe.
    """
    row = conn.execute("SELECT now() AS now").fetchone()
    assert row is not None
    return row["now"]
