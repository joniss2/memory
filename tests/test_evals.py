"""Die Eval-Suite selbst -- sie ist Teil des Produkts, also wird sie getestet."""

from __future__ import annotations

from evals.metrics import Kind, Outcome
from evals.runner import DEFAULT_THRESHOLDS, load_scenarios, run_suite


def test_twenty_scenarios_across_five_patterns():
    scenarios = load_scenarios()
    assert len(scenarios) == 20
    patterns: dict[str, int] = {}
    for scenario in scenarios:
        patterns[scenario["pattern"]] = patterns.get(scenario["pattern"], 0) + 1
    assert patterns == {
        "Ersetzung": 4, "Verfeinerung": 4, "Befristung": 4,
        "Scheinwiderspruch": 4, "Widerruf": 4,
    }


def test_every_scenario_has_a_checkpoint():
    for scenario in load_scenarios():
        assert scenario.get("turns"), f"{scenario['id']} hat keine Beiträge"
        assert scenario.get("checkpoints"), f"{scenario['id']} hat keinen Kontrollpunkt"


def test_replacement_scenario_passes_all_four_metrics():
    report = run_suite(only="01-ersetzung")
    assert not report.failed
    assert report.threshold_breaches() == []
    summary = report.metrics.summary()
    assert summary["update_recall"]["wert"] == 1.0
    assert summary["stale_rate"]["wert"] == 0.0
    assert summary["erasure_completeness"]["wert"] == 1.0


def test_erasure_probe_checks_every_store():
    """Erasure Completeness ist keine Qualitätskennzahl, sondern eine Zusage."""
    report = run_suite(only="01-ersetzung")
    probes = [p for s in report.scenarios for p in s.probes if p.kind is Kind.ERASURE]
    # Köln ist die Wurzel, Leipzig daraus abgeleitet -- beide müssen weg sein.
    assert {probe.needle for probe in probes} == {"Köln", "Leipzig"}
    assert all(probe.outcome is Outcome.PASS for probe in probes)
    assert DEFAULT_THRESHOLDS["erasure_completeness"] == 1.0


def test_naive_baseline_is_caught_by_the_stale_rate():
    """Eine Eval, die nur das eigene Vorgehen bewertet, könnte zu leicht sein.

    Der naive Vergleichsmaßstab überschreibt nach Ähnlichkeit und hat keinen
    Begriff von Widerruf. Auf dem Update Recall -- der Kennzahl, die gängige
    Benchmarks ausweisen -- ist er nicht zu unterscheiden; die Stale Rate
    entlarvt ihn.
    """
    from provenance.config import Settings
    from provenance.service import MemoryService

    naive = Settings(llm_provider="naive")
    strict_report = run_suite(only="17-widerruf")
    naive_report = run_suite(only="17-widerruf", settings=naive)
    assert isinstance(MemoryService(settings=naive).llm.name, str)

    assert strict_report.metrics.update_recall == naive_report.metrics.update_recall
    assert strict_report.metrics.stale_rate == 0.0
    assert naive_report.metrics.stale_rate == 1.0
    assert "stale_rate" in " ".join(naive_report.threshold_breaches())


def test_report_serialises():
    report = run_suite(only="18-widerruf")
    payload = report.as_dict()
    assert payload["environment"]["prompts"]
    assert payload["kennzahlen"]["stale_rate"]["proben"] >= 1
    assert payload["szenarien"][0]["id"] == "18-widerruf-wohnort"


def test_scenario_error_does_not_abort_the_suite(tmp_path):
    (tmp_path / "kaputt.yaml").write_text(
        "title: kaputt\npattern: Ersetzung\nturns:\n  - at: kein-datum\n    text: x\n"
        "checkpoints:\n  - after: 1\n    query: q\n",
        "utf-8",
    )
    (tmp_path / "heil.yaml").write_text(
        "title: heil\npattern: Ersetzung\nturns:\n  - at: 2026-01-01\n    text: Ich wohne in Köln.\n"
        "checkpoints:\n  - after: 1\n    query: Wo wohnt er?\n    expect_present: [Köln]\n",
        "utf-8",
    )
    report = run_suite(scenarios_dir=tmp_path)
    errors = [scenario for scenario in report.scenarios if scenario.error]
    assert len(errors) == 1
    assert "kein-datum" in errors[0].error
    # Das heile Szenario ist trotzdem gelaufen.
    assert report.metrics.update_recall == 1.0
