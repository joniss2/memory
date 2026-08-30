"""Regressionen aus dem Review: sichere Vorgaben und Randfälle."""

from __future__ import annotations

import pytest

from provenance.config import InsecureExposure, Settings, check_exposure, is_loopback
from provenance.db.migration import load_migrations
from provenance.db.pool import connection
from provenance.evals.runner import find_residue, like_literal, run_suite
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
