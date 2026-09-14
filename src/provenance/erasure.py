"""Löschung.

Der Ablauf aus Abschnitt 7, mit zwei Ergänzungen, die der Entwurf offenlässt:

* **Rohmaterial.** ``turns.content`` ist die unmittelbarste personenbezogene
  Ablage. Der Schrittfolge im Entwurf fehlt sie; eine Löschung, die den
  Ursprungstext stehen lässt, wäre keine.
* **Knoten.** Kanten werden geschlossen, aber ``entities.name`` trägt selbst
  Personenbezug ("ACME", "Köln"). Ein Knoten bleibt genau so lange
  inhaltlich stehen, wie ihn noch ein nicht gelöschter Fakt belegt.
* **Begründungen und Fragen.** ``lineage.rationale`` zitiert die Werte, über
  die entschieden wurde, und ``traces.query`` den Wortlaut einer Abfrage.
  Beide Felder nennt Abschnitt 7 nicht, und beide überlebten die Löschung,
  bis sie hier aufgenommen wurden -- die Zeile bleibt, der Freitext geht.

Was in allen Fällen bleibt: die Zeile. Ein spurloses ``DELETE`` kann man
einer Aufsichtsbehörde nicht vorzeigen.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg

from provenance.db.pool import Jsonb
from provenance.store import descendant_facts

REDACTED_ENTITY = "(gelöscht)"


@dataclass(slots=True)
class ErasurePreview:
    """Was passieren würde. Abschnitt 7, Schritt 2."""

    subject_id: str
    scope: str
    roots: list[int]
    facts: list[dict[str, Any]] = field(default_factory=list)
    derived: list[int] = field(default_factory=list)
    edge_ids: list[int] = field(default_factory=list)
    trace_step_ids: list[int] = field(default_factory=list)
    turn_ids: list[int] = field(default_factory=list)
    entity_ids: list[int] = field(default_factory=list)
    # lineage.rationale zitiert die Werte, über die entschieden wurde, und
    # traces.query den Wortlaut einer Frage. Beides ist personenbezogen und
    # überlebte die Löschung, bis es hier aufgenommen wurde.
    lineage_ids: list[int] = field(default_factory=list)
    trace_ids: list[int] = field(default_factory=list)

    @property
    def fact_ids(self) -> list[int]:
        return [int(item["id"]) for item in self.facts]

    def as_dict(self) -> dict[str, Any]:
        return {
            "subject_id": self.subject_id,
            "scope": self.scope,
            "roots": self.roots,
            "facts": self.facts,
            "derived": self.derived,
            "counts": {
                "facts": len(self.facts),
                "derived": len(self.derived),
                "edges": len(self.edge_ids),
                "trace_steps": len(self.trace_step_ids),
                "turns": len(self.turn_ids),
                "entities": len(self.entity_ids),
                "lineage_rationales": len(self.lineage_ids),
                "trace_queries": len(self.trace_ids),
            },
            "edge_ids": self.edge_ids,
            "trace_step_ids": self.trace_step_ids,
            "turn_ids": self.turn_ids,
            "entity_ids": self.entity_ids,
            "lineage_ids": self.lineage_ids,
            "trace_ids": self.trace_ids,
        }


@dataclass(slots=True)
class ErasureReceipt:
    receipt_id: int
    preview: ErasurePreview
    executed_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "receipt_id": self.receipt_id,
            "executed_at": self.executed_at.isoformat(),
            **self.preview.as_dict(),
        }


# ------------------------------------------------------------------ Vorschau


def preview(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    fact_ids: Sequence[int] | None = None,
) -> ErasurePreview:
    """Ermittelt die transitive Hülle und alles, was mit ihr fällt.

    ``fact_ids=None`` löscht die betroffene Person vollständig; sonst nur die
    genannten Fakten und alles, was aus ihnen abgeleitet wurde.
    """
    scope = "subject" if fact_ids is None else "facts"

    if fact_ids is None:
        rows = conn.execute(
            "SELECT id FROM facts WHERE subject_id = %s AND status <> 'erased' ORDER BY id",
            (subject_id,),
        ).fetchall()
        roots = [int(row["id"]) for row in rows]
        closure = roots
    else:
        rows = conn.execute(
            "SELECT id FROM facts WHERE id = ANY(%s) AND subject_id = %s ORDER BY id",
            (list(fact_ids), subject_id),
        ).fetchall()
        roots = [int(row["id"]) for row in rows]
        # Abschnitt 7, Schritt 1: alles, was aus dem zu löschenden abgeleitet
        # wurde, geht mit.
        closure = descendant_facts(conn, roots)

    facts = [
        dict(row)
        for row in conn.execute(
            """
            SELECT id, content, status, valid_from, recorded_at, origin_turn
            FROM facts WHERE id = ANY(%s) AND status <> 'erased' ORDER BY id
            """,
            (closure,),
        ).fetchall()
    ] if closure else []
    surviving = [int(item["id"]) for item in facts]

    edge_ids = _edge_ids(conn, surviving)
    trace_step_ids = _trace_step_ids(conn, subject_id=subject_id, fact_ids=surviving, scope=scope)
    turn_ids = _turn_ids(conn, subject_id=subject_id, fact_ids=surviving, scope=scope)
    entity_ids = _orphaned_entities(conn, subject_id=subject_id, fact_ids=surviving)
    lineage_ids = _lineage_ids(conn, surviving)
    trace_ids = _trace_ids(conn, subject_id=subject_id, step_ids=trace_step_ids, scope=scope)

    return ErasurePreview(
        subject_id=subject_id,
        scope=scope,
        roots=roots,
        facts=facts,
        derived=sorted(set(surviving) - set(roots)),
        edge_ids=edge_ids,
        trace_step_ids=trace_step_ids,
        turn_ids=turn_ids,
        entity_ids=entity_ids,
        lineage_ids=lineage_ids,
        trace_ids=trace_ids,
    )


def _edge_ids(conn: psycopg.Connection, fact_ids: Sequence[int]) -> list[int]:
    if not fact_ids:
        return []
    rows = conn.execute(
        "SELECT id FROM edges WHERE fact_id = ANY(%s) ORDER BY id", (list(fact_ids),)
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _trace_step_ids(
    conn: psycopg.Connection, *, subject_id: str, fact_ids: Sequence[int], scope: str
) -> list[int]:
    """Schritte, deren Inhalt zu den betroffenen Fakten gehört.

    Bei einer vollständigen Löschung ist das jeder Schritt der betroffenen
    Person. Bei einer gezielten Löschung müssen auch *Lese*-Traces mit --
    Stufe 3 hat die Fakt-ID protokolliert, Stufe 4 den ausgelieferten Text.
    Ohne diesen Schritt bliebe der gelöschte Inhalt im Auditlog stehen.
    """
    if scope == "subject":
        rows = conn.execute(
            """
            SELECT ts.id FROM trace_steps ts JOIN traces t ON t.id = ts.trace_id
            WHERE t.subject_id = %s AND ts.redacted_at IS NULL ORDER BY ts.id
            """,
            (subject_id,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    if not fact_ids:
        return []
    ids = list(fact_ids)
    rows = conn.execute(
        """
        SELECT DISTINCT ts.id
        FROM trace_steps ts
        JOIN traces t ON t.id = ts.trace_id
        WHERE t.subject_id = %(subject_id)s
          AND ts.redacted_at IS NULL
          AND (
                ts.trace_id IN (SELECT trace_id FROM lineage WHERE fact_id = ANY(%(ids)s)
                                 UNION SELECT trace_id FROM lineage WHERE parent_id = ANY(%(ids)s))
             OR EXISTS (
                  SELECT 1 FROM unnest(%(ids)s::bigint[]) AS fid
                  WHERE ts.output->'included' @> to_jsonb(fid)
                     OR ts.output->'fused' @> jsonb_build_array(jsonb_build_object('fact_id', fid))
                     OR ts.input->'neighbours' @> jsonb_build_array(jsonb_build_object('id', fid))
                )
          )
        ORDER BY ts.id
        """,
        {"subject_id": subject_id, "ids": ids},
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _turn_ids(
    conn: psycopg.Connection, *, subject_id: str, fact_ids: Sequence[int], scope: str
) -> list[int]:
    if scope == "subject":
        rows = conn.execute(
            "SELECT id FROM turns WHERE subject_id = %s AND redacted_at IS NULL ORDER BY id",
            (subject_id,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    if not fact_ids:
        return []
    # Ein Ursprungs-Turn wird nur dann geschwärzt, wenn er ausschließlich
    # gelöschte Fakten hervorgebracht hat -- sonst risse die Löschung eines
    # Fakts die Belege der anderen mit.
    rows = conn.execute(
        """
        SELECT t.id
        FROM turns t
        WHERE t.subject_id = %(subject_id)s
          AND t.redacted_at IS NULL
          AND EXISTS (SELECT 1 FROM facts f WHERE f.origin_turn = t.id AND f.id = ANY(%(ids)s))
          AND NOT EXISTS (
                SELECT 1 FROM facts f
                WHERE f.origin_turn = t.id AND NOT (f.id = ANY(%(ids)s)) AND f.status <> 'erased'
              )
        ORDER BY t.id
        """,
        {"subject_id": subject_id, "ids": list(fact_ids)},
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _lineage_ids(conn: psycopg.Connection, fact_ids: Sequence[int]) -> list[int]:
    """Abstammungszeilen, deren Begründung den gelöschten Wert nennen kann.

    Eine Begründung wie „Aussage kehrt die Polarität zu ‚Espresso' um" zitiert
    genau den Wert, der verschwinden soll. Die Zeile bleibt -- sie ist die
    Herkunftsspur --, der Freitext geht.
    """
    if not fact_ids:
        return []
    ids = list(fact_ids)
    rows = conn.execute(
        """
        SELECT id FROM lineage
        WHERE (fact_id = ANY(%(ids)s) OR parent_id = ANY(%(ids)s)) AND rationale IS NOT NULL
        ORDER BY id
        """,
        {"ids": ids},
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _trace_ids(
    conn: psycopg.Connection, *, subject_id: str, step_ids: Sequence[int], scope: str
) -> list[int]:
    """Traces, deren Frage im Klartext gespeichert ist.

    ``traces.query`` ist der Wortlaut einer Abfrage und kann den gesuchten
    Namen oder Wert enthalten.
    """
    if scope == "subject":
        rows = conn.execute(
            "SELECT id FROM traces WHERE subject_id = %s AND query IS NOT NULL ORDER BY id",
            (subject_id,),
        ).fetchall()
        return [int(row["id"]) for row in rows]
    if not step_ids:
        return []
    rows = conn.execute(
        """
        SELECT DISTINCT t.id FROM traces t
        JOIN trace_steps ts ON ts.trace_id = t.id
        WHERE ts.id = ANY(%s) AND t.query IS NOT NULL
        ORDER BY t.id
        """,
        (list(step_ids),),
    ).fetchall()
    return [int(row["id"]) for row in rows]


def _orphaned_entities(
    conn: psycopg.Connection, *, subject_id: str, fact_ids: Sequence[int]
) -> list[int]:
    """Knoten, die nach der Löschung kein nicht gelöschter Fakt mehr belegt."""
    rows = conn.execute(
        """
        SELECT e.id
        FROM entities e
        WHERE e.subject_id = %(subject_id)s
          AND e.name <> %(placeholder)s
          AND NOT EXISTS (
                SELECT 1 FROM edges g JOIN facts f ON f.id = g.fact_id
                WHERE (g.src = e.id OR g.dst = e.id)
                  AND f.status <> 'erased'
                  AND NOT (f.id = ANY(%(ids)s))
              )
        ORDER BY e.id
        """,
        {"subject_id": subject_id, "ids": list(fact_ids), "placeholder": REDACTED_ENTITY},
    ).fetchall()
    return [int(row["id"]) for row in rows]


# ------------------------------------------------------------------ Ausführung


def execute(
    conn: psycopg.Connection,
    *,
    subject_id: str,
    fact_ids: Sequence[int] | None = None,
    requested_by: str | None = None,
    reason: str | None = None,
) -> ErasureReceipt:
    """Führt die Löschung aus und schreibt den Beleg."""
    plan = preview(conn, subject_id=subject_id, fact_ids=fact_ids)
    row = conn.execute("SELECT now() AS now").fetchone()
    assert row is not None
    at: datetime = row["now"]

    ids = plan.fact_ids

    if ids:
        # Schritt 3: Zeile bleibt, Inhalt geht. content_tsv und triple müssen
        # mit -- sonst findet die Volltextquelle den Fakt weiterhin und das
        # Tripel trägt den Wert im Klartext.
        conn.execute(
            """
            UPDATE facts
            SET status = 'erased',
                content = '',
                embedding = NULL,
                content_tsv = NULL,
                triple = NULL,
                erased_at = %s,
                invalidated_at = COALESCE(invalidated_at, %s),
                valid_to = COALESCE(valid_to, %s)
            WHERE id = ANY(%s)
            """,
            (at, at, at, ids),
        )
        # Schritt 4
        conn.execute(
            "UPDATE edges SET valid_to = COALESCE(valid_to, %s) WHERE fact_id = ANY(%s)",
            (at, ids),
        )

    # Schritt 5
    redacted_steps = redact_trace_steps(conn, plan.trace_step_ids, at=at)

    if plan.turn_ids:
        conn.execute(
            "UPDATE turns SET content = '', redacted_at = %s WHERE id = ANY(%s)",
            (at, plan.turn_ids),
        )

    if plan.lineage_ids:
        conn.execute(
            "UPDATE lineage SET rationale = NULL WHERE id = ANY(%s)", (plan.lineage_ids,)
        )

    if plan.trace_ids:
        conn.execute("UPDATE traces SET query = NULL WHERE id = ANY(%s)", (plan.trace_ids,))

    if plan.entity_ids:
        conn.execute(
            """
            UPDATE entities
            SET name = %s || ' #' || id::text, embedding = NULL
            WHERE id = ANY(%s)
            """,
            (REDACTED_ENTITY, plan.entity_ids),
        )

    # Schritt 6
    receipt = conn.execute(
        """
        INSERT INTO erasure_receipts (subject_id, scope, requested_by, reason, affected, executed_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            subject_id,
            plan.scope,
            requested_by,
            reason,
            Jsonb(
                {
                    "roots": plan.roots,
                    "facts": ids,
                    "derived": plan.derived,
                    "edges": plan.edge_ids,
                    "trace_steps": redacted_steps,
                    "turns": plan.turn_ids,
                    "entities": plan.entity_ids,
                    "lineage": plan.lineage_ids,
                    "traces": plan.trace_ids,
                }
            ),
            at,
        ),
    ).fetchone()
    assert receipt is not None
    return ErasureReceipt(receipt_id=int(receipt["id"]), preview=plan, executed_at=at)


