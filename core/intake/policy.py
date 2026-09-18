# -*- coding: utf-8 -*-
"""Intake policy: limits, type identification rules, and text decoding.

Everything here is pure. The core states *what the rules are*; an adapter carries them out,
because the core may not open a file, a stream or an archive.

:class:`IntakePolicy` is a plain frozen dataclass with defaults chosen for a public web
deployment. The core never reads an environment variable — an application that needs different
limits constructs its own policy and passes it in.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

from core.errors import IntakeError, IntakeErrorCode
from core.models import FileType

_MIB = 1024 * 1024


@dataclass(frozen=True)
class IntakePolicy:
    """Limits applied to one intake session.

    Defaults target a public deployment accepting uploads from anyone. A self-hosted
    installation processing its own documents will usually raise them.
    """

    #: Largest single upload accepted, before any parsing is attempted.
    max_file_bytes: int = 25 * _MIB

    #: Largest total *declared uncompressed* size inside one OOXML package. Guards against an
    #: archive that is small on the wire and enormous once expanded.
    max_uncompressed_bytes: int = 200 * _MIB

    #: Largest total across every file in one session.
    max_batch_bytes: int = 100 * _MIB

    #: Longest display label kept. Anything beyond this is truncated, not rejected.
    max_display_label_chars: int = 100

    #: File types this deployment accepts.
    supported_types: frozenset[FileType] = frozenset(FileType)

    def accepts(self, file_type: FileType) -> bool:
        return file_type in self.supported_types


#: The default policy, used when a caller does not supply one.
DEFAULT_POLICY = IntakePolicy()


# ---------------------------------------------------------------------------
# type identification
# ---------------------------------------------------------------------------

#: Leading bytes that identify a binary container. Text formats have no signature, which is
#: itself a useful fact: a file declared as CSV must *not* match any of these.
MAGIC_SIGNATURES: tuple[tuple[bytes, frozenset[FileType]], ...] = (
    (b"%PDF-", frozenset({FileType.PDF})),
    (b"PK\x03\x04", frozenset({FileType.DOCX, FileType.PPTX, FileType.XLSX})),
)

#: Types whose content is a ZIP package and therefore cannot be told apart by magic bytes alone.
OOXML_TYPES = frozenset({FileType.DOCX, FileType.PPTX, FileType.XLSX})

#: Text formats, identified by the *absence* of a binary signature.
TEXT_TYPES = frozenset({FileType.CSV, FileType.TXT, FileType.MD, FileType.HTML})

#: The main document part of each OOXML package. Checking these rather than the top-level
#: directory names matters: a DOCX may legitimately contain an embedded workbook, and a rule
#: based on "does it contain xl/" would then misidentify it.
OOXML_MAIN_PARTS: dict[FileType, str] = {
    FileType.DOCX: "word/document.xml",
    FileType.PPTX: "ppt/presentation.xml",
    FileType.XLSX: "xl/workbook.xml",
}

#: Fallback directory prefixes, used only when no main part is found.
OOXML_PREFIXES: dict[FileType, str] = {
    FileType.DOCX: "word/",
    FileType.PPTX: "ppt/",
    FileType.XLSX: "xl/",
}

#: Every OOXML package declares its parts here. Its absence means the ZIP is not OOXML at all.
OOXML_CONTENT_TYPES = "[Content_Types].xml"

#: Enough bytes for every signature above.
MAGIC_PREFIX_BYTES = 8


def classify_magic(head: bytes) -> Optional[frozenset[FileType]]:
    """Which types the leading bytes are consistent with.

    Returns ``None`` when no binary signature matches, which means the data may be text.
    """
    for signature, types in MAGIC_SIGNATURES:
        if head.startswith(signature):
            return types
    return None


def resolve_ooxml(entry_names: Iterable[str]) -> Optional[FileType]:
    """Identify an OOXML package from the names of its entries.

    The caller (an adapter) opens the archive and reads its central directory; deciding what the
    names mean stays here. Returns ``None`` when the package is not OOXML or is ambiguous —
    the caller then reports a type mismatch rather than guessing.
    """
    names = set(entry_names)
    if OOXML_CONTENT_TYPES not in names:
        return None

    by_main_part = [ft for ft, part in OOXML_MAIN_PARTS.items() if part in names]
    if len(by_main_part) == 1:
        return by_main_part[0]
    if len(by_main_part) > 1:
        return None

    by_prefix = [
        ft
        for ft, prefix in OOXML_PREFIXES.items()
        if any(name.startswith(prefix) for name in names)
    ]
    return by_prefix[0] if len(by_prefix) == 1 else None


def check_declared_type(declared: FileType, head: bytes) -> None:
    """Reject a file whose leading bytes contradict its declared type.

    An extension is a claim, not evidence. For OOXML this check can only establish "it is a ZIP";
    :func:`resolve_ooxml` finishes the job once the adapter has opened the archive.

    Raises :class:`core.errors.IntakeError` with ``TYPE_MISMATCH``.
    """
    matched = classify_magic(head)

    if declared in TEXT_TYPES:
        if matched is not None:
            raise IntakeError(IntakeErrorCode.TYPE_MISMATCH)
        return

    if matched is None or declared not in matched:
        raise IntakeError(IntakeErrorCode.TYPE_MISMATCH)


# ---------------------------------------------------------------------------
# archive limits
# ---------------------------------------------------------------------------

def check_archive_size(declared_sizes: Iterable[int], policy: IntakePolicy) -> None:
    """Apply the uncompressed-size limit before any entry is decompressed.

    A ZIP central directory declares each entry's uncompressed size, so the total can be
    checked without expanding anything. That is the part of the guard available up front, and
    it stops the classic highly-compressed bomb.

    It is not a complete defence: the declared sizes are supplied by the archive itself and a
    hostile file can understate them. The file-size limit bounds what a liar can attempt, and
    the parsing libraries read entries individually rather than expanding the whole package.

    Raises ``ARCHIVE_LIMIT_EXCEEDED``.
    """
    total = 0
    for size in declared_sizes:
        total += max(int(size), 0)
        if total > policy.max_uncompressed_bytes:
            raise IntakeError(IntakeErrorCode.ARCHIVE_LIMIT_EXCEEDED)


# ---------------------------------------------------------------------------
# text decoding
# ---------------------------------------------------------------------------

#: Tried in order. UTF-8-SIG first so a BOM is consumed rather than becoming a stray character;
#: CP949 last because Korean business documents exported from older tooling are still common.
TEXT_ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp949")


def decode_text(data: bytes) -> str:
    """Decode a text payload, trying each supported encoding in turn.

    Raises ``TEXT_DECODE_FAILED`` when none succeeds. The underlying ``UnicodeDecodeError`` is
    deliberately not propagated and not attached: its message quotes the offending bytes, which
    is document content.
    """
    for encoding in TEXT_ENCODINGS:
        try:
            return data.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
    raise IntakeError(IntakeErrorCode.TEXT_DECODE_FAILED)


# ---------------------------------------------------------------------------
# display label
# ---------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")


def normalize_display_label(raw: Optional[str], policy: IntakePolicy = DEFAULT_POLICY) -> Optional[str]:
    """Clean a label a person typed, or return ``None``.

    A display label is **supplied by the person uploading**, never derived from a filename. It
    exists so that an analyst with a dozen uploads can tell which one a finding came from, and
    it is the only human-chosen text this harness keeps about a source.

    Control characters are removed and runs of whitespace collapsed, so the value cannot carry
    a newline into a log line or a terminal escape into a report.

    Each control character becomes a space rather than disappearing: a tab between two words is
    a word boundary, and deleting it outright would silently turn ``"3분기\t전망"`` into one
    word.
    """
    if raw is None:
        return None

    printable = "".join(ch if ch.isprintable() else " " for ch in raw)
    collapsed = _WHITESPACE.sub(" ", printable).strip()
    if not collapsed:
        return None
    return collapsed[: policy.max_display_label_chars]
