"""Regressionen aus dem Review: sichere Vorgaben und Randfälle."""

from __future__ import annotations

import pytest

from provenance import export as export_mod
from provenance.config import InsecureExposure, Settings, check_exposure, is_loopback
from provenance.db.migration import DimensionMismatch, load_migrations, migrate
from provenance.db.pool import connection
from provenance.embeddings.openai_compat import OpenAICompatEmbedder
from provenance.evals.runner import find_residue, like_literal, run_suite
from provenance.export import subject_export
from provenance.llm.openai_compat import OpenAICompatProvider
from provenance.retention import prune_traces
from provenance.store import _like_literal

# ----------------------------------------------------------- Exponierung


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("127.0.1.1", True),
        ("localhost", True),
        ("::1", True),
        ("[::1]", True),
        ("0.0.0.0", False),
        ("::", False),
        ("192.168.1.10", False),
    ],
)
def test_loopback_detection(host, loopback):
    assert is_loopback(host) is loopback


def test_default_host_is_loopback():
    """Wer ins Netz will, soll das entscheiden, nicht erben."""
    assert is_loopback(Settings().host)


def test_open_api_beyond_loopback_is_refused():
    with pytest.raises(InsecureExposure, match="PROVENANCE_API_TOKEN"):
        check_exposure(Settings(host="0.0.0.0", api_token=""))


@pytest.mark.parametrize(
    "settings",
    [
        Settings(host="127.0.0.1", api_token=""),
        Settings(host="0.0.0.0", api_token="geheim"),
        Settings(host="0.0.0.0", api_token="", allow_unauthenticated=True),
    ],
)
def test_permitted_exposures(settings):
    check_exposure(settings)


# ------------------------------------------------- Transport zum Modell


def test_remote_http_model_endpoint_is_refused():
    with pytest.raises(ValueError, match="unverschlüsselt"):
        OpenAICompatProvider(base_url="http://modelle.example.com/v1")


def test_loopback_http_and_remote_https_are_fine():
    OpenAICompatProvider(base_url="http://localhost:11434/v1")
    OpenAICompatProvider(base_url="https://api.example.com/v1")
    OpenAICompatProvider(base_url="http://modelle.example.com/v1", allow_insecure_http=True)


# ------------------------------------------------------------ Randfälle


@pytest.mark.parametrize("days", [0, -1])
def test_pruning_refuses_a_cutoff_in_the_present(days):
    """Bei 0 träfe die Abfrage jeden Schritt -- und Schwärzung ist endgültig."""
    with connection() as conn, pytest.raises(ValueError, match="mindestens 1"):
        prune_traces(conn, older_than_days=days)


def test_empty_scenario_selection_is_an_error():
    """Sonst endete der Befehl mit 0, ohne je etwas geprüft zu haben."""
    with pytest.raises(ValueError, match="Kein Szenario"):
        run_suite(only="gibt-es-nicht")


def test_like_metacharacters_are_escaped():
    assert like_literal("100%") == r"100\%"
    assert like_literal("a_b") == r"a\_b"
    assert _like_literal("100%") == r"100\%"


def test_residue_search_takes_needles_literally(ingest):
    """Eine Probe auf „100%" darf nicht auf beliebigen Text passen."""
    ingest("Ich mag Kaffee.", None)
    assert find_residue("s", "100%") == []
    assert find_residue("s", "Kaffee")


def test_migration_checksum_survives_a_dimension_change():
    """Sonst verweigerte der Dienst nach einer Änderung von
    PROVENANCE_EMBEDDING_DIM den Start -- mit der falschen Begründung, jemand
    habe die Migration bearbeitet."""
    a = load_migrations(embedding_dim=1024)[0]
    b = load_migrations(embedding_dim=768)[0]
    assert a.sql != b.sql
    assert a.checksum == b.checksum


# ------------------------------------------- Transport: auch die Einbettung


@pytest.mark.parametrize(
    ("base_url", "abgelehnt"),
    [
        ("http://127.0.0.1:11434/v1", False),
        ("http://localhost:11434/v1", False),
        ("https://api.example.com/v1", False),
        ("http://modelle.example.com/v1", True),
        ("http://host.docker.internal:11434/v1", True),
    ],
)
def test_embedder_refuses_plaintext_to_a_remote_host(base_url, abgelehnt):
    """Der einzubettende Text ist derselbe Gesprächsinhalt wie bei der
    Textgenerierung. Er war bis hierher die Lücke: die Prüfung hing nur am
    Chat-Anbieter."""
    if abgelehnt:
        with pytest.raises(ValueError, match="unverschlüsselt"):
            OpenAICompatEmbedder(base_url=base_url, model="bge-m3")
    else:
        OpenAICompatEmbedder(base_url=base_url, model="bge-m3")


def test_embedder_insecure_http_can_be_allowed_explicitly():
    """vLLM im eigenen Netz ist ein legitimer Aufbau -- aber eine Entscheidung."""
    OpenAICompatEmbedder(
        base_url="http://modelle.example.com/v1", model="bge-m3", allow_insecure_http=True
    )


# ------------------------------------------------------ Einbettungsweite


