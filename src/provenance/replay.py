"""Replay.

Eine gespeicherte Sitzung gegen geänderte Prompts oder Parameter erneut
laufen lassen und das Ergebnis diffen (Abschnitt 6, Entwickleransicht).

Das ist der Nutzen der Regel „nichts wird überschrieben": weil die Beiträge
im Original stehen und die Fakten versioniert sind, lässt sich derselbe
Verlauf ein zweites Mal fahren und mit dem ersten vergleichen -- ohne den
ersten anzutasten.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

import psycopg

from provenance.prompts import prompt_refs
from provenance.service import MemoryService
from provenance.store import active_facts, list_turns

# Wiederholungsläufe und Eval-Läufe bekommen ein eigenes Präfix. Nur solche
# Kennungen dürfen hart gelöscht werden -- ein Tippfehler soll nicht echte
# Daten kosten.
REPLAY_PREFIX = "replay:"
PURGEABLE_PREFIXES = (REPLAY_PREFIX, "eval:")


@dataclass(slots=True)
class ReplayResult:
    source_subject: str
    target_subject: str
    session_id: str | None
    turns_replayed: int
    original: list[dict[str, Any]] = field(default_factory=list)
    replayed: list[dict[str, Any]] = field(default_factory=list)
    only_original: list[str] = field(default_factory=list)
    only_replay: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    prompt_refs: dict[str, str] = field(default_factory=dict)

    @property
    def differs(self) -> bool:
        return bool(self.only_original or self.only_replay)

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_subject": self.source_subject,
            "target_subject": self.target_subject,
            "session_id": self.session_id,
            "turns_replayed": self.turns_replayed,
            "prompt_refs": self.prompt_refs,
            "differs": self.differs,
            "diff": {
                "nur_im_original": self.only_original,
                "nur_im_wiederholungslauf": self.only_replay,
                "unverändert": self.unchanged,
            },
            "original": self.original,
            "wiederholt": self.replayed,
        }


def replay_session(
    conn: psycopg.Connection,
    *,
    service: MemoryService,
    source_subject: str,
    session_id: str | None = None,
    target_subject: str | None = None,
) -> ReplayResult:
    """Fährt die Beiträge einer Person erneut durch die Stufen 1--2."""
    target = target_subject or f"{REPLAY_PREFIX}{source_subject}"
    if target == source_subject:
        raise ValueError("Ziel und Quelle dürfen nicht dieselbe Kennung haben")

    turns = [
        turn
        for turn in list_turns(conn, subject_id=source_subject, limit=10_000)
        if session_id is None or turn["session_id"] == session_id
    ]

    purge_subject(conn, target)

    replayed_count = 0
    for turn in turns:
        if turn["redacted_at"]:
            # Ein geschwärzter Beitrag lässt sich nicht wiederholen -- der
            # Wortlaut ist weg. Das ist kein Fehler, sondern der Preis der
            # Löschung, und der Diff soll ihn zeigen.
            continue
        service.ingest_turn_in(
            conn,
            subject_id=target,
            session_id=turn["session_id"],
            role=turn["role"],
            content=turn["content"],
            occurred_at=turn["occurred_at"],
        )
        replayed_count += 1

    original = active_facts(conn, subject_id=source_subject, limit=10_000)
    replayed = active_facts(conn, subject_id=target, limit=10_000)

    original_keys = {_key(item["content"]): item["content"] for item in original}
    replay_keys = {_key(item["content"]): item["content"] for item in replayed}

    return ReplayResult(
        source_subject=source_subject,
        target_subject=target,
        session_id=session_id,
        turns_replayed=replayed_count,
        original=[_slim(item) for item in original],
        replayed=[_slim(item) for item in replayed],
        only_original=sorted(
            text for key, text in original_keys.items() if key not in replay_keys
        ),
        only_replay=sorted(text for key, text in replay_keys.items() if key not in original_keys),
        unchanged=sorted(text for key, text in original_keys.items() if key in replay_keys),
        prompt_refs=prompt_refs(),
    )


def purge_subject(conn: psycopg.Connection, subject_id: str) -> int:
    """Entfernt einen Wiederholungslauf restlos.

    Anders als eine Löschung nach Abschnitt 7 bleibt hier *nichts* stehen --
    ein Wiederholungslauf ist ein Rechenergebnis, kein Beleg. Deshalb ist die
    Operation auf Kennungen mit dem Präfix ``replay:`` beschränkt.
    """
    if not subject_id.startswith(PURGEABLE_PREFIXES):
        raise ValueError(
            f"purge_subject ist auf Kennungen mit den Präfixen {PURGEABLE_PREFIXES} beschränkt; "
            f"{subject_id!r} sieht nach echten Daten aus."
        )
    conn.execute("DELETE FROM edges WHERE subject_id = %s", (subject_id,))
    conn.execute("DELETE FROM entities WHERE subject_id = %s", (subject_id,))
    conn.execute(
        "DELETE FROM lineage WHERE trace_id IN (SELECT id FROM traces WHERE subject_id = %s)",
        (subject_id,),
    )
    conn.execute("DELETE FROM traces WHERE subject_id = %s", (subject_id,))
    result = conn.execute("DELETE FROM facts WHERE subject_id = %s", (subject_id,))
    deleted = result.rowcount
    conn.execute("DELETE FROM turns WHERE subject_id = %s", (subject_id,))
    conn.execute("DELETE FROM erasure_receipts WHERE subject_id = %s", (subject_id,))
    return deleted


_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE = re.compile(r"\s+")


def _key(content: str) -> str:
    folded = unicodedata.normalize("NFKD", (content or "").casefold())
    stripped = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return _SPACE.sub(" ", _PUNCT.sub(" ", stripped)).strip()


def _slim(fact: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": int(fact["id"]),
        "content": fact["content"],
        "valid_from": fact["valid_from"].isoformat() if fact["valid_from"] else None,
        "status": fact["status"],
    }
