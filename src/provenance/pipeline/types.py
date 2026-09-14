"""Die Werte, die zwischen den vier Stufen fließen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

DECISIONS = frozenset({"add", "update", "retract", "noop", "merge"})


@dataclass(slots=True)
class Candidate:
    """Ein Kandidatenfakt aus Stufe 1."""

    content: str
    confidence: float
    valid_from: datetime
    op_hint: str = "assert"
    triple: dict[str, Any] | None = None
    match_predicates: list[str] = field(default_factory=list)
    match_terms: list[str] = field(default_factory=list)
    temporary: bool = False
    source_text: str = ""

    def as_payload(self) -> dict[str, Any]:
        return {
            "content": self.content,
            "confidence": self.confidence,
            "valid_from": self.valid_from.isoformat(),
            "op_hint": self.op_hint,
            "triple": self.triple,
            "match_predicates": self.match_predicates,
            "match_terms": self.match_terms,
            "temporary": self.temporary,
            "source_text": self.source_text,
        }


@dataclass(slots=True)
class Discarded:
    text: str
    reason: str


@dataclass(slots=True)
class ExtractionResult:
    candidates: list[Candidate]
    non_extractions: list[Discarded]
    discarded: list[Discarded]
    step_id: int
    prompt_ref: str
    model: str

    @property
    def is_empty(self) -> bool:
        return not self.candidates


@dataclass(slots=True)
class Decision:
    """Das Ergebnis von Stufe 2 für genau einen Kandidaten."""

    op: str
    target_fact_ids: list[int]
    rationale: str
    confidence: float
    proposed_op: str | None = None
    policy_note: str | None = None

    @property
    def was_overridden(self) -> bool:
        return self.proposed_op is not None and self.proposed_op != self.op


@dataclass(slots=True)
class AppliedDecision:
    decision: Decision
    candidate: Candidate
    fact_id: int | None
    superseded: list[int] = field(default_factory=list)
    retracted: list[int] = field(default_factory=list)
    edge_ids: list[int] = field(default_factory=list)
    closed_edge_ids: list[int] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "op": self.decision.op,
            "proposed_op": self.decision.proposed_op,
            "policy_note": self.decision.policy_note,
            "rationale": self.decision.rationale,
            "confidence": self.decision.confidence,
            "fact_id": self.fact_id,
            "superseded": self.superseded,
            "retracted": self.retracted,
            "content": self.candidate.content,
        }


@dataclass(slots=True)
class RetrievedFact:
    fact_id: int
    content: str
    score: float
    sources: dict[str, int]
    valid_from: datetime | None = None
    status: str = "active"
    origin_turn: int | None = None
    confidence: float | None = None


@dataclass(slots=True)
class Injection:
    text: str
    included: list[RetrievedFact]
    dropped: list[dict[str, Any]]
    tokens_used: int
    token_budget: int
