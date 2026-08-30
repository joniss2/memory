"""Prompt-Vorlagen mit Versionskennung.

``prompt_ref`` ist Name plus Inhaltshash. Ohne diese Kennung ist ein Trace
von vor drei Wochen nicht interpretierbar, weil niemand mehr weiß, welche
Extraktionsanweisung damals galt (Abschnitt 4.5). Weil der Hash über den
Inhalt läuft, ändert jede Bearbeitung der Vorlage die Kennung -- auch die,
bei der jemand vergisst, die Versionsnummer hochzuzählen.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

PROMPTS_DIR = Path(__file__).parent

_SECTION = re.compile(r"^---\s*(system|user)\s*---\s*$", re.MULTILINE)
_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")


@dataclass(frozen=True)
class Prompt:
    name: str
    system: str
    user: str
    ref: str

    def render(self, **values: Any) -> tuple[str, str]:
        return _fill(self.system, values), _fill(self.user, values)


def _fill(template: str, values: dict[str, Any]) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in values:
            raise KeyError(f"Platzhalter {{{{{key}}}}} ohne Wert")
        return str(values[key])

    return _PLACEHOLDER.sub(replace, template)


@lru_cache(maxsize=32)
def load_prompt(name: str) -> Prompt:
    """Lädt ``<name>.md`` und leitet die Versionskennung aus dem Inhalt ab."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.is_file():
        raise FileNotFoundError(f"keine Prompt-Vorlage {name!r} unter {path}")
    raw = path.read_text("utf-8")

    parts = _SECTION.split(raw)
    # parts == ['<Vorspann>', 'system', '<...>', 'user', '<...>']
    sections: dict[str, str] = {}
    for index in range(1, len(parts) - 1, 2):
        sections[parts[index]] = parts[index + 1].strip()
    if "system" not in sections or "user" not in sections:
        raise ValueError(f"Vorlage {name!r} braucht einen system- und einen user-Abschnitt")

    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
    return Prompt(name=name, system=sections["system"], user=sections["user"], ref=f"{name}@{digest}")


def prompt_refs() -> dict[str, str]:
    """Kennungen aller ausgelieferten Vorlagen -- für Health-Endpunkt und Dashboard."""
    return {path.stem: load_prompt(path.stem).ref for path in sorted(PROMPTS_DIR.glob("*.md"))}
