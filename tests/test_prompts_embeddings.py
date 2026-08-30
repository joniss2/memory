"""Prompt-Versionierung, Einbettungen und die Kennzahlen selbst."""

from __future__ import annotations

import math

import pytest

from provenance.embeddings.hashing import HashingEmbedder
from provenance.evals.metrics import Kind, Metrics, Outcome, Probe, matches
from provenance.llm.base import LLMError, parse_json_object
from provenance.prompts import PROMPTS_DIR, load_prompt, prompt_refs


def test_prompt_ref_follows_the_content(tmp_path, monkeypatch):
    """Jede Bearbeitung der Vorlage ändert die Kennung -- auch die ohne
    hochgezählte Versionsnummer."""
    original = (PROMPTS_DIR / "extract.v1.md").read_text("utf-8")
    first = load_prompt("extract.v1").ref
    try:
        (PROMPTS_DIR / "extract.v1.md").write_text(original + "\nein Wort mehr\n", "utf-8")
        load_prompt.cache_clear()
        assert load_prompt("extract.v1").ref != first
    finally:
        (PROMPTS_DIR / "extract.v1.md").write_text(original, "utf-8")
        load_prompt.cache_clear()
    assert load_prompt("extract.v1").ref == first


def test_prompt_render_requires_every_placeholder():
    prompt = load_prompt("extract.v1")
    with pytest.raises(KeyError):
        prompt.render(subject_label="s")


def test_all_prompts_are_loadable():
    refs = prompt_refs()
    assert set(refs) == {"extract.v1", "consolidate.v1"}


def test_json_parser_tolerates_fences_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Gern! {"a": 1}') == {"a": 1}
    with pytest.raises(LLMError):
        parse_json_object("gar kein JSON")
    with pytest.raises(LLMError):
        parse_json_object("")


def test_hashing_embedder_is_deterministic_and_normalised():
    embedder = HashingEmbedder(dim=64)
    a, b = embedder.embed(["Wohnt in Köln.", "Wohnt in Köln."])
    assert a == b
    assert math.isclose(math.sqrt(sum(v * v for v in a)), 1.0, rel_tol=1e-9)


def test_hashing_embedder_handles_empty_text():
    """Ein Nullvektor hätte keinen definierten Kosinusabstand."""
    vector = HashingEmbedder(dim=32).embed([""])[0]
    assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-9)


def test_hashing_embedder_sees_inflection_through_ngrams():
    embedder = HashingEmbedder(dim=1024)
    wohnt, wohne, fremd = embedder.embed(["wohnt in Köln", "wohne in Köln", "mag Kaffee"])
    close = sum(x * y for x, y in zip(wohnt, wohne, strict=True))
    far = sum(x * y for x, y in zip(wohnt, fremd, strict=True))
    assert close > far


def test_needle_matching_supports_regex():
    assert matches("köln", "Wohnt in Köln.")
    assert matches("re:wohnt\\s+in", "Wohnt in Köln.")
    assert not matches("Bonn", "Wohnt in Köln.")


def test_stale_rate_counts_failures_not_passes():
    metrics = Metrics()
    metrics.add(Probe(Kind.STALE, "x", "c", "alt", Outcome.FAIL))
    metrics.add(Probe(Kind.STALE, "x", "c", "alt2", Outcome.PASS))
    assert metrics.stale_rate == 0.5


def test_probes_without_basis_stay_out_of_the_denominator():
    """Sonst sähe ein System, das gar nichts extrahiert, hier gut aus."""
    metrics = Metrics()
    metrics.add(Probe(Kind.FALSE_RETRACTION, "x", "c", "a", Outcome.PASS))
    metrics.add(Probe(Kind.FALSE_RETRACTION, "x", "c", "b", Outcome.UNSUPPORTED))
    assert metrics.false_retraction == 0.0
    assert metrics.summary()["false_retraction"]["proben"] == 1
    assert metrics.summary()["false_retraction"]["ohne_grundlage"] == 1


def test_metric_without_probes_is_none():
    assert Metrics().update_recall is None
