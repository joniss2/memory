"""MCP-Server.

Dieselben Operationen wie die HTTP-API als Werkzeuge, damit das Gedächtnis
ohne Integrationsarbeit an beliebigen Assistenten hängt (Abschnitt 8).

Bewusst mit dabei: ``explain_fact``. Ein Assistent, der begründen kann,
*warum* er etwas erinnert, ist der Punkt der ganzen Übung -- ein
Gedächtniswerkzeug, das nur Fakten zurückgibt, gibt es schon.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from provenance import __version__, erasure
from provenance.db.pool import connection, transaction
from provenance.export import fact_history, subject_export
from provenance.service import MemoryService
from provenance.store import AsOf, get_fact, get_trace, lineage_for_trace, trace_steps

try:  # mcp >= 2
    from mcp.server.mcpserver import MCPServer as _Server
except ImportError:  # pragma: no cover - mcp < 2
    from mcp.server.fastmcp import FastMCP as _Server  # type: ignore[no-redef]


def build_server(service: MemoryService | None = None) -> Any:
    service = service or MemoryService()
    server = _Server(
        name="provenance",
        version=__version__,
        instructions=(
            "Gedächtnis-Layer mit Herkunftsspur. `remember` nimmt einen "
            "Gesprächsbeitrag auf, `recall` liefert den passenden Kontext, "
            "`explain_fact` begründet, woher eine Erinnerung stammt und was "
            "seither mit ihr geschehen ist. Löschungen laufen grundsätzlich "
            "erst als Vorschau."
        ),
    )

    @server.tool(
        name="remember",
        description=(
            "Nimmt einen Gesprächsbeitrag auf und leitet daraus Fakten ab "
            "(Extraktion und Konsolidierung). Gibt zurück, was aufgenommen, "
            "abgelöst oder zurückgezogen wurde -- jeweils mit Begründung."
        ),
    )
    def remember(
        subject_id: str,
        content: str,
        session_id: str = "mcp",
        role: str = "user",
        occurred_at: datetime | None = None,
    ) -> dict[str, Any]:
        result = service.ingest_turn(
            subject_id=subject_id,
            session_id=session_id,
            role=role,
            content=content,
            occurred_at=occurred_at,
        )
        return result.as_dict()

    @server.tool(
        name="recall",
        description=(
            "Sucht das Gedächtnis nach einer Frage ab und liefert den Text, der "
            "in den Prompt gestellt werden soll -- samt der Fakten dahinter und "
            "der Angabe, was am Token-Budget gescheitert ist."
        ),
    )
    def recall(
        subject_id: str,
        query: str,
        limit: int | None = None,
        token_budget: int | None = None,
        as_of_transaction_time: datetime | None = None,
        as_of_valid_time: datetime | None = None,
    ) -> dict[str, Any]:
        result = service.recall(
            subject_id=subject_id,
            query=query,
            as_of=AsOf(
                transaction_time=as_of_transaction_time, valid_time=as_of_valid_time
            ),
            limit=limit,
            token_budget=token_budget,
        )
        return result.as_dict()

    @server.tool(
        name="explain_fact",
        description=(
            "Beantwortet für einen Fakt: woher stammt er, was ist mit dem "
            "vorherigen Wert passiert, welcher Beitrag hat ihn ausgelöst."
        ),
    )
    def explain_fact(fact_id: int) -> dict[str, Any]:
        with connection() as conn:
            fact = get_fact(conn, fact_id)
            if fact is None:
                return {"error": f"Fakt {fact_id} nicht gefunden"}
            return {"fakt": _plain(fact), "verlauf": fact_history(conn, fact_id=fact_id)}

    @server.tool(
        name="get_trace",
        description="Liefert einen vollständigen Trace über alle vier Pipeline-Stufen.",
    )
    def get_full_trace(trace_id: int) -> dict[str, Any]:
        with connection() as conn:
            header = get_trace(conn, trace_id)
            if header is None:
                return {"error": f"Trace {trace_id} nicht gefunden"}
            return {
                "trace": _plain(header),
                "steps": [_plain(step) for step in trace_steps(conn, trace_id)],
                "lineage": [_plain(item) for item in lineage_for_trace(conn, trace_id)],
            }

    @server.tool(
        name="export_subject",
        description=(
            "DSGVO-Auskunft: alle gespeicherten Aussagen über eine Person mit "
            "Quelle, Zeitpunkt und Verlauf."
        ),
    )
    def export_subject(subject_id: str) -> dict[str, Any]:
        with connection() as conn:
            return subject_export(conn, subject_id=subject_id)

    @server.tool(
        name="erase",
        description=(
            "Löscht Fakten samt allem, was aus ihnen abgeleitet wurde. Ohne "
            "confirm=true wird ausschließlich die Vorschau berechnet und nichts "
            "verändert -- gelöscht wird erst auf ausdrückliche Bestätigung."
        ),
    )
    def erase(
        subject_id: str,
        fact_ids: list[int] | None = None,
        confirm: bool = False,
        reason: str | None = None,
    ) -> dict[str, Any]:
        with transaction() as conn:
            if not confirm:
                plan = erasure.preview(conn, subject_id=subject_id, fact_ids=fact_ids)
                return {
                    "ausgefuehrt": False,
                    "hinweis": "Vorschau. Zum Ausführen erneut mit confirm=true aufrufen.",
                    "vorschau": _plain(plan.as_dict()),
                }
            receipt = erasure.execute(
                conn, subject_id=subject_id, fact_ids=fact_ids, reason=reason
            )
            return {"ausgefuehrt": True, "beleg": _plain(receipt.as_dict())}

    return server


def _plain(value: Any) -> Any:
    """Datumswerte in ISO-Text -- MCP-Antworten müssen JSON-serialisierbar sein."""
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def main() -> None:
    from provenance.db.migration import migrate

    migrate()
    build_server().run(transport="stdio")


if __name__ == "__main__":
    main()
