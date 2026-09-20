# -*- coding: utf-8 -*-
"""SQLite for **application** state. The harness's nine entities are not in here.

``docs/product-spec.md`` splits persistence ownership: the harness's ``StorageProvider`` keeps
Finding, SWOT, KeyIssue, ClientCandidate and the rest; the application keeps sessions, runs,
participants and reveal state. Even when the two share one file they do not share tables, and
this module is the application half. It imports nothing from ``core``.

What is deliberately absent: any column that could hold an uploaded document, its text, its
filename, or anything a person typed about themselves. The proof's upload path never reaches
this module with bytes in hand.
"""
from __future__ import annotations

import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from proof_app.runs import BootstrapStatus, reading_for

SCHEMA = """
CREATE TABLE IF NOT EXISTS proof_run (
    run_id          TEXT PRIMARY KEY,
    status          TEXT NOT NULL,
    error_code      TEXT,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    finding_count   INTEGER NOT NULL DEFAULT 0,
    llm_calls       INTEGER NOT NULL DEFAULT 0,
    created_at      REAL NOT NULL,
    updated_at      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS proof_session (
    session_id TEXT PRIMARY KEY,
    created_at REAL NOT NULL
);
"""


class ProofStore:
    """One SQLite file, opened per operation.

    A connection per call rather than one shared connection, because the runner hands work to
    a thread and ``sqlite3`` connections are not safe to share across threads by default.
    Cheap enough for a proof, and it removes a whole class of "works until it doesn't".
    """

    def __init__(self, db_path: Path, *, process_started_at: Optional[float] = None) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        #: Rows left RUNNING_* before this instant belong to a process that is gone.
        self.process_started_at = process_started_at if process_started_at is not None else time.time()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # -- sessions ----------------------------------------------------------
    def ensure_session(self, session_id: str) -> str:
        """Record an opaque session id. Nothing about the person is stored beside it."""
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO proof_session (session_id, created_at) VALUES (?, ?)",
                (session_id, time.time()),
            )
        return session_id

    def session_count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM proof_session").fetchone()[0])

    # -- runs --------------------------------------------------------------
    def create_run(self) -> str:
        run_id = f"run_{uuid.uuid4().hex}"
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO proof_run (run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?)",
                (run_id, BootstrapStatus.NOT_STARTED.value, now, now),
            )
        return run_id

    def set_status(
        self,
        run_id: str,
        status: BootstrapStatus,
        *,
        error_code: Optional[str] = None,
        counts: Optional[dict] = None,
    ) -> None:
        counts = counts or {}
        with self._connect() as conn:
            conn.execute(
                """UPDATE proof_run
                      SET status = ?, error_code = ?, updated_at = ?,
                          candidate_count = COALESCE(?, candidate_count),
                          finding_count   = COALESCE(?, finding_count),
                          llm_calls       = COALESCE(?, llm_calls)
                    WHERE run_id = ?""",
                (
                    status.value,
                    error_code,
                    time.time(),
                    counts.get("candidate_count"),
                    counts.get("finding_count"),
                    counts.get("llm_calls"),
                    run_id,
                ),
            )

    def get_run(self, run_id: str) -> Optional[dict]:
        """The stored row, with its status **read** rather than echoed.

        ``reading_for`` turns a stale ``RUNNING_*`` into ``INTERRUPTED_REUPLOAD_REQUIRED``
        here, at read time. The stored value is left alone — see ``runs.reading_for``.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM proof_run WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        stored = BootstrapStatus(row["status"])
        return {
            "run_id": row["run_id"],
            "status": reading_for(
                stored,
                process_started_at=self.process_started_at,
                row_updated_at=row["updated_at"],
            ).value,
            "stored_status": stored.value,
            "error_code": row["error_code"],
            "candidate_count": row["candidate_count"],
            "finding_count": row["finding_count"],
            "llm_calls": row["llm_calls"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def column_names(self) -> dict[str, list[str]]:
        """Used by the privacy test to assert no column can hold a document or a person."""
        with self._connect() as conn:
            return {
                table: [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
                for table in ("proof_run", "proof_session")
            }
