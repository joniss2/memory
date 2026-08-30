"""Die vier Kennzahlen aus Abschnitt 9.

* **Update Recall** -- kennt das System nach der Änderung den neuen Wert?
* **Stale Rate** -- liefert es weiterhin den alten? *Die Kennzahl, die heute
  niemand ausweist.*
* **False Retraction** -- hat ein Scheinwiderspruch einen korrekten Fakt
  gekillt?
* **Erasure Completeness** -- ist nach einer Löschung wirklich alles
  Abgeleitete weg?

Alle vier werden gegen den *tatsächlich in den Prompt gestellten Text* aus
Stufe 4 gemessen, nicht gegen die Trefferliste aus Stufe 3. Ein Fakt, der
gefunden wurde und am Budget scheiterte, ist für den Agenten genauso
abwesend wie einer, der nie extrahiert wurde -- und muss darum genauso
zählen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Kind(StrEnum):
    UPDATE_RECALL = "update_recall"
    STALE = "stale"
    FALSE_RETRACTION = "false_retraction"
    ERASURE = "erasure"


class Outcome(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    # Der Fakt war nie da: das ist ein Extraktionsbefund, kein Rückzug. Er
    # wird berichtet, zählt aber nicht in die False-Retraction-Quote -- sonst
    # sähe ein System, das gar nichts extrahiert, in dieser Kennzahl gut aus.
    UNSUPPORTED = "unsupported"


@dataclass(slots=True)
class Probe:
    kind: Kind
    scenario: str
    checkpoint: str
    needle: str
    outcome: Outcome
    detail: str = ""

    @property
    def failed(self) -> bool:
        return self.outcome is Outcome.FAIL

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "scenario": self.scenario,
            "checkpoint": self.checkpoint,
            "needle": self.needle,
            "outcome": self.outcome.value,
            "detail": self.detail,
        }


@dataclass(slots=True)
class Metrics:
    probes: list[Probe] = field(default_factory=list)

    def add(self, probe: Probe) -> None:
        self.probes.append(probe)

    def _counts(self, kind: Kind) -> tuple[int, int, int]:
        subset = [probe for probe in self.probes if probe.kind is kind]
        passed = sum(1 for probe in subset if probe.outcome is Outcome.PASS)
        failed = sum(1 for probe in subset if probe.outcome is Outcome.FAIL)
        unsupported = sum(1 for probe in subset if probe.outcome is Outcome.UNSUPPORTED)
        return passed, failed, unsupported

    def rate(self, kind: Kind, *, of_failures: bool = False) -> float | None:
        passed, failed, _ = self._counts(kind)
        total = passed + failed
        if total == 0:
            return None
        return (failed if of_failures else passed) / total

    @property
    def update_recall(self) -> float | None:
        return self.rate(Kind.UPDATE_RECALL)

    @property
    def stale_rate(self) -> float | None:
        """Anteil der Proben, bei denen der überholte Wert weiterhin geliefert wird."""
        return self.rate(Kind.STALE, of_failures=True)

    @property
    def false_retraction(self) -> float | None:
        return self.rate(Kind.FALSE_RETRACTION, of_failures=True)

    @property
    def erasure_completeness(self) -> float | None:
        return self.rate(Kind.ERASURE)

    def summary(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for kind, name, inverted in (
            (Kind.UPDATE_RECALL, "update_recall", False),
            (Kind.STALE, "stale_rate", True),
            (Kind.FALSE_RETRACTION, "false_retraction", True),
            (Kind.ERASURE, "erasure_completeness", False),
        ):
            passed, failed, unsupported = self._counts(kind)
            out[name] = {
                "wert": self.rate(kind, of_failures=inverted),
                "proben": passed + failed,
                "bestanden": passed,
                "gescheitert": failed,
                "ohne_grundlage": unsupported,
            }
        return out


NEEDLE_REGEX = re.compile(r"^re:(.*)$", re.DOTALL)


def matches(needle: str, haystack: str) -> bool:
    """Findet ``needle`` in ``haystack``.

    Vorgabe ist ein Teilstring ohne Rücksicht auf Groß- und Kleinschreibung.
    Mit dem Präfix ``re:`` wird der Rest als regulärer Ausdruck gelesen --
    nötig für Proben, die eine Zahl oder eine Wortgrenze prüfen wollen.
    """
    match = NEEDLE_REGEX.match(needle)
    if match:
        return re.search(match.group(1), haystack, re.IGNORECASE | re.MULTILINE) is not None
    return needle.casefold() in (haystack or "").casefold()
