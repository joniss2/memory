"""Graphprojektion.

Der Graph ist keine zweite Wahrheit, sondern eine Projektion über denselben
Fakten: jede Kante trägt in ``fact_id`` ihren Beleg. Damit erbt sie die
gesamte Herkunfts- und Löschmechanik (Abschnitt 4.4).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from provenance.embeddings.base import Embedder
from provenance.store import insert_edge, upsert_entity


def materialise_triple(
    conn: psycopg.Connection,
    *,
    embedder: Embedder,
    subject_id: str,
    triple: dict[str, Any] | None,
    fact_id: int,
    valid_from: datetime,
) -> int | None:
    """Legt Knoten und Kante für ein Tripel an. Ohne Tripel passiert nichts.

    Ein Fakt ohne erkannte Struktur bleibt ein Fakt -- er ist über Vektor und
    Volltext auffindbar, nur eben nicht über den Graphen.
    """
    if not triple:
        return None
    src_name = str(triple.get("src") or "").strip()
    dst_name = str(triple.get("dst") or "").strip()
    predicate = str(triple.get("predicate") or "").strip()
    if not (src_name and dst_name and predicate):
        return None

    vectors = embedder.embed([src_name, dst_name])
    src_id = upsert_entity(
        conn,
        subject_id=subject_id,
        name=src_name,
        kind=_kind(triple.get("src_kind")),
        embedding=vectors[0],
    )
    dst_id = upsert_entity(
        conn,
        subject_id=subject_id,
        name=dst_name,
        kind=_kind(triple.get("dst_kind")),
        embedding=vectors[1],
    )
    return insert_edge(
        conn,
        subject_id=subject_id,
        src=src_id,
        predicate=predicate,
        dst=dst_id,
        fact_id=fact_id,
        valid_from=valid_from,
    )


def _kind(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().casefold()
    return text[:80] or None


def entity_snapshot(
    conn: psycopg.Connection, *, subject_id: str, at: datetime | None = None
) -> dict[str, Any]:
    """Knoten und Kanten für die Graph-Ansicht, wahlweise zu einem Zeitpunkt."""
    from provenance.store import graph_edges

    edges = graph_edges(conn, subject_id=subject_id, at=at)
    nodes: dict[int, dict[str, Any]] = {}
    for edge in edges:
        nodes.setdefault(
            int(edge["src"]), {"id": int(edge["src"]), "name": edge["src_name"], "kind": edge["src_kind"]}
        )
        nodes.setdefault(
            int(edge["dst"]), {"id": int(edge["dst"]), "name": edge["dst_name"], "kind": edge["dst_kind"]}
        )
    return {"nodes": list(nodes.values()), "edges": edges}
