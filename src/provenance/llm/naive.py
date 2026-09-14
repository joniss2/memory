"""Vergleichsmaßstab: die übliche Konsolidierung.

Der Entwurf behauptet, dass Systeme an Stufe 2 brechen und dass es niemand
misst. Eine Eval, die nur das eigene Vorgehen bewertet, kann das nicht
belegen -- sie könnte auch schlicht zu leicht sein.

Dieser Anbieter macht deshalb das, was der übliche Zugriff macht: er sucht
den ähnlichsten bestehenden Fakt und löst ihn ab, wenn die Ähnlichkeit über
einer Schwelle liegt. Keine Prädikatslogik, keine Polarität, kein Begriff von
Widerruf, keine Unterscheidung zwischen dauerhaft und vorübergehend. Die
Extraktion bleibt dieselbe -- der Unterschied soll in Stufe 2 sichtbar
werden, nicht in Stufe 1.

Erwartung: auf Ersetzungsfällen -- den einzigen, die gängige Benchmarks
prüfen -- ist er kaum zu unterscheiden. Auf Verfeinerung, Befristung,
Scheinwiderspruch und Widerruf fällt er auseinander, und genau das weisen
Stale Rate und False Retraction aus.
"""

from __future__ import annotations

from typing import Any

from provenance.llm.heuristic import HeuristicProvider


class NaiveProvider(HeuristicProvider):
    name = "naive"

    #: Ab dieser Kosinusähnlichkeit gilt ein bestehender Fakt als „derselbe".
    similarity_threshold = 0.55

    def _consolidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate: dict[str, Any] = payload.get("candidate") or {}
        neighbours: list[dict[str, Any]] = payload.get("neighbours") or []

        scored = [
            (float(item.get("similarity") or 0.0), item)
            for item in neighbours
            if item.get("similarity") is not None
        ]
        if not scored:
            return {
                "op": "add",
                "target_fact_ids": [],
                "confidence": float(candidate.get("confidence") or 0.7),
                "rationale": "Nichts Ähnliches gefunden.",
            }

        similarity, best = max(scored, key=lambda pair: pair[0])
        if similarity >= self.similarity_threshold:
            return {
                "op": "update",
                "target_fact_ids": [int(best["id"])],
                # Hoch genug, um jede Schwelle aus Abschnitt 5 zu passieren:
                # eine Richtlinie kann ein zuversichtliches Modell nicht
                # umstimmen, nur ein unsicheres bremsen.
                "confidence": 0.9,
                "rationale": (
                    f"Sehr ähnlich zu einem bestehenden Fakt (Ähnlichkeit {similarity:.2f}); "
                    "der neue Wert ersetzt den alten."
                ),
            }
        return {
            "op": "add",
            "target_fact_ids": [],
            "confidence": float(candidate.get("confidence") or 0.7),
            "rationale": f"Ähnlichkeit {similarity:.2f} unter der Schwelle; als neu behandelt.",
        }