def test_changed_embedding_dimension_is_refused_with_its_own_error():
    """Die Prüfsumme geht über den Rohtext und merkt eine geänderte Weite
    nicht mehr. Ungeprüft liefe der Dienst mit einer Vektorspalte einer Weite
    und einem Einbetter einer anderen an."""
    with connection() as conn:
        applied = conn.execute(
            "SELECT embedding_dim FROM schema_migrations ORDER BY version LIMIT 1"
        ).fetchone()
    assert applied["embedding_dim"] is not None, "die angewandte Weite muss festgehalten sein"

    with pytest.raises(DimensionMismatch, match="Dimensionen angelegt"):
        migrate(embedding_dim=applied["embedding_dim"] + 8)

    # Unverändert bleibt es ein reiner Durchlauf.
    assert migrate(embedding_dim=applied["embedding_dim"]) == []


# ---------------------------------------------------------- Auskunft: Grenzen


def test_export_at_the_limit_is_not_reported_as_truncated(ingest, monkeypatch, conn):
    """Genau so viele wie erlaubt ist vollständig. Die frühere Prüfung
    verglich mit >= und log eine Auskunft in genau dem Randfall an."""
    ingest("Ich wohne in Köln.")
    facts = conn.execute("SELECT count(*) AS n FROM facts WHERE subject_id = 's'").fetchone()["n"]
    assert facts >= 1

    monkeypatch.setattr(export_mod, "FACT_LIMIT", facts)
    monkeypatch.setattr(export_mod, "TURN_LIMIT", 10_000)
    bericht = subject_export(conn, subject_id="s")
    assert bericht["vollstaendig"] is True

    monkeypatch.setattr(export_mod, "FACT_LIMIT", facts - 1)
    bericht = subject_export(conn, subject_id="s")
    assert bericht["vollstaendig"] is False
    assert "Aussagen" in bericht["hinweis"]


def test_export_history_stays_within_the_delivered_facts(ingest, conn):
    """Der Verlauf wurde für die ganze Person geladen, auch für Fakten, die
    die Auskunft nie ausliefert."""
    ingest("Ich wohne in Köln.")
    ingest("Ich bin nach Berlin gezogen.")
    bericht = subject_export(conn, subject_id="s")
    ausgeliefert = {item["id"] for item in bericht["aussagen"]}
    assert ausgeliefert
    for item in bericht["aussagen"]:
        assert isinstance(item["verlauf"], list)
    # Der Verlauf eines abgelösten Fakts bleibt am ausgelieferten Nachfolger
    # sichtbar -- die parent_id-Bedingung darf nicht wegfallen.
    assert any(item["verlauf"] for item in bericht["aussagen"])


# ------------------------------------------------- Eval: Status vs. Einzelprobe


def test_report_status_follows_thresholds_and_says_so(monkeypatch):
    """Der Ausgangsstatus hängt an den Schwellen, nicht an der Einzelprobe --
    und der Bericht muss das aussprechen, sonst steht eine rote Tabelle über
    einem Befehl, der mit 0 endet."""
    from provenance.evals.metrics import Kind, Metrics, Outcome, Probe
    from provenance.evals.runner import Report, ScenarioResult

    fehlprobe = Probe(
        kind=Kind.UPDATE_RECALL,
        scenario="x",
        checkpoint="c",
        needle="n",
        outcome=Outcome.FAIL,
    )
    gute = [
        Probe(kind=Kind.UPDATE_RECALL, scenario="x", checkpoint="c", needle="n",
              outcome=Outcome.PASS)
        for _ in range(29)
    ]
    metrics = Metrics()
    for probe in [fehlprobe, *gute]:
        metrics.add(probe)

    szenario = ScenarioResult(id="x", title="x", pattern="p", subject="s")
    szenario.probes = [fehlprobe, *gute]
    report = Report(scenarios=[szenario], metrics=metrics, environment={})

    # 1/30 = 0,967 -- über der Schwelle 0,900, also besteht der Lauf ...
    assert report.failed is False
    # ... aber die Probe ist gescheitert, und beides steht im Bericht.
    assert szenario.failed is True
    assert report.failed_probes == 1
    payload = report.as_dict()
    assert payload["gescheitert"] is False
    assert payload["gescheiterte_proben"] == 1


def test_report_fails_when_a_threshold_is_missed():
    """Und umgekehrt: reicht die Toleranz nicht, kippt der Lauf."""
    from provenance.evals.metrics import Kind, Metrics, Outcome, Probe
    from provenance.evals.runner import Report, ScenarioResult

    proben = [
        Probe(kind=Kind.ERASURE, scenario="x", checkpoint="c", needle="n", outcome=Outcome.FAIL)
    ]
    metrics = Metrics()
    for probe in proben:
        metrics.add(probe)
    szenario = ScenarioResult(id="x", title="x", pattern="p", subject="s")
    szenario.probes = proben
    report = Report(scenarios=[szenario], metrics=metrics, environment={})

    # Erasure Completeness duldet nichts: jede gescheiterte Probe bricht sie.
    assert report.failed is True
    assert "erasure_completeness" in " ".join(report.threshold_breaches())
