"""Deterministische Einbettung ohne Modell.

Wort-Token plus Zeichen-4-Gramme werden in einen festen Vektorraum gehasht.
Das ist kein Sprachverständnis -- Paraphrasen ohne gemeinsame Wortstämme
liegen weit auseinander --, aber es ist reproduzierbar, netzfrei und trägt
genug Ähnlichkeitsstruktur, um Stufe 2 und Stufe 3 ernsthaft auszuüben.

Die Zeichen-N-Gramme sind der Grund, warum „wohnt" und „wohne" einander noch
sehen; über reine Wort-Token wäre deutsche Flexion für dieses Verfahren
unsichtbar.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence

TOKEN = re.compile(r"[\wäöüßÄÖÜ]+", re.UNICODE)

WORD_WEIGHT = 1.0
NGRAM_WEIGHT = 0.35
NGRAM_SIZE = 4


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def _bucket(token: str, dim: int) -> tuple[int, float]:
    digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
    value = int.from_bytes(digest, "big")
    return value % dim, 1.0 if (value >> 63) & 1 else -1.0


class HashingEmbedder:
    name = "hashing"

    def __init__(self, dim: int = 1024) -> None:
        if dim <= 0:
            raise ValueError("dim muss positiv sein")
        self.dim = dim

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        normalised = _normalise(text or "")
        words = TOKEN.findall(normalised)

        for word in words:
            index, sign = _bucket(f"w:{word}", self.dim)
            vector[index] += sign * WORD_WEIGHT

        padded = f" {' '.join(words)} "
        for start in range(max(0, len(padded) - NGRAM_SIZE + 1)):
            gram = padded[start : start + NGRAM_SIZE]
            index, sign = _bucket(f"g:{gram}", self.dim)
            vector[index] += sign * NGRAM_WEIGHT

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            # Leerer Text: ein fester Einheitsvektor ist besser als ein
            # Nullvektor, für den Kosinusabstand undefiniert ist.
            vector[0] = 1.0
            return vector
        return [v / norm for v in vector]
