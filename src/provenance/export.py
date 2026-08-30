"""Auskunft.

Dieselben Tabellen wie die Entwickleransicht, andere Sprache: Fakten,
Quellen, Zeitpunkte -- keine Modell-Interna (Abschnitt 6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import psycopg

from provenance.erasure import receipts
from provenance.store import all_facts, list_turns

OP_LABELS = {
    "add": "aufgenommen",
    "update": "abgelöst durch einen neueren Stand",
    "retract": "zurückgezogen",
    "noop": "bestätigt, ohne Änderung",
    "merge": "mit einem anderen Eintrag zusammengeführt",
}

STATUS_LABELS = {
    "active": "gilt",
    "superseded": "abgelöst",
    "retracted": "zurückgezogen",
    "erased": "gelöscht",
}


# Obergrenzen, damit eine Auskunft nicht unbegrenzt Speicher zieht. Sie werden
# um eine Zeile überzogen abgefragt: nur so lässt sich „genau so viele" von
# „mindestens so viele" unterscheiden. Wird eine erreicht, muss das im Bericht
# stehen -- sonst behauptet der Hinweis unten eine Vollständigkeit, die eine
# Auskunft nach Art. 15 gerade zusichern soll.
FACT_LIMIT = 10_000
TURN_LIMIT = 10_000
RECEIPT_LIMIT = 1_000


def subject_export(
    conn: psycopg.Connection, *, subject_id: str, include_history: bool = True
) -> dict[str, Any]:
    """Vollständige Auskunft über eine betroffene Person."""
    facts = all_facts(conn, subject_id=subject_id, limit=FACT_LIMIT + 1)
    turns = list_turns(conn, subject_id=subject_id, limit=TURN_LIMIT + 1)
    belege = receipts(conn, subject_id=subject_id, limit=RECEIPT_LIMIT + 1)

    abgeschnitten = [
        name
        for name, rows, cap in (
            ("Aussagen", facts, FACT_LIMIT),
            ("Gesprächsbeiträge", turns, TURN_LIMIT),
            ("Löschbelege", belege, RECEIPT_LIMIT),
        )
        if len(rows) > cap
    ]
    facts = facts[:FACT_LIMIT]
    turns = turns[:TURN_LIMIT]
    belege = belege[:RECEIPT_LIMIT]

    turn_index = {int(turn["id"]): turn for turn in turns}

    exported: list[dict[str, Any]] = []
    for fact in facts:
        if fact["status"] == "erased":
            continue
        origin = turn_index.get(int(fact["origin_turn"])) if fact["origin_turn"] else None
        exported.append(
            {
                "id": int(fact["id"]),
                "aussage": fact["content"],
                "status": STATUS_LABELS.get(fact["status"], fact["status"]),
                "gilt_seit": _iso(fact["valid_from"]),
                "gilt_bis": _iso(fact["valid_to"]),
                "gespeichert_am": _iso(fact["recorded_at"]),
                "quelle": None
                if origin is None
                else {
                    "turn_id": int(origin["id"]),
                    "gesagt_am": _iso(origin["occurred_at"]),
                    "wortlaut": "(gelöscht)" if origin.get("redacted_at") else origin["content"],
                },
            }
        )

    # Erst jetzt, und nur für die Fakten, die tatsächlich ausgeliefert werden:
    # sonst lud die Auskunft die gesamte Lineage der Person, um den größeren
    # Teil davon wieder wegzuwerfen.
    history = (
        _history(conn, subject_id, [item["id"] for item in exported]) if include_history else {}
    )
    for item in exported:
        item["verlauf"] = history.get(item["id"], [])

    return {
        "betroffene_person": subject_id,
        "erstellt_am": datetime.now().astimezone().isoformat(),
        "vollstaendig": not abgeschnitten,
        "hinweis": (
            "Diese Auskunft enthält alle gespeicherten Aussagen über die genannte Person, "
            "ihre Quelle und ihren Verlauf. Abgelöste und zurückgezogene Aussagen sind "
            "als solche gekennzeichnet und werden nicht mehr ausgeliefert."
        )
        if not abgeschnitten
        else (
            f"Diese Auskunft ist unvollständig: {' und '.join(abgeschnitten)} wurden an der "
            "Obergrenze abgeschnitten. Für eine vollständige Auskunft muss sie seitenweise "
            "abgerufen werden."
        ),
        "aussagen": exported,
        "gespraechsbeitraege": [
            {
                "id": int(turn["id"]),
                "sitzung": turn["session_id"],
                "rolle": turn["role"],
                "wortlaut": "(gelöscht)" if turn.get("redacted_at") else turn["content"],
                "zeitpunkt": _iso(turn["occurred_at"]),
            }
            for turn in turns
        ],
        "loeschbelege": [
            {
                "id": int(item["id"]),
                "umfang": item["scope"],
                "grund": item["reason"],
                "ausgefuehrt_am": _iso(item["executed_at"]),
                "betroffen": item["affected"],
            }
            for item in belege
        ],
    }


def fact_history(conn: psycopg.Connection, *, fact_id: int) -> list[dict[str, Any]]:
    """Die Kette über ``lineage``, lesbar dargestellt (Abschnitt 6)."""
    rows = conn.execute(
        """
        SELECT l.id, l.fact_id, l.parent_id, l.op, l.rationale, l.created_at,
               l.proposed_op, t.turn_id, tu.occurred_at, tu.content AS turn_content,
               tu.redacted_at, f.content AS fact_content
        FROM lineage l
        JOIN traces t ON t.id = l.trace_id
        LEFT JOIN turns tu ON tu.id = t.turn_id
        LEFT JOIN facts f ON f.id = l.fact_id
        WHERE l.fact_id = %s OR l.parent_id = %s
        ORDER BY l.created_at, l.id
        """,
        (fact_id, fact_id),
    ).fetchall()
    return [
        {
            "zeitpunkt": _iso(row["created_at"]),
            "vorgang": OP_LABELS.get(row["op"], row["op"]),
            "vorgang_technisch": row["op"],
            "betroffener_fakt": int(row["fact_id"]),
            "abgeleitet_aus": int(row["parent_id"]) if row["parent_id"] else None,
            "begruendung": row["rationale"],
            "vom_modell_vorgeschlagen": row["proposed_op"],
            "ausloesender_beitrag": None
            if row["turn_id"] is None
            else {
                "turn_id": int(row["turn_id"]),
                "gesagt_am": _iso(row["occurred_at"]),
                "wortlaut": "(gelöscht)" if row["redacted_at"] else row["turn_content"],
            },
        }
        for row in rows
    ]


def _history(
    conn: psycopg.Connection, subject_id: str, fact_ids: list[int]
) -> dict[int, list[dict[str, Any]]]:
    """Der Verlauf zu genau den Fakten, die die Auskunft ausliefert.

    ``parent_id`` bleibt in der Bedingung: ein Fakt, der einen ausgelieferten
    abgelöst hat, gehört zu dessen Verlauf, auch wenn er selbst nicht in der
    Liste steht.
    """
    if not fact_ids:
        return {}
    rows = conn.execute(
        """
        SELECT l.fact_id, l.parent_id, l.op, l.rationale, l.created_at, l.proposed_op, t.turn_id
        FROM lineage l
        JOIN traces t ON t.id = l.trace_id
        JOIN facts f ON f.id = l.fact_id
        WHERE f.subject_id = %s
          AND (l.fact_id = ANY(%s) OR l.parent_id = ANY(%s))
        ORDER BY l.created_at, l.id
        """,
        (subject_id, fact_ids, fact_ids),
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        entry = {
            "zeitpunkt": _iso(row["created_at"]),
            "vorgang": OP_LABELS.get(row["op"], row["op"]),
            "begruendung": row["rationale"],
            "abgeleitet_aus": int(row["parent_id"]) if row["parent_id"] else None,
            "ausloesender_beitrag": int(row["turn_id"]) if row["turn_id"] else None,
        }
        grouped.setdefault(int(row["fact_id"]), []).append(entry)
        if row["parent_id"]:
            grouped.setdefault(int(row["parent_id"]), []).append(
                {**entry, "hinweis": f"wurde durch Fakt {int(row['fact_id'])} abgelöst"}
            )
    return grouped


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None
