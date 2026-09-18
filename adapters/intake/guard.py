# -*- coding: utf-8 -*-
"""Turning library exceptions into codes, without carrying the document along.

A parsing library that fails describes the failure in a sentence, and that sentence routinely
quotes the bytes or the text that confused it. ``"invalid literal for int() with base 10:
'매출 1,240백만원'"`` is a perfectly ordinary Python error message and also a line out of
somebody's financial statement. Let it propagate and it lands in the log, the stack trace and
the error tracker.

:func:`parser_guard` converts any unexpected exception into an :class:`IntakeError` carrying
only a code and the originating exception's class name. ``raise ... from None`` matters as much
as the conversion: without it the original exception stays attached as ``__cause__`` and
``traceback.format_exc()`` prints its message anyway.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from core.errors import IntakeError, IntakeErrorCode


@contextmanager
def parser_guard(parser_name: str, *, code: str = IntakeErrorCode.EXTRACT_FAILED) -> Iterator[None]:
    """Convert any leaking exception into an :class:`IntakeError` with no document content."""
    try:
        yield
    except IntakeError:
        # Already a code. Re-raise unchanged: it was raised deliberately and carries no text.
        raise
    except Exception as exc:  # noqa: BLE001 - converting is the entire point
        raise IntakeError(
            code,
            parser=parser_name,
            exception_type=type(exc).__name__,
        ) from None
