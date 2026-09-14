"""Datenzugriff.

Alles, was SQL spricht, steht hier -- die Pipeline-Stufen bleiben dadurch
lesbar und die bitemporalen Fensterbedingungen stehen genau einmal.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from provenance.config import get_settings
from provenance.db.pool import Jsonb, to_pgvector

FACT_COLUMNS = """
    f.id, f.subject_id, f.content, f.status, f.valid_from, f.valid_to,
    f.recorded_at, f.invalidated_at, f.confidence, f.origin_turn, f.triple,
    f.erased_at
"""

_WORD = re.compile(r"[\wäöüßÄÖÜ]{2,}", re.UNICODE)


def _like_literal(value: str) -> str:
    """Maskiert LIKE-Metazeichen, damit ein Term wörtlich gesucht wird.

    Ohne ESCAPE-Klausel: der Backslash ist in Postgres bereits das
    voreingestellte Fluchtzeichen, und ``ILIKE ANY(...) ESCAPE ...`` ist
    syntaktisch gar nicht erlaubt.
    """
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


@dataclass(frozen=True)
class AsOf:
    """Zwei Zeitachsen, zwei Fragen.

    ``transaction_time`` beantwortet „was wusste das System am 14. Mai?".
    ``valid_time`` beantwortet „was galt am 14. Mai in der Welt?".
    Beides ohne Wert bedeutet: der heutige Kenntnisstand, ohne
    Gültigkeitsfilter.
    """

    transaction_time: datetime | None = None
    valid_time: datetime | None = None

    @property
    def is_current(self) -> bool:
        return self.transaction_time is None and self.valid_time is None


NOW = AsOf()


def _temporal_clause(as_of: AsOf, params: dict[str, Any], alias: str = "f") -> str:
    """Baut die bitemporale Fensterbedingung und füllt die Parameter.

    Drei Fälle, drei verschiedene Fragen:

    * **ohne Angabe** -- was gilt jetzt? Nur ``active``.
    * **transaction_time = T** -- was wusste das System an T? Das
      Transaktionsfenster entscheidet; der heutige Status ist unerheblich.
    * **valid_time = V ohne T** -- was weiß das System *heute* über den
      Zeitpunkt V? Hier ist der Unterschied zwischen ``superseded`` und
      ``retracted`` wesentlich: ein abgelöster Fakt hat in seinem
      Gültigkeitsfenster gegolten und zählt mit, ein zurückgezogener wurde
      widerrufen und zählt nie. Würde man auch hier auf
      ``invalidated_at IS NULL`` filtern, könnte das System auf die Frage
      „wo hat er im März gewohnt?" nur schweigen, sobald jemand umgezogen
      ist -- und genau das wäre keine ehrliche Auskunft.
    """
    clauses = [f"{alias}.status <> 'erased'"]
    if as_of.transaction_time is not None:
        params["tx_time"] = as_of.transaction_time
        clauses.append(
            f"{alias}.recorded_at <= %(tx_time)s "
            f"AND ({alias}.invalidated_at IS NULL OR {alias}.invalidated_at > %(tx_time)s)"
        )
    elif as_of.valid_time is not None:
        clauses.append(f"{alias}.status <> 'retracted'")
    else:
        clauses.append(f"{alias}.invalidated_at IS NULL")

    if as_of.valid_time is not None:
        params["valid_time"] = as_of.valid_time
        clauses.append(
            f"{alias}.valid_from <= %(valid_time)s "
            f"AND ({alias}.valid_to IS NULL OR {alias}.valid_to > %(valid_time)s)"
        )
    return " AND ".join(clauses)


# --------------------------------------------------------------------- turns


def insert_turn(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    session_id: str,
    role: str,
    content: str,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO turns (subject_id, session_id, role, content, occurred_at)
        VALUES (%s, %s, %s, %s, COALESCE(%s, now()))
        RETURNING id, subject_id, session_id, role, content, occurred_at
        """,
        (subject_id, session_id, role, content, occurred_at),
    ).fetchone()
    assert row is not None
    return dict(row)


