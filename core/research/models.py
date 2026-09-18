# -*- coding: utf-8 -*-
"""Transient objects for one research run.

Like ``core/intake/models.py``, nothing here is persisted and nothing gets a schema in
``schemas/``. Evidence blocks carry document text, so they define a ``__repr__`` that omits it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from core.models import KeyIssue, ResearchFinding, SWOTIssue


@dataclass(repr=False)
class EvidenceEntry:
    """One passage, under the short key the model is asked to cite it by."""

    ref: str
    text: str
    #: The candidate this came from, so a cited ref resolves back to real provenance.
    candidate: object
    truncated: bool = False

    def __repr__(self) -> str:
        return (
            f"<EvidenceEntry {self.ref} chars={len(self.text)} truncated={self.truncated}>"
        )


@dataclass(repr=False)
class EvidenceBlock:
    """A batch of passages plus the map that turns a cited ref back into provenance.

    The refs (``E1``, ``E2``, …) exist because ``LLMProvider.analyze`` takes plain strings. A
    model cannot hand back an object reference, but it can repeat a short key, and a key that is
    not in this map is a fabrication the pipeline rejects.
    """

    entries: list[EvidenceEntry] = field(default_factory=list)

    def lines(self) -> list[str]:
        """The strings handed to the provider, each prefixed with its ref."""
        return [f"[{entry.ref}] {entry.text}" for entry in self.entries]

    def resolve(self, ref: str) -> Optional[EvidenceEntry]:
        for entry in self.entries:
            if entry.ref == ref:
                return entry
        return None

    @property
    def char_count(self) -> int:
        return sum(len(entry.text) for entry in self.entries)

    def __repr__(self) -> str:
        return f"<EvidenceBlock entries={len(self.entries)} chars={self.char_count}>"


#: Longest reference kept on a rejection or a flag.
_MAX_REFERENCE_CHARS = 60

_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9_,.\- ]*$")


def safe_reference(value: object) -> str:
    """Reduce a value to something safe to record.

    Rejections and flags are diagnostics, and a diagnostic that quotes the document defeats the
    logging rules everything else in this harness follows. Identifiers, short reference keys and
    enum-shaped tokens pass through; anything else becomes a placeholder.
    """
    text = "" if value is None else str(value)
    if len(text) > _MAX_REFERENCE_CHARS or not _SAFE_REFERENCE.match(text):
        return "<omitted>"
    return text


class RejectionCode:
    """Why something was refused. A closed set, so a run can be summarised by counts."""

    ITEM_NOT_AN_OBJECT = "ITEM_NOT_AN_OBJECT"
    EMPTY_STATEMENT = "EMPTY_STATEMENT"
    UNUSABLE_EVIDENCE_TYPE = "UNUSABLE_EVIDENCE_TYPE"
    UNUSABLE_CATEGORY = "UNUSABLE_CATEGORY"
    UNKNOWN_EVIDENCE_REF = "UNKNOWN_EVIDENCE_REF"
    NO_SOURCE_RECORD = "NO_SOURCE_RECORD"
    NO_SUPPORTING_FINDING = "NO_SUPPORTING_FINDING"
    NO_FINDING_RESOLVED = "NO_FINDING_RESOLVED"
    NO_SWOT_RESOLVED = "NO_SWOT_RESOLVED"
    MISSING_DECISION_AREA = "MISSING_DECISION_AREA"
    MISSING_STRATEGIC_IMPLICATION = "MISSING_STRATEGIC_IMPLICATION"


REJECTION_CODES = frozenset(
    value
    for name, value in vars(RejectionCode).items()
    if not name.startswith("_") and isinstance(value, str)
)


class FlagCode:
    """Something worth a person's attention that is not grounds for discarding the record."""

    IMPLICATION_READS_AS_DIRECTIVE = "IMPLICATION_READS_AS_DIRECTIVE"


@dataclass
class Rejection:
    """Something the model produced that the pipeline refused to keep.

    Recorded rather than discarded silently. A run that quietly drops half of what it generated
    looks identical to a run that generated little, and an operator needs to be able to tell
    those apart — a high rejection count is a signal about the prompt or the provider.

    Carries a code, the stage and a reference. Never the text that was rejected.
    """

    stage: str
    code: str
    reference: str = ""

    def __post_init__(self) -> None:
        self.reference = safe_reference(self.reference)

    def __repr__(self) -> str:
        return f"<Rejection {self.stage}/{self.code} ref={self.reference!r}>"


@dataclass
class ReviewFlag:
    """A note for the person reviewing the output. Not a rejection.

    Used where a signal is worth surfacing but is too unreliable to discard a record on. The
    directive-phrase check is the case in point: matching on wording is language-specific and
    wrong in both directions, so it raises a flag and leaves the judgement to a reader.
    """

    stage: str
    code: str
    reference: str = ""

    def __post_init__(self) -> None:
        self.reference = safe_reference(self.reference)

    def __repr__(self) -> str:
        return f"<ReviewFlag {self.stage}/{self.code} ref={self.reference!r}>"


@dataclass
class ResearchOutcome:
    """Everything one research run produced, including what it threw away."""

    findings: list[ResearchFinding] = field(default_factory=list)
    swot_issues: list[SWOTIssue] = field(default_factory=list)
    key_issues: list[KeyIssue] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    #: Notes for the reviewer. Unlike a rejection, the record itself was kept.
    review_flags: list[ReviewFlag] = field(default_factory=list)
    #: Frameworks the shortlist skipped, with the reason. Empty when the shortlist is off.
    skipped_frameworks: list[tuple[str, str]] = field(default_factory=list)
    #: One record per external call, for logging. Carries counts, never text.
    transmissions: list = field(default_factory=list)

    @property
    def facts(self) -> list[ResearchFinding]:
        from core.models import EvidenceType

        return [f for f in self.findings if f.evidence_type is EvidenceType.FACT]

    def summary(self) -> dict:
        """Counts only — safe to log."""
        from core.models import EvidenceType

        by_type = {t.value: 0 for t in EvidenceType}
        for finding in self.findings:
            by_type[finding.evidence_type.value] += 1
        return {
            "findings": len(self.findings),
            "by_evidence_type": by_type,
            "swot_issues": len(self.swot_issues),
            "key_issues": len(self.key_issues),
            "rejections": len(self.rejections),
            "review_flags": len(self.review_flags),
            "transmissions": len(self.transmissions),
        }
