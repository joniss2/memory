"""HTTP-Schnittstelle (Abschnitt 8).

Die fünf dokumentierten Endpunkte plus das, was die beiden Dashboard-Ansichten
brauchen. Alle Handler sind synchron: die Arbeit steckt in Postgres und im
Modellaufruf, beides blockierend, und Starlette gibt synchrone Handler an
einen Threadpool -- das ist ehrlicher als ein `async def`, das doch blockiert.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from provenance import __version__, erasure
from provenance.config import Settings, get_settings
from provenance.db.migration import migrate
from provenance.db.pool import connection, transaction
from provenance.export import fact_history, subject_export
from provenance.graph import entity_snapshot
from provenance.prompts import prompt_refs
from provenance.replay import purge_subject, replay_session
from provenance.service import MemoryService
from provenance.store import (
    AsOf,
    active_facts,
    all_facts,
    get_fact,
    get_trace,
    lineage_for_trace,
    list_subjects,
    list_traces,
    list_turns,
    trace_steps,
    traces_for_turn,
)

_service: MemoryService | None = None


def get_service() -> MemoryService:
    global _service
    if _service is None:
        _service = MemoryService()
    return _service


def reset_service() -> None:
    global _service
    _service = None


# ------------------------------------------------------------------- Schemata


class TurnIn(BaseModel):
    subject_id: str = Field(..., min_length=1, max_length=200)
    session_id: str = Field(..., min_length=1, max_length=200)
    role: str = Field("user", pattern="^(user|assistant|system)$")
    content: str = Field(..., min_length=1)
    occurred_at: datetime | None = None
    subject_label: str | None = None


class ReplayIn(BaseModel):
    subject_id: str
    session_id: str | None = None
    target_subject: str | None = None
    discard: bool = Field(
        default=True,
        description="Den Wiederholungslauf nach dem Vergleich wieder entfernen. "
        "Mit false bleibt er zur Inspektion stehen.",
    )


class EraseIn(BaseModel):
    fact_ids: list[int] | None = Field(
        default=None,
        description="Nur diese Fakten samt allem, was aus ihnen abgeleitet wurde. "
        "Ohne Angabe: die betroffene Person vollständig.",
    )
    confirm: bool = Field(
        default=False,
        description="Ohne confirm=true wird nur die Vorschau berechnet, nichts gelöscht.",
    )
    reason: str | None = None
    requested_by: str | None = None


# --------------------------------------------------------------------- App


def require_token(
    authorization: Annotated[str | None, Header()] = None,
    settings: Settings = Depends(get_settings),
) -> None:
    """Bearer-Prüfung, sofern PROVENANCE_API_TOKEN gesetzt ist.

    Ohne gesetztes Token bleibt die Schnittstelle offen -- das ist für einen
    lokalen Betrieb hinter einem Reverse Proxy gewollt und für alles andere
    eine bewusste Entscheidung des Betreibers.
    """
    expected = settings.api_token
    if not expected:
        return
    if authorization != f"Bearer {expected}":
        raise HTTPException(status_code=401, detail="ungültiges oder fehlendes Token")


@asynccontextmanager
async def lifespan(app: FastAPI):
    migrate()
    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(
        title="provenance",
        version=__version__,
        summary="Gedächtnis-Layer mit Herkunftsspur",
        lifespan=lifespan,
    )
    guard = [Depends(require_token)]

    # ----------------------------------------------------------- Betriebsdaten

    @app.get("/healthz", tags=["Betrieb"])
    def healthz() -> dict[str, Any]:
        with connection() as conn:
            row = conn.execute("SELECT count(*) AS n FROM facts WHERE status = 'active'").fetchone()
        return {
            "status": "ok",
            "version": __version__,
            "llm_provider": settings.llm_provider,
            "embedding_provider": settings.embedding_provider,
            "embedding_dim": settings.embedding_dim,
            "prompts": prompt_refs(),
            "active_facts": int(row["n"]) if row else 0,
        }

    # ------------------------------------------------------------ Stufen 1--2

    @app.post("/v1/turns", tags=["Gedächtnis"], dependencies=guard)
    def post_turn(body: TurnIn, service: MemoryService = Depends(get_service)) -> dict[str, Any]:
        """Nimmt einen Beitrag auf und löst die Stufen 1--2 aus."""
        result = service.ingest_turn(
            subject_id=body.subject_id,
            session_id=body.session_id,
            role=body.role,
            content=body.content,
            occurred_at=body.occurred_at,
            subject_label=body.subject_label,
        )
        return result.as_dict()

    # ------------------------------------------------------------ Stufen 3--4

    @app.get("/v1/recall", tags=["Gedächtnis"], dependencies=guard)
    def get_recall(
        subject_id: str,
        query: str,
        limit: int | None = None,
        token_budget: int | None = None,
        as_of_transaction_time: datetime | None = Query(
            None, description="Was wusste das System zu diesem Zeitpunkt?"
        ),
        as_of_valid_time: datetime | None = Query(
            None, description="Was galt zu diesem Zeitpunkt in der Welt?"
        ),
        service: MemoryService = Depends(get_service),
    ) -> dict[str, Any]:
        """Abruf über die Stufen 3--4."""
        result = service.recall(
            subject_id=subject_id,
            query=query,
            as_of=AsOf(
                transaction_time=as_of_transaction_time,
                valid_time=as_of_valid_time,
            ),
            limit=limit,
            token_budget=token_budget,
        )
        return result.as_dict()

    # ---------------------------------------------------------------- Traces

    @app.get("/v1/traces/{trace_id}", tags=["Herkunft"], dependencies=guard)
    def get_full_trace(trace_id: int) -> dict[str, Any]:
        """Der vollständige Trace: alle vier Stufen mit Ein- und Ausgabe."""
        with connection() as conn:
            trace = get_trace(conn, trace_id)
            if trace is None:
                raise HTTPException(status_code=404, detail="Trace nicht gefunden")
            return {
                "trace": trace,
                "steps": trace_steps(conn, trace_id),
                "lineage": lineage_for_trace(conn, trace_id),
            }

    @app.get("/v1/traces", tags=["Herkunft"], dependencies=guard)
    def get_traces(
        subject_id: str, kind: str | None = None, limit: int = 50, offset: int = 0
    ) -> dict[str, Any]:
        with connection() as conn:
            return {
                "traces": list_traces(
                    conn, subject_id=subject_id, kind=kind, limit=limit, offset=offset
                )
            }

    # --------------------------------------------------------------- Subjekte

    @app.get("/v1/subjects", tags=["Auskunft"], dependencies=guard)
    def get_subjects() -> dict[str, Any]:
        with connection() as conn:
            return {"subjects": list_subjects(conn)}

    @app.get("/v1/subjects/{subject_id}/export", tags=["Auskunft"], dependencies=guard)
    def get_export(subject_id: str) -> dict[str, Any]:
        """DSGVO-Auskunft: Aussagen, Quellen, Verlauf, Löschbelege."""
        with connection() as conn:
            return subject_export(conn, subject_id=subject_id)

    @app.get("/v1/subjects/{subject_id}/facts", tags=["Auskunft"], dependencies=guard)
    def get_subject_facts(
        subject_id: str,
        include_inactive: bool = False,
        as_of_transaction_time: datetime | None = None,
        as_of_valid_time: datetime | None = None,
    ) -> dict[str, Any]:
        with connection() as conn:
            if include_inactive:
                facts = all_facts(conn, subject_id=subject_id)
            else:
                facts = active_facts(
                    conn,
                    subject_id=subject_id,
                    as_of=AsOf(
                        transaction_time=as_of_transaction_time, valid_time=as_of_valid_time
                    ),
                )
            return {"facts": facts}

    @app.get("/v1/subjects/{subject_id}/timeline", tags=["Herkunft"], dependencies=guard)
    def get_timeline(subject_id: str, limit: int = 200) -> dict[str, Any]:
        """Turn-Zeitleiste mit der Zustandsänderung je Beitrag (Abschnitt 6)."""
        with connection() as conn:
            turns = list_turns(conn, subject_id=subject_id, limit=limit)
            timeline: list[dict[str, Any]] = []
            for turn in turns:
                traces = traces_for_turn(conn, int(turn["id"]))
                changes: list[dict[str, Any]] = []
                for trace in traces:
                    changes.extend(lineage_for_trace(conn, int(trace["id"])))
                timeline.append(
                    {
                        "turn": turn,
                        "traces": traces,
                        "changes": changes,
                        "summary": _summarise(changes),
                    }
                )
            return {"timeline": timeline}

    @app.get("/v1/subjects/{subject_id}/graph", tags=["Herkunft"], dependencies=guard)
    def get_graph(subject_id: str, at: datetime | None = None) -> dict[str, Any]:
        """Knoten und Kanten, wahlweise zu einem Zeitpunkt (Zeitschieber)."""
        with connection() as conn:
            return entity_snapshot(conn, subject_id=subject_id, at=at)

    @app.get("/v1/facts/{fact_id}/history", tags=["Auskunft"], dependencies=guard)
    def get_fact_history(fact_id: int) -> dict[str, Any]:
        with connection() as conn:
            fact = get_fact(conn, fact_id)
            if fact is None:
                raise HTTPException(status_code=404, detail="Fakt nicht gefunden")
            return {"fact": fact, "verlauf": fact_history(conn, fact_id=fact_id)}

    # --------------------------------------------------------------- Löschung

    @app.post("/v1/subjects/{subject_id}/erase", tags=["Löschung"], dependencies=guard)
    def post_erase(subject_id: str, body: EraseIn) -> dict[str, Any]:
        """Löschung mit Vorschau.

        Ohne ``confirm: true`` wird nur berechnet, was betroffen wäre --
        Abschnitt 7 verlangt die Vorschau *vor* der Löschung.
        """
        with transaction() as conn:
            if not body.confirm:
                plan = erasure.preview(conn, subject_id=subject_id, fact_ids=body.fact_ids)
                return {"vorschau": plan.as_dict(), "ausgefuehrt": False}
            receipt = erasure.execute(
                conn,
                subject_id=subject_id,
                fact_ids=body.fact_ids,
                requested_by=body.requested_by,
                reason=body.reason,
            )
            return {"beleg": receipt.as_dict(), "ausgefuehrt": True}

    @app.get("/v1/subjects/{subject_id}/erasures", tags=["Löschung"], dependencies=guard)
    def get_erasures(subject_id: str) -> dict[str, Any]:
        with connection() as conn:
            return {"belege": erasure.receipts(conn, subject_id=subject_id)}

    # ----------------------------------------------------------------- Replay

    @app.post("/v1/replay", tags=["Herkunft"], dependencies=guard)
    def post_replay(
        body: ReplayIn, service: MemoryService = Depends(get_service)
    ) -> dict[str, Any]:
        """Fährt eine gespeicherte Sitzung erneut und difft gegen das Original."""
        with transaction() as conn:
            result = replay_session(
                conn,
                service=service,
                source_subject=body.subject_id,
                session_id=body.session_id,
                target_subject=body.target_subject,
            )
            if body.discard:
                purge_subject(conn, result.target_subject)
            return result.as_dict()

    # -------------------------------------------------------------- Dashboard

    if settings.dashboard_enabled:
        from provenance.dashboard import router as dashboard_router

        app.include_router(dashboard_router)

        @app.get("/", include_in_schema=False)
        def index() -> HTMLResponse:
            return HTMLResponse(
                '<meta http-equiv="refresh" content="0; url=/ui/">', status_code=200
            )

    @app.exception_handler(ValueError)
    def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    return app


def _summarise(changes: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for change in changes:
        counts[change["op"]] = counts.get(change["op"], 0) + 1
    return counts


app = create_app()
