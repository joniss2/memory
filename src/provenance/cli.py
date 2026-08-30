"""Kommandozeile.

Der erste lauffähige Stand aus Abschnitt 11 hat keine Oberfläche -- nur das
hier.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table

from provenance import __version__, erasure
from provenance.config import get_settings
from provenance.db.migration import migrate as run_migrate
from provenance.db.migration import reset as run_reset
from provenance.db.pool import connection, transaction
from provenance.export import subject_export
from provenance.prompts import prompt_refs
from provenance.retention import prune_traces, storage_report
from provenance.service import MemoryService
from provenance.store import (
    AsOf,
    all_facts,
    get_trace,
    lineage_for_trace,
    list_subjects,
    list_turns,
    reindex_fulltext,
    trace_steps,
    traces_for_turn,
)
from provenance.trace import STAGE_NAMES

app = typer.Typer(
    add_completion=False,
    help="provenance -- Gedächtnis-Layer mit Herkunftsspur.",
    no_args_is_help=True,
)
console = Console()

STATUS_STYLE = {
    "active": "green",
    "superseded": "yellow",
    "retracted": "red",
    "erased": "dim",
}


@app.command()
def version() -> None:
    """Version und geladene Prompt-Kennungen."""
    console.print(f"provenance {__version__}")
    settings = get_settings()
    console.print(f"Modell:     {settings.llm_provider} ({settings.llm_model_extract})")
    console.print(f"Einbettung: {settings.embedding_provider} ({settings.embedding_dim} Dim.)")
    for ref in prompt_refs().values():
        console.print(f"Prompt:     {ref}")


@app.command()
def migrate(
    reset: bool = typer.Option(False, "--reset", help="Schema vorher verwerfen. Zerstört Daten."),
) -> None:
    """Wendet ausstehende Migrationen an."""
    if reset:
        if not typer.confirm("Das gesamte Schema wird verworfen. Fortfahren?"):
            raise typer.Abort()
        run_reset()
        console.print("[yellow]Schema neu aufgebaut.[/]")
        return
    applied = run_migrate()
    console.print(f"Angewandt: {', '.join(applied) if applied else '(nichts offen)'}")


@app.command()
def ingest(
    subject: str = typer.Option(..., "--subject", "-s", help="Kennung der betroffenen Person"),
    content: str = typer.Option(..., "--content", "-c"),
    session: str = typer.Option("cli", "--session"),
    role: str = typer.Option("user", "--role"),
    at: datetime | None = typer.Option(None, "--at", help="Zeitpunkt des Beitrags (ISO-8601)"),
    show_trace: bool = typer.Option(False, "--trace", help="Trace danach ausgeben"),
) -> None:
    """Nimmt einen Beitrag auf und fährt die Stufen 1--2."""
    service = MemoryService()
    result = service.ingest_turn(
        subject_id=subject, session_id=session, role=role, content=content, occurred_at=at
    )
    console.print(f"Turn [bold]{result.turn_id}[/], Trace [bold]{result.trace_id}[/]")

    if not result.decisions:
        console.print("[yellow]Kein Fakt aufgenommen.[/]")
    table = Table(show_header=True, header_style="bold")
    table.add_column("Entscheidung")
    table.add_column("Fakt")
    table.add_column("Betroffen")
    table.add_column("Begründung", overflow="fold")
    for decision in result.decisions:
        marker = decision.decision.op
        if decision.decision.was_overridden:
            marker = f"{marker} [dim](statt {decision.decision.proposed_op})[/]"
        affected = decision.superseded + decision.retracted
        table.add_row(
            marker,
            str(decision.fact_id or "-"),
            ", ".join(str(item) for item in affected) or "-",
            decision.decision.rationale,
        )
    if result.decisions:
        console.print(table)

    for item in result.extraction.non_extractions:
        console.print(f"[dim]nicht extrahiert:[/] {item.text!r} -- {item.reason}")
    for item in result.extraction.discarded:
        console.print(f"[red]verworfen:[/] {item.text!r} -- {item.reason}")

    if show_trace:
        trace(result.trace_id)


@app.command()
def recall(
    subject: str = typer.Option(..., "--subject", "-s"),
    query: str = typer.Option(..., "--query", "-q"),
    limit: int | None = typer.Option(None, "--limit"),
    budget: int | None = typer.Option(None, "--budget", help="Token-Budget für Stufe 4"),
    as_of_tx: datetime | None = typer.Option(
        None, "--as-of-transaction", help="Was wusste das System zu diesem Zeitpunkt?"
    ),
    as_of_valid: datetime | None = typer.Option(
        None, "--as-of-valid", help="Was galt zu diesem Zeitpunkt in der Welt?"
    ),
    show_trace: bool = typer.Option(False, "--trace"),
) -> None:
    """Ruft ab und zeigt, was in den Prompt gestellt würde."""
    service = MemoryService()
    result = service.recall(
        subject_id=subject,
        query=query,
        as_of=AsOf(transaction_time=as_of_tx, valid_time=as_of_valid),
        limit=limit,
        token_budget=budget,
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Fakt", justify="right")
    table.add_column("RRF", justify="right")
    table.add_column("Quellen")
    table.add_column("Inhalt", overflow="fold")
    for rank, item in enumerate(result.facts, start=1):
        sources = ", ".join(f"{name}#{position}" for name, position in item.sources.items())
        table.add_row(str(rank), str(item.fact_id), f"{item.score:.4f}", sources, item.content)
    console.print(table)
    console.print(
        Panel(
            result.injection.text or "[dim](nichts)[/]",
            title=f"Stufe 4 -- {result.injection.tokens_used}/{result.injection.token_budget} Token",
        )
    )
    for dropped in result.injection.dropped:
        console.print(f"[yellow]aus dem Budget gefallen:[/] Rang {dropped['rank']} -- {dropped['content']}")
    console.print(f"[dim]Trace {result.trace_id}[/]")
    if show_trace:
        trace(result.trace_id)


@app.command()
def trace(trace_id: int = typer.Argument(..., help="Kennung des Traces")) -> None:
    """Zeigt einen vollständigen Trace, Stufe für Stufe."""
    with connection() as conn:
        header = get_trace(conn, trace_id)
        if header is None:
            console.print(f"[red]Trace {trace_id} nicht gefunden.[/]")
            raise typer.Exit(code=1)
        steps = trace_steps(conn, trace_id)
        changes = lineage_for_trace(conn, trace_id)

    console.print(
        Panel(
            f"Person [bold]{header['subject_id']}[/] · {header['kind']} · "
            f"{header['started_at']:%Y-%m-%d %H:%M:%S} · {header['duration_ms']} ms"
            + (f"\nFrage: {header['query']}" if header["query"] else ""),
            title=f"Trace {trace_id}",
        )
    )
    for step in steps:
        title = f"Stufe {step['stage']} -- {STAGE_NAMES.get(step['stage'], '?')}"
        meta = f"{step['model'] or '-'} · {step['prompt_ref'] or '-'} · {step['duration_ms']} ms"
        if step["redacted_at"]:
            meta += " · [red]geschwärzt[/]"
        console.print(Panel(meta, title=title, expand=False))
        for label, payload in (("Eingang", step["input"]), ("Ausgang", step["output"])):
            if payload is None:
                continue
            console.print(f"[bold]{label}[/]")
            console.print(JSON(json.dumps(payload, ensure_ascii=False, default=str)))
    if changes:
        table = Table(title="Abstammung", show_header=True, header_style="bold")
        table.add_column("Vorgang")
        table.add_column("Fakt")
        table.add_column("Aus")
        table.add_column("Begründung", overflow="fold")
        for change in changes:
            table.add_row(
                change["op"], str(change["fact_id"]), str(change["parent_id"] or "-"),
                change["rationale"] or "",
            )
        console.print(table)


@app.command()
def facts(
    subject: str = typer.Option(..., "--subject", "-s"),
    all_states: bool = typer.Option(False, "--all", help="Auch abgelöste und zurückgezogene"),
) -> None:
    """Listet die Fakten einer Person."""
    with connection() as conn:
        rows = all_facts(conn, subject_id=subject)
    table = Table(show_header=True, header_style="bold")
    table.add_column("#", justify="right")
    table.add_column("Status")
    table.add_column("gilt seit")
    table.add_column("gilt bis")
    table.add_column("Inhalt", overflow="fold")
    for row in rows:
        if not all_states and row["status"] != "active":
            continue
        style = STATUS_STYLE.get(row["status"], "")
        table.add_row(
            str(row["id"]),
            f"[{style}]{row['status']}[/]" if style else row["status"],
            f"{row['valid_from']:%Y-%m-%d}",
            f"{row['valid_to']:%Y-%m-%d}" if row["valid_to"] else "-",
            row["content"] or "[dim](gelöscht)[/]",
        )
    console.print(table)


@app.command()
def timeline(subject: str = typer.Option(..., "--subject", "-s"), limit: int = 50) -> None:
    """Turn-Zeitleiste mit der Zustandsänderung je Beitrag."""
    with connection() as conn:
        turns = list_turns(conn, subject_id=subject, limit=limit)
        table = Table(show_header=True, header_style="bold")
        table.add_column("Turn", justify="right")
        table.add_column("Zeitpunkt")
        table.add_column("Rolle")
        table.add_column("Beitrag", overflow="fold", max_width=48)
        table.add_column("Änderung")
        for turn in turns:
            changes: list[dict[str, Any]] = []
            for item in traces_for_turn(conn, int(turn["id"])):
                changes.extend(lineage_for_trace(conn, int(item["id"])))
            counts: dict[str, int] = {}
            for change in changes:
                counts[change["op"]] = counts.get(change["op"], 0) + 1
            summary = ", ".join(f"{op}×{n}" for op, n in sorted(counts.items())) or "[dim]--[/]"
            table.add_row(
                str(turn["id"]),
                f"{turn['occurred_at']:%Y-%m-%d %H:%M}",
                turn["role"],
                "[dim](gelöscht)[/]" if turn["redacted_at"] else turn["content"],
                summary,
            )
    console.print(table)


@app.command()
def subjects() -> None:
    """Wer ist im Gedächtnis?"""
    with connection() as conn:
        rows = list_subjects(conn)
    table = Table(show_header=True, header_style="bold")
    table.add_column("Person")
    table.add_column("Beiträge", justify="right")
    table.add_column("aktive Fakten", justify="right")
    table.add_column("zuletzt")
    for row in rows:
        table.add_row(
            row["subject_id"], str(row["turns"]), str(row["active_facts"]),
            f"{row['last_seen']:%Y-%m-%d %H:%M}",
        )
    console.print(table)


@app.command("export")
def export_cmd(
    subject: str = typer.Option(..., "--subject", "-s"),
    out: Path | None = typer.Option(None, "--out", help="Zieldatei; ohne Angabe nach stdout"),
) -> None:
    """DSGVO-Auskunft als JSON."""
    with connection() as conn:
        payload = subject_export(conn, subject_id=subject)
    text = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    if out is None:
        sys.stdout.write(text + "\n")
    else:
        out.write_text(text, "utf-8")
        console.print(f"Geschrieben nach {out}")


@app.command()
def erase(
    subject: str = typer.Option(..., "--subject", "-s"),
    fact_ids: str | None = typer.Option(
        None, "--facts", help="Kommaliste von Fakt-IDs; ohne Angabe die ganze Person"
    ),
    confirm: bool = typer.Option(False, "--confirm", help="Ohne dies nur Vorschau"),
    reason: str | None = typer.Option(None, "--reason"),
) -> None:
    """Löschung mit Vorschau (Abschnitt 7)."""
    ids = [int(part) for part in fact_ids.split(",")] if fact_ids else None
    with transaction() as conn:
        plan = erasure.preview(conn, subject_id=subject, fact_ids=ids)
        table = Table(title="Betroffen", show_header=True, header_style="bold")
        table.add_column("Fakt", justify="right")
        table.add_column("Herkunft")
        table.add_column("Inhalt", overflow="fold")
        roots = set(plan.roots)
        for item in plan.facts:
            table.add_row(
                str(item["id"]),
                "genannt" if int(item["id"]) in roots else "[yellow]abgeleitet[/]",
                item["content"],
            )
        console.print(table)
        counts = plan.as_dict()["counts"]
        console.print(
            f"Kanten: {counts['edges']} · Trace-Schritte: {counts['trace_steps']} · "
            f"Beiträge: {counts['turns']} · Knoten: {counts['entities']}"
        )
        if not confirm:
            console.print("[yellow]Vorschau. Mit --confirm ausführen.[/]")
            return
        receipt = erasure.execute(conn, subject_id=subject, fact_ids=ids, reason=reason)
        console.print(f"[green]Gelöscht.[/] Löschbeleg {receipt.receipt_id}.")


@app.command("prune-traces")
def prune_traces_cmd(
    days: int = typer.Option(None, "--days", help="Vorgabe: PROVENANCE_TRACE_RETENTION_DAYS"),
    subject: str | None = typer.Option(None, "--subject"),
) -> None:
    """Reduziert alte Traces auf Metadaten; Abstammung bleibt unbefristet."""
    horizon = days if days is not None else get_settings().trace_retention_days
    with transaction() as conn:
        result = prune_traces(conn, older_than_days=horizon, subject_id=subject)
    console.print(f"Auf Metadaten reduziert: {result['reduced_steps']} Schritte (vor {result['cutoff']}).")


@app.command()
def storage() -> None:
    """Wie groß ist welche Tabelle?"""
    with connection() as conn:
        rows = storage_report(conn)
    table = Table(show_header=True, header_style="bold")
    table.add_column("Tabelle")
    table.add_column("Größe", justify="right")
    table.add_column("Zeilen", justify="right")
    for row in rows:
        table.add_row(row["tabelle"], row["groesse"], str(row["zeilen"] or 0))
    console.print(table)


@app.command()
def reindex(subject: str | None = typer.Option(None, "--subject")) -> None:
    """Baut den Volltextindex neu -- nötig nach Wechsel von PROVENANCE_FTS_CONFIG."""
    with transaction() as conn:
        count = reindex_fulltext(conn, subject_id=subject)
    console.print(f"{count} Fakten neu indiziert (Konfiguration: {get_settings().fts_config}).")


@app.command()
def serve(
    host: str | None = typer.Option(None, "--host"),
    port: int | None = typer.Option(None, "--port"),
    reload: bool = typer.Option(False, "--reload"),
) -> None:
    """Startet HTTP-API und Dashboard."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "provenance.api:app",
        host=host or settings.host,
        port=port or settings.port,
        reload=reload,
    )


@app.command("eval")
def eval_cmd(
    scenarios: Path | None = typer.Option(None, "--scenarios", help="Verzeichnis mit Szenarien"),
    only: str | None = typer.Option(None, "--only", help="Nur Szenarien, deren ID dies enthält"),
    out: Path | None = typer.Option(None, "--out", help="Ergebnis als JSON ablegen"),
    keep: bool = typer.Option(False, "--keep", help="Datenbank nach dem Lauf nicht leeren"),
) -> None:
    """Führt die Eval-Suite aus Abschnitt 9 aus."""
    from evals.runner import run_suite

    report = run_suite(scenarios_dir=scenarios, only=only, keep=keep)
    report.render(console)
    if out is not None:
        out.write_text(json.dumps(report.as_dict(), ensure_ascii=False, indent=2, default=str), "utf-8")
        console.print(f"Geschrieben nach {out}")
    if report.failed:
        raise typer.Exit(code=1)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