def redact_trace_steps(
    conn: psycopg.Connection, step_ids: Sequence[int], *, at: datetime
) -> list[int]:
    """Schwärzt ``input`` und ``output`` schemakonform.

    Abschnitt 7, Schritt 5: die Werte gehen, Struktur und Zeitstempel
    bleiben. Wer im Nachhinein prüfen will, ob eine Stufe gelaufen ist und
    wie lange sie gebraucht hat, kann das weiterhin -- nur *was* sie
    verarbeitet hat, steht nicht mehr da.
    """
    if not step_ids:
        return []
    rows = conn.execute(
        "SELECT id, input, output FROM trace_steps WHERE id = ANY(%s) AND redacted_at IS NULL",
        (list(step_ids),),
    ).fetchall()
    done: list[int] = []
    for row in rows:
        conn.execute(
            "UPDATE trace_steps SET input = %s, output = %s, redacted_at = %s WHERE id = %s",
            (
                Jsonb(redact_json(row["input"])) if row["input"] is not None else None,
                Jsonb(redact_json(row["output"])) if row["output"] is not None else None,
                at,
                row["id"],
            ),
        )
        done.append(int(row["id"]))
    return done


def redact_json(value: Any, _depth: int = 0) -> Any:
    """Ersetzt alle Blätter durch ``None``, behält Schlüssel und Längen.

    Aus ``{"candidates": [{"content": "Wohnt in Köln.", "confidence": 0.85}]}``
    wird ``{"candidates": [{"content": null, "confidence": null}]}``: die Form
    des Schritts bleibt lesbar, der Inhalt ist weg.
    """
    if _depth > 32:
        return None
    if isinstance(value, dict):
        return {key: redact_json(item, _depth + 1) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_json(item, _depth + 1) for item in value]
    return None


def receipts(
    conn: psycopg.Connection, *, subject_id: str, limit: int = 50
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, subject_id, scope, requested_by, reason, affected, executed_at
        FROM erasure_receipts WHERE subject_id = %s
        ORDER BY executed_at DESC, id DESC LIMIT %s
        """,
        (subject_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]
