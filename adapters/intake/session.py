# -*- coding: utf-8 -*-
"""One intake session: request lifecycle, batch limits, buffer release.

Deliberately small. All eight supported formats parse from memory, so this implementation
creates no temporary file, and there is therefore no temp registry, no ``atexit`` hook and no
cleanup machinery to get wrong. When a parser that genuinely needs a file on disk arrives, disk
cleanup gets added then — not in anticipation of it.

What the session does:

* applies the per-file and per-batch limits from :class:`~core.intake.policy.IntakePolicy`
* checks the declared type against the leading bytes before handing anything to a parser
* releases its references to the incoming buffers, overwriting the ones it can
* turns any failure into a ``SourceMetadata`` with a code, so one bad file does not end a batch

What it does not do: persist anything. The caller decides whether ``result.source`` goes to a
``StorageProvider``. ``result.candidates`` never do.
"""
from __future__ import annotations

from types import TracebackType
from typing import Optional, Union

from adapters.intake.registry import ParserRegistry
from core.errors import IntakeError, IntakeErrorCode
from core.intake.extract import candidates_from, source_metadata_from
from core.intake.models import ExtractedDocument, IntakeResult
from core.intake.policy import (
    DEFAULT_POLICY,
    MAGIC_PREFIX_BYTES,
    IntakePolicy,
    check_declared_type,
    normalize_display_label,
)
from core.models import (
    FileType,
    ProcessingStatus,
    SourceCategory,
    SourceMetadata,
    SourceOrigin,
    new_id,
)

Payload = Union[bytes, bytearray]


def release_buffer(buffer: Payload) -> None:
    """Best-effort clearing of an incoming buffer.

    A ``bytearray`` is overwritten in place; ``bytes`` is immutable and can only be dropped.

    This is **not** a guarantee that the content is gone from memory. CPython may have copied
    the data during decoding, a parsing library may hold its own copy, and the allocator may
    keep freed pages around. What this harness does hold to is narrower and checkable: the
    upload is never persisted, this implementation creates no temporary file, and the content
    never reaches a log. What third-party libraries, the runtime or the operating system do
    internally is outside its control. See ``docs/privacy.md``.
    """
    if isinstance(buffer, bytearray):
        buffer[:] = bytes(len(buffer))


class IntakeSession:
    """Ingests documents for one project, within one request."""

    def __init__(
        self,
        project_id: str,
        *,
        policy: IntakePolicy = DEFAULT_POLICY,
        registry: Optional[ParserRegistry] = None,
    ) -> None:
        self.project_id = project_id
        self.policy = policy
        self.registry = registry if registry is not None else ParserRegistry(policy=policy)
        self._batch_bytes = 0
        self._buffers: list[Payload] = []
        self._closed = False

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self) -> "IntakeSession":
        return self

    def __exit__(
        self,
        exc_type: Optional[type[BaseException]],
        exc: Optional[BaseException],
        tb: Optional[TracebackType],
    ) -> None:
        self.close()

    def close(self) -> None:
        """Release every buffer handed to this session. Safe to call more than once."""
        for buffer in self._buffers:
            release_buffer(buffer)
        self._buffers.clear()
        self._closed = True

    @property
    def batch_bytes(self) -> int:
        return self._batch_bytes

    # -- ingestion ---------------------------------------------------------
    def ingest(
        self,
        data: Payload,
        *,
        file_type: FileType,
        source_category: SourceCategory,
        display_label: Optional[str] = None,
        source_date: Optional[str] = None,
    ) -> IntakeResult:
        """Turn one document into a source record and its evidence candidates.

        Never raises for a bad document: a failure comes back as a ``FAILED`` source carrying
        an ``error_code``, so a batch continues. Programming errors (a closed session) still
        raise.

        There is no ``filename`` parameter, and that is the point — the original name cannot
        enter the system because there is nowhere to put it. ``display_label`` is a separate
        thing: text the person typed, for their own benefit.
        """
        if self._closed:
            raise RuntimeError("IntakeSession is closed")

        self._buffers.append(data)
        size = len(data)
        source_id = new_id("src")

        try:
            self._check_limits(size)
            check_declared_type(file_type, bytes(data[:MAGIC_PREFIX_BYTES]))

            parser = self.registry.for_type(file_type)
            document = parser.parse(bytes(data), file_type=file_type)

            if not document.segments:
                raise IntakeError(IntakeErrorCode.EMPTY_DOCUMENT, parser=parser.name)

            self._batch_bytes += size
            return self._succeed(
                document,
                source_id=source_id,
                source_category=source_category,
                display_label=display_label,
                source_date=source_date,
            )

        except IntakeError as error:
            self._batch_bytes += size
            return self._fail(
                error,
                source_id=source_id,
                file_type=file_type,
                size=size,
                source_category=source_category,
                display_label=display_label,
                source_date=source_date,
            )
        finally:
            release_buffer(data)

    # -- internals ---------------------------------------------------------
    def _check_limits(self, size: int) -> None:
        if size > self.policy.max_file_bytes:
            raise IntakeError(IntakeErrorCode.FILE_TOO_LARGE)
        if self._batch_bytes + size > self.policy.max_batch_bytes:
            raise IntakeError(IntakeErrorCode.BATCH_TOO_LARGE)

    def _succeed(
        self,
        document: ExtractedDocument,
        *,
        source_id: str,
        source_category: SourceCategory,
        display_label: Optional[str],
        source_date: Optional[str],
    ) -> IntakeResult:
        source = source_metadata_from(
            document,
            project_id=self.project_id,
            source_category=source_category,
            source_id=source_id,
            display_label=display_label,
            source_date=source_date,
            policy=self.policy,
            processing_status=ProcessingStatus.EXTRACTED,
        )
        candidates = candidates_from(
            document, project_id=self.project_id, source_id=source.source_id
        )
        # The buffer is released in the caller's finally block, so by the time this record is
        # handed back the original no longer exists anywhere in this process.
        source.processing_status = ProcessingStatus.PURGED
        return IntakeResult(source=source, candidates=candidates)

    def _fail(
        self,
        error: IntakeError,
        *,
        source_id: str,
        file_type: FileType,
        size: int,
        source_category: SourceCategory,
        display_label: Optional[str],
        source_date: Optional[str],
    ) -> IntakeResult:
        source = SourceMetadata(
            project_id=self.project_id,
            source_origin=SourceOrigin.UPLOADED_FILE,
            source_category=source_category,
            file_type=file_type,
            file_size=size,
            source_id=source_id,
            display_label=normalize_display_label(display_label, self.policy),
            source_date=source_date,
            processing_status=ProcessingStatus.FAILED,
            error_code=error.code,
        )
        return IntakeResult(source=source, candidates=[])
