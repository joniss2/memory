"""Stufe 3 -- Retrieval.

Drei Kandidatenquellen, fusioniert über Reciprocal Rank Fusion. Alle drei
laufen in Postgres: ein Netzwerk-Hop weniger, eine Transaktion, ein
konsistenter Zeitpunkt (Abschnitt 5, Stufe 3).

Der Trace hält für jeden Kandidaten fest, aus welcher Quelle er kam, mit
welchem Rang -- und wie die Fusion ihn platziert hat.
"""

from __future__ import annotations

import time
from typing import Any

import psycopg

from provenance.config import Settings
from provenance.embeddings.base import Embedder
from provenance.pipeline.types import RetrievedFact
from provenance.store import (
    NOW,
    AsOf,
    build_tsquery,
    find_seed_entities,
    get_facts_visible,
    graph_neighbourhood,
    search_fulltext,
    search_vector,
)
from provenance.trace import STAGE_RETRIEVE, TraceRecorder

SOURCES = ("vector", "fulltext", "graph")


def retrieve(
    conn: psycopg.Connection,
    *,
    embedder: Embedder,
    settings: Settings,
    recorder: TraceRecorder,
    subject_id: str,
    query: str,
    as_of: AsOf = NOW,
    limit: int | None = None,
) -> list[RetrievedFact]:
    limit = limit or settings.retrieval_limit
    per_source = settings.retrieval_candidates_per_source
    started = time.perf_counter()

    query_embedding = embedder.embed([query])[0] if query.strip() else None

    ranked: dict[str, list[int]] = {}
    raw_scores: dict[str, dict[int, float]] = {}

    if query_embedding is not None:
        rows = search_vector(
            conn,
            subject_id=subject_id,
            embedding=query_embedding,
            limit=per_source,
            as_of=as_of,
        )
        ranked["vector"] = [int(row["id"]) for row in rows]
        raw_scores["vector"] = {int(row["id"]): float(row["score"]) for row in rows}
    else:
        ranked["vector"] = []
        raw_scores["vector"] = {}

    rows = search_fulltext(conn, subject_id=subject_id, query=query, limit=per_source, as_of=as_of)
    ranked["fulltext"] = [int(row["id"]) for row in rows]
    raw_scores["fulltext"] = {int(row["id"]): float(row["score"]) for row in rows}

    seeds = find_seed_entities(
        conn, subject_id=subject_id, query=query, embedding=query_embedding, limit=5
    )
    graph_rows = graph_neighbourhood(
        conn,
        subject_id=subject_id,
        seed_ids=[int(seed["id"]) for seed in seeds],
        hops=settings.graph_hops,
        valid_at=as_of.valid_time,
        only_open=as_of.transaction_time is None,
    )
    ranked["graph"] = [int(row["fact_id"]) for row in graph_rows][:per_source]
    raw_scores["graph"] = {int(row["fact_id"]): float(row["hop"]) for row in graph_rows}

    fused = _reciprocal_rank_fusion(ranked, k=settings.rrf_k)

    # Die Graphquelle kann Fakten liefern, die das Zeitfenster ausschließt --
    # ihre Kanten tragen keine Transaktionszeit. Das bitemporale Fenster wird
    # deshalb hier noch einmal angelegt, und zwar auf den Fakt: er ist die
    # einzige Stelle, an der beide Zeitachsen stehen.
    visible = {
        int(row["id"]): row
        for row in get_facts_visible(conn, [fact_id for fact_id, _ in fused], as_of)
    }

    results: list[RetrievedFact] = []
    for fact_id, score in fused:
        row = visible.get(fact_id)
        if row is None:
            continue
        results.append(
            RetrievedFact(
                fact_id=fact_id,
                content=row["content"],
                score=score,
                sources={
                    source: ranked[source].index(fact_id) + 1
                    for source in SOURCES
                    if fact_id in ranked.get(source, [])
                },
                valid_from=row["valid_from"],
                status=row["status"],
                origin_turn=row["origin_turn"],
                confidence=row["confidence"],
            )
        )
        if len(results) >= limit:
            break

    duration_ms = int((time.perf_counter() - started) * 1000)
    recorder.step(
        STAGE_RETRIEVE,
        model=getattr(embedder, "name", "?"),
        duration_ms=duration_ms,
        input={
            "query": query,
            "tsquery": build_tsquery(query),
            "limit": limit,
            "candidates_per_source": per_source,
            "rrf_k": settings.rrf_k,
            "graph_hops": settings.graph_hops,
            "graph_seeds": [
                {"id": int(seed["id"]), "name": seed["name"], "matched_by": seed.get("matched_by")}
                for seed in seeds
            ],
            "as_of": {
                "transaction_time": as_of.transaction_time.isoformat()
                if as_of.transaction_time
                else None,
                "valid_time": as_of.valid_time.isoformat() if as_of.valid_time else None,
            },
        },
        output={
            "per_source": {
                source: [
                    {"fact_id": fact_id, "rank": index + 1, "score": raw_scores[source].get(fact_id)}
                    for index, fact_id in enumerate(ranked.get(source, []))
                ]
                for source in SOURCES
            },
            "fused": [
                {
                    "fact_id": item.fact_id,
                    "rrf_score": round(item.score, 6),
                    "rank": index + 1,
                    "sources": item.sources,
                }
                for index, item in enumerate(results)
            ],
            "returned": len(results),
        },
    )
    return results


def _reciprocal_rank_fusion(ranked: dict[str, list[int]], k: int) -> list[tuple[int, float]]:
    """RRF: jede Quelle stimmt mit 1/(k + Rang) ab.

    Der Vorzug gegenüber gewichteten Rohwerten: Kosinusabstand,
    ``ts_rank_cd`` und Hop-Distanz sind nicht vergleichbar skaliert. Ränge
    sind es.
    """
    scores: dict[int, float] = {}
    for ids in ranked.values():
        for index, fact_id in enumerate(ids):
            scores[fact_id] = scores.get(fact_id, 0.0) + 1.0 / (k + index + 1)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def as_dicts(results: list[RetrievedFact]) -> list[dict[str, Any]]:
    return [
        {
            "fact_id": item.fact_id,
            "content": item.content,
            "score": round(item.score, 6),
            "sources": item.sources,
            "valid_from": item.valid_from.isoformat() if item.valid_from else None,
            "status": item.status,
            "origin_turn": item.origin_turn,
            "confidence": item.confidence,
        }
        for item in results
    ]
