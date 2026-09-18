# -*- coding: utf-8 -*-
"""Selecting a parser for a file type.

A mapping rather than a provider on the harness: intake is request-scoped, so a parser is
picked per file and forgotten. Binding one to a harness's lifetime would imply a persistence it
does not have — see ``core/interfaces/intake.py``.
"""
from __future__ import annotations

from typing import Mapping, Optional

from adapters.intake.html import HtmlParser
from adapters.intake.office import OfficeParser
from adapters.intake.pdf import PdfParser
from adapters.intake.text import TextParser
from core.errors import IntakeError, IntakeErrorCode
from core.interfaces.intake import DocumentParser
from core.intake.policy import DEFAULT_POLICY, IntakePolicy
from core.models import FileType


def default_parsers(policy: IntakePolicy = DEFAULT_POLICY) -> dict[FileType, DocumentParser]:
    """Every parser shipped with this repository, keyed by the type it handles."""
    parsers: dict[FileType, DocumentParser] = {}
    for parser in (TextParser(policy), HtmlParser(policy), PdfParser(policy), OfficeParser(policy)):
        for file_type in parser.supported_types:
            parsers[file_type] = parser
    return parsers


class ParserRegistry:
    """Maps a file type to the parser that handles it."""

    def __init__(
        self,
        parsers: Optional[Mapping[FileType, DocumentParser]] = None,
        *,
        policy: IntakePolicy = DEFAULT_POLICY,
    ) -> None:
        self.policy = policy
        self._parsers: dict[FileType, DocumentParser] = dict(
            parsers if parsers is not None else default_parsers(policy)
        )

    def for_type(self, file_type: FileType) -> DocumentParser:
        """The parser for ``file_type``.

        Raises ``UNSUPPORTED_FILE_TYPE`` when this deployment's policy excludes the type or no
        parser is registered for it. Both are configuration facts, not document faults.
        """
        if not self.policy.accepts(file_type):
            raise IntakeError(IntakeErrorCode.UNSUPPORTED_FILE_TYPE)
        parser = self._parsers.get(file_type)
        if parser is None:
            raise IntakeError(IntakeErrorCode.UNSUPPORTED_FILE_TYPE)
        return parser

    def supported_types(self) -> frozenset[FileType]:
        return frozenset(ft for ft in self._parsers if self.policy.accepts(ft))
