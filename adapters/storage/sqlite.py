# -*- coding: utf-8 -*-
"""SQLite storage — the first adapter in this repository that actually keeps anything.

``null`` discards and ``memory`` forgets at exit. This one survives a restart, which is what
Phase 8 needs and also what makes it the adapter that has to be most careful: a bug here does
not lose data, it *keeps* something that should never have been written down.

**One table, and the domain schema is not restated in it.** Every entity is stored as the
JSON that ``core.models.as_dict`` already produces, under the few columns a lookup actually
needs. Modelling nineteen ``AnalysisClaim`` fields as columns would make this file a second
definition of the data model — one that drifts the first time somebody adds a field to
``core/models.py`` and forgets there is a copy down here. ``schemas/*.schema.json`` and
``docs/data-model.md`` are the two mirrors of that model and ``tests/test_schemas.py`` already
keeps them in step; a third mirror with no such test is a liability, not a feature.

**The semantics are copied from ``MemoryStorage``, not chosen.** Saving the same finding twice
appends twice, because that is what the in-memory adapter does and two adapters that disagree
about that make the pipeline's behaviour depend on which one is wired. Only ``save_project``
replaces. Reads come back in insertion order for the same reason.

**What is not here.** ``EvidenceCandidate`` has no method and no column: it carries document
text, and ``docs/privacy.md`` section 3 puts that on the permanent-storage prohibition list.
Neither has application state — training sessions, participants, HTTP sessions and background
runs belong to the application layer, in its own tables even if it shares this file. And
there is no ``clear()``: ``MemoryStorage`` has one because ephemeral mode ends a session by
dropping everything, and a one-call wipe on a *persistence* adapter is a footgun wearing a
familiar name.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from pathlib import Path
from typing import Any, Callable, Optional

from core.errors import ProviderError
from core.models import (
    ClientAnalysis,
    ClientCandidate,
    KeyIssue,
    PricingResult,
    Project,
    ProposalStrategy,
    ResearchFinding,
    SourceMetadata,
    SWOTIssue,
    as_dict,
    from_dict,
)

#: Bumped when the table layout changes in a way an older adapter cannot read. There is no
#: migration framework here — the point of the version is that a mismatch stops rather than
#: being read as though it were understood.
SCHEMA_VERSION = 1

#: ``entity_type`` values. Stable strings, not ``cls.__name__``: renaming a dataclass must not
#: silently orphan every row already written under the old name.
ENTITY_TYPES: dict[str, type] = {
    "project": Project,
    "source_metadata": SourceMetadata,
    "research_finding": ResearchFinding,
    "swot_issue": SWOTIssue,
    "key_issue": KeyIssue,
    "client_candidate": ClientCandidate,
    "client_analysis": ClientAnalysis,
    "proposal_strategy": ProposalStrategy,
    "pricing_result": PricingResult,
}

#: ``row_id`` is what preserves insertion order, which is the ordering ``MemoryStorage``
#: happens to have and therefore the ordering both adapters must agree on.
#:
#: There is deliberately no ``created_at`` or ``updated_at`` column. Every entity already
#: carries ``created_at`` in its payload; a second copy in the table would be a second answer
#: to the same question, and no read in ``StorageProvider`` asks for it.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS harness_entity (
    row_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type  TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    project_id   TEXT NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_harness_entity_list
    ON harness_entity (entity_type, project_id, row_id);
CREATE INDEX IF NOT EXISTS ix_harness_entity_identity
    ON harness_entity (entity_type, entity_id);
"""


class SQLiteStorageError(ProviderError):
    """A storage operation failed, described without describing what was in it.

    Defined here rather than in ``core/errors.py`` because it is an adapter's concern and the
    core has no business knowing that one of its adapters speaks SQL.

    ``sqlite3`` error messages quote the statement and sometimes the values in it — a column
    name, a constraint, the row that violated it. Every one of those can carry a client's
    data, so the original message is discarded and what remains is a stable code plus the
    originating exception's *class name*. Same rule, same reason, as ``IntakeError``.
    """

    code = "STORAGE_FAILED"

    def __init__(self, code: str, *, sqlite_error_type: Optional[str] = None) -> None:
        self.sqlite_error_type = sqlite_error_type
        super().__init__(code, code=code)

    def __repr__(self) -> str:
        return (
            f"SQLiteStorageError(code={self.code!r}, "
            f"sqlite_error_type={self.sqlite_error_type!r})"
        )


