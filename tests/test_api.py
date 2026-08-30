"""Die HTTP-Schnittstelle aus Abschnitt 8."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from provenance.api import create_app, reset_service
from provenance.config import get_settings


@pytest.fixture
def client():
    reset_service()
    with TestClient(create_app()) as test_client:
        yield test_client


def post_turn(client, text: str, when: str, subject: str = "s"):
    response = client.post(
        "/v1/turns",
        json={"subject_id": subject, "session_id": "t", "content": text, "occurred_at": when},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_healthz_reports_prompt_versions(client):
    body = client.get("/healthz").json()
    assert body["status"] == "ok"
    assert body["prompts"]["extract.v1"].startswith("extract.v1@")


def test_ingest_and_recall(client):
    post_turn(client, "Ich wohne in Köln.", "2026-01-10T12:00:00Z")
    post_turn(client, "Ich bin nach Leipzig gezogen.", "2026-06-14T12:00:00Z")

    body = client.get("/v1/recall", params={"subject_id": "s", "query": "Wo wohnt er?"}).json()
    assert "Leipzig" in body["context"]
    assert "Köln" not in body["context"]
    assert body["facts"][0]["sources"]


def test_recall_accepts_both_time_axes(client):
    post_turn(client, "Ich wohne in Köln.", "2026-01-10T12:00:00Z")
    post_turn(client, "Ich bin nach Leipzig gezogen.", "2026-06-14T12:00:00Z")

    body = client.get(
        "/v1/recall",
        params={"subject_id": "s", "query": "Wo wohnt er?", "as_of_valid_time": "2026-03-01T00:00:00Z"},
    ).json()
    assert "Köln" in body["context"]


def test_trace_endpoint_returns_all_four_stages(client):
    ingest = post_turn(client, "Ich wohne in Köln.", "2026-01-10T12:00:00Z")
    client.get("/v1/recall", params={"subject_id": "s", "query": "Wo?"})

    body = client.get(f"/v1/traces/{ingest['trace_id']}").json()
    assert {step["stage"] for step in body["steps"]} == {1, 2}
    assert body["lineage"][0]["op"] == "add"

    read = client.get("/v1/traces", params={"subject_id": "s", "kind": "read"}).json()
    read_trace = client.get(f"/v1/traces/{read['traces'][0]['id']}").json()
    assert {step["stage"] for step in read_trace["steps"]} == {3, 4}


def test_unknown_trace_is_404(client):
    assert client.get("/v1/traces/999999").status_code == 404


def test_export_is_readable_without_model_internals(client):
    post_turn(client, "Ich wohne in Köln.", "2026-01-10T12:00:00Z")
    body = client.get("/v1/subjects/s/export").json()
    assert body["betroffene_person"] == "s"
    assert body["aussagen"][0]["aussage"] == "Wohnt in Köln."
    assert body["aussagen"][0]["quelle"]["wortlaut"] == "Ich wohne in Köln."
    assert body["aussagen"][0]["status"] == "gilt"
    # Die Auskunftsansicht zeigt keine Modell-Interna.
    assert "prompt_ref" not in str(body)
    assert "embedding" not in str(body)


def test_erase_previews_before_it_deletes(client):
    post_turn(client, "Ich wohne in Köln.", "2026-01-10T12:00:00Z")
    post_turn(client, "Ich bin nach Leipzig gezogen.", "2026-06-14T12:00:00Z")

    preview = client.post("/v1/subjects/s/erase", json={"fact_ids": [1]}).json()
    assert preview["ausgefuehrt"] is False
    assert preview["vorschau"]["derived"] == [2]

    still_there = client.get("/v1/subjects/s/facts", params={"include_inactive": True}).json()
    assert len(still_there["facts"]) == 2

    done = client.post("/v1/subjects/s/erase", json={"fact_ids": [1], "confirm": True}).json()
    assert done["ausgefuehrt"] is True
    assert done["beleg"]["receipt_id"] > 0

    after = client.get("/v1/recall", params={"subject_id": "s", "query": "Wo wohnt er?"}).json()
    assert after["context"] == ""


def test_timeline_summarises_each_turn(client):
    post_turn(client, "Ich wohne in Köln.", "2026-01-10T12:00:00Z")
    post_turn(client, "Ich bin nach Leipzig gezogen.", "2026-06-14T12:00:00Z")
    body = client.get("/v1/subjects/s/timeline").json()
    assert [item["summary"] for item in body["timeline"]] == [{"add": 1}, {"update": 1}]


def test_graph_endpoint_exposes_the_supporting_fact(client):
    post_turn(client, "Ich arbeite bei ACME.", "2026-01-10T12:00:00Z")
    body = client.get("/v1/subjects/s/graph").json()
    assert body["edges"][0]["fact_content"] == "Arbeitet bei ACME."


def test_replay_endpoint_diffs(client):
    post_turn(client, "Ich wohne in Köln.", "2026-01-10T12:00:00Z")
    body = client.post("/v1/replay", json={"subject_id": "s"}).json()
    assert body["turns_replayed"] == 1
    assert body["differs"] is False


def test_dashboard_pages_render(client):
    for path in ("/ui/", "/ui/auskunft"):
        response = client.get(path)
        assert response.status_code == 200
        assert "provenance" in response.text
        assert "/*SHARED_CSS*/" not in response.text


def test_bearer_token_is_enforced_when_configured(monkeypatch):
    from provenance.config import reset_settings_cache

    monkeypatch.setenv("PROVENANCE_API_TOKEN", "geheim")
    reset_settings_cache()
    reset_service()
    try:
        with TestClient(create_app(get_settings())) as client:
            assert client.get("/v1/subjects").status_code == 401
            ok = client.get("/v1/subjects", headers={"Authorization": "Bearer geheim"})
            assert ok.status_code == 200
            # Der Betriebsendpunkt bleibt offen, damit Health-Checks funktionieren.
            assert client.get("/healthz").status_code == 200
    finally:
        monkeypatch.delenv("PROVENANCE_API_TOKEN", raising=False)
        reset_settings_cache()
        reset_service()
