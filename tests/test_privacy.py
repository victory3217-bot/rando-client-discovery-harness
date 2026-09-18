# -*- coding: utf-8 -*-
"""Privacy by Default, checked rather than promised.

Phase 1 has no file intake yet, so there is no uploaded document to trace through the system.
What can be checked now is the shape of the thing that will hold document provenance — and
shape is where this normally goes wrong: a ``filename`` field added for debugging, a ``text``
field added "temporarily", an exception message carrying a paragraph of a client's strategy
into a log.

The end-to-end canary test (upload a document containing a unique string, assert it appears in
no log, no temporary directory and no store) belongs to Phase 2 and is listed in
docs/development-guide.md.
"""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from core.models import SourceMetadata, new_id

#: Field names that would mean the harness is holding on to document content or to a name that
#: can itself identify a client.
FORBIDDEN_FIELD_SUBSTRINGS = (
    "filename",
    "file_name",
    "original_name",
    "path",
    "raw",
    "content",
    "text",
    "body",
    "extract",
    "blob",
)


def test_source_metadata_holds_no_filename_and_no_content() -> None:
    names = {f.name for f in dataclasses.fields(SourceMetadata)}
    offenders = [
        name
        for name in sorted(names)
        for bad in FORBIDDEN_FIELD_SUBSTRINGS
        if bad in name.lower()
    ]
    assert not offenders, (
        f"SourceMetadata has fields that would retain document content or a client-identifying "
        f"name: {offenders}. See docs/privacy.md."
    )


def test_source_metadata_schema_is_closed(repo_root: Path) -> None:
    """``additionalProperties: false`` is what stops an adapter adding such a field anyway."""
    with (repo_root / "schemas" / "source_metadata.schema.json").open(encoding="utf-8") as fh:
        schema = json.load(fh)

    assert schema["additionalProperties"] is False

    offenders = [
        name
        for name in sorted(schema["properties"])
        for bad in FORBIDDEN_FIELD_SUBSTRINGS
        if bad in name.lower()
    ]
    assert not offenders, f"source_metadata schema declares: {offenders}"


def test_source_ids_are_random_not_derived() -> None:
    """Two uploads of the same document must not produce the same id.

    A content- or name-derived id leaks information about the document through every log line
    and every URL that carries it.
    """
    ids = {new_id("src") for _ in range(200)}
    assert len(ids) == 200

    for value in ids:
        assert value.startswith("src_")
        assert len(value) > 20, "identifiers should be long enough not to be guessable"


def test_purged_is_a_terminal_status() -> None:
    """The privacy story depends on there being a state that means 'the original is gone'."""
    from core.models import ProcessingStatus

    assert ProcessingStatus.PURGED.value == "PURGED"
    assert {s.value for s in ProcessingStatus} == {
        "PENDING",
        "EXTRACTED",
        "FAILED",
        "PURGED",
    }


def test_error_code_exists_so_messages_need_not_be_logged() -> None:
    """Exception text is the most common way document content reaches a log file."""
    names = {f.name for f in dataclasses.fields(SourceMetadata)}
    assert "error_code" in names

    from core.errors import EvidenceRuleViolation, HarnessError, ProviderError

    assert HarnessError("x").code == "HARNESS_ERROR"
    assert ProviderError("x").code == "PROVIDER_ERROR"
    assert EvidenceRuleViolation(["a", "b"]).code == "EVIDENCE_RULE_VIOLATION"


def test_gitignore_blocks_uploaded_document_types(repo_root: Path) -> None:
    """A commit is the most permanent place an uploaded file can end up."""
    text = (repo_root / ".gitignore").read_text(encoding="utf-8")
    for pattern in ("*.pdf", "*.docx", "*.pptx", "*.xlsx", "clients/", "uploads/", ".env"):
        assert pattern in text, f".gitignore should block {pattern}"
