# -*- coding: utf-8 -*-
"""Exception hierarchy for the harness.

The core never logs and never prints — it raises. Whatever wraps the core (a reference app, a
CLI, an embedding system) decides what the user sees, in which language, and what ends up in a
log line. ``error_code`` exists so that a failure can be recorded without putting document
content into a log; see ``docs/privacy.md``.
"""
from __future__ import annotations

from typing import Optional


class HarnessError(Exception):
    """Base class for every error this harness raises deliberately.

    ``code`` is a short, stable, non-sensitive identifier safe to log.
    """

    code = "HARNESS_ERROR"

    def __init__(self, message: str, code: Optional[str] = None) -> None:
        super().__init__(message)
        if code is not None:
            self.code = code


class EvidenceRuleViolation(HarnessError):
    """An entity broke one of the Evidence invariants (HARNESS.md section 6-4).

    Carries the full list of violations rather than only the first, so a caller can show a
    person everything that needs fixing at once.
    """

    code = "EVIDENCE_RULE_VIOLATION"

    def __init__(self, violations: list[str]) -> None:
        self.violations = list(violations)
        super().__init__("; ".join(self.violations))


class ProviderError(HarnessError):
    """A provider (storage, knowledge, llm, search) failed to fulfil its contract."""

    code = "PROVIDER_ERROR"


class UnknownFrameworkError(ProviderError):
    """A framework id was requested that the configured KnowledgeProvider does not have."""

    code = "UNKNOWN_FRAMEWORK"


class StructuredOutputError(ProviderError):
    """An LLM returned something that does not satisfy the requested schema."""

    code = "STRUCTURED_OUTPUT_INVALID"