def context_turns(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    session_id: str,
    before_turn_id: int,
    limit: int,
) -> list[dict[str, Any]]:
    """Die letzten *n* Beiträge derselben Sitzung, aufsteigend sortiert."""
    rows = conn.execute(
        """
        SELECT id, role, content, occurred_at, redacted_at
        FROM turns
        WHERE subject_id = %s AND session_id = %s AND id < %s
        ORDER BY id DESC
        LIMIT %s
        """,
        (subject_id, session_id, before_turn_id, limit),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


def get_turn(conn: psycopg.Connection, turn_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT id, subject_id, session_id, role, content, occurred_at, redacted_at "
        "FROM turns WHERE id = %s",
        (turn_id,),
    ).fetchone()
    return dict(row) if row else None


def list_turns(
    conn: psycopg.Connection, *, subject_id: str, limit: int = 200, offset: int = 0
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, session_id, role, content, occurred_at, redacted_at
        FROM turns WHERE subject_id = %s
        ORDER BY occurred_at, id
        LIMIT %s OFFSET %s
        """,
        (subject_id, limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


# --------------------------------------------------------------------- facts


def insert_fact(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    content: str,
    embedding: Sequence[float] | None,
    valid_from: datetime,
    valid_to: datetime | None = None,
    confidence: float | None = None,
    origin_turn: int | None = None,
    triple: dict[str, Any] | None = None,
) -> dict[str, Any]:
    fts_config = get_settings().fts_config
    row = conn.execute(
        f"""
        INSERT INTO facts
            (subject_id, content, embedding, content_tsv, valid_from, valid_to,
             confidence, origin_turn, triple)
        VALUES (%s, %s, %s::vector, to_tsvector(%s::regconfig, %s), %s, %s, %s, %s, %s)
        RETURNING {FACT_COLUMNS.replace("f.", "")}
        """,
        (
            subject_id,
            content,
            to_pgvector(embedding),
            fts_config,
            content,
            valid_from,
            valid_to,
            confidence,
            origin_turn,
            Jsonb(triple) if triple is not None else None,
        ),
    ).fetchone()
    assert row is not None
    return dict(row)


def get_fact(conn: psycopg.Connection, fact_id: int) -> dict[str, Any] | None:
    row = conn.execute(f"SELECT {FACT_COLUMNS} FROM facts f WHERE f.id = %s", (fact_id,)).fetchone()
    return dict(row) if row else None


def get_facts(conn: psycopg.Connection, fact_ids: Sequence[int]) -> list[dict[str, Any]]:
    if not fact_ids:
        return []
    rows = conn.execute(
        f"SELECT {FACT_COLUMNS} FROM facts f WHERE f.id = ANY(%s)", (list(fact_ids),)
    ).fetchall()
    return [dict(row) for row in rows]


def get_facts_visible(
    conn: psycopg.Connection, fact_ids: Sequence[int], as_of: AsOf = NOW
) -> list[dict[str, Any]]:
    """Wie :func:`get_facts`, aber durch das bitemporale Fenster gefiltert.

    Nötig, weil die Graphquelle in Stufe 3 Kandidaten über Kanten findet und
    Kanten keine Transaktionszeit tragen. Die Entscheidung, was zu einem
    Zeitpunkt sichtbar war, fällt deshalb am Fakt -- nicht an der Kante.
    """
    if not fact_ids:
        return []
    params: dict[str, Any] = {"fact_ids": list(fact_ids)}
    where = _temporal_clause(as_of, params)
    rows = conn.execute(
        f"SELECT {FACT_COLUMNS} FROM facts f WHERE f.id = ANY(%(fact_ids)s) AND {where}",
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def close_fact(
    conn: psycopg.Connection,
    *,
    fact_id: int,
    status: str,
    at: datetime,
    valid_to: datetime | None,
) -> dict[str, Any] | None:
    """Setzt einen Fakt ungültig, ohne ihn zu verändern.

    Nichts wird überschrieben (Abschnitt 2): ``content`` und ``embedding``
    bleiben stehen, es kommen nur Endzeitpunkte dazu. Ein bereits
    geschlossener Fakt wird nicht erneut geschlossen -- sonst verschöbe eine
    zweite Entscheidung den Zeitpunkt der ersten.
    """
    row = conn.execute(
        """
        UPDATE facts
        SET status = %s::fact_status,
            invalidated_at = %s,
            valid_to = COALESCE(%s, valid_to)
        WHERE id = %s AND invalidated_at IS NULL
        RETURNING id, status, invalidated_at, valid_to
        """,
        (status, at, valid_to, fact_id),
    ).fetchone()
    return dict(row) if row else None


def active_facts(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    as_of: AsOf = NOW,
    limit: int = 500,
    offset: int = 0,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"subject_id": subject_id, "limit": limit, "offset": offset}
    where = _temporal_clause(as_of, params)
    rows = conn.execute(
        f"""
        SELECT {FACT_COLUMNS}
        FROM facts f
        WHERE f.subject_id = %(subject_id)s AND {where}
        ORDER BY f.valid_from DESC, f.id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def all_facts(
    conn: psycopg.Connection, *, subject_id: str, limit: int = 1000, offset: int = 0
) -> list[dict[str, Any]]:
    """Alle Fakten, unabhängig vom Status -- für Auskunft und Zeitleiste."""
    rows = conn.execute(
        f"""
        SELECT {FACT_COLUMNS}
        FROM facts f WHERE f.subject_id = %s
        ORDER BY f.recorded_at, f.id
        LIMIT %s OFFSET %s
        """,
        (subject_id, limit, offset),
    ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------- Kandidatensuche Stufe 2


def neighbours_for_candidate(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    embedding: Sequence[float] | None,
    limit: int,
    predicates: Sequence[str] = (),
    terms: Sequence[str] = (),
    as_of: AsOf = NOW,
) -> list[dict[str, Any]]:
    """Nachbarn eines Kandidaten für die Konsolidierung.

    Drei Zugänge in einer Abfrage: Vektorähnlichkeit, Prädikatsgleichheit und
    Termtreffer. Die beiden letzten sind für Widerrufe unentbehrlich -- „vergiss,
    was ich über meinen Arbeitgeber gesagt habe" liegt im Vektorraum nicht in
    der Nähe von „Arbeitet bei ACME", und ein rein ähnlichkeitsbasierter Zugriff
    fände den zu widerrufenden Fakt schlicht nicht.
    """
    params: dict[str, Any] = {"subject_id": subject_id, "limit": limit}
    where = _temporal_clause(as_of, params)

    if embedding is not None:
        params["embedding"] = to_pgvector(embedding)
        similarity = "1 - (f.embedding <=> %(embedding)s::vector)"
        order = "f.embedding <=> %(embedding)s::vector"
    else:
        similarity = "NULL::float8"
        order = "f.id DESC"

    filters: list[str] = []
    if predicates:
        params["predicates"] = list(predicates)
        filters.append("(f.triple->>'predicate') = ANY(%(predicates)s)")
    if terms:
        # %, _ und \\ sind in ILIKE Platzhalter. Ein Term wie „100%" würde die
        # Ankersuche sonst auf beliebige Fakten ausweiten.
        params["terms"] = [f"%{_like_literal(term)}%" for term in terms]
        filters.append("f.content ILIKE ANY(%(terms)s)")

    base = f"""
        SELECT {FACT_COLUMNS}, {similarity} AS similarity, %(source)s AS matched_by
        FROM facts f
        WHERE f.subject_id = %(subject_id)s AND {where}
    """

    rows: dict[int, dict[str, Any]] = {}

    if embedding is not None:
        params["source"] = "vector"
        for row in conn.execute(base + f" ORDER BY {order} LIMIT %(limit)s", params).fetchall():
            rows[int(row["id"])] = dict(row)

    if filters:
        params["source"] = "anchor"
        anchored = base + " AND (" + " OR ".join(filters) + ") ORDER BY f.id DESC LIMIT %(limit)s"
        for row in conn.execute(anchored, params).fetchall():
            existing = rows.get(int(row["id"]))
            if existing is None:
                rows[int(row["id"])] = dict(row)
            else:
                existing["matched_by"] = "vector+anchor"

    ordered = sorted(rows.values(), key=lambda r: (-(r.get("similarity") or 0.0), -int(r["id"])))
    return ordered


# ------------------------------------------------------------------- lineage


def insert_lineage(
    conn: psycopg.Connection,
    *,
    fact_id: int,
    parent_id: int | None,
    op: str,
    rationale: str | None,
    trace_id: int,
    proposed_op: str | None = None,
) -> dict[str, Any]:
    row = conn.execute(
        """
        INSERT INTO lineage (fact_id, parent_id, op, rationale, trace_id, proposed_op)
        VALUES (%s, %s, %s::decision, %s, %s, %s::decision)
        RETURNING id, fact_id, parent_id, op, rationale, trace_id, created_at, proposed_op
        """,
        (fact_id, parent_id, op, rationale, trace_id, proposed_op),
    ).fetchone()
    assert row is not None
    return dict(row)


def lineage_for_fact(conn: psycopg.Connection, fact_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT l.id, l.fact_id, l.parent_id, l.op, l.rationale, l.trace_id,
               l.created_at, l.proposed_op, t.turn_id
        FROM lineage l JOIN traces t ON t.id = l.trace_id
        WHERE l.fact_id = %s OR l.parent_id = %s
        ORDER BY l.created_at, l.id
        """,
        (fact_id, fact_id),
    ).fetchall()
    return [dict(row) for row in rows]


def lineage_for_trace(conn: psycopg.Connection, trace_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT l.id, l.fact_id, l.parent_id, l.op, l.rationale, l.trace_id,
               l.created_at, l.proposed_op, f.content
        FROM lineage l LEFT JOIN facts f ON f.id = l.fact_id
        WHERE l.trace_id = %s
        ORDER BY l.id
        """,
        (trace_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def descendant_facts(conn: psycopg.Connection, fact_ids: Sequence[int]) -> list[int]:
    """Die transitive Hülle über ``lineage.parent_id``.

    Abschnitt 7, Schritt 1: alles, was aus den genannten Fakten abgeleitet
    wurde, samt der Wurzeln selbst. Die Rekursion bricht auf besuchten Knoten
    ab; ohne das würde ein Zyklus in der Abstammung die Abfrage nicht beenden.
    """
    if not fact_ids:
        return []
    rows = conn.execute(
        """
        WITH RECURSIVE closure AS (
            SELECT id AS fact_id, ARRAY[id] AS path
            FROM facts WHERE id = ANY(%s)
          UNION ALL
            SELECT l.fact_id, c.path || l.fact_id
            FROM lineage l
            JOIN closure c ON l.parent_id = c.fact_id
            WHERE NOT l.fact_id = ANY(c.path)
        )
        SELECT DISTINCT fact_id FROM closure ORDER BY fact_id
        """,
        (list(fact_ids),),
    ).fetchall()
    return [int(row["fact_id"]) for row in rows]


# --------------------------------------------------------------------- graph


def upsert_entity(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    name: str,
    kind: str | None,
    embedding: Sequence[float] | None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO entities (subject_id, name, kind, embedding)
        VALUES (%s, %s, %s, %s::vector)
        ON CONFLICT (subject_id, name, kind)
        DO UPDATE SET embedding = COALESCE(entities.embedding, EXCLUDED.embedding)
        RETURNING id
        """,
        (subject_id, name, kind, to_pgvector(embedding)),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def insert_edge(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    src: int,
    predicate: str,
    dst: int,
    fact_id: int,
    valid_from: datetime,
) -> int:
    row = conn.execute(
        """
        INSERT INTO edges (subject_id, src, predicate, dst, fact_id, valid_from)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (subject_id, src, predicate, dst, fact_id, valid_from),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def close_edges_for_facts(
    conn: psycopg.Connection, *, fact_ids: Sequence[int], at: datetime
) -> list[int]:
    """Zieht die Kanten mit, deren belegender Fakt nicht mehr gilt.

    ``edges.fact_id`` ist der Grund, warum das eine Zeile SQL ist und nicht
    ein Abgleich zwischen zwei Datenbanken (Abschnitt 4.4).
    """
    if not fact_ids:
        return []
    rows = conn.execute(
        """
        UPDATE edges SET valid_to = %s
        WHERE fact_id = ANY(%s) AND valid_to IS NULL
        RETURNING id
        """,
        (at, list(fact_ids)),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def find_seed_entities(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    query: str,
    embedding: Sequence[float] | None,
    limit: int = 5,
) -> list[dict[str, Any]]:
    """Einstiegsknoten für die Graphsuche: Namenstreffer zuerst, dann Nähe."""
    tokens = {token.casefold() for token in _WORD.findall(query or "")}
    found: dict[int, dict[str, Any]] = {}

    if tokens:
        rows = conn.execute(
            """
            SELECT id, name, kind FROM entities
            WHERE subject_id = %s AND lower(name) = ANY(%s)
            LIMIT %s
            """,
            (subject_id, list(tokens), limit),
        ).fetchall()
        for row in rows:
            found[int(row["id"])] = {**dict(row), "matched_by": "name"}

    if embedding is not None and len(found) < limit:
        rows = conn.execute(
            """
            SELECT id, name, kind, 1 - (embedding <=> %s::vector) AS similarity
            FROM entities
            WHERE subject_id = %s AND embedding IS NOT NULL
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (to_pgvector(embedding), subject_id, to_pgvector(embedding), limit),
        ).fetchall()
        for row in rows:
            found.setdefault(int(row["id"]), {**dict(row), "matched_by": "vector"})

    return list(found.values())[:limit]


def graph_neighbourhood(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    seed_ids: Sequence[int],
    hops: int,
    valid_at: datetime | None = None,
    only_open: bool = True,
) -> list[dict[str, Any]]:
    """Belegende Fakten in der *n*-Hop-Nachbarschaft der Startknoten.

    Gegenüber der gerichteten Fassung im Entwurf wird hier ungerichtet
    traversiert: für einen Abruf ist „wer arbeitet bei derselben Firma"
    genauso interessant wie die Gegenrichtung, und die Kanten tragen ohnehin
    nur eine Leserichtung.

    Kanten kennen nur die Gültigkeitszeit. Bei einem Replay auf
    *Transaktions*zeit darf deshalb nicht auf offene Kanten eingeschränkt
    werden (``only_open=False``) -- sonst fehlen genau die Bezüge, die
    seither geschlossen wurden. Die Sichtbarkeit entscheidet danach der
    Faktenfilter.
    """
    if not seed_ids or hops < 1:
        return []
    params: dict[str, Any] = {"subject_id": subject_id, "seeds": list(seed_ids), "hops": hops}
    if valid_at is not None:
        params["valid_at"] = valid_at
        edge_window = "AND valid_from <= %(valid_at)s AND (valid_to IS NULL OR valid_to > %(valid_at)s)"
    elif only_open:
        edge_window = "AND valid_to IS NULL"
    else:
        edge_window = ""
    rows = conn.execute(
        f"""
        WITH RECURSIVE adj AS (
            SELECT src AS a, dst AS b, fact_id FROM edges
            WHERE subject_id = %(subject_id)s {edge_window}
            UNION ALL
            SELECT dst AS a, src AS b, fact_id FROM edges
            WHERE subject_id = %(subject_id)s {edge_window}
        ),
        nodes AS (
            SELECT seed AS node, 0 AS hop
            FROM unnest(%(seeds)s::bigint[]) AS seed
          UNION
            SELECT adj.b, nodes.hop + 1
            FROM adj JOIN nodes ON adj.a = nodes.node
            WHERE nodes.hop < %(hops)s
        )
        SELECT adj.fact_id, MIN(nodes.hop) + 1 AS hop
        FROM nodes JOIN adj ON adj.a = nodes.node
        GROUP BY adj.fact_id
        ORDER BY hop, adj.fact_id
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def graph_edges(
    conn: psycopg.Connection, *, subject_id: str, at: datetime | None = None
) -> list[dict[str, Any]]:
    """Kanten für die Graph-Ansicht, wahlweise zu einem Zeitpunkt."""
    params: dict[str, Any] = {"subject_id": subject_id}
    window = "e.valid_to IS NULL"
    if at is not None:
        params["at"] = at
        window = "e.valid_from <= %(at)s AND (e.valid_to IS NULL OR e.valid_to > %(at)s)"
    rows = conn.execute(
        f"""
        SELECT e.id, e.predicate, e.valid_from, e.valid_to, e.fact_id,
               e.src, e.dst,
               s.name AS src_name, s.kind AS src_kind,
               d.name AS dst_name, d.kind AS dst_kind,
               f.content AS fact_content, f.origin_turn, f.status AS fact_status
        FROM edges e
        JOIN entities s ON s.id = e.src
        JOIN entities d ON d.id = e.dst
        JOIN facts f ON f.id = e.fact_id
        WHERE e.subject_id = %(subject_id)s AND {window}
        ORDER BY e.valid_from, e.id
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


# ----------------------------------------------------------- Stufe 3 Quellen


def search_vector(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    embedding: Sequence[float],
    limit: int,
    as_of: AsOf = NOW,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {
        "subject_id": subject_id,
        "embedding": to_pgvector(embedding),
        "limit": limit,
    }
    where = _temporal_clause(as_of, params)
    rows = conn.execute(
        f"""
        SELECT f.id, 1 - (f.embedding <=> %(embedding)s::vector) AS score
        FROM facts f
        WHERE f.subject_id = %(subject_id)s AND f.embedding IS NOT NULL AND {where}
        ORDER BY f.embedding <=> %(embedding)s::vector
        LIMIT %(limit)s
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def build_tsquery(query: str, limit_terms: int = 24) -> str:
    """Baut eine ODER-verknüpfte Suchanfrage aus den Wörtern der Frage.

    ``plainto_tsquery`` verknüpft mit UND und liefert bei einer ganzen Frage
    fast immer nichts. Für eine Kandidatenquelle in einer Fusion ist ODER die
    richtige Verknüpfung -- die Rangfolge trennt danach.
    """
    seen: list[str] = []
    for token in _WORD.findall(query or ""):
        folded = token.casefold()
        if folded not in seen:
            seen.append(folded)
        if len(seen) >= limit_terms:
            break
    return " or ".join(seen)


def search_fulltext(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    query: str,
    limit: int,
    as_of: AsOf = NOW,
) -> list[dict[str, Any]]:
    tsquery = build_tsquery(query)
    if not tsquery:
        return []
    params: dict[str, Any] = {
        "subject_id": subject_id,
        "tsquery": tsquery,
        "limit": limit,
        "config": get_settings().fts_config,
    }
    where = _temporal_clause(as_of, params)
    rows = conn.execute(
        f"""
        SELECT f.id,
               ts_rank_cd(f.content_tsv, websearch_to_tsquery(%(config)s::regconfig, %(tsquery)s)) AS score
        FROM facts f
        WHERE f.subject_id = %(subject_id)s
          AND f.content_tsv @@ websearch_to_tsquery(%(config)s::regconfig, %(tsquery)s)
          AND {where}
        ORDER BY score DESC, f.id DESC
        LIMIT %(limit)s
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def reindex_fulltext(conn: psycopg.Connection, *, subject_id: str | None = None) -> int:
    """Baut ``content_tsv`` neu auf -- nötig nach einem Wechsel von PROVENANCE_FTS_CONFIG."""
    config = get_settings().fts_config
    if subject_id is None:
        result = conn.execute(
            "UPDATE facts SET content_tsv = to_tsvector(%s::regconfig, content) WHERE status <> 'erased'",
            (config,),
        )
    else:
        result = conn.execute(
            "UPDATE facts SET content_tsv = to_tsvector(%s::regconfig, content) "
            "WHERE subject_id = %s AND status <> 'erased'",
            (config, subject_id),
        )
    return result.rowcount


# -------------------------------------------------------------------- traces


def get_trace(conn: psycopg.Connection, trace_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT id, subject_id, kind, turn_id, query, started_at, duration_ms
        FROM traces WHERE id = %s
        """,
        (trace_id,),
    ).fetchone()
    return dict(row) if row else None


def trace_steps(conn: psycopg.Connection, trace_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, trace_id, stage, model, prompt_ref, input, output,
               duration_ms, tokens_in, tokens_out, redacted_at
        FROM trace_steps WHERE trace_id = %s ORDER BY stage, id
        """,
        (trace_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_traces(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    kind: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict[str, Any]]:
    params: list[Any] = [subject_id]
    filter_sql = ""
    if kind:
        filter_sql = " AND kind = %s::trace_kind"
        params.append(kind)
    params.extend([limit, offset])
    rows = conn.execute(
        f"""
        SELECT id, subject_id, kind, turn_id, query, started_at, duration_ms
        FROM traces WHERE subject_id = %s{filter_sql}
        ORDER BY started_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def traces_for_turn(conn: psycopg.Connection, turn_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, kind, query, started_at, duration_ms FROM traces WHERE turn_id = %s ORDER BY id",
        (turn_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def list_subjects(conn: psycopg.Connection, limit: int = 200) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT t.subject_id,
               count(*) AS turns,
               max(t.occurred_at) AS last_seen,
               (SELECT count(*) FROM facts f
                 WHERE f.subject_id = t.subject_id AND f.status = 'active') AS active_facts
        FROM turns t
        GROUP BY t.subject_id
        ORDER BY max(t.occurred_at) DESC
        LIMIT %s
        """,
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]
