# -*- coding: utf-8 -*-
"""Allowlist logging. A field that is not on the list cannot be logged by accident.

``adapters/intake/safe_logging.py`` does the same job for intake and is the model for this.
The reason it is an allowlist and not a denylist is that a denylist is a list somebody
eventually forgets to extend — and the field they forget is the filename.

Records are emitted as ``key=value`` pairs so a line stays greppable without a parser.
"""
from __future__ import annotations

import logging
from typing import Any

#: Everything a proof log line may contain. Nothing else is emitted, ever.
ALLOWED_FIELDS: frozenset[str] = frozenset(
    {
        "request_id",
        "run_id",
        "session_id",
        "route",
        "method",
        "status",
        "latency_ms",
        "error_code",
        "byte_count",
        "part_count",
        "candidate_count",
        "finding_count",
        "llm_calls",
    }
)

#: Names that look plausible and must never appear. Kept only so the test can assert that the
#: allowlist excludes them — the enforcement is the allowlist itself, not this set.
NEVER_LOGGED: frozenset[str] = frozenset(
    {
        "filename",
        "file_name",
        "document",
        "text",
        "content",
        "prompt",
        "cookie",
        "csrf_token",
        "session_cookie",
        "email",
        "phone",
        "body",
        "request_body",
        "display_label",
    }
)

_logger = logging.getLogger("phase8.proof")


def safe_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Drop everything not on the allowlist. Silent by design: a caller that passes a
    forbidden field gets it removed rather than getting an exception that might be caught and
    logged with the field in the message."""
    return {k: v for k, v in fields.items() if k in ALLOWED_FIELDS}


def log_event(event: str, **fields: Any) -> str:
    """Emit one event. Returns the rendered line so tests can assert on exactly what was written."""
    kept = safe_fields(fields)
    line = event + ("  " + " ".join(f"{k}={v}" for k, v in sorted(kept.items())) if kept else "")
    _logger.info(line)
    return line
