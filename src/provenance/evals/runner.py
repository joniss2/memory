"""Der Eval-Läufer.

Skriptgeführte Sitzungen, in denen sich Fakten planmäßig ändern, mit
Prüffragen an definierten Kontrollpunkten (Abschnitt 9).

Zwei Entwurfsentscheidungen, die die Zahlen ehrlich halten:

* Gemessen wird gegen den Text aus Stufe 4, nicht gegen die Trefferliste aus
  Stufe 3. Was am Budget scheitert, ist für den Agenten abwesend.
* Jedes Szenario läuft unter einer eigenen Kennung (``eval:<id>``) und wird
  vorher restlos geräumt. Kein Szenario kann von einem anderen profitieren.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from provenance.config import Settings, get_settings
from provenance.db.migration import migrate
from provenance.db.pool import connection, transaction
from provenance.erasure import execute as execute_erasure
from provenance.evals.metrics import Kind, Metrics, Outcome, Probe, matches
from provenance.prompts import prompt_refs
from provenance.replay import purge_subject
from provenance.service import MemoryService

SCENARIOS_DIR = Path(__file__).parent / "scenarios"

# Erasure Completeness ist keine Qualitätskennzahl, sondern eine Zusage. Sie
# muss 1.0 sein; alles andere ist ein Fehler, kein schlechterer Wert.
DEFAULT_THRESHOLDS = {
    "update_recall": 0.90,
    "stale_rate": 0.10,
    "false_retraction": 0.05,
    "erasure_completeness": 1.0,
}


@dataclass(slots=True)
class ScenarioResult:
    id: str
    title: str
    pattern: str
    subject: str
    turns: int = 0
    probes: list[Probe] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    missing_preconditions: list[str] = field(default_factory=list)
    error: str | None = None

    @property
    def failed(self) -> bool:
        return self.error is not None or any(probe.failed for probe in self.probes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "pattern": self.pattern,
            "subject": self.subject,
            "turns": self.turns,
            "failed": self.failed,
            "error": self.error,
            "notes": self.notes,
            "fehlende_vorbedingungen": self.missing_preconditions,
            "probes": [probe.as_dict() for probe in self.probes],
        }


@dataclass(slots=True)
class Report:
    scenarios: list[ScenarioResult]
    metrics: Metrics
    environment: dict[str, Any]
    thresholds: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))

    @property
    def failed(self) -> bool:
        return bool(self.threshold_breaches()) or any(
            scenario.error is not None for scenario in self.scenarios
        )

    def threshold_breaches(self) -> list[str]:
        summary = self.metrics.summary()
        breaches: list[str] = []
        for name, limit in self.thresholds.items():
            value = summary[name]["wert"]
            if value is None:
                continue
            worse = value < limit if name in {"update_recall", "erasure_completeness"} else value > limit
            if worse:
                breaches.append(f"{name}={value:.3f} verfehlt {limit:.3f}")
        return breaches

    def as_dict(self) -> dict[str, Any]:
        return {
            "environment": self.environment,
            "kennzahlen": self.metrics.summary(),
            "schwellen": self.thresholds,
            "verfehlt": self.threshold_breaches(),
            "szenarien": [scenario.as_dict() for scenario in self.scenarios],
        }

    def render(self, console: Any) -> None:
        from rich.table import Table

        table = Table(title="Szenarien", show_header=True, header_style="bold")
        table.add_column("Szenario")
        table.add_column("Muster")
        table.add_column("Turns", justify="right")
        table.add_column("Proben", justify="right")
        table.add_column("Befund")
        for scenario in self.scenarios:
            failures = [probe for probe in scenario.probes if probe.failed]
            unsupported = [
                probe for probe in scenario.probes if probe.outcome is Outcome.UNSUPPORTED
            ]
            if scenario.error:
                verdict = f"[red]Fehler: {scenario.error[:60]}[/]"
            elif failures:
                verdict = "[red]" + ", ".join(
                    f"{probe.kind.value}: {probe.needle}" for probe in failures[:3]
                ) + "[/]"
            elif scenario.missing_preconditions:
                verdict = "[yellow]Vorbedingung fehlt: " + ", ".join(
                    scenario.missing_preconditions
                ) + "[/]"
            elif unsupported:
                verdict = f"[yellow]{len(unsupported)} Probe(n) ohne Grundlage[/]"
            else:
                verdict = "[green]ok[/]"
            table.add_row(
                scenario.id, scenario.pattern, str(scenario.turns), str(len(scenario.probes)), verdict
            )
        console.print(table)

        summary = self.metrics.summary()
        headline = Table(title="Kennzahlen", show_header=True, header_style="bold")
        headline.add_column("Kennzahl")
        headline.add_column("Wert", justify="right")
        headline.add_column("Schwelle", justify="right")
        headline.add_column("Proben", justify="right")
        headline.add_column("")
        labels = {
            "update_recall": ("Update Recall", "hoch ist gut"),
            "stale_rate": ("Stale Rate", "niedrig ist gut"),
            "false_retraction": ("False Retraction", "niedrig ist gut"),
            "erasure_completeness": ("Erasure Completeness", "muss 1,000 sein"),
        }
        breaches = set()
        for breach in self.threshold_breaches():
            breaches.add(breach.split("=")[0])
        for key, (label, hint) in labels.items():
            entry = summary[key]
            value = entry["wert"]
            text = "—" if value is None else f"{value:.3f}"
            style = "red" if key in breaches else "green"
            note = hint
            if entry["ohne_grundlage"]:
                note += f" · {entry['ohne_grundlage']} ohne Grundlage"
            headline.add_row(
                label,
                f"[{style}]{text}[/]",
                f"{self.thresholds[key]:.3f}",
                str(entry["proben"]),
                f"[dim]{note}[/]",
            )
        console.print(headline)

        by_pattern = Table(title="Nach Muster", show_header=True, header_style="bold")
        by_pattern.add_column("Muster")
        by_pattern.add_column("Szenarien", justify="right")
        by_pattern.add_column("Proben", justify="right")
        by_pattern.add_column("gescheitert", justify="right")
        by_pattern.add_column("ohne Grundlage", justify="right")
        patterns: dict[str, list[ScenarioResult]] = {}
        for scenario in self.scenarios:
            patterns.setdefault(scenario.pattern, []).append(scenario)
        for pattern, group in sorted(patterns.items()):
            probes = [probe for scenario in group for probe in scenario.probes]
            failed = sum(1 for probe in probes if probe.failed)
            weak = sum(1 for probe in probes if probe.outcome is Outcome.UNSUPPORTED)
            by_pattern.add_row(
                pattern,
                str(len(group)),
                str(len(probes)),
                f"[red]{failed}[/]" if failed else "0",
                f"[yellow]{weak}[/]" if weak else "0",
            )
        console.print(by_pattern)

        failures = [probe for scenario in self.scenarios for probe in scenario.probes if probe.failed]
        if failures:
            detail = Table(title="Gescheiterte Proben", show_header=True, header_style="bold")
            detail.add_column("Szenario")
            detail.add_column("Kontrollpunkt")
            detail.add_column("Kennzahl")
            detail.add_column("Probe")
            detail.add_column("Befund", overflow="fold")
            for probe in failures:
                detail.add_row(
                    probe.scenario, probe.checkpoint, probe.kind.value, probe.needle, probe.detail
                )
            console.print(detail)

        console.print(
            f"[dim]Modell: {self.environment['llm_provider']} · "
            f"Einbettung: {self.environment['embedding_provider']} · "
            f"Prompts: {', '.join(self.environment['prompts'].values())}[/]"
        )
        if self.environment["llm_provider"] == "heuristic":
            console.print(
                "[yellow]Hinweis:[/] Der Lauf misst den deterministischen Ersatz aus "
                "provenance.llm.heuristic, nicht ein Sprachmodell. Die Zahlen sagen etwas "
                "über die Mechanik der Pipeline aus, nichts über Sprachverständnis. "
                "Für eine Qualitätsaussage PROVENANCE_LLM_PROVIDER=openai setzen."
            )


# ------------------------------------------------------------------- Laden


def load_scenarios(directory: Path | None = None, only: str | None = None) -> list[dict[str, Any]]:
    directory = directory or SCENARIOS_DIR
    scenarios: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text("utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{path}: ein Szenario je Datei, als Zuordnung erwartet")
        data.setdefault("id", path.stem)
        if only and only not in str(data["id"]):
            continue
        scenarios.append(data)
    return scenarios


# ------------------------------------------------------------------ Ausführung


def run_suite(
    scenarios_dir: Path | None = None,
    only: str | None = None,
    keep: bool = False,
    settings: Settings | None = None,
) -> Report:
    settings = settings or get_settings()
    migrate()
    service = MemoryService(settings=settings)
    metrics = Metrics()
    results: list[ScenarioResult] = []

    scenarios = load_scenarios(scenarios_dir, only)
    if not scenarios:
        # Sonst meldete die Suite „keine Probe gescheitert" und der Befehl
        # endete mit 0, ohne je etwas geprüft zu haben.
        raise ValueError(
            f"Kein Szenario ausgewählt (Filter {only!r})."
            if only
            else "Keine Szenarien gefunden."
        )
    for scenario in scenarios:
        result = run_scenario(scenario, service=service, metrics=metrics, keep=keep)
        results.append(result)

    return Report(
        scenarios=results,
        metrics=metrics,
        environment={
            "llm_provider": settings.llm_provider,
            "llm_model": settings.llm_model_extract,
            "embedding_provider": settings.embedding_provider,
            "embedding_dim": settings.embedding_dim,
            "prompts": prompt_refs(),
            "thresholds": {
                "add": settings.add_min_confidence,
                "update": settings.update_min_confidence,
                "retract": settings.retract_min_confidence,
            },
            "injection_token_budget": settings.injection_token_budget,
            "run_at": datetime.now(UTC).isoformat(),
        },
    )


def run_scenario(
    scenario: dict[str, Any], *, service: MemoryService, metrics: Metrics, keep: bool = False
) -> ScenarioResult:
    scenario_id = str(scenario["id"])
    subject = f"eval:{scenario_id}"
    result = ScenarioResult(
        id=scenario_id,
        title=str(scenario.get("title") or scenario_id),
        pattern=str(scenario.get("pattern") or "—"),
        subject=subject,
    )

    try:
        with transaction() as conn:
            purge_subject(conn, subject)

        turns = list(scenario.get("turns") or [])
        checkpoints = list(scenario.get("checkpoints") or [])
        erasures = scenario.get("erasure")
        erasure_blocks = (
            [erasures] if isinstance(erasures, dict) else list(erasures or [])
        )

        preconditions = list(scenario.get("preconditions") or [])

        for index, turn in enumerate(turns, start=1):
            service.ingest_turn(
                subject_id=subject,
                session_id=str(scenario.get("session") or "eval"),
                role=str(turn.get("role") or "user"),
                content=str(turn["text"]),
                occurred_at=_parse_at(turn.get("at")),
            )
            result.turns = index

            for checkpoint in checkpoints:
                if int(checkpoint.get("after", len(turns))) == index:
                    _run_checkpoint(checkpoint, scenario_id, subject, service, metrics, result)

            for block in erasure_blocks:
                if int(block.get("after", len(turns))) == index:
                    _run_erasure(block, scenario_id, subject, metrics, result)

        _check_preconditions(preconditions, subject, result)

    except Exception as exc:  # noqa: BLE001 - ein Szenario darf die Suite nicht abbrechen
        result.error = f"{type(exc).__name__}: {exc}"
    finally:
        if not keep:
            with transaction() as conn:
                purge_subject(conn, subject)

    return result


def _run_checkpoint(
    checkpoint: dict[str, Any],
    scenario_id: str,
    subject: str,
    service: MemoryService,
    metrics: Metrics,
    result: ScenarioResult,
) -> None:
    name = str(checkpoint.get("name") or f"nach Turn {checkpoint.get('after')}")
    query = str(checkpoint["query"])
    recall = service.recall(subject_id=subject, query=query, limit=checkpoint.get("limit"))
    context = recall.injection.text

    if recall.injection.dropped:
        result.notes.append(
            f"{name}: {len(recall.injection.dropped)} Fakten am Token-Budget gescheitert"
        )

    for needle in checkpoint.get("expect_present") or []:
        found = matches(needle, context)
        _record(
            metrics,
            result,
            Probe(
                kind=Kind.UPDATE_RECALL,
                scenario=scenario_id,
                checkpoint=name,
                needle=str(needle),
                outcome=Outcome.PASS if found else Outcome.FAIL,
                detail="" if found else f"nicht im gestellten Kontext: {context!r}"[:400],
            ),
        )

    for needle in checkpoint.get("expect_absent") or []:
        _record(metrics, result, _check_stale(str(needle), scenario_id, name, subject, context))

    for needle in checkpoint.get("must_stay_active") or []:
        _record(metrics, result, _check_still_active(needle, scenario_id, name, subject))


def _check_stale(
    needle: str, scenario_id: str, checkpoint: str, subject: str, context: str
) -> Probe:
    """Stale Rate: wird der überholte Wert weiterhin geliefert?

    Eine Stale-Probe trägt nur, wenn der Wert überhaupt einmal gespeichert
    war. Wurde er nie extrahiert, sagt ihr Bestehen nichts über die
    Konsolidierung aus -- sie zählt dann nicht in den Nenner. Ohne diese
    Unterscheidung sähe ein System, das gar nichts extrahiert, in genau der
    Kennzahl gut aus, die es entlarven soll.
    """
    if matches(needle, context):
        return Probe(
            kind=Kind.STALE,
            scenario=scenario_id,
            checkpoint=checkpoint,
            needle=needle,
            outcome=Outcome.FAIL,
            detail="überholter Wert wird weiterhin geliefert",
        )
    with connection() as conn:
        rows = conn.execute(
            "SELECT content FROM facts WHERE subject_id = %s", (subject,)
        ).fetchall()
    if any(matches(needle, row["content"] or "") for row in rows):
        return Probe(
            kind=Kind.STALE, scenario=scenario_id, checkpoint=checkpoint, needle=needle,
            outcome=Outcome.PASS,
        )
    return Probe(
        kind=Kind.STALE,
        scenario=scenario_id,
        checkpoint=checkpoint,
        needle=needle,
        outcome=Outcome.UNSUPPORTED,
        detail="Wert war nie gespeichert -- die Probe kann keinen Stale-Fall zeigen.",
    )


def _check_still_active(needle: str, scenario_id: str, checkpoint: str, subject: str) -> Probe:
    """False Retraction: hat ein Scheinwiderspruch einen korrekten Fakt gekillt?"""
    with connection() as conn:
        rows = conn.execute(
            "SELECT id, content, status FROM facts WHERE subject_id = %s ORDER BY id",
            (subject,),
        ).fetchall()

    candidates = [row for row in rows if matches(needle, row["content"] or "")]
    if not candidates:
        # Nie extrahiert: ein Befund für Stufe 1, aber kein Rückzug. Zählt
        # deshalb nicht in die Quote.
        return Probe(
            kind=Kind.FALSE_RETRACTION,
            scenario=scenario_id,
            checkpoint=checkpoint,
            needle=needle,
            outcome=Outcome.UNSUPPORTED,
            detail="Kein Fakt zu dieser Probe vorhanden -- in Stufe 1 nie extrahiert.",
        )
    active = [row for row in candidates if row["status"] == "active"]
    if active:
        return Probe(
            kind=Kind.FALSE_RETRACTION,
            scenario=scenario_id,
            checkpoint=checkpoint,
            needle=needle,
            outcome=Outcome.PASS,
        )
    states = ", ".join(f"#{row['id']} {row['status']}" for row in candidates)
    return Probe(
        kind=Kind.FALSE_RETRACTION,
        scenario=scenario_id,
        checkpoint=checkpoint,
        needle=needle,
        outcome=Outcome.FAIL,
        detail=f"korrekter Fakt nicht mehr aktiv ({states})",
    )


def _check_preconditions(
    preconditions: list[Any], subject: str, result: ScenarioResult
) -> None:
    """Prüft, ob das Szenario überhaupt das ausgeübt hat, was es prüfen will.

    Ein Scheinwiderspruch-Szenario, dessen widersprüchlicher Satz in Stufe 1
    gar nicht erst zu einem Fakt wurde, hat die Konsolidierung nie
    beansprucht. Seine Proben bestehen dann aus dem falschen Grund. Das ist
    kein Fehler der Pipeline, aber es muss im Bericht stehen -- sonst liest
    man eine Extraktionslücke als Konsolidierungsstärke.
    """
    if not preconditions:
        return
    with connection() as conn:
        rows = conn.execute("SELECT content FROM facts WHERE subject_id = %s", (subject,)).fetchall()
    contents = [row["content"] or "" for row in rows]
    for needle in preconditions:
        if not any(matches(str(needle), content) for content in contents):
            result.missing_preconditions.append(str(needle))
    if result.missing_preconditions:
        result.notes.append(
            "Vorbedingung nicht erfüllt: zu "
            + ", ".join(repr(item) for item in result.missing_preconditions)
            + " wurde kein Fakt angelegt; die Proben dieses Szenarios laufen ins Leere."
        )


def _run_erasure(
    block: dict[str, Any],
    scenario_id: str,
    subject: str,
    metrics: Metrics,
    result: ScenarioResult,
) -> None:
    """Löscht und prüft danach, ob wirklich nichts übrig ist."""
    name = str(block.get("name") or f"Löschung nach Turn {block.get('after')}")
    pattern = block.get("facts_matching")

    with transaction() as conn:
        fact_ids: list[int] | None = None
        if pattern:
            rows = conn.execute(
                "SELECT id, content FROM facts WHERE subject_id = %s AND status <> 'erased'",
                (subject,),
            ).fetchall()
            fact_ids = [int(row["id"]) for row in rows if matches(str(pattern), row["content"] or "")]
            if not fact_ids:
                result.notes.append(f"{name}: kein Fakt passt auf {pattern!r}, nichts zu löschen")
        receipt = execute_erasure(
            conn,
            subject_id=subject,
            fact_ids=fact_ids,
            reason=f"Eval {scenario_id}",
            requested_by="evals",
        )
        result.notes.append(
            f"{name}: {len(receipt.preview.fact_ids)} Fakten gelöscht "
            f"(davon {len(receipt.preview.derived)} abgeleitet)"
        )

    for needle in block.get("residue") or []:
        locations = find_residue(subject, str(needle))
        _record(
            metrics,
            result,
            Probe(
                kind=Kind.ERASURE,
                scenario=scenario_id,
                checkpoint=name,
                needle=str(needle),
                outcome=Outcome.PASS if not locations else Outcome.FAIL,
                detail="" if not locations else "Rest gefunden in: " + ", ".join(locations),
            ),
        )


def like_literal(needle: str) -> str:
    """Maskiert LIKE-Metazeichen, damit eine Probe wörtlich gesucht wird.

    ``%`` und ``_`` sind in ``ILIKE`` Platzhalter. Eine Probe auf „100%" würde
    sonst auf beliebigen Text passen und eine Löschung fälschlich als
    unvollständig melden.
    """
    return needle.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


#: Jede Spalte, in der ein gelöschter Wert im Klartext stehen könnte. Die
#: Liste ist der eigentliche Inhalt der Zusage „Erasure Completeness" -- was
#: hier fehlt, kann die Kennzahl nicht sehen.
RESIDUE_CHECKS: tuple[tuple[str, str], ...] = (
    ("facts.content", "SELECT count(*) AS n FROM facts WHERE subject_id = %(s)s AND content ILIKE %(p)s"),
    ("turns.content", "SELECT count(*) AS n FROM turns WHERE subject_id = %(s)s AND content ILIKE %(p)s"),
    ("entities.name", "SELECT count(*) AS n FROM entities WHERE subject_id = %(s)s AND name ILIKE %(p)s"),
    (
        "lineage.rationale",
        "SELECT count(*) AS n FROM lineage l JOIN facts f ON f.id = l.fact_id "
        "WHERE f.subject_id = %(s)s AND l.rationale ILIKE %(p)s",
    ),
    (
        "traces.query",
        "SELECT count(*) AS n FROM traces WHERE subject_id = %(s)s AND query ILIKE %(p)s",
    ),
    (
        "trace_steps",
        "SELECT count(*) AS n FROM trace_steps ts JOIN traces t ON t.id = ts.trace_id "
        "WHERE t.subject_id = %(s)s AND (ts.input::text ILIKE %(p)s "
        "OR ts.output::text ILIKE %(p)s)",
    ),
)


def find_residue(subject: str, needle: str) -> list[str]:
    """Sucht einen gelöschten Wert überall dort, wo er stehen könnte.

    Fakten, Rohbeiträge, Graphknoten, Abstammungsbegründungen, Trace-Fragen
    *und* die Trace-Schritte. Die letzten drei sind die Stelle, an der
    Systeme mit getrenntem Auditlog auffliegen -- und waren bis zuletzt auch
    hier die Lücke.
    """
    params = {"s": subject, "p": f"%{like_literal(needle)}%"}
    found: list[str] = []
    with connection() as conn:
        for label, sql in RESIDUE_CHECKS:
            row = conn.execute(sql, params).fetchone()
            if row and int(row["n"]) > 0:
                found.append(f"{label} ({row['n']}×)")
    return found


def _record(metrics: Metrics, result: ScenarioResult, probe: Probe) -> None:
    metrics.add(probe)
    result.probes.append(probe)


def _parse_at(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    text = str(value).strip().replace("Z", "+00:00")
    for candidate in (text, f"{text}T12:00:00+00:00"):
        try:
            parsed = datetime.fromisoformat(candidate)
        except ValueError:
            continue
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    raise ValueError(f"unlesbarer Zeitpunkt: {value!r}")
