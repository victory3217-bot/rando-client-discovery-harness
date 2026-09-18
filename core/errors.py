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


class IntakeErrorCode:
    """The closed set of reasons a document can fail to be ingested.

    Codes rather than messages, because the thing that went wrong is usually described by the
    parsing library in a sentence that quotes the document — see ``docs/privacy.md``.
    """

    UNSUPPORTED_FILE_TYPE = "UNSUPPORTED_FILE_TYPE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    BATCH_TOO_LARGE = "BATCH_TOO_LARGE"
    TYPE_MISMATCH = "TYPE_MISMATCH"
    PARSER_UNAVAILABLE = "PARSER_UNAVAILABLE"
    ENCRYPTED_DOCUMENT = "ENCRYPTED_DOCUMENT"
    EXTRACT_NO_TEXT_LAYER = "EXTRACT_NO_TEXT_LAYER"
    EMPTY_DOCUMENT = "EMPTY_DOCUMENT"
    MALFORMED_DOCUMENT = "MALFORMED_DOCUMENT"
    ARCHIVE_LIMIT_EXCEEDED = "ARCHIVE_LIMIT_EXCEEDED"
    TEXT_DECODE_FAILED = "TEXT_DECODE_FAILED"
    EXTRACT_FAILED = "EXTRACT_FAILED"


#: Every code an :class:`IntakeError` may carry. Tests assert that no failure path invents one.
INTAKE_ERROR_CODES = frozenset(
    value
    for name, value in vars(IntakeErrorCode).items()
    if not name.startswith("_") and isinstance(value, str)
)


class IntakeError(HarnessError):
    """A document could not be ingested.

    The exception message is the code and nothing else. Parsing libraries raise errors whose
    text quotes the bytes or the text that confused them, and that text is the user's document;
    attaching it here would put it into every log line and stack trace that touches this error.

    ``exception_type`` keeps the originating exception's *class name* — ``PdfReadError``,
    ``KeyError`` — which is useful when debugging and carries no document content. The original
    message is discarded, not stored.
    """

    code = "INTAKE_FAILED"

    def __init__(
        self,
        code: str,
        *,
        parser: Optional[str] = None,
        exception_type: Optional[str] = None,
    ) -> None:
        self.parser = parser
        self.exception_type = exception_type
        super().__init__(code, code=code)

    def __repr__(self) -> str:
        return (
            f"IntakeError(code={self.code!r}, parser={self.parser!r}, "
            f"exception_type={self.exception_type!r})"
        )
