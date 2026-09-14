"""Deterministischer Ersatz für ein Sprachmodell.

Wozu das gut ist: Tests, Eval-Läufe und ein `docker run` ohne Modell sollen
durchlaufen und echte Zahlen liefern. Der Ersatz erfüllt dieselben beiden
Verträge wie ein echtes Modell -- Extraktion und Konsolidierung -- über eine
kleine, deklarative Mustertabelle.

Wozu das *nicht* gut ist: Qualitätsaussagen. Wer die Kennzahlen aus
Abschnitt 9 als Aussage über das Produkt lesen will, muss gegen ein echtes
Modell messen (PROVENANCE_LLM_PROVIDER=openai). Die Zahlen dieses Ersatzes
sagen etwas über die Mechanik der Pipeline aus, nichts über Sprachverständnis.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from provenance.llm.base import LLMRequest, LLMResponse, estimate_tokens

# --------------------------------------------------------------------------
# Prädikate und ihre Kardinalität
#
# Einwertige Prädikate vertragen nur einen aktiven Wert: wer nach Leipzig
# zieht, wohnt nicht mehr in Köln. Mehrwertige vertragen mehrere: wer Kaffee
# mag, darf auch Tee mögen. Die Unterscheidung entscheidet in Stufe 2
# zwischen 'update' und 'add' -- und ist damit die Stellschraube, an der
# False Retraction hängt.
# --------------------------------------------------------------------------

SINGLE_VALUED = frozenset({"wohnt_in", "arbeitet_bei", "heisst", "status"})

# Prädikatpaare, die einander widersprechen.
POLARITY_PARTNER = {"mag": "mag_nicht", "mag_nicht": "mag"}


@dataclass(frozen=True)
class Pattern:
    regex: re.Pattern[str]
    predicate: str
    object_group: int
    object_kind: str | None
    temporary: bool = False
    confidence: float = 0.85


def _p(
    pattern: str,
    predicate: str,
    object_group: int = 1,
    object_kind: str | None = None,
    temporary: bool = False,
    confidence: float = 0.85,
) -> Pattern:
    return Pattern(
        regex=re.compile(pattern, re.IGNORECASE),
        predicate=predicate,
        object_group=object_group,
        object_kind=object_kind,
        temporary=temporary,
        confidence=confidence,
    )


# Reihenfolge ist bedeutsam: das erste Muster gewinnt. "Ich bin nach Leipzig
# gezogen" muss vor "ich bin X" stehen, sonst wird der Umzug zur Eigenschaft.
PATTERNS: tuple[Pattern, ...] = (
    # -- Umzug / Wohnort ---------------------------------------------------
    _p(r"\bich\s+(?:bin|war)\s+(?:gerade\s+)?nach\s+(.+?)\s+(?:um)?gezogen\b", "wohnt_in", 1, "ort"),
    _p(r"\bich\s+ziehe\s+nach\s+(.+?)(?:\s+um)?$", "wohnt_in", 1, "ort"),
    _p(r"\bich\s+wohne\s+(?:jetzt\s+|inzwischen\s+|mittlerweile\s+)?in\s+(.+)$", "wohnt_in", 1, "ort"),
    _p(r"\bich\s+lebe\s+(?:jetzt\s+|inzwischen\s+)?in\s+(.+)$", "wohnt_in", 1, "ort"),
    _p(r"\bi\s+(?:have\s+)?moved\s+to\s+(.+)$", "wohnt_in", 1, "ort"),
    _p(r"\bi\s+live\s+in\s+(.+)$", "wohnt_in", 1, "ort"),
    # -- Arbeitgeber -------------------------------------------------------
    _p(r"\bich\s+arbeite\s+(?:jetzt\s+|inzwischen\s+)?(?:bei|für)\s+(.+)$", "arbeitet_bei", 1, "organisation"),
    _p(r"\bmein\s+arbeitgeber\s+ist\s+(.+)$", "arbeitet_bei", 1, "organisation"),
    _p(r"\bich\s+habe\s+(?:bei|zu)\s+(.+?)\s+angefangen\b", "arbeitet_bei", 1, "organisation"),
    _p(r"\bi\s+work\s+(?:at|for)\s+(.+)$", "arbeitet_bei", 1, "organisation"),
    # -- Name --------------------------------------------------------------
    _p(r"\bich\s+hei(?:ß|ss)e\s+(.+)$", "heisst", 1, "person"),
    _p(r"\bmy\s+name\s+is\s+(.+)$", "heisst", 1, "person"),
    # -- Vorübergehender Zustand ------------------------------------------
    _p(
        r"\bich\s+bin\s+(?:gerade|zurzeit|zur\s+zeit|momentan|aktuell)\s+(?:in\s+)?(.+)$",
        "status",
        1,
        None,
        temporary=True,
    ),
    _p(r"\bi\s+am\s+(?:currently|right\s+now)\s+(?:on\s+|in\s+)?(.+)$", "status", 1, None, temporary=True),
    # -- Abneigung (vor Zuneigung, sonst schluckt 'mag' die Verneinung) ----
    _p(r"\bich\s+mag\s+kein(?:e|en|em)?\s+(.+)$", "mag_nicht", 1),
    _p(r"\bich\s+(?:trinke|esse)\s+kein(?:e|en|em)?\s+(.+)$", "mag_nicht", 1),
    _p(r"\bich\s+(?:trinke|esse)\s+(?:aber\s+)?kein(?:e|en|em)?\s+(.+)$", "mag_nicht", 1),
    _p(r"\bkein(?:e|en)?\s+(.+?)\s+(?:mehr\s+)?für\s+mich\b", "mag_nicht", 1),
    _p(r"\bi\s+(?:do\s+not|don't|dont)\s+(?:like|drink|eat)\s+(.+)$", "mag_nicht", 1),
    # -- Zuneigung ---------------------------------------------------------
    _p(r"\bich\s+mag\s+(?:am\s+liebsten\s+|vor\s+allem\s+|nur\s+)?(.+)$", "mag", 1),
    _p(r"\bich\s+(?:trinke|esse)\s+(?:am\s+liebsten|gerne?|nur)\s+(.+)$", "mag", 1),
    _p(r"\bich\s+liebe\s+(.+)$", "mag", 1),
    _p(r"\bi\s+(?:like|love|prefer)\s+(.+)$", "mag", 1),
    # -- Besitz / Zugehörigkeit -------------------------------------------
    _p(r"\bich\s+habe\s+(?:einen|eine|ein)\s+(.+)$", "hat", 1),
    _p(r"\bi\s+have\s+(?:a|an)\s+(.+)$", "hat", 1),
    # -- Eigenschaft (Auffangmuster, deshalb zuletzt) ---------------------
    _p(r"\bich\s+bin\s+(?:seit\s+\S+\s+)?(.+)$", "ist", 1, None, confidence=0.8),
    _p(r"\bi\s+(?:am|'m)\s+(.+)$", "ist", 1, None, confidence=0.8),
)

REVOCATION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bvergiss(?:\s+bitte)?,?\s+was\s+ich\s+(?:dir\s+)?(?:über|zu)\s+(.+?)\s+(?:gesagt|erzählt)", re.IGNORECASE),
    re.compile(r"\b(?:vergiss|streich|lösch(?:e)?)\s+(?:bitte\s+)?(?:alles\s+(?:über|zu)\s+)?(?:meine[nrs]?\s+|die\s+|das\s+|den\s+)?(.+?)\s*$", re.IGNORECASE),
    re.compile(r"\bforget\s+(?:what\s+i\s+(?:said|told\s+you)\s+about\s+)?(?:my\s+)?(.+?)\s*$", re.IGNORECASE),
)

# Worüber gesprochen wird -> welche Prädikate das betrifft. Ein echtes Modell
# leistet diese Auflösung selbst; hier steht sie als Tabelle.
TOPIC_PREDICATES: dict[str, tuple[str, ...]] = {
    "arbeitgeber": ("arbeitet_bei",),
    "arbeit": ("arbeitet_bei",),
    "job": ("arbeitet_bei",),
    "firma": ("arbeitet_bei",),
    "employer": ("arbeitet_bei",),
    "work": ("arbeitet_bei",),
    "wohnort": ("wohnt_in",),
    "adresse": ("wohnt_in",),
    "address": ("wohnt_in",),
    "zuhause": ("wohnt_in",),
    "name": ("heisst",),
    "essen": ("mag", "mag_nicht", "ist"),
    "ernährung": ("mag", "mag_nicht", "ist"),
    "diet": ("mag", "mag_nicht", "ist"),
    "food": ("mag", "mag_nicht", "ist"),
    "getränke": ("mag", "mag_nicht"),
    "kaffee": ("mag", "mag_nicht"),
}

GREETINGS = re.compile(
    r"^(?:hallo|hi|hey|guten\s+(?:morgen|tag|abend)|moin|servus|danke|dankeschön|"
    r"ok(?:ay)?|alles\s+klar|bis\s+später|tschüss|ciao|hello|thanks|thank\s+you|bye)\b",
    re.IGNORECASE,
)

HEDGES = re.compile(r"\b(?:vielleicht|eventuell|ich\s+glaube|ich\s+denke|womöglich|maybe|i\s+think|probably)\b", re.IGNORECASE)

_MONTH_NAMES = {
    "januar": 1, "january": 1, "februar": 2, "february": 2, "märz": 3, "maerz": 3, "march": 3,
    "april": 4, "mai": 5, "may": 5, "juni": 6, "june": 6, "juli": 7, "july": 7,
    "august": 8, "september": 9, "oktober": 10, "october": 10, "november": 11,
    "dezember": 12, "december": 12,
}

# Die Schlüssel laufen durch dieselbe Faltung wie der gesuchte Text -- sonst
# findet _normalise("März") == "marz" den Eintrag "märz" nie.
MONTHS = {}

SINCE = re.compile(r"\bseit\s+(?:dem\s+)?([\wäöüß]+)(?:\s+(\d{4}))?", re.IGNORECASE)
SINCE_EN = re.compile(r"\bsince\s+([\w]+)(?:\s+(\d{4}))?", re.IGNORECASE)

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
TRAILING_PUNCT = re.compile(r"[\s.,;:!?]+$")

# Füllwörter, die als Objekt nichts taugen.
STOP_OBJECTS = frozenset({"das", "es", "dies", "hier", "da", "so", "it", "that", "this"})


def _strip(text: str) -> str:
    return TRAILING_PUNCT.sub("", text.strip())


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).strip()


MONTHS.update({_normalise(name): number for name, number in _MONTH_NAMES.items()})


def _split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT.split(text or "") if s.strip()]


def _parse_since(sentence: str, reference: datetime) -> str | None:
    """Löst 'seit März' bzw. 'since March' in einen Gültigkeitsbeginn auf."""
    for pattern in (SINCE, SINCE_EN):
        match = pattern.search(sentence)
        if not match:
            continue
        token = _normalise(match.group(1))
        year_token = match.group(2)
        if token.isdigit() and len(token) == 4:
            return datetime(int(token), 1, 1, tzinfo=UTC).isoformat()
        month = MONTHS.get(token)
        if month is None:
            continue
        year = int(year_token) if year_token else reference.year
        candidate = datetime(year, month, 1, tzinfo=UTC)
        if not year_token and candidate > reference:
            candidate = datetime(year - 1, month, 1, tzinfo=UTC)
        return candidate.isoformat()
    return None


def _looks_like_question(sentence: str) -> bool:
    return sentence.rstrip().endswith("?")


class HeuristicProvider:
    """Erfüllt den Modellvertrag über Muster statt über Sprachverständnis."""

    name = "heuristic"

    def complete(self, request: LLMRequest) -> LLMResponse:
        if request.task == "extract":
            result = self._extract(request.payload)
        elif request.task == "consolidate":
            result = self._consolidate(request.payload)
        else:  # pragma: no cover - Vertrag kennt nur zwei Aufgaben
            raise ValueError(f"unbekannte Aufgabe: {request.task!r}")
        text = json.dumps(result, ensure_ascii=False)
        return LLMResponse(
            text=text,
            model=f"heuristic/{request.task}",
            tokens_in=estimate_tokens(request.user),
            tokens_out=estimate_tokens(text),
        )

    # -- Stufe 1 ----------------------------------------------------------

    def _extract(self, payload: dict[str, Any]) -> dict[str, Any]:
        turn = payload.get("turn") or {}
        content: str = turn.get("content") or ""
        role: str = turn.get("role") or "user"
        subject: str = payload.get("subject_label") or payload.get("subject_id") or "subject"
        occurred_raw = turn.get("occurred_at")
        reference = _parse_dt(occurred_raw) or datetime.now(UTC)

        facts: list[dict[str, Any]] = []
        non_extractions: list[dict[str, str]] = []
        seen: set[str] = set()

        for sentence in _split_sentences(content):
            if role != "user":
                non_extractions.append(
                    {"text": sentence, "reason": "Turn stammt nicht von der betroffenen Person"}
                )
                continue
            if _looks_like_question(sentence):
                non_extractions.append({"text": sentence, "reason": "Frage, keine Aussage"})
                continue
            if GREETINGS.match(sentence):
                non_extractions.append({"text": sentence, "reason": "Höflichkeitsfloskel ohne Faktengehalt"})
                continue

            revocation = self._match_revocation(sentence)
            if revocation is not None:
                revocation["source_text"] = sentence
                facts.append(revocation)
                continue

            candidate = self._match_assertion(sentence, subject, reference)
            if candidate is None:
                non_extractions.append(
                    {"text": sentence, "reason": "kein belastbarer Fakt über die betroffene Person erkennbar"}
                )
                continue

            key = _normalise(candidate["content"])
            if key in seen:
                non_extractions.append({"text": sentence, "reason": "Dublette innerhalb desselben Turns"})
                continue
            seen.add(key)
            candidate["source_text"] = sentence
            facts.append(candidate)

        return {"facts": facts, "non_extractions": non_extractions}

    def _match_revocation(self, sentence: str) -> dict[str, Any] | None:
        for pattern in REVOCATION_PATTERNS:
            match = pattern.search(sentence)
            if not match:
                continue
            topic = _strip(match.group(1))
            if not topic or _normalise(topic) in STOP_OBJECTS:
                continue
            predicates: list[str] = []
            for word in re.findall(r"[\wäöüß]+", _normalise(topic)):
                predicates.extend(TOPIC_PREDICATES.get(word, ()))
            return {
                "content": f"Widerruf: Angaben zu „{topic}“ sollen vergessen werden.",
                "confidence": 0.9,
                "op_hint": "retract",
                "match_predicates": sorted(set(predicates)),
                "match_terms": [topic],
                "triple": None,
                "valid_from": None,
            }
        return None

    def _match_assertion(self, sentence: str, subject: str, reference: datetime) -> dict[str, Any] | None:
        for pattern in PATTERNS:
            match = pattern.regex.search(sentence)
            if not match:
                continue
            obj = _strip(match.group(pattern.object_group))
            if not obj or _normalise(obj) in STOP_OBJECTS or len(obj) > 120:
                continue
            confidence = pattern.confidence
            if HEDGES.search(sentence):
                confidence = round(max(0.1, confidence - 0.25), 2)
            valid_from = _parse_since(sentence, reference)
            return {
                "content": _render_content(pattern.predicate, obj),
                "confidence": confidence,
                "op_hint": "assert",
                "valid_from": valid_from,
                "temporary": pattern.temporary,
                "triple": {
                    "src": subject,
                    "src_kind": "person",
                    "predicate": pattern.predicate,
                    "dst": obj,
                    "dst_kind": pattern.object_kind,
                },
            }
        return None

    # -- Stufe 2 ----------------------------------------------------------

    def _consolidate(self, payload: dict[str, Any]) -> dict[str, Any]:
        candidate: dict[str, Any] = payload.get("candidate") or {}
        neighbours: list[dict[str, Any]] = payload.get("neighbours") or []

        if candidate.get("op_hint") == "retract":
            return self._consolidate_revocation(candidate, neighbours)

        cand_triple = candidate.get("triple") or {}
        cand_pred = cand_triple.get("predicate")
        cand_dst = _normalise(str(cand_triple.get("dst") or ""))
        cand_src = _normalise(str(cand_triple.get("src") or ""))
        confidence = float(candidate.get("confidence") or 0.5)

        exact: list[int] = []
        slot_conflicts: list[int] = []
        polarity_conflicts: list[int] = []

        for neighbour in neighbours:
            triple = neighbour.get("triple") or {}
            n_pred = triple.get("predicate")
            n_dst = _normalise(str(triple.get("dst") or ""))
            n_src = _normalise(str(triple.get("src") or ""))

            if cand_pred and n_pred and cand_src == n_src:
                if n_pred == cand_pred and n_dst == cand_dst:
                    exact.append(int(neighbour["id"]))
                    continue
                if n_pred == cand_pred and cand_pred in SINGLE_VALUED:
                    slot_conflicts.append(int(neighbour["id"]))
                    continue
                if POLARITY_PARTNER.get(cand_pred) == n_pred and n_dst == cand_dst:
                    polarity_conflicts.append(int(neighbour["id"]))
                    continue

            # Ohne Tripel bleibt nur Textähnlichkeit -- und die trägt nur
            # eine Dublettenentscheidung, keine Überschreibung.
            if not cand_pred and not n_pred and float(neighbour.get("similarity") or 0.0) >= 0.97:
                exact.append(int(neighbour["id"]))

        if exact:
            return {
                "op": "noop",
                "target_fact_ids": exact[:1],
                "confidence": confidence,
                "rationale": "Inhaltsgleich zu einem bereits aktiven Fakt; nichts zu ändern.",
            }
        if polarity_conflicts:
            return {
                "op": "update",
                "target_fact_ids": polarity_conflicts,
                "confidence": confidence,
                "rationale": (
                    f"Aussage kehrt die Polarität zu „{cand_triple.get('dst')}“ um; "
                    "der bisherige Fakt wird abgelöst, nicht gelöscht."
                ),
            }
        if slot_conflicts:
            return {
                "op": "update",
                "target_fact_ids": slot_conflicts,
                "confidence": confidence,
                "rationale": (
                    f"„{cand_pred}“ ist einwertig und trägt jetzt einen anderen Wert; "
                    "der bisherige Fakt wird abgelöst."
                ),
            }
        return {
            "op": "add",
            "target_fact_ids": [],
            "confidence": confidence,
            "rationale": "Kein Konflikt mit bestehenden Fakten erkennbar.",
        }

    def _consolidate_revocation(
        self, candidate: dict[str, Any], neighbours: list[dict[str, Any]]
    ) -> dict[str, Any]:
        predicates = set(candidate.get("match_predicates") or ())
        terms = [_normalise(t) for t in (candidate.get("match_terms") or ()) if t]
        targets: list[int] = []
        for neighbour in neighbours:
            triple = neighbour.get("triple") or {}
            predicate = triple.get("predicate")
            haystack = _normalise(str(neighbour.get("content") or ""))
            if predicate and predicate in predicates or any(term and term in haystack for term in terms):
                targets.append(int(neighbour["id"]))
        if not targets:
            return {
                "op": "noop",
                "target_fact_ids": [],
                "confidence": float(candidate.get("confidence") or 0.9),
                "rationale": "Widerruf ohne auffindbaren Bezug; nichts zurückzuziehen.",
            }
        return {
            "op": "retract",
            "target_fact_ids": sorted(set(targets)),
            "confidence": float(candidate.get("confidence") or 0.9),
            "rationale": "Ausdrücklicher Widerruf durch die betroffene Person.",
        }


def _render_content(predicate: str, obj: str) -> str:
    templates = {
        "wohnt_in": "Wohnt in {o}.",
        "arbeitet_bei": "Arbeitet bei {o}.",
        "heisst": "Heißt {o}.",
        "mag": "Mag {o}.",
        "mag_nicht": "Mag kein {o}.",
        "hat": "Hat {o}.",
        "ist": "Ist {o}.",
        "status": "Ist zurzeit {o}.",
    }
    return templates.get(predicate, "{o}.").format(o=obj)


def _parse_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None
