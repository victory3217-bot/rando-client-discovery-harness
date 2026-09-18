# -*- coding: utf-8 -*-
"""Document parsing contract.

The boundary is ``bytes``, not a path. The core names the type; it never opens anything. That
choice has a practical consequence worth stating: all eight supported formats can be parsed
from memory, so this implementation creates no temporary file of its own. The surest way to
clean up a temporary file is not to have made one. (What a parsing library or the runtime does
internally is a separate matter — see ``docs/privacy.md``.)

A parser receives no filename and has no parameter to put one in. Keeping the original name out
of the system is a structural property here rather than a rule someone has to remember.

This is not one of the four providers passed to :func:`core.harness.create_harness`. Intake is
request-scoped: a parser is selected per file, used, and forgotten. Binding it to the lifetime
of a harness would suggest a persistence it does not have.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.intake.models import ExtractedDocument
from core.models import FileType


@runtime_checkable
class DocumentParser(Protocol):
    """Turns the bytes of one document into addressable segments.

    Implementations raise :class:`core.errors.IntakeError` with a code from
    :class:`core.errors.IntakeErrorCode`, never a library-specific exception, and never one
    whose message quotes the document.
    """

    #: Short adapter identifier, safe to log (e.g. ``"pdf"``, ``"office"``, ``"text"``).
    name: str

    #: The types this parser handles.
    supported_types: frozenset[FileType]

    def parse(self, data: bytes, *, file_type: FileType) -> ExtractedDocument: ...
