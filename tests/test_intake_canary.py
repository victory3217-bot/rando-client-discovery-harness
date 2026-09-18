# -*- coding: utf-8 -*-
"""Canary tests: a unique string goes into a document and must not come out anywhere it should not.

Each of the eight formats gets a document containing ``CANARY``. After a full intake run the
string must appear in exactly one place — the evidence candidates, which are transient and
never stored — and in none of these:

1. log records
2. the filesystem (this implementation creates no temporary file)
3. anything handed to a ``StorageProvider``
4. ``repr`` of any intake object
5. an exception's message or its formatted traceback
6. the serialised ``SourceMetadata``

**What these tests can and cannot establish.** They cover this repository: its logging, its
exceptions, its ``repr`` implementations and what it passes to storage. They cannot cover an
APM agent that captures local variables, a debugger that snapshots frames, or a web framework
that logs request bodies. Those are configuration outside this codebase and ``docs/privacy.md``
says what has to be switched off.
"""
from __future__ import annotations

import logging
import tempfile
import traceback
from pathlib import Path

import pytest

from adapters.intake import IntakeSession, safe_error_fields, safe_fields, safe_result_fields
from adapters.intake.safe_logging import ALLOWED_LOG_FIELDS
from adapters.storage.memory import MemoryStorage
from core.errors import IntakeError, IntakeErrorCode
from core.models import FileType, SourceCategory, as_dict
from intake_fixtures import BUILDERS, CANARY

PROJECT = "prj_canary"


@pytest.fixture(params=sorted(BUILDERS), ids=sorted(BUILDERS))
def ingested(request):
    """One intake run per supported format, with the canary inside the document."""
    type_name = request.param
    with IntakeSession(PROJECT) as session:
        result = session.ingest(
            bytearray(BUILDERS[type_name]()),
            file_type=FileType[type_name],
            source_category=SourceCategory.COMPANY_DATA,
            display_label=f"{type_name} fixture",
        )
    return type_name, result


# -- the canary must survive where it is supposed to -----------------------

def test_canary_reaches_the_evidence_candidates(ingested) -> None:
    """The control case. If this fails the other assertions prove nothing."""
    type_name, result = ingested
    assert result.ok, f"{type_name}: {result.source.error_code}"
    assert any(CANARY in c.text for c in result.candidates)


# -- 1. logs ---------------------------------------------------------------

def test_canary_never_reaches_a_log_record(ingested, caplog) -> None:
    _, result = ingested
    logger = logging.getLogger("intake.test")

    with caplog.at_level(logging.DEBUG):
        logger.info("ingested", extra={"intake": safe_result_fields(result)})
        logger.info("source", extra={"intake": safe_fields(result.source)})

    rendered = "\n".join(
        f"{record.getMessage()} {getattr(record, 'intake', '')}" for record in caplog.records
    )
    assert CANARY not in rendered
    assert caplog.records, "the test must actually have logged something"


def test_log_helpers_drop_everything_outside_the_allowlist(ingested) -> None:
    _, result = ingested
    fields = safe_result_fields(result, duration_ms=12)

    assert set(fields) <= ALLOWED_LOG_FIELDS
    assert fields["source_id"] == result.source.source_id
    assert fields["segment_count"] == len(result.candidates)


def test_display_label_is_not_in_the_logging_allowlist(ingested) -> None:
    """It is free text a person typed and may hold a client name."""
    _, result = ingested
    assert result.source.display_label, "the fixture supplies a label"
    assert "display_label" not in ALLOWED_LOG_FIELDS
    assert "display_label" not in safe_fields(result.source)
    assert result.source.display_label not in str(safe_result_fields(result))


# -- 2. the filesystem -----------------------------------------------------

def test_intake_leaves_no_file_in_the_temp_directory() -> None:
    """All eight formats parse from memory, so this implementation makes nothing to clean up.

    Scope: this observes what the harness leaves behind. It is not a claim that no byte ever
    reaches a disk — a parsing library, the allocator or the OS paging out memory are all
    outside its reach. See docs/privacy.md sections 1 and 2.
    """
    temp_root = Path(tempfile.gettempdir())
    before = set(temp_root.iterdir())

    with IntakeSession(PROJECT) as session:
        for type_name, build in BUILDERS.items():
            session.ingest(
                bytearray(build()),
                file_type=FileType[type_name],
                source_category=SourceCategory.COMPANY_DATA,
            )

    created = set(temp_root.iterdir()) - before
    assert not created, f"intake left files behind: {sorted(p.name for p in created)}"