class SQLiteStorage:
    """File-backed storage for the nine core entities. Implements ``StorageProvider``.

    The database path is **supplied by the caller** and has no default. Choosing where a file
    containing a client's analysis lives is a deployment decision, and an adapter that picks
    the home directory, the working directory or a temp directory has made it for them.

    Constructing an instance creates and initialises the file. Importing this module does
    not: nothing runs at import time, which is a property
    ``tests/test_adapters.py`` checks because the harness's own intake canary watches the
    system temp directory and a stray file there fails it.

    A connection is opened per operation and closed again. It costs a file open per call and
    buys thread-safety by construction — the application layer runs Bootstrap work on a
    worker thread while the request thread polls, and a shared ``sqlite3`` connection across
    those two is the classic way to get ``ProgrammingError`` in production and never in tests.
    """

    name = "sqlite"

    def __init__(self, path: str | Path, *, timeout: float = 5.0) -> None:
        self.path = Path(path)
        self._timeout = timeout
        #: Serialises writes from this instance. SQLite handles cross-process locking itself;
        #: this only removes the needless contention of one process fighting itself.
        self._write_lock = threading.Lock()

        if not self.path.parent.is_dir():
            # Not created here. The caller owns the filesystem and a storage adapter that
            # quietly makes directories is one that writes where nobody looked.
            raise SQLiteStorageError("STORAGE_PATH_UNAVAILABLE")

        self._initialise()

    # -- lifecycle ---------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self.path, timeout=self._timeout)
        except sqlite3.Error as exc:
            raise SQLiteStorageError(
                "STORAGE_UNAVAILABLE", sqlite_error_type=type(exc).__name__
            ) from None
        connection.row_factory = sqlite3.Row
        return connection

    def _initialise(self) -> None:
        """Create the schema, or refuse a database this adapter does not understand."""
        with self._guard("STORAGE_INIT_FAILED"), closing(self._connect()) as connection:
            # WAL lets the polling reader see committed rows while a background write is in
            # flight. It creates -wal and -shm files beside the database: a normal
            # consequence of *using* the adapter, never of importing it.
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA foreign_keys=ON")

            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            existing = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='harness_entity'"
            ).fetchone()

            if version == SCHEMA_VERSION:
                return
            if version == 0 and existing is None:
                connection.executescript(_SCHEMA)
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
                connection.commit()
                return

            # Either a newer adapter wrote it, or an older one did before versions existed.
            # Reading it anyway would mean guessing at a layout, and a wrong guess here is
            # silently mangled analysis rather than a crash.
            raise SQLiteStorageError("STORAGE_SCHEMA_VERSION_UNSUPPORTED")

    def schema_version(self) -> int:
        """The version recorded in the file. For diagnostics and tests."""
        with self._guard("STORAGE_READ_FAILED"), closing(self._connect()) as connection:
            return int(connection.execute("PRAGMA user_version").fetchone()[0])

    def journal_mode(self) -> str:
        """The journal mode actually in force. WAL is requested; this reports what happened."""
        with self._guard("STORAGE_READ_FAILED"), closing(self._connect()) as connection:
            return str(connection.execute("PRAGMA journal_mode").fetchone()[0])

    # -- error boundary ----------------------------------------------------

    class _Guard:
        """Turns any ``sqlite3.Error`` into a stable code, discarding the message."""

        def __init__(self, code: str) -> None:
            self._code = code

        def __enter__(self) -> "SQLiteStorage._Guard":
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            if exc_type is not None and issubclass(exc_type, sqlite3.Error):
                raise SQLiteStorageError(
                    self._code, sqlite_error_type=exc_type.__name__
                ) from None
            return False

    def _guard(self, code: str) -> "SQLiteStorage._Guard":
        return SQLiteStorage._Guard(code)

    # -- the two primitives every method below is built from ---------------

    def _append(self, entity_type: str, entity_id: str, project_id: str, entity: Any) -> str:
        """Insert a row. Appends, exactly as ``MemoryStorage`` does — no upsert."""
        payload = self._encode(entity)
        with self._write_lock, self._guard("STORAGE_WRITE_FAILED"), closing(self._connect()) as conn:
            # `with conn` is the transaction — committed on success, rolled back on any
            # exception — and `closing` is what actually releases the file handle. They are
            # two different things, and using only the first leaks handles and leaves the
            # WAL sidecar locked.
            with conn:
                conn.execute(
                    "INSERT INTO harness_entity"
                    " (entity_type, entity_id, project_id, payload_json)"
                    " VALUES (?, ?, ?, ?)",
                    (entity_type, entity_id, project_id, payload),
                )
        return entity_id

    def _replace(self, entity_type: str, entity_id: str, project_id: str, entity: Any) -> str:
        """Delete-then-insert in one transaction. Only ``save_project`` has this semantics."""
        payload = self._encode(entity)
        with self._write_lock, self._guard("STORAGE_WRITE_FAILED"), closing(self._connect()) as conn:
            # Both statements inside one transaction: a delete that lands without its insert
            # would lose the project entirely.
            with conn:
                conn.execute(
                    "DELETE FROM harness_entity WHERE entity_type = ? AND entity_id = ?",
                    (entity_type, entity_id),
                )
                conn.execute(
                    "INSERT INTO harness_entity"
                    " (entity_type, entity_id, project_id, payload_json)"
                    " VALUES (?, ?, ?, ?)",
                    (entity_type, entity_id, project_id, payload),
                )
        return entity_id

    def _list(self, entity_type: str, project_id: str) -> list:
        """Every row of one type for one project, in insertion order."""
        with self._guard("STORAGE_READ_FAILED"), closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT payload_json FROM harness_entity"
                " WHERE entity_type = ? AND project_id = ? ORDER BY row_id",
                (entity_type, project_id),
            ).fetchall()
        return [self._decode(entity_type, row["payload_json"]) for row in rows]

    def _one(self, entity_type: str, entity_id: str) -> Optional[Any]:
        with self._guard("STORAGE_READ_FAILED"), closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT payload_json FROM harness_entity"
                " WHERE entity_type = ? AND entity_id = ? ORDER BY row_id DESC LIMIT 1",
                (entity_type, entity_id),
            ).fetchone()
        return None if row is None else self._decode(entity_type, row["payload_json"])

    # -- serialisation: the core's own, and nothing else -------------------

    @staticmethod
    def _encode(entity: Any) -> str:
        """``as_dict`` then JSON. No bespoke encoder, no manual enum handling.

        ``sort_keys`` so the same entity produces the same bytes — it makes a stored row
        diffable and a test able to compare files rather than parsed objects.
        """
        return json.dumps(as_dict(entity), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _decode(entity_type: str, payload: str) -> Any:
        """``from_dict``, which is strict: an unknown field raises rather than being dropped.

        That strictness is wanted. A stored row that no longer matches the entity is schema
        drift somebody needs to see, and half-loading it would hide exactly the case this
        adapter exists to survive.
        """
        try:
            return from_dict(ENTITY_TYPES[entity_type], json.loads(payload))
        except (ValueError, TypeError, KeyError) as exc:
            raise SQLiteStorageError(
                "STORAGE_PAYLOAD_UNREADABLE", sqlite_error_type=type(exc).__name__
            ) from None

    # -- project -----------------------------------------------------------

    def save_project(self, project: Project) -> str:
        return self._replace("project", project.project_id, project.project_id, project)

    def get_project(self, project_id: str) -> Optional[Project]:
        return self._one("project", project_id)

    # -- sources -----------------------------------------------------------

    def save_source_metadata(self, source: SourceMetadata) -> str:
        return self._append(
            "source_metadata", source.source_id, source.project_id, source
        )

    def get_source_metadata(self, project_id: str) -> list[SourceMetadata]:
        return self._list("source_metadata", project_id)

    # -- engine 1 ----------------------------------------------------------

    def save_finding(self, finding: ResearchFinding) -> str:
        return self._append(
            "research_finding", finding.finding_id, finding.project_id, finding
        )

    def get_findings(self, project_id: str) -> list[ResearchFinding]:
        return self._list("research_finding", project_id)

    def save_swot_issue(self, issue: SWOTIssue) -> str:
        return self._append("swot_issue", issue.issue_id, issue.project_id, issue)

    def get_swot_issues(self, project_id: str) -> list[SWOTIssue]:
        return self._list("swot_issue", project_id)

    def save_key_issue(self, issue: KeyIssue) -> str:
        return self._append("key_issue", issue.key_issue_id, issue.project_id, issue)

    def get_key_issues(self, project_id: str) -> list[KeyIssue]:
        return self._list("key_issue", project_id)

    # -- engine 2 ----------------------------------------------------------

    def save_client(self, client: ClientCandidate) -> str:
        return self._append(
            "client_candidate", client.client_id, client.project_id, client
        )

    def get_clients(self, project_id: str) -> list[ClientCandidate]:
        return self._list("client_candidate", project_id)

    def save_client_analysis(self, analysis: ClientAnalysis) -> str:
        return self._append(
            "client_analysis", analysis.analysis_id, analysis.project_id, analysis
        )

    def get_client_analyses(self, project_id: str) -> list[ClientAnalysis]:
        return self._list("client_analysis", project_id)

    def save_proposal_strategy(self, strategy: ProposalStrategy) -> str:
        return self._append(
            "proposal_strategy", strategy.strategy_id, strategy.project_id, strategy
        )

    def get_proposal_strategies(self, project_id: str) -> list[ProposalStrategy]:
        return self._list("proposal_strategy", project_id)

    # -- pricing hand-off --------------------------------------------------

    def save_pricing_result(self, result: PricingResult) -> str:
        return self._append(
            "pricing_result", result.pricing_result_id, result.project_id, result
        )

    def get_pricing_results(self, project_id: str) -> list[PricingResult]:
        return self._list("pricing_result", project_id)
