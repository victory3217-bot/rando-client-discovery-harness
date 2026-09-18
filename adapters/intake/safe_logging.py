# -*- coding: utf-8 -*-
"""What an application is allowed to log about an ingested document.

An **allowlist**, not a deny-list. A deny-list leaks every time a field is added and nobody
remembers to exclude it; an allowlist fails closed.

``display_label`` is deliberately absent. It is free text a person typed and may well contain a
client's name — the exact thing that must not accumulate in log files. It is fine in a record
the operator chose to keep; it is not fine in a log line.
"""
from __future__ import annotations

from typing import Any, Optional

from core.errors import IntakeError
from core.intake.models import IntakeResult
from core.models import SourceMetadata, as_dict

#: The complete set of fields that may be logged about intake. Nothing else, ever.
ALLOWED_LOG_FIELDS = frozenset(
    {
        "source_id",
        "project_id",
        "file_type",
        "file_size",
        "page_count",
        "processing_status",
        "error_code",
        "ingested_at",
        "parser",
        "exception_type",
        "segment_count",
        "duration_ms",
    }
)


def safe_fields(source: SourceMetadata, **extra: Any) -> dict:
    """Build a log-safe mapping from a source record plus optional extras.

    Anything outside :data:`ALLOWED_LOG_FIELDS` is dropped silently rather than raising: a
    logging helper that throws during error handling turns one problem into two.
    """
    record = {
        key: value
        for key, value in as_dict(source).items()
        if key in ALLOWED_LOG_FIELDS and value is not None
    }
    for key, value in extra.items():
        if key in ALLOWED_LOG_FIELDS and value is not None:
            record[key] = value
    return record


def safe_result_fields(result: IntakeResult, **extra: Any) -> dict:
    """Log-safe mapping for a whole intake result, including the candidate count.

    The count, never the candidates: their text is the document.
    """
    return safe_fields(result.source, segment_count=len(result.candidates), **extra)


def safe_error_fields(error: IntakeError, source_id: Optional[str] = None) -> dict:
    """Log-safe mapping for a failure.

    Carries the code, the parser and the originating exception's *class name*. The original
    exception message is not available here by construction — ``adapters.intake.guard`` discards
    it at the point of conversion rather than storing it for later.
    """
    return {
        key: value
        for key, value in {
            "source_id": source_id,
            "error_code": error.code,
            "parser": error.parser,
            "exception_type": error.exception_type,
        }.items()
        if key in ALLOWED_LOG_FIELDS and value is not None
    }