def test_intake_adapters_do_not_open_files() -> None:
    """Structural check: no file handling anywhere in the intake adapters."""
    import ast

    intake_dir = Path(__file__).resolve().parent.parent / "adapters" / "intake"
    offenders: list[str] = []

    for path in sorted(intake_dir.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in {"open", "print"}:
                    offenders.append(f"{path.name}:{node.lineno} {node.func.id}()")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.split(".")[0] in {"tempfile", "shutil"}:
                        offenders.append(f"{path.name}:{node.lineno} import {alias.name}")
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.split(".")[0] in {"tempfile", "shutil"}:
                    offenders.append(f"{path.name}:{node.lineno} from {node.module}")

    assert not offenders, f"intake touches the filesystem: {offenders}"


# -- 3. storage ------------------------------------------------------------

def test_canary_never_reaches_storage(ingested) -> None:
    """Only the source record may be persisted, and it holds no document text."""
    _, result = ingested
    storage = MemoryStorage()
    storage.save_source_metadata(result.source)

    stored = storage.get_source_metadata(PROJECT)
    assert len(stored) == 1
    assert CANARY not in str(as_dict(stored[0]))


def test_storage_has_no_way_to_persist_a_candidate() -> None:
    """The absence of a save method is the control, not a convention to remember."""
    from core.interfaces.storage import StorageProvider

    methods = {name for name in dir(StorageProvider) if name.startswith("save_")}
    assert not any("candidate" in name or "evidence" in name for name in methods), methods
    assert not hasattr(MemoryStorage(), "save_evidence_candidate")


# -- 4. repr ---------------------------------------------------------------

def test_canary_never_appears_in_a_repr(ingested) -> None:
    """A debugger or a %r in a log line prints a shape, not a paragraph."""
    _, result = ingested

    assert CANARY not in repr(result)
    assert CANARY not in repr(result.source)
    for candidate in result.candidates:
        assert CANARY not in repr(candidate)
        assert CANARY not in f"{candidate!r}"


def test_repr_still_says_something_useful(ingested) -> None:
    """A redacted repr that says nothing would just get replaced by a raw one."""
    _, result = ingested
    text = repr(result.candidates[0])
    assert "EvidenceCandidate" in text
    assert "chars=" in text and "locator=" in text


def test_extracted_document_repr_is_redacted() -> None:
    from core.intake.models import DocumentSegment, ExtractedDocument

    document = ExtractedDocument(
        file_type=FileType.TXT,
        byte_size=99,
        segments=[DocumentSegment(text=CANARY, locator="line 1")],
    )
    assert CANARY not in repr(document)
    assert CANARY not in repr(document.segments[0])
    assert "segments=1" in repr(document)


# -- 5. exceptions and tracebacks -----------------------------------------

def test_a_library_exception_carrying_the_canary_is_not_propagated(monkeypatch) -> None:
    """The realistic leak: a parser error message quoting the text that confused it."""
    import adapters.intake.text as text_module

    def explode(_text):
        raise ValueError(f"cannot parse near {CANARY}")

    monkeypatch.setattr(text_module, "_txt_segments", explode)

    with IntakeSession(PROJECT) as session:
        result = session.ingest(
            bytearray(BUILDERS["TXT"]()),
            file_type=FileType.TXT,
            source_category=SourceCategory.COMPANY_DATA,
        )

    assert result.source.error_code == IntakeErrorCode.EXTRACT_FAILED
    assert CANARY not in str(as_dict(result.source))


def test_the_converted_error_has_no_canary_in_message_or_traceback(monkeypatch) -> None:
    """``raise ... from None`` matters: a chained cause prints the original message."""
    import adapters.intake.text as text_module

    def explode(_text):
        raise ValueError(f"cannot parse near {CANARY}")

    monkeypatch.setattr(text_module, "_txt_segments", explode)

    from adapters.intake.text import TextParser

    try:
        TextParser().parse(BUILDERS["TXT"](), file_type=FileType.TXT)
    except IntakeError as error:
        assert CANARY not in str(error)
        assert CANARY not in repr(error)
        assert CANARY not in traceback.format_exc()
        assert error.exception_type == "ValueError"
        assert CANARY not in str(safe_error_fields(error, source_id="src_x"))
    else:
        raise AssertionError("the parser guard did not convert the exception")


def test_decode_failure_does_not_quote_the_bytes() -> None:
    """``UnicodeDecodeError`` prints the offending bytes, which are document content."""
    payload = CANARY.encode("utf-8") + b"\xff\xfe\x81\xff" * 8

    with IntakeSession(PROJECT) as session:
        result = session.ingest(
            bytearray(payload),
            file_type=FileType.TXT,
            source_category=SourceCategory.COMPANY_DATA,
        )

    assert result.source.error_code == IntakeErrorCode.TEXT_DECODE_FAILED
    assert CANARY not in str(as_dict(result.source))

    try:
        from core.intake import decode_text

        decode_text(payload)
    except IntakeError as error:
        assert CANARY not in str(error)
        assert CANARY not in traceback.format_exc()


# -- 6. serialised metadata ------------------------------------------------

def test_canary_never_appears_in_serialised_source_metadata(ingested) -> None:
    _, result = ingested
    assert CANARY not in str(as_dict(result.source))


def test_source_metadata_still_has_no_text_carrying_field(ingested) -> None:
    """A field that could hold document content must not appear, whatever its name."""
    _, result = ingested
    for key, value in as_dict(result.source).items():
        if isinstance(value, str):
            assert len(value) <= 120, f"{key} is long enough to be document text"
